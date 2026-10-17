#!/usr/bin/env python3
"""Run an explicit, opt-in llama-bench matrix and record its raw results."""

import argparse
import hashlib
import itertools
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
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
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_command(
    command: list[str],
    timeout: float,
    env: dict[str, str],
    device_path: Path,
    min_free_mib: int,
) -> dict[str, Any]:
    total, used = read_vram(device_path)
    if total - used < min_free_mib:
        raise RuntimeError(
            f"VRAM reserve breach before launch: {total - used} MiB free, {min_free_mib} MiB required"
        )
    with (
        tempfile.TemporaryFile() as stdout_file,
        tempfile.TemporaryFile() as stderr_file,
    ):
        process = subprocess.Popen(
            command,
            stdout=stdout_file,
            stderr=stderr_file,
            env=env,
            start_new_session=True,
        )
        started = time.monotonic()
        peak = used
        failure = None
        try:
            while process.poll() is None:
                try:
                    total, used = read_vram(device_path)
                    peak = max(peak, used)
                    if total - used < min_free_mib:
                        failure = f"VRAM reserve breach during run: {total - used} MiB free, {min_free_mib} MiB required"
                        break
                except (OSError, ValueError) as error:
                    failure = f"cannot read VRAM counters during run: {error}"
                    break
                if time.monotonic() - started >= timeout:
                    failure = f"timed out after {timeout:g} seconds"
                    break
                time.sleep(min(0.1, max(0.01, timeout / 100)))
        finally:
            # Also reap our child if the operator interrupts the matrix.
            if process.poll() is None:
                terminate(process)
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
        "--gpu-layers", default="99", type=lambda v: comma_values(v, int)
    )
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
    if args.timeout <= 0 or args.min_free_mib < 0:
        parser.error("timeout must be positive and min-free-mib nonnegative")
    model = args.model.resolve(strict=True)
    binary = (args.binary_prefix / "bin/llama-bench").resolve(strict=True)
    if not model.is_file() or not binary.is_file() or not os.access(binary, os.X_OK):
        parser.error("model must be a file and bin/llama-bench must be executable")
    if (
        any(number <= 0 for number in args.batches + args.ubatches + args.threads)
        or any(number < 0 for number in args.gpu_layers)
        or (args.depths is not None and any(number < 0 for number in args.depths))
    ):
        parser.error(
            "batches, ubatches and threads must be positive; gpu-layers and depths must be nonnegative"
        )
    lib_dirs = [
        str(args.binary_prefix / part)
        for part in ("lib", "lib64")
        if (args.binary_prefix / part).is_dir()
    ]
    env = os.environ.copy()
    env.pop("HF_TOKEN", None)
    env.pop("HUGGING_FACE_HUB_TOKEN", None)
    env["LD_LIBRARY_PATH"] = ":".join(
        lib_dirs + ([env["LD_LIBRARY_PATH"]] if env.get("LD_LIBRARY_PATH") else [])
    )
    server = (args.binary_prefix / "bin/llama-server").resolve(strict=True)
    if not server.is_file() or not os.access(server, os.X_OK):
        parser.error("bin/llama-server must be executable to record build version")
    version_error = None
    try:
        version = subprocess.run(
            [str(server), "--version"],
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
    except OSError as error:
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
    )
    try:
        for device, batch, ubatch, cache, threads, layers in configurations:
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
                    "512,4096",
                    "-n",
                    "128",
                    "-r",
                    "3",
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
                print(
                    f"Running {device} batch={batch} ubatch={ubatch} cache={cache} threads={threads} ngl={layers} depth={depth}",
                    flush=True,
                )
                result = run_command(
                    command, args.timeout, env, device_path, args.min_free_mib
                )
                row = {
                    "device": device,
                    "batch": batch,
                    "ubatch": ubatch,
                    "cache": cache,
                    "flash_attn": args.flash_attn,
                    "threads": threads,
                    "gpu_layers": layers,
                    "prompt_tokens": [512, 4096],
                    "generation_tokens": 128,
                    "repetitions": 3,
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
    sys.exit(main())
