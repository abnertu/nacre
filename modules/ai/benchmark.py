#!/usr/bin/env python3
"""Run an explicit, opt-in llama-bench matrix and record its raw results."""

import argparse
import hashlib
import itertools
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast


def comma_values[Value](value: str, cast: Callable[[str], Value] = str) -> list[Value]:
    try:
        values = [cast(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    if not values:
        raise argparse.ArgumentTypeError("provide at least one comma-separated value")
    return values


def parse_metrics(output: str) -> dict[str, Any]:
    """Parse llama-bench JSON while preserving every PP and TG measurement."""
    try:
        parsed: object = json.loads(output)
    except json.JSONDecodeError:
        return {"parse_error": "llama-bench did not emit valid JSON"}
    records: object
    metadata: dict[str, Any]
    if isinstance(parsed, dict):
        document = cast("dict[str, Any]", parsed)
        records = document.get("results", [document])
        metadata = {key: value for key, value in document.items() if key != "results"}
    elif isinstance(parsed, list):
        records, metadata = cast("list[Any]", parsed), {}
    else:
        return {"parse_error": "llama-bench JSON must be an object or array"}
    if (
        not isinstance(records, list)
        or not records
        or not all(
            isinstance(record, dict)
            and isinstance(cast("dict[str, Any]", record).get("avg_ts"), (int, float))
            and cast("dict[str, Any]", record)["avg_ts"] > 0
            for record in cast("list[object]", records)
        )
    ):
        return {"parse_error": "llama-bench JSON has no valid throughput records"}
    return {"metadata": metadata, "records": records}


def read_vram(device_path: Path) -> tuple[int, int]:
    """Read AMD DRM sysfs VRAM counters, returning (total_mib, used_mib)."""
    root = Path(device_path)
    total = int((root / "mem_info_vram_total").read_text().strip())
    used = int((root / "mem_info_vram_used").read_text().strip())
    return total // (1024 * 1024), used // (1024 * 1024)


def terminate(process: subprocess.Popen[bytes]) -> None:
    # The session belongs to this invocation, including any surviving children.
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    finally:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)


def region_bytes(path: Path, region: str) -> int:
    for line in path.read_text().splitlines():
        key, value = line.split()
        if key == region:
            number = int(value)
            if number < 0:
                raise ValueError(f"negative device memory counter in {path}")
            return number
    raise ValueError(f"missing device memory region {region} in {path}")


def drm_bytes(value: str) -> int:
    matched = re.fullmatch(r"(\d+)\s*(B|KiB|kB|MiB)", value)
    if matched is None:
        raise ValueError("unknown DRM memory counter unit")
    return (
        int(matched[1])
        * {"B": 1, "KiB": 1024, "kB": 1024, "MiB": 1024 * 1024}[matched[2]]
    )


def read_drm_clients(
    group: Path, pci: str, proc_root: Path = Path("/proc")
) -> dict[str, int]:
    """Sum the DRM memory of this group's clients on device `pci`.

    A client that several descriptors or processes share counts once, with
    the largest value that any of its descriptors reports.
    """
    clients: dict[tuple[str, str], dict[str, int]] = {}
    for pid in group_pids(group):
        for fields in drm_descriptors(proc_root / str(pid) / "fdinfo"):
            if fields.get("drm-pdev") != pci or "drm-client-id" not in fields:
                continue
            previous = clients.setdefault(
                (fields["drm-pdev"], fields["drm-client-id"]), {}
            )
            for key, amount in client_counters(fields).items():
                previous[key] = max(previous.get(key, 0), amount)
    return combine_clients(list(clients.values()))


def group_pids(group: Path) -> set[int]:
    """The processes in `group` and its descendant cgroups."""
    memberships = [group / "cgroup.procs", *group.glob("**/cgroup.procs")]
    return {
        int(line)
        for membership in memberships
        for line in membership.read_text().splitlines()
    }


def drm_descriptors(fdinfo: Path) -> list[dict[str, str]]:
    """The `drm-*` fields of each descriptor in `fdinfo`; gone processes give none."""
    try:
        descriptors = list(fdinfo.iterdir())
    except FileNotFoundError:
        return []
    found: list[dict[str, str]] = []
    for descriptor in descriptors:
        try:
            lines = descriptor.read_text().splitlines()
        except (FileNotFoundError, ProcessLookupError):
            continue
        pairs = (line.split(":", 1) for line in lines if line.startswith("drm-"))
        found.append({key: value.strip() for key, value in pairs})
    return found


def client_counters(fields: dict[str, str]) -> dict[str, int]:
    """The resident and requested VRAM and GTT bytes of one descriptor."""
    counters: dict[str, int] = {}
    for kind in ("vram", "gtt"):
        resident = fields.get(f"drm-resident-{kind}", fields.get(f"drm-memory-{kind}"))
        total = fields.get(f"drm-total-{kind}")
        if resident is not None:
            counters[f"drm_resident_{kind}_bytes"] = drm_bytes(resident)
        if total is not None:
            counters[f"drm_requested_{kind}_bytes"] = drm_bytes(total)
    return counters


def combine_clients(clients: list[dict[str, int]]) -> dict[str, int]:
    """Totals across clients, plus the requested VRAM that is not resident."""
    combined: dict[str, int] = {"drm_client_count": len(clients)}
    for counters in clients:
        for key, amount in counters.items():
            combined[key] = combined.get(key, 0) + amount
    combined["drm_nonresident_vram_bytes"] = sum(
        max(
            0,
            counters.get("drm_requested_vram_bytes", 0)
            - counters.get("drm_resident_vram_bytes", 0),
        )
        for counters in clients
    )
    return combined


class DmemGroup:
    """Use an explicitly delegated, empty cgroup; never create host policy."""

    def __init__(self, path: Path, region: str, limit: int) -> None:
        self.path = path.resolve(strict=True)
        self.region, self.limit = region, limit

    def prepare(self) -> None:
        if (self.path / "cgroup.procs").read_text().strip():
            raise RuntimeError("experiment cgroup already contains processes")
        events = dict(
            line.split()
            for line in (self.path / "cgroup.events").read_text().splitlines()
        )
        if events.get("populated") != "0":
            raise RuntimeError("experiment cgroup has populated descendants")
        if region_bytes(self.path / "dmem.current", self.region) != 0:
            raise RuntimeError("experiment cgroup still owns device memory")
        # Missing controller files must fail, rather than become ordinary files.
        for name in ("dmem.max",):
            if not (self.path / name).is_file():
                raise RuntimeError(f"missing cgroup controller interface: {name}")
        with (self.path / "dmem.max").open("r+") as control:
            control.write(f"{self.region} {self.limit}\n")
        swap_limit = self.path / "memory.swap.max"
        if swap_limit.is_file():
            swap_limit.write_text("0\n")
        self.sample()

    def command(self, command: list[str]) -> list[str]:
        return [
            sys.executable,
            str(Path(__file__).resolve()),
            "--enter-cgroup",
            str(self.path),
            "--",
            *command,
        ]

    def sample(self) -> dict[str, int]:
        if region_bytes(self.path / "dmem.max", self.region) != self.limit:
            raise RuntimeError("experiment device memory limit changed")
        current = region_bytes(self.path / "dmem.current", self.region)
        peak_path = self.path / "dmem.peak"
        peak = region_bytes(peak_path, self.region) if peak_path.is_file() else None
        if current > self.limit or (peak is not None and peak > self.limit):
            raise RuntimeError(
                f"experiment device memory ceiling breached: current={current}, peak={peak}, limit={self.limit}"
            )
        counters = {"current_vram_bytes": current}
        if peak is not None:
            counters["group_peak_vram_bytes"] = peak
        for filename, key in (
            ("memory.current", "group_memory_bytes"),
            ("memory.peak", "group_peak_memory_bytes"),
            ("memory.swap.current", "group_swap_bytes"),
        ):
            path = self.path / filename
            if path.is_file():
                counters[key] = int(path.read_text())
        if counters.get("group_swap_bytes", 0):
            raise RuntimeError("experiment group used swap")
        counters.update(read_drm_clients(self.path, self.region.split("/")[1]))
        return counters


def host_available(path: Path) -> int:
    for line in path.read_text().splitlines():
        if line.startswith("MemAvailable:"):
            _, value, unit = line.split()
            if unit != "kB":
                raise ValueError("unexpected MemAvailable unit")
            return int(value) * 1024
    raise ValueError("missing MemAvailable counter")


@dataclass
class Monitor:
    """Resource limits of one benchmark run, and what the run used.

    Device VRAM must keep `min_free_mib` free and the host must keep
    `min_host_bytes` available; an optional cgroup bounds device memory.
    """

    device_path: Path
    min_free_mib: int
    min_host_bytes: int
    meminfo_path: Path
    group: DmemGroup | None
    reject_vram_spill: bool
    peak: int = 0
    minimum_host: int = 0
    sampled_group_peak: int = 0
    drm_peaks: dict[str, int] = field(default_factory=dict[str, int])
    group_metrics: dict[str, int] = field(default_factory=dict[str, int])

    def check_before_launch(self) -> None:
        """Raise `RuntimeError` unless the reserves hold before the run starts."""
        total, used = read_vram(self.device_path)
        if total - used < self.min_free_mib:
            raise RuntimeError(
                f"VRAM reserve breach before launch: {total - used} MiB free, {self.min_free_mib} MiB required"
            )
        if self.group is not None:
            self.group.prepare()
        self.peak = used
        self.minimum_host = host_available(self.meminfo_path)
        if self.minimum_host < self.min_host_bytes:
            raise RuntimeError("host memory reserve breach before launch")

    def sample(self) -> str | None:
        """Sample once during the run; return the failure that stops it, if any."""
        try:
            total, used = self.sample_host()
            if self.minimum_host < self.min_host_bytes:
                return "host memory reserve breach during run"
            if self.group is not None:
                self.sample_group()
                for key, amount in self.group_metrics.items():
                    if key.startswith("drm_"):
                        self.drm_peaks[key] = max(self.drm_peaks.get(key, 0), amount)
                if self.reject_vram_spill and self.group_metrics.get(
                    "drm_nonresident_vram_bytes", 0
                ):
                    return "requested VRAM became nonresident; reject driver spill"
            if total - used < self.min_free_mib:
                return f"VRAM reserve breach during run: {total - used} MiB free, {self.min_free_mib} MiB required"
        except (OSError, ValueError, RuntimeError) as error:
            return f"resource monitor failed during run: {error}"
        return None

    def final_sample(self) -> str | None:
        """Sample once after the run; return a failure that the run caused, if any."""
        try:
            self.sample_host()
            if self.group is not None:
                self.sample_group()
            if self.minimum_host < self.min_host_bytes:
                return "host memory reserve breach after run"
        except (OSError, ValueError, RuntimeError) as error:
            return f"resource monitor failed after run: {error}"
        return None

    def sample_host(self) -> tuple[int, int]:
        """Record device VRAM use and host availability; return VRAM (total, used)."""
        total, used = read_vram(self.device_path)
        self.peak = max(self.peak, used)
        self.minimum_host = min(self.minimum_host, host_available(self.meminfo_path))
        return total, used

    def sample_group(self) -> None:
        """Record the cgroup's counters and its sampled VRAM peak."""
        assert self.group is not None
        self.group_metrics = self.group.sample()
        self.sampled_group_peak = max(
            self.sampled_group_peak, self.group_metrics["current_vram_bytes"]
        )


def run_command(
    command: list[str],
    timeout: float,
    env: dict[str, str],
    device_path: Path,
    min_free_mib: int,
    group: DmemGroup | None = None,
    min_host_available_mib: int = 0,
    meminfo_path: Path = Path("/proc/meminfo"),
    reject_vram_spill: bool = False,
) -> dict[str, Any]:
    """Run one benchmark command under the resource monitor; return its row.

    Raise `RuntimeError` when a reserve is breached before launch. A breach,
    monitor failure or timeout during the run stops it and is the row's error.
    """
    monitor = Monitor(
        device_path=device_path,
        min_free_mib=min_free_mib,
        min_host_bytes=min_host_available_mib * 1024 * 1024,
        meminfo_path=meminfo_path,
        group=group,
        reject_vram_spill=reject_vram_spill,
    )
    monitor.check_before_launch()
    with (
        tempfile.TemporaryFile() as stdout_file,
        tempfile.TemporaryFile() as stderr_file,
    ):
        process = subprocess.Popen(
            group.command(command) if group is not None else command,
            stdout=stdout_file,
            stderr=stderr_file,
            env=env,
            start_new_session=True,
        )
        started = time.monotonic()
        try:
            failure = watch(process, monitor, started, timeout)
        finally:
            # Also reap our child if the operator interrupts the matrix.
            terminate(process)
        final_failure = monitor.final_sample()
        failure = failure or final_failure
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read().decode(errors="replace")
        stderr = stderr_file.read().decode(errors="replace")
    return {
        "returncode": process.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "elapsed_seconds": time.monotonic() - started,
        "peak_vram_used_mib": monitor.peak,
        "minimum_host_available_bytes": monitor.minimum_host,
        "sampled_group_peak_vram_bytes": monitor.sampled_group_peak if group else None,
        "sampled_drm_peaks": monitor.drm_peaks,
        **monitor.group_metrics,
        "error": failure,
    }


def watch(
    process: subprocess.Popen[bytes], monitor: Monitor, started: float, timeout: float
) -> str | None:
    """Sample until the process exits; return the failure that stopped it, if any."""
    while process.poll() is None:
        if failure := monitor.sample():
            return failure
        if time.monotonic() - started >= timeout:
            return f"timed out after {timeout:g} seconds"
        time.sleep(min(0.1, max(0.01, timeout / 100)))
    return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as model:
        for chunk in iter(lambda: model.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Variables that benchmark children inherit; everything else stays out.
INHERITED_ENVIRONMENT = (
    "PATH",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "XDG_RUNTIME_DIR",
    "VK_ICD_FILENAMES",
    "VK_DRIVER_FILES",
    "ROCR_VISIBLE_DEVICES",
    "HIP_VISIBLE_DEVICES",
    "GGML_VK_VISIBLE_DEVICES",
)
INTERRUPTED = 130


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark matrix and write its JSON document; return the status.

    The document is rewritten after every row, so an interrupted matrix
    keeps the rows that finished.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    validate(parser, args)
    model = args.model.resolve(strict=True)
    binary = (args.binary_prefix / "bin/llama-bench").resolve(strict=True)
    if not model.is_file() or not binary.is_file() or not os.access(binary, os.X_OK):
        parser.error("model must be a file and bin/llama-bench must be executable")
    server = (args.binary_prefix / "bin/llama-server").resolve(strict=True)
    if not server.is_file() or not os.access(server, os.X_OK):
        parser.error("bin/llama-server must be executable to record build version")
    env = child_environment(args.binary_prefix)
    version, group = read_version(server, args, env)
    rows: list[dict[str, Any]] = []
    data = result_document(args, model, binary, version, group is not None, rows)
    try:
        if not data.get("error"):
            run_matrix(args, binary, model, env, group, data, rows)
    except (OSError, ValueError, RuntimeError) as error:
        data["error"] = str(error)
    except KeyboardInterrupt:
        data["interrupted"] = True
    if not rows and not data.get("error") and not data.get("interrupted"):
        data["error"] = "no runnable benchmark configurations"
    args.output.write_text(json.dumps(data, indent=2) + "\n")
    return exit_status(data, rows)


def build_parser() -> argparse.ArgumentParser:
    """The benchmark's command-line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", required=True, type=Path, help="explicit GGUF model file"
    )
    parser.add_argument(
        "--binary-prefix", required=True, type=Path, help="llama.cpp install prefix"
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="explicit JSON result path"
    )
    parser.add_argument(
        "--devices",
        default="ROCm0,Vulkan0",
        type=lambda v: comma_values(v),
        help="device matrix",
    )
    parser.add_argument(
        "--batches", default="2048", type=lambda v: comma_values(v, int)
    )
    parser.add_argument("--ubatches", default="64", type=lambda v: comma_values(v, int))
    parser.add_argument("--caches", default="q8_0", type=lambda v: comma_values(v))
    parser.add_argument("--flash-attn", choices=["on", "off", "auto"], default="on")
    parser.add_argument("--threads", default="8", type=lambda v: comma_values(v, int))
    parser.add_argument(
        "--prompt-tokens", default="512,4096", type=lambda v: comma_values(v, int)
    )
    parser.add_argument("--generation-tokens", type=int, default=128)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument(
        "--gpu-layers", default="99", type=lambda v: comma_values(v, int)
    )
    parser.add_argument(
        "--cpu-moe-layers", default="0", type=lambda v: comma_values(v, int)
    )
    parser.add_argument(
        "--cgroup",
        type=Path,
        help="explicit empty delegated cgroup with dmem interfaces",
    )
    parser.add_argument(
        "--dmem-region", help="device memory region, such as drm/0000:03:00.0/vram"
    )
    parser.add_argument(
        "--max-vram-mib", type=int, help="kernel dmem limit for this experiment group"
    )
    parser.add_argument(
        "--reject-vram-spill",
        action="store_true",
        help="stop when DRM reports nonresident requested VRAM",
    )
    parser.add_argument("--min-host-available-mib", type=int, default=4096)
    parser.add_argument("--meminfo-path", type=Path, default=Path("/proc/meminfo"))
    parser.add_argument(
        "--depths",
        type=lambda v: comma_values(v, int),
        help="optional llama-bench depth values",
    )
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--min-free-mib", type=int, default=4096)
    parser.add_argument(
        "--device-path",
        required=True,
        type=Path,
        help="explicit GPU DRM device directory with VRAM sysfs counters",
    )
    return parser


def validate(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Reject inconsistent options; argparse exits with status 2."""
    if args.timeout <= 0 or args.min_free_mib < 0 or args.min_host_available_mib < 0:
        parser.error("timeout must be positive and memory reserves nonnegative")
    if (
        args.repetitions <= 0
        or args.generation_tokens < 0
        or any(value < 0 for value in args.prompt_tokens)
    ):
        parser.error("repetitions must be positive and token counts nonnegative")
    if not any(args.prompt_tokens) and not args.generation_tokens:
        parser.error("at least one prompt or generation test is required")
    validate_cgroup(parser, args)
    if (
        any(number <= 0 for number in args.batches + args.ubatches + args.threads)
        or any(number < 0 for number in args.gpu_layers + args.cpu_moe_layers)
        or (args.depths is not None and any(number < 0 for number in args.depths))
    ):
        parser.error(
            "batches, ubatches and threads must be positive; offload counts and depths must be nonnegative"
        )


def validate_cgroup(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Require the cgroup, region and limit together, and a DRM VRAM region."""
    limits = (args.cgroup, args.dmem_region, args.max_vram_mib)
    if any(value is not None for value in limits):
        if any(value is None for value in limits) or args.max_vram_mib <= 0:
            parser.error(
                "cgroup, dmem-region and positive max-vram-mib must be provided together"
            )
        if any(character.isspace() for character in args.dmem_region):
            parser.error("dmem-region must not contain whitespace")
        if not re.fullmatch(r"drm/[^/\s]+/vram\d*", args.dmem_region):
            parser.error("dmem-region must identify a DRM VRAM region")
    if args.reject_vram_spill and args.cgroup is None:
        parser.error("reject-vram-spill requires a monitored cgroup")


def child_environment(prefix: Path) -> dict[str, str]:
    """The environment of benchmark children, with the prefix's libraries."""
    lib_dirs = [
        str(prefix / part) for part in ("lib", "lib64") if (prefix / part).is_dir()
    ]
    env = {key: os.environ[key] for key in INHERITED_ENVIRONMENT if key in os.environ}
    env["LD_LIBRARY_PATH"] = ":".join(lib_dirs)
    return env


@dataclass(frozen=True)
class Version:
    """The output of `llama-server --version`, or why it could not be read."""

    returncode: int | None
    stdout: str
    stderr: str
    error: str | None


def read_version(
    server: Path, args: argparse.Namespace, env: dict[str, str]
) -> tuple[Version, DmemGroup | None]:
    """Prepare the experiment group, if any, and run `llama-server --version` in it.

    A group or version failure is recorded in the returned version.
    """
    group = None
    try:
        if args.cgroup is not None:
            group = DmemGroup(
                args.cgroup, args.dmem_region, args.max_vram_mib * 1024 * 1024
            )
            group.prepare()
        command = [str(server), "--version"]
        result = subprocess.run(
            group.command(command) if group is not None else command,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
    except subprocess.TimeoutExpired as error:
        message = f"could not read llama-server version: {error}"
        return Version(
            None, decoded(error.stdout), decoded(error.stderr), message
        ), group
    except (OSError, ValueError, RuntimeError) as error:
        message = f"could not read llama-server version: {error}"
        return Version(None, "", "", message), group
    return Version(result.returncode, result.stdout, result.stderr, None), group


def decoded(value: str | bytes | None) -> str:
    """Partial output of a timed-out process as text."""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""


def result_document(
    args: argparse.Namespace,
    model: Path,
    binary: Path,
    version: Version,
    grouped: bool,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """The JSON document that the benchmark writes; `rows` fills in as it runs."""
    data: dict[str, Any] = {
        "model": str(model),
        "model_sha256": sha256(model),
        "binary": str(binary),
        "binary_version": version.stdout.strip() or version.stderr.strip(),
        "binary_version_returncode": version.returncode,
        "binary_version_stdout": version.stdout,
        "binary_version_stderr": version.stderr,
        "parameters": vars_json(args),
        "resource_accounting": {
            "system_vram": "sampled aggregate, including desktop; not a process allocation limit",
            "group_vram": "dmem current; lifetime peak when available; sampled peaks are lower bounds; device enforcement requires separate qualification"
            if grouped
            else "unavailable",
        },
        "rows": rows,
    }
    if version.error:
        data["error"] = version.error
    elif version.returncode != 0:
        data["error"] = (
            f"llama-server --version failed with status {version.returncode}"
        )
    return data


def run_matrix(
    args: argparse.Namespace,
    binary: Path,
    model: Path,
    env: dict[str, str],
    group: DmemGroup | None,
    data: dict[str, Any],
    rows: list[dict[str, Any]],
) -> None:
    """Run each configuration and depth; stop at the first row with an error."""
    configurations = itertools.product(
        args.devices,
        args.batches,
        args.ubatches,
        args.caches,
        args.threads,
        args.gpu_layers,
        args.cpu_moe_layers,
    )
    for configuration in configurations:
        device, batch, ubatch, cache, threads, layers, cpu_moe_layers = configuration
        if ubatch > batch:
            continue
        for depth in args.depths or [None]:
            command = bench_command(args, binary, model, configuration, depth)
            print(
                f"Running {device} batch={batch} ubatch={ubatch} cache={cache} threads={threads} ngl={layers} ncmoe={cpu_moe_layers} depth={depth}",
                flush=True,
            )
            result = run_command(
                command,
                args.timeout,
                env,
                args.device_path,
                args.min_free_mib,
                group,
                args.min_host_available_mib,
                args.meminfo_path,
                args.reject_vram_spill,
            )
            row = {
                "device": device,
                "batch": batch,
                "ubatch": ubatch,
                "cache": cache,
                "flash_attn": args.flash_attn,
                "threads": threads,
                "gpu_layers": layers,
                "cpu_moe_layers": cpu_moe_layers,
                "prompt_tokens": args.prompt_tokens,
                "generation_tokens": args.generation_tokens,
                "repetitions": args.repetitions,
                "depth": depth,
                "command": command,
                **result,
            }
            row["parsed_metrics"] = parse_metrics(result["stdout"])
            rows.append(row)
            args.output.write_text(json.dumps(data, indent=2) + "\n")
            if result["error"]:
                return


def bench_command(
    args: argparse.Namespace,
    binary: Path,
    model: Path,
    configuration: tuple[str, int, int, str, int, int, int],
    depth: int | None,
) -> list[str]:
    """The llama-bench command line of one configuration and depth."""
    device, batch, ubatch, cache, threads, layers, cpu_moe_layers = configuration
    command = [
        str(binary),
        "-m",
        str(model),
        "-p",
        ",".join(str(value) for value in args.prompt_tokens),
        "-n",
        str(args.generation_tokens),
        "-r",
        str(args.repetitions),
        "-b",
        str(batch),
        "-ub",
        str(ubatch),
        "-ctk",
        cache,
        "-ctv",
        cache,
        "-t",
        str(threads),
        "-ngl",
        str(layers),
        "-dev",
        device,
        "-o",
        "json",
        "-fa",
        args.flash_attn,
    ]
    if depth is not None:
        command += ["-d", str(depth)]
    if cpu_moe_layers:
        command += ["--n-cpu-moe", str(cpu_moe_layers)]
    return command


def exit_status(data: dict[str, Any], rows: list[dict[str, Any]]) -> int:
    """130 when interrupted; 1 on any error, failed run or unparsed output."""
    if data.get("interrupted"):
        return INTERRUPTED
    failed = any(
        row.get("error")
        or row["returncode"] != 0
        or row["parsed_metrics"].get("parse_error")
        for row in rows
    )
    return 1 if data.get("error") or failed else 0


def vars_json(args: argparse.Namespace) -> dict[str, Any]:
    return {
        key: str(value) if isinstance(value, Path) else value
        for key, value in vars(args).items()
    }


if __name__ == "__main__":
    if len(sys.argv) >= 5 and sys.argv[1] == "--enter-cgroup" and sys.argv[3] == "--":
        with (Path(sys.argv[2]) / "cgroup.procs").open("w") as membership:
            membership.write(str(os.getpid()))
        os.execv(sys.argv[4], sys.argv[4:])
    sys.exit(main())
