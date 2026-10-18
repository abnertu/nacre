# pyright: standard
"""Complete nacre in real bash and zsh sessions against `nacre --help`."""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE = Path(sys.argv.pop())
ZSH_COMPLETE = Path(__file__).with_name("zsh-complete.zsh")


class CompletionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        profiles = self.home / ".local/state/nix/profiles"
        profiles.mkdir(parents=True)
        for number in (4, 7):
            (profiles / f"home-manager-{number}-link").symlink_to(self.home)
        self.env = {"HOME": str(self.home), "PATH": os.environ["PATH"], "TERM": "dumb"}

    def bash(self, line):
        words = line.split(" ")
        script = (
            f"source {PACKAGE}/share/bash-completion/completions/nacre\n"
            f"COMP_WORDS=({' '.join(repr(w) for w in words)})\n"
            f"COMP_CWORD={len(words) - 1}\n"
            '_nacre; printf "%s\\n" "${COMPREPLY[@]}"'
        )
        result = subprocess.run(
            ["bash", "-c", script], env=self.env, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return set(result.stdout.split())

    def zsh(self, line):
        result = subprocess.run(
            [
                "zsh",
                "-f",
                str(ZSH_COMPLETE),
                f"{PACKAGE}/share/zsh/site-functions",
                line,
            ],
            env=self.env,
            cwd=self.home,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return set(result.stdout.split())

    def test_commands_match_help(self):
        usage = subprocess.run(
            [PACKAGE / "bin/nacre", "--help"], capture_output=True, text=True
        ).stdout
        commands = set(re.findall(r"(?m)^  ([a-z]+)\b", usage))
        self.assertIn("doctor", commands)
        for shell in (self.bash, self.zsh):
            with self.subTest(shell.__name__):
                self.assertEqual(shell("nacre "), commands)
                self.assertEqual(shell("nacre --flake /tmp sw"), {"switch"})

    def test_shells_agree_on_arguments(self):
        # Both scripts are written by hand; they must offer the same words.
        for line in (
            "nacre --",
            "nacre install --",
            "nacre install --role ",
            "nacre changes ",
            "nacre ai ",
            "nacre ai prepare ",
            "nacre runner ",
            "nacre noctalia ",
            "nacre noctalia capture --",
            "nacre noctalia deploy --",
        ):
            with self.subTest(line):
                offered = self.bash(line)
                self.assertTrue(offered)
                self.assertEqual(self.zsh(line), offered)

    def test_rollback_offers_existing_generations(self):
        for shell in (self.bash, self.zsh):
            with self.subTest(shell.__name__):
                self.assertEqual(shell("nacre rollback "), {"4", "7"})


if __name__ == "__main__":
    unittest.main()
