#!/usr/bin/env python3
"""On-live-report driver: pytest. Runs the full suite via pytest_in_tmp.sh."""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DRIVER = REPO_ROOT / "scripts/testing/pytest_in_tmp.sh"
REPORT_HINT = "runtime/reports/security/production_gate/pytest_*"


def progress(message: str) -> None:
    print(f"[on-live:pytest] {message}", file=sys.stderr, flush=True)

if not DRIVER.exists():
    print(f"ERROR: {DRIVER} missing", file=sys.stderr)
    sys.exit(2)

cmd = ["bash", str(DRIVER), "-q", "tests", *sys.argv[1:]]
progress(f"target repo: {REPO_ROOT}")
progress(f"artifact hint: {REPORT_HINT}")
progress("phase pytest-in-tmp started: selected pytest suite")
rc = subprocess.run(cmd, cwd=REPO_ROOT, env={**os.environ}).returncode
progress(f"phase result pytest-in-tmp: exit={rc}")
if rc != 0:
    progress("failure hint: inspect pytest-in-tmp output and preserved tmp copy path if cleanup was skipped")
sys.exit(rc)
