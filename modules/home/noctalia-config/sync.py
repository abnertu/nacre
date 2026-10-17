"""Explicit, reviewed preference exchange with Noctalia v5 (not secret sync)."""

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from nix_adapter import dump_toml, parse_toml

# A parsed TOML document.
Settings = dict[str, Any]
Runner = Callable[..., bytes]

# Whole sections are owned together. Unknown/new sections require code review.
SECTIONS = frozenset(
    {
        "theme",
        "wallpaper",
        "bar",
        "widget",
        "dock",
        "desktop",
        "desktop_widgets",
        "shell",
        "osd",
        "notification",
        "audio",
        "brightness",
        "battery",
        "control_center",
        "accessibility",
        "night_light",
    }
)
REVIEW = re.compile(
    r"password|secret|token|credential|account|command|exec|script|hook|action|keybind|url",
    re.IGNORECASE,
)


def require(ok: object, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def safe_path(path: Path) -> None:
    require(path.is_absolute(), "Expected an absolute path")
    for item in (path, *path.parents):
        require(not item.is_symlink(), "Refusing a symlinked write/state path")


def encode(data: Settings) -> bytes:
    return dump_toml(data).encode()


def parse(raw: bytes | str) -> Settings:
    return parse_toml(raw)


def read(path: Path) -> bytes:
    return path.read_bytes() if path.exists() else b""


def needs_review(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            (REVIEW.search(str(key)) and bool(item)) or needs_review(item)
            for key, item in cast("dict[object, object]", value).items()
        )
    if isinstance(value, list):
        return any(needs_review(item) for item in cast("list[object]", value))
    return False


def select(data: Settings) -> tuple[Settings, list[str]]:
    selected = {
        key: value
        for key, value in data.items()
        if key in SECTIONS and not needs_review(value)
    }
    return selected, sorted(set(data) - set(selected))


def merge(base: Settings, override: Settings) -> Settings:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], cast(Settings, value))
        else:
            result[key] = value
    return result


