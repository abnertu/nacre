"""Stable adapter contracts, using temporary paths and a fake native runner."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from nix_adapter import (
    Conflict,
    FakeNative,
    FakeProcess,
    Files,
)

RUNTIME_PATH = Path(__file__).resolve().parents[1] / "runtime.py"
spec = importlib.util.spec_from_file_location("runtime", RUNTIME_PATH)
assert spec is not None and spec.loader is not None
runtime = importlib.util.module_from_spec(spec)
sys.modules["runtime"] = runtime
spec.loader.exec_module(runtime)
System = runtime.System


class Fake(FakeNative):
    def __init__(self, files):
        super().__init__()
        self.files = files
        self.fail: tuple[str, ...] | None = None
        self.locales = ["C", "en_US.utf8", "zh_TW.utf8"]
        self.zone = "UTC"
        self.local_rtc = "no"
        self.host = {"--static": "old", "--transient": "old"}
        self.units = {}
        self.active = True
        self.rules = {("7777", "tcp", False), ("7777", "tcp", True)}
        self.kernel = set(self.rules)
        self.policy_ok = True
        self.logging = "low"
        self.profiles = "skip"
        self.disks = [
            {"name": "vda", "type": "disk", "disc-max": 4096, "mountpoints": ["/"]}
        ]

    def unit(self, name):
        return self.units.setdefault(
            name,
            {
                "LoadState": "loaded",
                "ActiveState": "inactive",
                "UnitFileState": "disabled",
            },
        )

    def run(self, *args, check=True, **kwargs):
        self.calls.append(args)
        if self.fail and args[: len(self.fail)] == self.fail:
            raise Conflict("injected native failure")
        code, out = 0, ""
        cmd, *rest = args
        if cmd == "systemctl":
            verb = rest[0]
            if verb == "show":
                out = "\n".join(f"{k}={v}" for k, v in self.unit(rest[1]).items())
            elif verb in ("enable", "start", "restart"):
                self.unit(rest[1])[
                    "UnitFileState" if verb == "enable" else "ActiveState"
                ] = "enabled" if verb == "enable" else "active"
            elif verb not in ("list-timers", "daemon-reload", "try-restart"):
                raise AssertionError(args)
        elif cmd == "timedatectl":
            if rest[0] == "set-timezone":
                self.zone = rest[1]
                path = self.files.path("/etc/localtime", symlink_leaf=True)
                path.unlink(missing_ok=True)
                path.symlink_to("/usr/share/zoneinfo/" + self.zone)
            elif "--value" in rest:
                out = "no\n"
            else:
                out = f"Timezone={self.zone}\nLocalRTC={self.local_rtc}\n"
        elif cmd == "hostnamectl":
            if len(rest) == 1:
                out = self.host[rest[0]]
            else:
                self.host[rest[0]] = rest[-1]
                if rest[0] == "--static":
                    self.files.write("/etc/hostname", rest[-1] + "\n")
        elif cmd == "locale":
            out = "\n".join(self.locales)
        elif cmd == "locale-gen":
            self.locales = ["en_US.utf8", "zh_TW.utf8", "C"]
        elif cmd in ("systemd-tmpfiles", "journalctl"):
            pass
        elif cmd == "lsblk":
            out = json.dumps({"blockdevices": self.disks})
        elif cmd == "ufw":
            if rest[:2] == ["status", "verbose"]:
                if not self.active:
                    out = "Status: inactive\n"
                else:
                    out = f"Status: active\nLogging: on ({self.logging})\nDefault: deny (incoming), allow (outgoing), deny (routed)\nNew profiles: {self.profiles}\n\nTo Action From\n-- ------ ----\n"
                    for port, protocol, v6 in sorted(self.rules):
                        suffix = " (v6)" if v6 else ""
                        out += f"{port}/{protocol}{suffix}    ALLOW IN    Anywhere{suffix}\n"
            elif rest[0] == "allow":
                port, protocol = rest[-1].split("/")
                for v6 in (False, True):
                    self.rules.add((port, protocol, v6))
                self.kernel = set(self.rules)
            elif rest[0] == "logging":
                self.logging = rest[1]
            elif rest[0] == "app":
                self.profiles = rest[-1]
            elif rest[0] in ("--force", "reload"):
                self.active = True
                self.policy_ok = True
                self.kernel = set(self.rules)
            else:
                raise AssertionError(args)
        elif cmd in ("iptables", "ip6tables"):
            if "-S" in rest:
                chain = rest[-1]
                policy = "ACCEPT" if chain == "OUTPUT" or not self.policy_ok else "DROP"
                out = f"-P {chain} {policy}\n"
            else:
                code = (
                    0
                    if (
                        rest[
                            rest.index("--dports" if "--dports" in rest else "--dport")
                            + 1
                        ],
                        rest[rest.index("-p") + 1],
                        cmd == "ip6tables",
                    )
                    in self.kernel
                    else 1
                )
        else:
            raise AssertionError(args)
        if code and check:
            raise Conflict("fake native failed")
        return FakeProcess(stdout=out, returncode=code)


class SystemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.files = Files(self.root, (os.getuid(), os.getgid()))
        self.native = Fake(self.files)
        self.d = {}
        self.system = System(self.d, self.files, self.native)
        self.output = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.output))

    def write(self, path, text):
        self.files.write(path, text)

    def test_entrypoint_never_writes_bytecode_beside_its_source(self):
        # Root ignores store permissions; bytecode there corrupts the store path.
        with tempfile.TemporaryDirectory() as directory:
            for name in ("adapter.py", "runtime.py"):
                shutil.copy(RUNTIME_PATH.with_name(name), directory)
            env = {
                k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"
            }
            subprocess.run(
                [sys.executable, str(Path(directory) / "adapter.py")],
                env=env,
                capture_output=True,
            )
            self.assertEqual(
                sorted(os.listdir(directory)), ["adapter.py", "runtime.py"]
            )

    def test_purge_removes_owned_dropins_and_keeps_system_values(self):
        names = ("timesyncd", "journald", "logind")
        for name in names:
            self.write(f"/etc/systemd/{name}.conf.d/60-nix-config.conf", "[X]\n")
        self.write("/etc/systemd/system/fstrim.timer.d/60-nix-config.conf", "[Timer]\n")
        self.write("/etc/locale.conf", "LANG=en_US.UTF-8\n")
        self.d.update(files={name: "[X]\n" for name in names}, trim={})
        self.system.purge()
        for name in names:
            self.assertFalse(
                (self.root / f"etc/systemd/{name}.conf.d/60-nix-config.conf").exists()
            )
        self.assertFalse(
            (
                self.root / "etc/systemd/system/fstrim.timer.d/60-nix-config.conf"
            ).exists()
        )
        self.assertEqual(
            (self.root / "etc/locale.conf").read_text(), "LANG=en_US.UTF-8\n"
        )
        restarted = [
            call[2]
            for call in self.native.calls
            if call[:2] == ("systemctl", "try-restart")
        ]
        self.assertEqual(
            restarted, ["systemd-timesyncd.service", "systemd-journald.service"]
        )

    def test_unmanaged_does_nothing(self):
        self.system.converge()
        self.assertEqual(self.native.calls, [])
        self.assertEqual(list(self.root.iterdir()), [])

    def locale(self):
        self.d["locale"] = {
            "generated": ["en_US.UTF-8", "zh_TW.UTF-8"],
            "lang": "en_US.UTF-8",
        }
        self.write(
            "/etc/locale.gen", "# operator\nen_US.UTF-8 UTF-8  \nde_DE.UTF-8 UTF-8\n"
        )
        self.write("/etc/locale.conf", "# operator\nLANG=old\nLC_TIME=zh_TW.UTF-8\n")

    def test_locale_preserves_unowned_and_repeat_does_not_generate(self):
        self.locale()
        self.system.converge()
        self.assertIn("de_DE.UTF-8 UTF-8", self.files.read("/etc/locale.gen"))
        self.assertIn("LC_TIME=zh_TW.UTF-8", self.files.read("/etc/locale.conf"))
        before = self.files.path("/etc/locale.gen").stat()
        self.native.calls.clear()
        self.system.converge()
        self.assertNotIn(("locale-gen",), self.native.calls)
        self.assertEqual(
            before.st_ino, self.files.path("/etc/locale.gen").stat().st_ino
        )

    def test_locale_failure_does_not_publish_lang_and_retries(self):
        self.locale()
        self.native.fail = ("locale-gen",)
        with self.assertRaises(Conflict):
            self.system.converge()
        self.assertIn("LANG=old", self.files.read("/etc/locale.conf"))
        self.assertTrue(self.files.pending("locale"))
        self.native.fail = None
        self.system.converge()
        self.assertFalse(self.files.pending("locale"))

    def test_locale_runtime_drift_and_metadata_repair(self):
        self.locale()
        self.system.converge()
        self.native.calls.clear()
        self.native.locales = ["C"]
        self.files.path("/etc/locale.conf").chmod(0o600)
        self.system.converge()
        self.assertIn(("locale-gen",), self.native.calls)
        self.assertEqual(
            self.files.path("/etc/locale.conf").stat().st_mode & 0o777, 0o644
        )

    def test_preflight_conflict_before_any_write(self):
        self.locale()
        self.d["files"] = {"journald": "[Journal]\nStorage=volatile\n"}
        self.write(
            "/etc/systemd/journald.conf.d/operator.conf",
            "[Journal]\nStorage=persistent\n",
        )
        original = self.files.read("/etc/locale.gen")
        with self.assertRaises(Conflict):
            self.system.converge()
        self.assertEqual(self.files.read("/etc/locale.gen"), original)
        self.assertFalse(self.files.pending("locale"))

    def test_symlink_ancestor_and_leaf_are_rejected(self):
        self.locale()
        self.files.path("/etc/locale.conf").unlink()
        self.files.path("/etc/locale.conf").symlink_to("/dev/null")
        with self.assertRaises(Conflict):
            self.system.converge()
        (self.root / "var").symlink_to("/tmp")
        with self.assertRaises(Conflict):
            self.files.mark("locale")

    def timezone(self):
        self.d["timeZone"] = "Asia/Taipei"
        self.write("/usr/share/zoneinfo/Asia/Taipei", "fixture")
        (self.root / "etc").mkdir(exist_ok=True)

    def test_timezone_and_hostname_repeat_and_drift(self):
        self.timezone()
        self.d["hostname"] = "fixture"
        self.system.converge()
        self.native.calls.clear()
        self.system.converge()
        self.assertFalse(
            any(
                "set-timezone" in call or "set-hostname" in call
                for call in self.native.calls
            )
        )
        self.native.host["--transient"] = "drift"
        self.system.converge()
        self.assertEqual(self.native.host["--transient"], "fixture")

    def test_timezone_rejects_regular_file_local_rtc_and_missing_zone(self):
        self.timezone()
        self.write("/etc/localtime", "unowned")
        with self.assertRaises(Conflict):
            self.system.converge()
        self.files.path("/etc/localtime").unlink()
        self.native.local_rtc = "yes"
        with self.assertRaises(Conflict):
            self.system.converge()
        self.native.local_rtc = "no"
        self.files.path("/usr/share/zoneinfo/Asia/Taipei").unlink()
        with self.assertRaises(Conflict):
            self.system.converge()

    def test_timezone_failure_retains_marker(self):
        self.timezone()
        self.native.fail = ("timedatectl", "set-timezone")
        with self.assertRaises(Conflict):
            self.system.converge()
        self.assertTrue(self.files.pending("timezone"))
        self.native.fail = None
        self.system.converge()
        self.assertFalse(self.files.pending("timezone"))

    def timesync(self):
        self.d["timeSync"] = {"provider": "systemd-timesyncd", "servers": []}
        self.d["files"] = {"timesyncd": "[Time]\n"}

    def test_timesync_offline_repeat_and_runtime_drift(self):
        self.timesync()
        self.system.converge()
        self.assertIn("waiting for network synchronization", self.output.getvalue())
        self.native.calls.clear()
        self.system.converge()
        self.assertFalse(
            any(
                call[1] in ("start", "restart", "enable")
                for call in self.native.calls
                if call[0] == "systemctl"
            )
        )
        self.native.unit("systemd-timesyncd.service")["ActiveState"] = "inactive"
        self.system.converge()
        self.assertEqual(
            self.native.unit("systemd-timesyncd.service")["ActiveState"], "active"
        )

    def test_timesync_conflict_and_failed_restart(self):
        self.timesync()
        self.native.unit("chronyd.service")["ActiveState"] = "active"
        with self.assertRaises(Conflict):
            self.system.converge()
        self.native.unit("chronyd.service")["ActiveState"] = "inactive"
        self.native.fail = ("systemctl", "restart")
        with self.assertRaises(Conflict):
            self.system.converge()
        self.assertTrue(self.files.pending("timesyncd"))
        self.native.fail = None
        self.system.converge()
        self.assertFalse(self.files.pending("timesyncd"))

    def test_journal_flush_failure_retries_without_vacuum(self):
        self.d["journal"] = {"storage": "persistent"}
        self.d["files"] = {"journald": "[Journal]\nStorage=persistent\n"}
        self.native.fail = ("journalctl", "--flush")
        with self.assertRaises(Conflict):
            self.system.converge()
        self.assertTrue(self.files.pending("journald"))
        self.native.fail = None
        self.system.converge()
        self.assertFalse(self.files.pending("journald"))
        self.native.calls.clear()
        self.system.converge()
        self.assertNotIn(
            ("systemctl", "restart", "systemd-journald.service"), self.native.calls
        )

    def test_console_preserves_font_and_never_changes_live_tty(self):
        self.d["console"] = {"keymap": "us", "font": None}
        self.write("/etc/vconsole.conf", "FONT=keep\n")
        self.write("/usr/share/kbd/keymaps/us.map.gz", "fixture")
        self.system.converge()
        self.assertIn("FONT=keep", self.files.read("/etc/vconsole.conf"))
        self.assertEqual(self.native.calls, [])

    def test_power_waits_for_boot_and_never_restarts_logind(self):
        self.d["power"] = {"powerKey": "ignore", "lidSwitch": None}
        self.d["files"] = {"logind": "[Login]\nHandlePowerKey=ignore\n"}
        self.write("/proc/sys/kernel/random/boot_id", "boot-one\n")
        self.system.converge()
        self.assertTrue(self.files.pending("power"))
        self.system.converge()
        self.assertTrue(self.files.pending("power"))
        self.write("/proc/sys/kernel/random/boot_id", "boot-two\n")
        self.system.converge()
        self.assertFalse(self.files.pending("power"))
        self.assertEqual(self.native.calls, [])

    def test_trim_timer_only_and_encryption_gate(self):
        self.d["trim"] = {"enable": True}
        self.d["trimDropin"] = "[Timer]\nPersistent=false\n"
        self.native.disks[0]["type"] = "crypt"
        with self.assertRaises(Conflict):
            self.system.converge()
        self.native.disks[0]["type"] = "disk"
        self.system.converge()
        self.assertIn(("systemctl", "restart", "fstrim.timer"), self.native.calls)
        self.assertFalse(any(call[0] == "fstrim" for call in self.native.calls))

    def firewall(self):
        self.d["firewall"] = {
            "logging": "low",
            "rules": [{"protocol": "tcp", "fromPort": 7777, "toPort": None}],
        }
        self.write(
            "/etc/default/ufw",
            'IPV6=yes\nMANAGE_BUILTINS=no\nDEFAULT_INPUT_POLICY="DROP"\nDEFAULT_OUTPUT_POLICY="ACCEPT"\nDEFAULT_FORWARD_POLICY="DROP"\n',
        )
        self.native.unit("ufw.service").update(
            ActiveState="active", UnitFileState="enabled"
        )

    def test_firewall_adopts_rules_and_preserves_unowned_rules(self):
        self.firewall()
        self.native.rules.add(("1234", "udp", False))
        self.system.converge()
        self.assertFalse(
            any(call[0] == "ufw" and call[1] != "status" for call in self.native.calls)
        )
        self.assertIn(("1234", "udp", False), self.native.rules)

    def test_firewall_adds_missing_ipv6_and_repairs_kernel_drift(self):
        self.firewall()
        self.native.rules.remove(("7777", "tcp", True))
        self.system.converge()
        self.assertIn(("ufw", "allow", "in", "7777/tcp"), self.native.calls)
        self.native.calls.clear()
        self.native.kernel.clear()
        self.system.converge()
        self.assertIn(("ufw", "reload"), self.native.calls)

    def test_firewall_failure_retry_and_removal_does_not_retire(self):
        self.firewall()
        self.native.kernel.clear()
        self.native.fail = ("ufw", "reload")
        with self.assertRaises(Conflict):
            self.system.converge()
        self.assertTrue(self.files.pending("firewall"))
        self.native.fail = None
        self.system.converge()
        self.assertFalse(self.files.pending("firewall"))
        self.d["firewall"] = None
        self.native.calls.clear()
        self.system.converge()
        self.assertEqual(self.native.calls, [])
        self.assertTrue(self.native.active)

    def test_firewall_conflicting_owner_and_unsafe_builtins(self):
        self.firewall()
        self.native.unit("nftables.service")["ActiveState"] = "active"
        with self.assertRaises(Conflict):
            self.system.converge()
        self.native.unit("nftables.service")["ActiveState"] = "inactive"
        self.write("/etc/default/ufw", "IPV6=yes\nMANAGE_BUILTINS=yes\n")
        with self.assertRaises(Conflict):
            self.system.converge()

    def test_missing_or_masked_unit_does_not_succeed(self):
        self.timesync()
        self.native.unit("systemd-timesyncd.service")["UnitFileState"] = "masked"
        with self.assertRaises(Conflict):
            self.system.converge()

    def test_firewall_range_and_policy_drift(self):
        self.firewall()
        self.d["firewall"]["rules"].append(
            {"protocol": "udp", "fromPort": 27031, "toPort": 27036}
        )
        self.system.converge()
        self.assertIn(("27031:27036", "udp", True), self.native.kernel)
        self.native.policy_ok = False
        self.native.calls.clear()
        self.system.converge()
        self.assertIn(("ufw", "reload"), self.native.calls)

    def test_missing_native_command_precedes_writes(self):
        self.locale()
        self.native.available = lambda command: command != "locale-gen"
        with self.assertRaises(Conflict):
            self.system.converge()
        self.assertFalse(self.files.pending("locale"))
        self.assertIn("LANG=old", self.files.read("/etc/locale.conf"))

    def test_atomic_write_failure_keeps_pending_and_cleans_temp(self):
        self.locale()
        original = os.replace

        def replace(source, target):
            if str(target).endswith("/etc/locale.gen"):
                raise OSError("fixture failure")
            return original(source, target)

        with patch("nix_adapter.files.os.replace", side_effect=replace):
            with self.assertRaises(OSError):
                self.system.converge()
        self.assertTrue(self.files.pending("locale"))
        self.assertEqual(list((self.root / "etc").glob(".nix-config.*")), [])
        self.assertEqual(
            self.files.path(self.files.marker("locale")).stat().st_mode & 0o777, 0o600
        )
        self.system.converge()
        self.assertFalse(self.files.pending("locale"))

    def test_unsafe_parent_and_special_file_preflight(self):
        self.locale()
        self.files.path("/etc").chmod(0o777)
        with self.assertRaises(Conflict):
            self.system.converge()
        self.files.path("/etc").chmod(0o755)
        self.files.path("/etc/locale.conf").unlink()
        os.mkfifo(self.root / "etc/locale.conf")
        with self.assertRaises(Conflict):
            self.system.converge()

    def test_zone_alias_is_bounded(self):
        self.write("/usr/share/zoneinfo/Etc/UTC", "fixture")
        self.files.path("/usr/share/zoneinfo/UTC").symlink_to("Etc/UTC")
        self.assertTrue(self.files.zone_exists("UTC"))
        self.files.path("/usr/share/zoneinfo/escape").symlink_to("/etc/passwd")
        with self.assertRaises(Conflict):
            self.files.zone_exists("escape")

    def test_dropin_precedence_masks_and_duplicate_keys(self):
        text = "[Journal]\nStorage=volatile\n"
        self.write(
            "/usr/lib/systemd/journald.conf.d/vendor.conf",
            "[Journal]\nStorage=persistent\n",
        )
        self.write("/etc/systemd/journald.conf.d/vendor.conf", text)
        self.files.dropin("journald", text)
        self.write(
            "/etc/systemd/journald.conf.d/conflict.conf",
            "[Journal]\nStorage=persistent\n",
        )
        with self.assertRaises(Conflict) as caught:
            self.files.dropin("journald", text)
        self.assertIn(
            "/etc/systemd/journald.conf.d/conflict.conf", str(caught.exception)
        )
        self.assertIn(
            "[Journal] Storage=persistent (expected: volatile)", str(caught.exception)
        )
        self.write(
            "/etc/systemd/journald.conf.d/vendor.conf",
            "[Journal]\nStorage=volatile\nStorage=volatile\n",
        )
        with self.assertRaises(Conflict):
            self.files.dropin("journald", text)

    def test_trim_pending_retry_and_no_catchup(self):
        self.d["trim"] = {"enable": True}
        self.d["trimDropin"] = "[Timer]\nPersistent=false\n"
        self.native.fail = ("systemctl", "restart")
        with self.assertRaises(Conflict):
            self.system.converge()
        self.assertTrue(self.files.pending("trim"))
        self.assertEqual(
            self.files.read("/etc/systemd/system/fstrim.timer.d/60-nix-config.conf"),
            "[Timer]\nPersistent=false\n",
        )
        self.native.fail = None
        self.system.converge()
        self.assertFalse(self.files.pending("trim"))
        self.native.calls.clear()
        self.system.converge()
        self.assertNotIn(("systemctl", "restart", "fstrim.timer"), self.native.calls)


if __name__ == "__main__":
    unittest.main()
