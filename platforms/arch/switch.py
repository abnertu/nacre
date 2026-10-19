"""arch-switch: converge Arch-native policy, then leave Home Manager to its stage.

Package operations run here because yay must run as the login user; the
privileged adapters own every file, unit and runtime change. package.nix
supplies every path and declared value as one JSON config; tests supply an
isolated filesystem and fake native commands the same way.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import NoReturn, TypedDict

from nix_adapter import Progress
from nix_adapter.plan import STYLES

USAGE = "usage: arch-switch [--check | --plan | --update | --purge] [--verbose]"
# An optional adapter exits 20 only while its preparation has never completed.
NOT_READY = 20


class Adapter(TypedDict):
    adapter: str
    manifest: str


class Extension(TypedDict):
    """A machine-provided optional adapter: platforms/arch/module.nix."""

    name: str
    label: str
    requires: list[str]
    notReady: str


class Config(TypedDict):
    fsRoot: str
    nativeBin: str
    adapterPython: str
    adapters: dict[str, Adapter]
    extensions: list[Extension]
    lizardbyteConf: str
    curl: str
    tar: str
    expectedUser: str
    pacman: list[str]
    lizardbyte: list[str]
    aur: list[str]
    hold: list[str]
    userServices: list[str]


class Failure(Exception):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


class Switch:
    def __init__(self, config: Config, verbose: bool, progress: Progress):
        self.config = config
        self.verbose = verbose
        self.progress = progress
        self.root = Path(config["fsRoot"] or "/")
        self.bin = Path(config["nativeBin"])
        self.kernel = os.uname().release
        self.work = Path(tempfile.mkdtemp(prefix="arch-switch-"))
        # Plan markers keep the adapters' colors on an interactive terminal.
        self.color = (
            not verbose
            and sys.stdout.isatty()
            and sys.stderr.isatty()
            and os.environ.get("TERM", "dumb") != "dumb"
            and "NO_COLOR" not in os.environ
            and not os.environ.get("CI")
        )

    # Native commands own the terminal while they run.
    def native(
        self, command: str, *args: str, capture: bool = False, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        with self.progress.external_output():
            result = subprocess.run(
                [str(self.bin / command), *args],
                text=True,
                capture_output=capture,
                check=False,
            )
        if check and result.returncode != 0:
            raise Failure("", result.returncode)
        return result

    def root_command(self, command: str, *args: str) -> None:
        self.native("sudo", str(self.bin / command), *args)

    def say(self, line: str, *, error: bool = False) -> None:
        with self.progress.external_output():
            print(line, file=sys.stderr if error else sys.stdout, flush=True)

    def plan_line(self, kind: str, text: str) -> None:
        line = f"{kind} {text}"
        self.say(f"\033[{STYLES[kind]}m{line}\033[0m" if self.color else line)

    def skip(self, name: str, reason: str) -> None:
        line = f"SKIP optional module {name}: {reason}"
        self.say(f"\033[1;33m{line}\033[0m" if self.color else line, error=True)

    def report(self, title: str, details: str) -> None:
        if details.strip():
            heading = f"\033[1;31m{title}:\033[0m" if self.color else f"{title}:"
            self.say(heading + "\n" + details.rstrip("\n"), error=True)

    def adapter(self, name: str, phase: str) -> int:
        entry = self.config["adapters"][name]
        args = [
            self.config["adapterPython"],
            entry["adapter"],
            entry["manifest"],
            phase,
        ]
        if self.verbose:
            args.append("--verbose")
        if phase == "plan" and self.color:
            args.append("--color")
        return self.native("sudo", *args, check=False).returncode

    def require(self, name: str, phase: str) -> None:
        status = self.adapter(name, phase)
        if status != 0:
            raise Failure("", status)

    def optional_preflight(self, name: str, label: str, reason: str) -> bool:
        status = self.adapter(name, "preflight")
        if status == NOT_READY:
            self.skip(label, reason)
            return False
        if status != 0:
            raise Failure("", status)
        return True

    def optional_converge(self, name: str, description: str) -> None:
        status = self.adapter(name, "converge")
        if status == NOT_READY:
            raise Failure(f"{description} changed after preflight; deployment stopped")
        if status != 0:
            raise Failure("", status)

    def extensions_preflight(self, ready: dict[str, bool]) -> list[str]:
        """Preflight each extension whose requirements are ready; return the ready ones."""
        prepared: list[str] = []
        for extension in self.config["extensions"]:
            missing = [name for name in extension["requires"] if not ready[name]]
            if missing:
                self.skip(extension["label"], f"{', '.join(missing)} is not ready")
            elif self.optional_preflight(
                extension["name"], extension["label"], extension["notReady"]
            ):
                prepared.append(extension["name"])
        return prepared

    def check_kernel(self) -> None:
        if not (self.root / "usr/lib/modules" / self.kernel).is_dir():
            raise Failure(
                f"kernel modules do not match running kernel {self.kernel}; "
                "reboot, then rerun the deployment",
                75,
            )

    def installed(self) -> set[str]:
        # One query for every installed name, instead of one per package.
        return set(
            self.native("pacman", "--query", "--quiet", capture=True).stdout.split()
        )

    def missing_packages(self) -> list[str]:
        c = self.config
        installed = self.installed()
        return [
            package
            for package in (*c["pacman"], *c["lizardbyte"], *c["aur"])
            if package not in installed
        ]

    def held_upgrade(self, names: list[str]) -> list[str]:
        """Options and targets for an upgrade that keeps held packages.

        Naming a target overrides --ignore, so installed held packages are left
        out of the targets; missing ones still install.
        """
        hold = self.config["hold"]
        if not hold:
            return ["--", *names]
        held = set(hold) & self.installed()
        targets = [name for name in names if name.split("/")[-1] not in held]
        return ["--ignore", ",".join(hold), "--", *targets]

    def require_multilib(self) -> None:
        for package in self.config["pacman"]:
            if package.startswith("lib32-"):
                multilib = self.native(
                    "pacman-conf",
                    "--repo",
                    "multilib",
                    "Server",
                    capture=True,
                    check=False,
                )
                if multilib.returncode != 0:
                    raise Failure(
                        f"declared package {package} requires the [multilib] "
                        "repository in /etc/pacman.conf"
                    )
                return

    def resolve_inventory(self) -> None:
        c = self.config
        self.require_multilib()
        # Simulate the transaction update performs: a full upgrade with the
        # inventory. Resolving it alone would fail on pending upgrades of deps.
        result = self.native(
            "pacman",
            "--sync",
            "--sysupgrade",
            "--print",
            "--needed",
            *self.held_upgrade(c["pacman"]),
            capture=True,
            check=False,
        )
        if result.returncode != 0:
            # pacman prints the conflicting dependencies on stdout, beside URLs.
            conflicts = [
                line for line in result.stdout.splitlines() if "://" not in line
            ]
            self.report(
                "Package resolution error", result.stderr + "\n".join(conflicts)
            )
            raise Failure(
                "Arch package inventory did not resolve; check for package conflicts"
            )
        if c["lizardbyte"]:
            server = self.native(
                "pacman-conf",
                "--config",
                c["lizardbyteConf"],
                "--repo",
                "lizardbyte",
                "Server",
                capture=True,
            ).stdout.strip()
            database = self.work / "lizardbyte.db"
            with self.progress.external_output():
                fetched = subprocess.run(
                    [
                        c["curl"],
                        "--fail",
                        "--location",
                        "--show-error",
                        "--silent",
                        "--connect-timeout",
                        "10",
                        "--max-time",
                        "60",
                        "--output",
                        str(database),
                        f"{server}/lizardbyte.db",
                    ],
                    check=False,
                )
                listing = subprocess.run(
                    [c["tar"], "-tf", str(database)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            if fetched.returncode != 0 or listing.returncode != 0:
                raise Failure("LizardByte repository database could not be read")
            for package in c["lizardbyte"]:
                pattern = re.compile(rf"{re.escape(package)}-[^/]+/desc")
                if not any(
                    pattern.fullmatch(line) for line in listing.stdout.splitlines()
                ):
                    raise Failure(f"LizardByte package did not resolve: {package}")
        if c["aur"]:
            info = self.native(
                "yay", "--sync", "--info", "--", *c["aur"], capture=True, check=False
            )
            if info.returncode != 0:
                self.report("AUR package resolution error", info.stderr)
                raise Failure("AUR package inventory did not resolve")

    @contextlib.contextmanager
    def lock(self) -> Generator[None]:
        """Serialize deployments in the login user's runtime directory.

        The lock file is never removed, so its inode stays the same.
        """
        uid = self.native("id", "-u", capture=True).stdout.strip()
        runtime = self.root / "run/user" / uid
        if not runtime.is_dir() or runtime.is_symlink():
            raise Failure("login runtime directory is unavailable")
        with open(runtime / "nacre-arch.lock", "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Failure("another arch-switch is running", 75) from None
            yield

    def validate_host(self) -> None:
        if not (self.root / "etc/arch-release").exists():
            raise Failure("arch-switch only supports Arch Linux")
        if self.native("id", "-u", capture=True).stdout.strip() == "0":
            raise Failure("run arch-switch as the login user, not root")
        user = self.native("id", "--user", "--name", capture=True).stdout.strip()
        expected = self.config["expectedUser"]
        if user != expected:
            raise Failure(f"arch-switch must run as {expected}, not {user}")
        groups = self.native("id", "-nG", user, capture=True).stdout.split()
        if "wheel" not in groups:
            raise Failure(
                "deployment user is not in required administrator group: wheel"
            )
        # The adapters check their own commands; these are the orchestration's.
        for command in ("id", "sudo", "pacman", "pacman-conf", "yay", "systemctl"):
            if not os.access(self.bin / command, os.X_OK):
                raise Failure(f"required command is missing: {self.bin / command}")

    def user_service_enabled(self, service: str) -> bool:
        return (
            self.native(
                "systemctl", "--user", "is-enabled", "--quiet", service, check=False
            ).returncode
            == 0
        )

    def plan(self) -> None:
        with self.progress.task("Plan Arch changes", total=1) as task:
            for package in self.missing_packages():
                self.plan_line("+", f"package {package} (missing; installed by update)")
            if (self.bin / "checkupdates").exists():
                result = self.native("checkupdates", capture=True, check=False)
                upgrades = (
                    len(result.stdout.splitlines()) if result.returncode == 0 else 0
                )
                if upgrades:
                    self.plan_line(
                        "~",
                        f"{upgrades} repository package upgrades available (installed by update)",
                    )
            if not (self.root / "usr/lib/modules" / self.kernel).is_dir():
                self.plan_line(
                    "!",
                    f"kernel modules do not match running kernel {self.kernel}; reboot first",
                )
            self.require("core", "plan")
            self.require("system", "plan")
            ai_ready = self.optional_preflight(
                "ai",
                "ai",
                "llama.cpp build/model is not prepared; run 'nacre ai prepare'",
            )
            if ai_ready:
                self.require("ai", "plan")
            for name in self.extensions_preflight({"ai": ai_ready}):
                self.require(name, "plan")
            for service in self.config["userServices"]:
                if not self.user_service_enabled(service):
                    self.plan_line("~", f"enable user service {service}")
            task.update(1)

    def check(self) -> None:
        with self.progress.task("Check package inventories", total=1) as task:
            self.resolve_inventory()
            self.say("Arch, LizardByte, and AUR package inventories resolve")
            task.update(1)

    def purge(self) -> None:
        with self.progress.task("Purge managed Arch state", total=1) as task:
            self.native("sudo", "-v")
            # Optional services first, then system drop-ins; core removes pending state.
            self.require("ai", "purge")
            self.require("system", "purge")
            self.require("core", "purge")
            task.update(1)

    def deploy(self, update: bool) -> None:
        c = self.config
        total = 6 if update else 5
        steps = iter(range(1, total + 1))

        def step(label: str) -> contextlib.AbstractContextManager[object]:
            return self.progress.task(f"[{next(steps)}/{total}] {label}")

        with step("Validate Arch host, packages, and kernel"):
            missing = self.missing_packages()
            if missing and not update:
                raise Failure(
                    "declared Arch packages are missing; rerun with --update to install them safely:\n"
                    + "\n".join(f"  {package}" for package in missing),
                    3,
                )
            self.check_kernel()

        # Read-only ownership preflight precedes package and configuration writes.
        with step("Preflight core and optional modules"):
            self.require("core", "preflight")
            self.require("system", "preflight")
            ai_ready = self.optional_preflight(
                "ai",
                "ai",
                "llama.cpp build/model is not prepared; run 'nacre ai prepare'",
            )
            extensions = self.extensions_preflight({"ai": ai_ready})

        self.native("sudo", "-v")
        if update:
            with step("Resolve and update native packages"):
                # Declared repositories first, then one refresh, so resolution
                # and the upgrade both see the databases the transaction uses.
                self.require_multilib()
                self.require("core", "repositories")
                self.root_command("pacman", "--sync", "--refresh")
                self.resolve_inventory()
                self.root_command(
                    "pacman",
                    "--sync",
                    "--sysupgrade",
                    "--needed",
                    "--noconfirm",
                    *self.held_upgrade(
                        [
                            *c["pacman"],
                            *(f"lizardbyte/{name}" for name in c["lizardbyte"]),
                        ]
                    ),
                )
                self.check_kernel()
                aur = self.held_upgrade(c["aur"])
                # Nothing after "--": no AUR package left to install or upgrade.
                if aur[-1] != "--":
                    self.native("yay", "--sync", "--needed", "--noconfirm", *aur)
        else:
            self.require("core", "repositories")

        with step("Converge core files and services"):
            self.require("system", "converge")
            self.require("core", "converge")

        with step("Converge optional modules"):
            if ai_ready:
                self.optional_converge("ai", "AI preparation")
            labels = {e["name"]: e["label"] for e in c["extensions"]}
            for name in extensions:
                self.optional_converge(name, labels[name])

        with step("Finish runtime convergence"):
            self.require("core", "finish")
            # User units belong to the login user's manager: stay unprivileged.
            actions = 0
            for service in c["userServices"]:
                if not self.user_service_enabled(service):
                    self.native("systemctl", "--user", "enable", service)
                    actions += 1
            self.say(
                f"User services converged: 0 files updated, {actions} runtime actions."
            )


def parse(args: list[str]) -> tuple[str, bool]:
    modes = {"--check", "--plan", "--update", "--purge"}
    if "--help" in args:
        print(USAGE)
        raise SystemExit(0)
    if any(arg not in modes | {"--verbose"} for arg in args):
        raise Failure(USAGE, 2)
    chosen = [arg for arg in args if arg in modes]
    if len(chosen) > 1:
        raise Failure(USAGE, 2)
    return (chosen[0].removeprefix("--") if chosen else "deploy"), "--verbose" in args


def main(argv: list[str]) -> int:
    if argv[:1] != ["--config"] or len(argv) < 2:
        print("arch-switch must be started through its package", file=sys.stderr)
        return 2
    config: Config = json.loads(Path(argv[1]).read_text())
    try:
        mode, verbose = parse(argv[2:])
    except Failure as failure:
        print(str(failure), file=sys.stderr)
        return failure.code
    with Progress("arch", verbose=verbose) as progress:
        switch = Switch(config, verbose, progress)
        try:
            switch.validate_host()
            if mode == "plan":
                switch.plan()
            elif mode == "check":
                switch.check()
            else:
                with switch.lock():
                    if mode == "purge":
                        switch.purge()
                    else:
                        switch.deploy(update=mode == "update")
            return 0
        except Failure as failure:
            if str(failure):
                switch.say(str(failure), error=True)
            return failure.code
        except KeyboardInterrupt:
            return 130
        finally:
            for path in switch.work.glob("*"):
                path.unlink()
            switch.work.rmdir()


def entry() -> NoReturn:
    raise SystemExit(main(sys.argv[1:]))


if __name__ == "__main__":
    entry()
