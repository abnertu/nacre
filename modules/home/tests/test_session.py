# pyright: standard
"""Assert systemd relationships on generated units, including repeated keys."""

import json
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from pathlib import Path

EXPECTED = json.loads(Path(sys.argv.pop()).read_text())
UNITS = Path(sys.argv.pop())


def unit(name):
    values = {}
    for line in (UNITS / (name + ".service")).read_text().splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values.setdefault(key, []).extend(
                value.split()
                if key in {"After", "Before", "Wants", "Requires", "WantedBy", "PartOf"}
                else [value]
            )
    return values


class SessionTests(unittest.TestCase):
    def test_launcher_wait_bounds_slow_calls_and_degrades(self):
        launcher = unit("vicinae")
        script = (
            launcher["ExecStartPre"][0].split(" -c '", 1)[1][:-1].replace("$$", "$")
        )
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "busctl"
            for mode in ("ready", "unavailable", "hung"):
                fake.write_text(
                    f"#!{sys.executable}\n"
                    "import sys, time\n"
                    f"mode = {mode!r}\n"
                    "if mode == 'ready': raise SystemExit(0)\n"
                    "if mode == 'hung':\n"
                    "    timeout = next((float(a.split('=')[1][:-1]) "
                    "for a in sys.argv if a.startswith('--timeout=') "
                    "and a.endswith('s')), 2.6)\n"
                    "    time.sleep(min(timeout, 2.6))\n"
                    "raise SystemExit(1)\n"
                )
                fake.chmod(0o755)
                candidate = (
                    script.replace("/usr/bin/busctl", str(fake))
                    .replace("/usr/bin/sleep", shutil.which("sleep"))
                    .replace("SECONDS + 10", "SECONDS + 1")
                )
                started = time.monotonic()
                subprocess.run(["bash", "-c", candidate], check=True, timeout=3)
                self.assertLess(time.monotonic() - started, 2.5)

    def test_launcher_releases_watcher_before_shell_stops(self):
        launcher = unit("vicinae")
        self.assertIn("noctalia.service", launcher["After"])
        self.assertIn("noctalia.service", launcher.get("BindsTo", []))
        self.assertIn("noctalia.service", launcher["PartOf"])
        self.assertIn("vicinae.service", unit("noctalia").get("Wants", []))
        # Restart only the competing watcher, not communication apps or vaults.
        for name in ("vesktop", "tailscale-systray"):
            if (UNITS / (name + ".service")).exists():
                self.assertNotIn("noctalia.service", unit(name).get("PartOf", []))

    def test_noctalia_uses_a_runtime_file_key(self):
        if not EXPECTED["storage"]:
            self.assertFalse((UNITS / "../../noctalia/storage.toml").exists())
            return
        policy = tomllib.loads((UNITS / "../../noctalia/storage.toml").read_text())
        self.assertEqual(
            policy["storage"],
            {
                "key_source": "file",
                "key_file": EXPECTED["home"]
                + "/.local/share/noctalia/file-key-v1/master-key",
            },
        )
        self.assertFalse(policy["calendar"]["enabled"])
        self.assertFalse(
            (
                UNITS / "../../.." / ".local/share/noctalia/file-key-v1/master-key"
            ).exists()
        )

    def test_tray_consumers_and_degraded_launcher(self):
        names = ["tailscale-systray", "vesktop", "vicinae"]
        if EXPECTED["openrazer"]:
            names.append("polychromatic-tray")
        for name in names:
            config = unit(name)
            self.assertIn("noctalia.service", config["After"])
            self.assertIn("noctalia.service", config["Wants"])
            self.assertIn("graphical-session.target", config["PartOf"])


if __name__ == "__main__":
    unittest.main()
