"""Arch system settings. Only packaging invokes this privileged private adapter.

The caller holds the arch-switch deployment lock. Tests inject a filesystem and
native runner directly; production accepts no root/command overrides.
"""

import hashlib
import os
from pathlib import Path
from nix_adapter import (
    BaseAdapter,
    Conflict,
    Firewall,
    Hotspot,
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


class System(BaseAdapter):
    def __init__(self, desired, files=None, native=None):
        root = getattr(files, "root", Path("/")) if files else Path("/")
        super().__init__(desired=desired, root=root, runner=native, files=files)

    def boot_id(self):
        # A kernel pseudo-file, not a managed path: skip ownership checks.
        path = self.files.root / "proc/sys/kernel/random/boot_id"
        return path.read_text() if path.is_file() else ""

    def service(self, name, action, restart=False):
        self.converge_unit(
            name, restart=restart, before_change=lambda: self.files.mark(action)
        )

    def remove(self, name):
        path = self.files.path(name)
        if not path.exists():
            return False
        if not path.is_file():
            raise Conflict(f"managed path is not a regular file: {name}")
        path.unlink()
        self.files.sync_dir(path.parent)
        return True

    def purge(self):
        """Withdraw the drop-ins this adapter owns; keep the system's own values.

        Locale, timezone, hostname, console, firewall rules and the hotspot
        profile are the machine's settings, so withdrawing management keeps
        them as they are now.
        """
        d = self.desired
        removed = [
            name
            for name in d.get("files", {})
            if self.remove(f"/etc/systemd/{name}.conf.d/60-nix-config.conf")
        ]
        if d.get("trim") is not None and self.remove(
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

    def localtime(self):
        return get_timezone(runner=self.native, root=self.files.root)

    def console(self):
        desired = self.desired["console"]
        values = {"KEYMAP": desired["keymap"]}
        if desired["font"] is not None:
            values["FONT"] = desired["font"]
        return replace_keys(
            self.files.read(self.path_str("vconsole", "/etc/vconsole.conf")), values
        )

    def check_console_assets(self):
        desired = self.desired["console"]
        for directory, key, suffixes in [
            ("keymaps", "keymap", (".map", ".map.gz")),
            ("consolefonts", "font", (".psf", ".psf.gz", ".psfu", ".psfu.gz")),
        ]:
            value = desired[key]
            if value is None:
                continue
            base = self.files.path("/usr/share/kbd/" + directory)
            found = [p for suffix in suffixes for p in base.rglob(value + suffix)]
            if not found or not all(p.is_file() and not p.is_symlink() for p in found):
                raise Conflict("console keymap or font is unavailable")

    def check_time_provider(self):
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

    def check_trim(self):
        check_discard_support(runner=self.native)
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

    def preflight(self, installed=False):
        d, f = self.desired, self.files
        if installed:
            commands = set()
            for capability, required in {
                "locale": ("locale", "locale-gen"),
                "timeZone": ("timedatectl",),
                "hostname": ("hostnamectl",),
                "timeSync": ("systemctl", "timedatectl"),
                "journal": ("systemctl", "systemd-tmpfiles", "journalctl"),
                "trim": ("systemctl", "lsblk"),
                "hotspot": ("nmcli", "ip", "iw"),
                "firewall": ("systemctl", "ufw", "iptables", "ip6tables"),
            }.items():
                if d.get(capability) is not None:
                    commands.update(required)
            missing = sorted(c for c in commands if not self.native.available(c))
            if missing:
                raise Conflict(
                    "required native system commands are missing: " + " ".join(missing)
                )
        # Read/validate all owned state before writes; no mutation during preflight.
        for capability, action in {
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
        }.items():
            if d.get(capability) is not None:
                f.pending(action)
        if d.get("locale") is not None:
            locale_gen(
                f.read(self.path_str("localeGen", "/etc/locale.gen")),
                d["locale"]["generated"],
            )
            replace_keys(
                f.read(self.path_str("localeConf", "/etc/locale.conf")),
                {"LANG": d["locale"]["lang"]},
            )
        if d.get("timeZone") is not None:
            if installed and not f.zone_exists(d["timeZone"]):
                raise Conflict(f"declared zoneinfo is unavailable: {d['timeZone']}")
            self.localtime()
        if d.get("hostname") is not None:
            f.read(self.path_str("hostnameFile", "/etc/hostname"))
        for name, text in d.get("files", {}).items():
            f.dropin(name, text)
        if d.get("timeSync") is not None:
            self.check_time_provider()
            if installed:
                self.ready_unit("systemd-timesyncd.service")
        if d.get("journal") is not None and installed:
            self.ready_unit("systemd-journald.service")
        if d.get("console") is not None:
            self.console()
            if installed:
                self.check_console_assets()
        if d.get("power") is not None:
            if not self.boot_id().strip():
                raise Conflict("boot identity is unavailable")
        if d.get("trim") is not None:
            f.timer_dropin(d["trimDropin"])
            self.check_trim()
            if installed:
                self.ready_unit("fstrim.timer")
        if d.get("hotspot") is not None:
            Hotspot(self).preflight()
        if d.get("firewall") is not None:
            Firewall(self).preflight(installed)

    def converge(self):
        self.preflight(installed=True)
        d, f = self.desired, self.files
        if d.get("locale") is not None:
            value = d["locale"]
            locale_gen_path = self.path_str("localeGen", "/etc/locale.gen")
            self.write(
                locale_gen_path,
                locale_gen(f.read(locale_gen_path), value["generated"]),
                "locale",
            )

            def available():
                return {
                    line.lower().replace("-", "")
                    for line in self.run("locale", "-a").stdout.splitlines()
                }

            wanted = {name.lower().replace("-", "") for name in value["generated"]}
            if f.pending("locale") or not wanted <= available():
                f.mark("locale")
                self.run("locale-gen")
                self.actions += 1
                absent = wanted - available()
                if absent:
                    names = [
                        name
                        for name in value["generated"]
                        if name.lower().replace("-", "") in absent
                    ]
                    raise Conflict(
                        "required locales were not generated: " + " ".join(names)
                    )
            locale_conf_path = self.path_str("localeConf", "/etc/locale.conf")
            self.write(
                locale_conf_path,
                replace_keys(f.read(locale_conf_path), {"LANG": value["lang"]}),
                "locale",
            )
            f.clear("locale")
        if d.get("timeZone") is not None:
            localtime_path = self.path_str("localtime", "/etc/localtime")
            target = f.path(localtime_path, symlink_leaf=True)
            expected = "/usr/share/zoneinfo/" + d["timeZone"]
            matches = target.is_symlink() and os.readlink(target) in (
                expected,
                ".." + expected,
            )
            if (
                not matches
                or self.localtime() != d["timeZone"]
                or f.pending("timezone")
                or not f.metadata_matches(localtime_path, symlink=True)
            ):
                f.mark("timezone")
                set_timezone(d["timeZone"], runner=self.native)
                self.actions += 1
                if (
                    self.localtime() != d["timeZone"]
                    or not target.is_symlink()
                    or os.readlink(target) not in (expected, ".." + expected)
                ):
                    raise Conflict("timezone did not converge")
                self.updates += int(f.repair_metadata(localtime_path, symlink=True))
                f.clear("timezone")
        if d.get("hostname") is not None:
            hostname_path = self.path_str("hostnameFile", "/etc/hostname")
            for kind in ("--static", "--transient"):
                actual = get_hostname(runner=self.native, kind=kind)
                if actual != d["hostname"] or (
                    kind == "--static"
                    and f.read(hostname_path).strip() != d["hostname"]
                ):
                    f.mark("hostname")
                    set_hostname(d["hostname"], runner=self.native, kind=kind)
                    self.actions += 1
                    if get_hostname(runner=self.native, kind=kind) != d["hostname"]:
                        raise Conflict("hostname did not converge")
            if not f.metadata_matches(hostname_path):
                f.mark("hostname")
                self.updates += int(f.repair_metadata(hostname_path))
            f.clear("hostname")
        for name, text in d.get("files", {}).items():
            target = f.dropin(name, text)
            if name == "logind":
                self.power(target, text)
                continue
            self.write(target, text, name)
            pending = f.pending(name)
            if name == "timesyncd":
                self.service("systemd-timesyncd.service", name, restart=pending)
                synchronized = is_ntp_synchronized(runner=self.native)
                print(
                    "Time synchronization: synchronized."
                    if synchronized
                    else "Time synchronization: waiting for network synchronization."
                )
            elif name == "journald":
                self.ready_unit("systemd-journald.service")
                if (
                    pending
                    or self.unit("systemd-journald.service").get("ActiveState")
                    != "active"
                ):
                    f.mark(name)
                    if d["journal"]["storage"] == "persistent":
                        self.run(
                            "systemd-tmpfiles", "--create", "--prefix=/var/log/journal"
                        )
                    self.systemd.restart("systemd-journald.service")
                    if d["journal"]["storage"] in ("auto", "persistent"):
                        self.run("journalctl", "--flush")
                    self.actions += 1
                    if (
                        self.unit("systemd-journald.service").get("ActiveState")
                        != "active"
                    ):
                        raise Conflict("journald did not become ready")
            f.clear(name)
        if d.get("console") is not None:
            vconsole_path = self.path_str("vconsole", "/etc/vconsole.conf")
            if self.write(vconsole_path, self.console(), "console") or f.pending(
                "console"
            ):
                print("Console configuration is prepared for the next boot.")
            f.clear("console")
        if d.get("trim") is not None:
            path, text = f.timer_dropin(d["trimDropin"])
            self.write(path, text, "trim")
            pending = f.pending("trim")
            if pending:
                # Disable catch-up, so starting an overdue timer cannot request
                # an immediate full trim during deployment. Keep native schedule.
                self.systemd.daemon_reload()
            self.service("fstrim.timer", "trim", restart=pending)
            f.clear("trim")
        if d.get("firewall") is not None:
            Firewall(self).converge()
        if d.get("hotspot") is not None:
            Hotspot(self).converge()
        print(
            f"System settings converged: {self.updates} files updated, {self.actions} runtime actions."
        )
        if d.get("locale") is not None:
            print("System language applies to new login sessions.")

    def power(self, path, text):
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
