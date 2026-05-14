#!/usr/bin/env python3
"""On-live-report driver: snapshot_restore. Runs tests/snapshots regression suite."""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DRIVER = REPO_ROOT / "scripts/testing/pytest_in_tmp.sh"
REPORT_HINT = "runtime/reports/security/production_gate/snapshot_restore_*"


def progress(message: str) -> None:
    print(f"[on-live:snapshot-restore] {message}", file=sys.stderr, flush=True)

cmd = ["bash", str(DRIVER), "-q", "tests/snapshots/test_snapshots.py", *sys.argv[1:]]
progress(f"target repo: {REPO_ROOT}")
progress(f"artifact hint: {REPORT_HINT}")
progress("phase pytest-in-tmp started: snapshot restore regressions")
rc = subprocess.run(cmd, cwd=REPO_ROOT, env={**os.environ}).returncode
progress(f"phase result pytest-in-tmp: exit={rc}")
if rc != 0:
    progress("failure hint: inspect snapshot pytest output and restore/reset runtime artifacts")
sys.exit(rc)
