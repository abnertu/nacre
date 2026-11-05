"""plan, switch, update and purge: build the deployment and run it."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .common import now, revision
from .doctor import doctor
from .machine import Machine, append_record, write_record

MODES = ("plan", "switch", "update", "purge")
FLAGS = {"plan": ["--plan"], "update": ["--update"], "purge": ["--purge"]}


def deploy(machine: Machine, mode: str) -> int:
    """Build #deployment and run it in `mode`; return its exit status.

    A successful switch or update records the checkout revision. An update
    also runs doctor afterwards, because kernels, units and replaced files
    change then; the update's own exit status stays the result.
    """
    status, artifact = machine.build_deployment()
    if status != 0:
        return status
    if mode == "update":
        # Recorded before running: a stopped update has still upgraded packages.
        append_record("updates", now())
    status = run_deployment(machine, artifact, mode)
    if status == 0 and mode in ("switch", "update"):
        write_record("last-switch", f"{now()} {revision(machine.flake)} {artifact}")
    if mode == "update":
        print("\nAfter the update:", file=sys.stderr)
        sys.stderr.flush()
        doctor(machine)
    return status


def run_deployment(machine: Machine, artifact: str, mode: str) -> int:
    """Run the deployment program of `artifact` in `mode`."""
    args = FLAGS.get(mode, []) + (["--verbose"] if machine.verbose else [])
    # The deployment's only program is named after the machine.
    (program,) = Path(artifact, "bin").iterdir()
    return subprocess.run([str(program), *args], check=False).returncode
