#!/usr/bin/env python3
"""On-live-report driver: snapshot_restore. Runs tests/snapshots regression suite."""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DRIVER = REPO_ROOT / "scripts/testing/pytest_in_tmp.sh"

cmd = ["bash", str(DRIVER), "-q", "tests/snapshots/test_snapshots.py", *sys.argv[1:]]
sys.exit(subprocess.run(cmd, cwd=REPO_ROOT, env={**os.environ}).returncode)
