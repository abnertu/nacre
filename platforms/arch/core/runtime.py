"""Converge and purge core Arch policy from the Nix-generated manifest."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from nix_adapter import AdapterContext, BaseAdapter, Change, Conflict, Files, Native
from schema import Block, CoreManifest, Repository

STATE = "/var/lib/nix-config/arch"


class Core(BaseAdapter[CoreManifest]):
    def __init__(
        self,
        desired: Mapping[str, Any],
        files: Files | None = None,
        native: Native | None = None,
        context: AdapterContext | None = None,
    ):
        root = files.root if files else Path("/")
        super().__init__(
            desired=cast(CoreManifest, desired),
            root=root,
            native=native,
            files=files,
            context=context,
        )

    # Pending markers keep their historic names so interrupted runs resume.
    @property
    def phases(self) -> dict[str, Callable[[], None]]:
        """The extra phases arch-switch runs around package installation."""
        return {"repositories": self.repositories, "finish": self.finish}

    def marker(self, action: str) -> str:
        return f"{STATE}/{action}.pending"

    def mark(self, action: str | None) -> None:
        if action and not self.pending(action):
            self.files.write(self.marker(action), "")

    def pending(self, action: str) -> bool:
        self.files.read(self.marker(action))
        return self.files.path(self.marker(action)).exists()

    def clear(self, action: str) -> None:
        self.remove(self.marker(action))

    def remove(self, name: str) -> bool:
        path = self.files.path(name)
        if not path.exists():
            return False
        if not path.is_file():
            raise Conflict(f"managed path is not a regular file: {name}")
        path.unlink()
        self.files.sync_dir(path.parent)
        return True

    def put(self, name: str, text: str, action: str | None = None) -> None:
        if self.files.matches(name, text):
            return
        self.mark(action)
        self.files.write(name, text)
        self.updates += 1
        print(f"updated {name}")

    @staticmethod
    def block_lines(name: str) -> tuple[str, str]:
        return f"# BEGIN nix-config {name}", f"# END nix-config {name}"

    def without_block(self, block: Block) -> str | None:
        """Return the file without its managed block, or None if it is absent."""
        path = self.files.path(block["path"])
        if not path.exists():
            if block["create"]:
                return None
            raise Conflict(f"required configuration is missing: {block['path']}")
        begin, end = self.block_lines(block["name"])
        kept: list[str] = []
        inside = False
        for line in self.files.read(block["path"]).splitlines(keepends=True):
            stripped = line.rstrip("\n")
            if stripped == begin:
                if inside:
                    raise Conflict(f"nested managed block in {block['path']}")
                inside = True
            elif stripped == end:
                if not inside:
                    raise Conflict(f"unmatched managed block end in {block['path']}")
                inside = False
            elif not inside:
                kept.append(line)
        if inside:
            raise Conflict(f"unterminated managed block in {block['path']}")
        return "".join(kept)

    def with_block(self, block: Block) -> str:
        begin, end = self.block_lines(block["name"])
        return (self.without_block(block) or "") + f"{begin}\n{block['text']}{end}\n"

    def repository_server(self, *config: str) -> str | None:
        repository = self.desired["repository"]
        if repository is None:
            raise Conflict("no repository is declared")
        name = repository["name"]
        result = self.run("pacman-conf", *config, "--repo", name, "Server", check=False)
        return result.stdout.strip() if result.returncode == 0 else None

    def required_commands(self) -> set[str]:
        d = self.desired
        commands = {"systemctl", "sysctl", "gpasswd", "id", "modprobe"}
        if d["initramfsImages"]:
            commands.add("mkinitcpio")
        if d["fileCapabilities"]:
            commands |= {"getcap", "setcap"}
        if d["repository"]:
            commands.add("pacman-conf")
        return commands

    def preflight(self, installed: bool = False) -> bool:
        d = self.desired
        missing = sorted(
            c for c in self.required_commands() if not self.native.available(c)
        )
        if missing:
            raise Conflict(
                "required native core commands are missing: " + " ".join(missing)
            )
        for entry in d["files"]:
            self.files.read(entry["path"])
        for block in d["blocks"]:
            self.without_block(block)
        repository = d["repository"]
        if repository:
            self.files.read(repository["path"])
            included = (
                repository["include"]
                in self.files.read("/etc/pacman.conf").splitlines()
            )
            if not included and self.repository_server() is not None:
                raise Conflict(
                    f"an unmanaged [{repository['name']}] repository already exists in pacman.conf"
                )
        return True

    def repositories(self) -> None:
        repository = self.desired["repository"]
        if not repository:
            return
        self.put(repository["path"], repository["text"])
        pacman = self.files.read("/etc/pacman.conf")
        if repository["include"] not in pacman.splitlines():
            self.put("/etc/pacman.conf", pacman + f"\n{repository['include']}\n")
        expected = self.repository_server("--config", repository["source"])
        if expected is None or self.repository_server() != expected:
            raise Conflict(
                f"managed [{repository['name']}] repository did not load as expected"
            )

    def systemctl_ok(self, *args: str) -> bool:
        return self.run("systemctl", *args, check=False).returncode == 0

    def converge(self) -> None:
        d = self.desired
        for entry in d["files"]:
            self.put(entry["path"], entry["text"], entry["action"])
        for block in d["blocks"]:
            self.put(block["path"], self.with_block(block), block["action"])
        self.initramfs()
        groups_changed = self.groups()
        if d["reloadUnits"] and self.pending("units"):
            self.systemd.daemon_reload()
            self.clear("units")
            self.actions += 1
        for unit in d["units"]:
            self.converge_unit(unit)
        print(
            f"Core converged: {self.updates} files updated, {self.actions} runtime actions."
        )
        if groups_changed:
            print("Group membership changed; log out and back in.")

    def initramfs(self) -> None:
        images = self.desired["initramfsImages"]
        if not images:
            return
        if any(not self.nonempty(image) for image in images):
            self.mark("initramfs")
        if self.pending("initramfs"):
            self.run("mkinitcpio", "-P")
            for image in images:
                if not self.nonempty(image):
                    raise Conflict(f"initramfs was not generated: {image}")
            self.clear("initramfs")
            self.actions += 1

    def nonempty(self, name: str) -> bool:
        path = self.files.path(name)
        return path.is_file() and path.stat().st_size > 0

    def groups(self) -> bool:
        user = self.desired["user"]
        current = set(self.run("id", "-nG", user).stdout.split())
        changed = False
        for group in self.desired["groups"]:
            if group not in current:
                self.run("gpasswd", "--add", user, group)
                changed = True
        return changed

    def finish(self) -> None:
        d = self.desired
        for restart in d["restarts"]:
            if not self.pending(restart["action"]):
                continue
            if not restart["onlyIfActive"] or self.systemctl_ok(
                "is-active", "--quiet", restart["unit"]
            ):
                self.systemd.restart(restart["unit"])
            self.clear(restart["action"])
            self.actions += 1
        # Compare runtime values too: unchanged files must not conceal drift.
        for module in d["kernelModules"]:
            if not (self.root / "sys/module" / module).is_dir():
                self.run("modprobe", module)
                self.actions += 1
        for key, value in d["sysctl"].items():
            if self.run("sysctl", "-n", key).stdout.strip() != value:
                self.run("sysctl", "-w", f"{key}={value}")
                self.actions += 1
        for entry in d["fileCapabilities"]:
            target = self.resolve(entry["path"])
            expected = f"{target} {entry['capability']}"
            if self.run("getcap", target).stdout.strip() != expected:
                self.run("setcap", entry["capability"].replace("=", "+"), target)
                self.actions += 1
        print(
            f"Core runtime converged: 0 files updated, {self.actions} runtime actions."
        )

    def resolve(self, name: str) -> str:
        real = Path(os.path.realpath(self.root / name.lstrip("/")))
        if not real.is_relative_to(self.root) or not real.is_file():
            raise Conflict(f"executable is missing: {name}")
        return "/" + str(real.relative_to(self.root))

    def plan(self) -> list[Change]:
        """What converge and finish would change; nothing is changed."""
        self.preflight()
        return self.plan_files() + self.plan_runtime()

    def plan_files(self) -> list[Change]:
        """The managed file, managed block and repository changes."""
        d = self.desired
        changes = [self.plan_file(entry["path"], entry["text"]) for entry in d["files"]]
        changes += [
            self.plan_file(block["path"], self.with_block(block))
            for block in d["blocks"]
        ]
        if repository := d["repository"]:
            changes.append(self.plan_file(repository["path"], repository["text"]))
            if (
                repository["include"]
                not in self.files.read("/etc/pacman.conf").splitlines()
            ):
                changes.append(Change("~", "/etc/pacman.conf (add repository Include)"))
        return changes

    def plan_runtime(self) -> list[Change]:
        """The initramfs, group, unit, kernel and capability changes."""
        d = self.desired
        changes: list[Change] = []
        images = d["initramfsImages"]
        if images and (
            self.pending("initramfs") or not all(map(self.nonempty, images))
        ):
            changes.append(Change("~", "rebuild initramfs images"))
        current = set(self.run("id", "-nG", d["user"]).stdout.split())
        changes += [
            Change("~", f"add {d['user']} to group {g}")
            for g in d["groups"]
            if g not in current
        ]
        if d["reloadUnits"] and self.pending("units"):
            changes.append(Change("~", "reload systemd units"))
        for unit in d["units"]:
            changes += self.plan_unit(unit)
        changes += [
            Change("~", f"restart {restart['unit']} (pending)")
            for restart in d["restarts"]
            if self.pending(restart["action"])
        ]
        return changes + self.plan_kernel() + self.plan_capabilities()

    def plan_kernel(self) -> list[Change]:
        """The kernel modules to load and the sysctl values to set."""
        d = self.desired
        changes = [
            Change("~", f"load kernel module {module}")
            for module in d["kernelModules"]
            if not (self.root / "sys/module" / module).is_dir()
        ]
        for key, value in d["sysctl"].items():
            current = self.run("sysctl", "-n", key).stdout.strip()
            if current != value:
                changes.append(Change("~", f"sysctl {key}: {current} -> {value}"))
        return changes

    def plan_capabilities(self) -> list[Change]:
        """The file capabilities to set."""
        changes: list[Change] = []
        for entry in self.desired["fileCapabilities"]:
            target = self.resolve(entry["path"])
            if (
                self.run("getcap", target).stdout.strip()
                != f"{target} {entry['capability']}"
            ):
                changes.append(Change("~", f"set {entry['capability']} on {target}"))
        return changes

    def purge(self) -> None:
        """Withdraw the managed Arch state; keep packages, accounts and user data.

        Units stop first, then the repository Include goes before its target,
        then owned files and blocks, and the deployment state last.
        """
        self.purge_units()
        if repository := self.desired["repository"]:
            self.purge_repository(repository)
        for entry in self.desired["files"]:
            self.remove(entry["path"])
        for block in self.desired["purge"]["blocks"]:
            self.purge_block(block)
        state = self.files.path(STATE)
        if state.exists():
            shutil.rmtree(state)
        print("Arch deployment state purged; package and user data were preserved.")

    def purge_units(self) -> None:
        """Disable the managed units and remove the unit files that Nacre owns."""
        d = self.desired
        for unit in d["units"]:
            if self.systemctl_ok("is-enabled", "--quiet", unit):
                self.systemd.disable(unit, now=True)
        reload = False
        for owned in d["purge"]["ownedUnits"]:
            if self.files.path(owned["path"]).exists():
                if self.systemctl_ok("is-enabled", "--quiet", owned["unit"]):
                    self.systemd.disable(owned["unit"], now=True)
                reload |= self.remove(owned["path"])
        if reload:
            self.systemd.daemon_reload()

    def purge_repository(self, repository: Repository) -> None:
        """Drop the repository's Include, then its file."""
        # Drop the Include before its target: pacman cannot load a missing include.
        lines = self.files.read("/etc/pacman.conf").splitlines(keepends=True)
        kept = [line for line in lines if line.rstrip("\n") != repository["include"]]
        if kept != lines:
            self.files.write("/etc/pacman.conf", "".join(kept))
        self.remove(repository["path"])

    def purge_block(self, block: Block) -> None:
        """Remove a managed block; restart nix-daemon after its block changes."""
        text = self.without_block(block)
        if text is None or text == self.files.read(block["path"]):
            return
        self.files.write(block["path"], text)
        if block["action"] == "nix-daemon" and self.systemctl_ok(
            "is-active", "--quiet", "nix-daemon.service"
        ):
            self.systemd.restart("nix-daemon.service")
