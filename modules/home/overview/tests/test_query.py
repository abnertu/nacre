# pyright: standard
"""Exercise real Query QML against fake Quickshell signals, never native IPC."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

source = Path(sys.argv[1])
runner = sys.argv[2]
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    fixtures = Path(__file__).parent / "qml"
    shutil.copytree(fixtures, root / "test")
    (root / "test").chmod(0o700)
    subject = root / "test/subject"
    subject.mkdir()
    for name in ("HyprlandQuery.qml", "Refresh.js"):
        shutil.copyfile(source / name, subject / name)
    (subject / "qmldir").write_text("HyprlandQuery 1.0 HyprlandQuery.qml\n")
    runtime = root / "runtime"
    runtime.mkdir(mode=0o700)
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in (
            "DISPLAY",
            "WAYLAND_DISPLAY",
            "DBUS_SESSION_BUS_ADDRESS",
            "HYPRLAND_INSTANCE_SIGNATURE",
            "QML_IMPORT_PATH",
            "QML2_IMPORT_PATH",
        )
    }
    env.update(
        HOME=str(root),
        XDG_RUNTIME_DIR=str(runtime),
        QT_QPA_PLATFORM="offscreen",
        QT_QUICK_BACKEND="software",
    )
    subprocess.run(
        [
            runner,
            "-input",
            str(root / "test"),
            "-import",
            str(root / "test"),
            "-import",
            str(Path(runner).parent.parent / "lib/qt-6/qml"),
        ],
        env=env,
        check=True,
        timeout=20,
    )
