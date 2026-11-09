# pyright: standard
"""Focused orchestration tests for optional modules and verbose adapters."""

import importlib.util
import json
import os
import pty
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

SOURCE = Path(sys.argv.pop()).resolve()
PACKAGES = [Path(value) for value in sys.argv[1:]]
del sys.argv[1:]
BASE_TEST = Path(__file__).with_name("test_arch_switch.py")
sys.argv.append(str(SOURCE))
spec = importlib.util.spec_from_file_location("arch_switch_base", BASE_TEST)
assert spec is not None and spec.loader is not None
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


class OptionalLifecycleTests(unittest.TestCase):
    state: dict[str, Any]
    root: Path
    setUp = base.ArchSwitchTests.setUp
    write_config = base.ArchSwitchTests.write_config
    command = base.ArchSwitchTests.command
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
                self.command(),
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

    def extension_phases(self):
        prefix = ["python", "/fixture/extension-adapter", "/fixture/extension-manifest"]
        return [call[3] for call in self.commands() if call[:3] == prefix]

    def test_extension_waits_for_its_required_module_and_preparation(self):
        for key, phases, reason in (
            ("ai_not_ready", [], "ai is not ready"),
            ("extension_not_ready", ["preflight"], "fixture service is not prepared"),
        ):
            with self.subTest(key=key):
                (self.root / "commands.jsonl").unlink(missing_ok=True)
                self.state = {"groups": ["wheel"], key: True}
                self.save()
                result = self.invoke()
                self.assertIn(
                    f"SKIP optional module fixture-service: {reason}", result.stderr
                )
                self.assertEqual(self.extension_phases(), phases)

    def test_ready_extension_plans_and_converges_after_ai(self):
        self.invoke("--plan")
        self.assertEqual(self.extension_phases(), ["preflight", "plan"])
        (self.root / "commands.jsonl").unlink()
        self.invoke()
        self.assertEqual(self.extension_phases(), ["preflight", "converge"])
        calls = self.commands()
        self.assertLess(
            calls.index(
                ["python", "/fixture/ai-adapter", "/fixture/ai-manifest", "converge"]
            ),
            calls.index(
                [
                    "python",
                    "/fixture/extension-adapter",
                    "/fixture/extension-manifest",
                    "converge",
                ]
            ),
        )

    def test_ready_module_cannot_become_a_skip_during_convergence(self):
        for key, label in (
            ("ai_converge_not_ready", "AI preparation changed after preflight"),
            ("extension_converge_not_ready", "fixture-service changed after preflight"),
        ):
            with self.subTest(key=key):
                self.state[key] = True
                self.save()
                result = self.invoke(code=1)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(label, result.stderr)
                self.assertNotIn("SKIP optional module", result.stderr)
                self.state.pop(key)

    def test_purge_runs_opted_in_extensions_before_builtins_without_preflight(self):
        first = self.config["extensions"][0]
        first["purge"] = True
        second = {**first, "name": "second"}
        self.config["extensions"].append(second)
        self.config["adapters"]["second"] = {
            "adapter": "/fixture/second-adapter",
            "manifest": "/fixture/second-manifest",
        }
        self.state["ai_not_ready"] = True
        self.save()
        self.write_config()
        self.invoke("--purge", "--verbose")
        calls = [call for call in self.commands() if call[0] == "python"]
        self.assertEqual(
            [(call[1], call[3:]) for call in calls],
            [
                ("/fixture/extension-adapter", ["purge", "--verbose"]),
                ("/fixture/second-adapter", ["purge", "--verbose"]),
                ("/fixture/ai-adapter", ["purge", "--verbose"]),
                ("/fixture/system-adapter", ["purge", "--verbose"]),
                ("/fixture/core-adapter", ["purge", "--verbose"]),
            ],
        )

    def test_extension_purge_failure_stops_later_retirement(self):
        self.config["extensions"][0]["purge"] = True
        self.config["extensions"].append(
            {**self.config["extensions"][0], "name": "later"}
        )
        self.config["adapters"]["later"] = self.config["adapters"]["extension"]
        self.write_config()
        for failure, code in (("fail", 1), ("extension_not_ready", 20)):
            with self.subTest(failure=failure):
                (self.root / "commands.jsonl").unlink(missing_ok=True)
                self.state = {"groups": ["wheel"]}
                self.state[failure] = (
                    ["python", "/fixture/extension-adapter"]
                    if failure == "fail"
                    else True
                )
                self.save()
                result = self.invoke("--purge", code=code)
                self.assertNotIn("SKIP", result.stderr)
                self.assertEqual(
                    [call for call in self.commands() if call[0] == "python"],
                    [
                        [
                            "python",
                            "/fixture/extension-adapter",
                            "/fixture/extension-manifest",
                            "purge",
                        ]
                    ],
                )

    def test_packaged_extension_purge_policy(self):
        self.assertEqual(
            len(PACKAGES), 2, "pass default and opted-in arch-switch packages"
        )
        synthetic = self.config
        for package, opted_in in zip(PACKAGES, (False, True), strict=True):
            with self.subTest(opted_in=opted_in):
                (self.root / "commands.jsonl").unlink(missing_ok=True)
                packaged_config = package / "share/arch-switch/config.json"
                self.config = json.loads(packaged_config.read_text())
                # Keep generated extensions and their purge policy. Replace only
                # host and command boundaries before executing the real CLI.
                for key in ("fsRoot", "nativeBin", "adapterPython", "expectedUser"):
                    self.config[key] = synthetic[key]
                self.config["adapters"] = {
                    name: synthetic["adapters"][
                        name if name in ("core", "system", "ai") else "extension"
                    ]
                    for name in self.config["adapters"]
                }
                self.write_config()
                self.invoke("--purge", "--verbose")
                self.assertEqual(self.extension_phases(), ["purge"] if opted_in else [])


if __name__ == "__main__":
    unittest.main()
