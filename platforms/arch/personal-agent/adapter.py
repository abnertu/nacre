"""Converge the Arch Personal Agent without transporting runtime secrets."""

from __future__ import annotations

import re
import stat
import subprocess
from pathlib import Path

from nix_adapter import (
    BaseServiceAdapter,
    Change,
    Conflict,
    Native,
    NotReady,
    run_adapter_cli,
)


def execute(
    *argv: str, allow_failure: bool = False
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv, text=True, capture_output=True, timeout=60, check=not allow_failure
        )
    except subprocess.TimeoutExpired as error:
        raise Conflict(f"command timed out: {argv[0]}") from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "").strip()
        message = f"command failed ({error.returncode}): {argv[0]}"
        if detail:
            message = f"{message}: {detail}"
        raise Conflict(message) from None


class _AdapterRunner(Native):
    def __init__(self, adapter: PersonalAgent):
        super().__init__()
        self._adapter = adapter

    def run(
        self, *argv: str, check: bool = True, **kwargs
    ) -> subprocess.CompletedProcess[str]:
        return self._adapter.run(*argv, allow_failure=not check)


class PersonalAgent(BaseServiceAdapter):
    def __init__(self, desired: dict[str, object], root: Path = Path("/"), run=execute):
        self.run = run
        super().__init__(desired=desired, root=root, runner=_AdapterRunner(self))

    def validate_file(self, key: str, mode_mask: int = 0o022) -> Path:
        path = self.path(key)
        if path.is_symlink() or not path.is_file():
            raise Conflict(f"Personal Agent {key} must be a regular file")
        info = path.stat()
        if info.st_nlink != 1 or (info.st_uid != 0 and self.root == Path("/")):
            raise Conflict(f"Personal Agent {key} has unsafe ownership")
        if stat.S_IMODE(info.st_mode) & mode_mask:
            raise Conflict(f"Personal Agent {key} is writable by an unsafe identity")
        return path

    def validate_secrets(self, path: Path) -> None:
        keys: set[str] = set()
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            match = re.fullmatch(r"(DISCORD_TOKEN|NOTION_TOKEN)=(.+)", stripped)
            if not match or match.group(1) in keys:
                raise Conflict("Personal Agent secret configuration is invalid")
            keys.add(match.group(1))
        if keys != {"DISCORD_TOKEN", "NOTION_TOKEN"}:
            raise Conflict("Personal Agent secret configuration is incomplete")

    def preflight(self, installed: bool = False) -> None:
        if not self.desired.get("enabled"):
            return
        missing = [key for key in ("config", "secrets") if not self.path(key).exists()]
        if missing:
            if self.path("receipt").exists():
                raise Conflict(
                    "prepared Personal Agent runtime configuration is missing"
                )
            raise NotReady("runtime configuration is not prepared")
        config = self.validate_file("config")
        secrets = self.validate_file("secrets")
        self.validate_secrets(secrets)
        executable = self.desired.get("executable")
        if not isinstance(executable, str) or not Path(executable).is_file():
            raise Conflict("Personal Agent executable is missing")
        self.run(executable, "check-config", "--config", str(config))
        self.run(
            executable,
            "check-runtime",
            "--config",
            str(config),
            "--env-file",
            str(secrets),
        )
        self.account(create=False)

    def account(self, create: bool) -> None:
        self.ensure_system_account("personal-agent", create=create)

    def write_unit(
        self,
        path: Path | None = None,
        unit: object = None,
        receipt: Path | None = None,
        pending: Path | None = None,
        mode: int = 0o644,
    ) -> bool:
        p = path or self.path("unitPath")
        u = unit if unit is not None else self.desired.get("unit")
        if not isinstance(u, str):
            raise Conflict("Personal Agent unit is invalid")
        r = receipt or self.path("receipt")
        pend = pending or self.path("pending")
        return super().write_unit(p, u, r, pend, mode=mode)

    def plan(self) -> list[Change]:
        """What converge would change; preparation and secrets are only checked."""
        if not self.desired.get("enabled"):
            return [Change("=", "Personal Agent unmanaged")]
        try:
            self.preflight()
        except NotReady as error:
            return [Change("-", f"Personal Agent not ready: {error}")]
        unit_path = self.path("unitPath")
        if not unit_path.exists():
            unit = Change("+", str(unit_path))
        elif unit_path.read_text() != self.desired.get("unit"):
            unit = Change("~", f"{unit_path} (content differs)")
        else:
            unit = Change("=", str(unit_path))
        changes = [unit]
        name = "personal-agent.service"
        if not self.systemd.is_enabled(name):
            changes.append(Change("~", f"enable {name}"))
        if not self.systemd.is_active(name):
            changes.append(Change("~", f"start {name}"))
        elif unit.kind != "=" or self.path("pending").exists():
            changes.append(Change("~", f"restart {name}"))
        if len(changes) == 1 and unit.kind == "=":
            changes.append(Change("=", name))
        return changes

    def converge(self) -> None:
        if not self.desired.get("enabled"):
            return
        self.preflight()
        retry = self.path("pending").exists()
        self.path("pending").touch()
        self.account(create=True)
        state = self.path("state")
        self.run(
            "install",
            "-d",
            "-m0750",
            "-o",
            "personal-agent",
            "-g",
            "personal-agent",
            str(state),
        )
        self.ensure_metadata(self.path("config"), "root", "personal-agent", 0o640)
        self.ensure_metadata(self.path("secrets"), "root", "root", 0o600)
        changed = self.write_unit()
        if changed:
            self.systemd.daemon_reload()
        if not self.systemd.is_enabled("personal-agent.service"):
            self.systemd.enable("personal-agent.service")
        if not self.systemd.is_active("personal-agent.service"):
            self.systemd.start("personal-agent.service")
        elif changed or retry:
            self.systemd.restart("personal-agent.service")
        self.path("receipt").touch()
        self.path("pending").unlink(missing_ok=True)


def main() -> int:
    return run_adapter_cli(
        lambda desired: PersonalAgent(desired),
        name="Personal Agent",
    )


if __name__ == "__main__":
    raise SystemExit(main())
