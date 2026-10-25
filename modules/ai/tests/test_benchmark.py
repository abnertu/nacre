# pyright: standard
"""Exercise the opt-in benchmark controller with fake binaries and sysfs."""

import importlib.util
import json
import os
import shutil
import tempfile
import time
import unittest
from contextlib import suppress
from pathlib import Path
from unittest.mock import patch

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

    def test_filters_ubatch_above_batch(self):
        self.install_binary("import sys\nprint('fake')\n")
        self.assertEqual(self.cli("--ubatches", "65"), 1)
        self.assertEqual(json.loads(self.output.read_text())["rows"], [])
        self.assertIn("no runnable", json.loads(self.output.read_text())["error"])

    def test_cpu_expert_matrix_reaches_the_native_binary(self):
        self.install_binary(
            "import sys\n"
            "count = int(sys.argv[sys.argv.index('--n-cpu-moe') + 1]) if '--n-cpu-moe' in sys.argv else 0\n"
            "work = sum(map(int, sys.argv[sys.argv.index('-p')+1].split(','))) + int(sys.argv[sys.argv.index('-n')+1])\n"
            "work *= int(sys.argv[sys.argv.index('-r')+1])\n"
            "print('[{\"avg_ts\":%s}]' % (count + work))\n"
        )
        self.assertEqual(
            self.cli(
                "--cpu-moe-layers",
                "0,24,28",
                "--prompt-tokens",
                "128",
                "--generation-tokens",
                "16",
                "--repetitions",
                "1",
            ),
            0,
        )
        rows = json.loads(self.output.read_text())["rows"]
        self.assertEqual([row["cpu_moe_layers"] for row in rows], [0, 24, 28])
        self.assertEqual(
            [row["parsed_metrics"]["records"][0]["avg_ts"] for row in rows],
            [144, 168, 172],
        )

    def group_fixture(self):
        group = self.root / "cgroup"
        group.mkdir()
        self.region = "drm/0000:03:00.0/vram"
        for name, value in {
            "cgroup.procs": "",
            "cgroup.events": "populated 0\nfrozen 0\n",
            "dmem.max": f"{self.region} max\n",
            "dmem.current": f"{self.region} 0\n",
            "dmem.peak": f"{self.region} 0\n",
        }.items():
            (group / name).write_text(value)
        return group

    def test_group_membership_precedes_execution_and_peak_catches_short_allocation(
        self,
    ):
        group = self.group_fixture()
        self.install_binary(
            "import os,pathlib\n"
            f"group=pathlib.Path({str(group)!r})\n"
            "assert group.joinpath('cgroup.procs').read_text() == str(os.getpid())\n"
            f"group.joinpath('dmem.peak').write_text({self.region!r} + ' 2097152\\n')\n"
            "group.joinpath('cgroup.procs').write_text('')\n"
            "print('[{\"avg_ts\":5}]')\n"
        )
        self.server.write_text(
            f"#!{shutil.which('python3')}\nimport pathlib\n"
            f"pathlib.Path({str(group / 'cgroup.procs')!r}).write_text('')\n"
            "print('fixture version')\n"
        )
        self.assertEqual(
            self.cli(
                "--cgroup",
                str(group),
                "--dmem-region",
                self.region,
                "--max-vram-mib",
                "1",
            ),
            1,
        )
        row = json.loads(self.output.read_text())["rows"][0]
        self.assertEqual(row["returncode"], 0)
        self.assertIn("ceiling breached", row["error"])

    def test_populated_group_is_rejected_before_any_binary_executes(self):
        group = self.group_fixture()
        (group / "cgroup.events").write_text("populated 1\n")
        sentinel = self.root / "executed"
        self.install_binary(
            f"import pathlib\npathlib.Path({str(sentinel)!r}).touch()\n"
        )
        self.assertEqual(
            self.cli(
                "--cgroup",
                str(group),
                "--dmem-region",
                self.region,
                "--max-vram-mib",
                "1",
            ),
            1,
        )
        self.assertIn(
            "populated descendants", json.loads(self.output.read_text())["error"]
        )
        self.assertFalse(sentinel.exists())

    def test_kernel_without_dmem_peak_records_sampled_lower_bound(self):
        group = self.group_fixture()
        (group / "dmem.peak").unlink()
        self.install_binary(
            "import pathlib,time\n"
            f"group=pathlib.Path({str(group)!r})\n"
            f"group.joinpath('dmem.current').write_text({self.region!r} + ' 1048576\\n')\n"
            "time.sleep(1)\n"
            f"group.joinpath('dmem.current').write_text({self.region!r} + ' 0\\n')\n"
            "group.joinpath('cgroup.procs').write_text('')\n"
            "print('[{\"avg_ts\":5}]')\n"
        )
        self.server.write_text(
            f"#!{shutil.which('python3')}\nimport pathlib\n"
            f"pathlib.Path({str(group / 'cgroup.procs')!r}).write_text('')\n"
            "print('fixture version')\n"
        )
        self.assertEqual(
            self.cli(
                "--cgroup",
                str(group),
                "--dmem-region",
                self.region,
                "--max-vram-mib",
                "2",
            ),
            0,
        )
        row = json.loads(self.output.read_text())["rows"][0]
        self.assertNotIn("group_peak_vram_bytes", row)
        self.assertEqual(row["sampled_group_peak_vram_bytes"], 1048576)

    def test_shared_drm_client_is_counted_once_across_fds_and_children(self):
        group = self.group_fixture()
        (group / "cgroup.procs").write_text("100\n")
        child = group / "child"
        child.mkdir()
        (child / "cgroup.procs").write_text("200\n")
        proc = self.root / "proc"
        for pid, fd, pci, client, resident in (
            (100, 4, "0000:03:00.0", 7, 2),
            (100, 8, "0000:03:00.0", 7, 2),
            (200, 4, "0000:03:00.0", 7, 2),
            (200, 9, "0000:03:00.0", 8, 3),
            (200, 10, "0000:12:00.0", 9, 999),
        ):
            directory = proc / str(pid) / "fdinfo"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / str(fd)).write_text(
                f"drm-pdev:\t{pci}\ndrm-client-id:\t{client}\n"
                f"drm-total-vram:\t{resident + 1} KiB\ndrm-resident-vram:\t{resident} KiB\n"
                "drm-resident-gtt:\t4 KiB\n"
            )
        counters = benchmark.read_drm_clients(group, "0000:03:00.0", proc)
        self.assertEqual(counters["drm_client_count"], 2)
        self.assertEqual(counters["drm_resident_vram_bytes"], 5 * 1024)
        self.assertEqual(counters["drm_resident_gtt_bytes"], 8 * 1024)
        self.assertEqual(counters["drm_nonresident_vram_bytes"], 2 * 1024)

    def test_driver_spill_stops_the_native_command(self):
        group = self.group_fixture()
        self.install_binary(
            "import time\nprint('started', flush=True)\ntime.sleep(10)\n"
        )
        self.server.write_text(
            f"#!{shutil.which('python3')}\nimport pathlib\n"
            f"pathlib.Path({str(group / 'cgroup.procs')!r}).write_text('')\n"
            "print('fixture version')\n"
        )

        def sample(*args):
            return {
                "drm_nonresident_vram_bytes": 1024
                if (group / "cgroup.procs").read_text().strip()
                else 0
            }

        with patch.object(benchmark, "read_drm_clients", side_effect=sample):
            self.assertEqual(
                self.cli(
                    "--cgroup",
                    str(group),
                    "--dmem-region",
                    self.region,
                    "--max-vram-mib",
                    "1",
                    "--reject-vram-spill",
                ),
                1,
            )
        row = json.loads(self.output.read_text())["rows"][0]
        self.assertIn("reject driver spill", row["error"])
        self.assertEqual(row["sampled_drm_peaks"]["drm_nonresident_vram_bytes"], 1024)

    def test_monitor_failure_terminates_the_run(self):
        self.install_binary(
            "import pathlib,time\n"
            f"pathlib.Path({str(self.used_file)!r}).unlink()\n"
            "print('before monitor failure', flush=True)\ntime.sleep(10)\n"
        )
        self.assertEqual(self.cli(), 1)
        row = json.loads(self.output.read_text())["rows"][0]
        self.assertIn("resource monitor failed", row["error"])
        self.assertIn("before monitor failure", row["stdout"])

    def test_host_reserve_failure_prevents_launch(self):
        self.install_binary("print('[{\"avg_ts\":5}]')\n")
        meminfo = self.root / "meminfo"
        meminfo.write_text("MemAvailable: 1 kB\n")
        self.assertEqual(self.cli("--meminfo-path", str(meminfo)), 1)
        self.assertIn(
            "host memory reserve breach", json.loads(self.output.read_text())["error"]
        )

    def test_timeout_kills_children_that_ignore_termination(self):
        child_pid = self.root / "child.pid"
        self.install_binary(
            "import os,pathlib,signal,time\n"
            "pid=os.fork()\n"
            "if pid == 0:\n"
            " signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            f" pathlib.Path({str(child_pid)!r}).write_text(str(os.getpid()))\n"
            " time.sleep(30)\n"
            "else:\n"
            " time.sleep(30)\n"
        )
        self.assertEqual(self.cli("--timeout", "1"), 1)
        pid = int(child_pid.read_text())
        try:
            # A dead orphan may remain a zombie until the host reaps it.
            deadline = time.monotonic() + 2
            while Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z":
                if time.monotonic() >= deadline:
                    self.fail("benchmark child survived process-group cleanup")
                time.sleep(0.01)
        except FileNotFoundError:
            pass
        finally:
            with suppress(ProcessLookupError):
                os.kill(pid, 9)

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
            "print('started', flush=True)\n"
            "print('e' * 131072, file=sys.stderr, flush=True)\n"
            # Make the output available before the monitor can terminate us.
            f"pathlib.Path({str(self.used_file)!r}).write_text(str(8 * 1024 * 1024 * 1024))\n"
            "time.sleep(10)\n"
        )
        self.assertEqual(self.cli("--min-free-mib", "1024"), 1)
        row = json.loads(self.output.read_text())["rows"][0]
        self.assertIn("reserve breach", row["error"])
        self.assertIn("started", row["stdout"])
        self.assertGreater(len(row["stderr"]), 131072)
        self.assertIsNotNone(row["returncode"])


if __name__ == "__main__":
    unittest.main()
