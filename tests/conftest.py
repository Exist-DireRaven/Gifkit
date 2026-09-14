"""Make the repo's helper modules importable when tests load them in-process.

- The repo root is needed to import the gifkit package (and its CLI).
- v2/ is on the path because the build/verify scripts live in v2/ and v3/
  and import each other by module name (``import morph``), which works when
  run as scripts (sys.path[0] is the script directory) but not under
  importlib in-process.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for entry in (str(ROOT), str(ROOT / "v2")):
    if entry not in sys.path:
        sys.path.insert(0, entry)
