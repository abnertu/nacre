"""Converge and purge core Arch policy from the Nix-generated manifest."""

from __future__ import annotations

import datetime
import os
import shutil
import stat
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from nix_adapter import AdapterContext, BaseAdapter, Change, Conflict, Files, Native
from receipts import (
    INTENT,
    RECEIPT,
    RECEIPT_LINE,
    STATE,
    VERSION,
    FileRecord,
    Intent,
    Original,
    Receipt,
    digest,
    file_key,
    load_json,
    load_receipt,
    original_name,
    save_json,
)
from schema import Block, CoreRequest, EtcEntry, Repository

__all__ = ["RECEIPT_LINE", "Core"]

# A file state: text, mode, UID and GID.
type FileState = tuple[str, int, int, int]


class Core(BaseAdapter[CoreRequest]):
    def __init__(
        self,
        desired: Mapping[str, Any],
        files: Files | None = None,
        native: Native | None = None,
        context: AdapterContext | None = None,
    ):
        root = files.root if files else Path("/")
        super().__init__(
            desired=cast(CoreRequest, desired),
            root=root,
            native=native,
            files=files,
            context=context,
        )
        self._receipt: Receipt | None = None

    # Pending markers keep their historic names so interrupted runs resume.
    @property
    def phases(self) -> dict[str, Callable[[], None]]:
        """The extra phases arch-switch runs around package installation."""
        return {
            "repositories": self.repositories,
            "finish": self.finish,
            "forget": self.forget,
        }

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

    def group_id(self, group: str) -> int | None:
        """The GID of `group` in the target root's /etc/group, or None."""
        for line in self.files.read("/etc/group").splitlines():
            fields = line.split(":")
            if len(fields) >= 3 and fields[0] == group and fields[2].isdigit():
                return int(fields[2])
        return None

    def entry_files(self, entry: EtcEntry) -> Files:
        """Files that write `entry` as the adapter's user and the entry's group.

        Raise `Conflict` if the group does not exist in the target root.
        """
        gid = self.group_id(entry["group"])
        if gid is None:
            raise Conflict(f"group {entry['group']} of {entry['path']} does not exist")
        return Files(self.files.root, (self.files.identity[0], gid))

    # environment.etc: the receipt is the only proof that Nacre owns a file.

    @property
    def receipt(self) -> Receipt:
        if self._receipt is None:
            self._receipt = load_receipt(self.files) or {
                "version": VERSION,
                "records": {},
            }
        return self._receipt

    @property
    def records(self) -> dict[str, FileRecord]:
        return self.receipt["records"]

    def save_receipt(self) -> None:
        save_json(self.files, RECEIPT, self.receipt)

    def intent(self) -> Intent | None:
        return cast("Intent | None", load_json(self.files, INTENT, "intent"))

    def check_host(self) -> None:
        """Refuse a host that a Nacre version without receipts deployed."""
        if load_receipt(self.files) is not None:
            return
        lines = self.files.read("/etc/nix/nix.conf").splitlines()
        if "# BEGIN nix-config settings" in lines and RECEIPT_LINE not in lines:
            raise Conflict(
                "this host was deployed by an older Nacre without receipts; "
                "run `nacre purge` with that version, then deploy this one"
            )

    def state(self, name: str) -> FileState | None:
        """The text, mode, UID and GID of `name`, or None if it does not exist."""
        text = self.files.read(name)
        path = self.files.path(name)
        if not path.exists():
            return None
        info = path.stat()
        return text, stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid

    @staticmethod
    def recorded(record: FileRecord, current: FileState) -> bool:
        """Whether `current` is the state that `record` left."""
        text, mode, uid, gid = current
        return (digest(text), mode, uid, gid) == (
            record["sha256"],
            int(record["mode"], 8),
            record["uid"],
            record["gid"],
        )

    def desired_entries(self) -> dict[str, EtcEntry]:
        return {file_key(entry["name"]): entry for entry in self.desired["etc"]}

    def withdrawn(self, purge: bool = False) -> list[FileRecord]:
        """The records that the manifest no longer declares; all of them on purge."""
        desired = {} if purge else self.desired_entries()
        return [record for key, record in self.records.items() if key not in desired]

    def package_owner(self, name: str) -> tuple[str, str] | None:
        """The pacman package that owns `name`, and its version."""
        owner = self.run("pacman", "-Qqo", name, check=False)
        if owner.returncode != 0:
            return None
        package = owner.stdout.strip()
        query = self.run("pacman", "-Q", package, check=False).stdout.split()
        return package, query[1] if len(query) > 1 else ""

    def check_withdrawn(self, record: FileRecord) -> None:
        """Raise `Conflict` if a withdrawn file changed since Nacre wrote it."""
        current = self.state(record["path"])
        if current is not None and not self.recorded(record, current):
            key = file_key(record["name"])
            raise Conflict(
                f"{record['path']} changed since Nacre wrote it; restore or delete it, "
                f"or run `nacre forget {key}` to leave it unmanaged"
            )

    def check_declared(self, entry: EtcEntry, converging: bool) -> None:
        """Raise `Conflict` if an unrecorded existing file may not be replaced."""
        if file_key(entry["name"]) in self.records:
            return
        current = self.state(entry["path"])
        if current is None or current[0] == entry["text"] or entry["adopt"]:
            return
        if not converging:
            raise Conflict(
                f"{entry['path']} exists, differs from environment.etc."
                f'"{entry["name"]}" and Nacre does not manage it; set adopt = true '
                "to replace it (Nacre saves the original)"
            )
        # Preflight passed, so the file appeared or changed since then.
        if self.package_owner(entry["path"]) is None:
            raise Conflict(
                f"{entry['path']} changed after preflight; deployment stopped"
            )

    def check_etc(self, converging: bool, purge: bool = False) -> None:
        self.check_host()
        intent = self.intent()
        busy = intent["key"] if intent and intent["op"] == "withdraw" else None
        for record in self.withdrawn(purge):
            if file_key(record["name"]) != busy:
                self.check_withdrawn(record)
        if not purge:
            for entry in self.desired["etc"]:
                self.check_declared(entry, converging)

    def clear_intent(self) -> None:
        self.remove(INTENT)

    def recover_intent(self) -> None:
        """Complete the record of a change that an earlier run interrupted."""
        intent = self.intent()
        if intent is None:
            return
        key = intent["key"]
        if intent["op"] == "write" and "record" in intent:
            record = intent["record"]
            current = self.state(record["path"])
            if current is not None and digest(current[0]) == record["sha256"]:
                self.records[key] = record
                self.save_receipt()
        elif (record := self.records.get(key)) is not None:
            current = self.state(record["path"])
            original = self.saved_original(record)
            if current is None or (original and current[0] == original["text"]):
                self.drop(key)
        self.clear_intent()

    def saved_original(self, record: FileRecord) -> Original | None:
        if record["original"] is None:
            return None
        return cast(
            "Original | None", load_json(self.files, record["original"], "original")
        )

    def save_original(self, name: str, current: FileState) -> str:
        """Save the file that an adoption replaces; return where it went."""
        text, mode, uid, gid = current
        owner = self.package_owner(name)
        original: Original = {
            "path": name,
            "text": text,
            "mode": f"{mode:04o}",
            "uid": uid,
            "gid": gid,
            "package": owner[0] if owner else None,
            "version": owner[1] if owner else None,
            "date": datetime.date.today().isoformat(),
        }
        saved = original_name(name)
        save_json(self.files, saved, original)
        return saved

    def drop(self, key: str) -> None:
        record = self.records.pop(key)
        if record["original"] is not None:
            self.remove(record["original"])
        self.save_receipt()

    def forget(self) -> None:
        """Drop one record and its original; leave the native state as it is."""
        record = self.desired.get("forget", "")
        kind, _, name = record.partition(":")
        if kind != "file" or not name:
            raise Conflict(
                f"unknown record {record}; core records look like file:<name>"
            )
        if record not in self.records:
            raise Conflict(f"Nacre has no record {record}")
        path = self.records[record]["path"]
        self.drop(record)
        print(f"forgot {record}; {path} stays as it is, unmanaged")

    def write_entry(self, entry: EtcEntry) -> None:
        key = file_key(entry["name"])
        record = self.records.get(key)
        files = self.entry_files(entry)
        mode = int(entry["mode"], 8)
        if record is not None and files.matches(entry["path"], entry["text"], mode):
            return
        current = self.state(entry["path"])
        drifted = (
            record is not None
            and current is not None
            and not self.recorded(record, current)
        )
        if record is not None:
            original = record["original"]
        elif current is None or "nix-config" in Path(entry["path"]).name:
            original = None
        else:
            original = self.save_original(entry["path"], current)
        new: FileRecord = {
            "kind": "file",
            "name": entry["name"],
            "path": entry["path"],
            "sha256": digest(entry["text"]),
            "mode": entry["mode"],
            "uid": files.identity[0],
            "gid": files.identity[1],
            "action": entry["action"],
            "original": original,
        }
        save_json(self.files, INTENT, {"op": "write", "key": key, "record": new})
        if files.write(entry["path"], entry["text"], mode):
            self.mark(entry["action"])
            self.updates += 1
            print(f"{'overwrote drifted' if drifted else 'updated'} {entry['path']}")
        self.records[key] = new
        self.save_receipt()
        self.clear_intent()

    def withdraw(self, record: FileRecord) -> None:
        """Restore the adopted original of a withdrawn file, or remove the file."""
        key = file_key(record["name"])
        save_json(self.files, INTENT, {"op": "withdraw", "key": key})
        if self.state(record["path"]) is not None:
            if record["original"] is None:
                self.remove(record["path"])
                print(f"removed {record['path']}")
            else:
                self.restore(record)
            self.mark(record["action"])
            self.updates += 1
        self.drop(key)
        self.clear_intent()

    def restore(self, record: FileRecord) -> None:
        original = self.saved_original(record)
        if original is None:
            raise Conflict(f"the saved original of {record['path']} is missing")
        files = Files(self.files.root, (self.files.identity[0], original["gid"]))
        files.write(original["path"], original["text"], int(original["mode"], 8))
        if original["uid"] != self.files.identity[0]:
            os.chown(
                files.path(original["path"]),
                original["uid"],
                original["gid"],
                follow_symlinks=False,
            )
        print(f"restored {record['path']}")
        if original["package"]:
            owner = self.package_owner(record["path"])
            if owner and owner[1] != original["version"]:
                print(
                    f"warning: the restored {record['path']} predates "
                    f"{owner[0]} {owner[1]}; merge the package changes by hand"
                )

    def plan_etc(self) -> list[Change]:
        """The etc writes, adoptions, restores and removals, without content."""
        changes: list[Change] = []
        for record in self.withdrawn():
            if self.state(record["path"]) is None:
                continue
            original = self.saved_original(record)
            changes.append(
                Change(
                    "~", f"{record['path']} (restore original from {original['date']})"
                )
                if original
                else Change("~", f"{record['path']} (withdrawn, remove)")
            )
        for entry in self.desired["etc"]:
            changes.append(self.plan_entry(entry))
        return changes

    def plan_entry(self, entry: EtcEntry) -> Change:
        path = entry["path"]
        record = self.records.get(file_key(entry["name"]))
        current = self.state(path)
        try:
            files = self.entry_files(entry)
        except Conflict:
            return Change("~", f"{path} (group {entry['group']} does not exist yet)")
        if current is None:
            return Change("+", path)
        if record is None:
            created = "nix-config" in Path(path).name
            note = "adopt as Nacre's" if created else "adopt, save original"
        elif files.matches(path, entry["text"], int(entry["mode"], 8)):
            return Change("=", path)
        elif not self.recorded(record, current):
            note = "drifted, overwrite"
        else:
            note = "content differs"
        return Change("~", f"{path} ({note})")

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
        commands = {"systemctl", "sysctl", "gpasswd", "id", "modprobe", "pacman"}
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
        self.check_etc(converging=False)
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
        self.recover_intent()
        self.check_etc(converging=True)
        if load_receipt(self.files) is None:
            # Before any other change: an interrupted first run is then a
            # lost-receipt host, never a fresh one.
            self.save_receipt()
        for record in self.withdrawn():
            self.withdraw(record)
        for entry in d["etc"]:
            self.write_entry(entry)
        for block in d["blocks"]:
            self.put(block["path"], self.with_block(block), block["action"])
        self.initramfs()
        groups_changed = self.groups()
        if self.pending("units"):
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
        changes = self.plan_etc()
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
        if self.pending("units"):
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

        Every recorded file is checked for drift before any change. Units stop
        first, then the repository Include goes before its target, then
        recorded files are restored or removed, then blocks, and the
        deployment state last.
        """
        self.recover_intent()
        self.check_etc(converging=False, purge=True)
        self.purge_units()
        if repository := self.desired["repository"]:
            self.purge_repository(repository)
        for record in self.withdrawn(purge=True):
            self.withdraw(record)
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
