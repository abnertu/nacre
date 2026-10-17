"""Privileged Arch system-settings adapter entrypoint."""

from __future__ import annotations

import sys

# Runs as root from the read-only store: writing bytecode would modify it.
sys.dont_write_bytecode = True

import runtime
from nix_adapter import run_adapter_cli, validate
from schema import SystemManifest


def main() -> int:
    return run_adapter_cli(
        lambda desired: runtime.System(
            validate(SystemManifest, desired, "system settings manifest")
        ),
        name="System settings",
    )


if __name__ == "__main__":
    raise SystemExit(main())
