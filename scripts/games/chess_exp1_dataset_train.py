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
    samples: list[dict] = []
    for input_path in args.input_jsonl:
        samples.extend(_iter_jsonl(Path(input_path).expanduser().resolve()))
    if args.max_samples and int(args.max_samples) > 0:
        samples = samples[: int(args.max_samples)]
    result = train_experiment_from_replay_samples(
        samples,
        db_path=Path(args.db_path).expanduser().resolve() if args.db_path else default_chess_engine_db_path(),
    )
    result["input_rows"] = len(samples)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
