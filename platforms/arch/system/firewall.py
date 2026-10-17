"""UFW convergence for declared service ports and the hotspot."""

from __future__ import annotations

import contextlib
import ipaddress
import re
import shlex
from collections.abc import Sequence
from typing import Any

from nix_adapter import Change, Conflict, Native, assignments


def format_port_range(from_port: int | str, to_port: int | str | None = None) -> str:
    """Format a port or port range as a string like '80' or '27031:27036'."""
    return (
        str(from_port)
        if to_port is None or to_port == from_port
        else f"{from_port}:{to_port}"
    )


def parse_ufw_status(text: str) -> dict[str, Any]:
    """Parse 'ufw status verbose' output into structured policy and rules."""
    if text.strip() == "Status: inactive":
        return {"active": False, "rules": set()}
    if not text.startswith("Status: active\n"):
        raise Conflict("unrecognized UFW status")

    policy = re.search(
        r"^Default: (deny|allow|reject) \(incoming\), (deny|allow|reject) \(outgoing\), (deny|allow|reject|disabled) \(routed\)$",
        text,
        re.M,
    )
    logging = re.search(r"^Logging: (off|on \((low|medium|high|full)\))$", text, re.M)
    profiles = re.search(r"^New profiles: (skip|allow|deny|reject)$", text, re.M)
    if not policy or not logging or not profiles:
        raise Conflict("incomplete UFW status")

    rules: set[tuple[str, str, bool]] = set()
    for line in text.splitlines():
        match = re.fullmatch(
            r"(\d+(?::\d+)?)/(tcp|udp)\s*(\(v6\))?\s+ALLOW IN\s+Anywhere(?: \(v6\))?\s*(?:#.*)?",
            line,
        )
        if match:
            port, protocol, v6 = match.groups()
            rules.add((port, protocol, bool(v6)))
        elif re.search(r"\b(DENY|REJECT|LIMIT)\b", line):
            raise Conflict(
                "UFW has restrictive rules requiring explicit ownership review"
            )

    return {
        "active": True,
        "rules": rules,
        "policy": policy.groups(),
        "logging": logging[2] or "off",
        "profiles": profiles[1],
    }


def check_kernel_rule(
    chain: str,
    protocol: str,
    port: str,
    v6: bool = False,
    runner: Native | None = None,
) -> bool:
    """Check if a specific port acceptance rule is loaded in the netfilter chain."""
    r = runner or Native()
    command = "ip6tables" if v6 else "iptables"
    match = ["-m", "multiport", "--dports", port] if ":" in port else ["--dport", port]
    return (
        r.run(
            command,
            "-w",
            "5",
            "-C",
            chain,
            "-p",
            protocol,
            *match,
            "-j",
            "ACCEPT",
            check=False,
        ).returncode
        == 0
    )


def check_kernel_policy(runner: Native | None = None) -> bool:
    """Verify that default kernel policies for INPUT, OUTPUT, FORWARD match UFW defaults."""
    r = runner or Native()
    for command in ("iptables", "ip6tables"):
        for chain, policy in (
            ("INPUT", "DROP"),
            ("OUTPUT", "ACCEPT"),
            ("FORWARD", "DROP"),
        ):
            result = r.run(command, "-w", "5", "-S", chain, check=False)
            if (
                result.returncode
                or f"-P {chain} {policy}" not in result.stdout.splitlines()
            ):
                return False
    return True


def canonical_rule(
    words: Sequence[str],
) -> tuple[tuple[str, Any], ...] | None:
    """Normalize UFW's show-added syntax; unrelated rule forms remain unowned."""
    w = list(words)
    if w[:1] == ["ufw"]:
        w.pop(0)
    routed = w[:1] == ["route"]
    if routed:
        w.pop(0)
    if w[:1] != ["allow"]:
        return None
    w.pop(0)
    result: dict[str, Any] = {"routed": routed, "from": "0.0.0.0/0", "to": "0.0.0.0/0"}
    try:
        while w:
            key = w.pop(0)
            if key in ("in", "out"):
                if w.pop(0) != "on":
                    return None
                result[key] = w.pop(0)
            elif key in ("from", "to"):
                value = w.pop(0)
                result[key] = str(
                    ipaddress.ip_network(
                        "0.0.0.0/0" if value == "any" else value, strict=False
                    )
                )
            elif key in ("port", "proto"):
                result[key] = w.pop(0)
            elif key == "comment":
                w.pop(0)
            else:
                return None
    except (IndexError, ValueError):
        return None
    return tuple(sorted(result.items()))


