# pyright: standard
"""Run the built nacre command against fake nix, sudo and Home Manager state."""

import datetime
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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
        self.assertIn(f"{nacre}#deployment", self.recorded()[-1])
        self.run_nacre("build", NACRE_FLAKE=str(self.flake))
        self.assertIn(f"{self.flake}#deployment", self.recorded()[-1])
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
        # doctor reports after an update; the update's status stays the result.
        self.assertEqual(result.returncode, 3)
        self.assertRegex(result.stdout, r"(?m)^(ok|warn) +pending ")
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

    def test_changes_lists_package_events_since_the_last_update(self):
        log = self.root / "var/log/pacman.log"
        log.parent.mkdir(parents=True)
        env = {"NACRE_ROOT": str(self.root)}
        result = self.run_nacre("changes", **env)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--since", result.stderr)

        def at(minutes):
            when = datetime.datetime.now().astimezone()
            return (when + datetime.timedelta(minutes=minutes)).strftime(
                "%Y-%m-%dT%H:%M:%S%z"
            )

        log.write_text(
            f"[{at(-60)}] [ALPM] upgraded before (1-1 -> 1-2)\n"
            f"[{at(-60)}] [PACMAN] Running 'pacman -Syu'\n"
        )
        self.run_nacre("update", DEPLOY_STATUS="75", **env)
        with log.open("a") as stream:
            stream.write(
                f"[{at(1)}] [ALPM] upgraded kitty (0.48.2-1 -> 0.49.2-1)\n"
                f"[{at(1)}] [ALPM] installed claude-code (2.1-1)\n"
                f"[{at(1)}] [ALPM] removed kvantum (1.1-1)\n"
                f"[{at(1)}] [ALPM] upgraded hyprland (0.56.2-3 -> 0.56.2-4)\n"
            )
        result = self.run_nacre("changes", **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("before", result.stdout)
        lines = [line.split() for line in result.stdout.splitlines()]
        self.assertEqual(
            lines[2:],
            [
                ["Upgraded", "(2)"],
                ["hyprland", "0.56.2-3", "->", "0.56.2-4"],
                ["kitty", "0.48.2-1", "->", "0.49.2-1"],
                [],
                ["Installed", "(1)"],
                ["claude-code", "2.1-1"],
                [],
                ["Removed", "(1)"],
                ["kvantum", "1.1-1"],
            ],
        )
        result = self.run_nacre("changes", "--since", at(-90)[:10], **env)
        self.assertIn("before", result.stdout)

    def test_doctor_reports_what_needs_attention(self):
        env = {"NACRE_ROOT": str(self.root)}
        bin_dir = self.root / "bin"
        self.script(bin_dir / "uname", 'echo "${KERNEL:-7.2.11-arch1-1}"')
        (self.root / "usr/lib/modules/7.2.11-arch1-1").mkdir(parents=True)
        self.script(
            bin_dir / "systemctl",
            'case "$*" in\n'
            '  "--failed --plain --no-legend") echo "${FAILED:-}" ;;\n'
            '  "--user --failed --plain --no-legend") ;;\n'
            '  "--user is-active graphical-session.target") echo active ;;\n'
            '  "--user show "*)\n'
            '    printf "Id=watch.path\\nActiveState=%s\\nInactiveExitTimestampMonotonic=%s\\n" \\\n'
            '      "${WATCH_STATE:-active}" "${WATCH_STARTED:-5}" ;;\n'
            "  *) exit 1 ;;\n"
            "esac",
        )
        wants = self.home / ".config/systemd/user/graphical-session.target.wants"
        wants.mkdir(parents=True)
        (wants / "watch.path").symlink_to("/nix/store/fixture-home-files/watch.path")
        files = self.root / "generation-1/home-files/.config/kitty"
        files.mkdir(parents=True)
        (files / "kitty.conf").write_text("")
        profiles = self.home / ".local/state/nix/profiles"
        profiles.mkdir(parents=True)
        (profiles / "home-manager-1-link").symlink_to(self.root / "generation-1")
        (profiles / "home-manager").symlink_to("home-manager-1-link")
        self.run_nacre("switch", **env)

        result = self.run_nacre("doctor", **env)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue(
            all(line.startswith("ok") for line in result.stdout.splitlines())
        )

        pending = self.root / "var/lib/nix-config/arch"
        pending.mkdir(parents=True)
        (pending / "hotspot.pending").write_text("")
        (self.home / ".config/kitty").mkdir(parents=True)
        (self.home / ".config/kitty/kitty.conf.bak").write_text("")
        result = self.run_nacre(
            "doctor",
            KERNEL="7.2.6-arch2-1",
            FAILED="broken.service loaded failed failed Broken",
            WATCH_STATE="inactive",
            WATCH_STARTED="0",
            **env,
        )
        self.assertEqual(result.returncode, 1)
        warnings = {
            line.split()[1]: line
            for line in result.stdout.splitlines()
            if line.startswith("warn")
        }
        self.assertEqual(
            sorted(warnings), ["failed", "kernel", "leftover", "pending", "started"]
        )
        self.assertIn("hotspot", warnings["pending"])
        self.assertIn("7.2.6-arch2-1", warnings["kernel"])
        self.assertIn("broken.service", warnings["failed"])
        self.assertIn("watch.path", warnings["started"])
        self.assertIn("~/.config/kitty/kitty.conf.bak", warnings["leftover"])

    def prepare_install(self, wheel="alice"):
        (self.flake / "configuration.nix").write_text("# shipped example\n")
        git = [
            "git",
            "-C",
            str(self.flake),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
        ]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "."], check=True)
        subprocess.run([*git, "commit", "-qm", "fixture"], check=True)
        root = self.root / "machine"
        (root / "boot").mkdir(parents=True)
        (root / "etc").mkdir()
        (root / "etc/hostname").write_text("box\n")
        for image in ("initramfs-linux.img", "initramfs-linux-fallback.img"):
            (root / "boot" / image).write_text("")
        bin_dir = self.root / "bin"
        self.script(
            bin_dir / "getent",
            'case "$1 $2" in\n'
            '  "passwd alice") echo "alice:x:1000:1000:Alice A,,,:/home/alice:/bin/bash" ;;\n'
            f'  "group wheel") echo "wheel:x:998:{wheel}" ;;\n'
            "  *) exit 2 ;;\n"
            "esac",
        )
        self.script(
            bin_dir / "lspci",
            'echo "03:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI]"',
        )
        self.script(bin_dir / "timedatectl", "echo Asia/Taipei")
        return {"NACRE_INSTALL_ROOT": str(root), "USER": "alice"}

    def test_install_writes_the_machine_then_plans_and_updates(self):
        env = self.prepare_install()
        result = self.run_nacre("install", "--role", "minimal", "--yes", **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        written = (self.flake / "configuration.nix").read_text()
        for expected in (
            'role = "minimal";',
            'networking.hostname.name = "box";',
            'time.timeZone = "Asia/Taipei";',
            "users.users.alice = {",
            'description = "Alice A";',
            'graphics = "amd";',
            'initramfs.images = [ "/boot/initramfs-linux.img" ];',
        ):
            self.assertIn(expected, written)
        self.assertNotIn("@", written.replace("`nacre install`", ""))
        self.assertEqual(
            [call for call in self.recorded() if call.startswith("deploy")],
            ["deploy --plan", "deploy --update"],
        )

    def test_install_into_an_empty_directory_creates_a_machine_flake(self):
        env = self.prepare_install()
        machine = self.root / "machine-flake"
        result = self.run_nacre("--flake", str(machine), "install", "--yes", **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nacre.lib.mkFlake", (machine / "flake.nix").read_text())
        self.assertIn("users.users.alice", (machine / "configuration.nix").read_text())
        tracked = subprocess.run(
            ["git", "-C", str(machine), "ls-files"], capture_output=True, text=True
        ).stdout.split()
        self.assertEqual(sorted(tracked), ["configuration.nix", "flake.nix"])
        self.assertIn(f"{machine}#deployment", "\n".join(self.recorded()))

    def test_install_without_yes_only_plans_when_not_interactive(self):
        env = self.prepare_install()
        self.assertEqual(self.run_nacre("install", **env).returncode, 0)
        self.assertEqual(
            [call for call in self.recorded() if call.startswith("deploy")],
            ["deploy --plan"],
        )

    def test_install_refuses_before_writing(self):
        cases = (
            ({}, ("--user", "bob")),
            ({}, ("--hostname", "Bad.Name")),
            ({"wheel": "someone"}, ()),
        )
        for setup, args in cases:
            with self.subTest(args=args, setup=setup):
                self.tearDown_install()
                env = self.prepare_install(**setup)
                result = self.run_nacre("install", "--yes", *args, **env)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(
                    (self.flake / "configuration.nix").read_text(),
                    "# shipped example\n",
                )
                self.assertEqual(self.recorded(), [])

    def test_install_keeps_uncommitted_configuration(self):
        env = self.prepare_install()
        (self.flake / "configuration.nix").write_text("# local edits\n")
        result = self.run_nacre("install", "--yes", **env)
        self.assertEqual(result.returncode, 2)
        self.assertIn("uncommitted", result.stderr)
        self.assertEqual(
            (self.flake / "configuration.nix").read_text(), "# local edits\n"
        )
        self.assertEqual(
            self.run_nacre("install", "--yes", "--force", **env).returncode, 0
        )

    def tearDown_install(self):
        shutil.rmtree(self.flake / ".git", ignore_errors=True)
        shutil.rmtree(self.root / "machine", ignore_errors=True)
        self.calls.unlink(missing_ok=True)

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
