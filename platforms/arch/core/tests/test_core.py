# pyright: standard
"""Core adapter contracts on a temporary root with a stateful fake runner."""

import contextlib
import copy
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nix_adapter import Conflict, FakeNative, FakeProcess, Files

RUNTIME_PATH = Path(__file__).resolve().parents[1] / "runtime.py"
sys.path.insert(0, str(RUNTIME_PATH.parent))
spec = importlib.util.spec_from_file_location("core_runtime", RUNTIME_PATH)
assert spec is not None and spec.loader is not None
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)

INCLUDE = "Include = /etc/pacman.d/nix-config-lizardbyte.conf"
NIX_BLOCK = {
    "path": "/etc/nix/nix.conf",
    "name": "settings",
    "text": "trusted-users = root @wheel tester\n",
    "action": "nix-daemon",
    "create": True,
}
MANIFEST = {
    "user": "tester",
    "files": [
        {
            "path": "/etc/NetworkManager/conf.d/main.conf",
            "text": "[main]\n",
            "action": "network",
        },
        {"path": "/etc/sysctl.d/99-nix-config.conf", "text": "a = 1\n", "action": None},
        {
            "path": "/etc/pwrstatd.conf",
            "text": "runtime-threshold = 300\n",
            "action": "pwrstatd",
        },
    ],
    "repository": {
        "name": "lizardbyte",
        "path": "/etc/pacman.d/nix-config-lizardbyte.conf",
        "text": "[lizardbyte]\nServer = https://repo.example\n",
        "source": "/fixture/lizardbyte.conf",
        "include": INCLUDE,
    },
    "blocks": [
        {
            "path": "/etc/mkinitcpio.conf",
            "name": "modules",
            "text": "MODULES+=( usbhid )\n",
            "action": "initramfs",
            "create": False,
        },
        NIX_BLOCK,
    ],
    "initramfsImages": ["/boot/initramfs-linux.img"],
    "groups": ["wheel", "i2c"],
    "units": ["NetworkManager.service", "libvirtd.socket"],
    "reloadUnits": True,
    "restarts": [
        {"action": "network", "unit": "NetworkManager.service", "onlyIfActive": False},
        {"action": "nix-daemon", "unit": "nix-daemon.service", "onlyIfActive": False},
        {"action": "pwrstatd", "unit": "pwrstatd.service", "onlyIfActive": True},
    ],
    "kernelModules": ["br_netfilter"],
    "sysctl": {"net.ipv4.ip_forward": "1"},
    "fileCapabilities": [
        {"path": "/usr/bin/sunshine", "capability": "cap_sys_admin=p"}
    ],
    "purge": {
        "blocks": [NIX_BLOCK],
        "ownedUnits": [
            {
                "unit": "fixture-extension.service",
                "path": "/etc/systemd/system/fixture-extension.service",
            }
        ],
    },
}