def hotspot_firewall_rules(
    interface: str, uplink: str, address: str
) -> list[tuple[list[str], list[str]]]:
    """Return scoped UFW commands and their corresponding IPv4 kernel rules for an AP."""
    addr = ipaddress.IPv4Interface(address)
    subnet, host = str(addr.network), str(addr.ip)
    rules: list[tuple[list[str], list[str]]] = [
        (
            ["allow", "in", "on", interface, "proto", "udp", "to", "any", "port", "67"],
            [
                "ufw-user-input",
                "-i",
                interface,
                "-p",
                "udp",
                "--dport",
                "67",
                "-j",
                "ACCEPT",
            ],
        )
    ]
    for protocol in ("udp", "tcp"):
        rules.append(
            (
                [
                    "allow",
                    "in",
                    "on",
                    interface,
                    "proto",
                    protocol,
                    "from",
                    subnet,
                    "to",
                    host,
                    "port",
                    "53",
                ],
                [
                    "ufw-user-input",
                    "-i",
                    interface,
                    "-s",
                    subnet,
                    "-d",
                    host,
                    "-p",
                    protocol,
                    "--dport",
                    "53",
                    "-j",
                    "ACCEPT",
                ],
            )
        )
    rules.append(
        (
            [
                "route",
                "allow",
                "in",
                "on",
                interface,
                "out",
                "on",
                uplink,
                "from",
                subnet,
            ],
            [
                "ufw-user-forward",
                "-i",
                interface,
                "-o",
                uplink,
                "-s",
                subnet,
                "-j",
                "ACCEPT",
            ],
        )
    )
    return rules


