#!/usr/bin/env python3
"""On-live-report driver: functional. Runs core functional smoke + smoke_suite.py."""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_SH = REPO_ROOT / "scripts/security/pentest/run_functional_smoke.sh"
SMOKE_SUITE = REPO_ROOT / "tests/security/smoke/smoke_suite.py"
REPORT_HINT = "runtime/reports/security/functional_<RUN_ID>/"


def progress(message: str) -> None:
    print(f"[on-live:functional] {message}", file=sys.stderr, flush=True)

if not SMOKE_SH.exists():
    print(f"ERROR: {SMOKE_SH} missing", file=sys.stderr)
    sys.exit(2)

env = {**os.environ}
progress(f"target repo: {REPO_ROOT}")
progress(f"artifact hint: {REPORT_HINT}")
smoke_args = list(sys.argv[1:])
if "--qa-full" not in smoke_args and "--core-only" not in smoke_args:
    smoke_args.append("--core-only")
    env["GO_LIVE_CORE_ONLY"] = "1"
progress(f"phase functional smoke started args={' '.join(smoke_args) or '<none>'}")
rc = subprocess.run(["bash", str(SMOKE_SH), *smoke_args], cwd=REPO_ROOT, env=env).returncode
progress(f"phase result functional smoke: exit={rc}")
if rc != 0:
    progress("failure hint: inspect run_functional_smoke raw outputs under the functional report directory")
    sys.exit(rc)

if SMOKE_SUITE.exists():
    progress("phase smoke suite started")
    rc = subprocess.run([sys.executable, str(SMOKE_SUITE)], cwd=REPO_ROOT, env=env).returncode
    progress(f"phase result smoke suite: exit={rc}")
    if rc != 0:
        progress("failure hint: inspect smoke_suite output above")

sys.exit(rc)
