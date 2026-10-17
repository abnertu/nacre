"""Execute deployment entry points with isolated fake stages only."""

from pathlib import Path
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

HOME = Path(sys.argv.pop()).read_text()
DEPLOY = Path(sys.argv.pop()).read_text()


class DeploymentTests(unittest.TestCase):
    def test_order_and_argument_rejection_before_arch(self):
        for status, args in (
            (0, []),
            (3, []),
            (75, ["--update"]),
            (0, ["--verbose"]),
            (0, ["--purge"]),
            (0, ["-b", "backup"]),
            (0, ["--flake", "other"]),
            (0, ["--dry-run"]),
        ):
            with (
                self.subTest(status=status, args=args),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                for name, body in (
                    ("arch", f"echo arch >> {root}/calls\nexit {status}"),
                    ("home", f"echo home >> {root}/calls"),
                ):
                    path = root / name
                    path.write_text(f"#!{shutil.which('bash')}\n" + body)
                    path.chmod(0o755)
                script = (
                    f"set -euo pipefail\ndeployment_name=fixture\narch_switch={root}/arch\nhome_switch={root}/home\n"
                    + DEPLOY
                )
                result = subprocess.run(
                    ["bash", "-c", script, "deploy", *args], capture_output=True
                )
                rejected = args and args[0] not in ("--update", "--verbose", "--purge")
                self.assertEqual(result.returncode, 2 if rejected else status)
                calls = (
                    (root / "calls").read_text().splitlines()
                    if (root / "calls").exists()
                    else []
                )
                self.assertEqual(
                    calls,
                    []
                    if rejected
                    else ["arch"]
                    if status or args == ["--purge"]
                    else ["arch", "home"],
                )

    def test_plan_previews_both_stages_and_never_activates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("arch", "home"):
                path = root / name
                path.write_text(
                    f"#!{shutil.which('bash')}\n"
                    + f'echo "{name} $*" >> {root}/calls\n'
                )
                path.chmod(0o755)
            script = (
                f"set -euo pipefail\ndeployment_name=fixture\narch_switch={root}/arch\nhome_switch={root}/home\n"
                + DEPLOY
            )
            result = subprocess.run(
                ["bash", "-c", script, "deploy", "--plan"], capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (root / "calls").read_text().splitlines(),
                ["arch --plan", "home --plan"],
            )
            result = subprocess.run(
                ["bash", "-c", script, "deploy", "--plan", "--update"],
                capture_output=True,
            )
            self.assertEqual(result.returncode, 2)

    def test_home_plan_compares_the_active_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generation = root / "generation"
            (generation).mkdir()
            (generation / "activate").write_text(f"#!{shutil.which('bash')}\nexit 9\n")
            (generation / "activate").chmod(0o755)
            profile = root / "state/nix/profiles/home-manager"
            profile.parent.mkdir(parents=True)
            script = (
                f"set -euo pipefail\nactivation_package={shlex.quote(str(generation))}\n"
                + HOME
            )
            env = {**os.environ, "XDG_STATE_HOME": str(root / "state"), "NO_COLOR": ""}
            for target, expected in (
                (root, "~ Home Manager activates"),
                (generation, "= Home Manager generation unchanged"),
            ):
                profile.unlink(missing_ok=True)
                profile.symlink_to(target)
                result = subprocess.run(
                    ["bash", "-c", script, "home", "--plan"],
                    env=env,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout.startswith(expected), result.stdout)

    def test_home_activates_exact_generation_with_profile_managing_driver(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activation = root / "activate"
            activation.write_text(
                f"#!{shutil.which('bash')}\n"
                + "[[ ! -v HOME_MANAGER_BACKUP_EXT && ! -v SKIP_SANITY_CHECKS ]]\n"
                + f'printf "%s\\n" "$@" > {root}/args\n'
            )
            activation.chmod(0o755)
            script = (
                f"set -euo pipefail\nactivation_package={shlex.quote(directory)}\n"
                + HOME
            )
            result = subprocess.run(
                ["bash", "-c", script, "home", "--verbose"],
                env={
                    **os.environ,
                    "HOME_MANAGER_BACKUP_EXT": "backup",
                    "SKIP_SANITY_CHECKS": "1",
                },
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (root / "args").read_text().splitlines(), ["--driver-version", "0"]
            )
            (root / "args").unlink()
            result = subprocess.run(
                ["bash", "-c", script, "home", "--override-input", "other"],
                capture_output=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertFalse((root / "args").exists())

    def test_home_failure_preserves_exit_status_without_false_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activation = root / "activate"
            activation.write_text(
                f"#!{shutil.which('bash')}\nprintf 'Activating Home Manager...\\n'\nexit 17\n"
            )
            activation.chmod(0o755)
            script = (
                f"set -euo pipefail\nactivation_package={shlex.quote(directory)}\n"
                + HOME
            )
            result = subprocess.run(
                ["bash", "-c", script, "home"], capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 17)
            self.assertIn("[start] Home Manager activation", result.stderr)
            self.assertNotIn("[done] Home Manager activation", result.stderr)
            self.assertIn("Activating Home Manager...", result.stdout)


if __name__ == "__main__":
    unittest.main()
