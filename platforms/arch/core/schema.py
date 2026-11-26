"""The core manifest that platforms/arch/core/default.nix generates."""

from __future__ import annotations

from typing import TypedDict


class EtcEntry(TypedDict):
    """One enabled environment.etc entry."""

    name: str
    path: str
    text: str
    mode: str
    group: str
    adopt: bool
    action: str | None


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


class OwnedUnit(TypedDict):
    unit: str
    path: str


class Purge(TypedDict):
    blocks: list[Block]
    ownedUnits: list[OwnedUnit]


class CoreManifest(TypedDict):
    user: str
    etc: list[EtcEntry]
    repository: Repository | None
    units: list[str]
    blocks: list[Block]
    initramfsImages: list[str]
    groups: list[str]
    restarts: list[Restart]
    kernelModules: list[str]
    sysctl: dict[str, str]
    fileCapabilities: list[FileCapability]
    purge: Purge


class CoreRequest(CoreManifest, total=False):
    """The manifest, plus the record that `arch-switch --forget` drops."""

    forget: str
