# pyright: standard
"""Exercise the actual orchestration without host access or privilege."""

import fcntl
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

SOURCE = Path(sys.argv.pop()).resolve()
FAKE = Path(__file__).with_name("native.py")
CORE = ["python", "/fixture/core-adapter", "/fixture/core-manifest"]
SYSTEM = ["python", "/fixture/system-adapter", "/fixture/system-manifest"]


class ArchSwitchTests(unittest.TestCase):
    state: dict[str, Any]

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for name in ("usr/lib/modules/" + os.uname().release, "run/user/1000", "bin"):
            (self.root / name).mkdir(parents=True)
        (self.root / "etc").mkdir()
        (self.root / "etc/arch-release").touch()
        self.state = {"groups": ["wheel"]}
        self.save()
        for command in [
            "id",
            "sudo",
            "pacman",
            "pacman-conf",
            "yay",
            "systemctl",
            "curl",
            "bsdtar",
        ]:
            executable = self.root / "bin" / command
            executable.write_text(
                f"#!{sys.executable}\n" + FAKE.read_text().split("\n", 1)[1]
            )
            executable.chmod(0o755)
        self.config = {
            "fsRoot": str(self.root),
            "nativeBin": str(self.root / "bin"),
            "adapterPython": "/fixture/python",
            "adapters": {
                name: {
                    "adapter": f"/fixture/{slug}-adapter",
                    "manifest": f"/fixture/{slug}-manifest",
                }
                for name, slug in (
                    ("core", "core"),
                    ("system", "system"),
                    ("ai", "ai"),
                    ("extension", "extension"),
                )
            },
            "lizardbyteConf": "/fixture/lizardbyte.conf",
            "curl": str(self.root / "bin/curl"),
            "tar": str(self.root / "bin/bsdtar"),
            "expectedUser": "tester",
            "pacman": ["base"],
            "lizardbyte": ["sunshine"],
            "aur": ["extra"],
            "hold": [],
            "extensions": [
                {
                    "name": "extension",
                    "label": "fixture-service",
                    "requires": ["ai"],
                    "notReady": "fixture service is not prepared",
                }
            ],
            "userServices": ["openrazer-daemon.service"],
        }
        self.write_config()

    def write_config(self):
        (self.root / "config.json").write_text(json.dumps(self.config))

    def command(self, *args):
        return [
            sys.executable,
            str(SOURCE),
            "--config",
            str(self.root / "config.json"),
            *args,
        ]

    def save(self):
        (self.root / "state.json").write_text(json.dumps(self.state))

    def invoke(self, *args, code=0):
        result = subprocess.run(
            self.command(*args),
            text=True,
            capture_output=True,
            env={**os.environ, "ARCH_TEST_ROOT": str(self.root)},
        )
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.state = json.loads((self.root / "state.json").read_text())
        return result

    def commands(self):
        path = self.root / "commands.jsonl"
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )

    def index(self, predicate):
        return next(i for i, call in enumerate(self.commands()) if predicate(call))

    def adapter_phases(self, prefix):
        return [call[3] for call in self.commands() if call[:3] == prefix]

    def test_progress_marks_success_and_core_failure(self):
        result = self.invoke()
        self.assertRegex(
            result.stderr, r"\[done\] \[\d+/\d+\] Finish runtime convergence"
        )
        self.state["fail"] = ["python", "/fixture/core-adapter"]
        self.save()
        result = self.invoke(code=1)
        self.assertRegex(
            result.stderr, r"\[failed\] \[\d+/\d+\] Preflight core and optional modules"
        )
        self.assertNotRegex(
            result.stderr, r"\[done\] \[\d+/\d+\] Preflight core and optional modules"
        )

    def test_routine_runs_every_core_phase_in_order(self):
        self.invoke()
        self.assertEqual(
            self.adapter_phases(CORE),
            ["preflight", "repositories", "converge", "finish"],
        )
        self.assertLess(
            self.index(lambda call: call == [*SYSTEM, "converge"]),
            self.index(lambda call: call == [*CORE, "converge"]),
        )
        self.assertFalse(any(call[0] in ("yay", "curl") for call in self.commands()))

    def test_preflight_failure_precedes_packages_and_writes(self):
        for adapter in ("/fixture/core-adapter", "/fixture/system-adapter"):
            with self.subTest(adapter=adapter):
                (self.root / "commands.jsonl").unlink(missing_ok=True)
                self.state["fail"] = ["python", adapter]
                self.save()
                self.invoke("--update", code=1)
                self.assertEqual(self.adapter_phases(CORE)[1:], [])
                self.assertFalse(
                    any(
                        call[0] == "pacman" and "--sync" in call
                        for call in self.commands()
                    )
                )

    def test_update_orders_packages_between_preflight_and_convergence(self):
        self.invoke("--update")
        upgrade = self.index(
            lambda call: call[0] == "pacman" and "--sysupgrade" in call
        )
        aur = self.index(lambda call: call[:3] == ["yay", "--sync", "--needed"])
        self.assertLess(
            self.index(lambda call: call == [*SYSTEM, "preflight"]), upgrade
        )
        self.assertLess(
            self.index(lambda call: call == [*CORE, "repositories"]), upgrade
        )
        self.assertLess(upgrade, aur)
        self.assertLess(aur, self.index(lambda call: call == [*SYSTEM, "converge"]))

    def test_update_keeps_held_packages_but_installs_missing_ones(self):
        self.config["pacman"] = ["base", "kitty"]
        self.config["hold"] = ["kitty", "extra"]
        self.write_config()
        self.invoke("--update")
        upgrades = [
            call
            for call in self.commands()
            if call[0] == "pacman" and "--sysupgrade" in call
        ]
        self.assertEqual(len(upgrades), 2)  # resolution, then the upgrade
        for call in upgrades:
            self.assertEqual(call[call.index("--ignore") + 1], "kitty,extra")
            self.assertNotIn("kitty", call[call.index("--") :])
            self.assertIn("base", call[call.index("--") :])
        self.assertFalse(
            any(call[:3] == ["yay", "--sync", "--needed"] for call in self.commands())
        )

        (self.root / "commands.jsonl").unlink()
        self.state["missing"] = ["kitty", "extra"]
        self.save()
        self.invoke("--update")
        upgrade = self.commands()[
            self.index(
                lambda call: (
                    call[0] == "pacman"
                    and "--sysupgrade" in call
                    and "--print" not in call
                )
            )
        ]
        self.assertIn("kitty", upgrade[upgrade.index("--") :])
        self.assertIn(
            [
                "yay",
                "--sync",
                "--needed",
                "--noconfirm",
                "--ignore",
                "kitty,extra",
                "--",
                "extra",
            ],
            self.commands(),
        )

    def test_resolution_simulates_the_upgrade_and_reports_conflicts(self):
        self.invoke("--update")
        calls = self.commands()
        resolve = self.index(lambda call: call[0] == "pacman" and "--print" in call)
        self.assertIn("--sysupgrade", calls[resolve])
        refresh = self.index(lambda call: call[-2:] == ["--sync", "--refresh"])
        self.assertLess(refresh, resolve)
        (self.root / "commands.jsonl").unlink()
        self.state["resolve_conflict"] = True
        self.save()
        result = self.invoke("--update", code=1)
        self.assertIn("breaks dependency required by lib32-glibc", result.stderr)
        self.assertNotIn("repo.example", result.stderr)
        self.assertFalse(
            any(
                call[0] in ("pacman", "yay")
                and "--needed" in call
                and "--print" not in call
                for call in self.commands()
            )
        )

    def test_failed_upgrade_stops_before_aur_and_policy(self):
        for key, code in (("upgrade_failure", 1), ("kernel_upgrade", 75)):
            with self.subTest(key=key):
                (self.root / "commands.jsonl").unlink(missing_ok=True)
                self.state[key] = True
                self.save()
                self.invoke("--update", code=code)
                self.assertFalse(
                    any(
                        call[:3] == ["yay", "--sync", "--needed"]
                        for call in self.commands()
                    )
                )
                self.assertNotIn("converge", self.adapter_phases(CORE))
                self.state.pop(key)

    def test_missing_package_stops_before_adapters(self):
        self.state["missing"] = ["base"]
        self.save()
        self.invoke(code=3)
        self.assertTrue(all(call[0] in ("id", "pacman") for call in self.commands()))

    def test_multilib_package_requires_repository_before_update(self):
        self.state["no_multilib"] = True
        self.save()
        self.config["pacman"] = ["base", "lib32-fixture"]
        self.write_config()
        result = self.invoke("--update", code=1)
        self.assertIn("[multilib]", result.stderr)
        self.assertFalse(
            any(call[0] == "pacman" and "--sync" in call for call in self.commands())
        )

    def test_cli_rejects_invalid_modes_before_any_command(self):
        self.assertIn("usage: arch-switch", self.invoke("--help").stdout)
        for args in (
            ("--check", "--update"),
            ("--update", "--purge"),
            ("--plan", "--update"),
            ("--unknown",),
        ):
            with self.subTest(args=args):
                self.invoke(*args, code=2)
        self.assertEqual(self.commands(), [])

    def test_wrong_user_or_missing_admin_group_stops_after_identity(self):
        for key, value in (("user", "other"), ("groups", [])):
            with self.subTest(key=key):
                self.state[key] = value
                self.save()
                self.invoke(code=1)
                self.assertTrue(all(call[0] == "id" for call in self.commands()))
                self.state = {"groups": ["wheel"]}
                self.save()

    def test_check_only_queries_inventories(self):
        self.invoke("--check")
        self.assertTrue(
            all(
                call[0] in ("id", "pacman-conf", "pacman", "yay", "curl", "bsdtar")
                for call in self.commands()
            )
        )

    def test_lock_prevents_concurrent_deployment(self):
        with (self.root / "run/user/1000/nacre-arch.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.invoke(code=75)
        self.assertEqual(self.adapter_phases(CORE), [])

    def test_purge_withdraws_ai_then_system_then_core(self):
        self.invoke("--purge")
        self.assertEqual(
            [call for call in self.commands() if call[0] == "python"],
            [
                ["python", "/fixture/ai-adapter", "/fixture/ai-manifest", "purge"],
                [*SYSTEM, "purge"],
                [*CORE, "purge"],
            ],
        )
        self.assertFalse(any(call[0] in ("pacman", "yay") for call in self.commands()))

    def test_plan_reads_without_changing_anything(self):
        self.state["missing"] = ["extra"]
        self.save()
        result = self.invoke("--plan")
        self.assertIn("+ package extra (missing; installed by update)", result.stdout)
        self.assertIn("~ enable user service openrazer-daemon.service", result.stdout)
        self.assertEqual(self.adapter_phases(CORE), ["plan"])
        self.assertEqual(self.adapter_phases(SYSTEM), ["plan"])
        self.assertFalse(any(call[0] in ("yay", "curl") for call in self.commands()))
        self.assertFalse(
            any(call[0] == "pacman" and "--sync" in call for call in self.commands())
        )
        self.assertNotIn("user_services", self.state)

    def test_plan_fails_on_a_core_conflict(self):
        self.state["fail"] = ["python", "/fixture/core-adapter"]
        self.save()
        self.invoke("--plan", code=1)

    def test_user_services_are_enabled_once(self):
        self.invoke()
        self.assertEqual(self.state["user_services"], ["openrazer-daemon.service"])
        result = self.invoke()
        self.assertIn(
            "User services converged: 0 files updated, 0 runtime actions", result.stdout
        )
        self.assertEqual(self.state["user_services"], ["openrazer-daemon.service"])


if __name__ == "__main__":
    unittest.main()
