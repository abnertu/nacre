"""Converge Arch-owned llama.cpp, Caddy and Tailscale Serve policy."""

import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from nix_adapter import AdapterContext, BaseAdapter, Change, Conflict, Files, Native
from schema import AIManifest, Model, Unmanaged


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
            return False
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
        """Withdraw the router, its proxy site and the public route.

        Prepared binaries, models and receipts stay: they are mutable assets
        that are expensive to rebuild. Caddy itself stays installed.
        """
        if not self.desired["llama"]:
            print("AI services purged: not managed.")
            return
        d = self.managed()
        if d["proxy"]:
            # Withdraw public exposure first.
            target = f"http://127.0.0.1:{d['localPort']}"
            port = str(d["httpsPort"])
            status = self.run(
                "tailscale", "serve", "status", "--json", check=False
            ).stdout
            if target in status and port in status:
                self.run("tailscale", "serve", f"--https={port}", "off")
            site = self.path_str(
                "caddySite", "/etc/caddy/conf.d/nix-config-llama.caddy"
            )
            if (
                self.remove(site)
                and self.unit("caddy.service").get("ActiveState") == "active"
            ):
                self.run(
                    "caddy",
                    "reload",
                    "--config",
                    self.path_str("caddyMain", "/etc/caddy/Caddyfile"),
                    "--address",
                    "unix//run/caddy/admin.socket",
                )
        state = self.unit("llama-swap.service")
        if (
            state.get("UnitFileState") == "enabled"
            or state.get("ActiveState") == "active"
        ):
            self.systemd.disable("llama-swap.service", now=True)
        unit = self.remove(
            self.path_str("switcherUnit", "/etc/systemd/system/llama-swap.service")
        )
        self.remove(self.path_str("switcherConfig", "/etc/llama-swap/config.yaml"))
        if unit:
            self.systemd.daemon_reload()
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
            return [Change("=", "AI services unmanaged")]
        d, f = self.managed(), self.files
        if not self.preflight(installed=True):
            return [Change("-", "AI preparation never completed; run nacre ai prepare")]
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
            print("AI services unmanaged.")
            return
        d = self.managed()
        if not preflighted and not self.preflight(installed=True):
            print("AI services skipped: selected model is not prepared.")
            return
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
        self.write(caddy_file, self.caddy_main(), "ai-caddy")
        self.write(caddy_site, d["generated"]["caddySite"], "ai-caddy")
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
            self.run("tailscale", "serve", "--bg", f"--https={port}", target)
            self.actions += 1
            status = self.run("tailscale", "serve", "status", "--json").stdout
            if target not in status or port not in status:
                raise Conflict("Tailscale Serve route did not converge")
        f.clear("ai-serve")
