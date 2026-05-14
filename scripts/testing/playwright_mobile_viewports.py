#!/usr/bin/env python3
"""Stable entrypoint for mobile viewport Playwright health checks.

The platform health checker already exercises the mobile module views; this
wrapper provides the documented mobile-specific command name without forking the
coverage logic.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLATFORM_CHECK = ROOT / "scripts" / "testing" / "playwright_platform_health_check.py"


def main() -> int:
    return subprocess.call([sys.executable, str(PLATFORM_CHECK), *sys.argv[1:]], cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
