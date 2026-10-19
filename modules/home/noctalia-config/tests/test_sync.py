# pyright: standard
"""Public operations against temporary homes and fake native/Nix commands."""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

spec = importlib.util.spec_from_file_location("sync", sys.argv.pop())
assert spec is not None and spec.loader is not None
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.repo, self.config, self.state = [
            root / n for n in ("repo", "config", "state")
        ]
        self.target = self.repo / "homes/test/noctalia/config.toml"
        self.target.parent.mkdir(parents=True)
        self.target.write_text('[theme]\nmode="dark"\n')
        self.config.mkdir()
        self.state.mkdir()
        self.settings = self.state / "settings.toml"
        self.control = root / "control"
        self.commands = []
        self.exported: dict[str, object] = {"theme": {"mode": "light"}}
        self.fail_build = self.fail_switch = self.running = self.mismatch = False
        self.built = None
        self.mutate_after_build = False
        self.validation_warning = False
        self.validation_output = None
        self.instance = sync.Sync(
            self.repo,
            "test",
            "test@host",
            self.config,
            self.state,
            self.control,
            self.run_fake,
        )
        self.instance.stopped = self.stopped

    def stopped(self):
        sync.require(not self.running, "Exit Noctalia")

    def run_fake(self, argv, env=None, cwd=None):
        self.commands.append(argv)
        if argv[0] == "git":
            return str(self.repo).encode() if "rev-parse" in argv else b"tracked"
        if argv[0] == "/usr/bin/noctalia":
            if len(argv) > 2 and argv[2] == "validate":
                sync.parse(Path(argv[3]).read_bytes())
                if self.validation_output is not None:
                    return self.validation_output
                return b"WARN fixture" if self.validation_warning else b"valid"
            return sync.encode(self.exported)
        if argv[:2] == ["/usr/bin/nix", "build"]:
            sync.require(not self.fail_build, "fake build failure")
            self.built = sync.parse(self.target.read_bytes())
            output = Path(argv[argv.index("--out-link") + 1])
            output.mkdir()
            (output / "activate").write_text("fixture")
            if self.mutate_after_build:
                (self.repo / "flake.nix").write_text("different composition")
                (self.repo / "flake.lock").write_text("different lock")
            return b""
        if Path(argv[0]).name == "activate":
            self.assertTrue(Path(argv[0]).exists())
            self.assertEqual(argv[1:], ["--driver-version", "0"])
            sync.require(not self.fail_switch, "fake activation failure")
            self.exported = (
                {}
                if self.mismatch
                else sync.merge(
                    self.built,
                    sync.parse(sync.read(self.settings)),
                )
            )
            return b""
        raise AssertionError("Unexpected command")

    def test_capture_filters_policy_and_review_sections(self):
        self.exported.update(
            {
                "storage": {"key_file": "/private/key"},
                "calendar": {"accounts": [{"password": "fixture"}]},
                "shell": {"command": "private fixture"},
                "future": {},
            }
        )
        self.instance.capture()
        self.assertEqual(
            sync.parse(self.target.read_bytes()), {"theme": {"mode": "light"}}
        )
        self.assertFalse(
            any(argv[:2] == ["/usr/bin/nix", "run"] for argv in self.commands)
        )

    def test_capture_includes_desktop_widgets(self):
        self.exported.update(
            {
                "desktop_widgets": {
                    "schema_version": 2,
                    "widget_order": ["desktop-widget-1"],
                    "widget": {
                        "desktop-widget-1": {
                            "type": "clock",
                            "settings": {"clock_style": "digital"},
                        }
                    },
                }
            }
        )
        self.instance.capture()
        captured = sync.parse(self.target.read_bytes())
        self.assertIn("desktop_widgets", captured)
        self.assertEqual(captured["desktop_widgets"]["schema_version"], 2)

    def test_wallpaper_is_reviewed_and_deployed_without_touching_other_state(self):
        wallpaper = {
            "enabled": True,
            "fill_mode": "crop",
            "default": {
                "path": "/home/test/Pictures/Wallpapers/Noctalia/moonlight.png"
            },
        }
        self.exported["wallpaper"] = wallpaper
        self.instance.capture()
        self.assertEqual(sync.parse(self.target.read_bytes())["wallpaper"], wallpaper)
        self.settings.write_text(
            '[wallpaper.default]\npath="/tmp/old.png"\n[weather]\ncity="fixture"\n'
        )
        with self.assertRaisesRegex(RuntimeError, "override conflicts"):
            self.instance.deploy()
        self.instance.deploy(replace=True)
        self.assertEqual(
            sync.parse(self.settings.read_bytes()), {"weather": {"city": "fixture"}}
        )
        self.assertEqual(self.exported["wallpaper"], wallpaper)

    def test_wallpaper_commands_are_excluded_from_capture(self):
        self.exported["wallpaper"] = {
            "default": {"path": "/tmp/moonlight.png"},
            "action": "exec fixture",
        }
        self.instance.capture()
        self.assertNotIn("wallpaper", sync.parse(self.target.read_bytes()))

    def test_capture_filters_desktop_widgets_with_review_keys(self):
        self.exported.update(
            {
                "desktop_widgets": {
                    "widget": {
                        "custom": {
                            "type": "custom",
                            "settings": {"command": "sh /tmp/run.sh"},
                        }
                    }
                }
            }
        )
        self.instance.capture()
        captured = sync.parse(self.target.read_bytes())
        self.assertNotIn("desktop_widgets", captured)

    def test_capture_repeat_is_idempotent(self):
        self.instance.capture()
        before = self.target.stat()
        self.instance.capture()
        self.assertEqual(before.st_mtime_ns, self.target.stat().st_mtime_ns)
        self.assertEqual(before.st_ino, self.target.stat().st_ino)

    def test_check_reports_uncaptured_sections_without_writing(self):
        before = self.target.read_bytes()
        self.exported["storage"] = {"key_file": "/private/key"}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertFalse(self.instance.check())
        self.assertIn("in: theme;", output.getvalue())
        self.assertNotIn("light", output.getvalue())
        self.assertNotIn("storage", output.getvalue())
        self.assertEqual(before, self.target.read_bytes())
        self.instance.capture()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(self.instance.check())

    def test_dry_runs_never_write_or_build(self):
        before = self.target.read_bytes()
        self.instance.capture(dry_run=True)
        self.instance.deploy(dry_run=True)
        self.assertEqual(before, self.target.read_bytes())
        self.assertFalse(self.control.exists())
        self.assertFalse(any(argv[0] == "/usr/bin/nix" for argv in self.commands))

    def test_conflict_refuses_before_build(self):
        self.settings.write_text('[theme]\nmode="light"\n')
        with self.assertRaisesRegex(RuntimeError, "override conflicts"):
            self.instance.deploy()
        self.assertFalse(self.control.exists())

    def test_replace_preserves_unowned_settings_and_backup(self):
        original = '[theme]\nmode="light"\n[weather]\ncity="fixture"\n'
        self.settings.write_text(original)
        self.instance.deploy(replace=True)
        self.assertEqual(
            sync.parse(self.settings.read_bytes()), {"weather": {"city": "fixture"}}
        )
        backups = list(self.control.glob("settings-*.toml"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), original)
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.instance.pending.exists())
        self.instance.deploy(replace=True)
        self.assertEqual(len(list(self.control.glob("settings-*.toml"))), 1)

    def test_running_shell_blocks_override_changes(self):
        self.settings.write_text('[theme]\nmode="light"\n')
        original = self.settings.read_bytes()
        self.running = True
        with self.assertRaisesRegex(RuntimeError, "Exit Noctalia"):
            self.instance.deploy(replace=True)
        self.assertEqual(original, self.settings.read_bytes())

    def test_build_failure_does_not_touch_overrides(self):
        self.settings.write_text('[theme]\nmode="light"\n')
        original = self.settings.read_bytes()
        self.fail_build = True
        with self.assertRaisesRegex(RuntimeError, "build failure"):
            self.instance.deploy(replace=True)
        self.assertEqual(original, self.settings.read_bytes())
        self.assertFalse(self.instance.pending.exists())

    def test_activation_failure_restores_override(self):
        self.settings.write_text('[theme]\nmode="light"\n')
        original = self.settings.read_bytes()
        self.fail_switch = True
        with self.assertRaisesRegex(RuntimeError, "activation failure"):
            self.instance.deploy(replace=True)
        self.assertEqual(original, self.settings.read_bytes())
        self.assertFalse(self.instance.pending.exists())

    def test_effective_mismatch_is_failure(self):
        self.mismatch = True
        with self.assertRaisesRegex(RuntimeError, "Effective preferences"):
            self.instance.deploy()

    def test_interrupt_recover_preserves_concurrent_edits(self):
        self.settings.write_text('[theme]\nmode="light"\n')
        original = self.settings.read_bytes()
        run = self.instance.run

        def interrupt(argv):
            if Path(argv[0]).name == "activate":
                raise KeyboardInterrupt()
            return run(argv)

        self.instance.run = interrupt
        with self.assertRaises(KeyboardInterrupt):
            self.instance.deploy(replace=True)
        self.assertTrue(self.instance.pending.exists())
        after = self.settings.read_bytes()
        self.settings.write_text('[theme]\nmode="changed"\n')
        with self.assertRaisesRegex(RuntimeError, "changed after interruption"):
            self.instance.deploy(recover=True)
        self.settings.write_bytes(after)
        self.instance.deploy(recover=True)
        self.assertEqual(original, self.settings.read_bytes())

    def test_symlinks_and_unmanaged_targets_are_rejected(self):
        (self.config / "config.toml").write_text("# unowned")
        with self.assertRaisesRegex(RuntimeError, "Home Manager link"):
            self.instance.deploy()
        self.target.unlink()
        self.target.symlink_to(self.config / "config.toml")
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            self.instance.capture()

    def test_validation_warnings_leave_repository_unchanged(self):
        self.validation_warning = True
        original = self.target.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "warnings"):
            self.instance.capture()
        self.assertEqual(original, self.target.read_bytes())

    def test_warning_reports_only_known_section_and_local_review_command(self):
        self.validation_output = (
            b'WARN  widget.private-label: unrecognized widget type "private-value"\n'
            b"WARN  private-section: private-value\n"
            b"Config is valid (2 warning(s))\n"
        )
        original = self.target.read_bytes()
        with self.assertRaises(RuntimeError) as error:
            self.instance.capture()
        message = str(error.exception)
        self.assertIn("sections: widget", message)
        self.assertIn("/usr/bin/noctalia config validate", message)
        self.assertNotIn("private-", message)
        self.assertEqual(original, self.target.read_bytes())

    def test_other_toml_ownership_is_not_overwritten(self):
        (self.config / "theme.toml").write_text('[theme]\nmode="light"\n')
        with self.assertRaisesRegex(RuntimeError, "Another TOML"):
            self.instance.deploy(replace=True)

    def test_activation_uses_built_artifact_after_other_source_changes(self):
        self.mutate_after_build = True
        self.instance.deploy()
        self.assertEqual(self.exported, self.built)
        builds = [c for c in self.commands if c[:2] == ["/usr/bin/nix", "build"]]
        self.assertEqual(len(builds), 1)
        self.assertIn("test@host", builds[0][-1])
        self.assertFalse(any(c[:2] == ["/usr/bin/nix", "run"] for c in self.commands))
        self.assertFalse(Path(builds[0][builds[0].index("--out-link") + 1]).exists())

    def test_input_overrides_reach_the_home_build(self):
        self.instance.overrides = ["--override-input", "nacre", "path:/src/nacre"]
        self.instance.deploy()
        (build,) = [c for c in self.commands if c[:2] == ["/usr/bin/nix", "build"]]
        position = build.index("--override-input")
        self.assertEqual(build[position : position + 3], self.instance.overrides)

    def test_capture_redacts_unknown_section_names(self):
        self.exported["private-account-name"] = {}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.instance.capture()
        self.assertNotIn("private-account-name", output.getvalue())
        self.assertIn("1 unsupported sections", output.getvalue())

    def test_activation_timeout_preserves_receipt_and_releases_lock(self):
        self.settings.write_text('[theme]\nmode="light"\n')
        original = self.settings.read_bytes()
        run = self.instance.run

        def timeout(argv):
            if Path(argv[0]).name == "activate":
                raise sync.CommandTimeout("fixture timeout")
            return run(argv)

        self.instance.run = timeout
        with self.assertRaises(sync.CommandTimeout):
            self.instance.deploy(replace=True)
        self.assertTrue(self.instance.pending.exists())
        self.instance.deploy(recover=True)
        self.assertEqual(self.settings.read_bytes(), original)

    def test_execute_timeout_kills_children_before_return_and_redacts(self):
        marker = self.control.parent / "late-write"
        script = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); print('private',flush=True); time.sleep(10)"
        child = f"import time; from pathlib import Path; time.sleep(.3); Path({str(marker)!r}).touch()"
        with (
            mock.patch.dict(sync.COMMAND_TIMEOUTS, {"query": 0.1}),
            self.assertRaises(sync.CommandTimeout) as raised,
        ):
            sync.execute([sys.executable, "-c", script, child])
        self.assertNotIn("private", str(raised.exception))
        time.sleep(0.4)
        self.assertFalse(marker.exists())

    def test_receipt_never_contains_override_values(self):
        self.settings.write_text('[theme]\nmode="light"\n')
        run = self.instance.run

        def interrupt(argv):
            if Path(argv[0]).name == "activate":
                raise KeyboardInterrupt()
            return run(argv)

        self.instance.run = interrupt
        with self.assertRaises(KeyboardInterrupt):
            self.instance.deploy(replace=True)
        receipt = json.loads(self.instance.pending.read_text())
        self.assertNotIn("light", json.dumps(receipt))


if __name__ == "__main__":
    unittest.main()
