# pyright: standard
"""Core adapter contracts on a temporary root with a stateful fake runner."""

import collections
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import shlex
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


def entry(name, text, mode="0644", group="root", adopt=True, unit=None, **options):
    return {
        "name": name,
        "path": f"/etc/{name}",
        "text": text,
        "source": options.get("source"),
        "target": options.get("target"),
        "mode": mode,
        "group": group,
        "adopt": adopt,
        "unit": unit,
        "dropin": options.get("dropin", False),
        "restartIfChanged": options.get("restartIfChanged", True),
    }


def unit(name, start=True, triggers=None):
    return {"name": name, "start": start, "triggers": triggers}


UNIT_NAMES = ("NetworkManager.service", "libvirtd.socket")


NIX_BLOCK = {
    "path": "/etc/nix/nix.conf",
    "name": "settings",
    "text": "# nix-config receipts 1\ntrusted-users = root @wheel tester\n",
    "action": "nix-daemon",
    "create": True,
}
INITRAMFS_BLOCK = {
    "path": "/etc/mkinitcpio.conf",
    "name": "modules",
    "text": "MODULES+=( usbhid )\n",
    "action": "initramfs",
    "create": False,
}
MANIFEST = {
    "user": "tester",
    "etc": [
        entry("NetworkManager/conf.d/main.conf", "[main]\n"),
        entry("sysctl.d/99-nix-config.conf", "a = 1\n"),
        entry("pwrstatd.conf", "runtime-threshold = 300\n"),
    ],
    "repository": {
        "name": "lizardbyte",
        "path": "/etc/pacman.d/nix-config-lizardbyte.conf",
        "text": "[lizardbyte]\nServer = https://repo.example\n",
        "source": "/fixture/lizardbyte.conf",
        "include": INCLUDE,
    },
    "blocks": [INITRAMFS_BLOCK, NIX_BLOCK],
    "initramfsImages": ["/boot/initramfs-linux.img"],
    "groups": ["wheel", "i2c"],
    "units": [unit("NetworkManager.service", triggers="nm-1"), unit("libvirtd.socket")],
    "restarts": [
        {"action": "nix-daemon", "unit": "nix-daemon.service", "onlyIfActive": False},
    ],
    "kernelModules": ["br_netfilter"],
    "sysctl": {"net.ipv4.ip_forward": "1"},
    "fileCapabilities": [
        {"path": "/usr/bin/sunshine", "capability": "cap_sys_admin=p"}
    ],
    "purge": {
        "blocks": [INITRAMFS_BLOCK, NIX_BLOCK],
    },
    "extensions": [],
    "systemUsers": [],
    "systemGroups": [],
}


class Fake(FakeNative):
    def __init__(self, root: Path):
        super().__init__()
        self.root = root
        self.fail: tuple[str, ...] | None = None
        self.groups = {"wheel"}
        self.units: dict[str, dict[str, bool]] = {}
        # Socket properties: Accept=yes sockets, Triggers= and restart counts.
        self.accepting: set[str] = set()
        self.triggers: dict[str, list[str]] = {}
        self.restarts: collections.Counter[str] = collections.Counter()
        self.sysctl: dict[str, str] = {}
        # The capability that each binary carries.
        self.capabilities: dict[str, str] = {}
        self.stay_inactive: set[str] = set()
        # systemd-sysusers: the arguments of each run, and names it skips.
        self.sysusers: list[list[str]] = []
        self.sysusers_skip: set[str] = set()
        self.unmanaged_repository = False
        # Units that systemd does not know yet, such as one whose file is unwritten.
        self.unknown: set[str] = set()
        self.fail_extension = False
        # Package that owns each path, with its version: pacman -Qqo and -Q.
        self.owners: dict[str, tuple[str, str]] = {}

    def unit(self, name):
        return self.units.setdefault(name, {"enabled": False, "active": False})

    def run(self, *args, check=True, **kwargs):
        self.calls.append(args)
        if self.fail and args[: len(self.fail)] == self.fail:
            raise Conflict("injected native failure")
        cmd, *rest = args
        handler = {
            "id": lambda _: (0, " ".join(sorted(self.groups))),
            "gpasswd": self.gpasswd,
            "systemctl": self.systemctl,
            "sysctl": self.sysctl_command,
            "modprobe": self.modprobe,
            "mkinitcpio": self.mkinitcpio,
            "getcap": self.getcap,
            "setcap": self.setcap,
            "pacman-conf": self.pacman_conf,
            "pacman": self.pacman,
            "env": lambda _: (1 if self.fail_extension else 0, ""),
            "systemd-sysusers": self.systemd_sysusers,
        }.get(cmd)
        if handler is None:
            raise AssertionError(args)
        code, out = handler(rest)
        if code and check:
            raise Conflict(f"fake native failed: {args}")
        return FakeProcess(stdout=out, returncode=code)

    def systemd_sysusers(self, rest):
        """Apply only the given files, allocating IDs down from 999."""
        self.sysusers.append(list(rest))
        passwd, group = self.root / "etc/passwd", self.root / "etc/group"
        for name in rest:
            for line in (self.root / name.lstrip("/")).read_text().splitlines():
                fields = shlex.split(line)
                if (
                    not fields
                    or fields[0].startswith("#")
                    or fields[1] in self.sysusers_skip
                ):
                    continue
                groups = [g.split(":") for g in group.read_text().splitlines()]
                users = [u.split(":") for u in passwd.read_text().splitlines()]
                if fields[0] == "g" and fields[1] not in [g[0] for g in groups]:
                    gid = max(set(range(1, 1000)) - {int(g[2]) for g in groups})
                    group.write_text(group.read_text() + f"{fields[1]}:x:{gid}:\n")
                if fields[0] == "u" and fields[1] not in [u[0] for u in users]:
                    uid = max(set(range(1, 1000)) - {int(u[2]) for u in users})
                    primary = fields[2].split(":")[1]
                    gid = next(g[2] for g in groups if g[0] == primary)
                    passwd.write_text(
                        passwd.read_text()
                        + f"{fields[1]}:x:{uid}:{gid}:{fields[3]}:{fields[4]}:{fields[5]}\n"
                    )
        return 0, ""

    def refuses_restart(self, name):
        """systemd refuses to restart an Accept=no socket while its service runs."""
        return (
            name.endswith(".socket")
            and name not in self.accepting
            and any(self.unit(other)["active"] for other in self.triggers.get(name, []))
        )

    def gpasswd(self, rest):
        if rest[0] == "--delete":
            self.groups.discard(rest[-1])
        else:
            self.groups.add(rest[-1])
        return 0, ""

    def show(self, name):
        if name in self.unknown:
            return "LoadState=not-found\nActiveState=inactive\nUnitFileState=\n"
        unit = self.unit(name)
        active = "active" if unit["active"] else "inactive"
        enabled = "enabled" if unit["enabled"] else "disabled"
        accept = "yes" if name in self.accepting else "no"
        return (
            f"LoadState=loaded\nActiveState={active}\nUnitFileState={enabled}\n"
            f"Accept={accept}\nTriggers={' '.join(self.triggers.get(name, []))}\n"
        )

    def systemctl(self, rest):
        verb, *units = [value for value in rest if value not in ("--quiet", "--now")]
        unit = self.unit(units[0]) if units else {}
        if verb == "show":
            return 0, self.show(units[0])
        if verb == "is-enabled":
            return (0 if unit["enabled"] else 1), ""
        if verb == "is-active":
            return (0 if unit["active"] else 3), ""
        if verb == "enable":
            unit["enabled"] = True
        elif verb == "disable":
            unit.update(enabled=False, active=False)
        elif verb == "restart" and self.refuses_restart(units[0]):
            return 1, ""
        elif verb in ("start", "restart"):
            unit["active"] = units[0] not in self.stay_inactive
            self.restarts[units[0]] += verb == "restart"
        elif verb == "stop":
            unit["active"] = False
        elif verb != "daemon-reload":
            raise AssertionError(rest)
        return 0, ""

    def sysctl_command(self, rest):
        if rest[0] == "-n":
            return 0, self.sysctl.get(rest[1], "0")
        key, value = rest[1].split("=", 1)
        self.sysctl[key] = value
        return 0, ""

    def modprobe(self, rest):
        module = self.root / "sys/module" / rest[-1]
        if rest[0] == "-r":
            (module / "refcnt").unlink(missing_ok=True)
            module.rmdir()
        else:
            module.mkdir(parents=True)
            (module / "refcnt").write_text("0\n")
        return 0, ""

    def mkinitcpio(self, _):
        (self.root / "boot/initramfs-linux.img").write_text("image")
        return 0, ""

    def getcap(self, rest):
        capability = self.capabilities.get(rest[0])
        return 0, f"{rest[0]} {capability}" if capability else ""

    def setcap(self, rest):
        if rest[0] == "-r":
            self.capabilities.pop(rest[-1], None)
        else:
            self.capabilities[rest[-1]] = rest[0].replace("+", "=")
        return 0, ""

    def pacman(self, rest):
        if rest[0] == "-Qqo":
            owner = self.owners.get(rest[1])
            return (0, owner[0]) if owner else (1, "")
        if rest[0] == "-Q":
            versions = {name: version for name, version in self.owners.values()}
            return (
                (0, f"{rest[1]} {versions[rest[1]]}")
                if rest[1] in versions
                else (1, "")
            )
        raise AssertionError(rest)

    def pacman_conf(self, rest):
        pacman = (self.root / "etc/pacman.conf").read_text()
        loaded = "--config" in rest or self.unmanaged_repository or INCLUDE in pacman
        return (0, "https://repo.example") if loaded else (1, "")


