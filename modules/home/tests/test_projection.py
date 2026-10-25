# pyright: standard
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(sys.argv.pop(1)).read_text()
LOGIN_PROFILE = Path(sys.argv.pop(1)).read_text()


class ProjectionTests(unittest.TestCase):
    def test_login_replaces_shell_only_when_uwsm_allows_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = root / "uwsm"
            native.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "if sys.argv[1:] == ['check', 'may-start']:\n"
                "    raise SystemExit(int(os.environ['DENY_START']))\n"
                "print(json.dumps({'pid': os.getpid(), 'args': sys.argv[1:]}))\n"
            )
            native.chmod(0o755)
            profile = root / "zprofile"
            profile.write_text(LOGIN_PROFILE.replace("/usr/bin/uwsm", str(native)))
            zsh = shutil.which("zsh")
            if zsh is None:
                raise RuntimeError("required zsh is unavailable")
            for deny in (0, 1):
                with self.subTest(deny_start=deny):
                    process = subprocess.Popen(
                        [
                            zsh,
                            "-f",
                            "-c",
                            f"source {shlex.quote(str(profile))}; print continued",
                        ],
                        env={"HOME": directory, "DENY_START": str(deny)},
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    output, error = process.communicate(timeout=5)
                    self.assertEqual(process.returncode, 0, error)
                    if deny:
                        self.assertEqual(output.strip(), "continued")
                    else:
                        result = json.loads(output)
                        self.assertEqual(result["pid"], process.pid)
                        self.assertEqual(result["args"], ["start", "hyprland.desktop"])

    def test_clean_paths_worktrees_and_backups(self):
        for obstruction in (
            None,
            ".git",
            ".config/.git",
            ".config/hypr/.git",
            ".config/nvim/.git",
            ".config/hypr.bak",
            ".config/nvim.backup",
        ):
            with (
                self.subTest(obstruction=obstruction),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                if obstruction:
                    path = root / obstruction
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()
                before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
                result = subprocess.run(
                    [
                        "bash",
                        "-euc",
                        f"home_dir={shlex.quote(directory)}\nconfig_home={shlex.quote(directory + '/.config')}\nprojection_targets=(nvim hypr)\n"
                        + SCRIPT,
                    ],
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 1 if obstruction else 0)
                self.assertEqual(
                    before,
                    sorted(str(path.relative_to(root)) for path in root.rglob("*")),
                )

    def test_link_to_worktree_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source").mkdir()
            (root / "source/.git").touch()
            (root / ".config").mkdir()
            (root / ".config/nvim").symlink_to(
                root / "source", target_is_directory=True
            )
            result = subprocess.run(
                [
                    "bash",
                    "-euc",
                    f"home_dir={shlex.quote(directory)}\nconfig_home={shlex.quote(directory + '/.config')}\nprojection_targets=(nvim hypr)\n"
                    + SCRIPT,
                ],
                capture_output=True,
            )
            self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
