#!/usr/bin/env python3
"""On-live-report driver: points_chain_consistency. Runs tests/points regression suite."""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DRIVER = REPO_ROOT / "scripts/testing/pytest_in_tmp.sh"
REPORT_HINT = "runtime/reports/security/production_gate/points_chain_consistency_*"


def progress(message: str) -> None:
    print(f"[on-live:points-chain-consistency] {message}", file=sys.stderr, flush=True)

cmd = ["bash", str(DRIVER), "-q", "tests/points/test_points_chain.py", *sys.argv[1:]]
progress(f"target repo: {REPO_ROOT}")
progress(f"artifact hint: {REPORT_HINT}")
progress("phase pytest-in-tmp started: PointsChain ledger consistency")
rc = subprocess.run(cmd, cwd=REPO_ROOT, env={**os.environ}).returncode
progress(f"phase result pytest-in-tmp: exit={rc}")
if rc != 0:
    progress("failure hint: inspect ledger/hash-chain pytest output and runtime points-chain artifacts")
sys.exit(rc)
