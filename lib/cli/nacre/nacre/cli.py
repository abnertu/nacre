"""Command line of nacre: parse global options and dispatch one command."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .common import Refusal, Usage, config_home, revision
from .deploy import MODES, deploy
from .doctor import doctor
from .generations import list_generations, rollback
from .install import Installer
from .machine import Machine, find_flake
from .status import changes, status

# Packaging substitutes the VERSION file.
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

PREPARE_MODES = {
    "": [],
    "build": ["--", "--build-only"],
    "model": ["--", "--model-only"],
}
NOCTALIA_ACTIONS = ("capture", "deploy")


class HelpRequested(Exception):
    """--help: print usage on stdout and exit 0."""


@dataclass
class Options:
    """Global options, which precede the command."""

    flake: str | None = field(default_factory=lambda: os.environ.get("NACRE_FLAKE"))
    verbose: bool = False
    version: bool = False
    overrides: list[str] = field(default_factory=list[str])


def parse_options(argv: list[str]) -> Options:
    """Consume the global options at the front of `argv`."""
    options = Options()
    while argv and argv[0].startswith("-"):
        option = argv.pop(0)
        if option == "--flake":
            if not argv:
                raise Usage
            options.flake = argv.pop(0)
        elif option == "--override-input":
            if len(argv) < 2:
                raise Usage
            options.overrides += [option, argv.pop(0), argv.pop(0)]
        elif option == "--verbose":
            options.verbose = True
        elif option in ("--help", "-h"):
            raise HelpRequested
        elif option == "--version":
            options.version = True
        else:
            raise Usage
    return options


def run(argv: list[str]) -> int:
    """Run the command line `argv`; return the exit status."""
    try:
        options = parse_options(argv)
    except HelpRequested:
        print(USAGE, end="")
        return 0
    flake = find_flake(options.flake)
    if options.version:
        print(f"nacre {VERSION} ({revision(flake or Path('.'))})")
        return 0
    if not argv:
        raise Usage
    command, args = argv[0], argv[1:]
    if command == "install":
        machine = Machine(
            flake or config_home() / "nacre", options.verbose, options.overrides
        )
        return Installer(machine, args).run()
    if flake is None or not (flake / "flake.nix").is_file():
        raise Refusal("no checkout found; pass --flake PATH or set NACRE_FLAKE")
    machine = Machine(flake, options.verbose, options.overrides)
    handler = COMMANDS.get(command)
    if handler is None:
        raise Usage
    return handler(machine, args)


def no_arguments(
    action: Callable[[Machine], int],
) -> Callable[[Machine, list[str]], int]:
    """A command that takes no arguments."""

    def handler(machine: Machine, args: list[str]) -> int:
        if args:
            raise Usage
        return action(machine)

    return handler


def deployment(mode: str) -> Callable[[Machine, list[str]], int]:
    """plan, switch, update or purge."""
    return no_arguments(lambda machine: deploy(machine, mode))


def check(machine: Machine) -> int:
    """Run every flake check of the checkout."""
    machine.nix("flake", "check", str(machine.flake))


def build(machine: Machine) -> int:
    """Build the deployment without activating it."""
    machine.nix("build", "--no-link", machine.target("deployment"))


def changes_command(_: Machine, args: list[str]) -> int:
    """changes [--since TIME]."""
    if args and (len(args) != 2 or args[0] != "--since"):
        raise Usage
    return changes(args[1] if args else None)


def rollback_command(_: Machine, args: list[str]) -> int:
    """rollback [GENERATION]."""
    if len(args) > 1:
        raise Usage
    return rollback(args[0] if args else None)


def ai_command(machine: Machine, args: list[str]) -> int:
    """ai prepare [build|model]: prepare the pinned llama.cpp build and models."""
    if args[:1] != ["prepare"] or len(args) > 2:
        raise Usage
    mode = args[1] if len(args) == 2 else ""
    if mode not in PREPARE_MODES:
        raise Usage
    machine.nix_root(
        "NO_COLOR", "run", machine.target("llama-prepare"), *PREPARE_MODES[mode]
    )


def noctalia_command(machine: Machine, args: list[str]) -> int:
    """noctalia capture|deploy [ARGS]: the reviewed Noctalia snapshot."""
    if not args or args[0] not in NOCTALIA_ACTIONS:
        raise Usage
    # The snapshot lives in this checkout; a deploy builds the home with the
    # same input overrides.
    repo = [] if "--repo" in args else ["--repo", str(machine.flake)]
    extra = machine.overrides if args[0] == "deploy" else []
    machine.nix("run", machine.target("noctalia-config"), "--", *args, *repo, *extra)


COMMANDS: dict[str, Callable[[Machine, list[str]], int]] = {
    **{mode: deployment(mode) for mode in MODES},
    "check": no_arguments(check),
    "build": no_arguments(build),
    "status": no_arguments(status),
    "doctor": no_arguments(doctor),
    "changes": changes_command,
    "generations": no_arguments(lambda _: list_generations()),
    "rollback": rollback_command,
    "ai": ai_command,
    "noctalia": noctalia_command,
}


def main() -> int:
    """Console entry point: map errors to exit statuses."""
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
