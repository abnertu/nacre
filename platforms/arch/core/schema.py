"""The core manifest that platforms/arch/core/default.nix generates."""

from __future__ import annotations

from typing import TypedDict


class ManagedFile(TypedDict):
    path: str
    text: str
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
    files: list[ManagedFile]
    repository: Repository | None
    units: list[str]
    blocks: list[Block]
    initramfsImages: list[str]
    groups: list[str]
    reloadUnits: bool
    restarts: list[Restart]
    kernelModules: list[str]
    sysctl: dict[str, str]
    fileCapabilities: list[FileCapability]
    purge: Purge
