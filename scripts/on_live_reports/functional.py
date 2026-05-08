#!/usr/bin/env python3
"""On-live-report driver: functional. Runs run_functional_smoke.sh + smoke_suite.py."""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_SH = REPO_ROOT / "scripts/security/pentest/run_functional_smoke.sh"
SMOKE_SUITE = REPO_ROOT / "tests/security/smoke/smoke_suite.py"

if not SMOKE_SH.exists():
    print(f"ERROR: {SMOKE_SH} missing", file=sys.stderr)
    sys.exit(2)

env = {**os.environ}
rc = subprocess.run(["bash", str(SMOKE_SH), *sys.argv[1:]], cwd=REPO_ROOT, env=env).returncode
if rc != 0:
    sys.exit(rc)

if SMOKE_SUITE.exists():
    rc = subprocess.run([sys.executable, str(SMOKE_SUITE)], cwd=REPO_ROOT, env=env).returncode

sys.exit(rc)
