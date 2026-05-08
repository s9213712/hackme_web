#!/usr/bin/env python3
"""On-live-report driver: pytest. Runs the full suite via pytest_in_tmp.sh."""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DRIVER = REPO_ROOT / "scripts/testing/pytest_in_tmp.sh"

if not DRIVER.exists():
    print(f"ERROR: {DRIVER} missing", file=sys.stderr)
    sys.exit(2)

cmd = ["bash", str(DRIVER), "-q", "tests", *sys.argv[1:]]
sys.exit(subprocess.run(cmd, cwd=REPO_ROOT, env={**os.environ}).returncode)
