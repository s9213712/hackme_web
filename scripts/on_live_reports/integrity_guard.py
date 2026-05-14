#!/usr/bin/env python3
"""On-live-report driver: integrity_guard. Runs tests/security/integrity regression suite.

Production gate also expects a manual rescan + report fetch via the root API
(`POST /api/root/integrity/rescan` then `GET /api/root/integrity/report`).
This driver covers the regression-test side; pair it with the API calls when
generating the production gate package.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DRIVER = REPO_ROOT / "scripts/testing/pytest_in_tmp.sh"
REPORT_HINT = "runtime/reports/security/production_gate/integrity_guard_*"


def progress(message: str) -> None:
    print(f"[on-live:integrity-guard] {message}", file=sys.stderr, flush=True)

cmd = [
    "bash",
    str(DRIVER),
    "-q",
    "tests/security/integrity/test_integrity_guard.py",
    *sys.argv[1:],
]
progress(f"target repo: {REPO_ROOT}")
progress(f"artifact hint: {REPORT_HINT}")
progress("phase pytest-in-tmp started: integrity guard regressions")
rc = subprocess.run(cmd, cwd=REPO_ROOT, env={**os.environ}).returncode
progress(f"phase result pytest-in-tmp: exit={rc}")
if rc != 0:
    progress("failure hint: inspect integrity guard pytest output and root integrity rescan evidence")
sys.exit(rc)
