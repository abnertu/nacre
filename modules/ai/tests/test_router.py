# pyright: standard
"""Exercise the pinned llama-swap router against disposable HTTP model servers."""

import concurrent.futures
import contextlib
import http.server
import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import cast

LLAMA_SWAP: Path | None = None
FIXTURE = Path(__file__).resolve()


class FakeModelHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_error(404)
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_POST(self):
        if self.path not in (
            "/v1/completions",
            "/v1/chat/completions",
            "/v1/responses",
        ):
            self.send_error(404)
            return
        request = json.loads(
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
        )
        if self.path == "/v1/responses" and request.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            message = {
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": "LOCAL_PROFILE_OK",
                        "annotations": [],
                    }
                ],
            }
            has_shell = any(
                tool.get("name") == "exec_command" for tool in request.get("tools", [])
            )
            has_output = any(
                item.get("type") == "function_call_output"
                for item in request.get("input", [])
                if isinstance(item, dict)
            )
            call_shell = has_shell and not has_output
            if call_shell:
                message = {
                    "id": "fc_fixture",
                    "type": "function_call",
                    "call_id": "call_fixture",
                    "name": "exec_command",
                    "arguments": json.dumps({"cmd": "pwd", "max_output_tokens": 128}),
                    "status": "completed",
                }
            response = {
                "id": "resp_fixture",
                "object": "response",
                "created_at": 1,
                "model": request["model"],
                "status": "completed",
                "output": [message],
                "usage": {"input_tokens": 32, "output_tokens": 4, "total_tokens": 36},
            }
            events = [
                {
                    "type": "response.created",
                    "response": {**response, "status": "in_progress", "output": []},
                },
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {**message, "status": "in_progress", "content": []},
                },
                {
                    "type": "response.output_text.delta",
                    "item_id": "msg_fixture",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": "LOCAL_PROFILE_OK",
                },
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": message,
                },
                {"type": "response.completed", "response": response},
            ]
            if call_shell:
                events = [
                    events[0],
                    {
                        "type": "response.output_item.done",
                        "output_index": 0,
                        "item": message,
                    },
                    events[-1],
                ]
            with cast(FakeModelServer, self.server).request_file.open("a") as output:
                output.write(json.dumps(request) + "\n")
            for event in events:
                self.wfile.write(
                    (
                        "event: "
                        + event["type"]
                        + "\ndata: "
                        + json.dumps(event)
                        + "\n\n"
                    ).encode()
                )
                self.wfile.flush()
            return
        started = time.monotonic()
        time.sleep(float(request.get("fixture_delay", 0)))
        response = json.dumps(
            {
                "fixture_model": cast(FakeModelServer, self.server).fixture_model,
                "pid": os.getpid(),
                "native_arguments": cast(FakeModelServer, self.server).native_arguments,
                "request": request,
                "started": started,
                "ended": time.monotonic(),
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format, *args):
        pass


class FakeModelServer(http.server.ThreadingHTTPServer):
    fixture_model: str
    request_file: Path
    native_arguments: list[str]


def run_child(argv):
    model = argv[argv.index("--child-model") + 1]
    port = int(argv[argv.index("--child-port") + 1])
    server = FakeModelServer(("127.0.0.1", port), FakeModelHandler)
    server.fixture_model = model
    server.native_arguments = argv
    server.request_file = Path(argv[argv.index("--request-file") + 1])
    server.serve_forever()


def unused_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def unused_port_range(count):
    for _ in range(100):
        candidate = unused_port()
        sockets = []
        try:
            for port in range(candidate, candidate + count):
                listener = socket.socket()
                listener.bind(("127.0.0.1", port))
                sockets.append(listener)
            return candidate
        except OSError:
            pass
        finally:
            for listener in sockets:
                listener.close()
    raise RuntimeError("could not find free consecutive model ports")


def post(url, payload, timeout=10):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise AssertionError(
            f"POST {url} returned HTTP {error.code}: {detail}"
        ) from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise AssertionError(f"POST {url} failed: {error}") from error


class RouterIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="llama-swap-router-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model_port = unused_port_range(2)
        self.router_port = unused_port()
        while self.model_port <= self.router_port < self.model_port + 2:
            self.router_port = unused_port()
        self.router_log = (self.root / "router.log").open("w+b")
        self.child_pids = set()
        self.router = None
        models = {}
        for model in ("model-a", "model-b"):
            command = " ".join(
                (
                    shlex.quote(sys.executable),
                    shlex.quote(str(FIXTURE)),
                    "--child",
                    "--child-model",
                    model,
                    "--request-file",
                    shlex.quote(str(self.root / (model + ".requests.jsonl"))),
                    "--child-port",
                    "${PORT}",
                )
            )
            model_config = {
                "cmd": command,
                "proxy": "http://127.0.0.1:${PORT}",
                "checkEndpoint": "/health",
                "ttl": 0,
            }
            if model == "model-a":
                model_config["aliases"] = ["model-a-chat"]
                model_config["filters"] = {
                    "setParamsByID": {"model-a-chat": {"temperature": 0.23}}
                }
            models[model] = model_config
        self.config = {
            "listen": f"127.0.0.1:{self.router_port}",
            "startPort": self.model_port,
            "globalTTL": 0,
            "includeAliasesInList": True,
            "healthCheckTimeout": 5,
            "groups": {
                "shared": {
                    "members": ["model-a", "model-b"],
                    "swap": False,
                    "exclusive": False,
                    "persistent": True,
                }
            },
            "models": models,
        }
        self.config_path = self.root / "config.json"
        self.config_path.write_text(json.dumps(self.config))
        self.addCleanup(self.stop_router)

    def start_router(self, binary=None):
        binary = binary or LLAMA_SWAP
        if binary is None:
            raise RuntimeError(
                "router integration must run with the pinned binary path argument"
            )
        self.router = subprocess.Popen(
            [
                str(binary),
                "-config",
                str(self.config_path),
                "-listen",
                f"127.0.0.1:{self.router_port}",
            ],
            stdout=self.router_log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        url = f"http://127.0.0.1:{self.router_port}/v1/models"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.router.poll() is not None:
                break
            try:
                with urllib.request.urlopen(url, timeout=0.25):
                    return
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.05)
        self.router_log.flush()
        self.router_log.seek(0)
        raise AssertionError(
            f"llama-swap failed to start (status={self.router.poll()}):\n{self.router_log.read().decode(errors='replace')}"
        )

    def stop_router(self):
        if self.router is not None and self.router.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.router.pid, signal.SIGTERM)
            try:
                self.router.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(self.router.pid, signal.SIGKILL)
                self.router.wait(timeout=5)
        for pid in self.child_pids:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 2
        alive = []
        while time.monotonic() < deadline:
            alive = []
            for pid in self.child_pids:
                try:
                    os.kill(pid, 0)
                    alive.append(pid)
                except ProcessLookupError:
                    pass
            if not alive:
                break
            time.sleep(0.05)
        for pid in alive if "alive" in locals() else ():
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
        if self.router_log:
            self.router_log.close()

    def test_models_stay_loaded_route_concurrently_and_apply_chat_alias(self):
        self.start_router()
        base = f"http://127.0.0.1:{self.router_port}/v1/completions"
        try:
            first_a = post(base, {"model": "model-a", "prompt": "first A"})
        except AssertionError as error:
            self.router_log.flush()
            self.router_log.seek(0)
            raise AssertionError(
                f"{error}\nrouter log:\n{self.router_log.read().decode(errors='replace')}"
            ) from error
        first_b = post(base, {"model": "model-b", "prompt": "first B"})
        second_a = post(base, {"model": "model-a", "prompt": "second A"})
        self.child_pids.update((first_a["pid"], first_b["pid"]))
        self.assertEqual(first_a["fixture_model"], "model-a")
        self.assertEqual(first_b["fixture_model"], "model-b")
        self.assertEqual(
            second_a["pid"], first_a["pid"], "model A restarted after routing model B"
        )

        chat = post(
            f"http://127.0.0.1:{self.router_port}/v1/chat/completions",
            {
                "model": "model-a-chat",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        self.assertEqual(chat["pid"], first_a["pid"])
        self.assertEqual(chat["request"]["temperature"], 0.23)

        def slow_request(model):
            return post(base, {"model": model, "prompt": model, "fixture_delay": 0.5})

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            pending = [
                executor.submit(slow_request, model) for model in ("model-a", "model-b")
            ]
            overlap_a, overlap_b = [future.result(timeout=8) for future in pending]
        self.child_pids.update((overlap_a["pid"], overlap_b["pid"]))
        self.assertEqual(overlap_a["pid"], first_a["pid"])
        self.assertEqual(overlap_b["pid"], first_b["pid"])
        self.assertEqual(overlap_a["fixture_model"], "model-a")
        self.assertEqual(overlap_b["fixture_model"], "model-b")
        self.assertLess(
            max(overlap_a["started"], overlap_b["started"]),
            min(overlap_a["ended"], overlap_b["ended"]),
        )

    def test_responses_routes_alias_and_preserves_tools_and_reasoning(self):
        self.start_router()
        payload = {
            "model": "model-a-chat",
            "input": [{"role": "user", "content": "synthetic request"}],
            "reasoning": {"effort": "low"},
            "tools": [
                {
                    "type": "function",
                    "name": "lookup_symbol",
                    "description": "fixture",
                    "parameters": {
                        "type": "object",
                        "properties": {"symbol": {"type": "string"}},
                        "required": ["symbol"],
                    },
                }
            ],
        }
        result = post(f"http://127.0.0.1:{self.router_port}/v1/responses", payload)
        self.child_pids.add(result["pid"])
        self.assertEqual(result["fixture_model"], "model-a")
        self.assertEqual(result["request"]["model"], payload["model"])
        self.assertEqual(result["request"]["tools"], payload["tools"])
        self.assertEqual(result["request"]["reasoning"], payload["reasoning"])
        self.assertEqual(result["request"]["temperature"], 0.23)
        payload["stream"] = True
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.router_port}/v1/responses",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            events = response.read().decode()
        self.assertIn("response.completed", events)
        self.assertIn("LOCAL_PROFILE_OK", events)

    @unittest.skipUnless(
        os.environ.get("CODEX_TEST_BINARY"), "optional installed Codex integration"
    )
    def test_installed_codex_uses_generated_standalone_profile(self):
        self.start_router()
        codex_home = self.root / "codex-home"
        codex_home.mkdir()
        source = Path(os.environ["CODEX_TEST_PROFILE_FILE"]).read_text()
        profile = source.replace(
            "http://127.0.0.1:11434/v1", f"http://127.0.0.1:{self.router_port}/v1"
        )
        # Only the synthetic model and disposable endpoint replace generated policy.
        import tomllib

        model_id = tomllib.loads(profile)["model"]
        profile = profile.replace(json.dumps(model_id), '"model-a"', 1)
        (codex_home / "llama-cpp.config.toml").write_text(profile)
        env = os.environ.copy()
        env["CODEX_HOME"] = str(codex_home)
        for key in list(env):
            if key.startswith(("OPENAI_", "CODEX_")) and key != "CODEX_HOME":
                del env[key]
        result = subprocess.run(
            [
                os.environ["CODEX_TEST_BINARY"],
                "exec",
                "--profile",
                "llama-cpp",
                "--strict-config",
                "--skip-git-repo-check",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--color",
                "never",
                "Run pwd once, then return LOCAL_PROFILE_OK.",
            ],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("LOCAL_PROFILE_OK", result.stdout)
        self.assertIn("provider: llama_cpp", result.stderr)
        captured = [
            json.loads(line)
            for line in (self.root / "model-a.requests.jsonl").read_text().splitlines()
        ]
        self.assertGreaterEqual(len(captured), 2)
        self.assertTrue(
            all(not request.get("previous_response_id") for request in captured)
        )
        self.assertTrue(
            any(
                item.get("type") == "function_call_output"
                and item.get("call_id") == "call_fixture"
                for item in captured[-1]["input"]
            )
        )
        self.assertEqual(captured[-1]["model"], "model-a")
        self.assertTrue(captured[-1]["stream"])
        self.assertTrue(captured[-1]["tools"])
        self.assertTrue(
            all(tool["type"] == "function" for tool in captured[-1]["tools"]),
            [
                (
                    tool["type"],
                    tool.get("name"),
                    [t.get("name") for t in tool.get("tools", [])],
                )
                for tool in captured[-1]["tools"]
            ],
        )


if __name__ == "__main__":
    if "--child" in sys.argv:
        run_child(sys.argv)
    else:
        LLAMA_SWAP = Path(sys.argv.pop()).resolve(strict=True)
        unittest.main()
