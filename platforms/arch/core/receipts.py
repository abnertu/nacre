"""The core receipt: what Nacre wrote, and the originals it replaced.

The receipt is the only proof that Nacre owns a native resource. Each change
writes an intent first, then the change, then the receipt, then clears the
intent, so an interrupted run can complete its record.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal, NotRequired, TypedDict, cast

from nix_adapter import Conflict, Files

STATE = "/var/lib/nix-config/arch"
RECEIPT = f"{STATE}/receipts/core.json"
INTENT = f"{STATE}/receipts/core.intent"
ADOPTED = f"{STATE}/adopted"
VERSION = 1
# Written into the nix.conf settings block: a host with the block but without
# this line was deployed by a Nacre version without receipts.
RECEIPT_LINE = "# nix-config receipts 1"


class FileRecord(TypedDict):
    """A file that Nacre wrote, with the state it left."""

    kind: Literal["file"]
    name: str
    path: str
    sha256: str
    mode: str
    uid: int
    gid: int
    action: str | None
    # The adopted original to restore on withdrawal; None when Nacre created it.
    original: str | None


class Original(TypedDict):
    """The file that an adoption replaced. It can hold secrets: never print it."""

    path: str
    text: str
    mode: str
    uid: int
    gid: int
    package: str | None
    version: str | None
    date: str


class Intent(TypedDict):
    """A change that started: a write of `record`, or a withdrawal of `key`."""

    op: Literal["write", "withdraw"]
    key: str
    record: NotRequired[FileRecord]


class Receipt(TypedDict):
    version: int
    records: dict[str, FileRecord]


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def original_name(path: str) -> str:
    """The host path of the saved original of `path`."""
    return f"{ADOPTED}/{digest(path)}.json"


def file_key(name: str) -> str:
    return f"file:{name}"


def load_json(files: Files, name: str, what: str) -> object | None:
    """The JSON value in `name`, or None if it does not exist.

    Raise `Conflict` if the file is not valid JSON: Nacre never repairs it.
    """
    if not files.path(name).exists():
        return None
    try:
        return json.loads(files.read(name))
    except ValueError:
        raise Conflict(
            f"{what} {name} is corrupt; inspect it, then restore it or remove it"
        ) from None


def load_receipt(files: Files) -> Receipt | None:
    """The receipt, or None on a host without one."""
    value = load_json(files, RECEIPT, "receipt")
    if value is None:
        return None
    if (
        not isinstance(value, dict)
        or cast("dict[str, object]", value).get("version") != VERSION
        or not isinstance(cast("dict[str, object]", value).get("records"), dict)
    ):
        raise Conflict(f"receipt {RECEIPT} has an unknown format")
    return cast(Receipt, value)


def save_json(files: Files, name: str, value: object) -> None:
    files.write(name, json.dumps(value, indent=2, sort_keys=True) + "\n", 0o600)
