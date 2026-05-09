#!/usr/bin/env python3
"""Train exp1 from replay-derived datasets.

Accepted JSONL row format:

{"fen":"...", "move_uci":"e2e4", "side":"white", "target":1.0, "weight":1.0}
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess_engine import (  # noqa: E402
    default_chess_engine_db_path,
    train_experiment_from_replay_samples,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train exp1 from replay-derived fen+move datasets.")
    parser.add_argument("--input-jsonl", action="append", default=[], help="JSONL rows containing fen+move samples.")
    parser.add_argument("--db-path", default="")
    parser.add_argument("--max-samples", type=int, default=0, help="Optional cap after all rows are loaded.")
    return parser.parse_args()


def _progress(message: str) -> None:
    print(f"[chess-exp1-train] {message}", file=sys.stderr, flush=True)


def _iter_jsonl(path: Path):
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_no}: row must be an object")
        yield payload


def main() -> int:
    args = parse_args()
    input_paths = [Path(item).expanduser().resolve() for item in args.input_jsonl]
    db_path = Path(args.db_path).expanduser().resolve() if args.db_path else default_chess_engine_db_path()
    _progress(f"target db: {db_path}")
    _progress(f"input files: {len(input_paths)}")
    samples: list[dict] = []
    for input_path in input_paths:
        _progress(f"phase read input: {input_path}")
        before = len(samples)
        samples.extend(_iter_jsonl(input_path))
        _progress(f"phase result read input: {len(samples) - before} rows")
    if args.max_samples and int(args.max_samples) > 0:
        samples = samples[: int(args.max_samples)]
        _progress(f"phase cap samples: {len(samples)} rows")
    _progress(f"phase train started: {len(samples)} rows")
    result = train_experiment_from_replay_samples(
        samples,
        db_path=db_path,
    )
    result["input_rows"] = len(samples)
    _progress(f"phase result train: ok artifact={db_path}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _progress(f"FAIL: {exc}")
        _progress("failure hint: check input JSONL line numbers above and the target db path permissions")
        raise
