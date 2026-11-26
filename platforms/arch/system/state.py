"""The system receipt: what the system adapter changed, and the values before.

It mirrors the core receipt (platforms/arch/core/receipts.py). Each adapter
ships only its own directory, so this small copy keeps the two independent.
Records are keyed `kind:name`, which `nacre forget` accepts.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, TypedDict, cast

from nix_adapter import Conflict, Files

STATE = "/var/lib/nix-config/arch"
RECEIPT = f"{STATE}/receipts/system.json"
ADOPTED = f"{STATE}/adopted"
VERSION = 1
# Record kinds that `nacre forget` routes to this adapter.
KINDS = (
    "dropin",
    "locale",
    "console",
    "timezone",
    "hostname",
    "firewall",
    "ufw",
    "hotspot",
)


class Receipt(TypedDict):
    version: int
    records: dict[str, dict[str, Any]]


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load_receipt(files: Files) -> Receipt:
    """The receipt, or an empty one on a host without it.

    Raise `Conflict` if the file is corrupt or has an unknown format.
    """
    if not files.path(RECEIPT).exists():
        return {"version": VERSION, "records": {}}
    try:
        value: object = json.loads(files.read(RECEIPT))
    except ValueError:
        raise Conflict(
            f"receipt {RECEIPT} is corrupt; inspect it, then restore it or remove it"
        ) from None
    data = cast("dict[str, object]", value) if isinstance(value, dict) else {}
    if data.get("version") != VERSION or not isinstance(data.get("records"), dict):
        raise Conflict(f"receipt {RECEIPT} has an unknown format")
    return cast(Receipt, data)


def save_receipt(files: Files, receipt: Receipt) -> None:
    files.write(RECEIPT, json.dumps(receipt, indent=2, sort_keys=True) + "\n", 0o600)


def save_original(files: Files, path: str, text: str) -> str:
    """Save the text that a first write replaces; return where it went.

    The text can hold secrets: it stays root-only and is never printed.
    """
    saved = f"{ADOPTED}/{digest(path)}.json"
    files.write(saved, json.dumps({"path": path, "text": text}) + "\n", 0o600)
    return saved


def load_original(files: Files, saved: str) -> str:
    """The saved original text; raise `Conflict` if it is gone or corrupt."""
    try:
        value: object = json.loads(files.read(saved))
    except ValueError:
        raise Conflict(f"saved original {saved} is corrupt") from None
    if not isinstance(value, dict) or not isinstance(
        cast("dict[str, object]", value).get("text"), str
    ):
        raise Conflict(f"saved original {saved} is missing")
    return cast("dict[str, str]", value)["text"]
