"""Apply declared device-memory limits before the model router starts."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import TypedDict, cast

MIB = 1024**2


class Policy(TypedDict):
    limitsMiB: dict[str, int]


def load_policy(path: Path) -> Policy:
    value: object = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("device-memory policy must be an object")
    fields = cast(dict[object, object], value)
    if set(fields) != {"limitsMiB"}:
        raise ValueError("device-memory policy requires limitsMiB")
    limits = fields["limitsMiB"]
    if not isinstance(limits, dict) or not limits:
        raise ValueError("device-memory limits must be a nonempty object")
    for region, amount in cast(dict[object, object], limits).items():
        if not isinstance(region, str) or not re.fullmatch(
            r"drm/[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]/vram[0-9]*", region
        ):
            raise ValueError("invalid device-memory region")
        if type(amount) is not int or amount <= 0:
            raise ValueError("device-memory limits must be positive integer MiB")
    return cast(Policy, value)


def counters(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        region, amount = line.split()
        if region in values:
            raise ValueError("duplicate device-memory region")
        values[region] = amount
    return values


def apply(policy: Policy, root: Path, unit: str) -> None:
    """Set the policy's dmem.max limits on the cgroup of `unit` before it allocates.

    Raise `ValueError` unless the guard runs in its own service cgroup of a
    unified hierarchy with the dmem controller, the group holds no device
    memory yet, and the kernel reads the limits back unchanged.
    """
    hierarchy = root / "sys/fs/cgroup"
    relative = service_cgroup(root, unit)
    group = hierarchy / relative
    if group.is_symlink() or not group.resolve().is_relative_to(hierarchy.resolve()):
        raise ValueError("service cgroup escapes the hierarchy")
    enable_dmem(hierarchy, relative)
    limits = policy["limitsMiB"]
    current = counters(group / "dmem.current")
    if not set(limits) <= current.keys():
        raise ValueError("a declared device-memory region is unavailable")
    if any(int(current[region]) for region in limits):
        raise ValueError(
            "service has device-memory allocations before its startup guard"
        )
    target = group / "dmem.max"
    for region, amount in limits.items():
        target.write_text(f"{region} {amount * MIB}\n")
    configured = counters(target)
    if any(
        configured.get(region) != str(amount * MIB) for region, amount in limits.items()
    ):
        raise ValueError("device-memory limit readback differs from policy")


def service_cgroup(root: Path, unit: str) -> Path:
    """This process's cgroup, relative to the hierarchy; it must be `unit`'s own."""
    entries = (root / "proc/self/cgroup").read_text().splitlines()
    if len(entries) != 1 or not entries[0].startswith("0::/"):
        raise ValueError("a unified cgroup hierarchy is required")
    relative = Path(entries[0][4:])
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.name != unit
        or any(not part.endswith(".slice") for part in relative.parts[:-1])
    ):
        raise ValueError("guard must run inside its declared service cgroup")
    return relative


def enable_dmem(hierarchy: Path, relative: Path) -> None:
    """Enable the dmem controller in every ancestor of the service cgroup."""
    parent = hierarchy
    for part in relative.parts:
        if "dmem" not in (parent / "cgroup.controllers").read_text().split():
            raise ValueError("dmem controller is unavailable in a service ancestor")
        control = parent / "cgroup.subtree_control"
        if "dmem" not in control.read_text().split():
            control.write_text("+dmem\n")
        parent /= part


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("policy", type=Path)
    parser.add_argument(
        "--root", type=Path, default=Path("/"), help="Use an isolated fixture root."
    )
    parser.add_argument("--unit", default="llama-swap.service")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_-]+\.service", args.unit):
        parser.error("unit must be a simple service name")
    if args.root == Path("/") and os.geteuid() != 0:
        parser.error("live service limits require root")
    try:
        apply(load_policy(args.policy), args.root, args.unit)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Device-memory startup guard failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
