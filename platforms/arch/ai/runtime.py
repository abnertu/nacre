"""Converge Arch-owned llama.cpp, Caddy and Tailscale Serve policy."""

import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from nix_adapter import AdapterContext, BaseAdapter, Change, Conflict, Files, Native
from schema import AIManifest, Model, Unmanaged

RECEIPT = "/var/lib/nix-config/arch/receipts/ai.json"
ADOPTED = "/var/lib/nix-config/arch/adopted"
CADDY_ADMIN = "unix//run/caddy/admin.socket"


class AI(BaseAdapter[AIManifest | Unmanaged]):
    # AI markers share the system adapter's namespace: system-ai-<action>.
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
            desired=cast(AIManifest | Unmanaged, desired),
            root=root,
            native=native,
            files=files,
            context=context,
        )
        self._records: dict[str, dict[str, Any]] | None = None

    @property
    def phases(self) -> dict[str, Callable[[], None]]:
        return {"forget": self.forget}

    def forget(self) -> None:
        """Drop one record and its saved original; the native state stays."""
        request = cast("dict[str, Any]", self.desired).get("forget", "")
        kind, _, name = str(request).partition(":")
        if kind != "ai" or name not in self.records:
            raise Conflict(f"Nacre has no record {request}; AI records are ai:<name>")
        if isinstance(original := self.records[name].get("original"), str):
            self.remove(original)
        del self.records[name]
        self.save_records()
        print(f"forgot {request}; the native state stays as it is, unmanaged")

    @staticmethod
    def digest(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def check_unchanged(self, key: str, record: dict[str, Any]) -> None:
        """Raise `Conflict` if a file that Nacre wrote changed since then."""
        for path, digest in record.get("sha256", {}).items():
            if (
                self.files.path(path).exists()
                and self.digest(self.files.read(path)) != digest
            ):
                raise Conflict(
                    f"{path} changed since Nacre wrote it; restore it, "
                    f"or run `nacre forget ai:{key}` to leave it unmanaged"
                )

    def remember_written(self, key: str, paths: list[str]) -> None:
        """Record the checksums of the files that `key` just wrote."""
        record = dict(self.records[key])
        record["sha256"] = {path: self.digest(self.files.read(path)) for path in paths}
        self.record(key, record)

    # The receipt records what this adapter wrote and changed: the router
    # files, the Caddy site with the Caddyfile before Nacre and whether Caddy
    # ran then, and the Serve route. Withdrawal returns each one.

    @property
    def records(self) -> dict[str, dict[str, Any]]:
        if self._records is None:
            text = self.files.read(RECEIPT)
            try:
                value: object = (
                    json.loads(text) if text else {"version": 1, "records": {}}
                )
            except ValueError:
                raise Conflict(f"receipt {RECEIPT} is corrupt") from None
            data = cast("dict[str, object]", value) if isinstance(value, dict) else {}
            if data.get("version") != 1 or not isinstance(data.get("records"), dict):
                raise Conflict(f"receipt {RECEIPT} has an unknown format")
            self._records = cast("dict[str, dict[str, Any]]", data["records"])
        return self._records

    def record(self, key: str, value: dict[str, Any]) -> None:
        if self.records.get(key) != value:
            self.records[key] = dict(value)
            self.save_records()

    def save_records(self) -> None:
        receipt = {"version": 1, "records": self.records}
        self.files.write(
            RECEIPT, json.dumps(receipt, indent=2, sort_keys=True) + "\n", 0o600
        )

    def withdraw(self, keep: set[str]) -> None:
        """Withdraw each record outside `keep`: the route, then Caddy, then the router."""
        for key in ("serve", "caddy", "router"):
            if key in self.records and key not in keep:
                self.check_unchanged(key, self.records[key])
        for key in ("serve", "caddy", "router"):
            if key in self.records and key not in keep:
                getattr(self, f"withdraw_{key}")(self.records[key])
                del self.records[key]
                self.save_records()
                self.actions += 1

    def plan_withdrawals(self, keep: set[str]) -> list[Change]:
        """The withdrawal of each record outside `keep`."""
        return [
            Change("~", "withdraw " + self.withdrawal_note(key))
            for key in ("serve", "caddy", "router")
            if key in self.records and key not in keep
        ]

    def withdrawal_note(self, key: str) -> str:
        if key == "serve":
            return f"the Tailscale Serve route on port {self.records[key]['port']}"
        if key == "caddy":
            return "the Caddy site and restore the Caddyfile"
        return "llama-swap.service and its configuration"

    def withdraw_serve(self, record: dict[str, Any]) -> None:
        query = self.run("tailscale", "serve", "status", "--json", check=False)
        if query.returncode != 0:
            raise Conflict(
                "cannot read the Tailscale Serve status to remove the route; start "
                "tailscaled and rerun, or run `nacre forget ai:serve`"
            )
        status = query.stdout
        if record["target"] in status and record["port"] in status:
            self.run("tailscale", "serve", f"--https={record['port']}", "off")

    def withdraw_caddy(self, record: dict[str, Any]) -> None:
        """Remove the site and restore the Caddyfile; stop Caddy if Nacre started it."""
        self.remove(record["site"])
        caddyfile = record["caddyfile"]
        if record["original"] is not None:
            original = json.loads(self.files.read(record["original"]))
            self.files.write(caddyfile, original["text"])
            self.remove(record["original"])
        else:
            self.remove(caddyfile)
        state = self.unit("caddy.service")
        running = state.get("ActiveState") == "active"
        if not (record["wasEnabled"] or record["wasActive"]):
            if running or state.get("UnitFileState") == "enabled":
                self.systemd.disable("caddy.service", now=True)
        elif running:
            self.run("caddy", "reload", "--config", caddyfile, "--address", CADDY_ADMIN)

    def withdraw_router(self, record: dict[str, Any]) -> None:
        state = self.unit("llama-swap.service")
        if (
            state.get("UnitFileState") == "enabled"
            or state.get("ActiveState") == "active"
        ):
            self.systemd.disable("llama-swap.service", now=True)
        unit = self.remove(record["unit"])
        self.remove(record["config"])
        if unit:
            self.systemd.daemon_reload()

    def save_caddy_original(self, caddyfile: str) -> str | None:
        """Save the Caddyfile before Nacre; it can hold secrets, so root only."""
        if not self.files.path(caddyfile).exists():
            return None
        saved = f"{ADOPTED}/{hashlib.sha256(caddyfile.encode()).hexdigest()}.json"
        text = self.files.read(caddyfile)
        self.files.write(
            saved, json.dumps({"path": caddyfile, "text": text}) + "\n", 0o600
        )
        return saved

    def managed(self) -> AIManifest:
        d = self.desired
        if d["llama"] is True:
            return d
        raise Conflict("AI services are not managed")

    @staticmethod
    def model_receipt(model: Path, declaration: Model) -> str:
        info = model.stat()
        fingerprint = ":".join(
            str(value)
            for value in (
                info.st_dev,
                info.st_ino,
                info.st_size,
                int(info.st_mtime),
                int(info.st_ctime),
            )
        )
        return "\n".join(
            [
                declaration["repository"],
                declaration["revision"],
                declaration["file"],
                declaration["sha256"],
                fingerprint,
                "",
            ]
        )

    def caddy_main(self) -> str:
        generated = self.managed()["generated"]
        current = self.files.read(self.path_str("caddyMain", "/etc/caddy/Caddyfile"))
        if current == generated["caddyMain"]:
            return current
        if not current or current == generated["packageCaddy"]:
            return generated["caddyMain"]
        if (
            'admin "unix//run/caddy/admin.socket"' in current
            and "import /etc/caddy/conf.d/*" in current
            and "http://" not in current
        ):
            return current
        raise Conflict("existing Caddyfile requires explicit adoption")

    def preflight(self, installed: bool = False) -> bool:
        """Whether the prepared llama.cpp build and models match the declaration.

        Return False while preparation never completed. Raise `Conflict` when
        prepared assets exist but do not match, or, with `installed`, when a
        native command or unit that convergence needs is missing.
        """
        if not self.desired["llama"]:
            # Ready only to withdraw what an earlier deployment left.
            return bool(self.records)
        d = self.managed()
        if any(not Path(model["path"]).is_absolute() for model in d["models"].values()):
            raise Conflict("model paths must be absolute")
        if not self.prepared(d, installed):
            return False
        self.check_receipts(d)
        self.check_owned_files(d)
        if installed:
            self.check_native(d)
        return True

    def prepared(self, d: AIManifest, installed: bool) -> bool:
        """Whether the selector points at a complete prepared revision.

        Raise `Conflict` on a selector or asset set that exists but is wrong.
        """
        f = self.files
        install_prefix = d["source"]["installPrefix"]
        current = f.path(install_prefix + "/current", symlink_leaf=True)
        desired_link = (
            f"revisions/{d['source']['revision']}-"
            f"{d['source']['grammarRepetitionThreshold']}"
        )
        if not current.exists() and not current.is_symlink():
            if installed and f.path(install_prefix).exists():
                raise Conflict("prepared llama-server selector is missing")
            return False
        if not current.is_symlink() or os.readlink(current) != desired_link:
            raise Conflict(
                "prepared llama-server selector does not match the declaration"
            )
        revision_prefix = install_prefix + "/" + desired_link
        executable = f.path(revision_prefix + "/bin/llama-server")
        receipt = f.read(revision_prefix + "/nix-config-build").strip()
        models = [f.path(model["path"]) for model in d["models"].values()]
        complete = executable.is_file() and all(model.is_file() for model in models)
        if not complete or not receipt:
            # The selector exists here, so the assets were prepared once.
            raise Conflict("prepared llama.cpp assets are incomplete")
        return True

    def check_receipts(self, d: AIManifest) -> None:
        """Raise `Conflict` unless the build and model receipts match the declaration."""
        f = self.files
        source = d["source"]
        revision_prefix = (
            f"{source['installPrefix']}/revisions/"
            f"{source['revision']}-{source['grammarRepetitionThreshold']}"
        )
        receipt = f.read(revision_prefix + "/nix-config-build").strip()
        if receipt != f"{source['revision']} {source['grammarRepetitionThreshold']}":
            raise Conflict(
                "prepared llama-server receipt does not match the declaration"
            )
        for declaration in d["models"].values():
            model = f.path(declaration["path"])
            receipt_path = declaration["path"] + ".nix-config-receipt"
            if not f.metadata_matches(receipt_path) or f.read(
                receipt_path
            ) != self.model_receipt(model, declaration):
                raise Conflict("prepared model receipt does not match the declaration")

    def check_owned_files(self, d: AIManifest) -> None:
        """Read the router and proxy files and their pending markers."""
        f = self.files
        f.read(self.path_str("switcherConfig", "/etc/llama-swap/config.yaml"))
        f.read(self.path_str("switcherUnit", "/etc/systemd/system/llama-swap.service"))
        f.pending("ai-llama")
        if d["proxy"]:
            self.caddy_main()
            f.read(
                self.path_str("caddySite", "/etc/caddy/conf.d/nix-config-llama.caddy")
            )
            f.pending("ai-caddy")
            f.pending("ai-serve")

    def check_native(self, d: AIManifest) -> None:
        """Raise `Conflict` if a command or unit that convergence uses is missing."""
        required = {"systemctl", "curl"}
        if d["proxy"]:
            required |= {"caddy", "stat", "systemd-tmpfiles", "tailscale"}
        missing = sorted(c for c in required if not self.native.available(c))
        if missing:
            raise Conflict(
                "required native AI commands are missing: " + " ".join(missing)
            )
        if d["proxy"]:
            self.ready_unit("caddy.service")

    def ensure_service(self, name: str, action: str, restart: bool = False) -> None:
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
        """Withdraw the route, the Caddy site and the router from the receipt.

        Prepared binaries, models and receipts stay: they are mutable assets
        that are expensive to rebuild. Caddy itself stays installed.
        """
        self.withdraw(keep=set())
        print("AI services purged; prepared binaries and models were kept.")

    def _curl_ready(
        self,
        port: int,
        endpoint: str = "/v1/models",
        retries: int = 10,
        delay: float = 2,
    ) -> None:
        url = f"http://127.0.0.1:{port}{endpoint}"
        last_err = ""
        for attempt in range(1, retries + 1):
            try:
                self.run("curl", "--fail", "--silent", "--show-error", url)
                return
            except Conflict as exc:
                last_err = str(exc)
                if attempt < retries:
                    time.sleep(delay)
        raise Conflict(f"curl failed after {retries} retries; last: {last_err}")

    def plan(self) -> list[Change]:
        """What converge would change, judged the way converge judges it."""
        if not self.desired["llama"]:
            return self.plan_withdrawals(keep=set()) or [
                Change("=", "AI services unmanaged")
            ]
        d = self.managed()
        if not self.preflight(installed=True):
            return [Change("-", "AI preparation never completed; run nacre ai prepare")]
        keep = {"router", "caddy", "serve"} if d["proxy"] else {"router"}
        return self.plan_withdrawals(keep) + self.plan_converge(d)

    def plan_converge(self, d: AIManifest) -> list[Change]:
        """The router, proxy and route changes of a prepared, declared AI."""
        f = self.files
        generated = d["generated"]
        config = self.plan_file(
            self.path_str("switcherConfig", "/etc/llama-swap/config.yaml"),
            generated["switcherConfig"],
        )
        unit = self.plan_file(
            self.path_str("switcherUnit", "/etc/systemd/system/llama-swap.service"),
            generated["switcherUnit"],
        )
        changes = [config, unit, *self.plan_unit("llama-swap.service")]
        pending = f.pending("ai-llama")
        if config.kind != "=" or pending:
            changes.append(Change("~", "restart llama-swap.service"))
        if d["proxy"]:
            caddy = [
                self.plan_file(
                    self.path_str("caddyMain", "/etc/caddy/Caddyfile"),
                    self.caddy_main(),
                ),
                self.plan_file(
                    self.path_str(
                        "caddySite", "/etc/caddy/conf.d/nix-config-llama.caddy"
                    ),
                    generated["caddySite"],
                ),
            ]
            changes += [*caddy, *self.plan_unit("caddy.service")]
            if any(change.kind != "=" for change in caddy) or f.pending("ai-caddy"):
                changes.append(Change("~", "reload caddy.service"))
            status = self.run("tailscale", "serve", "status", "--json").stdout
            target = f"http://127.0.0.1:{d['localPort']}"
            port = str(d["httpsPort"])
            if target not in status or port not in status:
                changes.append(Change("+", f"tailscale serve --https={port} {target}"))
            else:
                changes.append(Change("=", f"tailscale serve --https={port}"))
        return changes

    def converge(self, preflighted: bool = False) -> None:
        """Converge llama-swap, then the Caddy proxy and the Tailscale Serve route.

        Skip with a message while preparation never completed.
        """
        if not self.desired["llama"]:
            self.withdraw(keep=set())
            print("AI services unmanaged.")
            return
        d = self.managed()
        if not preflighted and not self.preflight(installed=True):
            print("AI services skipped: selected model is not prepared.")
            return
        self.withdraw(keep={"router", "caddy", "serve"} if d["proxy"] else {"router"})
        self.converge_router(d)
        if d["proxy"]:
            self.converge_caddy(d)
            self.converge_serve(d)
        print(
            f"AI services converged: {self.updates} files updated, {self.actions} runtime actions."
        )

    def converge_router(self, d: AIManifest) -> None:
        """Install the llama-swap config and unit, and run it until it answers."""
        f = self.files
        generated = d["generated"]
        switcher_config = self.path_str("switcherConfig", "/etc/llama-swap/config.yaml")
        switcher_unit = self.path_str(
            "switcherUnit", "/etc/systemd/system/llama-swap.service"
        )
        # Record first (without checksums), so a crash still leaves a record.
        self.record("router", {"config": switcher_config, "unit": switcher_unit})
        config_changed = self.write(
            switcher_config, generated["switcherConfig"], "ai-llama"
        )
        unit_changed = self.write(switcher_unit, generated["switcherUnit"], "ai-llama")
        pending = f.pending("ai-llama")
        if config_changed or unit_changed or pending:
            self.run("systemctl", "daemon-reload")
            self.actions += 1
        self.ensure_service(
            "llama-swap.service", "ai-llama", restart=pending or config_changed
        )
        self.remember_written("router", [switcher_config, switcher_unit])
        self._curl_ready(d["server"]["port"])
        f.clear("ai-llama")

    def converge_caddy(self, d: AIManifest) -> None:
        """Install and validate the Caddy site, then reload Caddy when it changed.

        Raise `Conflict` unless Caddy's admin endpoint is a Unix socket.
        """
        f = self.files
        caddy_file = self.path_str("caddyMain", "/etc/caddy/Caddyfile")
        caddy_site = self.path_str(
            "caddySite", "/etc/caddy/conf.d/nix-config-llama.caddy"
        )
        if "caddy" not in self.records:
            state = self.unit("caddy.service")
            self.record(
                "caddy",
                {
                    "site": caddy_site,
                    "caddyfile": caddy_file,
                    "original": self.save_caddy_original(caddy_file),
                    "wasEnabled": state.get("UnitFileState") == "enabled",
                    "wasActive": state.get("ActiveState") == "active",
                },
            )
        # Drop the checksums while writing: a crash in between is no drift.
        self.record(
            "caddy", {k: v for k, v in self.records["caddy"].items() if k != "sha256"}
        )
        self.write(caddy_file, self.caddy_main(), "ai-caddy")
        self.write(caddy_site, d["generated"]["caddySite"], "ai-caddy")
        self.remember_written("caddy", [caddy_file, caddy_site])
        pending = f.pending("ai-caddy")
        runtime_dir = self.run("stat", "--format=%a:%U:%G", "/run/caddy", check=False)
        if runtime_dir.returncode or runtime_dir.stdout.strip() != "750:caddy:caddy":
            self.run("systemd-tmpfiles", "--create", "/usr/lib/tmpfiles.d/caddy.conf")
        self.run("caddy", "validate", "--config", caddy_file, "--adapter", "caddyfile")
        state = self.ready_unit("caddy.service")
        self.ensure_service(
            "caddy.service", "ai-caddy", restart=state.get("ActiveState") != "active"
        )
        kind = self.run("stat", "--format=%F", "/run/caddy/admin.socket").stdout.strip()
        if kind != "socket":
            raise Conflict("Caddy admin endpoint is not a Unix socket")
        if pending:
            self.run(
                "caddy",
                "reload",
                "--config",
                caddy_file,
                "--address",
                "unix//run/caddy/admin.socket",
            )
            self.actions += 1
        f.clear("ai-caddy")
        self._curl_ready(d["localPort"])

    def converge_serve(self, d: AIManifest) -> None:
        """Route the tailnet HTTPS port to the proxy with Tailscale Serve.

        Raise `Conflict` instead of replacing another Serve configuration.
        """
        f = self.files
        target = f"http://127.0.0.1:{d['localPort']}"
        port = str(d["httpsPort"])
        status = self.run("tailscale", "serve", "status", "--json").stdout
        if target not in status or port not in status:
            if status.strip() not in ("", "{}", "null"):
                raise Conflict(
                    "existing Tailscale Serve configuration requires explicit adoption"
                )
            f.mark("ai-serve")
            # Record first: a crash after the change still leaves its record.
            self.record("serve", {"port": port, "target": target})
            self.run("tailscale", "serve", "--bg", f"--https={port}", target)
            self.actions += 1
            status = self.run("tailscale", "serve", "status", "--json").stdout
            if target not in status or port not in status:
                raise Conflict("Tailscale Serve route did not converge")
        self.record("serve", {"port": port, "target": target})
        f.clear("ai-serve")
