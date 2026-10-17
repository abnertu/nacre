"""Exercise the actual shell implementation without host access or privilege."""

import fcntl
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(sys.argv.pop()).resolve()
FAKE = Path(__file__).with_name("native.py")


def progress_preamble() -> str:
    shell = os.environ.get("PROGRESS_TEST_SHELL")
    renderer = os.environ.get("PROGRESS_TEST_RENDERER")
    if not shell or not renderer:
        raise unittest.SkipTest("set PROGRESS_TEST_SHELL and PROGRESS_TEST_RENDERER")
    return (
        f"source {shlex.quote(shell)}\n"
        f"progress_renderer={shlex.quote(renderer)}\n"
        "progress_base64=$(command -v base64)\n"
    )


class ArchSwitchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for name in (
            "etc/pacman.d",
            "usr/lib/modules/" + os.uname().release,
            "run/user/1000",
            "boot",
            "bin",
        ):
            (self.root / name).mkdir(parents=True)
        (self.root / "etc/arch-release").touch()
        (self.root / "etc/pacman.conf").write_text("[options]\n")
        (self.root / "etc/mkinitcpio.conf").write_text(
            "MODULES=(existing)\nHOOKS=(base)\n"
        )
        (self.root / "etc/nix").mkdir(parents=True, exist_ok=True)
        (self.root / "etc/nix/nix.conf").write_text("build-users-group = nixbld\n")
        self.state = {"groups": ["wheel"], "services": {}}
        self.save()
        for command in (
            "id sudo pacman pacman-conf yay install mv rm touch mkdir mktemp "
            "systemctl sysctl gpasswd getcap setcap mkinitcpio modprobe curl bsdtar"
            " getent groupadd useradd chown chmod stat"
        ).split():
            executable = self.root / "bin" / command
            executable.write_text(
                f"#!{sys.executable}\n" + FAKE.read_text().split("\n", 1)[1]
            )
            executable.chmod(0o755)
        (self.root / "bin/sunshine").touch()
        q = shlex.quote
        self.script = self.root / "switch.sh"
        self.script.write_text(
            "set -euo pipefail\n"
            + progress_preamble()
            + "\n".join(
                [
                    f"fs_root={q(str(self.root))}",
                    f"native_bin={q(str(self.root / 'bin'))}",
                    f"files={q(str(SOURCE.parent / 'files'))}",
                    f"managed_identity=644:{os.getuid()}:{os.getgid()}",
                    f"curl_bin={q(str(self.root / 'bin/curl'))}",
                    f"tar_bin={q(str(self.root / 'bin/bsdtar'))}",
                    f"flock_bin={q(shutil.which('flock') or 'flock')}",
                    "expected_user=tester",
                    "pacman_packages=(base)",
                    "aur_packages=(extra)",
                    "lizardbyte_package_names=(sunshine)",
                    "lizardbyte_packages=(lizardbyte/sunshine)",
                    "required_groups=(wheel i2c)",
                    "system_units=(NetworkManager.service bluetooth.service power-profiles-daemon.service tailscaled.service)",
                    "system_python=/fixture/python",
                    "system_adapter=/fixture/adapter",
                    "system_manifest=/fixture/manifest",
                    "ai_python=/fixture/python",
                    "ai_adapter=/fixture/ai-adapter",
                    "ai_manifest=/fixture/ai-manifest",
                    "personal_agent_python=/fixture/python",
                    "personal_agent_adapter=/fixture/personal-agent-adapter",
                    "personal_agent_manifest=/fixture/personal-agent-manifest",
                    "initramfs_modules=(usbhid amdgpu)",
                    "initramfs_images=(/boot/initramfs-linux.img)",
                    "user_services=(openrazer-daemon.service app-dev.lizardbyte.app.Sunshine.service)",
                ]
            )
            + "\n"
            + SOURCE.read_text()
        )

    def save(self):
        (self.root / "state.json").write_text(json.dumps(self.state))

    def invoke(self, *args, code=0):
        result = subprocess.run(
            ["bash", str(self.script), *args],
            text=True,
            capture_output=True,
            env={**os.environ, "ARCH_TEST_ROOT": str(self.root)},
        )
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.state = json.loads((self.root / "state.json").read_text())
        return result

    def commands(self):
        path = self.root / "commands.jsonl"
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )

    def test_progress_marks_successful_stage_and_closes_after_convergence(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0)
        self.assertRegex(
            result.stderr,
            r"\[start\] \[\d+/\d+\] Validate Arch host, packages, and kernel",
        )
        self.assertRegex(
            result.stderr, r"\[done\] \[\d+/\d+\] Finish runtime convergence"
        )

    def test_progress_marks_core_failure_without_false_success(self):
        self.state["fail"] = ["python", "/fixture/adapter"]
        self.save()
        result = self.invoke(code=1)
        self.assertRegex(
            result.stderr, r"\[failed\] \[\d+/\d+\] Preflight core and optional modules"
        )
        self.assertNotRegex(
            result.stderr, r"\[done\] \[\d+/\d+\] Preflight core and optional modules"
        )

    def test_disabled_capabilities_preserve_files_and_pending_actions(self):
        self.invoke()
        before = {
            str(path): (path.stat().st_ino, path.read_bytes())
            for path in (self.root / "etc").rglob("*")
            if path.is_file()
        }
        pending = self.root / "var/lib/nix-config/arch"
        for action in ("network", "initramfs", "units"):
            (pending / f"{action}.pending").touch()
        source = self.script.read_text()
        source = source.replace(
            "lizardbyte_package_names=(sunshine)", "lizardbyte_package_names=()"
        )
        source = source.replace(
            "lizardbyte_packages=(lizardbyte/sunshine)", "lizardbyte_packages=()"
        )
        source = source.replace(
            "system_units=(NetworkManager.service bluetooth.service power-profiles-daemon.service tailscaled.service)",
            "system_units=()",
        )
        source = source.replace(
            "user_services=(openrazer-daemon.service app-dev.lizardbyte.app.Sunshine.service)",
            "user_services=()",
        )
        self.script.write_text(
            "manage_network=0\nmanage_sunshine=0\nmanage_desktop=0\nmanage_initramfs=0\n"
            + source
        )
        for command in ("sunshine", "getcap", "setcap", "mkinitcpio"):
            (self.root / f"bin/{command}").unlink()
        (self.root / "commands.jsonl").unlink()
        self.invoke()
        self.assertFalse(
            any(
                call[0] in ("curl", "bsdtar", "getcap", "setcap", "mkinitcpio")
                for call in self.commands()
            )
        )
        self.assertFalse(
            any(
                call[0] == "systemctl" and "NetworkManager.service" in call
                for call in self.commands()
            )
        )
        self.assertEqual(
            before,
            {
                str(path): (path.stat().st_ino, path.read_bytes())
                for path in (self.root / "etc").rglob("*")
                if path.is_file()
            },
        )
        for action in ("network", "initramfs", "units"):
            self.assertTrue((pending / f"{action}.pending").exists())
        (self.root / "commands.jsonl").unlink()
        self.invoke("--check")
        self.assertFalse(any(call[0] in ("curl", "bsdtar") for call in self.commands()))

    def test_system_preflight_failure_precedes_configuration_writes(self):
        self.state["fail"] = ["python", "/fixture/adapter"]
        self.save()
        self.invoke(code=1)
        self.assertFalse((self.root / "var").exists())
        self.assertEqual((self.root / "etc/pacman.conf").read_text(), "[options]\n")

    def test_system_settings_run_after_update_and_before_other_policy(self):
        self.invoke("--update")
        calls = self.commands()
        preflight = calls.index(
            ["python", "/fixture/adapter", "/fixture/manifest", "preflight"]
        )
        converge = calls.index(
            ["python", "/fixture/adapter", "/fixture/manifest", "converge"]
        )
        upgrade = next(
            i
            for i, call in enumerate(calls)
            if call[0] == "pacman" and "--sysupgrade" in call
        )
        aur = next(
            i
            for i, call in enumerate(calls)
            if call[:3] == ["yay", "--sync", "--needed"]
        )
        self.assertLess(preflight, upgrade)
        self.assertLess(aur, converge)
        self.assertLess(
            converge, next(i for i, call in enumerate(calls) if call[0] == "mkinitcpio")
        )

    def test_missing_package_has_no_mutations_or_remote_queries(self):
        self.state["missing"] = ["base"]
        self.save()
        self.invoke(code=3)
        self.assertTrue(
            all(call[0] in ("id", "pacman-conf", "pacman") for call in self.commands())
        )

    def test_cli_modes(self):
        self.assertIn("usage: arch-switch", self.invoke("--help").stdout)
        self.invoke("--check", "--update", code=2)
        self.invoke("--unknown", code=2)
        self.assertEqual(self.commands(), [])

    def test_wrong_user(self):
        self.state["user"] = "other"
        self.save()
        self.invoke(code=1)
        self.assertTrue(all(call[0] == "id" for call in self.commands()))

    def test_missing_admin_group(self):
        self.state["groups"] = []
        self.save()
        self.invoke(code=1)
        self.assertTrue(all(call[0] == "id" for call in self.commands()))

    def test_check_only_queries(self):
        self.invoke("--check")
        self.assertTrue(
            all(
                call[0] in ("id", "pacman-conf", "pacman", "yay", "curl", "bsdtar")
                for call in self.commands()
            )
        )

    def test_second_run_is_quiet_and_preserves_files(self):
        self.invoke()
        before = {
            str(path): (path.stat().st_ino, path.stat().st_mtime_ns)
            for path in (self.root / "etc").rglob("*")
            if path.is_file()
        }
        (self.root / "commands.jsonl").unlink()
        self.assertIn("0 files updated, 0 runtime actions", self.invoke().stdout)
        after = {
            str(path): (path.stat().st_ino, path.stat().st_mtime_ns)
            for path in (self.root / "etc").rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)
        self.assertFalse(
            any(
                call[0] in ("curl", "yay", "mkinitcpio", "mv")
                for call in self.commands()
            )
        )
        self.assertIn(
            "MODULES=(existing)", (self.root / "etc/mkinitcpio.conf").read_text()
        )

    def test_failed_restart_remains_pending_and_is_retried(self):
        self.state["fail"] = ["systemctl", "restart"]
        self.save()
        self.invoke(code=1)
        marker = self.root / "var/lib/nix-config/arch/network.pending"
        self.assertTrue(marker.exists())
        self.state.pop("fail")
        self.save()
        self.invoke()
        self.assertFalse(marker.exists())

    def test_failed_initramfs_is_retried(self):
        self.state["fail"] = ["mkinitcpio", "-P"]
        self.save()
        self.invoke(code=1)
        self.assertTrue(
            (self.root / "var/lib/nix-config/arch/initramfs.pending").exists()
        )
        self.state.pop("fail")
        self.save()
        self.invoke()

    def test_runtime_drift_is_repaired(self):
        self.invoke()
        self.state["sysctl"]["net.ipv4.ip_forward"] = "0"
        self.state["services"]["system:bluetooth.service"]["active"] = False
        self.save()
        self.invoke()
        self.assertEqual(self.state["sysctl"]["net.ipv4.ip_forward"], "1")
        self.assertTrue(self.state["services"]["system:bluetooth.service"]["active"])

    def enable_gui(self):
        self.script.write_text(
            self.script.read_text().replace(
                "tailscaled.service)", "tailscaled.service libvirtd.socket)"
            )
        )

    def test_gui_socket_converges_and_repairs_drift(self):
        self.enable_gui()
        self.invoke()
        socket = self.state["services"]["system:libvirtd.socket"]
        self.assertTrue(socket["enabled"] and socket["active"])
        self.assertIn("0 files updated, 0 runtime actions", self.invoke().stdout)
        self.state["services"]["system:libvirtd.socket"]["active"] = False
        self.save()
        self.invoke()
        self.assertTrue(self.state["services"]["system:libvirtd.socket"]["active"])

    def test_gui_socket_start_failure_is_retried(self):
        self.enable_gui()
        self.invoke()
        self.state["services"]["system:libvirtd.socket"]["active"] = False
        self.state["fail"] = ["systemctl", "start"]
        self.save()
        self.invoke(code=1)
        self.assertFalse(self.state["services"]["system:libvirtd.socket"]["active"])
        self.state.pop("fail")
        self.save()
        self.invoke()
        self.assertTrue(self.state["services"]["system:libvirtd.socket"]["active"])

    def test_disabled_gui_does_not_retire_socket(self):
        self.enable_gui()
        self.invoke()
        self.script.write_text(
            self.script.read_text().replace(
                "tailscaled.service libvirtd.socket)", "tailscaled.service)"
            )
        )
        (self.root / "commands.jsonl").unlink()
        self.invoke()
        self.assertFalse(any("libvirtd.socket" in call for call in self.commands()))
        self.assertTrue(self.state["services"]["system:libvirtd.socket"]["active"])

    def test_update_order_and_failure_short_circuit(self):
        self.invoke("--update")
        calls = self.commands()
        upgrade = next(
            i
            for i, call in enumerate(calls)
            if call[0] == "pacman" and "--sysupgrade" in call
        )
        aur = next(
            i
            for i, call in enumerate(calls)
            if call[:3] == ["yay", "--sync", "--needed"]
        )
        self.assertLess(upgrade, aur)
        self.state["fail"] = ["pacman", "--sync"]
        self.save()
        (self.root / "commands.jsonl").unlink()
        self.invoke("--update", code=1)
        self.assertFalse(
            any(call[:3] == ["yay", "--sync", "--needed"] for call in self.commands())
        )

    def test_kernel_upgrade_stops_before_aur_and_configuration(self):
        self.state["kernel_upgrade"] = True
        self.save()
        self.invoke("--update", code=75)
        self.assertFalse((self.root / "etc/NetworkManager").exists())
        self.assertFalse(
            any(call[:3] == ["yay", "--sync", "--needed"] for call in self.commands())
        )

    def test_repository_conflict_is_not_overwritten(self):
        self.state["unmanaged_repo"] = True
        self.save()
        self.invoke(code=1)
        self.assertEqual((self.root / "etc/pacman.conf").read_text(), "[options]\n")

    def test_lock_prevents_concurrent_deployment(self):
        with (self.root / "run/user/1000/nix-config-arch.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.invoke(code=75)
        self.assertFalse((self.root / "var").exists())

    def test_failed_upgrade_does_not_run_aur_or_policy(self):
        self.state["upgrade_failure"] = True
        self.save()
        self.invoke("--update", code=1)
        self.assertFalse((self.root / "etc/NetworkManager").exists())
        self.assertFalse(
            any(call[:3] == ["yay", "--sync", "--needed"] for call in self.commands())
        )

    def test_unterminated_module_block_does_not_erase_settings(self):
        path = self.root / "etc/mkinitcpio.conf"
        original = "MODULES=(existing)\n# BEGIN nix-config modules\nHOOKS=(keep)\n"
        path.write_text(original)
        self.invoke(code=1)
        self.assertEqual(path.read_text(), original)

    def test_missing_initramfs_is_rebuilt(self):
        self.invoke()
        image = self.root / "boot/initramfs-linux.img"
        image.unlink()
        self.invoke()
        self.assertTrue(image.is_file())

    def test_file_mode_drift_is_repaired(self):
        self.invoke()
        path = self.root / "etc/NetworkManager/conf.d/main.conf"
        path.chmod(0o600)
        self.invoke()
        self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_failed_atomic_replace_cleans_temporary_file(self):
        self.state["fail"] = ["mv", "-fT"]
        self.save()
        self.invoke(code=1)
        self.assertEqual(list((self.root / "etc/pacman.d").iterdir()), [])

    def test_nix_daemon_trusted_users_converged_and_restarted(self):
        self.invoke()
        conf = (self.root / "etc/nix/nix.conf").read_text()
        self.assertEqual(
            conf,
            "build-users-group = nixbld\n"
            "# BEGIN nix-config settings\n"
            "trusted-users = root @wheel tester\n"
            "# END nix-config settings\n",
        )
        self.assertTrue(
            any(
                call == ["systemctl", "restart", "nix-daemon.service"]
                for call in self.commands()
            )
        )
        self.assertTrue(self.state["services"]["system:nix-daemon.service"]["active"])

    def test_nix_daemon_configuration_is_idempotent(self):
        self.invoke()
        conf_before = (self.root / "etc/nix/nix.conf").read_text()
        (self.root / "commands.jsonl").unlink()
        result = self.invoke()
        conf_after = (self.root / "etc/nix/nix.conf").read_text()
        self.assertEqual(conf_before, conf_after)
        self.assertIn("0 files updated, 0 runtime actions", result.stdout)
        self.assertFalse(
            any(
                call == ["systemctl", "restart", "nix-daemon.service"]
                for call in self.commands()
            )
        )

    def test_purge_removes_managed_state_through_privileged_writes(self):
        conf = self.root / "fixture-pwrstatd.conf"
        conf.write_text("runtime-threshold = 300\n")
        source = self.script.read_text()
        self.script.write_text(
            f"manage_powerpanel=1\npowerpanel_conf={shlex.quote(str(conf))}\n" + source
        )
        self.invoke()
        self.assertTrue((self.root / "etc/pwrstatd.conf").exists())
        # As on a real host, the login user cannot write /etc directly.
        etc = [self.root / "etc", *(self.root / "etc").rglob("*")]
        self.addCleanup(
            lambda: [
                path.chmod(path.stat().st_mode | 0o200) for path in etc if path.exists()
            ]
        )
        for path in etc:
            path.chmod(path.stat().st_mode & ~0o222)
        (self.root / "commands.jsonl").unlink()
        self.invoke("--purge")
        self.assertFalse((self.root / "etc/pwrstatd.conf").exists())
        self.assertFalse(
            (self.root / "etc/pacman.d/nix-config-lizardbyte.conf").exists()
        )
        self.assertNotIn(
            "nix-config-lizardbyte", (self.root / "etc/pacman.conf").read_text()
        )
        conf = (self.root / "etc/nix/nix.conf").read_text()
        self.assertEqual(conf, "build-users-group = nixbld\n")
        self.assertTrue(
            any(
                call == ["systemctl", "restart", "nix-daemon.service"]
                for call in self.commands()
            )
        )

    def test_failed_purge_keeps_pacman_repository_loadable(self):
        self.invoke()
        self.state["fail"] = ["install", "-m0644"]
        self.save()
        self.invoke("--purge", code=1)
        pacman = (self.root / "etc/pacman.conf").read_text()
        self.assertIn("nix-config-lizardbyte", pacman)
        self.assertTrue(
            (self.root / "etc/pacman.d/nix-config-lizardbyte.conf").exists()
        )

    def test_unit_that_stays_inactive_after_start_fails_with_its_name(self):
        self.state["inactive_after_start"] = ["bluetooth.service"]
        self.save()
        result = self.invoke(code=1)
        self.assertIn("bluetooth.service did not become active", result.stderr)

    def test_multilib_package_requires_repository_before_update(self):
        self.state["no_multilib"] = True
        self.save()
        self.script.write_text(
            self.script.read_text().replace(
                "pacman_packages=(base)", "pacman_packages=(base lib32-fixture)"
            )
        )
        result = self.invoke("--update", code=1)
        self.assertIn("[multilib]", result.stderr)
        self.assertFalse(
            any(call[0] == "pacman" and "--sync" in call for call in self.commands())
        )

    def test_powerpanel_converges_and_restarts_service(self):
        conf = self.root / "fixture-pwrstatd.conf"
        conf.write_text("powerfail-shutdown = no\nruntime-threshold = 300\n")
        self.state["services"]["system:pwrstatd.service"] = {
            "enabled": True,
            "active": True,
        }
        self.save()
        source = self.script.read_text()
        self.script.write_text(
            f"manage_powerpanel=1\npowerpanel_conf={shlex.quote(str(conf))}\n" + source
        )
        self.invoke()
        installed = self.root / "etc/pwrstatd.conf"
        self.assertTrue(installed.is_file())
        self.assertEqual(installed.read_text(), conf.read_text())
        self.assertTrue(
            any(
                call == ["systemctl", "restart", "pwrstatd.service"]
                for call in self.commands()
            )
        )


if __name__ == "__main__":
    unittest.main()
