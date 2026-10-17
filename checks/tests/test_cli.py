"""Exercise every recipe with fake Nix and sudo, without workstation access."""

import errno
import json
import os
from pathlib import Path
import pty
import shutil
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(sys.argv.pop()).resolve()
FAKE = r"""
import json
import os
from pathlib import Path
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["CLI_TEST_LOG"], "a") as log:
    log.write(json.dumps({"command": name, "args": args,
                          "token": bool(os.environ.get("GITLAB_RUNNER_TOKEN")),
                          "no_color": "NO_COLOR" in os.environ}) + "\n")
if name == "sudo":
    keep = args.pop(0).removeprefix("--preserve-env=").split(",")
    environment = {key: os.environ[key] for key in
                   ("PATH", "CLI_TEST_LOG", "CLI_TEST_EXIT", "TERM")
                   if key in os.environ}
    environment.update({key: os.environ[key] for key in keep if key in os.environ})
    os.execvpe(args[0], args, environment)
print("fixture stdout")
print("fixture stderr", file=sys.stderr)
raise SystemExit(int(os.environ.get("CLI_TEST_EXIT", "0")))
"""


class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="cli fixtures ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.project = self.root / "project with spaces"
        (self.project / "lib/cli").mkdir(parents=True)
        # The Nix sandbox has no /usr/bin/env; keep each recipe intact while
        # selecting the same Bash interpreter from the isolated test PATH.
        (self.project / "Justfile").write_text(
            (SOURCE / "Justfile")
            .read_text()
            .replace("#!/usr/bin/env bash", f"#!{shutil.which('bash')}")
        )
        shutil.copyfile(SOURCE / "lib/cli/nix.sh", self.project / "lib/cli/nix.sh")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("nix", "sudo"):
            path = self.bin / name
            path.write_text(f"#!{sys.executable}\n" + FAKE)
            path.chmod(0o755)
        self.log = self.root / "commands.jsonl"

    def invoke(self, *args, terminal=False, environment=None):
        self.log.write_text("")
        env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "TERM": "xterm-256color",
            "CLI_TEST_LOG": str(self.log),
        } | (environment or {})
        command = ["just", "--justfile", str(self.project / "Justfile"), *args]
        if not terminal:
            return subprocess.run(command, env=env, capture_output=True, text=True)
        master, slave = pty.openpty()
        try:
            process = subprocess.Popen(
                command, env=env, stdout=subprocess.PIPE, stderr=slave
            )
            os.close(slave)
            slave = -1
            stdout, _ = process.communicate(timeout=15)
            chunks = []
            while True:
                try:
                    chunk = os.read(master, 4096)
                except OSError as error:
                    if error.errno == errno.EIO:
                        break
                    raise
                if not chunk:
                    break
                chunks.append(chunk)
            return subprocess.CompletedProcess(
                command, process.returncode, stdout.decode(), b"".join(chunks).decode()
            )
        finally:
            os.close(master)
            if slave >= 0:
                os.close(slave)

    def calls(self, name="nix"):
        return [
            call
            for line in self.log.read_text().splitlines()
            if (call := json.loads(line))["command"] == name
        ]

    def test_all_workflows_keep_diagnostics_and_arguments(self):
        for recipe, args, target, mode in (
            ("check", [], None, None),
            ("check-fast", [], ".#checks.x86_64-linux.source-format", None),
            ("build", [], ".#arch-workstation", None),
            ("check-arch", [], ".#arch-switch", "--check"),
            ("arch-workstation", [], ".#arch-workstation", None),
            ("arch-workstation", ["update"], ".#arch-workstation", "--update"),
            ("arch-workstation", ["purge"], ".#arch-workstation", "--purge"),
            ("arch-workstation", ["plan"], ".#arch-workstation", "--plan"),
            ("prepare-ai", [], ".#llama-prepare", None),
            ("prepare-ai", ["build"], ".#llama-prepare", "--build-only"),
            ("prepare-ai", ["model"], ".#llama-prepare", "--model-only"),
            ("prepare-runner", ["fixture"], ".#runnerctl", "reconcile"),
            ("initialize-runner", ["fixture"], ".#runnerctl", "register"),
            ("verify-runner", ["fixture"], ".#runnerctl", "verify"),
            ("status-runner", ["fixture"], ".#runnerctl", "status"),
        ):
            with self.subTest(recipe=recipe, args=args):
                result = self.invoke(
                    recipe,
                    *args,
                    environment={"GITLAB_RUNNER_TOKEN": "synthetic-test-only"},
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = self.calls()
                self.assertEqual(len(calls), 2 if recipe == "arch-workstation" else 1)
                for call in calls:
                    argv = call["args"]
                    self.assertEqual(argv[argv.index("--log-format") + 1], "raw")
                    self.assertIn("--show-trace", argv)
                    self.assertIn("--print-build-logs", argv)
                    if target:
                        self.assertIn(target, argv)
                if mode:
                    self.assertIn(mode, calls[-1]["args"])
                self.assertIn("fixture stdout", result.stdout)
                self.assertIn("fixture stderr", result.stderr)
                self.assertNotIn("synthetic-test-only", result.stdout + result.stderr)

    def test_terminal_log_format_and_plain_modes(self):
        for environment, options, expected in (
            ({}, [], "bar-with-logs"),
            ({"NO_COLOR": ""}, [], "raw"),
            ({"CI": "true"}, [], "raw"),
            ({"TERM": "dumb"}, [], "raw"),
            ({}, ["verbose"], "raw"),
            ({}, ["verbose", "update"], "raw"),
            ({}, ["update", "verbose"], "raw"),
        ):
            with self.subTest(environment=environment, options=options):
                result = self.invoke(
                    "arch-workstation", *options, terminal=True, environment=environment
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                for call in self.calls():
                    argv = call["args"]
                    self.assertEqual(argv[argv.index("--log-format") + 1], expected)
                    if "verbose" in options:
                        self.assertIn("--verbose", argv)

    def test_sudo_preserves_only_requested_display_and_registration_values(self):
        for recipe in ("prepare-runner", "initialize-runner", "verify-runner"):
            with self.subTest(recipe=recipe):
                result = self.invoke(
                    recipe,
                    "fixture",
                    environment={
                        "NO_COLOR": "1",
                        "GITLAB_RUNNER_TOKEN": "synthetic-test-only",
                    },
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                call = self.calls()[0]
                self.assertTrue(call["no_color"])
                self.assertEqual(call["token"], recipe == "initialize-runner")
                preserve = self.calls("sudo")[0]["args"][0]
                self.assertEqual(
                    preserve,
                    "--preserve-env=GITLAB_RUNNER_TOKEN,NO_COLOR"
                    if recipe == "initialize-runner"
                    else "--preserve-env=NO_COLOR",
                )

    def test_failed_build_does_not_launch_deployment(self):
        result = self.invoke("arch-workstation", environment={"CLI_TEST_EXIT": "75"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.calls()), 1)
        self.assertIn("fixture stderr", result.stderr)

    def test_invalid_options_do_not_launch_nix(self):
        for args in (
            ("arch-workstation", "update", "update"),
            ("arch-workstation", "plan", "update"),
            ("arch-workstation", "unknown"),
            ("prepare-ai", "unknown"),
            ("initialize-runner", "fixture"),
        ):
            with self.subTest(args=args):
                result = self.invoke(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
