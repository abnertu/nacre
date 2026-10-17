# pyright: standard
"""Exercise synthetic SSE diagnostics without loading a model."""

import importlib.util
import io
import json
import threading
import unittest
import urllib.error
from email.message import Message
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "probe", Path(__file__).parents[1] / "probe.py"
)
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def test_incomplete_stream_retains_partial_output_and_fails(self):
        stream = io.BytesIO(b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')
        with patch.object(probe.urllib.request, "urlopen", return_value=stream):
            result = probe.request("http://127.0.0.1:1", {"messages": []}, 5)
        self.assertEqual(result["content"], "partial")
        self.assertIn("completion marker", result["error"])

    def test_http_failure_retains_error_body(self):
        error = urllib.error.HTTPError(
            "http://127.0.0.1:1",
            503,
            "not ready",
            Message(),
            io.BytesIO(b"synthetic load failed"),
        )
        with patch.object(probe.urllib.request, "urlopen", side_effect=error):
            result = probe.request("http://127.0.0.1:1", {"messages": []}, 5)
        self.assertIn("HTTP 503", result["error"])
        self.assertIn("synthetic load failed", result["error"])
        error.close()

    def test_reasoning_first_stream_and_final_timings(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"]))
                )
                assert payload == {"messages": []}
                self.send_response(200)
                self.end_headers()
                for event in [
                    {"choices": [{"delta": {"role": "assistant"}}]},
                    {"choices": [{"delta": {"reasoning_content": "multiply"}}]},
                    {"choices": [{"delta": {"content": "391"}}]},
                    {
                        "choices": [],
                        "timings": {"predicted_per_second": 60},
                        "usage": {"completion_tokens": 3},
                    },
                ]:
                    self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
                self.wfile.write(b"data: [DONE]\n\n")

            def log_message(self, format, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            result = probe.request(
                f"http://127.0.0.1:{server.server_port}", {"messages": []}, 5
            )
            self.assertEqual(result["content"], "391")
            self.assertEqual(result["reasoning"], "multiply")
            self.assertLessEqual(
                result["first_event_seconds"], result["first_reasoning_seconds"]
            )
            self.assertLessEqual(
                result["first_reasoning_seconds"], result["first_content_seconds"]
            )
            self.assertEqual(result["timings"]["predicted_per_second"], 60)
            self.assertEqual(result["usage"]["completion_tokens"], 3)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
