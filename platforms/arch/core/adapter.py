"""Privileged Arch core adapter entrypoint."""

from __future__ import annotations

import sys

# Runs as root from the read-only store: writing bytecode would modify it.
sys.dont_write_bytecode = True

import runtime
from nix_adapter import run_adapter_cli

if __name__ == "__main__":
    raise SystemExit(
        run_adapter_cli(runtime.Core, "Core", phases=("repositories", "finish"))
    )
