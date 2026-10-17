"""Run the built nacre command against fake nix, sudo and Home Manager state."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

NACRE = sys.argv.pop()


class NacreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.flake = self.home / ".config/nix"
        self.flake.mkdir(parents=True)
        (self.flake / "flake.nix").write_text("{}")
        self.calls = self.root / "calls"
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        artifact = self.root / "artifact/bin"
        artifact.mkdir(parents=True)
        self.script(
            artifact / "fixture-deployment",
            f'echo "deploy $*" >> {self.calls}\nexit "${{DEPLOY_STATUS:-0}}"',
        )
        self.script(
            bin_dir / "nix",
            f'echo "nix $*" >> {self.calls}\n'
            '[[ -z ${NIX_STATUS:-} ]] || exit "$NIX_STATUS"\n'
            f'[[ " $* " != *" --print-out-paths "* ]] || echo {self.root / "artifact"}',
        )
        self.script(bin_dir / "sudo", f'echo "sudo $*" >> {self.calls}')
        self.env = {
            "HOME": str(self.home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "NO_COLOR": "1",
        }

    def script(self, path, body):
        path.write_text(f"#!{shutil.which('bash')}\n" + body + "\n")
        path.chmod(0o755)

    def run_nacre(self, *args, **env):
        return subprocess.run(
            [NACRE, *args], env=self.env | env, capture_output=True, text=True
        )

    def recorded(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def test_checkout_resolution(self):
        nacre = self.home / ".config/nacre"
        nacre.mkdir()
        (nacre / "flake.nix").write_text("{}")
        self.run_nacre("build")
        self.assertIn(f"{nacre}#fixture-deployment", self.recorded()[-1])
        self.run_nacre("build", NACRE_FLAKE=str(self.flake))
        self.assertIn(f"{self.flake}#fixture-deployment", self.recorded()[-1])
        result = self.run_nacre("--flake", str(self.root), "build")
        self.assertEqual(result.returncode, 2)
        self.assertIn("no checkout found", result.stderr)

    def test_deployment_modes_and_recorded_switches(self):
        state = self.home / ".local/state/nacre/last-switch"
        for command, expected in (
            ("plan", "deploy --plan"),
            ("purge", "deploy --purge"),
            ("switch", "deploy"),
        ):
            with self.subTest(command):
                state.unlink(missing_ok=True)
                result = self.run_nacre(command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.recorded()[-1].rstrip(), expected)
                self.assertEqual(state.exists(), command == "switch")
        state.unlink()
        result = self.run_nacre("--verbose", "update", DEPLOY_STATUS="3")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(self.recorded()[-1], "deploy --update --verbose")
        self.assertFalse(state.exists())

    def test_failed_build_never_deploys(self):
        result = self.run_nacre("switch", NIX_STATUS="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call.startswith("deploy") for call in self.recorded()))

    def test_rollback_activates_an_earlier_home_generation(self):
        profiles = self.home / ".local/state/nix/profiles"
        profiles.mkdir(parents=True)
        for number in (3, 5, 7):
            generation = self.root / f"generation-{number}"
            generation.mkdir()
            self.script(
                generation / "activate",
                f'echo "activate {number} $*" >> {self.calls}  # --driver-version',
            )
            (profiles / f"home-manager-{number}-link").symlink_to(generation)
        (profiles / "home-manager").symlink_to("home-manager-7-link")
        self.assertEqual(self.run_nacre("rollback").returncode, 0)
        self.assertEqual(self.recorded(), ["activate 5 --driver-version 0"])
        self.run_nacre("rollback", "3")
        self.assertEqual(self.recorded()[-1], "activate 3 --driver-version 0")
        (profiles / "home-manager").unlink()
        (profiles / "home-manager").symlink_to("home-manager-3-link")
        result = self.run_nacre("rollback")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no home generation", result.stderr)

    def test_runner_registration_requires_a_token(self):
        result = self.run_nacre("runner", "register", "frontend")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.recorded(), [])
        self.run_nacre("runner", "register", "frontend", GITLAB_RUNNER_TOKEN="x")
        call = self.recorded()[-1]
        self.assertIn("--preserve-env=GITLAB_RUNNER_TOKEN,NO_COLOR", call)
        self.assertTrue(call.endswith("-- register frontend"))
        self.run_nacre("runner", "prepare", "frontend")
        self.assertTrue(self.recorded()[-1].endswith("-- reconcile frontend"))

    def test_usage_errors_run_nothing(self):
        for args in (
            (),
            ("bogus",),
            ("switch", "extra"),
            ("ai", "prepare", "everything"),
            ("rollback", "latest"),
        ):
            with self.subTest(args):
                self.assertEqual(self.run_nacre(*args).returncode, 2)
        self.assertEqual(self.recorded(), [])


if __name__ == "__main__":
    unittest.main()
