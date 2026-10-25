# pyright: standard
"""Run the service startup guard against isolated cgroup fixtures."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GUARD = Path(sys.argv.pop()).resolve()
REGION = "drm/0000:03:00.0/vram"


class GuardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.hierarchy = self.root / "sys/fs/cgroup"
        self.slice = self.hierarchy / "system.slice"
        self.group = self.slice / "llama-swap.service"
        self.group.mkdir(parents=True)
        (self.root / "proc/self").mkdir(parents=True)
        (self.root / "proc/self/cgroup").write_text(
            "0::/system.slice/llama-swap.service\n"
        )
        for ancestor in (self.hierarchy, self.slice):
            (ancestor / "cgroup.controllers").write_text("cpu memory dmem\n")
            (ancestor / "cgroup.subtree_control").write_text("cpu\n")
        (self.group / "dmem.current").write_text(f"{REGION} 0\n")
        (self.group / "dmem.max").write_text(f"{REGION} max\n")
        self.policy = self.root / "policy.json"
        self.policy.write_text(json.dumps({"limitsMiB": {REGION: 173}}))

    def invoke(self):
        return subprocess.run(
            [sys.executable, str(GUARD), str(self.policy), "--root", str(self.root)],
            capture_output=True,
            text=True,
        )

    def test_controller_ancestors_and_limit_are_set_before_start(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (self.group / "dmem.max").read_text(), f"{REGION} {173 * 1024**2}\n"
        )
        for ancestor in (self.hierarchy, self.slice):
            self.assertEqual(
                (ancestor / "cgroup.subtree_control").read_text(), "+dmem\n"
            )

    def test_unavailable_controller_or_region_and_existing_allocations_fail(self):
        for path, value in (
            (self.slice / "cgroup.controllers", "cpu memory\n"),
            (self.group / "dmem.current", "drm/0000:09:00.0/vram 0\n"),
            (self.group / "dmem.current", f"{REGION} 4096\n"),
        ):
            original = path.read_text()
            with self.subTest(path=path, value=value):
                path.write_text(value)
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(
                    (self.group / "dmem.max").read_text(), f"{REGION} max\n"
                )
            path.write_text(original)

    def test_guard_cannot_modify_another_service_or_escape_the_hierarchy(self):
        for current in (
            "0::/system.slice/other.service\n",
            "0::/../llama-swap.service\n",
        ):
            with self.subTest(current=current):
                (self.root / "proc/self/cgroup").write_text(current)
                self.assertNotEqual(self.invoke().returncode, 0)
                self.assertEqual(
                    (self.group / "dmem.max").read_text(), f"{REGION} max\n"
                )

    def test_invalid_policy_is_rejected_before_controller_changes(self):
        for policy in (
            {"limitsMiB": {REGION: True}},
            {"limitsMiB": {REGION: -1}},
            {"limitsMiB": {"wrong": 173}},
            {"limitsMiB": {}},
            {"limitsMiB": {REGION: 173}, "unknown": True},
        ):
            with self.subTest(policy=policy):
                self.policy.write_text(json.dumps(policy))
                self.assertNotEqual(self.invoke().returncode, 0)
                self.assertEqual(
                    (self.hierarchy / "cgroup.subtree_control").read_text(), "cpu\n"
                )

    def test_failed_kernel_readback_does_not_permit_startup(self):
        # A regular file cannot retain both commands like the kernel interface.
        # This fixture deliberately drops the first command to exercise readback.
        second = "drm/0000:12:00.0/vram"
        (self.group / "dmem.current").write_text(f"{REGION} 0\n{second} 0\n")
        self.policy.write_text(json.dumps({"limitsMiB": {REGION: 173, second: 1}}))
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("readback", result.stderr)


if __name__ == "__main__":
    unittest.main()
