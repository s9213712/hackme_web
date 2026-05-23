#!/usr/bin/env python3
"""RC1.1 operational integrity gate."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "artifacts" / "qa" / "pointschain_rc1_1_gate.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_step(name: str, cmd: list[str], *, timeout: int = 300) -> dict:
    started_at = utc_now()
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    return {
        "name": name,
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "started_at": started_at,
        "finished_at": utc_now(),
        "command": cmd,
        "output_tail": (proc.stdout or "")[-6000:],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run RC1.1 operational integrity checks.")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--skip-drill", action="store_true", help="Skip isolated restore drill.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    steps = [
        run_step(
            "rc1_1_ops_py_compile",
            [
                sys.executable,
                "-m",
                "py_compile",
                "scripts/ops/export_chain_anchor.py",
                "scripts/ops/rc1_restore_drill.py",
                "scripts/qa/points_chain_rc1_1_gate.py",
            ],
            timeout=120,
        ),
        run_step(
            "rc1_1_operational_tests",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/points/test_rc1_1_operational_integrity.py",
                "tests/snapshots/test_snapshots.py",
            ],
            timeout=240,
        ),
    ]
    if not args.skip_drill:
        steps.append(
            run_step(
                "isolated_restore_drill",
                [
                    sys.executable,
                    "scripts/ops/rc1_restore_drill.py",
                    "--out",
                    str(ROOT / "artifacts" / "ops" / "restore_drill_rc1_1_gate.json"),
                ],
                timeout=240,
            )
        )
    ok = all(step["ok"] for step in steps)
    payload = {
        "release_candidate": "PointsChain RC1.1 Operational Integrity",
        "generated_at": utc_now(),
        "ok": ok,
        "restore_drill": "pass" if next((s for s in steps if s["name"] == "isolated_restore_drill"), {}).get("ok") else ("skipped" if args.skip_drill else "fail"),
        "anchor_export": "covered_by_operational_tests",
        "scope_expansion": "blocked",
        "steps": steps,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": ok,
        "out": str(out),
        "restore_drill": payload["restore_drill"],
        "anchor_export": payload["anchor_export"],
    }, ensure_ascii=False, indent=2))
    print(f"RC1.1 OPERATIONAL GATE: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
