"""Converge and purge core Arch policy from the Nix-generated manifest."""

from __future__ import annotations

import base64
import datetime
import hashlib
import json
import os
import shutil
import stat
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal, cast

from nix_adapter import AdapterContext, BaseAdapter, Change, Conflict, Files, Native
from receipts import (
    GCROOTS,
    INTENT,
    KINDS,
    RECEIPT,
    RECEIPT_LINE,
    STATE,
    SYSCTL_DIRS,
    VERSION,
    FileRecord,
    Intent,
    Original,
    Receipt,
    file_key,
    load_json,
    load_receipt,
    original_name,
    save_json,
)
from schema import Block, CoreRequest, EtcEntry, Repository, UnitEntry

__all__ = ["RECEIPT_LINE", "Core"]

# Units that carry the deploying session; purge stops them last.
NETWORK_UNITS = frozenset({"NetworkManager.service", "tailscaled.service"})


def restart_action(unit: str) -> str:
    """The pending action that restarts `unit` after its file changed."""
    return f"restart-{unit}"


# The content of a path: the bytes of a regular file, or a symlink target.
type Content = tuple[Literal["file"], bytes] | tuple[Literal["link"], str]
# A path state: content, mode, UID and GID. A link has LINK_MODE.
type FileState = tuple[Content, int, int, int]
# S_IFLNK and the permissions: no regular file has this mode.
LINK_MODE = stat.S_IFLNK | 0o777
STORE = "/nix/store"


def content_digest(content: Content) -> str:
    """The record digest: of the bytes of a file, or of the target of a link."""
    if content[0] == "file":
        return hashlib.sha256(content[1]).hexdigest()
    return hashlib.sha256(content[1].encode()).hexdigest()


