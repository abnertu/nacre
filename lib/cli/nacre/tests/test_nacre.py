# pyright: standard
"""Run the built nacre command against fake nix, sudo and Home Manager state."""

import datetime
import errno
import json
import os
import pty
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

PACKAGE_SOURCE = Path(sys.argv.pop())
NACRE = sys.argv.pop()
NIX = shutil.which("nix") or ""
if not NIX:
    raise RuntimeError("nix is required for installer fixtures")


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
            'if [[ " $* " == *" eval "* && -n ${NACRE_TEST_STORE:-} ]]; then\n'
            f'  exec {NIX} --store "$NACRE_TEST_STORE" "$@"\n'
            "fi\n"
            'if [[ -n ${NACRE_TEST_TRACKED:-} && " $* " == *" build "* ]]; then\n'
            '  git -C "$NACRE_TEST_TRACKED" ls-files --error-unmatch -- runners/frontend.toml '
            "runners/base.toml runners/ca/public.crt > /dev/null || exit 91\n"
            "fi\n"
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

    def run_nacre_tty(self, *args, **env):
        master, slave = pty.openpty()
        try:
            result = subprocess.run(
                [NACRE, *args],
                env=(self.env | env),
                stdin=subprocess.DEVNULL,
                stdout=slave,
                stderr=slave,
                timeout=10,
            )
        finally:
            os.close(slave)
        output = bytearray()
        try:
            while True:
                try:
                    chunk = os.read(master, 65536)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    break
                if not chunk:
                    break
                output.extend(chunk)
        finally:
            os.close(master)
        return result.returncode, output.decode().replace("\r\n", "\n")

    def test_cached_build_reports_artifact_only_after_success(self):
        result = self.run_nacre("build")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.root / "artifact"), result.stdout)
        failed = self.run_nacre("build", NIX_STATUS="7")
        self.assertEqual(failed.returncode, 7)
        self.assertEqual(failed.stdout, "")
        self.assertFalse(any(call.startswith("deploy") for call in self.recorded()))

    def test_native_output_colors_follow_terminal_policy(self):
        self.env.pop("NO_COLOR")
        self.env["TERM"] = "xterm-256color"
        self.env["NACRE_ROOT"] = str(self.root)
        for args in (
            ("--version",),
            ("status",),
            ("build",),
            ("--flake", str(self.root), "build"),
        ):
            with self.subTest(args=args):
                plain = self.run_nacre(*args)
                expected = plain.stdout + plain.stderr
                code, colored = self.run_nacre_tty(*args)
                self.assertEqual(code, plain.returncode)
                self.assertIn("\033[", colored)
                self.assertEqual(re.sub(r"\033\[[0-9;]*m", "", colored), expected)
                self.assertNotIn("\033", expected)
                for disabled in ({"NO_COLOR": ""}, {"TERM": "dumb"}, {"CI": "1"}):
                    code, output = self.run_nacre_tty(*args, **disabled)
                    self.assertEqual(code, plain.returncode)
                    self.assertEqual(output, expected)

    def test_entrypoint_never_writes_bytecode_beside_its_package(self):
        package = self.root / "nacre"
        shutil.copytree(PACKAGE_SOURCE, package)
        package.chmod(0o755)
        cli = package / "cli.py"
        cli.chmod(0o644)
        cli.write_text(cli.read_text().replace("@version@", "fixture-bytecode-check"))
        # Nix Python loads .pth files from NIX_PYTHONPATH even with -I. Put a
        # writable package first, so store permissions cannot hide a write.
        (self.root / "first.pth").write_text(
            f"import sys; sys.path.insert(0, {str(self.root)!r})\n"
        )
        result = self.run_nacre("--version", NIX_PYTHONPATH=str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nacre fixture-bytecode-check", result.stdout)
        self.assertEqual(list(package.rglob("*.pyc")), [])

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

    def test_input_overrides_reach_every_nix_call(self):
        override = ("--override-input", "nacre", "path:/src/nacre")
        self.assertEqual(self.run_nacre(*override, "switch").returncode, 0)
        self.assertEqual(self.run_nacre(*override, "check").returncode, 0)
        nix_calls = [call for call in self.recorded() if call.startswith("nix ")]
        self.assertEqual(len(nix_calls), 2)
        for call in nix_calls:
            self.assertIn(" ".join(override), call)
        self.assertEqual(self.run_nacre("--override-input", "nacre").returncode, 2)

    def test_noctalia_uses_the_checkout_and_input_overrides(self):
        override = ("--override-input", "nacre", "path:/src/nacre")
        self.assertEqual(self.run_nacre(*override, "noctalia", "deploy").returncode, 0)
        tail = self.recorded()[-1].split(" -- ", 1)[1]
        self.assertEqual(tail, f"deploy --repo {self.flake} {' '.join(override)}")
        self.run_nacre(*override, "noctalia", "capture", "--repo", "/elsewhere")
        tail = self.recorded()[-1].split(" -- ", 1)[1]
        self.assertEqual(tail, "capture --repo /elsewhere")

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

        snapshot = self.flake / "homes" / pwd.getpwuid(os.getuid()).pw_name
        (snapshot / "noctalia").mkdir(parents=True)
        (snapshot / "noctalia/config.toml").write_text("")
        self.script(
            bin_dir / "noctalia-config",
            'echo "Uncaptured Noctalia changes in: bar; run nacre noctalia capture"\n'
            "exit 3",
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
            sorted(warnings),
            ["failed", "kernel", "leftover", "noctalia", "pending", "started"],
        )
        self.assertIn("uncaptured GUI changes in: bar", warnings["noctalia"])
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

    def runner_install(self):
        env = self.prepare_install()
        source = self.root / "public"
        source.mkdir()
        (source / "ca").mkdir()
        (source / "ca/public.crt").write_text("synthetic public certificate\n")
        (source / "lookup").mkdir()
        (source / "base.toml").write_text(
            '[gitlab]\nca_certificate = "ca/public.crt"\n'
        )
        (source / "frontend.toml").write_text('extends = "lookup/../base.toml"\n')
        controls = "".join(chr(value) for value in range(1, 32))
        nested = source / (
            'nested ${1+1} "quoted" \\ [ab]*? Unicode 台 control' + controls
        )
        nested.mkdir()
        (nested / "dotnet.toml").write_text('extends = "../base.toml"\n')
        # Unselected files must never enter the captured source or checkout.
        (source / "unselected.txt").write_text("synthetic excluded payload\n")
        selected = [source / "frontend.toml", nested / "dotnet.toml"]
        env |= {
            "NACRE_TEST_STORE": f"local?store={self.root}/store&state={self.root}/state&log={self.root}/log",
            "NIX_CONFIG": "experimental-features = nix-command flakes\n",
        }
        args = ["install", "--role", "runner"]
        for file in selected:
            args += ["--runner-config", str(file)]
        return source, selected, args, env

    def test_runner_install_captures_public_files_before_building(self):
        source, selected, args, env = self.runner_install()
        for machine in (self.root / "fresh", self.flake):
            with self.subTest(machine=machine):
                result = self.run_nacre(
                    "--flake",
                    str(machine),
                    *args,
                    NACRE_TEST_TRACKED=str(machine),
                    **env,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = [
                    Path("frontend.toml"),
                    selected[1].relative_to(source),
                    Path("base.toml"),
                    Path("ca/public.crt"),
                ]
                actual = sorted(
                    p.relative_to(machine / "runners")
                    for p in (machine / "runners").rglob("*")
                    if p.is_file()
                )
                self.assertEqual(
                    actual, sorted([*expected, Path("lookup/.nix-config-directory")])
                )
                self.assertTrue((machine / "runners/lookup").is_dir())
                for file in expected:
                    self.assertEqual(
                        (machine / "runners" / file).read_bytes(),
                        (source / file).read_bytes(),
                    )
                evaluated = subprocess.run(
                    [
                        NIX,
                        "--store",
                        env["NACRE_TEST_STORE"],
                        "eval",
                        "--impure",
                        "--json",
                        "--expr",
                        f'let source = builtins.fetchGit {{ url = "{machine}"; }}; in '
                        'builtins.map toString ((import (source + "/configuration.nix") {}).services.gitlabRunner.configFiles)',
                    ],
                    env=self.env | env,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(evaluated.returncode, 0, evaluated.stderr)
                snapshot_paths = json.loads(evaluated.stdout)
                snapshot = Path(snapshot_paths[0]).parent
                self.assertEqual(
                    [str(Path(p).relative_to(snapshot)) for p in snapshot_paths],
                    [str(file.relative_to(source)) for file in selected],
                )
                # A Git-filtered closure must still pass the real packaged capture helper.
                roundtrip_args = [
                    "--flake",
                    str(self.root / (machine.name + "-roundtrip")),
                    "install",
                    "--role",
                    "runner",
                ]
                for copied in snapshot_paths:
                    roundtrip_args += ["--runner-config", copied]
                roundtrip = self.run_nacre(*roundtrip_args, **env)
                self.assertEqual(roundtrip.returncode, 0, roundtrip.stderr)
                for copied in snapshot_paths:
                    path = Path(copied)
                    base = path.parent / tomllib.loads(path.read_text())["extends"]
                    certificate = (
                        base.parent
                        / tomllib.loads(base.read_text())["gitlab"]["ca_certificate"]
                    )
                    self.assertEqual(
                        certificate.read_text(), "synthetic public certificate\n"
                    )
                self.assertEqual(
                    [c for c in self.recorded() if c.startswith("deploy")],
                    ["deploy --plan", "deploy --plan"],
                )
                self.calls.unlink()

    def test_runner_install_rejects_invalid_sources_before_writing(self):
        source, _, args, env = self.runner_install()
        original = (self.flake / "configuration.nix").read_bytes()
        file = source / "frontend.toml"
        outside = self.root / "outside.toml"
        outside.write_text("# synthetic outside source\n")
        (source / "link.toml").symlink_to(outside)
        for contents in (
            "[invalid TOML",
            'extends = "missing.toml"',
            'extends = "../outside.toml"',
            'extends = "link.toml"',
        ):
            with self.subTest(contents=contents):
                file.write_text(contents)
                result = self.run_nacre(*args, "--yes", **env)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(
                    (self.flake / "configuration.nix").read_bytes(), original
                )
                self.assertFalse((self.flake / "runners").exists())
                self.assertFalse(
                    any(
                        c.startswith("deploy") or " build " in c
                        for c in self.recorded()
                    )
                )

    def test_runner_install_stages_only_literal_public_paths(self):
        source, _, args, env = self.runner_install()
        selected = source / "glob*/dotnet.toml"
        selected.parent.mkdir()
        selected.write_text('extends = "../base.toml"\n')
        args[-1] = str(selected)
        unrelated = self.flake / "runners/glob-foreign/dotnet.toml"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("# unrelated synthetic policy\n")
        result = self.run_nacre(*args, **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        tracked = subprocess.run(
            [
                "git",
                "-C",
                str(self.flake),
                "ls-files",
                "--error-unmatch",
                "--",
                "runners/glob-foreign/dotnet.toml",
            ],
            capture_output=True,
        )
        self.assertNotEqual(tracked.returncode, 0)
        self.assertEqual(unrelated.read_text(), "# unrelated synthetic policy\n")

    def test_runner_install_preserves_identical_files_and_rejects_conflicts(self):
        source, _, args, env = self.runner_install()
        destination = self.flake / "runners"
        destination.mkdir()
        target = destination / "frontend.toml"
        target.write_bytes((source / "frontend.toml").read_bytes())
        os.utime(target, ns=(123456789, 123456789))
        before = target.stat()
        result = self.run_nacre(*args, **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (target.stat().st_ino, target.stat().st_mtime_ns),
            (before.st_ino, before.st_mtime_ns),
        )
        original = (self.flake / "configuration.nix").read_bytes()
        for target in (
            destination / "frontend.toml",
            destination / "lookup/.nix-config-directory",
        ):
            saved = target.read_bytes()
            for conflict in ("different content", "symlink"):
                with self.subTest(target=target.name, conflict=conflict):
                    target.unlink()
                    if conflict == "symlink":
                        target.symlink_to(source / "frontend.toml")
                    else:
                        target.write_text(conflict)
                    self.calls.unlink(missing_ok=True)
                    result = self.run_nacre(*args, "--force", "--yes", **env)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn("Runner destination", result.stderr)
                    self.assertEqual(
                        (self.flake / "configuration.nix").read_bytes(), original
                    )
                    self.assertFalse(
                        any(
                            c.startswith("deploy") or " build " in c
                            for c in self.recorded()
                        )
                    )
            target.unlink()
            target.write_bytes(saved)

    def test_install_refuses_before_writing(self):
        cases = (
            ({}, ("--user", "bob")),
            ({}, ("--hostname", "Bad.Name")),
            ({"wheel": "someone"}, ()),
            ({}, ("--role", "runner")),
            ({}, ("--runner-config", "/synthetic/frontend.toml")),
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
