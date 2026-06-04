"""Console helpers shared by command-line entry points."""
from __future__ import annotations

import sys


def configure_utf8_stdio() -> None:
    """Keep Korean/status-symbol output usable on Windows legacy consoles."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
