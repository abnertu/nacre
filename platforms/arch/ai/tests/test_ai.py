"""Isolated contract tests for the native llama.cpp adapter."""

import importlib.util
import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, cast
import unittest

from nix_adapter import FakeNative, FakeProcess, Files

SOURCE = Path(sys.argv.pop()).resolve()
PACKAGE_CADDY = Path(sys.argv.pop()).resolve()
spec = importlib.util.spec_from_file_location("ai_runtime", SOURCE)
assert spec is not None and spec.loader is not None
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class Native(FakeNative):
    def __init__(self):
        super().__init__()
        self.services = {
            "llama-swap.service": {
                "LoadState": "loaded",
                "ActiveState": "inactive",
                "UnitFileState": "disabled",
            },
            "caddy.service": {
                "LoadState": "loaded",
                "ActiveState": "inactive",
                "UnitFileState": "disabled",
            },
        }
        self.serve = "{}"

    def run(self, *args, check=True, **kwargs):
        self.calls.append(args)
        if args[:2] == ("systemctl", "show"):
            return FakeProcess(
                "\n".join(f"{k}={v}" for k, v in self.services[args[2]].items())
            )
        if args[:2] in (
            ("systemctl", "enable"),
            ("systemctl", "start"),
            ("systemctl", "restart"),
        ):
            key = "UnitFileState" if args[1] == "enable" else "ActiveState"
            self.services[args[2]][key] = (
                "enabled" if key == "UnitFileState" else "active"
            )
        if args[:4] == ("tailscale", "serve", "status", "--json"):
            return FakeProcess(self.serve)
        if args[:2] == ("stat", "--format=%a:%U:%G"):
            return FakeProcess("750:caddy:caddy\n")
        if args[:2] == ("stat", "--format=%F"):
            return FakeProcess("socket\n")
        if args[:3] == ("tailscale", "serve", "--bg"):
            self.serve = json.dumps({"443": "http://127.0.0.1:11435"})
        if args[:3] == ("tailscale", "serve", "--https=443") and args[-1] == "off":
            self.serve = "{}"
        if args[:3] == ("systemctl", "disable", "--now"):
            self.services[args[3]].update(
                UnitFileState="disabled", ActiveState="inactive"
            )
        return FakeProcess()


class AITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in (
            "etc/caddy/conf.d",
            "etc/llama-swap",
            "etc/llama/server",
            "etc/systemd/system/llama-server.service.d",
            "var/lib/nix-config/arch",
            "var/lib/llama/models",
            "opt/llama/revisions/deadbeef-20000/bin",
        ):
            (self.root / name).mkdir(parents=True)
        (self.root / "opt/llama/revisions/deadbeef-20000/bin/llama-server").write_text(
            "binary"
        )
        (self.root / "opt/llama/revisions/deadbeef-20000/nix-config-build").write_text(
            "deadbeef 20000\n"
        )
        (self.root / "opt/llama/current").symlink_to("revisions/deadbeef-20000")
        (self.root / "var/lib/llama/models/model.gguf").write_text("model")
        self.files = Files(self.root, (os.getuid(), os.getgid()))
        self.native = Native()
        self.desired = {
            "llama": True,
            "proxy": True,
            "localPort": 11435,
            "httpsPort": 443,
            "source": {
                "installPrefix": "/opt/llama",
                "revision": "deadbeef",
                "grammarRepetitionThreshold": 20000,
            },
            "server": {"host": "127.0.0.1", "port": 11434, "modelsMax": 1},
            "model": {
                "id": "agent",
                "path": "/var/lib/llama/models/model.gguf",
                "device": "ROCm0",
                "contextSize": 98304,
                "fitTarget": 1024,
                "cacheTypeK": "q8_0",
                "cacheTypeV": "q8_0",
                "batchSize": 2048,
                "microBatchSize": 512,
                "parallel": 1,
                "enableThinking": True,
                "temperature": 1.0,
                "topP": 0.95,
                "topK": 20,
                "minP": 0.0,
                "presencePenalty": 0.0,
                "repetitionPenalty": 1.0,
            },
            "models": {
                "qwen": {
                    "id": "agent",
                    "repository": "fixture/model",
                    "revision": "deadbeef",
                    "file": "model.gguf",
                    "path": "/var/lib/llama/models/model.gguf",
                    "sha256": hashlib.sha256(b"model").hexdigest(),
                }
            },
            "switcher": {
                "binary": "/nix/store/llama-swap/bin/llama-swap",
                "listen": "127.0.0.1:11434",
                "startPort": 12434,
                "includeAliasesInList": True,
                "groups": {
                    "default": {
                        "swap": True,
                        "exclusive": True,
                        "members": ["agent"],
                    }
                },
                "models": {
                    "agent": {
                        "cmd": "/opt/llama/current/bin/llama-server --model /var/lib/llama/models/model.gguf --port ${PORT}",
                        "proxy": "http://127.0.0.1:${PORT}",
                        "checkEndpoint": "/health",
                        "aliases": ["agent", "agent:coding"],
                        "filters": {
                            "setParamsByID": {
                                "agent": {
                                    "temperature": 1.0,
                                    "top_p": 0.95,
                                    "top_k": 20,
                                    "min_p": 0.0,
                                    "presence_penalty": 0.0,
                                    "repetition_penalty": 1.0,
                                },
                                "agent:coding": {
                                    "temperature": 0.6,
                                    "top_p": 0.95,
                                    "top_k": 20,
                                    "min_p": 0.0,
                                    "presence_penalty": 0.0,
                                    "repetition_penalty": 1.0,
                                    "chat_template_kwargs": {"enable_thinking": True},
                                },
                            }
                        },
                    }
                },
            },
        }
        site = ":11435 {\n    bind 127.0.0.1\n    @api path /health /v1/*\n    handle @api { reverse_proxy 127.0.0.1:11434 }\n    respond 404\n}\n"
        package_caddy = PACKAGE_CADDY.read_text()
        self.desired["generated"] = {
            "switcherConfig": json.dumps(self.desired["switcher"]),
            "switcherUnit": "[Unit]\nDescription=Nix-config llama-swap model router\n[Service]\nEnvironment=LD_LIBRARY_PATH=/opt/llama/current/lib:/opt/llama/current/lib64\nExecStart=/nix/store/llama-swap/bin/llama-swap --config /etc/llama-swap/config.yaml --listen 127.0.0.1:11434\n",
            "caddyMain": '{\n    admin "unix//run/caddy/admin.socket"\n}\nimport /etc/caddy/conf.d/*\n',
            "caddySite": site,
            "packageCaddy": package_caddy,
            "packageCaddyWithSite": package_caddy.replace(
                "# Import additional caddy config files in /etc/caddy/conf.d/\n",
                site
                + "\n# Import additional caddy config files in /etc/caddy/conf.d/\n",
            ),
            "legacyPreset": "",
            "legacyDropin": "",
        }
        self.generated = cast(dict[str, Any], self.desired["generated"])
        model = self.root / "var/lib/llama/models/model.gguf"
        receipt = self.root / "var/lib/llama/models/model.gguf.nix-config-receipt"
        receipt.write_text(
            runtime.AI.model_receipt(model, self.desired["models"]["qwen"])
        )

    def ai(self):
        return runtime.AI(self.desired, self.files, self.native)

    def test_converges_model_router_and_proxy(self):
        self.ai().converge()
        config = json.loads((self.root / "etc/llama-swap/config.yaml").read_text())
        self.assertEqual(
            config["models"]["agent"]["aliases"], ["agent", "agent:coding"]
        )
        self.assertEqual(
            config["models"]["agent"]["filters"]["setParamsByID"]["agent:coding"][
                "temperature"
            ],
            0.6,
        )
        unit = (self.root / "etc/systemd/system/llama-swap.service").read_text()
        self.assertIn(
            "Environment=LD_LIBRARY_PATH=/opt/llama/current/lib:/opt/llama/current/lib64",
            unit,
        )
        self.assertIn("--config /etc/llama-swap/config.yaml", unit)
        self.assertIn("--listen 127.0.0.1:11434", unit)
        self.assertIn("@api path /health /v1/*", self.generated["caddySite"])
        self.assertIn("respond 404", self.generated["caddySite"])
        self.assertTrue(any(c[:2] == ("caddy", "reload") for c in self.native.calls))
        self.assertFalse(any((self.root / "var/lib/nix-config/arch").iterdir()))

    def test_repeat_repairs_no_files_and_performs_no_reload(self):
        self.ai().converge()
        self.native.calls.clear()
        result = self.ai()
        result.converge()
        self.assertEqual(result.updates, 0)
        self.assertFalse(any(c[:2] == ("caddy", "reload") for c in self.native.calls))

    def test_purge_withdraws_route_site_and_router_but_keeps_assets(self):
        self.ai().converge()
        self.native.calls.clear()
        self.ai().purge()
        self.assertEqual(self.native.serve, "{}")
        self.assertFalse(
            (self.root / "etc/caddy/conf.d/nix-config-llama.caddy").exists()
        )
        self.assertTrue(
            any(call[:2] == ("caddy", "reload") for call in self.native.calls)
        )
        self.assertEqual(
            self.native.services["llama-swap.service"]["UnitFileState"], "disabled"
        )
        self.assertFalse((self.root / "etc/systemd/system/llama-swap.service").exists())
        self.assertFalse((self.root / "etc/llama-swap/config.yaml").exists())
        self.assertTrue((self.root / "var/lib/llama/models/model.gguf").exists())
        self.assertTrue((self.root / "opt/llama/current").exists())

    def test_disabled_preserves_state(self):
        path = self.root / "etc/llama/server/models.ini"
        path.write_text("existing")
        marker = self.root / "var/lib/nix-config/arch/system-ai-llama.pending"
        marker.write_text("")
        self.desired = {"llama": False}
        self.ai().converge()
        self.assertEqual(path.read_text(), "existing")
        self.assertTrue(marker.exists())
        self.assertEqual(self.native.calls, [])

    def test_missing_prepared_assets_fail_after_selector_exists(self):
        (self.root / "opt/llama/current/bin/llama-server").unlink()
        result = self.ai()
        with self.assertRaisesRegex(runtime.Conflict, "assets are incomplete"):
            result.converge()
        self.assertEqual(result.updates, 0)
        self.assertEqual(self.native.calls, [])

    def test_model_metadata_drift_invalidates_preparation_receipt(self):
        model = self.root / "var/lib/llama/models/model.gguf"
        model.write_text("changed")
        with self.assertRaisesRegex(runtime.Conflict, "model receipt"):
            self.ai().preflight(installed=True)

    def add_completion_model(self):
        models = cast(dict[str, dict[str, Any]], self.desired["models"])
        declaration = dict(models["qwen"])
        declaration["path"] = "/var/lib/llama/models/completion.gguf"
        declaration["file"] = "completion.gguf"
        models["completion"] = declaration
        return declaration

    def test_second_model_must_exist_before_any_convergence(self):
        self.add_completion_model()
        with self.assertRaisesRegex(runtime.Conflict, "assets are incomplete"):
            self.ai().converge()
        self.assertEqual(self.native.calls, [])

    def test_second_model_receipt_is_independently_verified(self):
        declaration = self.add_completion_model()
        model = self.root / "var/lib/llama/models/completion.gguf"
        model.write_text("synthetic completion")
        receipt = Path(str(model) + ".nix-config-receipt")
        receipt.write_text(runtime.AI.model_receipt(model, declaration))
        self.assertTrue(self.ai().preflight(installed=True))
        self.native.calls.clear()
        model.write_text("drift")
        with self.assertRaisesRegex(runtime.Conflict, "model receipt"):
            self.ai().preflight(installed=True)
        self.assertEqual(self.native.calls, [])

    def test_pending_restarts_then_clears(self):
        self.files.mark("ai-llama")
        self.ai().converge()
        self.assertIn(("systemctl", "restart", "llama-swap.service"), self.native.calls)
        self.assertFalse(self.files.pending("ai-llama"))
        self.assertIn(("systemctl", "daemon-reload"), self.native.calls)

    def test_rejects_legacy_runtime_files_before_writes(self):
        legacy = self.root / "etc/systemd/system/llama-server.service.d/60-local.conf"
        legacy.write_text("manual\n")
        with self.assertRaises(runtime.Conflict):
            self.ai().preflight()
        legacy.unlink()
        (self.root / "etc/caddy/conf.d/nix-config-ollama.caddy").write_text("legacy\n")
        with self.assertRaises(runtime.Conflict):
            self.ai().preflight()
        self.assertFalse((self.root / "etc/llama/server/models.ini").exists())

    def test_known_legacy_policy_is_accepted_but_modified_policy_is_rejected(self):
        paths = {
            "legacyPreset": "etc/llama/server/models.ini",
            "legacyDropin": "etc/systemd/system/llama-server.service.d/60-nix-config.conf",
        }
        for field, relative in paths.items():
            self.generated[field] = f"known historical {field}\n"
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.generated[field])
        self.assertTrue(self.ai().preflight())
        self.native.calls.clear()
        for field, relative in paths.items():
            with self.subTest(field=field):
                path = self.root / relative
                original = path.read_text()
                path.write_text(original + "operator customization\n")
                with self.assertRaisesRegex(
                    runtime.Conflict, "requires explicit adoption"
                ):
                    self.ai().preflight()
                self.assertEqual(self.native.calls, [])
                self.assertEqual(
                    path.read_text(), original + "operator customization\n"
                )
                path.write_text(original)

    def test_rejects_mismatched_prepared_receipt(self):
        (self.root / "opt/llama/current/nix-config-build").write_text("other 20000\n")
        with self.assertRaises(runtime.Conflict):
            self.ai().preflight(installed=True)

    def test_rejects_unowned_prepared_selector(self):
        (self.root / "opt/llama/current").unlink()
        (self.root / "opt/llama/current").symlink_to("revisions/other-20000")
        with self.assertRaises(runtime.Conflict):
            self.ai().preflight(installed=True)

    def test_rejects_custom_caddy_and_serve_conflicts(self):
        (self.root / "etc/caddy/Caddyfile").write_text("example.com { respond ok }\n")
        with self.assertRaises(runtime.Conflict):
            self.ai().preflight()
        (self.root / "etc/caddy/Caddyfile").unlink()
        self.native.serve = '{"443":"http://127.0.0.1:9000"}'
        with self.assertRaises(runtime.Conflict):
            self.ai().converge()

    def test_adopts_exact_package_caddyfile(self):
        path = self.root / "etc/caddy/Caddyfile"
        path.write_text(self.generated["packageCaddy"])
        self.assertEqual(self.ai().caddy_main(), self.generated["caddyMain"])
        path.write_text(self.generated["packageCaddyWithSite"])
        self.assertEqual(self.ai().caddy_main(), self.generated["caddyMain"])


if __name__ == "__main__":
    unittest.main()
