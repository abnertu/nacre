"""Delegate Runner policy through its configured public controller command."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict, cast

sys.dont_write_bytecode = True

from nix_adapter import AdapterContext, Change, Conflict, run_adapter_cli, validate
from nix_adapter.plan import Kind

# One reconciliation can include several independently bounded native operations.
COMMAND_TIMEOUT = 3600


class Manifest(TypedDict):
    """The feature's configured command and declared instance names."""

    executable: str
    instances: list[str]


class PlanItem(TypedDict):
    """One controller JSON change; reject drift in the public protocol."""

    kind: Kind
    text: str


def changes(output: str, instance: str) -> list[Change]:
    document: object = json.loads(output)
    if not isinstance(document, list):
        raise Conflict("Runner plan must be a JSON list")
    result: list[Change] = []
    for item in cast("list[object]", document):
        validate(PlanItem, item, "Runner plan item")
        entry = cast("dict[str, object]", item)
        kind, text = entry["kind"], entry["text"]
        if not isinstance(kind, str) or kind not in ("=", "~", "+", "!", "-"):
            raise Conflict("Runner plan has an invalid change kind")
        if not isinstance(text, str) or not text:
            raise Conflict("Runner plan has invalid change text")
        result.append(Change(kind, f"{instance}: {text}"))
    return result


class Runner:
    def __init__(self, desired: Mapping[str, object], context: AdapterContext):
        validate(Manifest, desired, "Runner manifest")
        executable, instances = desired["executable"], desired["instances"]
        if not isinstance(executable, str) or not Path(executable).is_absolute():
            raise Conflict("Runner executable must be an absolute path")
        if not isinstance(instances, list) or not instances:
            raise Conflict("Runner manifest requires instance names")
        names = cast("list[object]", instances)
        if not all(
            isinstance(name, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,17}", name)
            for name in names
        ):
            raise Conflict("Runner manifest has invalid instance names")
        checked = cast("list[str]", names)
        if len(checked) != len(set(checked)):
            raise Conflict("Runner manifest has duplicate instance names")
        self.instances = sorted(checked)
        self.command = [executable, *(["--verbose"] if context.verbose else [])]
        self.native = context.native(timeout=COMMAND_TIMEOUT)

    def invoke(self, phase: str, instance: str, *args: str) -> str:
        # Native supplies the fixed host environment. The controller redacts
        # its public diagnostics and owns native locks and pending markers.
        return self.native.run("env", *self.command, phase, instance, *args).stdout

    def preflight(self) -> None:
        for instance in self.instances:
            self.invoke("preflight", instance)

    def plan(self) -> list[Change]:
        result: list[Change] = []
        for instance in self.instances:
            result.extend(changes(self.invoke("plan", instance, "--json"), instance))
        return result

    def converge(self) -> None:
        # Recheck the whole set after package convergence before any mutation.
        self.preflight()
        for instance in self.instances:
            self.invoke("reconcile", instance)

    def purge(self) -> None:
        for instance in self.instances:
            self.invoke("purge", instance)


def main() -> int:
    try:
        return run_adapter_cli(Runner, name="GitLab Runner")
    except (Conflict, OSError, ValueError) as error:
        # Invocation and manifest validation precede the harness's phase handler.
        print(f"GitLab Runner: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
