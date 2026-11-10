# pyright: standard
"""Complete nacre in real bash and zsh sessions against `nacre --help`."""

import os
import pty
import re
import select
import shlex
import subprocess
import sys
import tempfile
import time
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
            # Readline owns compopt; candidate-only calls have no active completion.
            "compopt() { :; }\n"
            f"COMP_WORDS=({' '.join(repr(w) for w in words)})\n"
            f"COMP_CWORD={len(words) - 1}\n"
            '_nacre; printf "%s\\n" "${COMPREPLY[@]}"'
        )
        result = subprocess.run(
            ["bash", "-c", script],
            env=self.env,
            capture_output=True,
            text=True,
            cwd=self.home,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return set(result.stdout.split())

    def bash_readline(self, line):
        rc = self.home / "bashrc"
        rc.write_text(
            f"source {PACKAGE}/share/bash-completion/completions/nacre\n"
            "nacre() { return 99; }\n"
            "PS1='READY> '\n"
            "bind 'set bell-style none'\n"
            'bind -x \'"\\C-x\\C-r":printf "\\nCAPTURE:%s\\n" "$READLINE_LINE"\'\n'
        )
        master, slave = pty.openpty()
        process = subprocess.Popen(
            ["bash", "--noprofile", "--rcfile", str(rc), "-i"],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=self.env,
            cwd=self.home,
            start_new_session=True,
        )
        os.close(slave)
        try:
            output = b""
            deadline = time.monotonic() + 10
            sent = False
            while time.monotonic() < deadline:
                readable, _, _ = select.select([master], [], [], 0.2)
                if not readable:
                    continue
                output += os.read(master, 65536)
                if not sent and b"READY> " in output:
                    os.write(master, line.encode() + b"\t\x18\x12")
                    sent = True
                match = re.search(rb"\r?\nCAPTURE:([^\r\n]*)\r?\n", output)
                if match:
                    return shlex.split(match[1].decode())
            self.fail(f"Readline did not capture completion: {output!r}")
        finally:
            process.kill()
            process.wait(timeout=5)
            os.close(master)

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

    def test_runner_role_and_repeatable_configuration_files(self):
        (self.home / "frontend.toml").touch()
        (self.home / "dotnet.toml").touch()
        for shell in (self.bash, self.zsh):
            with self.subTest(shell.__name__):
                self.assertEqual(shell("nacre install --role run"), {"runner"})
                self.assertEqual(
                    shell("nacre install --role runner --runner-config fr"),
                    {"frontend.toml"},
                )
                self.assertEqual(
                    shell(
                        "nacre install --role runner --runner-config frontend.toml --runner-config do"
                    ),
                    {"dotnet.toml"},
                )

    def test_bash_readline_quotes_runner_files_and_enters_directories(self):
        (self.home / "with space.toml").touch()
        (self.home / "public").mkdir()
        prefix = ["nacre", "install", "--role", "runner", "--runner-config"]
        self.assertEqual(
            self.bash_readline(" ".join(prefix) + " with"), [*prefix, "with space.toml"]
        )
        self.assertEqual(
            self.bash_readline(" ".join(prefix) + " pub"), [*prefix, "public/"]
        )


if __name__ == "__main__":
    unittest.main()
