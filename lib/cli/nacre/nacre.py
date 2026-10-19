"""nacre: install, plan, switch and inspect a Nacre machine.

Every machine flake exposes its deployment as #deployment, so the command
works with any of them and the home generation that installs it does not
depend on the deployment. Packaging substitutes the version and templates.
"""

from __future__ import annotations

import datetime
import os
import pwd
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

# The machine flake template: flake.nix and configuration.nix.
TEMPLATES = Path("@templates@")
VERSION = "@version@"

USAGE = """\
usage: nacre [--flake PATH] [--override-input INPUT REF]... [--verbose] <command> [arguments]

Setup
  install [OPTIONS]        write configuration.nix for this machine, then plan and update
                           --user NAME --hostname NAME --role minimal|workstation
                           --timezone ZONE --locale LOCALE --yes --force

Deployment
  plan                     show what switch would change; changes nothing
  switch                   converge Arch, then activate the home generation
  update                   switch, also upgrading declared pacman and AUR packages
  purge                    remove managed Arch state; skips Home Manager

Inspection
  status                   checkout, last switch, home generation, pending work
  doctor                   report problems that need attention; changes nothing
  changes [--since TIME]   package changes since the last update (or TIME)
  generations              list home generations
  rollback [GENERATION]    activate an earlier home generation (Arch is not rolled back)

Source
  check                    run every flake check
  build                    build the deployment without activating

Features
  ai prepare [build|model] prepare the pinned llama.cpp build and models
  noctalia ACTION [ARGS]   ACTION: capture, deploy

The checkout is --flake, else $NACRE_FLAKE, else ~/.config/nacre or ~/.config/nix.
--override-input reaches every Nix evaluation, for example to try a local
Nacre checkout: nacre --override-input nacre path:$HOME/codebase/nacre switch
"""

# Tests point this at a temporary root.
ROOT = Path(os.environ.get("NACRE_ROOT") or "/")
PENDING_DIR = ROOT / "var/lib/nix-config/arch"
PACMAN_LOG = ROOT / "var/log/pacman.log"
NAME = re.compile(r"[a-z][a-z0-9_-]*")
PACKAGE_EVENT = re.compile(
    r"\[(?P<when>[^\]]+)\] \[ALPM\] "
    r"(?P<action>installed|upgraded|downgraded|reinstalled|removed) "
    r"(?P<name>\S+) \((?P<versions>[^)]*)\)"
)
# Home Manager and editors leave these beside a file that was in the way.
BACKUP_SUFFIXES = (".bak", ".backup", ".orig", ".old")


class Usage(Exception):
    """Invalid arguments: print usage and exit 2."""


class Refusal(Exception):
    """A precondition failed: print the message and exit 2."""


def state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")


