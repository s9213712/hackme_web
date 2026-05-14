#!/usr/bin/env python3
"""Larger tactical/behavioral suite for chess ``experiment 5:nnue``.

This wraps the holdout probe with a larger default target and records enough
metadata to make anti-overfitting checks reproducible.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.games.chess_exp5_holdout_probe import (  # noqa: E402
    EXP5,
    evaluate_case,
    holdout_cases,
    summarize,
)


DEFAULT_REPLAY = ROOT / "docs" / "games" / "2026-05-13_exp5_download_script_probe_replay.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a larger exp5 tactical suite.")
    parser.add_argument("--search-profile", default="balanced")
    parser.add_argument("--target-cases", type=int, default=300)
    parser.add_argument("--pgn-replay-jsonl", default=str(DEFAULT_REPLAY))
    parser.add_argument("--pgn-case-count", type=int, default=240)
    parser.add_argument("--no-mirrors", action="store_true")
    parser.add_argument("--output", default=str(ROOT / "docs" / "games" / "2026-05-13_exp5_tactical_suite.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pgn_path = Path(args.pgn_replay_jsonl).expanduser().resolve() if args.pgn_replay_jsonl else None
    cases = holdout_cases(
        include_mirrors=not bool(args.no_mirrors),
        target_cases=max(1, int(args.target_cases)),
        pgn_replay_jsonl=pgn_path,
        pgn_case_count=max(0, int(args.pgn_case_count)),
    )
    rows = [evaluate_case(case, search_profile=str(args.search_profile or "balanced")) for case in cases]
    summary = summarize(rows)
    artifact = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "engine": EXP5,
        "suite": "exp5_large_tactical_behavioral_suite_v1",
        "method": {
            "search_profile": str(args.search_profile or "balanced"),
            "target_cases": max(1, int(args.target_cases)),
            "actual_cases": len(cases),
            "include_mirrors": not bool(args.no_mirrors),
            "pgn_replay_jsonl": str(pgn_path) if pgn_path else "",
            "pgn_case_count_requested": max(0, int(args.pgn_case_count)),
        },
        "summary": summary,
        "cases": rows,
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
