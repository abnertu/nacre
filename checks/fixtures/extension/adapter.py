"""Fixture extension adapter: proves arch-switch passes the manifest and phase."""

import json
import sys
from pathlib import Path

manifest, phase = sys.argv[1], sys.argv[2]
data = json.loads(Path(manifest).read_text())
if data != {"greeting": "fixture"} or phase not in ("preflight", "plan", "converge"):
    sys.exit(f"fixture extension: unexpected {phase} with {data}")
print(f"Fixture extension {phase}: ok.")