def original_content(original: Original) -> Content:
    """The content that an adoption saved."""
    if "target" in original:
        return ("link", original["target"])
    if "base64" in original:
        return ("file", base64.b64decode(original["base64"]))
    return ("file", original.get("text", "").encode())


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
        # A host whose nix.conf block marks receipts but whose receipt is gone.
        self.lost_receipt = False
        # The bytes of each source store file, read once.
        self.sources: dict[str, bytes] = {}

    # Pending markers keep their historic names so interrupted runs resume.
    @property
    def phases(self) -> dict[str, Callable[[], None]]:
        """The extra phases arch-switch runs around package installation."""
        return {
            "repositories": self.repositories,
            "finish": self.finish,
            "forget": self.forget,
            "purgecheck": self.purge_check,
            "retire": self.retire,
        }

    def purge_check(self) -> None:
        """Check every record for drift before purge changes anything."""
        self.check_host()
        self.check_etc(converging=False, purge=True)
        self.check_runtime(purge=True)

    def retire(self) -> None:
        """Run the recorded purge phase of each removed extension."""
        self.withdraw_extensions(purge=True)

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
        path = self.files.path(name, symlink_leaf=True)
        if not os.path.lexists(path):
            return False
        if not path.is_symlink() and not path.is_file():
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
            loaded = load_receipt(self.files)
            if loaded is None:
                lines = self.files.read("/etc/nix/nix.conf").splitlines()
                self.lost_receipt = RECEIPT_LINE in lines
            self._receipt = loaded or {
                "version": VERSION,
                "records": {},
                "triggers": {},
                "state": {},
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
        """The content, mode, UID and GID of `name`, or None if nothing is there.

        A symlink is never followed. Raise `Conflict` for any other kind.
        """
        path = self.files.path(name, symlink_leaf=True)
        if not os.path.lexists(path):
            return None
        info = path.lstat()
        content: Content
        if stat.S_ISLNK(info.st_mode):
            content = ("link", os.readlink(path))
            mode = LINK_MODE
        elif stat.S_ISREG(info.st_mode):
            content = ("file", path.read_bytes())
            mode = stat.S_IMODE(info.st_mode)
        else:
            raise Conflict(f"{name} is not a regular file or symlink")
        return content, mode, info.st_uid, info.st_gid

    def desired_content(self, entry: EtcEntry) -> Content:
        """What `entry` declares: its text, the bytes of its source, or its target."""
        if entry["target"] is not None:
            return ("link", entry["target"])
        if entry["source"] is not None:
            source = entry["source"]
            if source not in self.sources:
                try:
                    info = os.stat(source)
                    if not stat.S_ISREG(info.st_mode):
                        raise OSError
                    self.sources[source] = Path(source).read_bytes()
                except OSError:
                    raise Conflict(
                        f"the source of {entry['path']} is not a readable file: {source}"
                    ) from None
            return ("file", self.sources[source])
        return ("file", (entry["text"] or "").encode())

    @staticmethod
    def entry_mode(entry: EtcEntry) -> int:
        return LINK_MODE if entry["target"] is not None else int(entry["mode"], 8)

    def matches(self, entry: EtcEntry, files: Files) -> bool:
        """Whether the path holds `entry` with its mode and identity."""
        current = self.state(entry["path"])
        return current == (
            self.desired_content(entry),
            self.entry_mode(entry),
            *files.identity,
        )

    def write_content(self, entry: EtcEntry, files: Files) -> bool:
        kind, value = self.desired_content(entry)
        if kind == "link":
            return files.write_link(entry["path"], cast(str, value))
        return files.write_bytes(
            entry["path"], cast(bytes, value), self.entry_mode(entry)
        )

    def check_target(self, entry: EtcEntry) -> None:
        """Raise `Conflict` if a target resolves into the Nix store."""
        if entry["target"] is None:
            return
        resolved = Path(os.path.realpath(self.files.root / entry["target"].lstrip("/")))
        stores = (Path(STORE), self.files.root / STORE.lstrip("/"))
        if any(resolved == store or resolved.is_relative_to(store) for store in stores):
            raise Conflict(
                f"{entry['path']} links to {entry['target']}, which resolves into "
                "the Nix store; link to a native path"
            )

    @staticmethod
    def recorded(record: FileRecord, current: FileState) -> bool:
        """Whether `current` is the state that `record` left."""
        content, mode, uid, gid = current
        return (content_digest(content), mode, uid, gid) == (
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
        self.check_target(entry)
        current = self.state(entry["path"])
        if (
            current is None
            or current[0] == self.desired_content(entry)
            or entry["adopt"]
        ):
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
            if current is not None and content_digest(current[0]) == record["sha256"]:
                self.records[key] = record
                self.save_receipt()
        elif (record := self.records.get(key)) is not None:
            current = self.state(record["path"])
            original = self.saved_original(record)
            if current is None or (
                original and current[0] == original_content(original)
            ):
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
        content, mode, uid, gid = current
        owner = self.package_owner(name)
        original: Original = {
            "path": name,
            "mode": f"{mode:04o}",
            "uid": uid,
            "gid": gid,
            "package": owner[0] if owner else None,
            "version": owner[1] if owner else None,
            "date": datetime.date.today().isoformat(),
        }
        kind, value = content
        if kind == "link":
            original["target"] = cast(str, value)
        else:
            try:
                original["text"] = cast(bytes, value).decode()
            except UnicodeDecodeError:
                original["base64"] = base64.b64encode(cast(bytes, value)).decode()
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
        if kind not in KINDS or not name:
            raise Conflict(f"unknown record {record}; see `nacre forget` in the guide")
        if kind == "extension" and record in self.receipt["state"]:
            self.drop_extension(record)
        elif kind != "file" and record in self.receipt["state"]:
            self.drop_state(record)
        elif kind == "file" and record in self.records:
            self.drop(record)
        else:
            raise Conflict(f"Nacre has no record {record}")
        print(f"forgot {record}; the native state stays as it is, unmanaged")

    # Runtime state: groups, capabilities, sysctl keys, modules and the
    # repository, recorded when Nacre changes them.

    @property
    def state_records(self) -> dict[str, dict[str, Any]]:
        return self.receipt["state"]

    def record_state(self, key: str, value: dict[str, Any]) -> None:
        if self.state_records.get(key) != value:
            self.state_records[key] = dict(value)
            self.save_receipt()

    def drop_state(self, key: str) -> None:
        del self.state_records[key]
        self.save_receipt()

    def state_withdrawn(self, kind: str, declared: set[str], purge: bool) -> list[str]:
        """The keys of `kind` records whose name the manifest no longer declares."""
        return [
            key
            for key, record in self.state_records.items()
            if record["kind"] == kind and (purge or record["name"] not in declared)
        ]

    def check_runtime(self, purge: bool = False) -> None:
        """Raise `Conflict` if withdrawn runtime state changed since Nacre set it."""
        d = self.desired
        for key in self.state_withdrawn("sysctl", set(d["sysctl"]), purge):
            record = self.state_records[key]
            query = self.run("sysctl", "-n", record["name"], check=False)
            # A missing key, the value before Nacre or the boot value is no edit.
            expected = {
                record["applied"],
                record["previous"],
                self.boot_value(record["name"]),
            }
            if query.returncode == 0 and query.stdout.strip() not in expected:
                raise Conflict(
                    f"sysctl {record['name']} changed since Nacre set it; restore it, "
                    f"or run `nacre forget {key}` to leave it unmanaged"
                )
        declared = {entry["path"] for entry in d["fileCapabilities"]}
        for key in self.state_withdrawn("capability", declared, purge):
            record = self.state_records[key]
            current = self.run("getcap", record["target"]).stdout.strip()
            if current and current != f"{record['target']} {record['capability']}":
                raise Conflict(
                    f"the capability of {record['target']} changed since Nacre set "
                    f"it; run `nacre forget {key}` to leave it unmanaged"
                )

    def boot_value(self, key: str) -> str | None:
        """The value that the sysctl.d files give `key` at boot, if any.

        A file that the manifest declares counts with its declared text, so a
        plan sees the file that convergence writes.
        """
        declared = {
            entry["path"]: entry["text"]
            for entry in self.desired["etc"]
            if entry["text"] is not None
        }
        chosen: dict[str, str] = {}
        for directory in reversed(SYSCTL_DIRS):  # Higher precedence overrides.
            path = self.files.path(directory)
            if path.is_dir():
                for file in sorted(path.glob("*.conf")):
                    chosen[file.name] = self.files.system_name(file)
        value = None
        for name in sorted(chosen):
            text = declared.get(chosen[name])
            if text is None:
                text = self.files.read(chosen[name])
            for line in text.splitlines():
                setting, separator, assigned = line.partition("=")
                setting = setting.strip().lstrip("-")
                if separator and setting == key:
                    value = assigned.strip()
        return value

    def withdraw_groups(self, purge: bool = False) -> None:
        user = self.desired["user"]
        current = set(self.run("id", "-nG", user).stdout.split())
        for key in self.state_withdrawn("group", set(self.desired["groups"]), purge):
            group = self.state_records[key]["name"]
            # wheel keeps the deployment user an administrator: never remove it.
            if group != "wheel" and group in current:
                self.run("gpasswd", "--delete", user, group)
                self.actions += 1
            self.drop_state(key)

    def withdraw_runtime(self, purge: bool = False) -> None:
        """Withdraw capabilities, sysctl keys and modules that Nacre set."""
        d = self.desired
        declared = {entry["path"] for entry in d["fileCapabilities"]}
        for key in self.state_withdrawn("capability", declared, purge):
            target = self.state_records[key]["target"]
            if self.run("getcap", target).stdout.strip():
                self.run("setcap", "-r", target)
                self.actions += 1
            self.drop_state(key)
        for key in self.state_withdrawn("sysctl", set(d["sysctl"]), purge):
            record = self.state_records[key]
            query = self.run("sysctl", "-n", record["name"], check=False)
            value = self.boot_value(record["name"]) or record["previous"]
            if query.returncode == 0 and value not in (None, query.stdout.strip()):
                self.run("sysctl", "-w", f"{record['name']}={value}")
                self.actions += 1
            self.drop_state(key)
        for key in self.state_withdrawn("module", set(d["kernelModules"]), purge):
            self.withdraw_module(key)

    def withdraw_module(self, key: str) -> None:
        """Unload a module that Nacre loaded, unless something still uses it."""
        module = self.state_records[key]["name"]
        directory = self.root / "sys/module" / module
        refcnt = directory / "refcnt"
        users = refcnt.read_text().strip() if refcnt.is_file() else "0"
        if not directory.is_dir():
            self.drop_state(key)
        elif users == "0":
            self.run("modprobe", "-r", module)
            self.actions += 1
            self.drop_state(key)
        else:
            print(
                f"kernel module {module} is in use; {module} stays loaded until reboot"
            )

    # Extensions: each deployment records the adapter, manifest and Python
    # that ran, under GC roots, so a removed extension can still retire.

    def gc_root(self, name: str, part: str) -> Path:
        return self.files.path(f"{GCROOTS}/{name}-{part}", symlink_leaf=True)

    def record_extensions(self) -> None:
        for extension in self.desired["extensions"]:
            name = extension["name"]
            self.record_state(f"extension:{name}", {"kind": "extension", **extension})
            for part in ("adapter", "manifest", "python"):
                link, target = self.gc_root(name, part), extension[part]
                if link.is_symlink() and os.readlink(link) == target:
                    continue
                link.parent.mkdir(parents=True, exist_ok=True)
                link.unlink(missing_ok=True)
                link.symlink_to(target)

    def drop_extension(self, key: str) -> None:
        name = self.state_records[key]["name"]
        for part in ("adapter", "manifest", "python"):
            self.gc_root(name, part).unlink(missing_ok=True)
        self.drop_state(key)

    def withdraw_extensions(self, purge: bool = False) -> None:
        """Retire each recorded extension that the manifest no longer declares.

        On purge, arch-switch has already run the hooks of declared extensions.
        """
        declared = {extension["name"] for extension in self.desired["extensions"]}
        for key in self.state_withdrawn("extension", declared, purge):
            record = self.state_records[key]
            name = record["name"]
            if record["purge"] and name not in declared:
                hook = (
                    record["python"],
                    record["adapter"],
                    record["manifest"],
                    "purge",
                )
                if self.run("env", *hook, check=False).returncode != 0:
                    raise Conflict(
                        f"the purge phase of extension {name} failed; fix its cause, "
                        f"or run `nacre forget {key}` to drop it without retirement"
                    )
                self.actions += 1
            self.drop_extension(key)

    def withdraw_repository(self) -> None:
        """Drop a repository that the manifest no longer declares."""
        for key in self.state_withdrawn("repository", set(), purge=True):
            record = self.state_records[key]
            self.purge_repository(cast(Repository, record))
            self.drop_state(key)

    def write_entry(self, entry: EtcEntry) -> None:
        key = file_key(entry["name"])
        record = self.records.get(key)
        files = self.entry_files(entry)
        if record is not None and self.matches(entry, files):
            return
        current = self.state(entry["path"])
        drifted = (
            record is not None
            and current is not None
            and not self.recorded(record, current)
        )
        if record is not None:
            original = record["original"]
        elif (
            current is None
            or "nix-config" in Path(entry["path"]).name
            # On a lost-receipt host, a file identical to its declaration is
            # Nacre's own: withdrawal removes it instead of restoring it.
            or (self.lost_receipt and current[0] == self.desired_content(entry))
        ):
            original = None
        else:
            original = self.save_original(entry["path"], current)
        new: FileRecord = {
            "kind": "file",
            "name": entry["name"],
            "path": entry["path"],
            "sha256": content_digest(self.desired_content(entry)),
            "mode": f"{self.entry_mode(entry):04o}",
            "uid": files.identity[0],
            "gid": files.identity[1],
            "unit": entry["unit"],
            "dropin": entry["dropin"],
            "original": original,
        }
        save_json(self.files, INTENT, {"op": "write", "key": key, "record": new})
        if self.write_content(entry, files):
            if entry["unit"] is not None:
                self.mark("units")
                # A new unit starts with its file; a changed one restarts.
                if (
                    record is not None
                    and not entry["dropin"]
                    and entry["restartIfChanged"]
                ):
                    self.mark(restart_action(entry["unit"]))
            self.updates += 1
            print(f"{'overwrote drifted' if drifted else 'updated'} {entry['path']}")
        self.records[key] = new
        self.save_receipt()
        self.clear_intent()

    def withdraw(self, record: FileRecord) -> None:
        """Restore the adopted original of a withdrawn file, or remove the file."""
        key = file_key(record["name"])
        save_json(self.files, INTENT, {"op": "withdraw", "key": key})
        unit = record["unit"]
        if (
            unit is not None
            and not record["dropin"]
            and (
                self.systemctl_ok("is-enabled", "--quiet", unit)
                or self.systemctl_ok("is-active", "--quiet", unit)
            )
        ):
            # An authored unit stops before its file goes away; a drop-in only reloads.
            self.systemd.disable(unit, now=True)
            self.actions += 1
        if self.state(record["path"]) is not None:
            if record["original"] is None:
                self.remove(record["path"])
                print(f"removed {record['path']}")
            else:
                self.restore(record)
            if unit is not None:
                self.mark("units")
            self.updates += 1
        self.drop(key)
        self.clear_intent()

    def restore(self, record: FileRecord) -> None:
        original = self.saved_original(record)
        if original is None:
            raise Conflict(f"the saved original of {record['path']} is missing")
        files = Files(self.files.root, (self.files.identity[0], original["gid"]))
        kind, value = original_content(original)
        if kind == "link":
            files.write_link(original["path"], cast(str, value))
        else:
            files.write_bytes(
                original["path"], cast(bytes, value), int(original["mode"], 8)
            )
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
            stops = record["unit"] is not None and not record["dropin"]
            removal = (
                "withdrawn, stop, disable and remove" if stops else "withdrawn, remove"
            )
            note = f"restore original from {original['date']}" if original else removal
            changes.append(Change("~", f"{record['path']} ({note})"))
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
            # The same rule as write_entry, which records these as Nacre's.
            created = "nix-config" in Path(path).name or (
                self.lost_receipt and current[0] == self.desired_content(entry)
            )
            note = "adopt as Nacre's" if created else "adopt, save original"
        elif self.matches(entry, files):
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
        self.check_runtime()
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
            self.withdraw_repository()
            return
        self.record_state(
            f"repository:{repository['name']}",
            {
                "kind": "repository",
                "name": repository["name"],
                "path": repository["path"],
                "include": repository["include"],
            },
        )
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
        self.withdraw_extensions()
        for record in self.withdrawn():
            self.withdraw(record)
        for entry in d["etc"]:
            self.write_entry(entry)
        for block in d["blocks"]:
            self.put(block["path"], self.with_block(block), block["action"])
        self.initramfs()
        groups_changed = self.groups()
        self.withdraw_groups()
        self.record_extensions()
        if self.pending("units"):
            self.systemd.daemon_reload()
            self.clear("units")
            self.actions += 1
        for unit in d["units"]:
            if unit["start"]:
                self.start_unit(unit)
        print(
            f"Core converged: {self.updates} files updated, {self.actions} runtime actions."
        )
        if groups_changed:
            print("Group membership changed; log out and back in.")

    def start_unit(self, unit: UnitEntry) -> None:
        """Enable and start a unit; a unit started now needs no trigger restart."""
        name = unit["name"]
        running = self.systemctl_ok("is-active", "--quiet", name)
        self.converge_unit(name)
        # A socket restart that stopped after its stops still has units to start.
        if not running and self.saved_triggered(name) is None:
            if unit["triggers"] is not None:
                self.receipt["triggers"][name] = unit["triggers"]
                self.save_receipt()
            self.clear(restart_action(name))

    def restart_units(self) -> None:
        """Restart running units whose file or triggers changed; record triggers."""
        triggers = self.receipt["triggers"]
        declared = {unit["name"]: unit for unit in self.desired["units"]}
        for name, unit in declared.items():
            wanted = unit["triggers"]
            changed = wanted is not None and triggers.get(name) != wanted
            pending = self.pending(restart_action(name))
            running = self.systemctl_ok("is-active", "--quiet", name)
            saved = self.saved_triggered(name)
            if saved is not None:
                self.start_socket(name, saved)
                self.actions += 1
            elif (changed or pending) and running:
                self.restart_unit(name)
                self.actions += 1
            if changed and wanted is not None:
                triggers[name] = wanted
                self.save_receipt()
            self.clear(restart_action(name))
        stale = [
            name
            for name in triggers
            if name not in declared or declared[name]["triggers"] is None
        ]
        for name in stale:
            del triggers[name]
            self.save_receipt()
        # Restart markers of withdrawn units have nothing left to restart.
        for marker in self.files.path(STATE).glob("restart-*.pending"):
            unit = marker.name.removeprefix("restart-").removesuffix(".pending")
            if unit not in declared:
                marker.unlink()

    def stopping_triggers(self, name: str) -> list[str] | None:
        """The units that a restart of `name` must stop, or None for a plain restart.

        systemd refuses to restart an Accept=no socket while its service
        runs. An Accept=yes socket restarts and keeps its connections.
        """
        if not name.endswith(".socket"):
            return None
        props = self.systemd.show(name, properties=["Accept", "Triggers"])
        if props.get("Accept") == "yes":
            return None
        return props.get("Triggers", "").split()

    def restart_unit(self, name: str) -> None:
        triggered = self.stopping_triggers(name)
        if triggered is None:
            self.systemd.restart(name)
            return
        active = [
            unit
            for unit in triggered
            if self.systemctl_ok("is-active", "--quiet", unit)
        ]
        # Record the units to start again before the first stop.
        self.files.write(self.marker(restart_action(name)), json.dumps(active) + "\n")
        self.systemd.stop(name)
        for unit in triggered:
            self.systemd.stop(unit)
        self.start_socket(name, active)

    def saved_triggered(self, name: str) -> list[str] | None:
        """The units that an interrupted socket restart still has to start."""
        text = self.files.read(self.marker(restart_action(name))).strip()
        if not text:
            return None
        try:
            saved = json.loads(text)
        except json.JSONDecodeError:
            saved = None
        if not isinstance(saved, list) or not all(
            isinstance(unit, str) for unit in cast(list[Any], saved)
        ):
            raise Conflict(f"invalid restart marker of {name}")
        return cast(list[str], saved)

    def start_socket(self, name: str, triggered: list[str]) -> None:
        self.systemd.start(name)
        for unit in triggered:
            self.systemd.start(unit)

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
                # Record first: a crash after the change still leaves its record.
                self.record_state(f"group:{group}", {"kind": "group", "name": group})
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
        self.restart_units()
        # Compare runtime values too: unchanged files must not conceal drift.
        self.converge_kernel()
        self.converge_capabilities()
        self.withdraw_runtime()
        print(
            f"Core runtime converged: 0 files updated, {self.actions} runtime actions."
        )

    def converge_kernel(self) -> None:
        """Load the declared modules and set the declared sysctl values.

        Each record is saved before its change, so a crash in between still
        leaves a record that withdrawal reverts.
        """
        d = self.desired
        for module in d["kernelModules"]:
            if not (self.root / "sys/module" / module).is_dir():
                self.record_state(
                    f"module:{module}", {"kind": "module", "name": module}
                )
                self.run("modprobe", module)
                self.actions += 1
        for key, value in d["sysctl"].items():
            current = self.run("sysctl", "-n", key).stdout.strip()
            record = self.state_records.get(f"sysctl:{key}")
            if current != value or record is not None:
                previous = record["previous"] if record else current
                self.record_state(
                    f"sysctl:{key}",
                    {
                        "kind": "sysctl",
                        "name": key,
                        "applied": value,
                        "previous": previous,
                    },
                )
            if current != value:
                self.run("sysctl", "-w", f"{key}={value}")
                self.actions += 1

    def converge_capabilities(self) -> None:
        """Set the declared file capabilities, each recorded before its change."""
        d = self.desired
        for entry in d["fileCapabilities"]:
            target = self.resolve(entry["path"])
            expected = f"{target} {entry['capability']}"
            if self.run("getcap", target).stdout.strip() != expected:
                self.record_state(
                    f"capability:{entry['path']}",
                    {
                        "kind": "capability",
                        "name": entry["path"],
                        "target": target,
                        "capability": entry["capability"],
                    },
                )
                self.run("setcap", entry["capability"].replace("=", "+"), target)
                self.actions += 1

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
            changes += self.plan_restart(unit)
        changes += [
            Change("~", f"restart {restart['unit']} (pending)")
            for restart in d["restarts"]
            if self.pending(restart["action"])
        ]
        return (
            changes
            + self.plan_kernel()
            + self.plan_capabilities()
            + self.plan_runtime_withdrawals()
        )

    def plan_runtime_withdrawals(self) -> list[Change]:
        """The runtime state that withdrawal returns to its state before Nacre."""
        d = self.desired
        changes: list[Change] = []
        for key in self.state_withdrawn("group", set(d["groups"]), purge=False):
            group = self.state_records[key]["name"]
            if group != "wheel":
                changes.append(Change("~", f"remove {d['user']} from group {group}"))
        declared = {entry["path"] for entry in d["fileCapabilities"]}
        for key in self.state_withdrawn("capability", declared, purge=False):
            record = self.state_records[key]
            note = f"clear {record['capability']} on {record['target']}"
            changes.append(Change("~", note))
        for key in self.state_withdrawn("sysctl", set(d["sysctl"]), purge=False):
            record = self.state_records[key]
            value = self.boot_value(record["name"]) or record["previous"]
            if value is not None and value != record["applied"]:
                note = f"sysctl {record['name']}: {record['applied']} -> {value}"
                changes.append(Change("~", note))
        for key in self.state_withdrawn("module", set(d["kernelModules"]), purge=False):
            changes.append(
                Change("~", f"unload kernel module {self.state_records[key]['name']}")
            )
        declared_extensions = {extension["name"] for extension in d["extensions"]}
        for key in self.state_withdrawn("extension", declared_extensions, purge=False):
            record = self.state_records[key]
            action = "run the purge phase of" if record["purge"] else "forget"
            changes.append(Change("~", f"{action} removed extension {record['name']}"))
        if d["repository"] is None:
            changes += [
                Change("~", f"remove repository {self.state_records[key]['name']}")
                for key in self.state_withdrawn("repository", set(), purge=True)
            ]
        return changes

    def plan_restart(self, unit: UnitEntry) -> list[Change]:
        """The start, enable and restart changes of one unit."""
        name = unit["name"]
        authored = {
            entry["unit"]: entry["path"]
            for entry in self.desired["etc"]
            if entry["unit"] is not None and not entry["dropin"]
        }
        if name in authored and self.state(authored[name]) is None:
            # systemd cannot know a unit whose file convergence writes first.
            return [Change("+", f"enable and start {name}")] if unit["start"] else []
        changes = self.plan_unit(name) if unit["start"] else []
        if not self.systemctl_ok("is-active", "--quiet", name):
            return changes
        if self.pending(restart_action(name)):
            changes.append(Change("~", f"{self.restart_label(name)} (pending)"))
        elif (
            unit["triggers"] is not None
            and self.receipt["triggers"].get(name) != unit["triggers"]
        ):
            changes.append(
                Change("~", f"{self.restart_label(name)} (triggers changed)")
            )
        return changes

    def restart_label(self, name: str) -> str:
        triggered = self.stopping_triggers(name) or []
        if any(self.systemctl_ok("is-active", "--quiet", unit) for unit in triggered):
            return f"restart {name} and its service"
        return f"restart {name}"

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
        """Uninstall: withdraw every record, then Nacre's own prerequisite state.

        Every record is checked for drift before any change. Units other than
        network units and ufw.service stop first. Recorded files, runtime state
        and the repository are withdrawn, then the nix.conf and initramfs
        blocks, with a rebuild of the images. systemd reloads after unit files
        went away. Network units stop last, so a purge over SSH completes its
        boot work first. Packages, accounts and mutable data stay.
        """
        self.recover_intent()
        self.check_etc(converging=False, purge=True)
        self.check_runtime(purge=True)
        self.withdraw_extensions(purge=True)
        self.purge_units(network=False)
        self.withdraw_repository()
        for record in self.withdrawn(purge=True):
            self.withdraw(record)
        self.withdraw_groups(purge=True)
        self.withdraw_runtime(purge=True)
        for block in self.desired["purge"]["blocks"]:
            self.purge_block(block)
        if self.pending("units"):
            self.systemd.daemon_reload()
        self.purge_units(network=True)
        state = self.files.path(STATE)
        if state.exists():
            shutil.rmtree(state)
        print("Nacre is uninstalled; packages, accounts and user data were preserved.")

    def purge_units(self, network: bool) -> None:
        """Disable the managed units of one group; ufw.service keeps running.

        Stopping ufw.service would flush the rules that purge keeps.
        """
        d = self.desired
        for unit in d["units"]:
            name = unit["name"]
            if (
                unit["start"]
                and name != "ufw.service"
                and (name in NETWORK_UNITS) == network
                and self.systemctl_ok("is-enabled", "--quiet", name)
            ):
                self.systemd.disable(name, now=True)

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
            # A purge that stopped before its rebuild resumes the rebuild.
            if block["action"] == "initramfs" and self.pending("initramfs"):
                self.initramfs()
            return
        if block["action"] == "initramfs":
            self.mark("initramfs")  # Record the intent before the boot change.
        self.files.write(block["path"], text)
        if block["action"] == "initramfs":
            self.initramfs()
        if block["action"] == "nix-daemon" and self.systemctl_ok(
            "is-active", "--quiet", "nix-daemon.service"
        ):
            self.systemd.restart("nix-daemon.service")
