#!/usr/bin/env python3
"""Fake Arch commands. Only the test harness installs these executables."""

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

root = Path(os.environ["ARCH_TEST_ROOT"])
state_path = root / "state.json"
state = json.loads(state_path.read_text())
command = Path(sys.argv[0]).name
args = sys.argv[1:]
privileged = command == "sudo"
if privileged:
    if args == ["-v"]:
        sys.exit(0)
    command, args = Path(args[0]).name, args[1:]
with (root / "commands.jsonl").open("a") as log:
    log.write(json.dumps([command, *args]) + "\n")
if state.get("fail") == [command, *args[:1]]:
    sys.exit(1)


def save():
    state_path.write_text(json.dumps(state))


def target(value):
    path = Path(value)
    assert path.is_relative_to(root), value
    # Tests may make /etc read-only to the login user; root writes regardless.
    if privileged:
        for item in (path.parent, path):
            if item.exists():
                item.chmod(item.stat().st_mode | 0o200)
    return path


if command == "python":
    assert args[:2] in (
        ["/fixture/adapter", "/fixture/manifest"],
        ["/fixture/ai-adapter", "/fixture/ai-manifest"],
        ["/fixture/personal-agent-adapter", "/fixture/personal-agent-manifest"],
    )
    assert args[2] in ("preflight", "converge")
    assert len(args) == 3 or args[3:] == ["--verbose"]
    if args[0] == "/fixture/ai-adapter" and state.get("ai_not_ready"):
        sys.exit(20)
    if (
        args[0] == "/fixture/ai-adapter"
        and args[2] == "converge"
        and state.get("ai_converge_not_ready")
    ):
        sys.exit(20)
    if args[0] == "/fixture/personal-agent-adapter" and state.get(
        "personal_agent_not_ready"
    ):
        sys.exit(20)
    if (
        args[0] == "/fixture/personal-agent-adapter"
        and args[2] == "converge"
        and state.get("personal_agent_converge_not_ready")
    ):
        sys.exit(20)
elif command == "id":
    print(
        state.get("user", "tester")
        if "--name" in args
        else " ".join(state["groups"])
        if "-nG" in args
        else "1000"
    )
elif command == "pacman-conf":
    if args[:2] == ["--repo", "multilib"]:
        sys.exit(1 if state.get("no_multilib") else 0)
    if "--config" not in args and not state.get("unmanaged_repo"):
        if (
            "Include = /etc/pacman.d/nix-config-lizardbyte.conf"
            not in (root / "etc/pacman.conf").read_text()
        ):
            sys.exit(1)
    print("https://repo.example")
elif command == "pacman":
    if "--query" in args:
        sys.exit(1 if args[-1] in state.get("missing", []) else 0)
    if "--sysupgrade" in args:
        if state.get("upgrade_failure"):
            sys.exit(1)
        state["missing"] = []
        if state.get("kernel_upgrade"):
            shutil.rmtree(root / "usr/lib/modules")
        save()
elif command in ("yay", "curl"):
    pass
elif command == "bsdtar":
    print("sunshine-1/desc")
elif command == "install":
    if "-d" in args:
        target(args[-1]).mkdir(parents=True, exist_ok=True)
    else:
        shutil.copyfile(args[-2], target(args[-1]))
        target(args[-1]).chmod(0o644)
elif command == "mkdir":
    target(args[-1]).mkdir(parents=True, exist_ok=True)
elif command == "mktemp":
    descriptor, name = tempfile.mkstemp(
        prefix=".nix-config.", dir=target(args[-1]).parent
    )
    os.close(descriptor)
    print(name)
elif command == "mv":
    target(args[-2]).replace(target(args[-1]))
elif command == "rm":
    path = target(args[-1])
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)
elif command == "touch":
    target(args[-1]).touch()
elif command == "mkinitcpio":
    target(str(root / "boot/initramfs-linux.img")).write_text("image")
elif command == "modprobe":
    (root / "sys/module" / args[0]).mkdir(parents=True, exist_ok=True)
elif command == "gpasswd":
    state["groups"].append(args[-1])
    save()
elif command == "systemctl":
    user = "--user" in args
    args = [value for value in args if value not in ("--user", "--quiet")]
    verb, *units = args
    if verb == "daemon-reload":
        sys.exit(0)
    key = ("user:" if user else "system:") + units[0]
    service = state.setdefault("services", {}).setdefault(key, {})
    if verb == "is-enabled":
        sys.exit(0 if service.get("enabled") else 1)
    if verb == "is-active":
        sys.exit(0 if service.get("active") else 3)
    if verb == "start" and units[0] in state.get("inactive_after_start", []):
        sys.exit(0)
    service["enabled" if verb == "enable" else "active"] = True
    save()
elif command == "sysctl":
    if args[0] == "-n":
        print(state.setdefault("sysctl", {}).get(args[1], "0"))
    else:
        key, value = args[1].split("=", 1)
        state.setdefault("sysctl", {})[key] = value
        save()
elif command == "getcap":
    if state.get("capability"):
        print(args[0] + " cap_sys_admin=p")
elif command == "setcap":
    state["capability"] = True
    save()
else:
    raise AssertionError((command, args))
