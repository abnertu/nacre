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
    """Read this group's clients and deduplicate shared DRM descriptors."""
    clients: dict[tuple[str, str], dict[str, int]] = {}
    memberships = [group / "cgroup.procs", *group.glob("**/cgroup.procs")]
    pids = {
        int(line)
        for membership in memberships
        for line in membership.read_text().splitlines()
    }
    for pid in pids:
        try:
            descriptors = list((proc_root / str(pid) / "fdinfo").iterdir())
        except FileNotFoundError:
            continue
        for descriptor in descriptors:
            try:
                fields = dict(
                    line.split(":", 1)
                    for line in descriptor.read_text().splitlines()
                    if line.startswith("drm-")
                )
            except (FileNotFoundError, ProcessLookupError):
                continue
            fields = {key: value.strip() for key, value in fields.items()}
            if fields.get("drm-pdev") != pci or "drm-client-id" not in fields:
                continue
            identity = fields["drm-pdev"], fields["drm-client-id"]
            counters: dict[str, int] = {}
            for kind in ("vram", "gtt"):
                resident = fields.get(
                    f"drm-resident-{kind}", fields.get(f"drm-memory-{kind}")
                )
                total = fields.get(f"drm-total-{kind}")
                if resident is not None:
                    counters[f"drm_resident_{kind}_bytes"] = drm_bytes(resident)
                if total is not None:
                    counters[f"drm_requested_{kind}_bytes"] = drm_bytes(total)
            previous = clients.setdefault(identity, {})
            for key, amount in counters.items():
                previous[key] = max(previous.get(key, 0), amount)
    combined: dict[str, int] = {"drm_client_count": len(clients)}
    for counters in clients.values():
        for key, amount in counters.items():
            combined[key] = combined.get(key, 0) + amount
    combined["drm_nonresident_vram_bytes"] = sum(
        max(
            0,
            counters.get("drm_requested_vram_bytes", 0)
            - counters.get("drm_resident_vram_bytes", 0),
        )
        for counters in clients.values()
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
    total, used = read_vram(device_path)
    if total - used < min_free_mib:
        raise RuntimeError(
            f"VRAM reserve breach before launch: {total - used} MiB free, {min_free_mib} MiB required"
        )
    if group is not None:
        group.prepare()
    initial_host = host_available(meminfo_path)
    if initial_host < min_host_available_mib * 1024 * 1024:
        raise RuntimeError("host memory reserve breach before launch")
    group_metrics: dict[str, int] = {}
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
        peak = used
        sampled_group_peak = 0
        drm_peaks: dict[str, int] = {}
        minimum_host = initial_host
        failure = None
        try:
            while process.poll() is None:
                try:
                    total, used = read_vram(device_path)
                    peak = max(peak, used)
                    minimum_host = min(minimum_host, host_available(meminfo_path))
                    if minimum_host < min_host_available_mib * 1024 * 1024:
                        failure = "host memory reserve breach during run"
                        break
                    if group is not None:
                        group_metrics = group.sample()
                        sampled_group_peak = max(
                            sampled_group_peak, group_metrics["current_vram_bytes"]
                        )
                        for key, amount in group_metrics.items():
                            if key.startswith("drm_"):
                                drm_peaks[key] = max(drm_peaks.get(key, 0), amount)
                        if reject_vram_spill and group_metrics.get(
                            "drm_nonresident_vram_bytes", 0
                        ):
                            failure = (
                                "requested VRAM became nonresident; reject driver spill"
                            )
                            break
                    if total - used < min_free_mib:
                        failure = f"VRAM reserve breach during run: {total - used} MiB free, {min_free_mib} MiB required"
                        break
                except (OSError, ValueError, RuntimeError) as error:
                    failure = f"resource monitor failed during run: {error}"
                    break
                if time.monotonic() - started >= timeout:
                    failure = f"timed out after {timeout:g} seconds"
                    break
                time.sleep(min(0.1, max(0.01, timeout / 100)))
        finally:
            # Also reap our child if the operator interrupts the matrix.
            terminate(process)
        try:
            total, used = read_vram(device_path)
            peak = max(peak, used)
            minimum_host = min(minimum_host, host_available(meminfo_path))
            if group is not None:
                group_metrics = group.sample()
                sampled_group_peak = max(
                    sampled_group_peak, group_metrics["current_vram_bytes"]
                )
            if minimum_host < min_host_available_mib * 1024 * 1024:
                failure = failure or "host memory reserve breach after run"
        except (OSError, ValueError, RuntimeError) as error:
            failure = failure or f"resource monitor failed after run: {error}"
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read().decode(errors="replace")
        stderr = stderr_file.read().decode(errors="replace")
    return {
        "returncode": process.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "elapsed_seconds": time.monotonic() - started,
        "peak_vram_used_mib": peak,
        "minimum_host_available_bytes": minimum_host,
        "sampled_group_peak_vram_bytes": sampled_group_peak if group else None,
        "sampled_drm_peaks": drm_peaks,
        **group_metrics,
        "error": failure,
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as model:
        for chunk in iter(lambda: model.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
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
    args = parser.parse_args(argv)
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
    if any(
        value is not None
        for value in (args.cgroup, args.dmem_region, args.max_vram_mib)
    ):
        if (
            any(
                value is None
                for value in (args.cgroup, args.dmem_region, args.max_vram_mib)
            )
            or args.max_vram_mib <= 0
        ):
            parser.error(
                "cgroup, dmem-region and positive max-vram-mib must be provided together"
            )
        if any(character.isspace() for character in args.dmem_region):
            parser.error("dmem-region must not contain whitespace")
        if not re.fullmatch(r"drm/[^/\s]+/vram\d*", args.dmem_region):
            parser.error("dmem-region must identify a DRM VRAM region")
    if args.reject_vram_spill and args.cgroup is None:
        parser.error("reject-vram-spill requires a monitored cgroup")
    model = args.model.resolve(strict=True)
    binary = (args.binary_prefix / "bin/llama-bench").resolve(strict=True)
    if not model.is_file() or not binary.is_file() or not os.access(binary, os.X_OK):
        parser.error("model must be a file and bin/llama-bench must be executable")
    if (
        any(number <= 0 for number in args.batches + args.ubatches + args.threads)
        or any(number < 0 for number in args.gpu_layers + args.cpu_moe_layers)
        or (args.depths is not None and any(number < 0 for number in args.depths))
    ):
        parser.error(
            "batches, ubatches and threads must be positive; offload counts and depths must be nonnegative"
        )
    lib_dirs = [
        str(args.binary_prefix / part)
        for part in ("lib", "lib64")
        if (args.binary_prefix / part).is_dir()
    ]
    allowed = (
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
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env["LD_LIBRARY_PATH"] = ":".join(lib_dirs)
    server = (args.binary_prefix / "bin/llama-server").resolve(strict=True)
    if not server.is_file() or not os.access(server, os.X_OK):
        parser.error("bin/llama-server must be executable to record build version")
    version_error = None
    group = None
    try:
        if args.cgroup is not None:
            group = DmemGroup(
                args.cgroup, args.dmem_region, args.max_vram_mib * 1024 * 1024
            )
            group.prepare()
        version_command = [str(server), "--version"]
        version = subprocess.run(
            group.command(version_command) if group is not None else version_command,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        version_returncode = version.returncode
        version_stdout = version.stdout
        version_stderr = version.stderr
    except subprocess.TimeoutExpired as error:
        version_returncode = None
        version_stdout = (
            error.stdout.decode(errors="replace")
            if isinstance(error.stdout, bytes)
            else (error.stdout or "")
        )
        version_stderr = (
            error.stderr.decode(errors="replace")
            if isinstance(error.stderr, bytes)
            else (error.stderr or "")
        )
        version_error = f"could not read llama-server version: {error}"
    except (OSError, ValueError, RuntimeError) as error:
        version_returncode = None
        version_stdout = ""
        version_stderr = ""
        version_error = f"could not read llama-server version: {error}"
    rows: list[dict[str, Any]] = []
    data: dict[str, Any] = {
        "model": str(model),
        "model_sha256": sha256(model),
        "binary": str(binary),
        "binary_version": version_stdout.strip() or version_stderr.strip(),
        "binary_version_returncode": version_returncode,
        "binary_version_stdout": version_stdout,
        "binary_version_stderr": version_stderr,
        "parameters": vars_json(args),
        "resource_accounting": {
            "system_vram": "sampled aggregate, including desktop; not a process allocation limit",
            "group_vram": "dmem current; lifetime peak when available; sampled peaks are lower bounds; device enforcement requires separate qualification"
            if group
            else "unavailable",
        },
        "rows": rows,
    }
    if version_error:
        data["error"] = version_error
    elif version_returncode != 0:
        data["error"] = (
            f"llama-server --version failed with status {version_returncode}"
        )
    device_path = args.device_path
    configurations = itertools.product(
        args.devices,
        args.batches,
        args.ubatches,
        args.caches,
        args.threads,
        args.gpu_layers,
        args.cpu_moe_layers,
    )
    try:
        for (
            device,
            batch,
            ubatch,
            cache,
            threads,
            layers,
            cpu_moe_layers,
        ) in configurations:
            if data.get("error"):
                break
            if ubatch > batch:
                continue
            depths = args.depths or [None]
            for depth in depths:
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
                print(
                    f"Running {device} batch={batch} ubatch={ubatch} cache={cache} threads={threads} ngl={layers} ncmoe={cpu_moe_layers} depth={depth}",
                    flush=True,
                )
                result = run_command(
                    command,
                    args.timeout,
                    env,
                    device_path,
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
                    break
            if rows and rows[-1].get("error"):
                break
    except (OSError, ValueError, RuntimeError) as error:
        data["error"] = str(error)
    except KeyboardInterrupt:
        data["interrupted"] = True
    if not rows and not data.get("error") and not data.get("interrupted"):
        data["error"] = "no runnable benchmark configurations"
    args.output.write_text(json.dumps(data, indent=2) + "\n")
    if data.get("interrupted"):
        return 130
    return (
        1
        if data.get("error")
        or any(
            row.get("error")
            or row["returncode"] != 0
            or row["parsed_metrics"].get("parse_error")
            for row in rows
        )
        else 0
    )


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
