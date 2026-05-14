#!/usr/bin/env python3
"""On-live-report driver: cloud_drive_quota_permission. Runs tests/storage regression suite."""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DRIVER = REPO_ROOT / "scripts/testing/pytest_in_tmp.sh"
REPORT_HINT = "runtime/reports/security/production_gate/cloud_drive_quota_permission_*"


def progress(message: str) -> None:
    print(f"[on-live:cloud-drive-quota-permission] {message}", file=sys.stderr, flush=True)

cmd = [
    "bash",
    str(DRIVER),
    "-q",
    "tests/storage/test_cloud_drive_attachments.py",
    "tests/storage/test_storage_albums_schema.py",
    *sys.argv[1:],
]
progress(f"target repo: {REPO_ROOT}")
progress(f"artifact hint: {REPORT_HINT}")
progress("phase pytest-in-tmp started: storage quota and permission regressions")
rc = subprocess.run(cmd, cwd=REPO_ROOT, env={**os.environ}).returncode
progress(f"phase result pytest-in-tmp: exit={rc}")
if rc != 0:
    progress("failure hint: inspect pytest-in-tmp output and storage/cloud-drive permission failures above")
sys.exit(rc)
