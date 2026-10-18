"""llama-prepare: build the pinned llama.cpp and fetch the declared models.

Runs as root outside deployment. Builds and models are published atomically
next to receipts that deployment verifies. package.nix supplies the declared
artifacts as JSON; tests supply their own paths, lock and identity checks.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import TypedDict

from nix_adapter import Progress

USAGE = "usage: llama-prepare [--build-only | --model-only]"
ROOT_HINT = (
    "run llama-prepare as root "
    "(sudo nix --extra-experimental-features 'nix-command flakes' run .#llama-prepare)"
)
REVIEWED_THRESHOLD = "#define MAX_REPETITION_THRESHOLD 2000"


class Source(TypedDict):
    repository: str
    revision: str
    grammarThreshold: int
    installPrefix: str


class Model(TypedDict):
    repository: str
    revision: str
    file: str
    path: str
    sha256: str


class Config(TypedDict):
    source: Source
    models: list[Model]
    lock: str
    workBase: str
    # Production checks these; isolated tests turn them off.
    requireRoot: bool
    checkToolchain: bool
    rootOwnership: bool


class Failure(Exception):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Prepare:
    def __init__(self, config: Config, progress: Progress, work: Path):
        self.config = config
        self.progress = progress
        self.work = work

    def run(self, *argv: str) -> None:
        with self.progress.external_output():
            result = subprocess.run(argv, check=False)
        if result.returncode != 0:
            raise Failure(f"command failed ({result.returncode}): {argv[0]}")

    def own(self, path: Path) -> None:
        if self.config["rootOwnership"]:
            os.chown(path, 0, 0)

    def directory(self, path: Path, mode: int) -> None:
        path.mkdir(mode=mode, parents=True, exist_ok=True)
        self.own(path)

    def build(self) -> None:
        source = self.config["source"]
        if self.config["checkToolchain"] and not (
            os.access("/usr/bin/c++", os.X_OK)
            and os.access("/opt/rocm/bin/hipcc", os.X_OK)
            and Path("/usr/include/vulkan/vulkan.h").is_file()
        ):
            raise Failure(
                "native C++, ROCm, or Vulkan development toolchain is missing"
            )
        prefix = Path(source["installPrefix"])
        name = f"{source['revision']}-{source['grammarThreshold']}"
        revision = prefix / "revisions" / name
        receipt_text = f"{source['revision']} {source['grammarThreshold']}"
        if revision.is_symlink():
            raise Failure("revision path must not be a symlink")
        if revision.exists():
            with self.progress.task("Select cached llama.cpp build"):
                receipt = revision / "nix-config-build"
                if not (
                    receipt.is_file()
                    and receipt.read_text().strip() == receipt_text
                    and os.access(revision / "bin/llama-server", os.X_OK)
                ):
                    raise Failure(
                        "existing llama.cpp revision directory is not owned by this declaration"
                    )
                self.select(prefix, name)
            return
        with self.progress.task("Build llama.cpp", total=5) as task:
            checkout = self.work / "llama.cpp"
            self.run(
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                "--",
                source["repository"],
                str(checkout),
            )
            task.update(1)
            self.run(
                "git", "-C", str(checkout), "checkout", "--detach", source["revision"]
            )
            grammar = checkout / "src/llama-grammar.cpp"
            text = grammar.read_text()
            if text.splitlines().count(REVIEWED_THRESHOLD) != 1:
                raise Failure(
                    "pinned source no longer contains the reviewed grammar threshold"
                )
            grammar.write_text(
                text.replace(
                    REVIEWED_THRESHOLD,
                    f"#define MAX_REPETITION_THRESHOLD {source['grammarThreshold']}",
                )
            )
            task.update(2)
            self.run(
                "cmake",
                "-S",
                str(checkout),
                "-B",
                str(self.work / "build"),
                "-G",
                "Ninja",
                "-DCMAKE_BUILD_TYPE=Release",
                f"-DCMAKE_INSTALL_PREFIX={self.work / 'install'}",
                "-DVulkan_INCLUDE_DIR=/usr/include",
                "-DVulkan_LIBRARY=/usr/lib/libvulkan.so",
                "-DGGML_HIP=ON",
                "-DGGML_VULKAN=ON",
                "-DLLAMA_CURL=ON",
            )
            task.update(3)
            self.run(
                "cmake", "--build", str(self.work / "build"), "--target", "install"
            )
            stage = prefix / "revisions" / f".nix-config-{name}"
            self.directory(prefix / "revisions", 0o755)
            if stage.exists() or stage.is_symlink():
                raise Failure(
                    "stale llama.cpp preparation stage requires operator review"
                )
            task.update(4)
            shutil.copytree(self.work / "install", stage, symlinks=True)
            if self.config["rootOwnership"]:
                for path in (stage, *stage.rglob("*")):
                    os.chown(path, 0, 0, follow_symlinks=False)
            (stage / "nix-config-build").write_text(receipt_text + "\n")
            (stage / "nix-config-build").chmod(0o644)
            stage.rename(revision)
            self.select(prefix, name)
            task.update(5)

    def select(self, prefix: Path, name: str) -> None:
        """Point current at the revision, refusing a selector another owner made."""
        current = prefix / "current"
        desired = f"revisions/{name}"
        if current.is_symlink():
            link = os.readlink(current)
            if not current.is_dir():
                raise Failure("current llama.cpp selector is dangling")
            if link == desired:
                return
            if not re.fullmatch(r"revisions/[0-9a-f]{40}-[0-9]+", link):
                raise Failure("existing current link is not owned by llama-prepare")
        elif current.exists():
            raise Failure("existing current path is not owned by llama-prepare")
        stage = prefix / f".current-{name}"
        stage.unlink(missing_ok=True)
        stage.symlink_to(desired)
        stage.replace(current)

    def models(self) -> None:
        models = self.config["models"]
        for index, model in enumerate(models, start=1):
            self.model(model, f"model {index} of {len(models)}")

    def model(self, model: Model, label: str) -> None:
        path = Path(model["path"])
        identity = "".join(
            f"{model[key]}\n" for key in ("repository", "revision", "file", "sha256")
        )
        with self.progress.task(f"Check {label}"):
            if path.is_symlink():
                raise Failure("model path must not be a symlink")
            current = sha256(path) if path.is_file() else None
            if current is not None and current != model["sha256"]:
                raise Failure(
                    "existing model checksum differs; preserve or relocate it before preparation"
                )
        downloaded: Path | None = None
        download = path.parent / f".nix-config-{model['file']}.download"
        if current is None:
            with self.progress.task(f"Download {label}"):
                if path.parent.is_symlink():
                    raise Failure("model directory must not be a symlink")
                self.directory(path.parent, 0o755)
                stage = path.parent / f".nix-config-{model['file']}"
                if stage.exists() or stage.is_symlink():
                    raise Failure(
                        "stale model preparation stage requires operator review"
                    )
                marker = download / "nix-config-identity"
                if download.exists() or download.is_symlink():
                    if not download.is_dir() or download.is_symlink():
                        raise Failure("model download stage must be a directory")
                    if not marker.is_file() or marker.read_text() != identity:
                        raise Failure(
                            "model download stage has a different declaration"
                        )
                else:
                    self.directory(download, 0o700)
                    marker.write_text(identity)
                    marker.chmod(0o600)
                self.run(
                    "hf",
                    "download",
                    model["repository"],
                    model["file"],
                    "--revision",
                    model["revision"],
                    "--local-dir",
                    str(download),
                )
                downloaded = download / model["file"]
                if not downloaded.is_file() or downloaded.is_symlink():
                    raise Failure(
                        "Hugging Face download did not produce the declared file"
                    )
            with self.progress.task(f"Verify {label}"):
                if sha256(downloaded) != model["sha256"]:
                    raise Failure(
                        "downloaded model checksum does not match the declaration"
                    )
        with self.progress.task(f"Publish receipt for {label}"):
            if downloaded is not None:
                downloaded.chmod(0o644)
                downloaded.replace(path)
                shutil.rmtree(download)
            info = path.stat()
            fingerprint = ":".join(
                str(value)
                for value in (
                    info.st_dev,
                    info.st_ino,
                    info.st_size,
                    int(info.st_mtime),
                    int(info.st_ctime),
                )
            )
            receipt = Path(f"{path}.nix-config-receipt")
            stage = Path(f"{receipt}.stage")
            if receipt.is_symlink() or stage.is_symlink():
                raise Failure("model receipt path must not be a symlink")
            stage.write_text(identity + fingerprint + "\n")
            stage.chmod(0o644)
            self.own(stage)
            stage.replace(receipt)


@contextlib.contextmanager
def locked(path: str) -> Generator[None]:
    with open(path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Failure("another llama-prepare is running", 75) from None
        yield


def main(argv: list[str]) -> int:
    if argv[:1] != ["--config"] or len(argv) < 2:
        print("llama-prepare must be started through its package", file=sys.stderr)
        return 2
    config: Config = json.loads(Path(argv[1]).read_text())
    modes = {"": "all", "--build-only": "build", "--model-only": "model"}
    option = argv[2] if len(argv) > 2 else ""
    if option == "--help":
        print(USAGE)
        return 0
    if len(argv) > 3 or option not in modes:
        print(USAGE, file=sys.stderr)
        return 2
    mode = modes[option]
    with Progress(f"AI preparation ({mode})") as progress:
        try:
            if config["requireRoot"] and os.geteuid() != 0:
                raise Failure(ROOT_HINT)
            with (
                locked(config["lock"]),
                tempfile.TemporaryDirectory(
                    prefix="nacre-llama.", dir=config["workBase"]
                ) as work,
            ):
                prepare = Prepare(config, progress, Path(work))
                if mode in ("all", "build"):
                    prepare.build()
                if mode in ("all", "model"):
                    prepare.models()
            print("llama.cpp preparation complete")
            return 0
        except Failure as failure:
            with progress.external_output():
                print(str(failure), file=sys.stderr)
            return failure.code
        except KeyboardInterrupt:
            return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
