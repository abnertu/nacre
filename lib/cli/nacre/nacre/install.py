"""install: write configuration.nix for this machine, then plan and update."""

from __future__ import annotations

import json
import os
import pwd
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from .common import NAME, Refusal, Usage, query
from .deploy import deploy
from .machine import Machine

# The machine flake template: flake.nix and configuration.nix. Packaging
# substitutes the store path.
TEMPLATES = Path("@templates@")
RUNNER_PUBLIC_FILES = Path("@runner-public-files@")


class Installer:
    """Write configuration.nix for this machine, then plan and update."""

    def __init__(self, machine: Machine, args: Sequence[str]):
        self.machine = machine
        self.root = Path(os.environ.get("NACRE_INSTALL_ROOT") or "/")
        hostname_file = self.root / "etc/hostname"
        self.values = {
            # USER is unset under podman exec, cron and su without a login.
            "user": os.environ.get("USER") or pwd.getpwuid(os.getuid()).pw_name,
            "hostname": (
                hostname_file.read_text().strip()
                if hostname_file.is_file()
                else os.uname().nodename
            ),
            "role": "workstation",
            "timezone": query("timedatectl", "show", "--property=Timezone", "--value")
            or "UTC",
            "locale": os.environ.get("LANG", "en_US.UTF-8").replace(".utf8", ".UTF-8"),
        }
        self.yes = self.force = False
        self.runner_configs: list[Path] = []
        self.runner_source: Path | None = None
        self.runner_markers: list[Path] = []
        rest = list(args)
        while rest:
            option = rest.pop(0)
            if option in ("--user", "--hostname", "--role", "--timezone", "--locale"):
                if not rest:
                    raise Usage
                self.values[option[2:]] = rest.pop(0)
            elif option == "--yes":
                self.yes = True
            elif option == "--runner-config":
                if not rest:
                    raise Usage
                self.runner_configs.append(Path(rest.pop(0)).absolute())
            elif option == "--force":
                self.force = True
            else:
                raise Usage

    def run(self) -> int:
        """Ask for missing values, write the files, plan, and update on consent."""
        interactive = sys.stdin.isatty()
        if not self.yes and interactive:
            self.ask()
        content = self.render()
        runner = self.capture_runner_files()
        self.write_configuration(content.replace("@runner@", runner))
        status = deploy(self.machine, "plan")
        if status != 0:
            return status
        if not self.yes and not self.confirmed(interactive):
            print("Not applied. Run nacre update when ready.", file=sys.stderr)
            return 0
        return deploy(self.machine, "update")

    def ask(self) -> None:
        """Let the operator replace each detected value."""
        for key in ("user", "hostname", "role", "timezone", "locale"):
            answer = input(f"{key} [{self.values[key]}]: ").strip()
            if answer:
                self.values[key] = answer

    @staticmethod
    def confirmed(interactive: bool) -> bool:
        """Whether the operator agrees to apply the plan; never without a terminal."""
        if not interactive:
            return False
        answer = input("Apply this plan with nacre update? [y/N] ")
        return answer.lower().startswith("y")

    def write_configuration(self, content: str) -> None:
        """Write configuration.nix, and create the machine flake if it is new.

        Raise `Refusal` instead of overwriting uncommitted changes, unless
        `--force` was given.
        """
        flake = self.machine.flake
        target = flake / "configuration.nix"
        created = not (flake / "flake.nix").exists()
        if not created and target.exists() and not self.force and self.uncommitted():
            raise Refusal(
                "configuration.nix has uncommitted changes; commit them or pass --force"
            )
        self.check_runner_destination()
        if created:
            # A new machine flake that follows Nacre; Git tracks it so Nix sees it.
            flake.mkdir(parents=True, exist_ok=True)
            (flake / "flake.nix").write_text((TEMPLATES / "flake.nix").read_text())
        runner_files = self.copy_runner_files()
        target.write_text(content + "\n")
        if created:
            for args in (
                ["init", "--quiet"],
                ["add", "flake.nix", "configuration.nix"],
            ):
                subprocess.run(["git", "-C", str(flake), *args], check=True)
        if runner_files:
            subprocess.run(
                [
                    "git",
                    "--literal-pathspecs",
                    "-C",
                    str(flake),
                    "add",
                    "--",
                    "configuration.nix",
                    *runner_files,
                ],
                check=True,
            )
        print(f"Wrote {target}:\n\n{content}\n", file=sys.stderr)

    def copy_runner_files(self) -> list[str]:
        """Copy absent public files and retain lookup directories in Git."""
        if self.runner_source is None:
            return []
        destination = self.machine.flake / "runners"
        destination.mkdir(exist_ok=True)
        files: list[Path] = []
        for source in sorted(self.runner_source.rglob("*")):
            relative = source.relative_to(self.runner_source)
            target = destination / relative
            if source.is_dir():
                target.mkdir(exist_ok=True)
            else:
                if not target.exists():
                    shutil.copyfile(source, target)
                files.append(relative)
        for marker in self.runner_markers:
            target = destination / marker
            if not target.exists():
                target.touch()
        return [str(Path("runners") / file) for file in files + self.runner_markers]

    def capture_runner_files(self) -> str:
        """Capture the same public closure used by the configured controller."""
        if not self.runner_configs:
            return ""
        root = self.runner_configs[0].parent
        try:
            selected = [str(file.relative_to(root)) for file in self.runner_configs]
        except ValueError as error:
            raise Refusal(
                "Runner instance files must stay under the first file's directory"
            ) from error
        result = subprocess.run(
            [
                "nix",
                *self.machine.log_format,
                "eval",
                *self.machine.nix_args,
                "--impure",
                "--json",
                "--file",
                str(RUNNER_PUBLIC_FILES),
                "capture",
                "--argstr",
                "root",
                str(root),
                "--argstr",
                "configFilesJSON",
                json.dumps(selected),
            ],
            stdout=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise Refusal(
                "invalid Runner public configuration; no machine files were written"
            )
        captured = json.loads(result.stdout)
        self.runner_source = Path(captured["source"])
        self.runner_markers = [
            directory.relative_to(self.runner_source) / ".nix-config-directory"
            for directory in self.runner_source.rglob("*")
            if directory.is_dir() and not any(directory.iterdir())
        ]
        return str(captured["declaration"])

    def check_runner_destination(self) -> None:
        """Refuse foreign destination files before changing the checkout."""
        if self.runner_source is None:
            return
        destination = self.machine.flake / "runners"
        pairs = [(self.runner_source, destination)] + [
            (source, destination / source.relative_to(self.runner_source))
            for source in self.runner_source.rglob("*")
        ]
        for source, target in pairs:
            if target.is_symlink():
                raise Refusal(f"Runner destination must not be a symlink: {target}")
            if not target.exists():
                continue
            if source.is_dir():
                matches = target.is_dir()
            else:
                matches = (
                    target.is_file() and source.read_bytes() == target.read_bytes()
                )
            if not matches:
                raise Refusal(
                    f"Runner destination conflicts with public configuration: {target}"
                )
        for marker in self.runner_markers:
            target = destination / marker
            if target.is_symlink() or (
                target.exists() and (not target.is_file() or target.stat().st_size != 0)
            ):
                raise Refusal(
                    f"Runner destination directory marker conflicts: {target}"
                )

    def uncommitted(self) -> bool:
        """Whether configuration.nix differs from the committed version."""
        return (
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.machine.flake),
                    "diff",
                    "--quiet",
                    "HEAD",
                    "--",
                    "configuration.nix",
                ],
                capture_output=True,
                check=False,
            ).returncode
            != 0
        )

    def render(self) -> str:
        """configuration.nix from the template; raise `Refusal` on a bad value."""
        v = self.values
        checks = (
            (NAME.fullmatch(v["user"]), f"invalid user name: {v['user']}"),
            (NAME.fullmatch(v["hostname"]), f"invalid hostname: {v['hostname']}"),
            (
                v["role"] in ("minimal", "workstation", "runner"),
                f"unknown role: {v['role']}",
            ),
            (
                v["role"] != "runner" or bool(self.runner_configs),
                "runner role requires --runner-config FILE",
            ),
            (
                not self.runner_configs or v["role"] == "runner",
                "--runner-config requires --role runner",
            ),
            (re.fullmatch(r"[A-Za-z0-9_+/-]+", v["timezone"]), "invalid time zone"),
            (re.fullmatch(r"[A-Za-z0-9_@.-]+", v["locale"]), "invalid locale"),
        )
        for ok, message in checks:
            if not ok:
                raise Refusal(message)
        entry = self.getent("passwd", v["user"])
        if entry is None:
            raise Refusal(f"create the account {v['user']} before installing")
        fields = entry.split(":")
        if fields[5] != f"/home/{v['user']}":
            raise Refusal(f"{v['user']} must live in /home/{v['user']}")
        wheel = self.getent("group", "wheel")
        if wheel is None or v["user"] not in wheel.split(":")[3].split(","):
            raise Refusal(f"{v['user']} must be in the wheel group")
        description = re.sub(r'[\\"$]', "", fields[4].split(",")[0]) or v["user"]
        images = sorted(
            f'"/boot/{image.name}"'
            for image in (self.root / "boot").glob("initramfs-*.img")
            if "fallback" not in image.name
        )
        if not images:
            raise Refusal("no initramfs image under /boot")
        template = (TEMPLATES / "configuration.nix").read_text()
        replacements = {
            "@role@": v["role"],
            "@hostname@": v["hostname"],
            "@timezone@": v["timezone"],
            "@locale@": v["locale"],
            "@description@": description,
            "@graphics@": "amd" if self.amd_graphics() else "generic",
            "@username@": v["user"],
            "@images@": " ".join(images),
        }
        for placeholder, value in replacements.items():
            template = template.replace(placeholder, value)
        return template.rstrip("\n")

    @staticmethod
    def getent(database: str, key: str) -> str | None:
        """The `getent DATABASE KEY` entry, or None."""
        return query("getent", database, key)

    @staticmethod
    def amd_graphics() -> bool:
        """Whether lspci lists an AMD display controller."""
        listing = query("lspci") or ""
        return any(
            re.search(r"VGA|3D|Display", line) and re.search(r"AMD|ATI", line, re.I)
            for line in listing.splitlines()
        )
