# pyright: standard
"""Exercise the opt-in benchmark controller with fake binaries and sysfs."""

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "benchmark.py"
SPEC = importlib.util.spec_from_file_location("ai_benchmark", SOURCE)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.prefix = self.root / "prefix"
        (self.prefix / "bin").mkdir(parents=True)
        self.binary = self.prefix / "bin/llama-bench"
        self.server = self.prefix / "bin/llama-server"
        self.model = self.root / "model.gguf"
        self.model.write_bytes(b"fixture model")
        self.device = self.root / "sysfs/device"
        self.device.mkdir(parents=True)
        self.total_file = self.device / "mem_info_vram_total"
        self.used_file = self.device / "mem_info_vram_used"
        self.total_file.write_text(str(8 * 1024 * 1024 * 1024))
        self.used_file.write_text("0")
        self.output = self.root / "result.json"

    def install_binary(self, body):
        self.binary.write_text(f"#!{shutil.which('python3')}\n" + body)
        self.binary.chmod(0o755)
        self.server.write_text(
            f"#!{shutil.which('python3')}\nimport sys\nprint('fake llama.cpp build abc123')\n"
        )
        self.server.chmod(0o755)

    def cli(self, *extra):
        return benchmark.main(
            [
                "--model",
                str(self.model),
                "--binary-prefix",
                str(self.prefix),
                "--output",
                str(self.output),
                "--device-path",
                str(self.device),
                "--devices",
                "ROCm0",
                "--batches",
                "64",
                "--ubatches",
                "32",
                "--caches",
                "f16",
                "--threads",
                "2",
                "--gpu-layers",
                "0",
                *extra,
            ]
        )

    def test_parse_json_keeps_prompt_and_generation_metrics(self):
        result = benchmark.parse_metrics(
            '[{"test":"pp512","avg_ts":12.5},{"test":"tg128","avg_ts":7.25}]'
        )
        self.assertEqual([row["test"] for row in result["records"]], ["pp512", "tg128"])
        self.assertEqual([row["avg_ts"] for row in result["records"]], [12.5, 7.25])

    def test_empty_measurements_fail(self):
        self.install_binary("print('[]')\n")
        self.assertEqual(self.cli(), 1)
        self.assertIn(
            "parse_error",
            json.loads(self.output.read_text())["rows"][0]["parsed_metrics"],
        )

    def test_runs_matrix_and_records_identity_command_and_output(self):
        self.install_binary(
            "import sys\n"
            "print(' ' * 131072)\n"
            'print(\'[{"test":"pp512","avg_ts":12.5},{"test":"tg128","avg_ts":7.25}]\')\n'
            "print('e' * 131072, file=sys.stderr)\n"
        )
        self.assertEqual(self.cli(), 0)
        result = json.loads(self.output.read_text())
        self.assertEqual(result["binary_version"], "fake llama.cpp build abc123")
        self.assertEqual(len(result["rows"]), 1)
        row = result["rows"][0]
        self.assertEqual(
            [r["test"] for r in row["parsed_metrics"]["records"]], ["pp512", "tg128"]
        )
        self.assertGreater(len(row["stderr"]), 131072)
        self.assertIn("-dev", row["command"])
        self.assertIn("ROCm0", row["command"])
        self.assertEqual(row["generation_tokens"], 128)
        self.assertIn("512,4096", row["command"])
        self.assertIn("3", row["command"])

    def test_filters_ubatch_above_batch(self):
        self.install_binary("import sys\nprint('fake')\n")
        self.assertEqual(self.cli("--ubatches", "65"), 0)
        self.assertEqual(json.loads(self.output.read_text())["rows"], [])

    def test_timeout_preserves_partial_output(self):
        self.install_binary(
            "import sys,time\n"
            "print('partial before timeout', flush=True)\n"
            "print('e' * 131072, file=sys.stderr, flush=True)\ntime.sleep(10)\n"
        )
        # Long enough for the child to start on a slow runner; it sleeps for 10.
        self.assertEqual(self.cli("--timeout", "3"), 1)
        row = json.loads(self.output.read_text())["rows"][0]
        self.assertIn("timed out", row["error"])
        self.assertIn("partial before timeout", row["stdout"])
        self.assertGreater(len(row["stderr"]), 131072)

    def test_reserve_breach_terminates_running_process_and_preserves_output(self):
        self.install_binary(
            "import pathlib,sys,time\n"
            f"pathlib.Path({str(self.used_file)!r}).write_text(str(8 * 1024 * 1024 * 1024))\n"
            "print('started', flush=True)\n"
            "print('e' * 131072, file=sys.stderr, flush=True)\ntime.sleep(10)\n"
        )
        self.assertEqual(self.cli("--min-free-mib", "1024"), 1)
        row = json.loads(self.output.read_text())["rows"][0]
        self.assertIn("reserve breach", row["error"])
        self.assertIn("started", row["stdout"])
        self.assertIsNotNone(row["returncode"])


if __name__ == "__main__":
    unittest.main()