def revision(flake: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(flake), "describe", "--always", "--dirty"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def query(*argv: str) -> str | None:
    """A read-only probe's output, or None when it fails or is not installed."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True, check=False)
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def parse_time(text: str) -> datetime.datetime:
    """An ISO date or time; one without an offset is local time."""
    try:
        when = datetime.datetime.fromisoformat(text)
    except ValueError:
        raise Refusal(f"not an ISO date or time: {text}") from None
    return when if when.tzinfo else when.astimezone()


def find_flake(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    for candidate in (config / "nacre", config / "nix"):
        if (candidate / "flake.nix").is_file():
            return candidate
    return None


class Nacre:
    def __init__(self, flake: Path, verbose: bool, overrides: Sequence[str] = ()):
        self.flake = flake
        self.verbose = verbose
        plain = (
            verbose
            or not sys.stderr.isatty()
            or os.environ.get("TERM", "dumb") == "dumb"
            or "NO_COLOR" in os.environ
            or bool(os.environ.get("CI"))
        )
        # Nix's own progress bar on a terminal, complete raw logs otherwise.
        self.log_format = ["--log-format", "raw" if plain else "bar-with-logs"]
        self.nix_args = [
            "--show-trace",
            "--print-build-logs",
            *(["--verbose"] if verbose else []),
            *overrides,
        ]
        self.overrides = list(overrides)
        self.profile = state_home() / "nix/profiles/home-manager"

    def target(self, attribute: str) -> str:
        return f"{self.flake}#{attribute}"

    def nix(self, command: str, *args: str) -> NoReturn:
        argv = ["nix", *self.log_format, command, *self.nix_args, *args]
        os.execvp(argv[0], argv)

    def nix_root(self, preserve: str, command: str, *args: str) -> NoReturn:
        argv = [
            "sudo",
            f"--preserve-env={preserve}",
            "nix",
            *self.log_format,
            "--extra-experimental-features",
            "nix-command flakes",
            command,
            *self.nix_args,
            *args,
        ]
        os.execvp(argv[0], argv)

    def deploy(self, mode: str) -> int:
        flags = {"plan": ["--plan"], "update": ["--update"], "purge": ["--purge"]}
        deployment_args = flags.get(mode, []) + (["--verbose"] if self.verbose else [])
        built = subprocess.run(
            [
                "nix",
                "build",
                "--no-link",
                "--print-out-paths",
                *self.log_format,
                *self.nix_args,
                self.target("deployment"),
            ],
            stdout=subprocess.PIPE,
            text=True,
            check=False,
        )
        if built.returncode != 0:
            return built.returncode
        artifact = built.stdout.strip()
        if mode == "update":
            # Recorded before running: a stopped update has still upgraded packages.
            record = state_home() / "nacre/updates"
            record.parent.mkdir(parents=True, exist_ok=True)
            with record.open("a") as updates:
                updates.write(f"{now()}\n")
        # The deployment's only program is named after the machine.
        (program,) = Path(artifact, "bin").iterdir()
        status = subprocess.run(
            [str(program), *deployment_args], check=False
        ).returncode
        if status == 0 and mode in ("switch", "update"):
            record = state_home() / "nacre/last-switch"
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_text(f"{now()} {revision(self.flake)} {artifact}\n")
        if mode == "update":
            # An update is when kernels, units and replaced files change; its
            # own exit status stays the result.
            print("\nAfter the update:", file=sys.stderr)
            sys.stderr.flush()
            self.doctor()
        return status

    def generations(self) -> list[int]:
        numbers: list[int] = []
        for link in self.profile.parent.glob(self.profile.name + "-*-link"):
            match = re.fullmatch(r"home-manager-(\d+)-link", link.name)
            if match and link.is_symlink():
                numbers.append(int(match[1]))
        return sorted(numbers)

    def current_generation(self) -> int | None:
        try:
            target = os.readlink(self.profile)
        except OSError:
            return None
        match = re.search(r"home-manager-(\d+)-link$", target)
        return int(match[1]) if match else None

    def link(self, number: int) -> Path:
        return self.profile.parent / f"home-manager-{number}-link"

    def status(self) -> int:
        print(f"Checkout     {self.flake} ({revision(self.flake)})")
        record = state_home() / "nacre/last-switch"
        if record.is_file():
            when, switched, *_ = record.read_text().split()
            print(f"Last switch  {when} from {switched}")
        else:
            print("Last switch  not recorded by nacre")
        current = self.current_generation()
        print(f"Home         generation {current if current is not None else ''}")
        pending = sorted(marker.stem for marker in PENDING_DIR.glob("*.pending"))
        if pending:
            print(f"Pending      {' '.join(pending)} (rerun the interrupted command)")
        else:
            print("Pending      none")
        return 0

    def changes(self, since: str | None) -> int:
        if since is None:
            record = state_home() / "nacre/updates"
            starts = record.read_text().split() if record.is_file() else []
            if not starts:
                raise Refusal("no update recorded by nacre yet; pass --since TIME")
            since = starts[-1]
        start = parse_time(since)
        sections: dict[str, list[tuple[str, str]]] = {}
        try:
            log = PACMAN_LOG.read_text(errors="replace").splitlines()
        except OSError as error:
            raise Refusal(f"cannot read {PACMAN_LOG}: {error.strerror}") from None
        for line in log:
            event = PACKAGE_EVENT.match(line)
            if event is None:
                continue
            try:
                when = datetime.datetime.fromisoformat(event["when"])
            except ValueError:
                continue
            if when >= start:
                sections.setdefault(event["action"], []).append(
                    (event["name"], event["versions"])
                )
        if not sections:
            print(f"No package changes since {start.isoformat()}.")
            return 0
        print(f"Package changes since {start.isoformat()}")
        for action in ("upgraded", "downgraded", "installed", "reinstalled", "removed"):
            entries = sorted(sections.get(action, []))
            if not entries:
                continue
            width = max(len(name) for name, _ in entries)
            print(f"\n{action.capitalize()} ({len(entries)})")
            for name, versions in entries:
                print(f"  {name:<{width}}  {versions}")
        return 0

    def doctor(self) -> int:
        problems = 0

        def report(label: str, problem: str | None, fine: str) -> None:
            nonlocal problems
            problems += problem is not None
            print(f"{'warn' if problem else 'ok':<5} {label:<9} {problem or fine}")

        current = revision(self.flake)
        record = state_home() / "nacre/last-switch"
        switched = record.read_text().split()[1] if record.is_file() else None
        report(
            "switch",
            "no switch recorded by nacre; run nacre switch"
            if switched is None
            else f"checkout is at {current}, last switch was from {switched}; "
            "run nacre switch"
            if switched != current or current.endswith("-dirty")
            else None,
            f"checkout matches the last switch ({current})",
        )
        pending = sorted(marker.stem for marker in PENDING_DIR.glob("*.pending"))
        report(
            "pending",
            f"interrupted: {' '.join(pending)}; rerun the interrupted command"
            if pending
            else None,
            "no interrupted work",
        )
        kernel = query("uname", "-r")
        report(
            "kernel",
            f"running {kernel} has no installed modules; reboot"
            if kernel and not (ROOT / "usr/lib/modules" / kernel).is_dir()
            else None,
            f"running {kernel}",
        )
        failed = [
            *self.units("--failed"),
            *(f"{unit} (user)" for unit in self.units("--user", "--failed")),
        ]
        report(
            "failed",
            f"failed units: {' '.join(failed)}" if failed else None,
            "no failed units",
        )
        idle = self.idle_home_units()
        report(
            "started",
            f"enabled but never started: {' '.join(idle)}; start them or log in again"
            if idle
            else None,
            "every enabled home unit has started",
        )
        snapshot, uncaptured = self.noctalia_drift()
        report(
            "noctalia",
            uncaptured,
            "GUI preferences match the snapshot"
            if snapshot
            else "no Noctalia snapshot in this checkout",
        )
        leftovers = self.backup_leftovers()
        report(
            "leftover",
            f"backups beside managed files: {' '.join(leftovers)}"
            if leftovers
            else None,
            "no backups beside managed files",
        )
        return 1 if problems else 0

    def noctalia_drift(self) -> tuple[bool, str | None]:
        """Whether a snapshot exists, and the uncaptured GUI changes if any."""
        user = pwd.getpwuid(os.getuid()).pw_name
        if not (self.flake / "homes" / user / "noctalia/config.toml").is_file():
            return False, None
        try:
            result = subprocess.run(
                ["noctalia-config", "capture", "--check", "--repo", str(self.flake)],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return True, "noctalia-config is not installed; run nacre switch"
        if result.returncode == 0:
            return True, None
        if result.returncode == 3:
            # "Uncaptured Noctalia changes in: <sections>; run ..."
            return True, result.stdout.strip().replace(
                "Uncaptured Noctalia changes", "uncaptured GUI changes"
            )
        return True, "could not compare; run nacre noctalia capture --dry-run"

    def units(self, *selection: str) -> list[str]:
        listing = query("systemctl", *selection, "--plain", "--no-legend")
        return [line.split()[0] for line in (listing or "").splitlines() if line]

    def idle_home_units(self) -> list[str]:
        """Units the home generation enables under an active target but that
        never started, as when activation adds them to a running session."""
        config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        wanted: list[str] = []
        for wants in sorted((config / "systemd/user").glob("*.target.wants")):
            target = wants.name.removesuffix(".wants")
            if query("systemctl", "--user", "is-active", target) != "active":
                continue
            wanted += sorted(
                link.name
                for link in wants.iterdir()
                if link.is_symlink() and os.readlink(link).startswith("/nix/store/")
            )
        if not wanted:
            return []
        shown = query(
            "systemctl",
            "--user",
            "show",
            "--property=Id,ActiveState,InactiveExitTimestampMonotonic",
            *wanted,
        )
        idle: list[str] = []
        for block in (shown or "").split("\n\n"):
            fields = dict(
                line.split("=", 1) for line in block.splitlines() if "=" in line
            )
            if (
                fields.get("ActiveState") not in ("active", "activating", "reloading")
                and fields.get("InactiveExitTimestampMonotonic") == "0"
            ):
                idle.append(fields.get("Id", "?"))
        return idle

    def backup_leftovers(self) -> list[str]:
        current = self.current_generation()
        if current is None:
            return []
        files = self.link(current) / "home-files"
        found: list[str] = []
        for directory, subdirectories, names in os.walk(files):
            for name in [*names, *subdirectories]:
                managed = Path(directory, name).relative_to(files)
                for suffix in BACKUP_SUFFIXES:
                    if (Path.home() / f"{managed}{suffix}").exists():
                        found.append(f"~/{managed}{suffix}")
        return sorted(found)

    def list_generations(self) -> int:
        current = self.current_generation()
        for number in self.generations():
            when = datetime.datetime.fromtimestamp(
                self.link(number).lstat().st_mtime
            ).strftime("%F %T")
            marker = "*" if number == current else " "
            print(f"{marker} {number:4}  {when}")
        return 0

    def rollback(self, requested: str | None) -> int:
        current = self.current_generation()
        if requested is not None:
            if not requested.isdigit():
                raise Usage
            target: int | None = int(requested)
        else:
            earlier = [n for n in self.generations() if current is None or n < current]
            target = earlier[-1] if earlier else None
        if target is None or not self.link(target).is_symlink():
            wanted = target if target is not None else f"before {current}"
            print(
                f"nacre: no home generation {wanted} to roll back to", file=sys.stderr
            )
            return 1
        print(
            f"Activating home generation {target}; Arch state is unchanged.",
            file=sys.stderr,
        )
        activate = self.link(target).resolve() / "activate"
        os.environ.setdefault("USER", pwd.getpwuid(os.getuid()).pw_name)
        argv = [str(activate)]
        if "--driver-version" in activate.read_text(errors="replace"):
            argv += ["--driver-version", "0"]
        os.execv(argv[0], argv)

    def install(self, args: Sequence[str]) -> int:
        return Installer(self, args).run()


class Installer:
    """Write configuration.nix for this machine, then plan and update."""

    def __init__(self, nacre: Nacre, args: Sequence[str]):
        self.nacre = nacre
        self.root = Path(os.environ.get("NACRE_INSTALL_ROOT") or "/")
        hostname_file = self.root / "etc/hostname"
        self.values = {
            # USER is unset under podman exec, cron and su without a login.
            "user": os.environ.get("USER") or pwd.getpwuid(os.getuid()).pw_name,
            "hostname": (
                hostname_file.read_text().strip()
                if hostname_file.is_file()
                else os.uname().nodename
            ),
            "role": "workstation",
            "timezone": query("timedatectl", "show", "--property=Timezone", "--value")
            or "UTC",
            "locale": os.environ.get("LANG", "en_US.UTF-8").replace(".utf8", ".UTF-8"),
        }
        self.yes = self.force = False
        rest = list(args)
        while rest:
            option = rest.pop(0)
            if option in ("--user", "--hostname", "--role", "--timezone", "--locale"):
                if not rest:
                    raise Usage
                self.values[option[2:]] = rest.pop(0)
            elif option == "--yes":
                self.yes = True
            elif option == "--force":
                self.force = True
            else:
                raise Usage

    def run(self) -> int:
        interactive = sys.stdin.isatty()
        if not self.yes and interactive:
            for key in ("user", "hostname", "role", "timezone", "locale"):
                answer = input(f"{key} [{self.values[key]}]: ").strip()
                if answer:
                    self.values[key] = answer
        content = self.render()
        flake = self.nacre.flake
        target = flake / "configuration.nix"
        created = not (flake / "flake.nix").exists()
        if not created and target.exists() and not self.force and self.uncommitted():
            raise Refusal(
                "configuration.nix has uncommitted changes; commit them or pass --force"
            )
        if created:
            # A new machine flake that follows Nacre; Git tracks it so Nix sees it.
            flake.mkdir(parents=True, exist_ok=True)
            (flake / "flake.nix").write_text((TEMPLATES / "flake.nix").read_text())
        target.write_text(content + "\n")
        if created:
            for args in (
                ["init", "--quiet"],
                ["add", "flake.nix", "configuration.nix"],
            ):
                subprocess.run(["git", "-C", str(flake), *args], check=True)
        print(f"Wrote {target}:\n\n{content}\n", file=sys.stderr)
        status = self.nacre.deploy("plan")
        if status != 0:
            return status
        if not self.yes:
            answer = (
                input("Apply this plan with nacre update? [y/N] ")
                if interactive
                else "n"
            )
            if not answer.lower().startswith("y"):
                print("Not applied. Run nacre update when ready.", file=sys.stderr)
                return 0
        return self.nacre.deploy("update")

    def uncommitted(self) -> bool:
        return (
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.nacre.flake),
                    "diff",
                    "--quiet",
                    "HEAD",
                    "--",
                    "configuration.nix",
                ],
                capture_output=True,
                check=False,
            ).returncode
            != 0
        )

    def render(self) -> str:
        v = self.values
        checks = (
            (NAME.fullmatch(v["user"]), f"invalid user name: {v['user']}"),
            (NAME.fullmatch(v["hostname"]), f"invalid hostname: {v['hostname']}"),
            (v["role"] in ("minimal", "workstation"), f"unknown role: {v['role']}"),
            (re.fullmatch(r"[A-Za-z0-9_+/-]+", v["timezone"]), "invalid time zone"),
            (re.fullmatch(r"[A-Za-z0-9_@.-]+", v["locale"]), "invalid locale"),
        )
        for ok, message in checks:
            if not ok:
                raise Refusal(message)
        entry = self.getent("passwd", v["user"])
        if entry is None:
            raise Refusal(f"create the account {v['user']} before installing")
        fields = entry.split(":")
        if fields[5] != f"/home/{v['user']}":
            raise Refusal(f"{v['user']} must live in /home/{v['user']}")
        wheel = self.getent("group", "wheel")
        if wheel is None or v["user"] not in wheel.split(":")[3].split(","):
            raise Refusal(f"{v['user']} must be in the wheel group")
        description = re.sub(r'[\\"$]', "", fields[4].split(",")[0]) or v["user"]
        images = sorted(
            f'"/boot/{image.name}"'
            for image in (self.root / "boot").glob("initramfs-*.img")
            if "fallback" not in image.name
        )
        if not images:
            raise Refusal("no initramfs image under /boot")
        template = (TEMPLATES / "configuration.nix").read_text()
        replacements = {
            "@role@": v["role"],
            "@hostname@": v["hostname"],
            "@timezone@": v["timezone"],
            "@locale@": v["locale"],
            "@description@": description,
            "@graphics@": "amd" if self.amd_graphics() else "generic",
            "@username@": v["user"],
            "@images@": " ".join(images),
        }
        for placeholder, value in replacements.items():
            template = template.replace(placeholder, value)
        return template.rstrip("\n")

    @staticmethod
    def getent(database: str, key: str) -> str | None:
        return query("getent", database, key)

    @staticmethod
    def amd_graphics() -> bool:
        listing = query("lspci") or ""
        return any(
            re.search(r"VGA|3D|Display", line) and re.search(r"AMD|ATI", line, re.I)
            for line in listing.splitlines()
        )


def run(argv: list[str]) -> int:
    explicit = os.environ.get("NACRE_FLAKE")
    verbose = version = False
    overrides: list[str] = []
    while argv and argv[0].startswith("-"):
        option = argv.pop(0)
        if option == "--flake":
            if not argv:
                raise Usage
            explicit = argv.pop(0)
        elif option == "--override-input":
            if len(argv) < 2:
                raise Usage
            overrides += [option, argv.pop(0), argv.pop(0)]
        elif option == "--verbose":
            verbose = True
        elif option in ("--help", "-h"):
            print(USAGE, end="")
            return 0
        elif option == "--version":
            version = True
        else:
            raise Usage
    flake = find_flake(explicit)
    if version:
        print(f"nacre {VERSION} ({revision(flake or Path('.'))})")
        return 0
    if not argv:
        raise Usage
    command, args = argv[0], argv[1:]
    if command == "install":
        config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        return Nacre(flake or config / "nacre", verbose, overrides).install(args)
    if flake is None or not (flake / "flake.nix").is_file():
        raise Refusal("no checkout found; pass --flake PATH or set NACRE_FLAKE")
    nacre = Nacre(flake, verbose, overrides)
    if command in ("plan", "switch", "update", "purge"):
        if args:
            raise Usage
        return nacre.deploy(command)
    if command == "check" and not args:
        nacre.nix("flake", "check", str(flake))
    if command == "build" and not args:
        nacre.nix("build", "--no-link", nacre.target("deployment"))
    if command == "status" and not args:
        return nacre.status()
    if command == "doctor" and not args:
        return nacre.doctor()
    if command == "changes" and (not args or (len(args) == 2 and args[0] == "--since")):
        return nacre.changes(args[1] if args else None)
    if command == "generations" and not args:
        return nacre.list_generations()
    if command == "rollback" and len(args) <= 1:
        return nacre.rollback(args[0] if args else None)
    if command == "ai" and args[:1] == ["prepare"] and len(args) <= 2:
        modes = {
            "": [],
            "build": ["--", "--build-only"],
            "model": ["--", "--model-only"],
        }
        mode = args[1] if len(args) == 2 else ""
        if mode not in modes:
            raise Usage
        nacre.nix_root("NO_COLOR", "run", nacre.target("llama-prepare"), *modes[mode])
    if command == "noctalia" and args[:1] in (["capture"], ["deploy"]):
        # The snapshot lives in this checkout; a deploy builds the home with
        # the same input overrides.
        repo = [] if "--repo" in args else ["--repo", str(flake)]
        extra = nacre.overrides if args[0] == "deploy" else []
        nacre.nix("run", nacre.target("noctalia-config"), "--", *args, *repo, *extra)
    raise Usage


def main() -> int:
    try:
        return run(sys.argv[1:])
    except Usage:
        print(USAGE, end="", file=sys.stderr)
        return 2
    except Refusal as error:
        print(f"nacre: {error}", file=sys.stderr)
        return 2
    except FileNotFoundError as error:
        print(f"nacre: command not found: {error.filename}", file=sys.stderr)
        return 127
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
