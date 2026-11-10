# pyright: standard
"""Guest-only fixtures for unrelated Arch and Home Manager boundaries."""

import json
import os
import shutil
import ssl
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

STATE = Path("/run/nacre-native")


def home():
    if "--plan" not in sys.argv:
        with (STATE / "home-activations").open("a") as stream:
            stream.write("activate\n")


def configure(file, executable):
    path = Path(file)
    config = json.loads(path.read_text())
    config.update(
        fsRoot="/run/nacre-native/root",
        nativeBin="/run/nacre-native/bin",
        pacman=[],
        aur=[],
        hold=[],
        lizardbyte=[],
        userServices=[],
    )
    config["extensions"] = [
        entry for entry in config["extensions"] if entry["name"] == "gitlab-runner"
    ]
    config["adapters"] = {
        name: (
            entry
            if name == "gitlab-runner"
            else {"adapter": executable, "manifest": name}
        )
        for name, entry in config["adapters"].items()
        if name in ("core", "system", "ai", "gitlab-runner")
    }
    path.write_text(json.dumps(config))


def withdraw_nixos_podman():
    # Preserve the guest's public user-bus policy; the controller owns Podman.
    units = Path("/etc/systemd/user")
    target = STATE / "user-units"
    shutil.copytree(units, target, symlinks=True)
    for path in list(target.rglob("*")):
        if path.name in (
            "podman.service",
            "podman.socket",
            "podman.service.d",
            "podman.socket.d",
        ):
            if path.is_symlink() or not path.is_dir():
                path.unlink(missing_ok=True)
            else:
                shutil.rmtree(path)
    units.unlink()
    units.symlink_to(target)


def setup(paths, executable):
    STATE.mkdir(mode=0o755)
    (STATE / "controller-calls").touch()
    (STATE / "home-activations").touch()
    withdraw_nixos_podman()
    for directory in (
        "root/etc",
        "root/usr/lib/modules/" + os.uname().release,
        "root/run/user/1000",
        "bin",
    ):
        (STATE / directory).mkdir(parents=True)
    (STATE / "root/etc/arch-release").touch()
    subprocess.run(["chown", "fixture", str(STATE / "home-activations")], check=True)
    subprocess.run(["chown", "fixture", str(STATE / "root/run/user/1000")], check=True)
    for name, source in {
        **json.loads(Path(paths).read_text()),
        "id": "/run/current-system/sw/bin/id",
        "sudo": "/run/wrappers/bin/sudo",
        "pacman": executable,
        "pacman-conf": executable,
        "yay": executable,
    }.items():
        (STATE / "bin" / name).symlink_to(source)
    # Never let NixOS-generated symlinks stand in for native writable files.
    for file in (Path("/etc/subuid"), Path("/etc/subgid")):
        content = file.read_bytes() if file.exists() else b""
        file.unlink(missing_ok=True)
        file.write_bytes(content)
        file.chmod(0o644)
    # Shadow's automatic allocation would race the controller's explicit policy.
    Path("/etc/login.defs").unlink()
    Path("/etc/login.defs").write_text("SUB_UID_COUNT 0\nSUB_GID_COUNT 0\n")
    # Load the socket from its real Arch vendor path, not a NixOS symlink path.
    Path("/usr/lib/systemd/user/podman.socket").write_text(
        "[Unit]\nDescription=Podman API Socket\n[Socket]\n"
        "ListenStream=%t/podman/podman.sock\nSocketMode=0660\n"
        "[Install]\nWantedBy=sockets.target\n"
    )
    Path("/usr/lib/systemd/user/podman.service").write_text(
        "[Unit]\nDescription=Podman API Service\nRequires=podman.socket\n"
        "After=podman.socket\n[Service]\nType=exec\n"
        "ExecStart=/usr/bin/podman system service --time=0\nKillMode=process\n"
    )
    # Generate the private key only in guest runtime; suppress OpenSSL output.
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(STATE / "health.key"),
            "-out",
            str(STATE / "health.crt"),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    (STATE / "health.key").chmod(0o600)
    bundle = Path("/etc/ssl/certs/ca-certificates.crt")
    public = bundle.read_bytes() + (STATE / "health.crt").read_bytes()
    bundle.unlink()
    bundle.write_bytes(public)


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/health" else 404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format, *args):
        pass


def serve():
    server = HTTPServer(("127.0.0.1", 8443), Health)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(STATE / "health.crt", STATE / "health.key")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


def preserve():
    # These values are synthetic and exist only in the disposable guest.
    path = Path("/home/gitlab-runner-frontend/gitlab-runner/config/config.toml")
    with path.open("a") as stream:
        stream.write(
            '\n[[runners]]\nname = "Synthetic registration"\n'
            'url = "https://localhost:8443"\nid = 42\n'
            'token = "synthetic-fixture-registration"\nexecutor = "docker"\n'
            '[runners.docker]\nimage = "fixture.invalid/job"\n'
        )


def main():
    arguments = sys.argv[1:]
    if arguments[0] == "configure":
        configure(*arguments[1:])
    elif arguments[0] == "setup":
        setup(*arguments[1:])
    elif arguments[0] == "serve":
        serve()
    elif arguments[0] == "preserve":
        preserve()
    elif arguments[0] in ("core", "system", "ai"):
        # These boundaries have their own real Arch/container tests.
        with (STATE / "adapter-calls").open("a") as stream:
            stream.write(" ".join(arguments) + "\n")
    elif Path(sys.argv[0]).name not in ("pacman", "pacman-conf", "yay"):
        raise SystemExit("unexpected native fixture command")


if __name__ == "__main__":
    main()
