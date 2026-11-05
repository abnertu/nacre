"""doctor: report the problems that need attention; it changes nothing."""

from __future__ import annotations

import os
import pwd
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .common import ROOT, config_home, pending_work, query, revision
from .generations import current_generation, link
from .machine import Machine, record_path

# Home Manager and editors leave these beside a file that was in the way.
BACKUP_SUFFIXES = (".bak", ".backup", ".orig", ".old")
NOCTALIA_UNCAPTURED = 3
"""`noctalia-config capture --check` status for uncaptured GUI changes."""


@dataclass(frozen=True)
class Finding:
    """One doctor line: a problem, or the healthy state when there is none."""

    label: str
    problem: str | None
    fine: str


def doctor(machine: Machine) -> int:
    """Print one line for each check; return 1 if any found a problem."""
    checks: list[Callable[[Machine], Finding]] = [
        check_switch,
        check_pending,
        check_kernel,
        check_failed_units,
        check_idle_units,
        check_noctalia,
        check_backups,
    ]
    problems = 0
    for check in checks:
        finding = check(machine)
        problems += finding.problem is not None
        state = "warn" if finding.problem else "ok"
        print(f"{state:<5} {finding.label:<9} {finding.problem or finding.fine}")
    return 1 if problems else 0


def check_switch(machine: Machine) -> Finding:
    """Whether the checkout matches the last recorded switch."""
    current = revision(machine.flake)
    record = record_path("last-switch")
    switched = record.read_text().split()[1] if record.is_file() else None
    if switched is None:
        problem = "no switch recorded by nacre; run nacre switch"
    elif switched != current or current.endswith("-dirty"):
        problem = (
            f"checkout is at {current}, last switch was from {switched}; "
            "run nacre switch"
        )
    else:
        problem = None
    return Finding("switch", problem, f"checkout matches the last switch ({current})")


def check_pending(_: Machine) -> Finding:
    """Whether an interrupted deployment left pending work."""
    pending = pending_work()
    problem = (
        f"interrupted: {' '.join(pending)}; rerun the interrupted command"
        if pending
        else None
    )
    return Finding("pending", problem, "no interrupted work")


def check_kernel(_: Machine) -> Finding:
    """Whether the running kernel still has its modules installed."""
    kernel = query("uname", "-r")
    missing = kernel and not (ROOT / "usr/lib/modules" / kernel).is_dir()
    problem = f"running {kernel} has no installed modules; reboot" if missing else None
    return Finding("kernel", problem, f"running {kernel}")


def check_failed_units(_: Machine) -> Finding:
    """Whether a system or user unit has failed."""
    failed = [
        *units("--failed"),
        *(f"{unit} (user)" for unit in units("--user", "--failed")),
    ]
    problem = f"failed units: {' '.join(failed)}" if failed else None
    return Finding("failed", problem, "no failed units")


def check_idle_units(_: Machine) -> Finding:
    """Whether an enabled home unit has never started."""
    idle = idle_home_units()
    problem = (
        f"enabled but never started: {' '.join(idle)}; start them or log in again"
        if idle
        else None
    )
    return Finding("started", problem, "every enabled home unit has started")


def check_noctalia(machine: Machine) -> Finding:
    """Whether Noctalia's GUI preferences drifted from the reviewed snapshot."""
    snapshot, uncaptured = noctalia_drift(machine.flake)
    fine = (
        "GUI preferences match the snapshot"
        if snapshot
        else "no Noctalia snapshot in this checkout"
    )
    return Finding("noctalia", uncaptured, fine)


def check_backups(_: Machine) -> Finding:
    """Whether backup files sit beside files that the home generation manages."""
    leftovers = backup_leftovers()
    problem = (
        f"backups beside managed files: {' '.join(leftovers)}" if leftovers else None
    )
    return Finding("leftover", problem, "no backups beside managed files")


def units(*selection: str) -> list[str]:
    """Unit names that `systemctl SELECTION --plain --no-legend` lists."""
    listing = query("systemctl", *selection, "--plain", "--no-legend")
    return [line.split()[0] for line in (listing or "").splitlines() if line]


def idle_home_units() -> list[str]:
    """Units that the home generation enables under an active target but that
    never started, as when activation adds them to a running session."""
    wanted = wanted_home_units()
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
        fields = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        running = fields.get("ActiveState") in ("active", "activating", "reloading")
        if not running and fields.get("InactiveExitTimestampMonotonic") == "0":
            idle.append(fields.get("Id", "?"))
    return idle


def wanted_home_units() -> list[str]:
    """Store-linked units in the .wants directories of active user targets."""
    wanted: list[str] = []
    for wants in sorted((config_home() / "systemd/user").glob("*.target.wants")):
        target = wants.name.removesuffix(".wants")
        if query("systemctl", "--user", "is-active", target) != "active":
            continue
        wanted += sorted(
            unit.name
            for unit in wants.iterdir()
            if unit.is_symlink() and os.readlink(unit).startswith("/nix/store/")
        )
    return wanted


def noctalia_drift(flake: Path) -> tuple[bool, str | None]:
    """Whether a snapshot exists, and the uncaptured GUI changes if any."""
    user = pwd.getpwuid(os.getuid()).pw_name
    if not (flake / "homes" / user / "noctalia/config.toml").is_file():
        return False, None
    try:
        result = subprocess.run(
            ["noctalia-config", "capture", "--check", "--repo", str(flake)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return True, "noctalia-config is not installed; run nacre switch"
    if result.returncode == 0:
        return True, None
    if result.returncode == NOCTALIA_UNCAPTURED:
        # "Uncaptured Noctalia changes in: <sections>; run ..."
        return True, result.stdout.strip().replace(
            "Uncaptured Noctalia changes", "uncaptured GUI changes"
        )
    return True, "could not compare; run nacre noctalia capture --dry-run"


def backup_leftovers() -> list[str]:
    """Backup paths in the home beside files that the active generation manages."""
    current = current_generation()
    if current is None:
        return []
    files = link(current) / "home-files"
    found: list[str] = []
    for directory, subdirectories, names in os.walk(files):
        for name in [*names, *subdirectories]:
            managed = Path(directory, name).relative_to(files)
            for suffix in BACKUP_SUFFIXES:
                if (Path.home() / f"{managed}{suffix}").exists():
                    found.append(f"~/{managed}{suffix}")
    return sorted(found)
