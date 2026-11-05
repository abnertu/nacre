"""Arch system settings. Only packaging invokes this privileged private adapter.

The caller holds the arch-switch deployment lock. Tests inject a filesystem and
native runner directly; production accepts no root/command overrides.
"""

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from firewall import Firewall
from hotspot import Hotspot
from nix_adapter import (
    AdapterContext,
    BaseAdapter,
    Change,
    Conflict,
    Files,
    Native,
    ini,
    locale_gen,
    replace_keys,
)
from nix_adapter.system import (
    check_discard_support,
    get_hostname,
    get_timezone,
    is_ntp_synchronized,
    set_hostname,
    set_timezone,
)
from schema import Console, Locale, SystemManifest

# Host identifiers keep the nix-config namespace, so existing machines need no
# migration.
DROPIN_FILE = "60-nix-config.conf"
LOCALE_BLOCK = "nix-config locales"
TRIM_DROPIN = f"/etc/systemd/system/fstrim.timer.d/{DROPIN_FILE}"
TIMER_BASES = ("/usr/lib", "/usr/local/lib", "/run", "/etc")


# Native commands that convergence of each setting runs.
NATIVE_COMMANDS: dict[str, tuple[str, ...]] = {
    "locale": ("locale", "locale-gen"),
    "timeZone": ("timedatectl",),
    "hostname": ("hostnamectl",),
    "timeSync": ("systemctl", "timedatectl"),
    "journal": ("systemctl", "systemd-tmpfiles", "journalctl"),
    "trim": ("systemctl", "lsblk"),
    "hotspot": ("nmcli", "ip", "iw"),
    "firewall": ("systemctl", "ufw", "iptables", "ip6tables"),
}
# The pending-marker action of each setting.
PENDING_ACTIONS = {
    "locale": "locale",
    "timeZone": "timezone",
    "hostname": "hostname",
    "timeSync": "timesyncd",
    "journal": "journald",
    "console": "console",
    "power": "power",
    "trim": "trim",
    "firewall": "firewall",
    "hotspot": "hotspot",
}


def locale_key(name: str) -> str:
    """A locale name as `locale -a` spells it: lower case, without dashes."""
    return name.lower().replace("-", "")


