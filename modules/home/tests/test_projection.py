# pyright: standard
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(sys.argv.pop()).read_text()


class ProjectionTests(unittest.TestCase):
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
