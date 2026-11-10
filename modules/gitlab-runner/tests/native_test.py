# pyright: standard
"""Real rootless lifecycle through the packaged deployment and Runner adapter."""

import json
from typing import Any

INSTANCES = (("dotnet", 1002), ("frontend", 1001))
IMAGE = "docker.io/gitlab/gitlab-runner:v18.10.1"


def run(machine: Any, setup: str, fixture: str, image: str, controller: str):
    prepare_guest(machine, setup, fixture, image)

    def user(name, uid, command):
        return (
            f"runuser -u gitlab-runner-{name} -- env -i PATH=/usr/bin "
            f"HOME=/home/gitlab-runner-{name} XDG_RUNTIME_DIR=/run/user/{uid} "
            f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus {command}"
        )

    def deploy(*arguments, success=True):
        command = "runuser -u fixture -- native-runner-deployment " + " ".join(
            arguments
        )
        command += " 2>&1"
        return machine.succeed(command) if success else machine.fail(command)

    def activations():
        return machine.succeed("wc -l </run/nacre-native/home-activations").strip()

    def snapshot():
        states = []
        for name, uid in INSTANCES:
            state = machine.succeed(
                user(
                    name,
                    uid,
                    f"/usr/bin/podman inspect --format '{{{{.Id}}}} {{{{.State.StartedAt}}}}' gitlab-runner-{name}",
                )
            ).strip()
            files = machine.succeed(
                f"find /home/gitlab-runner-{name}/.config/systemd/user "
                f"/home/gitlab-runner-{name}/gitlab-runner/config -type f "
                "-printf '%p %i %T@ %m %U %G\\n' | sort"
            )
            states.append((state, files))
        return states

    # Preview must not create Runner state before native prerequisites exist.
    machine.succeed(
        "sha256sum /etc/subuid /etc/subgid >/run/nacre-native/preview.sha256"
    )
    deploy("--plan")
    assert activations() == "0"
    machine.succeed("sha256sum --check /run/nacre-native/preview.sha256")
    for name, uid in INSTANCES:
        machine.fail(f"getent passwd gitlab-runner-{name}")
        machine.succeed(
            f"test ! -e /home/gitlab-runner-{name} && test ! -e /run/user/{uid}"
        )

    deploy()
    assert activations() == "1"
    check_instances(machine, user, controller)
    before = snapshot()
    deploy()
    assert snapshot() == before, "healthy repeat restarted a manager or rewrote policy"
    assert activations() == "2"

    # Native ownership conflicts stop at preflight, before either manager changes.
    unit = "/home/gitlab-runner-frontend/.config/systemd/user/gitlab-runner-frontend.service"
    machine.succeed(f"chown root {unit}")
    conflict = deploy(success=False)
    assert "foreign owner" in conflict
    assert activations() == "2"
    machine.succeed(f"chown gitlab-runner-frontend {unit}")
    assert snapshot() == before

    # Fail synchronously after pending intent, using a real failed image pull.
    name, uid = INSTANCES[0]
    machine.succeed(
        user(name, uid, f"/usr/bin/systemctl --user stop gitlab-runner-{name}.service")
    )
    machine.succeed(user(name, uid, f"/usr/bin/podman rmi {IMAGE}"))
    machine.succeed("systemctl stop docker-registry.service")
    deploy(success=False)
    pending = f"/home/gitlab-runner-{name}/gitlab-runner/config/.reconcile.pending"
    machine.succeed(f"test -f {pending}")
    assert activations() == "2"
    machine.succeed("systemctl start docker-registry.service")
    deploy()
    machine.succeed(f"test ! -e {pending}")
    assert activations() == "3"
    for instance, instance_uid in INSTANCES:
        machine.wait_until_succeeds(
            user(
                instance,
                instance_uid,
                f"/usr/bin/podman inspect --format '{{{{.State.Running}}}}' gitlab-runner-{instance}",
            )
            + " | grep -Fx true"
        )

    machine.succeed(f"{fixture} preserve")
    purge(machine, user, deploy, activations)


