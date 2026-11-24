"""Nacre's published release tags, read from its Git remote."""

from __future__ import annotations

import os
import re
import subprocess

from .common import Refusal

URL = "github:abnertu/nacre"
# Tests point this at a local repository; the Nix wrapper puts the real git
# first on PATH, so a fake git cannot stand in for the remote.
REMOTE = (
    os.environ.get("NACRE_TEST_RELEASE_REMOTE") or "https://github.com/abnertu/nacre"
)
TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")


def version(tag: str) -> tuple[int, int, int]:
    """The version numbers of a release tag such as v0.11.0."""
    match = TAG.fullmatch(tag)
    if match is None:
        raise ValueError(tag)
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def tags() -> dict[str, str]:
    """Each release tag on the remote, mapped to the commit that it names."""
    result = subprocess.run(
        ["git", "ls-remote", "--tags", REMOTE, "v*"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise Refusal(
            f"cannot read the Nacre releases from {REMOTE}: {result.stderr.strip()}"
        )
    found: dict[str, str] = {}
    peeled: dict[str, str] = {}
    for line in result.stdout.splitlines():
        commit, _, ref = line.partition("\t")
        name = ref.removeprefix("refs/tags/")
        if name.endswith("^{}"):
            peeled[name[:-3]] = commit
        elif TAG.fullmatch(name):
            found[name] = commit
    # An annotated tag names a tag object; its peeled line names the commit.
    return {name: peeled.get(name, commit) for name, commit in found.items()}


def newest(available: dict[str, str]) -> tuple[str, str]:
    """The highest release tag and its commit."""
    if not available:
        raise Refusal(f"no Nacre release tag found at {REMOTE}")
    tag = max(available, key=version)
    return tag, available[tag]
