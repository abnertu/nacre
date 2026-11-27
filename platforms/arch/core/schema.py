"""The core manifest that platforms/arch/core/default.nix generates."""

from __future__ import annotations

from typing import TypedDict


class EtcEntry(TypedDict):
    """One enabled environment.etc entry."""

    name: str
    path: str
    # Exactly one of text, source (a store file) and target (a symlink).
    text: str | None
    source: str | None
    target: str | None
    mode: str
    group: str
    adopt: bool
    # The unit whose file this is: a whole unit, or a drop-in when `dropin`.
    unit: str | None
    dropin: bool
    restartIfChanged: bool


class UnitEntry(TypedDict):
    """An enabled unit that is not a drop-in."""

    name: str
    # Enable and keep active: packaged units, and authored units that a target wants.
    start: bool
    # sha256 of restartTriggers, or None without triggers.
    triggers: str | None


class Block(TypedDict):
    path: str
    name: str
    text: str
    action: str
    create: bool


class Repository(TypedDict):
    name: str
    path: str
    text: str
    source: str
    include: str


class Restart(TypedDict):
    action: str
    unit: str
    onlyIfActive: bool


class FileCapability(TypedDict):
    path: str
    capability: str


class Purge(TypedDict):
    blocks: list[Block]


class Extension(TypedDict):
    """A feature or machine adapter, as its last deployment ran it."""

    name: str
    adapter: str
    manifest: str
    python: str
    # Whether the adapter has a purge phase that retires its state.
    purge: bool


class CoreManifest(TypedDict):
    user: str
    etc: list[EtcEntry]
    repository: Repository | None
    units: list[UnitEntry]
    blocks: list[Block]
    initramfsImages: list[str]
    groups: list[str]
    restarts: list[Restart]
    kernelModules: list[str]
    sysctl: dict[str, str]
    fileCapabilities: list[FileCapability]
    purge: Purge
    extensions: list[Extension]


class CoreRequest(CoreManifest, total=False):
    """The manifest, plus the record that `arch-switch --forget` drops."""

    forget: str
