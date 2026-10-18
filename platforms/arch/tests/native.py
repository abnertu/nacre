# pyright: standard
#!/usr/bin/env python3
"""Fake Arch commands. Only the test harness installs these executables."""

import json
import os
import shutil
import sys
from pathlib import Path

root = Path(os.environ["ARCH_TEST_ROOT"])
state_path = root / "state.json"
state = json.loads(state_path.read_text())
command = Path(sys.argv[0]).name
args = sys.argv[1:]
if command == "sudo":
    if args == ["-v"]:
        sys.exit(0)
    command, args = Path(args[0]).name, args[1:]
with (root / "commands.jsonl").open("a") as log:
    log.write(json.dumps([command, *args]) + "\n")
if state.get("fail") == [command, *args[:1]]:
    sys.exit(1)


def save():
    state_path.write_text(json.dumps(state))


ADAPTERS = {
    "/fixture/core-adapter": ("/fixture/core-manifest", None),
    "/fixture/system-adapter": ("/fixture/system-manifest", None),
    "/fixture/ai-adapter": ("/fixture/ai-manifest", "ai"),
    "/fixture/personal-agent-adapter": (
        "/fixture/personal-agent-manifest",
        "personal_agent",
    ),
}

if command == "python":
    adapter, manifest, phase, *rest = args
    assert ADAPTERS[adapter][0] == manifest, args
    assert rest in ([], ["--verbose"], ["--color"], ["--verbose", "--color"]), args
    if adapter == "/fixture/core-adapter":
        assert phase in (
            "preflight",
            "plan",
            "repositories",
            "converge",
            "finish",
            "purge",
        )
    else:
        assert phase in ("preflight", "plan", "converge", "purge"), args
    optional = ADAPTERS[adapter][1]
    if optional and state.get(f"{optional}_not_ready"):
        sys.exit(20)
    if optional and phase == "converge" and state.get(f"{optional}_converge_not_ready"):
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
    print("https://repo.example")
elif command == "pacman":
    if args == ["--query", "--quiet"]:
        config = json.loads((root / "config.json").read_text())
        declared = config["pacman"] + config["lizardbyte"] + config["aur"]
        print("\n".join(p for p in declared if p not in state.get("missing", [])))
        sys.exit(0)
    if "--print" in args:
        if state.get("resolve_conflict"):
            print("https://repo.example/glibc.pkg.tar.zst")
            print(":: installing glibc breaks dependency required by lib32-glibc")
            print("error: failed to prepare transaction", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)
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
elif command == "systemctl":
    assert args[0] == "--user", args
    verb, unit = [value for value in args[1:] if value != "--quiet"]
    services = state.setdefault("user_services", [])
    if verb == "is-enabled":
        sys.exit(0 if unit in services else 1)
    services.append(unit)
    save()
else:
    raise AssertionError((command, args))
