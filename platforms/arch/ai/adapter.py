"""Privileged AI adapter entrypoint with explicit optional readiness status."""

from __future__ import annotations

import sys

# Runs as root from the read-only store: writing bytecode would modify it.
sys.dont_write_bytecode = True

from nix_adapter import run_adapter_cli
import runtime


def main() -> int:
    return run_adapter_cli(
        lambda desired: runtime.AI(desired),
        name="AI services",
        allow_skip=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