def atomic_write(path: Path, raw: bytes, mode: int = 0o600) -> None:
    safe_path(path)
    if (
        path.exists()
        and read(path) == raw
        and stat.S_IMODE(path.stat().st_mode) == mode
    ):
        return
    fd, name = tempfile.mkstemp(prefix=".noctalia-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class CommandTimeout(RuntimeError):
    """A timed-out operation needs explicit recovery, never an implicit rollback."""


COMMAND_TIMEOUTS = {"query": 30, "deployment": 3600}


def execute(
    argv: list[str], env: dict[str, str] | None = None, cwd: Path | None = None
) -> bytes:
    deployment = argv[0] == "/usr/bin/nix" or Path(argv[0]).name == "activate"
    timeout = COMMAND_TIMEOUTS["deployment" if deployment else "query"]
    environment = dict(os.environ)
    if env:
        environment.update(env)
    if Path(argv[0]).name == "activate":
        for name in (
            "HOME_MANAGER_BACKUP_EXT",
            "HOME_MANAGER_BACKUP_OVERWRITE",
            "SKIP_SANITY_CHECKS",
            "DRY_RUN",
        ):
            environment.pop(name, None)
    process = subprocess.Popen(
        argv,
        env=environment,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    assert process.stdout is not None and process.stderr is not None
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except BaseException as error:
        # Kill the entire ordinary child process group before releasing our lock.
        # Do not recover overrides after an activation timeout: keep the receipt.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            # A detached descendant may still hold a pipe. Do not wait forever
            # or attempt recovery while its state is uncertain.
            process.stdout.close()
            process.stderr.close()
            process.wait(timeout=5)
            raise CommandTimeout(
                "Command termination is uncertain; preserve the receipt and inspect the operation before recovery."
            ) from None
        if isinstance(error, subprocess.TimeoutExpired):
            raise CommandTimeout(
                "External command timed out; output withheld. Preserve any pending receipt and use deploy --recover before retrying."
            ) from None
        raise
    require(
        process.returncode == 0,
        "External command failed; output withheld to protect settings",
    )
    return stdout + stderr if argv[1:3] == ["config", "validate"] else stdout


class Sync:
    def __init__(
        self,
        repo: Path,
        user: str,
        home_configuration: str,
        config: Path,
        state: Path,
        control: Path,
        run: Runner = execute,
    ):
        require(bool(re.fullmatch(r"[a-z_][a-z0-9_-]*", user)), "Invalid login user")
        self.repo, self.run = repo, run
        self.target = repo / "homes" / user / "noctalia/config.toml"
        self.config, self.state, self.settings = config, state, state / "settings.toml"
        self.control = control
        self.home_configuration = home_configuration
        self.pending = control / "pending.json"

    def validate(self, data: Settings) -> None:
        with tempfile.TemporaryDirectory(prefix="noctalia-validate-") as directory:
            candidate = Path(directory) / "config.toml"
            candidate.write_bytes(encode(data))
            result = self.run(
                ["/usr/bin/noctalia", "config", "validate", str(candidate)]
            )
            # Diagnostics may quote arbitrary values or user-defined key names.
            # Report only section names from our fixed preference allowlist.
            sections = sorted(
                set(
                    re.findall(
                        r"(?m)^WARN\s+([a-z_]+)(?=[.:])",
                        result.decode(errors="replace"),
                    )
                )
                & SECTIONS
            )
            detail = " (sections: " + ", ".join(sections) + ")" if sections else ""
            require(
                b"warn" not in result.lower(),
                "Noctalia validation warnings require review"
                + detail
                + ". Run /usr/bin/noctalia config validate locally to inspect "
                "the live configuration; candidate-only warnings may differ. "
                "Raw diagnostics withheld to protect settings; no preferences written.",
            )

    def export(self) -> Settings:
        return parse(self.run(["/usr/bin/noctalia", "config", "export"]))

    def stopped(self) -> None:
        # pgrep's exit 1 is an expected negative result, not a command failure.
        result = subprocess.run(
            ["/usr/bin/pgrep", "-u", str(os.getuid()), "-x", "noctalia"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
        require(
            result.returncode == 1,
            "Exit Noctalia before changing GUI overrides or recovering",
        )

    @contextmanager
    def locked(self) -> Generator[None]:
        safe_path(self.control)
        self.control.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(
            self.control.stat().st_uid == os.getuid()
            and stat.S_IMODE(self.control.stat().st_mode) == 0o700,
            "Command state requires login-user ownership and mode 0700",
        )
        lock_path = self.control / "lock"
        safe_path(lock_path)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "r+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def preflight(self) -> None:
        safe_path(self.target)
        safe_path(self.settings)
        safe_path(self.control)
        safe_path(self.pending)
        root = (
            self.run(["git", "-C", str(self.repo), "rev-parse", "--show-toplevel"])
            .decode()
            .strip()
        )
        require(Path(root) == self.repo, "--repo must identify the repository root")
        self.run(
            [
                "git",
                "-C",
                str(self.repo),
                "ls-files",
                "--error-unmatch",
                str(self.target.relative_to(self.repo)),
            ]
        )
        require(
            not self.pending.exists(),
            "An interrupted deployment exists; use deploy --recover",
        )

    def capture(self, dry_run: bool = False) -> None:
        self.preflight()
        original = read(self.target)
        exported = self.export()
        data, skipped = select(exported)
        require(bool(data), "No eligible preferences; repository file left unchanged")
        self.validate(data)
        print("Capture sections: " + ", ".join(sorted(data)))
        print(
            "Excluded sections (policy, unsupported or review required): "
            + ", ".join(name for name in skipped if name in SECTIONS)
            + f"; {sum(name not in SECTIONS for name in skipped)} unsupported sections"
        )

        if dry_run:
            return
        with self.locked():
            self.preflight()
            require(
                read(self.target) == original,
                "Repository preferences changed during capture; retry",
            )
            atomic_write(self.target, encode(data), 0o644)
        print(
            "Preferences captured. Review locally before committing; no Git index changes made."
        )

    def plan(self, replace: bool) -> tuple[Settings, bytes, bytes]:
        self.preflight()
        wanted = parse(read(self.target))
        eligible, excluded = select(wanted)
        require(
            not excluded and eligible == wanted,
            "Repository contains policy or unreviewed sections",
        )
        self.validate(wanted)
        # Other handwritten files remain unowned. Never overwrite their policy.
        for path in self.config.glob("*.toml"):
            if path.name == "config.toml":
                continue
            data = parse(read(path))
            require(
                not data.get("include"),
                "Included configuration needs manual ownership review",
            )
            require(
                not (set(data) & set(wanted)),
                "Another TOML owns the same preference sections",
            )
        current = self.config / "config.toml"
        require(
            not current.exists()
            or (
                current.is_symlink()
                and str(current.resolve()).startswith("/nix/store/")
            ),
            "Existing config.toml is not a Home Manager link; resolve ownership first",
        )
        original = read(self.settings)
        overrides = parse(original)
        conflicts = [
            key
            for key in wanted
            if key in overrides
            and merge({key: wanted[key]}, {key: overrides[key]})[key] != wanted[key]
        ]
        require(
            not conflicts or replace,
            "GUI override conflicts in sections: " + ", ".join(sorted(conflicts)),
        )
        # Clear only the sections explicitly owned by this repository snapshot.
        replacement = (
            encode(
                {key: value for key, value in overrides.items() if key not in wanted}
            )
            if replace
            else original
        )
        return wanted, original, replacement

    def recover(self) -> None:
        self.stopped()
        safe_path(self.pending)
        require(self.pending.is_file(), "No interrupted deployment to recover")
        journal = cast(Settings, json.loads(read(self.pending)))
        require(
            journal["settings"] == str(self.settings),
            "Recovery root differs from interrupted deployment",
        )
        backup = self.control / journal["backup"]
        require(
            backup.parent == self.control and backup.name.startswith("settings-"),
            "Invalid recovery receipt",
        )
        safe_path(backup)
        current_hash = hashlib.sha256(read(self.settings)).hexdigest()
        require(
            current_hash in (journal["before"], journal["after"]),
            "GUI settings changed after interruption; preserve receipt and resolve manually",
        )
        raw = read(backup)
        require(
            hashlib.sha256(raw).hexdigest() == journal["before"],
            "Recovery backup does not match receipt",
        )
        atomic_write(self.settings, raw, journal["mode"])
        self.pending.unlink()
        print(
            "GUI overrides restored; Home Manager generation was not rolled back. Backup retained."
        )

    def deploy(
        self, dry_run: bool = False, replace: bool = False, recover: bool = False
    ) -> None:
        if recover:
            require(not dry_run, "Recovery cannot be combined with dry-run")
            with self.locked():
                self.recover()
            return
        wanted, original, replacement = self.plan(replace)
        print("Deploy sections: " + ", ".join(sorted(wanted)))
        if dry_run:
            print("Dry run: no Home Manager build, activation or override changes.")
            return
        with (
            self.locked(),
            tempfile.TemporaryDirectory(prefix="noctalia-deploy-") as build_directory,
        ):
            wanted, original, replacement = self.plan(replace)
            artifact = Path(build_directory) / "generation"
            source = read(self.target)
            # Build the full home before touching mutable overrides.
            self.run(
                [
                    "/usr/bin/nix",
                    "build",
                    "--out-link",
                    str(artifact),
                    "--no-update-lock-file",
                    str(self.repo)
                    + '#homeConfigurations."'
                    + self.home_configuration
                    + '".activationPackage',
                ]
            )
            require(
                read(self.settings) == original,
                "GUI settings changed during build; retry",
            )
            require(
                read(self.target) == source,
                "Repository preferences changed during build; retry",
            )
            changed = original != replacement
            if changed:
                self.stopped()
                self.settings.parent.mkdir(parents=True, exist_ok=True)
                fd, backup = tempfile.mkstemp(
                    prefix="settings-", suffix=".toml", dir=self.control
                )
                os.close(fd)
                atomic_write(Path(backup), original)
                mode = stat.S_IMODE(self.settings.stat().st_mode)
                journal = {
                    "settings": str(self.settings),
                    "backup": Path(backup).name,
                    "before": hashlib.sha256(original).hexdigest(),
                    "after": hashlib.sha256(replacement).hexdigest(),
                    "mode": mode,
                }
                atomic_write(self.pending, json.dumps(journal).encode())
                atomic_write(self.settings, replacement, mode)
            try:
                self.run([str(artifact / "activate"), "--driver-version", "0"])
                effective = self.export()
                require(
                    all(effective.get(key) == value for key, value in wanted.items()),
                    "Effective preferences differ from repository after activation",
                )
            except CommandTimeout:
                raise
            except Exception:
                if changed:
                    self.recover()
                raise
            if changed:
                self.pending.unlink()
            print(
                "Home Manager deployment and effective preference verification completed."
            )


def main() -> int:
    parser = argparse.ArgumentParser(prog="noctalia-config", description=__doc__)
    parser.add_argument("operation", choices=("capture", "deploy"))
    parser.add_argument("--user", required=True, help=argparse.SUPPRESS)
    parser.add_argument("--home-configuration", required=True, help=argparse.SUPPRESS)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replace-overrides", action="store_true")
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    home = Path.home()
    config_root = Path(
        os.environ.get("NOCTALIA_CONFIG_HOME")
        or os.environ.get("XDG_CONFIG_HOME")
        or home / ".config"
    )
    state_root = Path(
        os.environ.get("NOCTALIA_STATE_HOME")
        or os.environ.get("XDG_STATE_HOME")
        or home / ".local/state"
    )
    control = (
        Path(os.environ.get("XDG_STATE_HOME") or home / ".local/state")
        / "nix-config/noctalia-config"
    )
    sync = Sync(
        args.repo.absolute(),
        args.user,
        args.home_configuration,
        config_root / "noctalia",
        state_root / "noctalia",
        control,
    )
    try:
        require(
            args.operation == "deploy" or not (args.replace_overrides or args.recover),
            "Override replacement/recovery are deploy-only operations",
        )
        if args.operation == "capture":
            sync.capture(args.dry_run)
        else:
            require(
                not os.environ.get("NOCTALIA_CONFIG_HOME")
                and not os.environ.get("NOCTALIA_STATE_HOME")
                and config_root == home / ".config"
                and state_root == home / ".local/state",
                "Custom Noctalia roots are capture-only until Home Manager ownership is configured",
            )
            sync.deploy(args.dry_run, args.replace_overrides, args.recover)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        print(
            "Operation failed; details withheld to protect configuration values",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
