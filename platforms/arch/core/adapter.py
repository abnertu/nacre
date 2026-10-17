"""Privileged Arch core adapter entrypoint."""

from __future__ import annotations

import sys

# Runs as root from the read-only store: writing bytecode would modify it.
sys.dont_write_bytecode = True

import json
import os
import traceback
from pathlib import Path

import runtime
from nix_adapter import Conflict

PHASES = ("preflight", "plan", "repositories", "converge", "finish", "purge")
FLAGS = {"--verbose", "--color"}


def main() -> int:
    args = sys.argv[1:]
    flags = set(args[2:])
    if (
        len(args) < 2
        or args[1] not in PHASES
        or not flags <= FLAGS
        or len(flags) != len(args) - 2
        or os.geteuid() != 0
    ):
        print("private core adapter must be invoked by arch-switch", file=sys.stderr)
        return 2
    verbose = "--verbose" in flags
    if verbose:
        os.environ["NIX_CONFIG_VERBOSE"] = "1"
    core = runtime.Core(json.loads(Path(args[0]).read_text()), color="--color" in flags)
    try:
        getattr(core, args[1])()
        return 0
    except Conflict as error:
        print(f"Core: {error}", file=sys.stderr)
    except (OSError, ValueError, KeyError) as error:
        print(f"Core failed: {type(error).__name__}: {error}", file=sys.stderr)
        if verbose:
            traceback.print_exc()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
