"""upgrade self: adopt the newest Nacre on the checkout's channel."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import releases
from .common import Refusal, Usage
from .deploy import deploy
from .machine import Machine

# `inputs.nacre.url = "...";` or `nacre.url = "...";` inside `inputs = { ... }`.
INPUT = re.compile(r'(?<![\w.-])((?:inputs\.)?nacre\.url\s*=\s*")([^"]*)(")')
SOURCE = re.compile(r"github:abnertu/nacre(?:/([^\s?#]+))?")
MISSING_PACKAGES = 3


def locked(lock: Path) -> tuple[str, str]:
    """The locked revision of the nacre input, and its original ref."""
    if not lock.is_file():
        return "", ""
    try:
        data: dict[str, Any] = json.loads(lock.read_text())
        nodes: dict[str, Any] = data["nodes"]
        name = nodes[data["root"]].get("inputs", {}).get("nacre")
        node: dict[str, Any] = nodes.get(name, {}) if isinstance(name, str) else {}
        rev: str = node.get("locked", {}).get("rev", "")
        ref: str = node.get("original", {}).get("ref", "")
    except (ValueError, KeyError, AttributeError, TypeError) as error:
        raise Refusal(f"{lock} is not a readable flake lock: {error}") from error
    return rev, ref


def describe(rev: str, ref: str) -> str:
    return f"{rev[:12] or 'unlocked'} ({ref or 'main'})"


def target(text: str, match: re.Match[str], ref: str, old_rev: str) -> str | None:
    """The flake text that pins the newest Nacre, or None when it is current.

    A release pin moves to the newest tag; a branch pin keeps its URL and
    always refreshes its lock entry.
    """
    if not releases.TAG.fullmatch(ref):
        return text
    tag, commit = releases.newest(releases.tags())
    if releases.version(ref) > releases.version(tag):
        raise Refusal(f"the pinned {ref} is newer than the newest release {tag}")
    if ref == tag and old_rev == commit:
        return None
    url = f"{releases.URL}/{tag}"
    return text[: match.start(2)] + url + text[match.end(2) :]


def upgrade_self(machine: Machine, args: list[str]) -> int:
    """Pin the newest Nacre, plan, ask, and switch."""
    if args not in ([], ["--yes"]):
        raise Usage
    yes = args == ["--yes"]
    pin_newest(machine)
    status = deploy(machine, "plan")
    if status != 0:
        return status
    interactive = sys.stdin.isatty()
    if not yes and not (
        interactive
        and input("Apply this plan with nacre switch? [y/N] ").lower().startswith("y")
    ):
        print("Not applied. Run nacre switch when ready.", file=sys.stderr)
        return 0
    status = deploy(machine, "switch")
    if status == MISSING_PACKAGES:
        print(
            "Declared packages are missing; run nacre upgrade system to install them.",
            file=sys.stderr,
        )
    return status


def pin_newest(machine: Machine) -> None:
    """Point the checkout's nacre input at the newest Nacre on its channel."""
    flake_file = machine.flake / "flake.nix"
    lock_file = machine.flake / "flake.lock"
    original = flake_file.read_bytes()
    text = original.decode()
    matches = list(INPUT.finditer(text))
    if len(matches) != 1:
        raise Refusal(
            f"{flake_file} must set the nacre input URL exactly once; found {len(matches)}"
        )
    (match,) = matches
    source = SOURCE.fullmatch(match[2])
    if source is None:
        raise Refusal(
            f"the nacre input is {match[2]!r}, not github:abnertu/nacre[/<ref>]; "
            "update it yourself"
        )
    ref = source[1] or ""
    old_rev, old_ref = locked(lock_file)
    new_text = target(text, match, ref, old_rev)
    if new_text is None:
        print(f"Nacre is current: {describe(old_rev, ref)}", file=sys.stderr)
    else:
        refresh(machine, flake_file, lock_file, original, new_text)
        new_rev, new_ref = locked(lock_file)
        print(
            f"Nacre: {describe(old_rev, old_ref)} -> {describe(new_rev, new_ref)}",
            file=sys.stderr,
        )


def refresh(
    machine: Machine, flake_file: Path, lock_file: Path, old: bytes, new: str
) -> None:
    """Write the new URL and update the nacre lock entry, or restore both files."""
    lock_bytes = lock_file.read_bytes() if lock_file.exists() else None
    try:
        flake_file.write_bytes(new.encode())
        result = subprocess.run(
            [
                "nix",
                *machine.log_format,
                "flake",
                "update",
                "nacre",
                "--flake",
                str(machine.flake),
                *(["--verbose"] if machine.verbose else []),
            ],
            check=False,
        )
        if result.returncode != 0:
            raise Refusal(
                f"nix flake update nacre failed with exit status {result.returncode}"
            )
    except BaseException:
        flake_file.write_bytes(old)
        if lock_bytes is None:
            lock_file.unlink(missing_ok=True)
        else:
            lock_file.write_bytes(lock_bytes)
        raise
