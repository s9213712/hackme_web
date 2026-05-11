#!/usr/bin/env python3
"""Train experiment 5:nnue from replay-derived position/move datasets.

Accepted JSONL row format:

    {"fen":"...", "move_uci":"e2e4", "side":"white", "target":1.0, "weight":1.0}

This is the exp5-specific minimal trainer. It mutates only the NNUE-like exp5
JSON model and replay file. Strength validation and promotion gates remain
separate pending design because exp5 is not compatible with exp3/exp4 semantic
replay assumptions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess_nnue import (  # noqa: E402
    default_chess_nnue_model_path,
    default_chess_nnue_replay_path,
    train_experiment_nnue_from_replay_samples,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train exp5 NNUE-like evaluator from replay-derived datasets.")
    parser.add_argument("--input-jsonl", action="append", default=[], help="JSONL rows containing fen+move samples.")
    parser.add_argument("--model-path", default="")
    parser.add_argument("--replay-path", default="")
    parser.add_argument("--replace-replay", action="store_true")
    parser.add_argument("--max-samples", type=int, default=0, help="Optional cap after all rows are expanded.")
    return parser.parse_args()


def _progress(message: str) -> None:
    print(f"[chess-exp5-train] {message}", file=sys.stderr, flush=True)


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
    model_path = Path(args.model_path).expanduser().resolve() if args.model_path else default_chess_nnue_model_path()
    replay_path = Path(args.replay_path).expanduser().resolve() if args.replay_path else default_chess_nnue_replay_path()
    _progress(f"target model: {model_path}")
    _progress(f"target replay: {replay_path}")
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
    result = train_experiment_nnue_from_replay_samples(
        samples,
        model_path=model_path,
        replay_path=replay_path,
        replace_replay=bool(args.replace_replay),
    )
    result["input_rows"] = len(samples)
    result["strength_validation_supported"] = False
    result["promotion_gate_supported"] = False
    result["next_design_required"] = "exp5-specific deterministic strength evaluator and promotion gate"
    _progress(f"phase result train: ok artifact={model_path} replay={replay_path}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _progress(f"FAIL: {exc}")
        _progress("failure hint: check input JSONL schema and target model/replay path permissions")
        raise