class Fake(FakeNative):
    def __init__(self, root: Path):
        super().__init__()
        self.root = root
        self.fail: tuple[str, ...] | None = None
        self.groups = {"wheel"}
        self.units: dict[str, dict[str, bool]] = {}
        self.sysctl: dict[str, str] = {}
        self.capabilities: set[str] = set()
        self.stay_inactive: set[str] = set()
        self.unmanaged_repository = False

    def unit(self, name):
        return self.units.setdefault(name, {"enabled": False, "active": False})

    def run(self, *args, check=True, **kwargs):
        self.calls.append(args)
        if self.fail and args[: len(self.fail)] == self.fail:
            raise Conflict("injected native failure")
        cmd, *rest = args
        out, code = "", 0
        if cmd == "id":
            out = " ".join(sorted(self.groups))
        elif cmd == "gpasswd":
            self.groups.add(rest[-1])
        elif cmd == "systemctl":
            rest = [value for value in rest if value not in ("--quiet", "--now")]
            verb, *units = rest
            unit = self.unit(units[0]) if units else {}
            if verb == "show":
                out = "LoadState=loaded\nActiveState={}\nUnitFileState={}\n".format(
                    "active" if unit["active"] else "inactive",
                    "enabled" if unit["enabled"] else "disabled",
                )
            elif verb == "is-enabled":
                code = 0 if unit["enabled"] else 1
            elif verb == "is-active":
                code = 0 if unit["active"] else 3
            elif verb == "enable":
                unit["enabled"] = True
            elif verb == "disable":
                unit.update(enabled=False, active=False)
            elif verb in ("start", "restart"):
                unit["active"] = units[0] not in self.stay_inactive
            elif verb != "daemon-reload":
                raise AssertionError(args)
        elif cmd == "sysctl":
            if rest[0] == "-n":
                out = self.sysctl.get(rest[1], "0")
            else:
                key, value = rest[1].split("=", 1)
                self.sysctl[key] = value
        elif cmd == "modprobe":
            (self.root / "sys/module" / rest[0]).mkdir(parents=True)
        elif cmd == "mkinitcpio":
            (self.root / "boot/initramfs-linux.img").write_text("image")
        elif cmd == "getcap":
            out = f"{rest[0]} cap_sys_admin=p" if rest[0] in self.capabilities else ""
        elif cmd == "setcap":
            self.capabilities.add(rest[-1])
        elif cmd == "pacman-conf":
            pacman = (self.root / "etc/pacman.conf").read_text()
            loaded = (
                "--config" in rest or self.unmanaged_repository or INCLUDE in pacman
            )
            out, code = ("https://repo.example", 0) if loaded else ("", 1)
        else:
            raise AssertionError(args)
        if code and check:
            raise Conflict(f"fake native failed: {args}")
        return FakeProcess(stdout=out, returncode=code)


class CoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name in ("etc/nix", "boot", "usr/bin", "sys/module"):
            (self.root / name).mkdir(parents=True)
        (self.root / "etc/pacman.conf").write_text("[options]\n")
        (self.root / "etc/mkinitcpio.conf").write_text("MODULES=(existing)\n")
        (self.root / "etc/nix/nix.conf").write_text("build-users-group = nixbld\n")
        (self.root / "usr/bin/sunshine").write_text("binary")
        self.files = Files(self.root, (os.getuid(), os.getgid()))
        self.native = Fake(self.root)
        self.manifest = copy.deepcopy(MANIFEST)
        self.output = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.output))

    def core(self):
        return runtime.Core(self.manifest, self.files, self.native)

    def deploy(self):
        core = self.core()
        core.preflight()
        core.repositories()
        core.converge()
        core.finish()
        return core

    def marker(self, action):
        return self.root / f"var/lib/nix-config/arch/{action}.pending"

    def snapshot(self):
        return {
            str(path): (path.stat().st_ino, path.stat().st_mtime_ns)
            for path in (self.root / "etc").rglob("*")
            if path.is_file()
        }

    def test_deploy_converges_policy_and_repeat_changes_nothing(self):
        self.deploy()
        main = self.root / "etc/NetworkManager/conf.d/main.conf"
        self.assertEqual(main.read_text(), "[main]\n")
        self.assertEqual(main.stat().st_mode & 0o777, 0o644)
        self.assertEqual(
            (self.root / "etc/nix/nix.conf").read_text(),
            "build-users-group = nixbld\n"
            "# BEGIN nix-config settings\n"
            "trusted-users = root @wheel tester\n"
            "# END nix-config settings\n",
        )
        self.assertTrue(
            (self.root / "etc/mkinitcpio.conf")
            .read_text()
            .startswith("MODULES=(existing)\n")
        )
        self.assertIn(INCLUDE, (self.root / "etc/pacman.conf").read_text())
        self.assertTrue((self.root / "boot/initramfs-linux.img").is_file())
        self.assertIn("i2c", self.native.groups)
        self.assertTrue(all(self.native.unit(u)["active"] for u in MANIFEST["units"]))
        self.assertEqual(self.native.sysctl["net.ipv4.ip_forward"], "1")
        self.assertTrue((self.root / "sys/module/br_netfilter").is_dir())
        self.assertIn("/usr/bin/sunshine", self.native.capabilities)
        self.assertIn(("systemctl", "restart", "nix-daemon.service"), self.native.calls)
        self.assertEqual(list((self.root / "var/lib/nix-config/arch").iterdir()), [])
        self.assertIn("Group membership changed", self.output.getvalue())

        before = self.snapshot()
        self.native.calls.clear()
        core = self.deploy()
        self.assertEqual((core.updates, core.actions), (0, 0))
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(
            any(
                call[:2] in (("systemctl", "restart"), ("mkinitcpio", "-P"))
                for call in self.native.calls
            )
        )

    def plan(self):
        return [f"{change.kind} {change.text}" for change in self.core().plan()]

    def test_plan_lists_every_change_without_making_it(self):
        before = sorted(str(path) for path in self.root.rglob("*"))
        lines = self.plan()
        self.assertEqual(sorted(str(path) for path in self.root.rglob("*")), before)
        for expected in (
            "+ /etc/NetworkManager/conf.d/main.conf",
            "~ /etc/nix/nix.conf (content differs)",
            "~ /etc/pacman.conf (add repository Include)",
            "~ rebuild initramfs images",
            "~ add tester to group i2c",
            "~ start libvirtd.socket",
            "~ load kernel module br_netfilter",
            "~ sysctl net.ipv4.ip_forward: 0 -> 1",
            "~ set cap_sys_admin=p on /usr/bin/sunshine",
        ):
            self.assertIn(expected, lines)
        self.assertFalse(
            any(
                call[0] in ("gpasswd", "modprobe", "setcap")
                for call in self.native.calls
            )
        )
        self.assertFalse(
            any(call[:2] == ("systemctl", "start") for call in self.native.calls)
        )

    def test_plan_after_deploy_reports_no_change(self):
        self.deploy()
        lines = self.plan()
        self.assertTrue(all(line.startswith("=") for line in lines), lines)

    def test_plan_reports_a_conflict_and_fails(self):
        (self.root / "etc/mkinitcpio.conf").write_text("# BEGIN nix-config modules\n")
        with self.assertRaisesRegex(Conflict, "unterminated managed block"):
            self.plan()

    def test_withdrawn_sections_leave_files_and_pending_actions(self):
        main = self.root / "etc/NetworkManager/conf.d/main.conf"
        main.parent.mkdir(parents=True)
        main.write_text("operator\n")
        self.marker("network").parent.mkdir(parents=True)
        self.marker("network").touch()
        for key in (
            "files",
            "blocks",
            "initramfsImages",
            "groups",
            "units",
            "restarts",
            "kernelModules",
            "fileCapabilities",
        ):
            self.manifest[key] = []
        self.manifest["sysctl"] = {}
        self.manifest["repository"] = None
        self.manifest["reloadUnits"] = False
        self.deploy()
        self.assertEqual(main.read_text(), "operator\n")
        self.assertTrue(self.marker("network").exists())
        self.assertEqual((self.root / "etc/pacman.conf").read_text(), "[options]\n")

    def test_failed_restart_stays_pending_and_is_retried(self):
        self.native.fail = ("systemctl", "restart", "NetworkManager.service")
        with self.assertRaises(Conflict):
            self.deploy()
        self.assertTrue(self.marker("network").exists())
        self.native.fail = None
        self.deploy()
        self.assertFalse(self.marker("network").exists())

    def test_failed_initramfs_is_retried_and_a_missing_image_rebuilt(self):
        self.native.fail = ("mkinitcpio",)
        with self.assertRaises(Conflict):
            self.deploy()
        self.assertTrue(self.marker("initramfs").exists())
        self.native.fail = None
        self.deploy()
        image = self.root / "boot/initramfs-linux.img"
        image.unlink()
        self.deploy()
        self.assertTrue(image.is_file())

    def test_runtime_and_file_drift_are_repaired(self):
        self.deploy()
        main = self.root / "etc/NetworkManager/conf.d/main.conf"
        main.chmod(0o600)
        self.native.sysctl["net.ipv4.ip_forward"] = "0"
        self.native.unit("libvirtd.socket")["active"] = False
        self.deploy()
        self.assertEqual(main.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.native.sysctl["net.ipv4.ip_forward"], "1")
        self.assertTrue(self.native.unit("libvirtd.socket")["active"])

    def test_unit_that_stays_inactive_after_start_fails_with_its_name(self):
        self.native.stay_inactive.add("libvirtd.socket")
        with self.assertRaisesRegex(
            Conflict, "libvirtd.socket did not become enabled and active"
        ):
            self.deploy()

    def test_inactive_powerpanel_is_not_restarted(self):
        self.deploy()
        self.marker("pwrstatd").touch()
        self.deploy()
        self.assertNotIn(
            ("systemctl", "restart", "pwrstatd.service"), self.native.calls
        )
        self.assertFalse(self.marker("pwrstatd").exists())

    def test_unterminated_block_fails_preflight_without_writes(self):
        path = self.root / "etc/mkinitcpio.conf"
        original = "MODULES=(existing)\n# BEGIN nix-config modules\nHOOKS=(keep)\n"
        path.write_text(original)
        with self.assertRaisesRegex(Conflict, "unterminated managed block"):
            self.core().preflight()
        self.assertEqual(path.read_text(), original)

    def test_unmanaged_repository_is_rejected_before_writes(self):
        self.native.unmanaged_repository = True
        with self.assertRaisesRegex(Conflict, "unmanaged \\[lizardbyte\\]"):
            self.core().preflight()
        self.assertFalse((self.root / "etc/pacman.d").exists())

    def test_symlinked_target_is_rejected(self):
        target = self.root / "etc/pwrstatd.conf"
        target.symlink_to(self.root / "etc/pacman.conf")
        with self.assertRaises(Conflict):
            self.core().preflight()

    def test_purge_withdraws_managed_state_and_preserves_the_rest(self):
        self.deploy()
        pacman = self.root / "etc/pacman.conf"
        pacman.write_text(pacman.read_text() + "[custom]\n")
        unit = self.root / "etc/systemd/system/fixture-extension.service"
        unit.parent.mkdir(parents=True)
        unit.write_text("[Unit]\n")
        self.native.unit("fixture-extension.service")["enabled"] = True
        self.native.unit("nix-daemon.service")["active"] = True
        self.native.calls.clear()
        self.core().purge()
        for entry in MANIFEST["files"]:
            self.assertFalse((self.root / entry["path"].lstrip("/")).exists())
        self.assertFalse(
            (self.root / "etc/pacman.d/nix-config-lizardbyte.conf").exists()
        )
        self.assertEqual(pacman.read_text(), "[options]\n\n[custom]\n")
        self.assertEqual(
            (self.root / "etc/nix/nix.conf").read_text(), "build-users-group = nixbld\n"
        )
        self.assertIn(
            "nix-config modules", (self.root / "etc/mkinitcpio.conf").read_text()
        )
        self.assertFalse(unit.exists())
        self.assertFalse(any(self.native.unit(u)["enabled"] for u in MANIFEST["units"]))
        self.assertIn(("systemctl", "restart", "nix-daemon.service"), self.native.calls)
        self.assertIn(("systemctl", "daemon-reload"), self.native.calls)
        self.assertFalse((self.root / "var/lib/nix-config/arch").exists())

    def test_failed_purge_keeps_pacman_repository_loadable(self):
        self.deploy()
        write = self.files.write

        def refuse_pacman(name, *args, **kwargs):
            if name == "/etc/pacman.conf":
                raise OSError("injected write failure")
            return write(name, *args, **kwargs)

        with (
            patch.object(self.files, "write", refuse_pacman),
            self.assertRaises(OSError),
        ):
            self.core().purge()
        self.assertIn(INCLUDE, (self.root / "etc/pacman.conf").read_text())
        self.assertTrue(
            (self.root / "etc/pacman.d/nix-config-lizardbyte.conf").exists()
        )


if __name__ == "__main__":
    unittest.main()
