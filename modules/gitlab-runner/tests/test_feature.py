# pyright: standard
"""Run generated Runner wiring through the Arch CLI with fake native commands."""

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

SOURCE = Path(sys.argv.pop()).resolve()
BASE_TEST = Path(sys.argv.pop()) / "test_arch_switch.py"
NATIVE_BIN = sys.argv.pop() + "/"
ENABLED, DISABLED, ENABLED_CLI, DISABLED_CLI = map(Path, sys.argv[1:])
del sys.argv[1:]
sys.argv.append(str(SOURCE))
spec = importlib.util.spec_from_file_location("runner_arch_base", BASE_TEST)
assert spec is not None and spec.loader is not None
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


class FeatureTests(unittest.TestCase):
    state: dict[str, Any]
    root: Path
    setUp = base.ArchSwitchTests.setUp
    write_config = base.ArchSwitchTests.write_config
    command = base.ArchSwitchTests.command
    save = base.ArchSwitchTests.save
    invoke = base.ArchSwitchTests.invoke
    commands = base.ArchSwitchTests.commands

    def select(self, package):
        synthetic = self.config
        self.config = json.loads(
            (package / "share/arch-switch/config.json").read_text()
        )
        for key in (
            "fsRoot",
            "nativeBin",
            "adapterPython",
            "expectedUser",
            "curl",
            "tar",
        ):
            self.config[key] = synthetic[key]
        self.config["adapters"] = {
            name: (
                {
                    "adapter": "/fixture/second-adapter",
                    "manifest": "/fixture/second-manifest",
                }
                if name == "gitlab-runner"
                else synthetic["adapters"][
                    name if name in ("core", "system", "ai") else "extension"
                ]
            )
            for name in self.config["adapters"]
        }
        self.write_config()

    def runner_phases(self):
        return [
            call[3]
            for call in self.commands()
            if call[:2] == ["python", "/fixture/second-adapter"]
        ]

    def reset(self):
        (self.root / "commands.jsonl").unlink(missing_ok=True)

    def test_operator_outputs_validate_the_full_set_with_deployment_enabled_or_disabled(
        self,
    ):
        for command in (ENABLED_CLI, DISABLED_CLI):
            result = subprocess.run(
                [str(command), "validate"], text=True, capture_output=True, check=True
            )
            self.assertEqual(json.loads(result.stdout), ["dotnet", "frontend"])

    def test_generated_manifest_and_adapter_execute_the_configured_controller(self):
        config = json.loads((ENABLED / "share/arch-switch/config.json").read_text())
        entry = config["adapters"]["gitlab-runner"]
        spec = importlib.util.spec_from_file_location(
            "packaged_runner", entry["adapter"]
        )
        assert spec is not None and spec.loader is not None
        packaged = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(packaged)
        stdout = io.StringIO()
        with (
            patch.object(sys, "argv", [entry["adapter"], entry["manifest"], "plan"]),
            patch("nix_adapter.native.COMMAND_DIRECTORY", NATIVE_BIN),
            patch("nix_adapter.cli.os.geteuid", return_value=0),
            contextlib.redirect_stdout(stdout),
        ):
            self.assertEqual(packaged.main(), 0)
        self.assertIn("= dotnet: synthetic configured controller", stdout.getvalue())
        self.assertIn("= frontend: synthetic configured controller", stdout.getvalue())

    def test_enabled_runner_is_independent_of_ai_and_purge_does_not_preflight(self):
        self.select(ENABLED)
        self.state["ai_not_ready"] = True
        self.save()
        for arguments, expected in (
            (["--plan"], ["preflight", "plan"]),
            ([], ["preflight", "converge"]),
            (["--purge"], ["purge"]),
        ):
            with self.subTest(arguments=arguments):
                self.reset()
                self.invoke(*arguments)
                self.assertEqual(self.runner_phases(), expected)

    def test_disabled_deployment_never_invokes_runner_in_any_mode(self):
        self.select(DISABLED)
        for arguments in (["--plan"], [], ["--purge"]):
            with self.subTest(arguments=arguments):
                self.reset()
                self.invoke(*arguments)
                self.assertEqual(self.runner_phases(), [])

    def test_missing_packages_block_switch_and_update_installs_before_runner(self):
        self.select(ENABLED)
        self.state["missing"] = ["podman"]
        self.save()
        self.invoke(code=3)
        self.assertEqual(self.runner_phases(), [])
        self.reset()
        self.invoke("--update")
        calls = self.commands()
        install = next(
            i
            for i, call in enumerate(calls)
            if call[0] == "pacman" and "--sysupgrade" in call
        )
        converge = next(
            i
            for i, call in enumerate(calls)
            if call[:2] == ["python", "/fixture/second-adapter"]
            and call[3] == "converge"
        )
        self.assertLess(install, converge)

    def test_runner_preflight_and_retirement_failures_stop_later_core_work(self):
        self.select(ENABLED)
        self.state["fail"] = ["python", "/fixture/second-adapter"]
        self.save()
        for arguments, phase in (([], "preflight"), (["--purge"], "purge")):
            with self.subTest(arguments=arguments):
                self.reset()
                result = self.invoke(*arguments, code=1)
                self.assertNotIn("SKIP optional module GitLab Runner", result.stderr)
                self.assertEqual(self.runner_phases(), [phase])
                core_phases = [
                    call[3]
                    for call in self.commands()
                    if call[:2] == ["python", "/fixture/core-adapter"]
                ]
                self.assertNotIn("finish", core_phases)
                self.assertNotIn("purge", core_phases)


if __name__ == "__main__":
    unittest.main()
