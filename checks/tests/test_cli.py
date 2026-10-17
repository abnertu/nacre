"""Exercise every development recipe with fake Nix, without workstation access."""

import errno
import json
import os
import pty
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(sys.argv.pop()).resolve()
FAKE = r"""
import json
import os
from pathlib import Path
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["CLI_TEST_LOG"], "a") as log:
    log.write(json.dumps({"command": name, "args": args}) + "\n")
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
        path = self.bin / "nix"
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
        ):
            with self.subTest(recipe=recipe, args=args):
                result = self.invoke(recipe, *args)
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = self.calls()
                self.assertEqual(len(calls), 1)
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

    def test_terminal_log_format_and_plain_modes(self):
        for environment, expected in (
            ({}, "bar-with-logs"),
            ({"NO_COLOR": ""}, "raw"),
            ({"CI": "true"}, "raw"),
            ({"TERM": "dumb"}, "raw"),
        ):
            with self.subTest(environment=environment):
                result = self.invoke("build", terminal=True, environment=environment)
                self.assertEqual(result.returncode, 0, result.stderr)
                argv = self.calls()[0]["args"]
                self.assertEqual(argv[argv.index("--log-format") + 1], expected)


if __name__ == "__main__":
    unittest.main()