def check_instances(machine, user, controller):
    sockets = []
    mappings = {"uid": [], "gid": []}
    for name, uid in INSTANCES:
        machine.succeed(f"test $(id -u gitlab-runner-{name}) = {uid}")
        machine.succeed(f"test -S /run/user/{uid}/podman/podman.sock")
        sockets.append(
            machine.succeed(
                f"stat -c '%d:%i' /run/user/{uid}/podman/podman.sock"
            ).strip()
        )
        machine.wait_until_succeeds(
            user(
                name,
                uid,
                f"/usr/bin/podman inspect --format '{{{{.State.Running}}}}' gitlab-runner-{name}",
            )
            + " | grep -Fx true"
        )
        info = json.loads(
            machine.succeed(user(name, uid, "/usr/bin/podman info --format json"))
        )
        assert info["host"]["security"]["rootless"] is True
        assert info["host"]["networkBackend"] == "netavark"
        assert info["store"]["graphRoot"].startswith(f"/home/gitlab-runner-{name}/")
        for kind, previous in mappings.items():
            output = machine.succeed(
                user(
                    name,
                    uid,
                    f"/usr/bin/podman unshare /run/current-system/sw/bin/cat /proc/self/{kind}_map",
                )
            )
            ranges = [
                (int(row.split()[1]), int(row.split()[2]))
                for row in output.splitlines()
            ]
            assert len(ranges) >= 2, "rootless mapping lacks subordinate IDs"
            for start, count in ranges:
                assert count > 0
                for other_start, other_count in previous:
                    assert max(start, other_start) >= min(
                        start + count, other_start + other_count
                    ), "rootless instances share host subordinate IDs"
            previous.extend(ranges)
        for unit in (f"gitlab-runner-{name}.service", "podman.socket"):
            assert (
                machine.succeed(
                    user(name, uid, f"/usr/bin/systemctl --user is-active {unit}")
                ).strip()
                == "active"
            )
        status = machine.succeed(f"{controller} status {name}")
        assert "registration=absent" in status
        assert "container=matches-declaration" in status
    assert sockets[0] != sockets[1]


def purge(machine, user, deploy, activations):
    # Retain controlled data, stopped containers and unrelated active containers.
    for name, uid in INSTANCES:
        machine.succeed(
            user(
                name,
                uid,
                f"/usr/bin/podman create --name preserved-stopped {IMAGE} --version",
            )
        )
        machine.succeed(
            user(
                name,
                uid,
                f"/usr/bin/podman run -d --name preserved-running --entrypoint /bin/sh {IMAGE} -c 'while :; do sleep 1; done'",
            )
        )
        machine.succeed(
            f"printf fixture-cache >/home/gitlab-runner-{name}/gitlab-runner/cache/fixture-data && chown {uid}:$(id -g gitlab-runner-{name}) /home/gitlab-runner-{name}/gitlab-runner/cache/fixture-data"
        )
    # Hash only controlled guest config and data, including synthetic registration.
    machine.succeed(
        "sha256sum /etc/subuid /etc/subgid /home/gitlab-runner-*/gitlab-runner/config/config.toml /home/gitlab-runner-*/gitlab-runner/cache/fixture-data >/run/nacre-native/preserved.sha256"
    )
    preserved = container_states(machine, user)
    for _ in range(2):
        deploy("--purge")
        assert container_states(machine, user) == preserved, (
            "purge changed an unrelated container"
        )
    assert activations() == "3"
    machine.succeed("sha256sum --check /run/nacre-native/preserved.sha256")
    for name, uid in INSTANCES:
        machine.succeed(f"getent passwd gitlab-runner-{name}")
        machine.succeed(
            f"test ! -e /home/gitlab-runner-{name}/.config/systemd/user/gitlab-runner-{name}.service && test ! -e /home/gitlab-runner-{name}/gitlab-runner/config/registration-template.toml"
        )
        machine.fail(
            user(
                name,
                uid,
                f"/usr/bin/systemctl --user is-active gitlab-runner-{name}.service",
            )
        )
        machine.fail(
            user(name, uid, "/usr/bin/systemctl --user is-active podman.socket")
        )
        machine.fail(
            user(name, uid, f"/usr/bin/podman container exists gitlab-runner-{name}")
        )
        machine.succeed(user(name, uid, f"/usr/bin/podman image exists {IMAGE}"))
    calls = machine.succeed("cat /run/nacre-native/controller-calls").splitlines()
    assert "register" not in calls and "verify" not in calls
    assert calls.count("reconcile") >= 6 and calls.count("purge") == 4


def container_states(machine, user):
    states = []
    for name, uid in INSTANCES:
        for container, running in (
            ("preserved-stopped", "false"),
            ("preserved-running", "true"),
        ):
            output = machine.succeed(
                user(
                    name,
                    uid,
                    "/usr/bin/podman inspect --format '{{.Id}} {{.State.Running}} {{.State.StartedAt}} {{.Image}}' "
                    + container,
                )
            ).strip()
            assert output.split()[1] == running
            states.append(output)
    return states


def prepare_guest(machine, setup, fixture, image):
    machine.start()
    machine.wait_for_unit("multi-user.target")
    machine.succeed(f"{fixture} setup {setup} {fixture}")
    assert not machine.succeed("ip route show default").strip()
    machine.succeed(f"systemd-run --unit=native-health {fixture} serve")
    machine.wait_until_succeeds("curl --fail https://localhost:8443/health")
    machine.wait_for_unit("docker-registry.service")
    machine.succeed(
        f"skopeo copy --dest-tls-verify=false docker-archive:{image} "
        "docker://127.0.0.1:5000/gitlab/gitlab-runner:v18.10.1"
    )