class Harness(unittest.TestCase):
    """A temporary root, a fake native runner and the core adapter."""

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
        (self.root / "etc/group").write_text(f"root:x:{os.getgid()}:\n")
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

    def plan(self):
        return [f"{change.kind} {change.text}" for change in self.core().plan()]


class CoreTests(Harness):
    def test_deploy_converges_policy_and_repeat_changes_nothing(self):
        self.deploy()
        main = self.root / "etc/NetworkManager/conf.d/main.conf"
        self.assertEqual(main.read_text(), "[main]\n")
        self.assertEqual(main.stat().st_mode & 0o777, 0o644)
        self.assertEqual(
            (self.root / "etc/nix/nix.conf").read_text(),
            "build-users-group = nixbld\n"
            "# BEGIN nix-config settings\n"
            "# nix-config receipts 1\n"
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
        self.assertTrue(all(self.native.unit(u)["active"] for u in UNIT_NAMES))
        self.assertEqual(self.native.sysctl["net.ipv4.ip_forward"], "1")
        self.assertTrue((self.root / "sys/module/br_netfilter").is_dir())
        self.assertIn("/usr/bin/sunshine", self.native.capabilities)
        self.assertIn(("systemctl", "restart", "nix-daemon.service"), self.native.calls)
        self.assertEqual(
            list((self.root / "var/lib/nix-config/arch").glob("*.pending")), []
        )
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
        for key in (
            "etc",
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
        self.deploy()
        self.assertEqual(main.read_text(), "operator\n")
        self.assertEqual((self.root / "etc/pacman.conf").read_text(), "[options]\n")

    def test_failed_trigger_restart_keeps_the_old_hash_and_is_retried(self):
        self.deploy()
        self.manifest["units"][0]["triggers"] = "nm-2"
        self.native.fail = ("systemctl", "restart", "NetworkManager.service")
        with self.assertRaises(Conflict):
            self.deploy()
        self.native.fail = None
        self.native.calls.clear()
        self.deploy()
        self.assertIn(
            ("systemctl", "restart", "NetworkManager.service"), self.native.calls
        )
        self.native.calls.clear()
        self.deploy()
        self.assertNotIn(
            ("systemctl", "restart", "NetworkManager.service"), self.native.calls
        )

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

    def test_trigger_change_restarts_only_a_running_unit(self):
        self.manifest["units"].append(
            unit("pwrstatd.service", start=False, triggers="p-1")
        )
        self.deploy()
        self.native.unit("NetworkManager.service")["active"] = True
        for item in self.manifest["units"]:
            item["triggers"] = item["triggers"] and item["triggers"] + "-new"
        self.native.calls.clear()
        self.deploy()
        restarts = [
            call for call in self.native.calls if call[:2] == ("systemctl", "restart")
        ]
        self.assertEqual(restarts, [("systemctl", "restart", "NetworkManager.service")])

    def test_unit_started_now_is_not_restarted_and_a_running_one_without_hash_is(self):
        self.native.calls.clear()
        self.deploy()
        restarts = [
            call
            for call in self.native.calls
            if call[:2] == ("systemctl", "restart") and "nix-daemon" not in call[2]
        ]
        self.assertEqual(restarts, [])
        receipt = self.root / "var/lib/nix-config/arch/receipts/core.json"
        data = json.loads(receipt.read_text())
        data["triggers"] = {}
        receipt.write_text(json.dumps(data))
        self.native.calls.clear()
        self.deploy()
        self.assertIn(
            ("systemctl", "restart", "NetworkManager.service"), self.native.calls
        )
        self.native.calls.clear()
        self.deploy()
        self.assertNotIn(
            ("systemctl", "restart", "NetworkManager.service"), self.native.calls
        )

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

    def test_purge_withdraws_managed_state_and_preserves_the_rest(self):
        self.deploy()
        pacman = self.root / "etc/pacman.conf"
        pacman.write_text(pacman.read_text() + "[custom]\n")
        self.native.unit("nix-daemon.service")["active"] = True
        self.native.calls.clear()
        self.core().purge()
        for item in MANIFEST["etc"]:
            self.assertFalse((self.root / item["path"].lstrip("/")).exists())
        self.assertFalse(
            (self.root / "etc/pacman.d/nix-config-lizardbyte.conf").exists()
        )
        self.assertEqual(pacman.read_text(), "[options]\n\n[custom]\n")
        self.assertEqual(
            (self.root / "etc/nix/nix.conf").read_text(), "build-users-group = nixbld\n"
        )
        self.assertEqual(
            (self.root / "etc/mkinitcpio.conf").read_text(), "MODULES=(existing)\n"
        )
        self.assertIn(("mkinitcpio", "-P"), self.native.calls)
        self.assertFalse(any(self.native.unit(u)["enabled"] for u in UNIT_NAMES))
        self.assertIn(("systemctl", "restart", "nix-daemon.service"), self.native.calls)
        self.assertFalse((self.root / "var/lib/nix-config/arch").exists())

    def test_purge_uninstalls_in_order_and_keeps_ufw(self):
        self.manifest["units"].append(unit("ufw.service"))
        self.deploy()
        self.native.calls.clear()
        self.core().purge()
        calls = self.native.calls
        order = [
            calls.index(("systemctl", "disable", "--now", "libvirtd.socket")),
            calls.index(("mkinitcpio", "-P")),
            calls.index(("systemctl", "disable", "--now", "NetworkManager.service")),
        ]
        self.assertEqual(order, sorted(order))
        self.assertTrue(self.native.unit("ufw.service")["enabled"])
        self.assertNotIn("i2c", self.native.groups)
        self.assertEqual(self.native.capabilities, {})
        self.assertEqual(self.native.sysctl["net.ipv4.ip_forward"], "0")
        self.assertFalse((self.root / "sys/module/br_netfilter").exists())
        self.assertFalse((self.root / STATE).exists())

    def test_interrupted_purge_still_rebuilds_the_boot_images(self):
        self.deploy()
        self.native.fail = ("mkinitcpio",)
        with self.assertRaises(Conflict):
            self.core().purge()
        self.native.fail = None
        self.native.calls.clear()
        self.core().purge()
        self.assertIn(("mkinitcpio", "-P"), self.native.calls)

    def test_purge_stops_on_runtime_drift_before_any_change(self):
        self.deploy()
        self.native.sysctl["net.ipv4.ip_forward"] = "7"
        nix = (self.root / "etc/nix/nix.conf").read_text()
        self.native.calls.clear()
        with self.assertRaisesRegex(
            Conflict, "nacre forget sysctl:net.ipv4.ip_forward"
        ):
            self.core().purge()
        self.assertEqual((self.root / "etc/nix/nix.conf").read_text(), nix)
        self.assertFalse(
            any(
                call[1] == "disable"
                for call in self.native.calls
                if call[0] == "systemctl"
            )
        )

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


STATE = "var/lib/nix-config/arch"
OLD_BLOCK = (
    "# BEGIN nix-config settings\ntrusted-users = root\n# END nix-config settings\n"
)


class EtcHarness(Harness):
    """Helpers for environment.etc cases."""

    def setUp(self):
        super().setUp()
        self.manifest["etc"] = []

    def path(self, name):
        return self.root / "etc" / name

    def receipt(self):
        return json.loads((self.root / STATE / "receipts/core.json").read_text())

    def original(self, name):
        digest = hashlib.sha256(f"/etc/{name}".encode()).hexdigest()
        return self.root / STATE / "adopted" / f"{digest}.json"

    def existing(self, name, text):
        self.path(name).parent.mkdir(parents=True, exist_ok=True)
        self.path(name).write_text(text)


class EtcTests(EtcHarness):
    """environment.etc entries: receipts, adoption, withdrawal and recovery."""

    def test_entry_gets_its_mode_group_and_record(self):
        gid = os.getgid()
        (self.root / "etc/group").write_text(f"root:x:{gid + 1}:\ndemo:x:{gid}:\n")
        self.manifest["etc"] = [entry("foo/bar.conf", "x\n", mode="0640", group="demo")]
        self.manifest["blocks"] = []
        self.deploy()
        info = self.path("foo/bar.conf").stat()
        self.assertEqual(self.path("foo/bar.conf").read_text(), "x\n")
        self.assertEqual((info.st_mode & 0o777, info.st_gid), (0o640, gid))
        record = self.receipt()["records"]["file:foo/bar.conf"]
        self.assertEqual(record["sha256"], hashlib.sha256(b"x\n").hexdigest())
        self.assertEqual(
            (record["mode"], record["uid"], record["gid"]), ("0640", os.getuid(), gid)
        )
        self.assertEqual(self.deploy().updates, 0)

    def test_differing_unmanaged_file_needs_adopt(self):
        self.existing("hosts", "operator\n")
        self.manifest["etc"] = [entry("hosts", "nacre\n", adopt=False)]
        with self.assertRaisesRegex(Conflict, "/etc/hosts .*adopt"):
            self.core().preflight()
        self.assertEqual(self.path("hosts").read_text(), "operator\n")

    def test_adoption_saves_the_original_and_withdrawal_restores_it(self):
        self.existing("hosts", "operator\n")
        self.path("hosts").chmod(0o600)
        self.manifest["etc"] = [entry("hosts", "nacre\n", adopt=True)]
        self.deploy()
        self.assertEqual(self.path("hosts").read_text(), "nacre\n")
        self.assertIn("operator", self.original("hosts").read_text())
        self.assertEqual(self.original("hosts").stat().st_mode & 0o777, 0o600)
        self.manifest["etc"] = []
        self.native.calls.clear()
        self.deploy()
        self.assertEqual(self.path("hosts").read_text(), "operator\n")
        self.assertEqual(self.path("hosts").stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.original("hosts").exists())
        self.assertNotIn("file:hosts", self.receipt()["records"])

    def test_identical_file_is_adopted_without_adopt_and_kept_on_withdrawal(self):
        self.existing("hosts", "same\n")
        self.manifest["etc"] = [entry("hosts", "same\n", adopt=False)]
        self.deploy()
        self.manifest["etc"] = []
        self.deploy()
        self.assertEqual(self.path("hosts").read_text(), "same\n")

    def test_created_file_is_removed_on_withdrawal(self):
        self.manifest["etc"] = [entry("new.conf", "x\n")]
        self.deploy()
        self.manifest["etc"] = []
        self.deploy()
        self.assertFalse(self.path("new.conf").exists())
        self.assertEqual(self.receipt()["records"], {})

    def test_package_file_created_after_preflight_is_adopted(self):
        self.manifest["etc"] = [entry("pwrstatd.conf", "nacre\n", adopt=False)]
        core = self.core()
        core.preflight()
        self.existing("pwrstatd.conf", "package default\n")
        self.native.owners["/etc/pwrstatd.conf"] = ("powerpanel", "1.4")
        core.repositories()
        core.converge()
        self.assertEqual(self.path("pwrstatd.conf").read_text(), "nacre\n")
        self.assertIn("package default", self.original("pwrstatd.conf").read_text())

    def test_other_file_created_after_preflight_is_runtime_drift(self):
        self.manifest["etc"] = [entry("hosts", "nacre\n", adopt=False)]
        core = self.core()
        core.preflight()
        self.existing("hosts", "operator\n")
        with self.assertRaisesRegex(Conflict, "/etc/hosts changed after preflight"):
            core.converge()
        self.assertEqual(self.path("hosts").read_text(), "operator\n")

    def test_drifted_withdrawn_file_stops_preflight_and_names_forget(self):
        self.manifest["etc"] = [entry("new.conf", "x\n")]
        self.deploy()
        self.path("new.conf").write_text("edited\n")
        self.manifest["etc"] = []
        with self.assertRaisesRegex(Conflict, "nacre forget file:new.conf"):
            self.core().preflight()
        self.assertEqual(self.path("new.conf").read_text(), "edited\n")

    def test_missing_withdrawn_file_drops_its_record(self):
        self.manifest["etc"] = [entry("new.conf", "x\n")]
        self.deploy()
        self.path("new.conf").unlink()
        self.manifest["etc"] = []
        self.deploy()
        self.assertEqual(self.receipt()["records"], {})

    def test_restore_warns_when_the_package_changed_since_adoption(self):
        self.existing("pwrstatd.conf", "package default\n")
        self.native.owners["/etc/pwrstatd.conf"] = ("powerpanel", "1.4")
        self.manifest["etc"] = [entry("pwrstatd.conf", "nacre\n")]
        self.deploy()
        self.native.owners["/etc/pwrstatd.conf"] = ("powerpanel", "1.5")
        self.manifest["etc"] = []
        self.deploy()
        self.assertEqual(self.path("pwrstatd.conf").read_text(), "package default\n")
        self.assertIn("predates powerpanel 1.5", self.output.getvalue())

    def test_edited_declared_file_is_overwritten_and_planned_as_drift(self):
        self.manifest["etc"] = [entry("new.conf", "x\n")]
        self.deploy()
        self.path("new.conf").write_text("edited\n")
        self.assertIn("~ /etc/new.conf (drifted, overwrite)", self.plan())
        self.deploy()
        self.assertEqual(self.path("new.conf").read_text(), "x\n")

    def test_plan_names_adoptions_restores_and_removals_without_content(self):
        self.existing("hosts", "operator\n")
        self.manifest["etc"] = [entry("hosts", "nacre\n"), entry("new.conf", "x\n")]
        self.assertIn("~ /etc/hosts (adopt, save original)", self.plan())
        self.deploy()
        self.manifest["etc"] = []
        lines = self.plan()
        self.assertTrue(
            any(
                line.startswith("~ /etc/hosts (restore original from ")
                for line in lines
            ),
            lines,
        )
        self.assertIn("~ /etc/new.conf (withdrawn, remove)", lines)
        self.assertFalse(any("operator" in line or "nacre" in line for line in lines))

    def test_interrupted_write_keeps_the_pre_nacre_original(self):
        self.deploy()
        self.existing("hosts", "operator\n")
        self.manifest["etc"] = [entry("hosts", "nacre\n")]
        save = runtime.Core.save_receipt
        calls = []

        def fail_once(core):
            calls.append(1)
            if len(calls) == 1:
                raise OSError("injected receipt failure")
            save(core)

        with (
            patch.object(runtime.Core, "save_receipt", fail_once),
            self.assertRaises(OSError),
        ):
            self.deploy()
        self.assertEqual(self.path("hosts").read_text(), "nacre\n")
        self.deploy()
        self.assertIn("operator", self.original("hosts").read_text())
        self.manifest["etc"] = []
        self.deploy()
        self.assertEqual(self.path("hosts").read_text(), "operator\n")

    def test_lost_receipt_records_namespaced_files_as_nacre_created(self):
        self.manifest["etc"] = [entry("sysctl.d/99-nix-config.conf", "a = 1\n")]
        self.deploy()
        (self.root / STATE / "receipts/core.json").unlink()
        self.deploy()
        self.assertFalse(self.original("sysctl.d/99-nix-config.conf").exists())
        self.manifest["etc"] = []
        self.deploy()
        self.assertFalse(self.path("sysctl.d/99-nix-config.conf").exists())

    def test_lost_receipt_records_an_identical_file_as_nacre_created(self):
        name = "systemd/system/getty@tty1.service.d/overrides.conf"
        self.manifest["etc"] = [
            entry(name, "[Service]\n", unit="getty@tty1.service", dropin=True)
        ]
        self.deploy()
        (self.root / STATE / "receipts/core.json").unlink()
        self.deploy()
        self.manifest["etc"] = []
        self.deploy()
        self.assertFalse(self.path(name).exists())

    def test_lost_receipt_plan_names_identical_text_as_nacre_created(self):
        self.deploy()
        (self.root / STATE / "receipts/core.json").unlink()
        self.existing("hosts", "nacre\n")
        self.path("hosts").chmod(0o600)
        self.existing("motd", "operator\n")
        self.manifest["etc"] = [entry("hosts", "nacre\n"), entry("motd", "nacre\n")]
        lines = self.plan()
        self.assertIn("~ /etc/hosts (adopt as Nacre's)", lines)
        self.assertIn("~ /etc/motd (adopt, save original)", lines)

    def test_host_of_an_older_version_stops_preflight(self):
        (self.root / "etc/nix/nix.conf").write_text(OLD_BLOCK)
        with self.assertRaisesRegex(Conflict, "older Nacre.*nacre purge"):
            self.core().preflight()

    def test_block_with_the_receipt_line_is_a_lost_receipt_not_an_old_host(self):
        self.deploy()
        self.assertIn(
            runtime.RECEIPT_LINE, (self.root / "etc/nix/nix.conf").read_text()
        )
        (self.root / STATE / "receipts/core.json").unlink()
        self.core().preflight()

    def test_purge_restores_originals_and_removes_created_files(self):
        self.existing("hosts", "operator\n")
        self.manifest["etc"] = [entry("hosts", "nacre\n"), entry("new.conf", "x\n")]
        self.deploy()
        self.core().purge()
        self.assertEqual(self.path("hosts").read_text(), "operator\n")
        self.assertFalse(self.path("new.conf").exists())
        self.assertFalse((self.root / STATE).exists())

    def systemctl(self, *verbs):
        return [
            call
            for call in self.native.calls
            if call[:1] == ("systemctl",) and call[1] in verbs
        ]

    def test_authored_unit_is_written_reloaded_enabled_and_started(self):
        self.manifest["etc"] = [
            entry("systemd/system/demo.service", "[Service]\n", unit="demo.service")
        ]
        self.manifest["units"] = [unit("demo.service")]
        self.deploy()
        self.assertTrue(self.path("systemd/system/demo.service").is_file())
        self.assertEqual(
            self.native.unit("demo.service"), {"enabled": True, "active": True}
        )
        self.assertEqual(
            self.systemctl("daemon-reload"), [("systemctl", "daemon-reload")]
        )
        first = self.native.calls.index(("systemctl", "daemon-reload"))
        self.assertLess(
            first, self.native.calls.index(("systemctl", "enable", "demo.service"))
        )

    def test_changed_authored_unit_restarts_unless_restart_if_changed_is_off(self):
        name = "systemd/system/demo.service"
        self.manifest["units"] = [unit("demo.service")]
        for restart, expected in ((True, 1), (False, 0)):
            with self.subTest(restart=restart):
                self.manifest["etc"] = [
                    entry(
                        name,
                        f"[Service]\n# {restart}\n",
                        unit="demo.service",
                        restartIfChanged=restart,
                    )
                ]
                self.deploy()
                self.manifest["etc"][0]["text"] += "# changed\n"
                self.native.calls.clear()
                self.deploy()
                self.assertEqual(len(self.systemctl("daemon-reload")), 1)
                self.assertEqual(
                    len(self.systemctl("restart"))
                    - len(
                        [c for c in self.systemctl("restart") if "nix-daemon" in c[2]]
                    ),
                    expected,
                )

    def socket(self, name="demo.socket", accept=False, text="[Socket]\n"):
        """A running authored socket whose service runs; returns the service."""
        service = "demo@1.service" if accept else "demo.service"
        self.manifest["units"] = [unit(name)]
        self.manifest["etc"] = [entry(f"systemd/system/{name}", text, unit=name)]
        self.deploy()
        if accept:
            self.native.accepting.add(name)
        self.native.triggers[name] = [service]
        self.native.unit(service)["active"] = True
        return service

    def test_changed_socket_restarts_with_its_running_service(self):
        service = self.socket()
        self.manifest["etc"][0]["text"] += "# changed\n"
        self.deploy()
        self.assertTrue(self.native.unit("demo.socket")["active"])
        self.assertTrue(self.native.unit(service)["active"])
        self.assertFalse(self.marker("restart-demo.socket").exists())

    def test_changed_accepting_socket_restarts_and_keeps_its_connections(self):
        instance = self.socket(accept=True)
        self.manifest["etc"][0]["text"] += "# changed\n"
        self.deploy()
        self.assertEqual(self.native.restarts["demo.socket"], 1)
        self.assertTrue(self.native.unit(instance)["active"])

    def test_interrupted_socket_restart_starts_the_saved_service(self):
        service = self.socket()
        self.native.unit("demo.socket")["active"] = False
        self.native.unit(service)["active"] = False
        self.marker("restart-demo.socket").write_text(f'["{service}"]\n')
        self.deploy()
        self.assertTrue(self.native.unit("demo.socket")["active"])
        self.assertTrue(self.native.unit(service)["active"])
        self.assertEqual(self.native.restarts["demo.socket"], 0)
        self.assertFalse(self.marker("restart-demo.socket").exists())

    def test_plan_names_the_service_that_a_socket_restart_stops(self):
        self.socket()
        self.marker("restart-demo.socket").write_text("")
        self.assertIn("~ restart demo.socket and its service (pending)", self.plan())
        self.native.unit("demo.service")["active"] = False
        self.assertIn("~ restart demo.socket (pending)", self.plan())

    def test_changed_timer_and_path_restart_like_services(self):
        names = ("demo.timer", "demo.path")
        self.manifest["units"] = [unit(name) for name in names]
        self.manifest["etc"] = [
            entry(f"systemd/system/{name}", "[Unit]\n", unit=name) for name in names
        ]
        self.deploy()
        for item in self.manifest["etc"]:
            item["text"] += "# changed\n"
        self.deploy()
        for name in names:
            self.assertEqual(self.native.restarts[name], 1, name)

    def test_withdrawn_authored_unit_stops_before_its_file_goes(self):
        name = "systemd/system/demo.service"
        self.manifest["etc"] = [entry(name, "[Service]\n", unit="demo.service")]
        self.manifest["units"] = [unit("demo.service")]
        self.deploy()
        self.manifest["etc"] = []
        self.manifest["units"] = []
        self.native.calls.clear()
        self.deploy()
        self.assertEqual(
            self.native.unit("demo.service"), {"enabled": False, "active": False}
        )
        self.assertFalse(self.path(name).exists())
        self.assertLess(
            self.native.calls.index(("systemctl", "disable", "--now", "demo.service")),
            self.native.calls.index(("systemctl", "daemon-reload")),
        )

    def test_drop_in_only_writes_reloads_and_withdraws_its_file(self):
        name = "systemd/system/getty@tty1.service.d/overrides.conf"
        dropin = entry(name, "[Service]\n", unit="getty@tty1.service", dropin=True)
        self.manifest["etc"] = [dropin]
        self.deploy()
        dropin["text"] += "# changed\n"
        self.deploy()
        self.manifest["etc"] = []
        self.deploy()
        self.assertFalse(self.path(name).exists())
        self.assertEqual(len(self.systemctl("daemon-reload")), 3)
        self.assertFalse(
            any(
                "getty@tty1.service" in call
                for call in self.native.calls
                if call[1] != "daemon-reload"
            )
        )
        self.assertEqual(list((self.root / STATE).glob("*.pending")), [])

    def test_plan_of_a_new_authored_unit_starts_it_without_a_conflict(self):
        self.manifest["etc"] = [
            entry("systemd/system/demo.service", "[Service]\n", unit="demo.service")
        ]
        self.manifest["units"] = [unit("demo.service")]
        self.native.unknown.add("demo.service")
        lines = self.plan()
        self.assertIn("+ /etc/systemd/system/demo.service", lines)
        self.assertIn("+ enable and start demo.service", lines)
        self.assertFalse(any(line.startswith("!") for line in lines), lines)

    def test_withdrawn_packaged_unit_keeps_running(self):
        self.manifest["units"] = [unit("NetworkManager.service")]
        self.deploy()
        self.manifest["units"] = []
        self.native.calls.clear()
        self.deploy()
        self.assertEqual(
            self.native.unit("NetworkManager.service"),
            {"enabled": True, "active": True},
        )
        self.assertEqual(self.systemctl("disable", "stop"), [])

    def runtime_state(self):
        return self.receipt()["state"]

    def bare(self):
        """A manifest without runtime state, so a test declares only its own."""
        self.manifest.update(
            groups=[], fileCapabilities=[], sysctl={}, kernelModules=[]
        )
        self.manifest["repository"] = None

    def test_withdrawn_repository_drops_its_include_then_its_file(self):
        self.manifest = copy.deepcopy(MANIFEST)
        self.deploy()
        self.manifest["repository"] = None
        self.deploy()
        self.assertNotIn(INCLUDE, (self.root / "etc/pacman.conf").read_text())
        self.assertFalse(
            (self.root / "etc/pacman.d/nix-config-lizardbyte.conf").exists()
        )
        self.assertNotIn("repository:lizardbyte", self.runtime_state())

    def test_runtime_changes_are_recorded_before_they_happen(self):
        self.bare()
        self.manifest.update(groups=["i2c"], sysctl={"net.ipv4.ip_forward": "1"})
        for command in (("gpasswd",), ("sysctl", "-w")):
            with self.subTest(command):
                self.native.fail = command
                with self.assertRaises(Conflict):
                    self.deploy()
        self.native.fail = None
        self.assertEqual(
            set(self.runtime_state()), {"group:i2c", "sysctl:net.ipv4.ip_forward"}
        )
        self.bare()
        self.deploy()  # The value never changed: no false drift, nothing to revert.
        self.assertEqual(self.runtime_state(), {})

    def test_reset_or_missing_sysctl_key_is_not_drift(self):
        self.bare()
        self.manifest["sysctl"] = {"net.ipv4.ip_forward": "1"}
        self.deploy()
        self.existing("sysctl.d/10-boot.conf", "net.ipv4.ip_forward = 2\n")
        self.native.sysctl["net.ipv4.ip_forward"] = "2"  # A reboot applied the files.
        self.bare()
        self.deploy()
        self.assertEqual(self.runtime_state(), {})

    def test_withdrawn_group_that_nacre_added_goes_and_wheel_stays(self):
        self.bare()
        self.native.groups |= {"audio"}
        self.manifest["groups"] = ["wheel", "i2c", "audio"]
        self.deploy()
        self.assertEqual(set(self.runtime_state()), {"group:i2c"})
        self.manifest["groups"] = []
        self.deploy()
        self.assertEqual(self.native.groups, {"wheel", "audio"})
        self.assertEqual(self.runtime_state(), {})

    def test_withdrawn_capability_is_cleared_or_dropped_with_a_new_binary(self):
        self.bare()
        self.manifest["fileCapabilities"] = MANIFEST["fileCapabilities"]
        self.deploy()
        self.manifest["fileCapabilities"] = []
        self.deploy()
        self.assertEqual(self.native.capabilities, {})
        self.manifest["fileCapabilities"] = MANIFEST["fileCapabilities"]
        self.deploy()
        self.native.capabilities.clear()  # A package upgrade replaced the binary.
        self.manifest["fileCapabilities"] = []
        self.native.calls.clear()
        self.deploy()
        self.assertFalse(
            any(call[:2] == ("setcap", "-r") for call in self.native.calls)
        )
        self.assertEqual(self.runtime_state(), {})

    def test_changed_capability_stops_and_names_forget(self):
        self.bare()
        self.manifest["fileCapabilities"] = MANIFEST["fileCapabilities"]
        self.deploy()
        self.native.capabilities["/usr/bin/sunshine"] = "cap_net_admin=p"
        self.manifest["fileCapabilities"] = []
        with self.assertRaisesRegex(
            Conflict, "nacre forget capability:/usr/bin/sunshine"
        ):
            self.core().preflight()

    def test_withdrawn_sysctl_key_takes_the_remaining_files_or_its_old_value(self):
        self.bare()
        self.manifest["sysctl"] = {"net.ipv4.ip_forward": "1", "vm.swappiness": "10"}
        self.native.sysctl.update({"net.ipv4.ip_forward": "0", "vm.swappiness": "60"})
        self.deploy()
        self.existing("sysctl.d/10-operator.conf", "vm.swappiness = 30\n")
        self.manifest["sysctl"] = {}
        self.deploy()
        self.assertEqual(self.native.sysctl["net.ipv4.ip_forward"], "0")
        self.assertEqual(self.native.sysctl["vm.swappiness"], "30")
        self.assertEqual(self.runtime_state(), {})

    def test_changed_sysctl_value_stops_and_names_forget(self):
        self.bare()
        self.manifest["sysctl"] = {"net.ipv4.ip_forward": "1"}
        self.deploy()
        self.native.sysctl["net.ipv4.ip_forward"] = "5"
        self.manifest["sysctl"] = {}
        with self.assertRaisesRegex(
            Conflict, "nacre forget sysctl:net.ipv4.ip_forward"
        ):
            self.core().preflight()

    def test_withdrawn_module_unloads_unless_in_use(self):
        self.bare()
        self.manifest["kernelModules"] = ["br_netfilter", "veth"]
        self.deploy()
        (self.root / "sys/module/veth/refcnt").write_text("2\n")
        self.manifest["kernelModules"] = []
        self.deploy()
        self.assertFalse((self.root / "sys/module/br_netfilter").exists())
        self.assertTrue((self.root / "sys/module/veth").exists())
        self.assertIn("veth stays loaded until reboot", self.output.getvalue())
        self.assertEqual(set(self.runtime_state()), {"module:veth"})
        (self.root / "sys/module/veth/refcnt").unlink()
        (self.root / "sys/module/veth").rmdir()  # The host rebooted.
        self.deploy()
        self.assertEqual(self.runtime_state(), {})

    def test_plan_names_runtime_withdrawals(self):
        self.manifest = copy.deepcopy(MANIFEST)
        self.manifest["etc"] = []
        self.deploy()
        self.bare()
        lines = self.plan()
        for expected in (
            "~ remove tester from group i2c",
            "~ clear cap_sys_admin=p on /usr/bin/sunshine",
            "~ sysctl net.ipv4.ip_forward: 1 -> 0",
            "~ unload kernel module br_netfilter",
            "~ remove repository lizardbyte",
        ):
            self.assertIn(expected, lines)

    def extension(self, manifest="/nix/store/b-arch-babu.json", purge=True):
        return {
            "name": "babu",
            "adapter": "/nix/store/a-babu/adapter.py",
            "manifest": manifest,
            "python": "/nix/store/c-python/bin/python3",
            "purge": purge,
        }

    def root_link(self, kind):
        link = self.root / f"nix/var/nix/gcroots/nacre/babu-{kind}"
        return os.readlink(link) if link.is_symlink() else None

    def test_extension_is_recorded_with_roots_that_follow_the_generation(self):
        self.manifest["extensions"] = [self.extension()]
        self.deploy()
        self.assertEqual(self.root_link("manifest"), "/nix/store/b-arch-babu.json")
        self.assertEqual(self.root_link("adapter"), "/nix/store/a-babu/adapter.py")
        self.assertEqual(self.root_link("python"), "/nix/store/c-python/bin/python3")
        self.manifest["extensions"] = [self.extension("/nix/store/d-arch-babu.json")]
        self.deploy()
        self.assertEqual(self.root_link("manifest"), "/nix/store/d-arch-babu.json")

    def test_withdrawn_extension_runs_its_recorded_purge_then_goes(self):
        for purge in (True, False):
            with self.subTest(purge=purge):
                self.manifest["extensions"] = [self.extension(purge=purge)]
                self.deploy()
                self.manifest["extensions"] = []
                self.native.calls.clear()
                self.deploy()
                hook = (
                    "env",
                    "/nix/store/c-python/bin/python3",
                    "/nix/store/a-babu/adapter.py",
                    "/nix/store/b-arch-babu.json",
                    "purge",
                )
                self.assertEqual(hook in self.native.calls, purge)
                self.assertIsNone(self.root_link("manifest"))
                self.assertNotIn("extension:babu", self.runtime_state())

    def test_failed_extension_purge_keeps_its_record_and_names_forget(self):
        self.manifest["extensions"] = [self.extension()]
        self.deploy()
        self.manifest["extensions"] = []
        self.native.fail_extension = True
        with self.assertRaisesRegex(Conflict, "nacre forget extension:babu"):
            self.deploy()
        self.assertIn("extension:babu", self.runtime_state())
        self.manifest["forget"] = "extension:babu"
        self.core().forget()
        self.assertIsNone(self.root_link("adapter"))
        self.assertNotIn("extension:babu", self.runtime_state())

    def test_purge_removes_extension_roots(self):
        self.manifest["extensions"] = [self.extension(purge=False)]
        self.deploy()
        self.core().purge()
        self.assertIsNone(self.root_link("python"))

    def test_plan_reverts_a_key_that_nacre_s_own_sysctl_file_still_sets(self):
        self.bare()
        self.manifest["sysctl"] = {"net.ipv4.ip_forward": "1"}
        self.manifest["etc"] = [
            entry("sysctl.d/99-nix-config.conf", "net.ipv4.ip_forward = 1\n")
        ]
        self.deploy()
        self.manifest["sysctl"] = {}
        self.manifest["etc"] = [entry("sysctl.d/99-nix-config.conf", "")]
        self.assertIn("~ sysctl net.ipv4.ip_forward: 1 -> 0", self.plan())

    def test_plan_names_the_hook_of_a_removed_extension(self):
        self.manifest["extensions"] = [self.extension()]
        self.deploy()
        self.manifest["extensions"] = []
        self.assertIn("~ run the purge phase of removed extension babu", self.plan())

    def test_forget_drops_only_the_record_and_its_original(self):
        self.existing("hosts", "operator\n")
        self.manifest["etc"] = [entry("hosts", "nacre\n")]
        self.deploy()
        self.path("hosts").write_text("edited\n")
        self.manifest["etc"] = []
        self.manifest["forget"] = "file:hosts"
        self.core().forget()
        self.assertEqual(self.path("hosts").read_text(), "edited\n")
        self.assertEqual(self.receipt()["records"], {})
        self.assertFalse(self.original("hosts").exists())
        del self.manifest["forget"]
        self.deploy()
        self.assertEqual(self.path("hosts").read_text(), "edited\n")

    def test_forget_of_an_unknown_record_fails_without_change(self):
        self.manifest["etc"] = [entry("new.conf", "x\n")]
        self.deploy()
        before = self.receipt()
        for record in ("file:other.conf", "group:wheel", "new.conf"):
            with self.subTest(record):
                self.manifest["forget"] = record
                with self.assertRaises(Conflict):
                    self.core().forget()
                self.assertEqual(self.receipt(), before)

    def test_purge_stops_on_drift_before_any_change(self):
        self.manifest["etc"] = [entry("new.conf", "x\n")]
        self.deploy()
        self.path("new.conf").write_text("edited\n")
        nix = (self.root / "etc/nix/nix.conf").read_text()
        with self.assertRaisesRegex(Conflict, "nacre forget file:new.conf"):
            self.core().purge()
        self.assertEqual((self.root / "etc/nix/nix.conf").read_text(), nix)
        self.assertTrue((self.root / STATE / "receipts/core.json").exists())


BLOB = b"\x00binary\xff\xfe\n"


class BinaryAndLinkTests(EtcHarness):
    """source entries copy bytes; target entries are symlinks that Nacre never follows."""

    def setUp(self):
        super().setUp()
        self.store = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.store / "blob").write_bytes(BLOB)

    def blob(self, name="blob.bin", **options):
        return entry(name, None, source=str(self.store / "blob"), **options)

    def link(self, name, target, **options):
        return entry(name, None, target=target, **options)

    def test_binary_source_is_copied_byte_identical_and_repeat_is_quiet(self):
        self.manifest["etc"] = [self.blob(mode="0600")]
        self.deploy()
        self.assertEqual(self.path("blob.bin").read_bytes(), BLOB)
        self.assertEqual(self.path("blob.bin").stat().st_mode & 0o777, 0o600)
        before = self.snapshot()
        self.assertIn("= /etc/blob.bin", self.plan())
        self.deploy()
        self.assertEqual(self.snapshot(), before)

    def test_adopted_binary_original_is_restored_byte_identical(self):
        self.path("blob.bin").write_bytes(b"\x00old\xff")
        self.path("blob.bin").chmod(0o600)
        self.manifest["etc"] = [self.blob()]
        self.deploy()
        self.assertEqual(self.path("blob.bin").read_bytes(), BLOB)
        self.manifest["etc"] = []
        self.deploy()
        self.assertEqual(self.path("blob.bin").read_bytes(), b"\x00old\xff")
        self.assertEqual(self.path("blob.bin").stat().st_mode & 0o777, 0o600)

    def test_target_entry_links_without_following_and_withdraws(self):
        (self.root / "srv").mkdir()
        self.manifest["etc"] = [
            self.link("dangling", "/missing/file"),
            self.link("directory", "/srv"),
        ]
        self.deploy()
        self.assertEqual(os.readlink(self.path("dangling")), "/missing/file")
        self.assertEqual(os.readlink(self.path("directory")), "/srv")
        self.assertIn("= /etc/dangling", self.plan())
        calls = len(self.native.calls)
        self.deploy()
        self.assertIn("Core converged: 0 files updated", self.output.getvalue())
        self.assertGreater(len(self.native.calls), calls)
        self.manifest["etc"] = []
        self.deploy()
        self.assertFalse(os.path.lexists(self.path("dangling")))
        self.assertFalse(os.path.lexists(self.path("directory")))
        self.assertTrue((self.root / "srv").is_dir())

    def test_changed_link_is_restored_and_a_changed_withdrawn_link_stops(self):
        self.manifest["etc"] = [self.link("zone", "/usr/share/zoneinfo/UTC")]
        self.deploy()
        self.path("zone").unlink()
        self.path("zone").symlink_to("/elsewhere")
        self.assertIn("~ /etc/zone (drifted, overwrite)", self.plan())
        self.deploy()
        self.assertEqual(os.readlink(self.path("zone")), "/usr/share/zoneinfo/UTC")
        # A file with the link's mode and bytes is still not that link.
        self.path("zone").unlink()
        self.path("zone").write_text("/usr/share/zoneinfo/UTC")
        self.path("zone").chmod(0o777)
        self.assertIn("~ /etc/zone (drifted, overwrite)", self.plan())
        self.deploy()
        self.path("zone").unlink()
        self.path("zone").symlink_to("/elsewhere")
        self.manifest["etc"] = []
        with self.assertRaisesRegex(Conflict, "nacre forget file:zone"):
            self.core().preflight()

    def test_existing_links_need_adopt_and_come_back(self):
        self.path("resolv.conf").symlink_to("../run/systemd/resolve/stub-resolv.conf")
        self.manifest["etc"] = [
            entry("resolv.conf", "nameserver 1.1.1.1\n", adopt=False)
        ]
        with self.assertRaisesRegex(Conflict, "set adopt = true"):
            self.core().preflight()
        self.manifest["etc"] = [
            self.link(
                "resolv.conf", "/run/systemd/resolve/stub-resolv.conf", adopt=False
            )
        ]
        with self.assertRaisesRegex(Conflict, "set adopt = true"):
            self.core().preflight()
        self.manifest["etc"] = [entry("resolv.conf", "nameserver 1.1.1.1\n")]
        self.existing("hosts", "operator\n")
        self.manifest["etc"].append(self.link("hosts", "/srv/hosts"))
        self.deploy()
        self.assertEqual(self.path("resolv.conf").read_text(), "nameserver 1.1.1.1\n")
        self.assertEqual(os.readlink(self.path("hosts")), "/srv/hosts")
        self.manifest["etc"] = []
        self.deploy()
        self.assertEqual(
            os.readlink(self.path("resolv.conf")),
            "../run/systemd/resolve/stub-resolv.conf",
        )
        self.assertFalse(self.path("hosts").is_symlink())
        self.assertEqual(self.path("hosts").read_text(), "operator\n")

    def test_lost_receipt_identical_source_and_link_are_nacre_s(self):
        self.manifest["etc"] = [
            self.blob(),
            self.link("zone", "/usr/share/zoneinfo/UTC"),
        ]
        self.deploy()
        (self.root / STATE / "receipts/core.json").unlink()
        lines = self.plan()
        self.assertIn("~ /etc/blob.bin (adopt as Nacre's)", lines)
        self.assertIn("~ /etc/zone (adopt as Nacre's)", lines)
        self.deploy()
        self.manifest["etc"] = []
        self.deploy()
        self.assertFalse(os.path.lexists(self.path("blob.bin")))
        self.assertFalse(os.path.lexists(self.path("zone")))

    def test_interrupted_link_write_is_recorded_on_the_next_run(self):
        self.manifest["etc"] = [self.link("zone", "/usr/share/zoneinfo/UTC")]
        self.deploy()
        receipt = self.receipt()
        record = receipt["records"].pop("file:zone")
        (self.root / STATE / "receipts/core.json").write_text(json.dumps(receipt))
        (self.root / runtime.INTENT.lstrip("/")).write_text(
            json.dumps({"op": "write", "key": "file:zone", "record": record})
        )
        self.core().preflight()
        self.deploy()
        self.assertEqual(self.receipt()["records"]["file:zone"], record)

    def test_paths_that_are_neither_file_nor_link_stop_preflight(self):
        self.path("dir.conf").mkdir()
        self.manifest["etc"] = [entry("dir.conf", "x\n")]
        with self.assertRaisesRegex(
            Conflict, "/etc/dir.conf is not a regular file or symlink"
        ):
            self.core().preflight()
        self.manifest["etc"] = [entry("fifo.conf", "x\n")]
        self.deploy()
        self.path("fifo.conf").unlink()
        os.mkfifo(self.path("fifo.conf"))
        self.manifest["etc"] = []
        with self.assertRaisesRegex(
            Conflict, "/etc/fifo.conf is not a regular file or symlink"
        ):
            self.core().preflight()

    def test_target_that_resolves_into_the_store_stops_preflight(self):
        (self.root / "nix/store/abc-x").mkdir(parents=True)
        (self.root / "usr/share").mkdir(parents=True)
        (self.root / "usr/share/profile").symlink_to(self.root / "nix/store/abc-x")
        self.manifest["etc"] = [self.link("profile", "/usr/share/profile")]
        with self.assertRaisesRegex(
            Conflict, "/etc/profile.*resolves into the Nix store"
        ):
            self.core().preflight()
        # A recorded entry is checked too.
        self.manifest["etc"] = [self.link("profile", "/srv")]
        self.deploy()
        self.manifest["etc"] = [self.link("profile", "/usr/share/profile")]
        with self.assertRaisesRegex(
            Conflict, "/etc/profile.*resolves into the Nix store"
        ):
            self.core().preflight()

    def test_saved_original_without_content_stops_withdrawal(self):
        self.existing("hosts", "operator\n")
        self.manifest["etc"] = [entry("hosts", "nacre\n")]
        self.deploy()
        saved = json.loads(self.original("hosts").read_text())
        del saved["text"]
        self.original("hosts").write_text(json.dumps(saved))
        self.manifest["etc"] = []
        with self.assertRaisesRegex(
            Conflict, "saved original of /etc/hosts is invalid"
        ):
            self.deploy()
        self.assertEqual(self.path("hosts").read_text(), "nacre\n")


class ServiceAccountTests(EtcHarness):
    """System accounts and groups through systemd-sysusers; withdrawal keeps them."""

    def setUp(self):
        super().setUp()
        gid = os.getgid()
        (self.root / "etc/passwd").write_text("root:x:0:0::/root:/bin/bash\n")
        (self.root / "etc/group").write_text(f"root:x:{gid}:\n")
        self.declare()

    def declare(self, *names):
        names = names or ("svc",)
        self.manifest["systemGroups"] = list(names)
        self.manifest["systemUsers"] = [
            {"name": name, "group": name, "description": "Demo", "home": "/"}
            for name in names
        ]

    def has(self, database, name):
        lines = (self.root / "etc" / database).read_text().splitlines()
        return any(line.split(":")[0] == name for line in lines)

    def entry_of(self, database, name):
        for line in (self.root / "etc" / database).read_text().splitlines():
            if line.split(":")[0] == name:
                return line.split(":")
        self.fail(f"{name} is not in /etc/{database}")

    def records(self):
        return {
            key: value
            for key, value in self.receipt()["state"].items()
            if value["kind"] in ("account", "system-group")
        }

    def test_declared_accounts_are_created_with_sysusers_only_from_nacre_s_file(self):
        self.deploy()
        user, group = self.entry_of("passwd", "svc"), self.entry_of("group", "svc")
        self.assertLess(int(user[2]), 1000)
        self.assertEqual(user[3], group[2])
        self.assertEqual(self.native.sysusers, [["/etc/sysusers.d/60-nix-config.conf"]])
        self.assertEqual(
            self.records(),
            {
                "account:svc": {
                    "kind": "account",
                    "name": "svc",
                    "created": True,
                    "id": int(user[2]),
                },
                "system-group:svc": {
                    "kind": "system-group",
                    "name": "svc",
                    "created": True,
                    "id": int(group[2]),
                },
            },
        )
        self.deploy()
        self.assertEqual(len(self.native.sysusers), 1)

    def test_plan_lists_creations_adoptions_and_kept_withdrawals(self):
        lines = self.plan()
        self.assertIn("+ system group svc", lines)
        self.assertIn("+ system account svc", lines)
        self.deploy()
        self.assertFalse([line for line in self.plan() if "system " in line])
        self.declare("svc", "old")
        (self.root / "etc/group").write_text(
            self.path("group").read_text() + "old:x:500:\n"
        )
        (self.root / "etc/passwd").write_text(
            self.path("passwd").read_text() + "old:x:500:500::/:/usr/bin/nologin\n"
        )
        lines = self.plan()
        self.assertIn("~ adopt system account old", lines)
        self.assertIn("~ adopt system group old", lines)
        self.manifest["systemUsers"] = []
        self.manifest["systemGroups"] = []
        self.deploy()
        self.manifest["systemUsers"] = []
        lines = self.plan()
        self.assertFalse([line for line in lines if "system " in line])
        self.declare()
        self.deploy()
        self.manifest["systemUsers"] = []
        self.manifest["systemGroups"] = []
        lines = self.plan()
        self.assertIn("~ stop managing system account svc (kept)", lines)
        self.assertIn("~ stop managing system group svc (kept)", lines)

    def test_machine_without_declarations_has_no_sysusers_file(self):
        self.manifest["systemUsers"] = []
        self.manifest["systemGroups"] = []
        self.deploy()
        self.assertFalse(self.path("sysusers.d/60-nix-config.conf").exists())
        self.assertEqual(self.native.sysusers, [])
        self.assertFalse([line for line in self.plan() if "sysusers" in line])

    def test_existing_accounts_are_adopted_or_refused(self):
        group = self.path("group").read_text()
        (self.root / "etc/group").write_text(group + "svc:x:500:\nnogroup:x:65534:\n")
        (self.root / "etc/passwd").write_text(
            "root:x:0:0::/root:/bin/bash\nsvc:x:500:500::/:/usr/bin/nologin\n"
            "nobody:x:65534:65534::/:/usr/bin/nologin\n"
        )
        self.manifest["systemGroups"] = ["svc", "nogroup"]
        self.manifest["systemUsers"] = [
            {"name": "svc", "group": "svc", "description": "", "home": "/"},
            {"name": "nobody", "group": "nogroup", "description": "", "home": "/"},
        ]
        self.deploy()
        self.assertFalse(self.records()["account:svc"]["created"])
        self.assertFalse(self.records()["account:nobody"]["created"])
        self.assertEqual(self.native.sysusers, [["/etc/sysusers.d/60-nix-config.conf"]])
        # A recorded account keeps its record when login.defs lowers the limit.
        (self.root / "etc/login.defs").write_text("SYS_UID_MAX 400\nSYS_GID_MAX 400\n")
        self.deploy()
        cases = {
            "human": (
                "human:x:1000:1000::/home/human:/bin/bash\n",
                "human:x:1000:\n",
                "human",
                "human",
            ),
            "wrong group": (
                "other:x:600:500::/:/usr/bin/nologin\n",
                "",
                "other",
                "nogroup",
            ),
        }
        for label, (passwd, groups, name, primary) in cases.items():
            with self.subTest(label):
                (self.root / "etc/passwd").write_text(
                    self.path("passwd").read_text() + passwd
                )
                (self.root / "etc/group").write_text(
                    self.path("group").read_text() + groups
                )
                self.manifest["systemGroups"] = sorted({primary, "nogroup"})
                self.manifest["systemUsers"] = [
                    {"name": name, "group": primary, "description": "", "home": "/"}
                ]
                with self.assertRaisesRegex(Conflict, f"system (account|group) {name}"):
                    self.core().preflight()

    def test_account_that_appears_after_preflight_stops_convergence(self):
        core = self.core()
        core.preflight()
        (self.root / "etc/passwd").write_text(
            self.path("passwd").read_text() + "svc:x:1500:1500::/:/bin/sh\n"
        )
        with self.assertRaisesRegex(Conflict, "system account svc"):
            core.converge()
        self.assertEqual(self.native.sysusers, [])

    def test_crash_before_the_ids_completes_the_records(self):
        self.deploy()
        receipt = self.receipt()
        receipt["state"]["account:svc"]["id"] = None
        (self.root / STATE / "receipts/core.json").write_text(json.dumps(receipt))
        self.deploy()
        self.assertEqual(
            self.records()["account:svc"]["id"], int(self.entry_of("passwd", "svc")[2])
        )
        self.assertTrue(self.records()["account:svc"]["created"])

    def test_name_that_sysusers_skips_stops_the_deployment(self):
        self.native.sysusers_skip.add("svc")
        with self.assertRaisesRegex(Conflict, "systemd-sysusers did not create svc"):
            self.deploy()

    def test_withdrawn_accounts_stay_and_purge_keeps_them(self):
        self.deploy()
        uid = self.entry_of("passwd", "svc")
        self.manifest["systemUsers"] = []
        self.manifest["systemGroups"] = []
        self.deploy()
        self.assertEqual(self.entry_of("passwd", "svc"), uid)
        self.assertTrue(self.has("group", "svc"))
        self.assertEqual(self.records(), {})
        self.assertFalse(self.path("sysusers.d/60-nix-config.conf").exists())
        self.declare()
        self.deploy()
        self.assertTrue(self.path("sysusers.d/60-nix-config.conf").exists())
        self.core().purge()
        self.assertFalse(self.path("sysusers.d/60-nix-config.conf").exists())
        self.assertEqual(self.entry_of("passwd", "svc"), uid)

    def test_forget_drops_only_the_account_record(self):
        self.deploy()
        self.manifest["forget"] = "account:svc"
        self.core().forget()
        self.assertNotIn("account:svc", self.records())
        self.assertIn("system-group:svc", self.records())
        self.assertTrue(self.has("passwd", "svc"))


if __name__ == "__main__":
    unittest.main()