class Firewall:
    """Owns declared UFW rules; other owners' rules are preserved."""

    def __init__(self, system: Any):
        self.system = system
        self.files = system.files
        self.desired = system.desired.get("firewall") or {}

    def run(self, *args: Any, **kwargs: Any) -> Any:
        return self.system.run(*args, **kwargs)

    def act(self, *command: str) -> None:
        self.files.mark("firewall")
        self.run("ufw", *command)
        self.system.actions += 1

    def snapshot(self) -> dict[str, Any]:
        return parse_ufw_status(self.run("ufw", "status", "verbose").stdout)

    def preflight(self, installed: bool = False) -> None:
        defaults = assignments(self.files.read("/etc/default/ufw"))
        if defaults:
            if defaults.get("IPV6") != "yes" or defaults.get("MANAGE_BUILTINS") != "no":
                raise Conflict(
                    "UFW requires IPv6 and MANAGE_BUILTINS=no to preserve other owners"
                )
            for key, value in [
                ("DEFAULT_INPUT_POLICY", "DROP"),
                ("DEFAULT_OUTPUT_POLICY", "ACCEPT"),
                ("DEFAULT_FORWARD_POLICY", "DROP"),
            ]:
                if defaults.get(key) != value:
                    raise Conflict(
                        "UFW default policy adoption requires operator review"
                    )
        elif installed:
            raise Conflict("UFW defaults are unavailable")

        for name in (
            "ufw.conf",
            "user.rules",
            "user6.rules",
            "before.rules",
            "before6.rules",
            "after.rules",
            "after6.rules",
        ):
            self.files.read("/etc/ufw/" + name)

        state = self.system.unit("nftables.service")
        if state.get("ActiveState") in ("active", "activating") or state.get(
            "UnitFileState"
        ) in ("enabled", "enabled-runtime"):
            raise Conflict("standalone nftables service conflicts with UFW ownership")

        if installed:
            self.system.ready_unit("ufw.service")
            self.snapshot()

    def kernel_rule(self, rule: dict[str, Any], v6: bool = False) -> bool:
        return check_kernel_rule(
            chain="ufw6-user-input" if v6 else "ufw-user-input",
            protocol=rule["protocol"],
            port=format_port_range(rule["fromPort"], rule.get("toPort")),
            v6=v6,
            runner=self.system.runner,
        )

    def kernel_drift(self, rules: list[dict[str, Any]]) -> bool:
        return not check_kernel_policy(runner=self.system.runner) or any(
            not self.kernel_rule(rule, v6) for rule in rules for v6 in (False, True)
        )

    def plan(self) -> list[Change]:
        rules = self.desired.get("rules", [])
        logging = self.desired.get("logging", "low")
        state = self.snapshot()
        changes: list[Change] = []
        for rule in rules:
            port = format_port_range(rule["fromPort"], rule.get("toPort"))
            wanted = {(port, rule["protocol"], v6) for v6 in (False, True)}
            if not wanted <= state["rules"]:
                changes.append(Change("+", f"ufw allow in {port}/{rule['protocol']}"))
        if state["active"] and state["logging"] != logging:
            changes.append(Change("~", f"ufw logging {state['logging']} -> {logging}"))
        if state["active"] and state["profiles"] != "skip":
            changes.append(Change("~", f"ufw new profiles {state['profiles']} -> skip"))
        if not state["active"]:
            changes.append(Change("~", "enable ufw"))
        elif self.files.pending("firewall") or self.kernel_drift(rules):
            changes.append(Change("~", "reload ufw to restore kernel rules"))
        hotspot = self.system.desired.get("hotspot")
        if hotspot is not None:
            existing = set()
            for line in self.run("ufw", "show", "added").stdout.splitlines():
                with contextlib.suppress(ValueError):
                    existing.add(canonical_rule(shlex.split(line)))
            for command, _ in hotspot_firewall_rules(
                hotspot["interface"], hotspot["uplink"], hotspot["address"]
            ):
                if canonical_rule(command) not in existing:
                    changes.append(Change("+", "ufw " + " ".join(command)))
        changes += self.system.plan_unit("ufw.service")
        return changes

    def converge(self) -> None:
        self.converge_service_rules()
        hotspot = self.system.desired.get("hotspot")
        if hotspot is not None:
            self.converge_hotspot_rules(hotspot)
        self.files.clear("firewall")

    def converge_service_rules(self) -> None:
        rules = self.desired.get("rules", [])
        logging = self.desired.get("logging", "low")
        profiles = "skip"
        state = self.snapshot()
        pending = self.files.pending("firewall")
        expected = {
            (
                format_port_range(rule["fromPort"], rule.get("toPort")),
                rule["protocol"],
                v6,
            )
            for rule in rules
            for v6 in (False, True)
        }

        for rule in rules:
            port = format_port_range(rule["fromPort"], rule.get("toPort"))
            if (
                not {(port, rule["protocol"], v6) for v6 in (False, True)}
                <= state["rules"]
            ):
                self.act("allow", "in", f"{port}/{rule['protocol']}")
        if state.get("logging") != logging:
            self.act("logging", logging)
        if state.get("profiles") != profiles:
            self.act("app", "default", profiles)
        if not state["active"]:
            self.act("--force", "enable")
        elif pending or self.kernel_drift(rules):
            self.act("reload")

        self.system.service("ufw.service", "firewall")

        final = self.snapshot()
        if (
            not final["active"]
            or final["policy"] != ("deny", "allow", "deny")
            or final["logging"] != logging
            or final["profiles"] != profiles
            or not expected <= final["rules"]
            or self.kernel_drift(rules)
        ):
            self.files.mark("firewall")
            raise Conflict("UFW policy or kernel rules did not converge")

    def converge_hotspot_rules(self, hotspot: dict[str, Any]) -> None:
        rules = hotspot_firewall_rules(
            hotspot["interface"], hotspot["uplink"], hotspot["address"]
        )
        existing = set()
        for line in self.run("ufw", "show", "added").stdout.splitlines():
            try:
                existing.add(canonical_rule(shlex.split(line)))
            except ValueError:
                continue
        for command, _ in rules:
            if canonical_rule(command) not in existing:
                self.act(*command)

        def missing() -> bool:
            return any(
                self.run("iptables", "-w", "5", "-C", *rule, check=False).returncode
                for _, rule in rules
            )

        if missing():
            self.act("reload")
        if missing():
            raise Conflict("hotspot firewall rules did not converge")
