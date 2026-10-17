"""The system settings manifest that platforms/arch/system/default.nix generates.

A section is null when its setting is not managed.
"""

from __future__ import annotations

from typing import TypedDict


class Locale(TypedDict):
    generated: list[str]
    lang: str


class Console(TypedDict):
    keymap: str
    font: str | None


class TimeSync(TypedDict):
    provider: str
    servers: list[str]


class Journal(TypedDict):
    storage: str
    systemMaxUseMiB: int | None
    systemKeepFreeMiB: int | None
    runtimeMaxUseMiB: int | None
    maxRetentionDays: int | None


class Power(TypedDict):
    powerKey: str | None
    lidSwitch: str | None


class Trim(TypedDict):
    enable: bool


class Rule(TypedDict):
    protocol: str
    fromPort: int
    toPort: int | None


class Firewall(TypedDict):
    provider: str
    incoming: str
    outgoing: str
    routed: str
    logging: str
    rules: list[Rule]


class Hotspot(TypedDict):
    connection: str
    ssid: str
    interface: str
    uplink: str
    band: str
    channel: int
    address: str
    autoconnect: bool
    ipv6: str


class Paths(TypedDict):
    vconsole: str
    localeGen: str
    localeConf: str
    localtime: str
    hostnameFile: str


class SystemManifest(TypedDict):
    locale: Locale | None
    timeZone: str | None
    hostname: str | None
    console: Console | None
    timeSync: TimeSync | None
    journal: Journal | None
    power: Power | None
    trim: Trim | None
    firewall: Firewall | None
    hotspot: Hotspot | None
    files: dict[str, str]
    trimDropin: str
    paths: Paths
