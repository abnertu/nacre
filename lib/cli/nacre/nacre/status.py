"""status and changes: what the machine runs, and what updates changed."""

from __future__ import annotations

import datetime
import re

from .common import ROOT, Refusal, parse_time, pending_work, revision, styled
from .generations import current_generation
from .machine import Machine, record_path

PACMAN_LOG = ROOT / "var/log/pacman.log"
PACKAGE_EVENT = re.compile(
    r"\[(?P<when>[^\]]+)\] \[ALPM\] "
    r"(?P<action>installed|upgraded|downgraded|reinstalled|removed) "
    r"(?P<name>\S+) \((?P<versions>[^)]*)\)"
)
ACTIONS = ("upgraded", "downgraded", "installed", "reinstalled", "removed")


def status(machine: Machine) -> int:
    """Print the checkout, the last switch, the home generation and pending work."""
    print(
        styled("Checkout     ", "1;36") + f"{machine.flake} ({revision(machine.flake)})"
    )
    record = record_path("last-switch")
    if record.is_file():
        when, switched, *_ = record.read_text().split()
        print(styled("Last switch  ", "1;36") + f"{when} from {switched}")
    else:
        print(styled("Last switch  ", "1;36") + styled("not recorded by nacre", "33"))
    current = current_generation()
    print(
        styled("Home         ", "1;36")
        + f"generation {current if current is not None else ''}"
    )
    pending = pending_work()
    if pending:
        print(
            styled("Pending      ", "1;36")
            + styled(f"{' '.join(pending)} (rerun the interrupted command)", "33")
        )
    else:
        print(styled("Pending      ", "1;36") + styled("none", "32"))
    return 0


def changes(since: str | None) -> int:
    """Print pacman's package changes since `since`, or since the last update."""
    start = parse_time(since if since is not None else last_update())
    sections = package_events(start)
    if not sections:
        print(f"No package changes since {start.isoformat()}.")
        return 0
    print(f"Package changes since {start.isoformat()}")
    for action in ACTIONS:
        entries = sorted(sections.get(action, []))
        if entries:
            width = max(len(name) for name, _ in entries)
            print(f"\n{action.capitalize()} ({len(entries)})")
            for name, versions in entries:
                print(f"  {name:<{width}}  {versions}")
    return 0


def last_update() -> str:
    """The start time of the last update that nacre recorded."""
    record = record_path("updates")
    starts = record.read_text().split() if record.is_file() else []
    if not starts:
        raise Refusal("no update recorded by nacre yet; pass --since TIME")
    return starts[-1]


def package_events(start: datetime.datetime) -> dict[str, list[tuple[str, str]]]:
    """pacman.log events from `start` on: action -> [(package, versions)]."""
    try:
        log = PACMAN_LOG.read_text(errors="replace").splitlines()
    except OSError as error:
        raise Refusal(f"cannot read {PACMAN_LOG}: {error.strerror}") from None
    sections: dict[str, list[tuple[str, str]]] = {}
    for line in log:
        event = PACKAGE_EVENT.match(line)
        if event is None:
            continue
        try:
            when = datetime.datetime.fromisoformat(event["when"])
        except ValueError:
            continue
        if when >= start:
            sections.setdefault(event["action"], []).append(
                (event["name"], event["versions"])
            )
    return sections
