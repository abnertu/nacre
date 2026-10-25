# pyright: standard
"""Pass generated routing policy through the real pinned native router."""

import concurrent.futures
import configparser
import importlib.util
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

MANIFEST = Path(sys.argv.pop(1))
BINARY = Path(sys.argv.pop(1))
FIXTURE = Path(sys.argv.pop(1))
EXPECTED = json.loads(Path(sys.argv.pop(1)).read_text())
SPEC = importlib.util.spec_from_file_location("router_fixture", FIXTURE)
assert SPEC is not None and SPEC.loader is not None
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)


class GeneratedRoutingTests(unittest.TestCase):
    def test_generated_startup_command_enforces_fixture_policy(self):
        manifest = json.loads(MANIFEST.read_text())
        unit = configparser.RawConfigParser()
        unit.read_string(manifest["generated"]["switcherUnit"])
        command = shlex.split(unit["Service"]["ExecStartPre"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hierarchy = root / "sys/fs/cgroup"
            group = hierarchy / "system.slice/llama-swap.service"
            group.mkdir(parents=True)
            (root / "proc/self").mkdir(parents=True)
            (root / "proc/self/cgroup").write_text(
                "0::/system.slice/llama-swap.service\n"
            )
            for ancestor in (hierarchy, group.parent):
                (ancestor / "cgroup.controllers").write_text("dmem\n")
                (ancestor / "cgroup.subtree_control").write_text("dmem\n")
            region = "drm/0000:03:00.0/vram"
            (group / "dmem.current").write_text(f"{region} 0\n")
            (group / "dmem.max").write_text(f"{region} max\n")
            result = subprocess.run(
                [*command, "--root", str(root)], capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            # The independently declared fixture supplies 173 MiB, not a default.
            self.assertEqual(
                (group / "dmem.max").read_text(), f"{region} {173 * 1024**2}\n"
            )

    def start_generated_router(self, manifest_path):
        harness = fixture.RouterIntegrationTests(methodName="runTest")
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        manifest = json.loads(Path(manifest_path).read_text())
        config = json.loads(manifest["generated"]["switcherConfig"])
        count = len(config["models"])
        config["startPort"] = fixture.unused_port_range(count)
        while config["startPort"] <= harness.router_port < config["startPort"] + count:
            config["startPort"] = fixture.unused_port_range(count)
        for model_id, model in config["models"].items():
            # Replace only the unavailable native inference binary. Retain its
            # generated arguments, aliases, filters and model concurrency policy.
            native = shlex.split(model["cmd"])
            model["cmd"] = (
                shlex.join(
                    [
                        sys.executable,
                        str(FIXTURE),
                        "--child",
                        "--child-model",
                        model_id,
                        "--request-file",
                        str(harness.root / f"{model_id}.requests.jsonl"),
                        "--child-port",
                    ]
                )
                + " ${PORT} "
                + shlex.join(native[1:]).replace("'${PORT}'", "${PORT}")
            )
        harness.config_path.write_text(json.dumps(config))
        harness.start_router(BINARY)
        return harness, config

    def test_aliases_share_backends_and_force_declared_sampling(self):
        harness, config = self.start_generated_router(MANIFEST)
        initial_pids = {}
        for model_id, model in config["models"].items():
            initial_pid = None
            for alias, expected in model["filters"]["setParamsByID"].items():
                response = fixture.post(
                    f"http://127.0.0.1:{harness.router_port}/v1/chat/completions",
                    {
                        "model": alias,
                        "messages": [{"role": "user", "content": "fixture"}],
                        "temperature": 1.111,
                        "top_k": 987,
                        "chat_template_kwargs": {"fixture_override": True},
                    },
                )
                harness.child_pids.add(response["pid"])
                if initial_pid is None:
                    initial_pid = response["pid"]
                    initial_pids[model_id] = initial_pid
                self.assertEqual(response["pid"], initial_pid)
                self.assertEqual(response["fixture_model"], model_id)
                for parameter, value in expected.items():
                    self.assertEqual(response["request"][parameter], value)
                if model_id == EXPECTED["baselineId"]:
                    arguments = response["native_arguments"]
                    self.assertEqual(
                        int(arguments[arguments.index("--batch-size") + 1]),
                        EXPECTED["batch"],
                    )
                    self.assertEqual(
                        int(arguments[arguments.index("--ubatch-size") + 1]),
                        EXPECTED["microBatch"],
                    )
                    self.assertEqual(
                        int(arguments[arguments.index("--threads") + 1]), 3
                    )
                    self.assertEqual(
                        int(arguments[arguments.index("--threads-batch") + 1]), 5
                    )
        preserved = fixture.post(
            f"http://127.0.0.1:{harness.router_port}/v1/chat/completions",
            {
                "model": EXPECTED["baselineId"] + ":preserved-thinking",
                "messages": [{"role": "user", "content": "fixture"}],
            },
        )
        self.assertEqual(
            preserved["request"]["chat_template_kwargs"],
            {"enable_thinking": True, "preserve_thinking": True},
        )
        instruct = fixture.post(
            f"http://127.0.0.1:{harness.router_port}/v1/chat/completions",
            {
                "model": EXPECTED["baselineId"] + ":instruct",
                "messages": [{"role": "user", "content": "fixture"}],
                "temperature": 1.111,
                "chat_template_kwargs": {"enable_thinking": True},
            },
        )
        self.assertEqual(instruct["request"]["temperature"], 0.42)
        self.assertFalse(instruct["request"]["chat_template_kwargs"]["enable_thinking"])
        if EXPECTED["concurrent"]:
            models = list(config["models"])[:2]

            def delayed(model):
                return fixture.post(
                    f"http://127.0.0.1:{harness.router_port}/v1/completions",
                    {"model": model, "prompt": "fixture", "fixture_delay": 0.5},
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(delayed, models))
            for model, response in zip(models, responses, strict=True):
                self.assertEqual(response["pid"], initial_pids[model])
            self.assertLess(
                max(r["started"] for r in responses), min(r["ended"] for r in responses)
            )

    def test_exclusive_routes_release_backends_and_use_target_presets(self):
        harness, _ = self.start_generated_router(EXPECTED["exclusiveManifest"])

        def request(model):
            response = fixture.post(
                f"http://127.0.0.1:{harness.router_port}/v1/chat/completions",
                {"model": model, "messages": [{"role": "user", "content": "fixture"}]},
            )
            harness.child_pids.add(response["pid"])
            return response

        def running(pid):
            try:
                state = Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1]
            except FileNotFoundError:
                return False
            return state.split()[0] != "Z"

        first = request(EXPECTED["exclusiveDefaultId"])
        second = request(EXPECTED["exclusiveTargetId"] + ":thinking-general")
        self.assertFalse(running(first["pid"]))
        self.assertEqual(second["fixture_model"], EXPECTED["exclusiveTargetId"])
        # The selected older model has no thinking template. The default
        # model's preset must not inject an unsupported mode into its request.
        self.assertNotIn("chat_template_kwargs", second["request"])
        restarted = request(EXPECTED["exclusiveDefaultId"])
        self.assertFalse(running(second["pid"]))
        self.assertNotEqual(first["pid"], restarted["pid"])


if __name__ == "__main__":
    unittest.main()
