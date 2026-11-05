"""install: write configuration.nix for this machine, then plan and update."""

from __future__ import annotations

import os
import pwd
import re
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
        rest = list(args)
        while rest:
            option = rest.pop(0)
            if option in ("--user", "--hostname", "--role", "--timezone", "--locale"):
                if not rest:
                    raise Usage
                self.values[option[2:]] = rest.pop(0)
            elif option == "--yes":
                self.yes = True
            elif option == "--force":
                self.force = True
            else:
                raise Usage

    def run(self) -> int:
        """Ask for missing values, write the files, plan, and update on consent."""
        interactive = sys.stdin.isatty()
        if not self.yes and interactive:
            self.ask()
        self.write_configuration(self.render())
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
        if created:
            # A new machine flake that follows Nacre; Git tracks it so Nix sees it.
            flake.mkdir(parents=True, exist_ok=True)
            (flake / "flake.nix").write_text((TEMPLATES / "flake.nix").read_text())
        target.write_text(content + "\n")
        if created:
            for args in (
                ["init", "--quiet"],
                ["add", "flake.nix", "configuration.nix"],
            ):
                subprocess.run(["git", "-C", str(flake), *args], check=True)
        print(f"Wrote {target}:\n\n{content}\n", file=sys.stderr)

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
            (v["role"] in ("minimal", "workstation"), f"unknown role: {v['role']}"),
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
