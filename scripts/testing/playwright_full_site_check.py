#!/usr/bin/env python3
"""Stable entrypoint for the broad Playwright full-site smoke.

This wrapper keeps the documented script name available while delegating the
actual coverage to ``playwright_deep_site_check.py``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEEP_CHECK = ROOT / "scripts" / "testing" / "playwright_deep_site_check.py"


def main() -> int:
    cmd = [sys.executable, str(DEEP_CHECK), "--max-chess-human-moves", "6", *sys.argv[1:]]
    return subprocess.call(cmd, cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
