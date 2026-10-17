# pyright: standard
"""Execute the preparation controller against an isolated model directory."""

import fcntl
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(sys.argv.pop()).resolve()


def progress_preamble() -> str:
    shell = os.environ.get("PROGRESS_TEST_SHELL")
    renderer = os.environ.get("PROGRESS_TEST_RENDERER")
    if not shell or not renderer:
        raise unittest.SkipTest("set PROGRESS_TEST_SHELL and PROGRESS_TEST_RENDERER")
    return f"source {shlex.quote(shell)}\nprogress_renderer={shlex.quote(renderer)}\nprogress_base64=$(command -v base64)\n"


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = b"pinned model\n"
        self.model = self.root / "models/model.gguf"
        self.second_model = self.root / "models/second-model.gguf"
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        hf = fake_bin / "hf"
        hf.write_text(
            f"#!{shutil.which('sh')}\n"
            'local_dir=0; cache_dir=0; for arg in "$@"; do\n'
            '  case "$arg" in --local-dir) local_dir=1 ;; --cache-dir) cache_dir=1 ;; esac\n'
            "done\n"
            'if [ "$local_dir" = 1 ] && [ "$cache_dir" = 1 ]; then\n'
            '  echo "Cannot use both --local-dir and --cache-dir" >&2; exit 2\n'
            "fi\n"
            'file=$3; while [ "$1" != --local-dir ]; do shift; done\n'
            "shift; printf 'pinned model\\n' >\"$1/$file\"\n"
        )
        hf.chmod(0o755)
        text = SOURCE.read_text()
        # The isolated run must never contend for the host lock.
        self.assertIn("/run/lock/nacre-llama-prepare.lock", text)
        text = text.replace(
            "((EUID == 0)) || { report_error \"run llama-prepare as root (sudo nix --extra-experimental-features 'nix-command flakes' run .#llama-prepare)\"; exit 1; }",
            "true",
        ).replace("/run/lock/nacre-llama-prepare.lock", str(self.root / "prepare.lock"))
        text = text.replace(
            "mktemp -d /var/tmp/nacre-llama.XXXXXXXX",
            f"mktemp -d {self.root}/work.XXXXXXXX",
        )
        text = text.replace(
            "[[ -x /usr/bin/c++ && -x /opt/rocm/bin/hipcc && -f /usr/include/vulkan/vulkan.h ]] || {\n"
            "    report_error 'native C++, ROCm, or Vulkan development toolchain is missing'; exit 1;\n"
            "  }",
            "true",
        )
        text = text.replace(" -o0 -g0", "")
        text = text.replace('chown 0:0 "$receipt_stage"', "true")
        digest = hashlib.sha256(self.payload).hexdigest()
        preamble = (
            "set -euo pipefail\n"
            + progress_preamble()
            + f"""
source_repository=unused
source_revision={"0" * 40}
grammar_threshold=20000
install_prefix={self.root / "opt"}
model_repositories=(example/model example/second-model)
model_revisions=({"1" * 40} {"1" * 40})
model_files=(model.gguf second-model.gguf)
model_paths=({self.model} {self.second_model})
model_sha256s=({digest} {digest})
"""
        )
        self.script = self.root / "prepare"
        self.script.write_text(preamble + text)
        self.env = os.environ | {"PATH": f"{fake_bin}:{os.environ['PATH']}"}

    def invoke(self, mode="--model-only"):
        return subprocess.run(
            ["bash", str(self.script), mode],
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )

    def test_installs_and_verified_repeat_is_quiet(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.model.read_bytes(), self.payload)
        self.assertEqual(self.second_model.read_bytes(), self.payload)
        self.assertEqual(self.model.stat().st_mode & 0o777, 0o644)
        self.assertTrue(Path(str(self.model) + ".nix-config-receipt").is_file())
        self.assertIn("[done] Verify model 1 of 2", result.stderr)
        self.assertIn("[done] Publish receipt for model 2 of 2", result.stderr)
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("[start] Download", result.stderr)
        self.assertIn("[done] Check model 1 of 2", result.stderr)

    def test_resumes_matching_stage_from_failed_download(self):
        download_dir = self.model.parent / ".nix-config-model.gguf.download"
        download_dir.mkdir(parents=True)
        digest = hashlib.sha256(self.payload).hexdigest()
        (download_dir / "nix-config-identity").write_text(
            f"example/model\n{'1' * 40}\nmodel.gguf\n{digest}\n"
        )
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.model.read_bytes(), self.payload)
        self.assertTrue(Path(str(self.model) + ".nix-config-receipt").is_file())

    def test_refuses_resume_stage_with_different_identity(self):
        download_dir = self.model.parent / ".nix-config-model.gguf.download"
        download_dir.mkdir(parents=True)
        identity = download_dir / "nix-config-identity"
        identity.write_text("different declaration\n")
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("model download stage has a different declaration", result.stderr)
        self.assertEqual(identity.read_text(), "different declaration\n")
        self.assertFalse(self.model.exists())

    def test_refuses_checksum_mismatch_without_overwrite(self):
        self.model.parent.mkdir()
        self.model.write_text("unowned\n")
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.model.read_text(), "unowned\n")

    def test_refuses_model_symlink(self):
        target = self.root / "unowned"
        target.write_text("keep\n")
        self.model.parent.mkdir()
        self.model.symlink_to(target)
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertEqual(target.read_text(), "keep\n")

    def test_failed_download_checksum_never_creates_final_target(self):
        text = self.script.read_text().replace(
            hashlib.sha256(self.payload).hexdigest(), "f" * 64
        )
        self.script.write_text(text)
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[failed] Verify model 1 of 2", result.stderr)
        self.assertNotIn("[done] Verify", result.stderr)
        self.assertNotIn("[start] Publish", result.stderr)
        self.assertFalse(self.model.exists())

    def test_existing_owned_revision_selects_current_and_repeats(self):
        revision = self.root / "opt/revisions" / ("0" * 40 + "-20000")
        (revision / "bin").mkdir(parents=True)
        server = revision / "bin/llama-server"
        server.write_text("binary")
        server.chmod(0o755)
        (revision / "nix-config-build").write_text(f"{'0' * 40} 20000\n")
        result = self.invoke("--build-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        current = self.root / "opt/current"
        self.assertEqual(os.readlink(current), f"revisions/{'0' * 40}-20000")
        result = self.invoke("--build-only")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_refuses_symlink_revision_and_contended_lock(self):
        revisions = self.root / "opt/revisions"
        revisions.mkdir(parents=True)
        (revisions / ("0" * 40 + "-20000")).symlink_to(self.root)
        self.assertNotEqual(self.invoke("--build-only").returncode, 0)
        (revisions / ("0" * 40 + "-20000")).unlink()
        lock = self.enterContext(open(self.root / "prepare.lock", "w"))
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(self.invoke().returncode, 75)


if __name__ == "__main__":
    unittest.main()
