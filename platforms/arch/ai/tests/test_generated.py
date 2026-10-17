"""Check the Nix-built AI manifest consumed by the privileged adapter."""

import json
from pathlib import Path
import sys
import unittest

MANIFEST = Path(sys.argv.pop(1))
PACKAGE_CADDY = Path(sys.argv.pop(1))


class GeneratedArtifactsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.desired = json.loads(MANIFEST.read_text())
        cls.generated = cls.desired["generated"]

    def test_router_and_legacy_units_listen_on_the_declared_loopback_port(self):
        desired = self.desired
        generated = self.generated
        self.assertIn(desired["switcher"]["binary"], generated["switcherUnit"])
        self.assertIn(
            f"--listen 127.0.0.1:{desired['server']['port']}",
            generated["switcherUnit"],
        )
        self.assertIn(f"--port {desired['server']['port']}", generated["legacyDropin"])
        self.assertIn(desired["legacy"]["model"]["path"], generated["legacyPreset"])

    def test_managed_templates_are_readable_store_assets_in_backend_commands(self):
        for model in self.desired["models"].values():
            template = model.get("chatTemplateFile")
            if template is None:
                continue
            with self.subTest(model=model["id"]):
                self.assertTrue(template.startswith("/nix/store/"))
                self.assertTrue(Path(template).is_file())
                command = self.desired["switcher"]["models"][model["id"]]["cmd"]
                self.assertIn("--chat-template-file", command)
                self.assertIn(template, command)

    def test_caddy_policy_is_loopback_only_and_keeps_package_adoption(self):
        desired = self.desired
        generated = self.generated
        site = generated["caddySite"]
        self.assertTrue(site.startswith(f":{desired['localPort']} {{\n"))
        self.assertIn("bind 127.0.0.1", site)
        self.assertIn(f"reverse_proxy 127.0.0.1:{desired['server']['port']}", site)
        self.assertIn("@api path /health /v1/*", site)
        self.assertIn("respond 404", site)
        self.assertIn(
            PACKAGE_CADDY.read_text().split("# Import additional")[0],
            generated["packageCaddyWithSite"],
        )
        self.assertIn('admin "unix//run/caddy/admin.socket"', generated["caddyMain"])


if __name__ == "__main__":
    unittest.main()
