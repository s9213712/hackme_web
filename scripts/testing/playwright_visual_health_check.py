#!/usr/bin/env python3
"""Stable entrypoint for visual Playwright health checks.

Runs the standalone ComfyUI workflow builder visual check, then the broader
platform checker that records UI quality and overflow warnings.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILDER_CHECK = ROOT / "scripts" / "testing" / "playwright_comfyui_workflow_builder_check.py"
PLATFORM_CHECK = ROOT / "scripts" / "testing" / "playwright_platform_health_check.py"


def main() -> int:
    builder_rc = subprocess.call([sys.executable, str(BUILDER_CHECK)], cwd=str(ROOT))
    if builder_rc != 0:
        return builder_rc
    return subprocess.call([sys.executable, str(PLATFORM_CHECK), *sys.argv[1:]], cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
