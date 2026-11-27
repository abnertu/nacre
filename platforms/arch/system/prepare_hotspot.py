"""Create the declared NetworkManager AP connection from a typed password.

The password goes from the terminal into a root-only keyfile and never into
a command argument, the output or a log.
"""

from __future__ import annotations

import io
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import termios
import uuid
from pathlib import Path
from types import FrameType
from typing import NoReturn, TextIO, TypedDict, cast

from nix_adapter import Conflict, Files

USAGE = "usage: hotspot-prepare\n  Create the declared hotspot connection; prompts for its password."
CONNECTIONS = "/etc/NetworkManager/system-connections"
HEX_PSK = re.compile(r"[0-9a-fA-F]{64}")


class Hotspot(TypedDict):
    connection: str
    ssid: str
    interface: str
    uplink: str
    band: str
    channel: int
    address: str
    autoconnect: bool
    ipv6: str


class Config(TypedDict):
    hotspot: Hotspot | None
    # Production checks these; isolated tests turn them off or redirect them.
    root: str
    tty: str
    requireRoot: bool
    rootOwnership: bool


class Failure(Exception):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def valid_psk(password: str) -> bool:
    """WPA-PSK: 8 to 63 printable ASCII characters, or 64 hex digits."""
    if HEX_PSK.fullmatch(password):
        return True
    return 8 <= len(password) <= 63 and all(" " <= char <= "~" for char in password)


def keyfile_value(text: str) -> str:
    """`text` in GKeyFile string escaping: a space or backslash survives a read."""
    return text.replace("\\", "\\\\").replace(" ", "\\s")


def keyfile(hotspot: Hotspot, identifier: str, password: str) -> str:
    sections = {
        "connection": {
            "id": hotspot["connection"],
            "uuid": identifier,
            "type": "wifi",
            "interface-name": hotspot["interface"],
            "autoconnect": "false",
        },
        "wifi": {
            "mode": "ap",
            "ssid": hotspot["ssid"],
            "band": hotspot["band"],
            "channel": str(hotspot["channel"]),
        },
        "wifi-security": {
            "key-mgmt": "wpa-psk",
            "proto": "rsn;",
            "pairwise": "ccmp;",
            "group": "ccmp;",
            "psk": password,
        },
        "ipv4": {"method": "shared", "address1": hotspot["address"]},
        "ipv6": {"method": hotspot["ipv6"]},
    }
    return "\n".join(
        f"[{name}]\n"
        + "".join(f"{key}={keyfile_value(value)}\n" for key, value in entries.items())
        for name, entries in sections.items()
    )


def interrupt(_signum: int, _frame: FrameType | None) -> NoReturn:
    raise KeyboardInterrupt


