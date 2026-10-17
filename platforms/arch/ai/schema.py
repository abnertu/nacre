"""The AI manifest that platforms/arch/ai/default.nix generates.

Without llama.cpp the manifest is only {"llama": false}. Nested sections type
the fields this adapter reads.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


class Model(TypedDict):
    repository: str
    revision: str
    file: str
    path: str
    sha256: str


class Source(TypedDict):
    repository: str
    revision: str
    grammarRepetitionThreshold: int
    installPrefix: str


class Server(TypedDict):
    host: str
    port: int
    modelsMax: int


class Generated(TypedDict):
    switcherConfig: str
    switcherUnit: str
    caddyMain: str
    caddySite: str
    packageCaddy: str


class Paths(TypedDict):
    switcherConfig: str
    switcherUnit: str
    caddyMain: str
    caddySite: str


class Unmanaged(TypedDict):
    llama: Literal[False]


class AIManifest(TypedDict):
    llama: Literal[True]
    proxy: bool
    source: Source
    server: Server
    profiles: dict[str, Any]
    switcher: dict[str, Any]
    models: dict[str, Model]
    model: dict[str, Any]
    localPort: int
    httpsPort: int
    paths: Paths
    generated: Generated
