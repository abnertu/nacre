"""Home Manager generations: list them and roll back to one."""

from __future__ import annotations

import datetime
import os
import pwd
import re
import sys
from pathlib import Path

from .common import Usage, state_home

GENERATION_LINK = re.compile(r"home-manager-(\d+)-link")


def profile() -> Path:
    """The Home Manager profile link of this user."""
    return state_home() / "nix/profiles/home-manager"


def link(number: int) -> Path:
    """The profile link of generation `number`."""
    return profile().parent / f"home-manager-{number}-link"


def generations() -> list[int]:
    """The numbers of every home generation, oldest first."""
    numbers: list[int] = []
    for candidate in profile().parent.glob(profile().name + "-*-link"):
        match = GENERATION_LINK.fullmatch(candidate.name)
        if match and candidate.is_symlink():
            numbers.append(int(match[1]))
    return sorted(numbers)


def current_generation() -> int | None:
    """The active home generation, or None when there is none."""
    try:
        target = os.readlink(profile())
    except OSError:
        return None
    match = GENERATION_LINK.fullmatch(Path(target).name)
    return int(match[1]) if match else None


def list_generations() -> int:
    """Print each generation with its time; mark the active one."""
    current = current_generation()
    for number in generations():
        when = datetime.datetime.fromtimestamp(link(number).lstat().st_mtime)
        marker = "*" if number == current else " "
        print(f"{marker} {number:4}  {when.strftime('%F %T')}")
    return 0


def rollback(requested: str | None) -> int:
    """Activate generation `requested`, or the one before the active one.

    Arch state is not rolled back. Return 1 when there is no such generation;
    otherwise this process becomes the generation's activation script.
    """
    target = rollback_target(requested)
    if target is None or not link(target).is_symlink():
        current = current_generation()
        wanted = target if target is not None else f"before {current}"
        print(f"nacre: no home generation {wanted} to roll back to", file=sys.stderr)
        return 1
    print(
        f"Activating home generation {target}; Arch state is unchanged.",
        file=sys.stderr,
    )
    activate = link(target).resolve() / "activate"
    os.environ.setdefault("USER", pwd.getpwuid(os.getuid()).pw_name)
    argv = [str(activate)]
    if "--driver-version" in activate.read_text(errors="replace"):
        argv += ["--driver-version", "0"]
    os.execv(argv[0], argv)


def rollback_target(requested: str | None) -> int | None:
    """The generation that a rollback activates."""
    if requested is not None:
        if not requested.isdigit():
            raise Usage
        return int(requested)
    current = current_generation()
    earlier = [
        number for number in generations() if current is None or number < current
    ]
    return earlier[-1] if earlier else None
