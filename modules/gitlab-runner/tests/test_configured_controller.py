# pyright: standard
"""Exercise the configured executable without running native operations."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    wrapper = Path(sys.argv[1])
    selected = sys.argv[2:]
    with tempfile.TemporaryDirectory(prefix="configured-controller-") as directory:
        environment = {
            **os.environ,
            "NACRE_RUNNER_TEST": "synthetic environment; $(false) ' \"",
            "NACRE_RUNNER_TEST_EXIT": "0",
            # The wrapper must resolve its supplied executable independently of PATH.
            "PATH": directory,
        }
        for arguments in (
            ["validate"],
            ["register", "frontend"],
            ["verify", "dotnet"],
            ["status", "frontend"],
            ["--verbose", "plan", "dotnet", "--json"],
            ["status", "synthetic argument; $(false) ' \"", ""],
        ):
            result = subprocess.run(
                [str(wrapper), *arguments],
                cwd=directory,
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )
            observed = json.loads(result.stdout)
            expected = ["--platform", "arch"]
            for file in selected:
                expected.extend(["--config", file])
            assert observed["argv"] == expected + arguments
            assert observed["environment"] == environment["NACRE_RUNNER_TEST"]
            assert observed["cwd"] == directory
            assert result.stderr == "synthetic controller stderr\n"

        environment["NACRE_RUNNER_TEST_EXIT"] = "23"
        failed = subprocess.run(
            [str(wrapper), "--verbose", "plan", "frontend", "--json"],
            cwd=directory,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert failed.returncode == 23, failed
        assert json.loads(failed.stdout)["argv"][-4:] == [
            "--verbose",
            "plan",
            "frontend",
            "--json",
        ]
        assert failed.stderr == "synthetic controller stderr\n"


if __name__ == "__main__":
    main()
