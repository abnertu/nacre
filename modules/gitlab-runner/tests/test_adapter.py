# pyright: standard
"""Exercise the adapter CLI against a real, isolated controller executable."""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(sys.argv.pop()).resolve()
NATIVE_BIN = sys.argv.pop() + "/"
spec = importlib.util.spec_from_file_location("runner_adapter", SOURCE)
assert spec is not None and spec.loader is not None
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)

CONTROLLER = """
import json
import sys
import time
from pathlib import Path

root = Path(__file__).parent
args = sys.argv[1:]
with (root / "calls.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\\n")
scenario = json.loads((root / "scenario.json").read_text())
phase, instance, *rest = [arg for arg in args if arg != "--verbose"]
if scenario.get("failure") in (phase, phase + ":" + instance):
    print("public stdout <redacted>", flush=True)
    print("public stderr <redacted>", file=sys.stderr, flush=True)
    if scenario.get("timeout"):
        time.sleep(2)
    sys.exit(scenario.get("exit", 23))
if phase == "plan":
    assert rest == ["--json"]
    print(scenario.get("plan", '[{"kind": "+", "text": "prepare public policy"}, {"kind": "-", "text": "runtime deferred"}]'))
else:
    assert not rest
"""


class AdapterTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.controller = self.root / "synthetic controller"
        self.controller.write_text(f"#!{sys.executable}\n" + CONTROLLER)
        self.controller.chmod(0o755)
        self.manifest = {
            "executable": str(self.controller),
            "instances": ["frontend", "dotnet"],
        }
        self.scenario = {}
        self.addCleanup(patch.stopall)
        patch("nix_adapter.native.COMMAND_DIRECTORY", NATIVE_BIN).start()
        patch("nix_adapter.cli.os.geteuid", return_value=0).start()

    def invoke(self, phase, *flags, code=0):
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps(self.manifest))
        (self.root / "scenario.json").write_text(json.dumps(self.scenario))
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.object(sys, "argv", [str(SOURCE), str(manifest), phase, *flags]),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            result = adapter.main()
        self.assertEqual(result, code, stdout.getvalue() + stderr.getvalue())
        return stdout.getvalue(), stderr.getvalue()

    def calls(self):
        path = self.root / "calls.jsonl"
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )

    def reset(self):
        (self.root / "calls.jsonl").unlink(missing_ok=True)

    def test_previews_only_inspect_and_convergence_rechecks_the_complete_set(self):
        for phase, expected in (
            ("preflight", [["preflight", "dotnet"], ["preflight", "frontend"]]),
            ("plan", [["plan", "dotnet", "--json"], ["plan", "frontend", "--json"]]),
            (
                "converge",
                [
                    ["preflight", "dotnet"],
                    ["preflight", "frontend"],
                    ["reconcile", "dotnet"],
                    ["reconcile", "frontend"],
                ],
            ),
            ("purge", [["purge", "dotnet"], ["purge", "frontend"]]),
        ):
            with self.subTest(phase=phase):
                self.reset()
                self.invoke(phase)
                self.assertEqual(self.calls(), expected)
                self.assertEqual(
                    set(path.name for path in self.root.iterdir()),
                    {
                        "synthetic controller",
                        "manifest.json",
                        "scenario.json",
                        "calls.jsonl",
                    },
                )

    def test_plan_renders_controller_changes_and_deferred_observations(self):
        stdout, _ = self.invoke("plan", "--color")
        self.assertIn("+ dotnet: prepare public policy", stdout)
        self.assertIn("- frontend: runtime deferred", stdout)
        self.assertIn("\x1b[", stdout)
        self.scenario["plan"] = '[{"kind":"!","text":"synthetic ownership conflict"}]'
        stdout, _ = self.invoke("plan", code=1)
        self.assertIn("! dotnet: synthetic ownership conflict", stdout)

    def test_verbose_is_global_and_reaches_every_controller_operation(self):
        self.invoke("converge", "--verbose")
        self.assertTrue(self.calls())
        self.assertTrue(all(call[0] == "--verbose" for call in self.calls()))
        self.assertEqual(
            [call[1] for call in self.calls()],
            ["preflight", "preflight", "reconcile", "reconcile"],
        )

    def test_controller_failure_never_becomes_a_preparation_skip(self):
        for phase, operation in (
            ("preflight", "preflight"),
            ("plan", "plan"),
            ("converge", "reconcile"),
            ("purge", "purge"),
        ):
            for status in (1, 20, 23):
                with self.subTest(phase=phase, status=status):
                    self.reset()
                    self.scenario = {"failure": operation + ":dotnet", "exit": status}
                    stdout, stderr = self.invoke(phase, code=1)
                    output = stdout + stderr
                    self.assertIn(f"exit {status}", output)
                    self.assertIn("public stdout <redacted>", output)
                    self.assertIn("public stderr <redacted>", output)
                    self.assertNotIn([operation, "frontend"], self.calls())

    def test_changed_preflight_stops_all_reconciliation(self):
        self.scenario = {"failure": "preflight:frontend"}
        self.invoke("converge", code=1)
        self.assertEqual(
            self.calls(), [["preflight", "dotnet"], ["preflight", "frontend"]]
        )

    def test_timeout_retains_partial_controller_diagnostics(self):
        self.scenario = {"failure": "preflight:dotnet", "timeout": True}
        with patch.object(adapter, "COMMAND_TIMEOUT", 1):
            _, stderr = self.invoke("preflight", code=1)
        self.assertIn("timed out", stderr)
        self.assertIn("public stdout <redacted>", stderr)
        self.assertIn("public stderr <redacted>", stderr)
        self.assertEqual(self.calls(), [["preflight", "dotnet"]])

    def test_manifest_schema_and_values_fail_before_controller_execution(self):
        original = self.manifest.copy()
        for manifest in (
            {**original, "unknown": True},
            {"executable": str(self.controller)},
            {**original, "executable": "relative/runnerctl"},
            {**original, "executable": 123},
            {**original, "instances": []},
            {**original, "instances": "frontend"},
            {**original, "instances": ["frontend", "frontend"]},
            {**original, "instances": ["--invalid"]},
            {**original, "instances": [123]},
        ):
            with self.subTest(manifest=manifest):
                self.manifest = manifest
                self.invoke("converge", code=1)
                self.assertEqual(self.calls(), [])

    def test_json_protocol_drift_stops_the_plan(self):
        for document in (
            "invalid JSON",
            "{}",
            "[null]",
            '[{"kind":"+"}]',
            '[{"kind":"+","text":"valid","unknown":1}]',
            '[{"kind":[],"text":"valid"}]',
            '[{"kind":"?","text":"valid"}]',
            '[{"kind":"+","text":123}]',
            '[{"kind":"+","text":""}]',
        ):
            with self.subTest(document=document):
                self.reset()
                self.scenario = {"plan": document}
                self.invoke("plan", code=1)
                self.assertEqual(self.calls(), [["plan", "dotnet", "--json"]])


if __name__ == "__main__":
    unittest.main()
