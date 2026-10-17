"""Privileged Arch core adapter entrypoint."""

from __future__ import annotations

import sys

# Runs as root from the read-only store: writing bytecode would modify it.
sys.dont_write_bytecode = True

from nix_adapter import run_adapter_cli, validate
from runtime import Core
from schema import CoreManifest

if __name__ == "__main__":
    raise SystemExit(
        run_adapter_cli(
            lambda desired: Core(validate(CoreManifest, desired, "core manifest")),
            "Core",
            phases=("repositories", "finish"),
        )
    )
