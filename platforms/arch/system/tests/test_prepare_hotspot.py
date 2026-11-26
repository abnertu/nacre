# pyright: standard
"""Run hotspot-prepare with a temporary root, a pty and fake nmcli and systemctl."""

import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import gi

gi.require_version("GLib", "2.0")
# gi.repository modules exist only at run time, after require_version.
GLib = importlib.import_module("gi.repository.GLib")

SOURCE = Path(sys.argv.pop()).resolve()
PYTHON = sys.argv.pop()

HOTSPOT = {
    "connection": "Demo AP",
    "ssid": "Demo-AP",
    "interface": "wlan0",
    "uplink": "eth0",
    "band": "a",
    "channel": 36,
    "address": "192.168.10.1/24",
    "autoconnect": True,
    "ipv6": "shared",
}
KEYFILE = "etc/NetworkManager/system-connections/Demo AP.nmconnection"

# nmcli and systemctl read and update state.json beside them.
FAKE_NMCLI = r"""
import json, re, sys
from pathlib import Path
here = Path(sys.argv[0]).parent
state = json.loads((here / "state.json").read_text())
args = sys.argv[1:]
with open(here / "calls.jsonl", "a") as calls:
    calls.write(json.dumps(args) + "\n")
def save():
    (here / "state.json").write_text(json.dumps(state))
if args[-2:] == ["connection", "show"]:
    for uid, name in state["connections"]:
        print(f"{uid}:{name}")
elif args[:2] == ["connection", "load"]:
    if state["load"] == "fail":
        sys.exit(1)
    text = (Path(state["root"]) / args[2].lstrip("/")).read_text()
    uid = re.search(r"^uuid=(.*)$", text, re.M).group(1)
    name = re.search(r"^id=(.*)$", text, re.M).group(1).replace("\\s", " ")
    state["connections"].append([uid, "Other" if state["load"] == "rename" else name])
    if state["load"] == "duplicate":
        state["connections"].append(["11111111-1111-1111-1111-111111111111", name])
    save()
elif args[:3] == ["connection", "show", "uuid"]:
    sys.exit(0 if any(uid == args[3] for uid, _ in state["connections"]) else 10)
elif args[:3] == ["connection", "delete", "uuid"]:
    state["connections"] = [c for c in state["connections"] if c[0] != args[3]]
    save()
else:
    sys.exit(2)
"""
FAKE_SYSTEMCTL = r"""
import json, sys
from pathlib import Path
state = json.loads((Path(sys.argv[0]).parent / "state.json").read_text())
sys.exit(0 if state["networkManager"] else 3)
"""


class PrepareHotspotTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / "root"
        (self.root / "etc/NetworkManager/system-connections").mkdir(parents=True)
        (self.root / "etc/NetworkManager/system-connections").chmod(0o700)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        for name, body in (("nmcli", FAKE_NMCLI), ("systemctl", FAKE_SYSTEMCTL)):
            path = self.bin / name
            path.write_text(f"#!{PYTHON}\n{body}")
            path.chmod(0o755)
        self.state = {
            "root": str(self.root),
            "connections": [],
            "load": "ok",
            "networkManager": True,
        }
        self.hotspot = dict(HOTSPOT)
        self.tty = None

    def prepare(self, *lines, hotspot=True):
        (self.bin / "state.json").write_text(json.dumps(self.state))
        master, slave = os.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        for line in lines:
            os.write(master, line.encode())
        config = {
            "hotspot": self.hotspot if hotspot else None,
            "root": str(self.root),
            "tty": self.tty or os.ttyname(slave),
            "requireRoot": False,
            "rootOwnership": False,
        }
        config_path = self.base / "config.json"
        config_path.write_text(json.dumps(config))
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}")
        result = subprocess.run(
            [PYTHON, "-I", str(SOURCE), "--config", str(config_path)],
            capture_output=True,
            text=True,
            env=env,
            stdin=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
        self.state = json.loads((self.bin / "state.json").read_text())
        return result

    def calls(self):
        path = self.bin / "calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    def entries(self):
        return sorted(
            path.name
            for path in (self.root / "etc/NetworkManager/system-connections").iterdir()
        )

    def keyfile(self):
        parsed = GLib.KeyFile()
        parsed.load_from_file(str(self.root / KEYFILE), GLib.KeyFileFlags.NONE)
        return parsed

    def test_creates_a_root_only_wpa_ap_and_loads_it(self):
        password = "correct horse"
        result = self.prepare(f"{password}\n", f"{password}\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.entries(), ["Demo AP.nmconnection"])
        self.assertEqual((self.root / KEYFILE).stat().st_mode & 0o777, 0o600)
        parsed = self.keyfile()
        expected = {
            ("connection", "id"): "Demo AP",
            ("connection", "interface-name"): "wlan0",
            ("connection", "autoconnect"): "false",
            ("wifi", "mode"): "ap",
            ("wifi", "ssid"): "Demo-AP",
            ("wifi", "band"): "a",
            ("wifi", "channel"): "36",
            ("wifi-security", "key-mgmt"): "wpa-psk",
            ("wifi-security", "proto"): "rsn;",
            ("wifi-security", "pairwise"): "ccmp;",
            ("wifi-security", "group"): "ccmp;",
            ("wifi-security", "psk"): password,
            ("ipv4", "method"): "shared",
            ("ipv4", "address1"): "192.168.10.1/24",
            ("ipv6", "method"): "shared",
        }
        for (group, key), value in expected.items():
            self.assertEqual(parsed.get_string(group, key), value, key)
        identifier = parsed.get_string("connection", "uuid")
        self.assertEqual(self.state["connections"], [[identifier, "Demo AP"]])
        self.assertIn(["connection", "load", f"/{KEYFILE}"], self.calls())
        self.assertFalse(any(password in " ".join(call) for call in self.calls()))
        self.assertNotIn(password, result.stdout + result.stderr)

    def test_password_rules_and_keyfile_escaping(self):
        accepted = ["12345678", "x" * 63, "0123456789abcdef" * 4, "  a\\b c\\s;#x"]
        for password in accepted:
            with self.subTest(password=password):
                (self.root / KEYFILE).unlink(missing_ok=True)
                self.state["connections"] = []
                result = self.prepare(f"{password}\n", f"{password}\n")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    self.keyfile().get_string("wifi-security", "psk"), password
                )
        (self.root / KEYFILE).unlink()
        refused = [
            ("1234567\n", "1234567\n"),
            ("g" * 64 + "\n", "g" * 64 + "\n"),
            ("pässwörd1\n", "pässwörd1\n"),
            ("12345678\n", "12345679\n"),
        ]
        for lines in refused:
            with self.subTest(lines=lines):
                self.state["connections"] = []
                result = self.prepare(*lines)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("nothing was written", result.stderr)
                self.assertEqual(self.entries(), [])

    def test_refusals_before_the_prompt_write_nothing(self):
        def existing_keyfile():
            (self.root / KEYFILE).write_text("other\n")

        cases = {
            "declares no networking.hotspot": lambda: None,
            "already exists; Nacre adopts": lambda: self.state["connections"].append(
                ["22222222-2222-2222-2222-222222222222", "Demo AP"]
            ),
            "remove it if NetworkManager lists no connection": existing_keyfile,
            "NetworkManager is not running": lambda: self.state.update(
                networkManager=False
            ),
            "needs a terminal": lambda: setattr(self, "tty", str(self.base / "plain")),
        }
        (self.base / "plain").write_text("")
        for message, arrange in cases.items():
            with self.subTest(message=message):
                for path in (
                    self.root / "etc/NetworkManager/system-connections"
                ).iterdir():
                    path.unlink()
                self.state.update(connections=[], networkManager=True)
                self.tty = None
                arrange()
                before = self.entries()
                result = self.prepare(
                    "12345678\n",
                    "12345678\n",
                    hotspot=message != "declares no networking.hotspot",
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(message, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(self.entries(), before)
        self.tty = None
        eof = self.prepare("\x04")
        self.assertEqual(eof.returncode, 1)
        self.assertIn("no password entered", eof.stderr)
        self.assertNotIn("Traceback", eof.stderr)
        self.assertEqual(self.entries(), [])

    def test_failed_load_removes_the_keyfile_and_its_profile(self):
        for mode in ("fail", "rename", "duplicate"):
            with self.subTest(mode=mode):
                self.state.update(connections=[], load=mode)
                result = self.prepare("12345678\n", "12345678\n")
                self.assertEqual(result.returncode, 1)
                self.assertIn("the keyfile was removed", result.stderr)
                self.assertEqual(self.entries(), [])
                left = [uid for uid, _ in self.state["connections"]]
                expected = (
                    ["11111111-1111-1111-1111-111111111111"]
                    if mode == "duplicate"
                    else []
                )
                if mode == "rename":
                    self.assertEqual(left, [])
                else:
                    self.assertEqual(left, expected)


if __name__ == "__main__":
    unittest.main()
