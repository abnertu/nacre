"""Adopts one prepared NetworkManager AP and keeps its public properties."""

from __future__ import annotations
import ipaddress
import json
import re
from typing import Any

from nix_adapter import Conflict


def validate_hotspot_address(address_str: str) -> ipaddress.IPv4Interface:
    """Validate that the address is a usable IPv4 host address with subnet <= 30."""
    try:
        address = ipaddress.IPv4Interface(address_str)
        if address.network.prefixlen > 30 or address.ip in (
            address.network.network_address,
            address.network.broadcast_address,
        ):
            raise ValueError
        return address
    except ValueError:
        raise Conflict(
            "hotspot requires a usable IPv4 host address and subnet"
        ) from None


def hotspot_properties(desired: dict[str, Any]) -> dict[str, str]:
    """Build the dictionary of NetworkManager connection properties for the AP."""
    return {
        "connection.interface-name": desired["interface"],
        "connection.autoconnect": "yes" if desired.get("autoconnect") else "no",
        "802-11-wireless.ssid": desired["ssid"],
        "802-11-wireless.band": desired["band"],
        "802-11-wireless.channel": str(desired["channel"]),
        "ipv4.method": "shared",
        "ipv4.addresses": desired["address"],
        "ipv4.shared-dhcp-range": "",
        "ipv4.shared-dhcp-lease-time": "0",
        "ipv6.method": desired.get("ipv6", "shared"),
    }


class Hotspot:
    def __init__(self, system: Any):
        self.system = system
        self.files = system.files
        self.desired = system.desired["hotspot"]
        self.uuid = ""

    def run(self, *args: Any, **kwargs: Any) -> Any:
        return self.system.run(*args, **kwargs)

    def read(self, field: str) -> str:
        return self.run(
            "nmcli",
            "--escape",
            "no",
            "-g",
            field,
            "connection",
            "show",
            "uuid",
            self.uuid,
        ).stdout.strip()

    def find_uuid(self) -> str:
        lines = self.run(
            "nmcli", "--escape", "no", "-t", "-f", "UUID,NAME", "connection", "show"
        ).stdout.splitlines()
        matches = [
            line.split(":", 1)[0]
            for line in lines
            if ":" in line and line.split(":", 1)[1] == self.desired["connection"]
        ]
        if len(matches) != 1 or not re.fullmatch(r"[0-9a-fA-F-]{36}", matches[0]):
            raise Conflict(
                "prepare exactly one named hotspot connection and its credentials in NetworkManager before deployment"
            )
        return matches[0]

    def preflight(self) -> None:
        d = self.desired
        validate_hotspot_address(d["address"])
        if d["interface"] == d["uplink"]:
            raise Conflict("hotspot and uplink interfaces must differ")
        self.system.ready_unit("NetworkManager.service")

        links = json.loads(self.run("ip", "-j", "link", "show").stdout)
        if not isinstance(links, list) or any(
            not isinstance(link, dict) or not isinstance(link.get("ifname"), str)
            for link in links
        ):
            raise Conflict("invalid native link inventory")
        available = {link["ifname"] for link in links}
        for role, name in (("wireless", d["interface"]), ("uplink", d["uplink"])):
            if name not in available:
                raise Conflict(f"declared hotspot {role} interface is missing: {name}")

        device_uuid = self.run(
            "nmcli", "-g", "GENERAL.CON-UUID", "device", "show", d["interface"]
        ).stdout.strip()
        self.uuid = self.find_uuid()
        if (
            self.read("connection.type") != "802-11-wireless"
            or self.read("802-11-wireless.mode") != "ap"
        ):
            raise Conflict("prepared hotspot must be a Wi-Fi AP connection")
        if self.read("802-11-wireless-security.key-mgmt") not in ("wpa-psk", "sae"):
            raise Conflict("prepared hotspot must use WPA personal security")
        if self.read("connection.interface-name") not in ("", d["interface"]):
            raise Conflict("prepared hotspot belongs to a different interface")
        if device_uuid not in ("", "--", self.uuid):
            raise Conflict("hotspot interface is in use by another connection")

    def selected(self) -> bool:
        active = self.run("nmcli", "-g", "UUID", "connection", "show", "--active")
        return self.uuid in active.stdout.splitlines()

    def active(self) -> bool:
        """The AP is selected, on the declared radio and holds its address."""
        d = self.desired
        if not self.selected():
            return False
        wireless = self.run("iw", "dev", d["interface"], "info").stdout
        channel = re.search(r"^\s*channel (\d+) ", wireless, re.M)
        ssid = re.search(r"^\s*ssid (.*)$", wireless, re.M)
        if (
            not channel
            or int(channel[1]) != d["channel"]
            or not ssid
            or ssid[1] != d["ssid"]
        ):
            return False
        data = json.loads(
            self.run("ip", "-j", "-4", "address", "show", "dev", d["interface"]).stdout
        )
        address = ipaddress.IPv4Interface(d["address"])
        return any(
            a.get("local") == str(address.ip)
            and a.get("prefixlen") == address.network.prefixlen
            for link in data
            for a in link.get("addr_info", [])
        )

    def converge(self) -> None:
        self.preflight()
        changes: list[str] = []
        for field, expected in hotspot_properties(self.desired).items():
            actual = self.read(field)
            if field == "ipv4.shared-dhcp-lease-time":
                actual = actual.split()[0]
            if actual == "--":
                actual = ""
            if actual != expected:
                changes.extend((field, expected))

        pending = self.files.pending("hotspot")
        marker = self.files.marker("hotspot")
        resume = (
            pending
            and self.files.path(marker).exists()
            and self.files.read(marker) == "activate\n"
        )
        activate = self.selected() or self.desired.get("autoconnect", False) or resume

        if changes:
            self.files.mark("hotspot", "activate\n" if activate else "pending\n")
            self.run("nmcli", "connection", "modify", "uuid", self.uuid, *changes)
            self.system.actions += 1
        if activate and (changes or pending or not self.active()):
            self.files.mark("hotspot", "activate\n")
            self.run(
                "nmcli",
                "connection",
                "up",
                "uuid",
                self.uuid,
                "ifname",
                self.desired["interface"],
            )
            self.system.actions += 1
            if not self.active():
                raise Conflict(
                    "hotspot activation did not converge; pending action retained"
                )
        self.files.clear("hotspot")
