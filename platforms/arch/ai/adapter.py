"""Privileged AI adapter entrypoint with explicit optional readiness status."""

from __future__ import annotations

import sys

# Runs as root from the read-only store: writing bytecode would modify it.
sys.dont_write_bytecode = True

from collections.abc import Mapping

import runtime
from nix_adapter import AdapterContext, run_adapter_cli, validate
from schema import AIManifest, Unmanaged


def load(desired: Mapping[str, object], context: AdapterContext) -> runtime.AI:
    schema = AIManifest if desired.get("llama") else Unmanaged
    return runtime.AI(validate(schema, desired, "AI manifest"), context=context)


def main() -> int:
    return run_adapter_cli(
        load,
        name="AI services",
        allow_skip=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