class Prepare:
    def __init__(self, config: Config, hotspot: Hotspot):
        self.config = config
        self.hotspot = hotspot
        identity = (0, 0) if config["rootOwnership"] else (os.getuid(), os.getgid())
        self.files = Files(config["root"], identity)
        self.directory = self.files.path(CONNECTIONS)
        self.path = self.directory / f"{hotspot['connection']}.nmconnection"
        # Whether the keyfile is in place, so an interrupt must remove it.
        self.linked = False

    @staticmethod
    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False
        )

    def connections(self) -> list[tuple[str, str]]:
        """The UUID and name of each NetworkManager connection."""
        result = self.run(
            "nmcli", "--escape", "no", "-t", "-f", "UUID,NAME", "connection", "show"
        )
        if result.returncode != 0:
            raise Failure("cannot list NetworkManager connections")
        pairs = [line.partition(":") for line in result.stdout.splitlines()]
        return [(uid, name) for uid, _, name in pairs if uid]

    def check(self) -> None:
        name = self.hotspot["connection"]
        active = self.run("systemctl", "is-active", "--quiet", "NetworkManager.service")
        if active.returncode:
            raise Failure(
                "NetworkManager is not running; start it, then run this again"
            )
        if any(found == name for _, found in self.connections()):
            raise Failure(f"connection {name} already exists; Nacre adopts it as it is")
        if os.path.lexists(self.path):
            raise Failure(
                f"{self.files.system_name(self.path)} already exists; remove it if "
                f"NetworkManager lists no connection {name}, then run this again"
            )

    def password(self) -> str:
        try:
            descriptor = os.open(self.config["tty"], os.O_RDWR | os.O_NOCTTY)
        except OSError:
            raise Failure("hotspot-prepare needs a terminal for the password") from None
        # As getpass does: a terminal is not seekable, so text mode r+ fails.
        # Bytes that are not UTF-8 become U+FFFD, which the PSK rule refuses.
        with io.TextIOWrapper(
            io.FileIO(descriptor, "w+"), encoding="utf-8", errors="replace"
        ) as terminal:
            if not terminal.isatty():
                raise Failure("hotspot-prepare needs a terminal for the password")
            first = self.ask(terminal, "Hotspot password: ")
            second = self.ask(terminal, "Repeat the password: ")
        if first != second:
            raise Failure("the two passwords differ; nothing was written")
        if not valid_psk(first):
            raise Failure(
                "a WPA password has 8 to 63 printable ASCII characters "
                "or 64 hex digits; nothing was written"
            )
        return first

    @staticmethod
    def ask(terminal: TextIO, prompt: str) -> str:
        descriptor = terminal.fileno()
        saved = termios.tcgetattr(descriptor)
        quiet = termios.tcgetattr(descriptor)
        quiet[3] &= ~termios.ECHO
        terminal.write(prompt)
        terminal.flush()
        try:
            termios.tcsetattr(descriptor, termios.TCSADRAIN, quiet)
            line = terminal.readline()
        finally:
            termios.tcsetattr(descriptor, termios.TCSADRAIN, saved)
            terminal.write("\n")
        if not line:
            raise Failure("no password entered; nothing was written")
        return line.removesuffix("\n")

    def write(self, text: str) -> None:
        """Link a complete 0600 file into place; fail if the path exists."""
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.directory / f".nacre-hotspot-{secrets.token_hex(8)}"
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        try:
            with os.fdopen(descriptor, "w") as stream:
                os.fchmod(stream.fileno(), 0o600)
                os.fchown(stream.fileno(), *self.files.identity)
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, self.path)
                self.linked = True
            except FileExistsError:
                raise Failure(
                    f"{self.files.system_name(self.path)} appeared; nothing was loaded"
                ) from None
        finally:
            temporary.unlink(missing_ok=True)
            Files.sync_dir(self.directory)

    def load(self, identifier: str) -> None:
        name = self.hotspot["connection"]
        loaded = self.run(
            "nmcli", "connection", "load", self.files.system_name(self.path)
        )
        if loaded.returncode != 0:
            self.undo(identifier, "NetworkManager did not load the connection")
        try:
            found = [uid for uid, other in self.connections() if other == name]
        except Failure as failure:
            self.undo(identifier, str(failure))
        if found != [identifier]:
            self.undo(
                identifier,
                f"NetworkManager lists {len(found)} connections named {name}",
            )

    def undo(self, identifier: str, reason: str) -> NoReturn:
        """Remove the keyfile and the profile that it created, then fail.

        Ctrl-C and SIGTERM wait until the cleanup is done.
        """
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
        failed: list[str] = []
        try:
            self.path.unlink(missing_ok=True)
            Files.sync_dir(self.directory)
        except OSError:
            failed.append(f"remove {self.files.system_name(self.path)}")
        listed = self.run("nmcli", "connection", "show", "uuid", identifier)
        if (
            listed.returncode == 0
            and self.run("nmcli", "connection", "delete", "uuid", identifier).returncode
        ):
            failed.append(f"nmcli connection delete uuid {identifier}")
        detail = f"; also failed: {', '.join(failed)}" if failed else ""
        raise Failure(f"{reason}; the keyfile was removed{detail}")

    def create(self) -> None:
        self.check()
        password = self.password()
        identifier = str(uuid.uuid4())
        try:
            self.write(keyfile(self.hotspot, identifier, password))
            self.load(identifier)
        except KeyboardInterrupt:
            if self.linked:
                self.undo(identifier, "interrupted")
            raise
        print(
            f"created hotspot connection {self.hotspot['connection']}; "
            "run `nacre switch` to adopt and start it"
        )


def arguments(argv: list[str]) -> Config | int:
    """The package config, or the exit status of a usage line."""
    if len(argv) < 2 or argv[0] != "--config":
        print("hotspot-prepare must be started through its package", file=sys.stderr)
        return 2
    if argv[2:] == ["--help"]:
        print(USAGE)
        return 0
    if argv[2:]:
        print(USAGE, file=sys.stderr)
        return 2
    return cast(Config, json.loads(Path(argv[1]).read_text()))


def main(argv: list[str]) -> int:
    config = arguments(argv)
    if isinstance(config, int):
        return config
    signal.signal(signal.SIGTERM, interrupt)
    try:
        hotspot = config["hotspot"]
        if hotspot is None:
            raise Failure(
                "this machine declares no networking.hotspot; declare it, then run this again"
            )
        if config["requireRoot"] and os.geteuid() != 0:
            raise Failure("run hotspot-prepare as root: nacre hotspot prepare")
        Prepare(config, hotspot).create()
        return 0
    except Failure as failure:
        print(str(failure), file=sys.stderr)
        return failure.code
    except Conflict as conflict:
        print(str(conflict), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted; nothing was written", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
