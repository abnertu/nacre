"""The machine checkout and the Nix commands that act on it."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from .common import config_home, state_home


def find_flake(explicit: str | None) -> Path | None:
    """The checkout: `explicit`, else ~/.config/nacre, else ~/.config/nix."""
    if explicit:
        return Path(explicit)
    for candidate in (config_home() / "nacre", config_home() / "nix"):
        if (candidate / "flake.nix").is_file():
            return candidate
    return None


def plain_output(verbose: bool) -> bool:
    """Whether Nix should print raw logs instead of its progress bar."""
    return (
        verbose
        or not sys.stderr.isatty()
        or os.environ.get("TERM", "dumb") == "dumb"
        or "NO_COLOR" in os.environ
        or bool(os.environ.get("CI"))
    )


class Machine:
    """A machine flake checkout, with the options of this invocation."""

    def __init__(self, flake: Path, verbose: bool, overrides: Sequence[str] = ()):
        self.flake = flake
        self.verbose = verbose
        self.overrides = list(overrides)
        self.log_format = [
            "--log-format",
            "raw" if plain_output(verbose) else "bar-with-logs",
        ]
        self.nix_args = [
            "--show-trace",
            "--print-build-logs",
            *(["--verbose"] if verbose else []),
            *self.overrides,
        ]

    def target(self, attribute: str) -> str:
        """The flake output `attribute` of this checkout."""
        return f"{self.flake}#{attribute}"

    def nix(self, command: str, *args: str) -> NoReturn:
        """Replace this process with `nix COMMAND`."""
        argv = ["nix", *self.log_format, command, *self.nix_args, *args]
        os.execvp(argv[0], argv)

    def nix_root(self, preserve: str, command: str, *args: str) -> NoReturn:
        """Replace this process with `sudo nix COMMAND`, keeping `preserve`."""
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

    def build_deployment(self) -> tuple[int, str]:
        """Build #deployment; return the exit status and the store path."""
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
        return built.returncode, built.stdout.strip()


def record_path(name: str) -> Path:
    """Where nacre keeps its record `name`."""
    return state_home() / "nacre" / name


def append_record(name: str, line: str) -> None:
    """Append `line` to record `name`."""
    path = record_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as record:
        record.write(f"{line}\n")


def write_record(name: str, line: str) -> None:
    """Replace record `name` with `line`."""
    path = record_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{line}\n")
