"""PyInstaller entry: launches the Gifkit CLI/GUI from the frozen bundle."""
import os
import sys

# windowed (console=False) builds have no stdout; builders print() freely,
# so give them a sink before anything imports
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

from gifkit.cli import main

sys.exit(main())
