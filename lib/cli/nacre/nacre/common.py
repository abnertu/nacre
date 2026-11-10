"""Errors, host paths and read-only probes that every command shares."""

from __future__ import annotations

import datetime
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import TextIO

# Tests point this at a temporary root.
ROOT = Path(os.environ.get("NACRE_ROOT") or "/")
PENDING_DIR = ROOT / "var/lib/nix-config/arch"
NAME = re.compile(r"[a-z][a-z0-9_-]*")


def styled(text: str, code: str, *, stream: TextIO | None = None) -> str:
    """Use native terminal colors while keeping redirected output plain."""
    output = sys.stdout if stream is None else stream
    enabled = (
        output.isatty()
        and os.environ.get("TERM", "dumb") != "dumb"
        and "NO_COLOR" not in os.environ
        and not os.environ.get("CI")
    )
    return f"\033[{code}m{text}\033[0m" if enabled else text


class Usage(Exception):
    """Invalid arguments: print usage and exit 2."""


class Refusal(Exception):
    """A precondition failed: print the message and exit 2."""


def config_home() -> Path:
    """`$XDG_CONFIG_HOME`, or `~/.config`."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def state_home() -> Path:
    """`$XDG_STATE_HOME`, or `~/.local/state`."""
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")


def revision(flake: Path) -> str:
    """`git describe --always --dirty` of the checkout, or `unknown`."""
    result = subprocess.run(
        ["git", "-C", str(flake), "describe", "--always", "--dirty"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def now() -> str:
    """The local time, as an ISO timestamp with offset."""
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


def pending_work() -> list[str]:
    """Names of the deployment actions that an interruption left pending."""
    return sorted(marker.stem for marker in PENDING_DIR.glob("*.pending"))
