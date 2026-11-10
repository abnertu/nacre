# pyright: standard
"""Open captured dependencies with native path semantics; reject unrelated files."""

import sys
import tomllib
from pathlib import Path


def read(path: Path) -> dict:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def certificate(document: dict, path: Path) -> bytes | None:
    reference = document.get("gitlab", {}).get("ca_certificate")
    if reference is None:
        return None
    # Do not resolve lexically: the kernel must walk every directory in the
    # original reference, including a directory before a parent component.
    return (path.parent / reference).read_bytes()


def main() -> None:
    source = Path(sys.argv[1])
    inherited = overridden = False
    for selected in map(Path, sys.argv[2:]):
        assert selected.is_relative_to(source), "selected path escaped the capture"
        instance = read(selected)
        base = selected.parent / instance["extends"]
        defaults = read(base)
        assert certificate(defaults, base), "base certificate was lost"
        if "ca_certificate" in instance.get("gitlab", {}):
            assert certificate(instance, selected), "override certificate was lost"
            overridden = True
        else:
            inherited = True
    assert inherited and overridden, "exercise inherited and overridden certificates"
    for path in source.rglob("*"):
        assert not path.is_symlink(), "the capture retained a symlink"
        if path.is_file():
            assert b"Synthetic unselected fixture" not in path.read_bytes(), (
                "an unrelated synthetic file entered the store source"
            )


if __name__ == "__main__":
    main()
