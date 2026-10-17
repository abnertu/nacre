"""Focused orchestration tests for optional modules and verbose adapters."""

import importlib.util
import os
import pty
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

SOURCE = Path(sys.argv.pop()).resolve()
BASE_TEST = Path(__file__).with_name("test_arch_switch.py")
sys.argv.append(str(SOURCE))
spec = importlib.util.spec_from_file_location("arch_switch_base", BASE_TEST)
assert spec is not None and spec.loader is not None
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


class OptionalLifecycleTests(unittest.TestCase):
    state: dict[str, Any]
    root: Path
    script: Path
    setUp = base.ArchSwitchTests.setUp
    save = base.ArchSwitchTests.save
    invoke = base.ArchSwitchTests.invoke
    commands = base.ArchSwitchTests.commands

    def test_unprepared_ai_is_skipped_with_high_visibility_warning(self):
        self.state["ai_not_ready"] = True
        self.save()
        result = self.invoke()
        self.assertIn("SKIP optional module ai:", result.stderr)
        self.assertNotIn("\x1b[", result.stderr)
        ai_calls = [
            call
            for call in self.commands()
            if call[:2] == ["python", "/fixture/ai-adapter"]
        ]
        self.assertEqual(
            ai_calls,
            [["python", "/fixture/ai-adapter", "/fixture/ai-manifest", "preflight"]],
        )
        self.assertIn("User services converged:", result.stdout)

    def test_empty_no_color_keeps_optional_skip_plain_on_a_terminal(self):
        self.state["ai_not_ready"] = True
        self.save()
        master, slave = pty.openpty()
        try:
            result = subprocess.run(
                ["bash", str(self.script)],
                stdout=subprocess.PIPE,
                stderr=slave,
                env={
                    **os.environ,
                    "ARCH_TEST_ROOT": str(self.root),
                    "TERM": "xterm-256color",
                    "NO_COLOR": "",
                },
                timeout=30,
            )
            os.close(slave)
            slave = -1
            chunks = []
            while True:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                chunks.append(chunk)
            output = b"".join(chunks)
            self.assertEqual(result.returncode, 0, output)
            self.assertIn(b"SKIP optional module ai:", output)
            self.assertNotIn(b"\x1b[", output)
        finally:
            os.close(master)
            if slave >= 0:
                os.close(slave)

    def test_verbose_reaches_both_privileged_adapters(self):
        self.invoke("--verbose")
        adapter_calls = [
            call for call in self.commands() if call and call[0] == "python"
        ]
        self.assertTrue(adapter_calls)
        self.assertTrue(all(call[-1] == "--verbose" for call in adapter_calls))

    def test_unprepared_personal_agent_is_skipped(self):
        self.state["personal_agent_not_ready"] = True
        self.save()
        result = self.invoke()
        self.assertIn("SKIP optional module personal-agent:", result.stderr)
        calls = [
            call
            for call in self.commands()
            if call[:2] == ["python", "/fixture/personal-agent-adapter"]
        ]
        self.assertEqual(
            calls,
            [
                [
                    "python",
                    "/fixture/personal-agent-adapter",
                    "/fixture/personal-agent-manifest",
                    "preflight",
                ]
            ],
        )

    def test_ready_module_cannot_become_a_skip_during_convergence(self):
        for key, label in (
            ("ai_converge_not_ready", "AI preparation changed after preflight"),
            (
                "personal_agent_converge_not_ready",
                "Personal Agent configuration changed after preflight",
            ),
        ):
            with self.subTest(key=key):
                self.state[key] = True
                self.save()
                result = self.invoke(code=1)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(label, result.stderr)
                self.assertNotIn("SKIP optional module", result.stderr)
                self.state.pop(key)


if __name__ == "__main__":
    unittest.main()