class System(BaseAdapter[SystemManifest]):
    pending_template = "/var/lib/nix-config/arch/system-{action}.pending"

    def __init__(
        self,
        desired: Mapping[str, Any],
        files: Files | None = None,
        native: Native | None = None,
        context: AdapterContext | None = None,
    ):
        root = files.root if files else Path("/")
        super().__init__(
            desired=cast(SystemManifest, desired),
            root=root,
            native=native,
            files=files,
            context=context,
        )

    def boot_id(self) -> str:
        # A kernel pseudo-file, not a managed path: skip ownership checks.
        path = self.files.root / "proc/sys/kernel/random/boot_id"
        return path.read_text() if path.is_file() else ""

    def service(self, name: str, action: str, restart: bool = False) -> None:
        self.converge_unit(
            name, restart=restart, before_change=lambda: self.files.mark(action)
        )

    def remove(self, name: str) -> bool:
        path = self.files.path(name)
        if not path.exists():
            return False
        if not path.is_file():
            raise Conflict(f"managed path is not a regular file: {name}")
        path.unlink()
        self.files.sync_dir(path.parent)
        return True

    def purge(self) -> None:
        """Withdraw the drop-ins this adapter owns; keep the system's own values.

        Locale, timezone, hostname, console, firewall rules and the hotspot
        profile are the machine's settings, so withdrawing management keeps
        them as they are now.
        """
        d = self.desired
        removed = [
            name
            for name in d["files"]
            if self.remove(f"/etc/systemd/{name}.conf.d/60-nix-config.conf")
        ]
        if d["trim"] is not None and self.remove(
            "/etc/systemd/system/fstrim.timer.d/60-nix-config.conf"
        ):
            removed.append("trim")
        if removed:
            self.systemd.daemon_reload()
        # logind applies at the next boot, as it does on convergence.
        for name, unit in (
            ("timesyncd", "systemd-timesyncd.service"),
            ("journald", "systemd-journald.service"),
        ):
            if name in removed:
                self.run("systemctl", "try-restart", unit)
        print(
            f"System settings purged: {len(removed)} drop-ins removed; locale, timezone, "
            "hostname, console, firewall and hotspot values were kept."
        )

    def localtime(self) -> str | None:
        return get_timezone(native=self.native, root=self.files.root)

    def console(self, desired: Console) -> str:
        values = {"KEYMAP": desired["keymap"]}
        if desired["font"] is not None:
            values["FONT"] = desired["font"]
        path = self.path_str("vconsole", "/etc/vconsole.conf")
        return replace_keys(self.files.read(path), values, source=path)

    def generated_locales(self, path: str, locales: list[str]) -> str:
        """`path` (locale.gen) with `locales` enabled in the managed block."""
        return locale_gen(
            self.files.read(path), locales, block=LOCALE_BLOCK, source=path
        )

    def locale_conf(self, path: str, lang: str) -> str:
        """`path` (locale.conf) with `LANG` set to `lang`."""
        return replace_keys(self.files.read(path), {"LANG": lang}, source=path)

    def trim_dropin(self, content: str) -> tuple[str, str]:
        """The managed fstrim.timer drop-in and its content.

        Raise `Conflict` if another drop-in sets the timer schedule, or sets
        `Persistent=` to anything but `false`.
        """
        self.files.read(TRIM_DROPIN)  # Validate the target path.
        for base in TIMER_BASES:
            directory = self.files.path(base + "/systemd/system/fstrim.timer.d")
            if not directory.exists():
                continue
            for file in directory.glob("*.conf"):
                name = self.files.system_name(file)
                if name != TRIM_DROPIN:
                    self.check_trim_override(name)
        return TRIM_DROPIN, content

    def check_trim_override(self, name: str) -> None:
        """Raise `Conflict` if drop-in `name` changes TRIM timing or catch-up."""
        values = ini(self.files.read(name), source=name)
        if any(section == "Timer" and key.startswith("On") for section, key in values):
            raise Conflict(f"custom TRIM timing in {name} requires operator review")
        persistent = values.get(("Timer", "Persistent"))
        if persistent is not None and persistent != "false":
            raise Conflict(
                f"conflicting TRIM timer persistence override in {name} "
                f"(Persistent={persistent})"
            )

    def check_console_assets(self, desired: Console) -> None:
        for directory, key, suffixes in [
            ("keymaps", "keymap", (".map", ".map.gz")),
            ("consolefonts", "font", (".psf", ".psf.gz", ".psfu", ".psfu.gz")),
        ]:
            value = desired["keymap"] if key == "keymap" else desired["font"]
            if value is None:
                continue
            base = self.files.path("/usr/share/kbd/" + directory)
            found = [p for suffix in suffixes for p in base.rglob(value + suffix)]
            if not found or not all(p.is_file() and not p.is_symlink() for p in found):
                raise Conflict("console keymap or font is unavailable")

    def check_time_provider(self) -> None:
        for unit in (
            "chronyd.service",
            "chrony.service",
            "ntpd.service",
            "openntpd.service",
        ):
            state = self.unit(unit)
            if state.get("ActiveState") in (
                "active",
                "activating",
                "reloading",
            ) or state.get("UnitFileState") in (
                "enabled",
                "enabled-runtime",
                "linked",
                "linked-runtime",
            ):
                raise Conflict(
                    "another time synchronization provider is enabled or active"
                )
        # Custom servers supplement native defaults; per-link sources are not overridden.

    def check_trim(self) -> None:
        check_discard_support(native=self.native)
        # A second custom fstrim timer/cron owner must be resolved by the operator.
        output = self.run(
            "systemctl", "list-timers", "--all", "--no-legend", "--no-pager"
        ).stdout
        if any(
            "fstrim" in line and "fstrim.timer" not in line
            for line in output.splitlines()
        ):
            raise Conflict("another TRIM schedule exists")
        for directory in (
            "/etc/cron.d",
            "/etc/cron.daily",
            "/etc/cron.weekly",
            "/etc/cron.monthly",
        ):
            path = self.files.path(directory)
            if path.exists() and any("trim" in p.name.lower() for p in path.iterdir()):
                raise Conflict("a possible additional TRIM schedule exists")

    def preflight(self, installed: bool = False) -> None:
        """Read and validate all owned state; change nothing.

        With `installed`, after package installation, also require the
        native commands, units, zoneinfo and console assets that convergence
        uses.
        """
        d = self.desired
        if installed:
            self.check_native_commands()
        # Read/validate all owned state before writes; no mutation during preflight.
        for setting, action in PENDING_ACTIONS.items():
            if d.get(setting) is not None:
                self.files.pending(action)
        self.check_files()
        self.check_services(installed)
        if d["hotspot"] is not None:
            Hotspot(self).preflight()
        if d["firewall"] is not None:
            Firewall(self).preflight(installed)

    def check_native_commands(self) -> None:
        """Raise `Conflict` if a command that a declared setting needs is missing."""
        commands: set[str] = set()
        for setting, required in NATIVE_COMMANDS.items():
            if self.desired.get(setting) is not None:
                commands.update(required)
        missing = sorted(c for c in commands if not self.native.available(c))
        if missing:
            raise Conflict(
                "required native system commands are missing: " + " ".join(missing)
            )

    def check_files(self) -> None:
        """Read every file that a declared setting rewrites, so conflicts stop here."""
        d, f = self.desired, self.files
        if (locale := d["locale"]) is not None:
            self.generated_locales(
                self.path_str("localeGen", "/etc/locale.gen"), locale["generated"]
            )
            self.locale_conf(
                self.path_str("localeConf", "/etc/locale.conf"), locale["lang"]
            )
        if d["timeZone"] is not None:
            self.localtime()
        if d["hostname"] is not None:
            f.read(self.path_str("hostnameFile", "/etc/hostname"))
        for name, text in d["files"].items():
            f.dropin(name, text, file_name=DROPIN_FILE)
        if (console := d["console"]) is not None:
            self.console(console)
        if d["trim"] is not None:
            self.trim_dropin(d["trimDropin"])

    def check_services(self, installed: bool) -> None:
        """Check the providers, units and assets that declared settings use."""
        d = self.desired
        if (
            installed
            and (zone := d["timeZone"]) is not None
            and not self.files.zone_exists(zone)
        ):
            raise Conflict(f"declared zoneinfo is unavailable: {zone}")
        if d["timeSync"] is not None:
            self.check_time_provider()
            if installed:
                self.ready_unit("systemd-timesyncd.service")
        if d["journal"] is not None and installed:
            self.ready_unit("systemd-journald.service")
        if (console := d["console"]) is not None and installed:
            self.check_console_assets(console)
        if d["power"] is not None and not self.boot_id().strip():
            raise Conflict("boot identity is unavailable")
        if d["trim"] is not None:
            self.check_trim()
            if installed:
                self.ready_unit("fstrim.timer")

    def converge(self) -> None:
        """Converge every declared setting; settings left null stay untouched."""
        self.preflight(installed=True)
        d = self.desired
        if (locale := d["locale"]) is not None:
            self.converge_locale(locale)
        if (zone := d["timeZone"]) is not None:
            self.converge_timezone(zone)
        if (hostname := d["hostname"]) is not None:
            self.converge_hostname(hostname)
        for name, text in d["files"].items():
            self.converge_dropin(name, text)
        if (console := d["console"]) is not None:
            self.converge_console(console)
        if d["trim"] is not None:
            self.converge_trim()
        if d["firewall"] is not None:
            Firewall(self).converge()
        if d["hotspot"] is not None:
            Hotspot(self).converge()
        print(
            f"System settings converged: {self.updates} files updated, {self.actions} runtime actions."
        )
        if d["locale"] is not None:
            print("System language applies to new login sessions.")

    def absent_locales(self, names: list[str]) -> list[str]:
        """The locales of `names` that `locale -a` does not list."""
        available = {
            locale_key(line) for line in self.run("locale", "-a").stdout.splitlines()
        }
        return [name for name in names if locale_key(name) not in available]

    def converge_locale(self, value: Locale) -> None:
        """Generate the declared locales and set the system language."""
        f = self.files
        locale_gen_path = self.path_str("localeGen", "/etc/locale.gen")
        self.write(
            locale_gen_path,
            self.generated_locales(locale_gen_path, value["generated"]),
            "locale",
        )

        if f.pending("locale") or self.absent_locales(value["generated"]):
            f.mark("locale")
            self.run("locale-gen")
            self.actions += 1
            if absent := self.absent_locales(value["generated"]):
                raise Conflict(
                    "required locales were not generated: " + " ".join(absent)
                )
        locale_conf_path = self.path_str("localeConf", "/etc/locale.conf")
        self.write(
            locale_conf_path,
            self.locale_conf(locale_conf_path, value["lang"]),
            "locale",
        )
        f.clear("locale")

    def converge_timezone(self, zone: str) -> None:
        """Point /etc/localtime at `zone` through timedated."""
        f = self.files
        localtime_path = self.path_str("localtime", "/etc/localtime")
        target = f.path(localtime_path, symlink_leaf=True)
        expected = "/usr/share/zoneinfo/" + zone
        matches = target.is_symlink() and os.readlink(target) in (
            expected,
            ".." + expected,
        )
        if (
            not matches
            or self.localtime() != zone
            or f.pending("timezone")
            or not f.metadata_matches(localtime_path, symlink=True)
        ):
            f.mark("timezone")
            set_timezone(zone, native=self.native)
            if not target.is_symlink() and not target.exists():
                # timedated changes nothing when the zone already matches,
                # and a missing /etc/localtime already reads as UTC.
                target.symlink_to(".." + expected)
            self.actions += 1
            if (
                self.localtime() != zone
                or not target.is_symlink()
                or os.readlink(target) not in (expected, ".." + expected)
            ):
                raise Conflict("timezone did not converge")
            self.updates += int(f.repair_metadata(localtime_path, symlink=True))
            f.clear("timezone")

    def converge_hostname(self, hostname: str) -> None:
        """Set the static and transient hostname, and repair /etc/hostname."""
        f = self.files
        hostname_path = self.path_str("hostnameFile", "/etc/hostname")
        for kind in ("--static", "--transient"):
            actual = get_hostname(native=self.native, kind=kind)
            if actual != hostname or (
                kind == "--static" and f.read(hostname_path).strip() != hostname
            ):
                f.mark("hostname")
                set_hostname(hostname, native=self.native, kind=kind)
                self.actions += 1
                if get_hostname(native=self.native, kind=kind) != hostname:
                    raise Conflict("hostname did not converge")
        if not f.metadata_matches(hostname_path):
            f.mark("hostname")
            self.updates += int(f.repair_metadata(hostname_path))
        f.clear("hostname")

    def converge_dropin(self, name: str, text: str) -> None:
        """Install the drop-in of service `name` and apply it."""
        f = self.files
        target = f.dropin(name, text, file_name=DROPIN_FILE)
        if name == "logind":
            # logind changes wait until reboot; power() reports that.
            self.power(target, text)
            return
        self.write(target, text, name)
        pending = f.pending(name)
        if name == "timesyncd":
            self.converge_timesyncd(restart=pending)
        elif name == "journald":
            self.converge_journald(restart=pending)
        f.clear(name)

    def converge_timesyncd(self, *, restart: bool) -> None:
        """Run systemd-timesyncd with its drop-in and report synchronization."""
        self.service("systemd-timesyncd.service", "timesyncd", restart=restart)
        if is_ntp_synchronized(native=self.native):
            print("Time synchronization: synchronized.")
        else:
            print("Time synchronization: waiting for network synchronization.")

    def converge_journald(self, *, restart: bool) -> None:
        """Restart journald when its drop-in changed or it is not active.

        Persistent storage gets its directory first, and stored logs are
        flushed afterwards. Raise `Conflict` if journald does not come back.
        """
        unit = "systemd-journald.service"
        self.ready_unit(unit)
        if not restart and self.unit(unit).get("ActiveState") == "active":
            return
        self.files.mark("journald")
        journal = self.desired["journal"]
        storage = journal["storage"] if journal else "auto"
        if storage == "persistent":
            self.run("systemd-tmpfiles", "--create", "--prefix=/var/log/journal")
        self.systemd.restart(unit)
        if storage in ("auto", "persistent"):
            self.run("journalctl", "--flush")
        self.actions += 1
        if self.unit(unit).get("ActiveState") != "active":
            raise Conflict("journald did not become ready")

    def converge_console(self, console: Console) -> None:
        """Prepare the console keymap and font for the next boot."""
        f = self.files
        vconsole_path = self.path_str("vconsole", "/etc/vconsole.conf")
        if self.write(vconsole_path, self.console(console), "console") or f.pending(
            "console"
        ):
            print("Console configuration is prepared for the next boot.")
        f.clear("console")

    def converge_trim(self) -> None:
        """Install the TRIM timer drop-in and restart the timer when it changed."""
        f = self.files
        d = self.desired
        path, text = self.trim_dropin(d["trimDropin"])
        self.write(path, text, "trim")
        pending = f.pending("trim")
        if pending:
            # Disable catch-up, so starting an overdue timer cannot request
            # an immediate full trim during deployment. Keep native schedule.
            self.systemd.daemon_reload()
        self.service("fstrim.timer", "trim", restart=pending)
        f.clear("trim")

    def plan(self) -> list[Change]:
        """What converge would change, judged the way converge judges it."""
        self.preflight(installed=True)
        d = self.desired
        changes: list[Change] = []
        if (locale := d["locale"]) is not None:
            changes += self.plan_locale(locale)
        if (zone := d["timeZone"]) is not None:
            changes.append(self.plan_timezone(zone))
        if (hostname := d["hostname"]) is not None:
            changes.append(self.plan_hostname(hostname))
        for name, text in d["files"].items():
            changes += self.plan_dropin(name, text)
        if (console := d["console"]) is not None:
            vconsole_path = self.path_str("vconsole", "/etc/vconsole.conf")
            changes.append(self.plan_file(vconsole_path, self.console(console)))
        if d["trim"] is not None:
            path, text = self.trim_dropin(d["trimDropin"])
            changes.append(self.plan_file(path, text))
            changes += self.plan_unit("fstrim.timer")
        if d["firewall"] is not None:
            changes += Firewall(self).plan()
        if d["hotspot"] is not None:
            changes += Hotspot(self).plan()
        return changes

    def plan_locale(self, locale: Locale) -> list[Change]:
        """The locale.gen, locale generation and locale.conf changes."""
        locale_gen_path = self.path_str("localeGen", "/etc/locale.gen")
        locale_conf_path = self.path_str("localeConf", "/etc/locale.conf")
        changes = [
            self.plan_file(
                locale_gen_path,
                self.generated_locales(locale_gen_path, locale["generated"]),
            )
        ]
        absent = self.absent_locales(locale["generated"])
        if absent or self.files.pending("locale"):
            changes.append(Change("~", "generate locales " + " ".join(absent)))
        changes.append(
            self.plan_file(
                locale_conf_path, self.locale_conf(locale_conf_path, locale["lang"])
            )
        )
        return changes

    def plan_timezone(self, zone: str) -> Change:
        """The time zone change, if any."""
        current = self.localtime()
        if current != zone or self.files.pending("timezone"):
            return Change("~", f"time zone {current} -> {zone}")
        return Change("=", f"time zone {current}")

    def plan_hostname(self, hostname: str) -> Change:
        """The hostname change, if the static, transient or file name differs."""
        hostname_path = self.path_str("hostnameFile", "/etc/hostname")
        current = get_hostname(native=self.native, kind="--static")
        transient = get_hostname(native=self.native, kind="--transient")
        if (
            hostname != current
            or hostname != transient
            or self.files.read(hostname_path).strip() != hostname
        ):
            return Change("~", f"hostname {current} -> {hostname}")
        return Change("=", f"hostname {current}")

    def plan_dropin(self, name: str, text: str) -> list[Change]:
        """The drop-in change of service `name` and the restart it implies."""
        target = self.files.dropin(name, text, file_name=DROPIN_FILE)
        change = self.plan_file(target, text)
        changes = [change]
        changed = change.kind != "=" or self.files.pending(name)
        if name == "logind" and change.kind != "=":
            changes.append(Change("~", "logind settings apply after the next boot"))
        elif name == "timesyncd":
            changes += self.plan_unit("systemd-timesyncd.service")
            if changed:
                changes.append(Change("~", "restart systemd-timesyncd.service"))
        elif name == "journald" and changed:
            changes.append(Change("~", "restart systemd-journald.service"))
        return changes

    def power(self, path: str, text: str) -> None:
        f = self.files
        boot = self.boot_id().strip()
        digest = hashlib.sha256(text.encode()).hexdigest()
        receipt = f"{boot} {digest}\n"
        if not f.matches(path, text):
            f.mark("power", receipt)
            self.updates += int(f.write(path, text))
        if f.pending("power"):
            previous = f.read(f.marker("power")).split()
            if len(previous) != 2:
                raise Conflict("invalid power pending receipt")
            if previous[0] != boot and previous[1] == digest:
                f.clear("power")
            else:
                # Never restart logind with live sessions. A new desired value
                # after a failed write also needs a complete boot boundary.
                if previous[1] != digest:
                    f.mark("power", receipt)
                print(
                    "Power event configuration pending: reboot required; desktop inhibitors still apply."
                )
