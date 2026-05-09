#!/usr/bin/env python3
"""Prepare filtered chess replay datasets for offline retraining.

This script reads the replay ledgers collected from user/computer matches,
filters them again in batch mode, then emits deterministic train/eval JSONL
files that can be fed into exp3 dataset training.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess_arena import default_chess_reports_dir  # noqa: E402
from services.games.chess_replay_buffer import (  # noqa: E402
    default_chess_replay_buffer_path,
    default_chess_replay_quarantine_path,
)
from services.games.chess import initial_board, validate_move  # noqa: E402


DEFAULT_DATASET_DIRNAME = "chess_datasets"


@dataclass
class PreparedSample:
    sample: dict
    bucket: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare filtered train/eval datasets from collected chess replay ledgers.")
    parser.add_argument("--trusted-replay-path", default="")
    parser.add_argument("--quarantine-replay-path", default="")
    parser.add_argument("--include-quarantine", action="store_true")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--train-path", default="")
    parser.add_argument("--eval-path", default="")
    parser.add_argument("--source-stage-label", default="final")
    parser.add_argument("--min-move-count", type=int, default=8)
    parser.add_argument("--eval-mod", type=int, default=5, help="Deterministic split: replay hash %% eval_mod == 0 goes to eval.")
    parser.add_argument("--include-losing-moves", action="store_true")
    parser.add_argument("--replace-output", action="store_true")
    return parser.parse_args()


def _default_dataset_dir() -> Path:
    return default_chess_reports_dir() / DEFAULT_DATASET_DIRNAME


def _iter_jsonl(path: Path):
    if not path.exists():
        return
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            payload["_source_path"] = str(path)
            payload["_source_line"] = line_no
            yield payload


def _split_bucket(replay_id: str, eval_mod: int) -> str:
    if max(1, int(eval_mod or 1)) == 1:
        return "eval"
    digest = hashlib.sha256(str(replay_id or "").encode("utf-8")).hexdigest()
    return "eval" if (int(digest[:8], 16) % max(1, int(eval_mod or 1)) == 0) else "train"


def _source_weight(record: dict, *, from_quarantine: bool) -> float:
    base = float(record.get("confidence_score") or 0.0)
    if from_quarantine:
        base *= 0.35
    if str(record.get("adjudicated_or_natural") or "") == "adjudicated":
        base *= 0.8
    if str(record.get("source") or "") in {"teacher_guidance", "benchmark"}:
        base *= 1.2
    return max(0.1, min(2.5, round(base, 4)))


def _move_target(move_side: str, winner_color: str | None, *, include_losing_moves: bool) -> float | None:
    if winner_color in {"white", "black"}:
        if move_side == winner_color:
            return 1.0
        return -0.2 if include_losing_moves else None
    return 0.15


def _prepared_samples_from_record(
    record: dict,
    *,
    include_losing_moves: bool,
    from_quarantine: bool,
    eval_mod: int,
    source_stage_label: str,
) -> list[PreparedSample]:
    if int(record.get("move_count") or 0) <= 0:
        return []
    opening_seed = str(record.get("opening_seed") or "").strip() or ""
    board = {"__fen__": opening_seed} if opening_seed and opening_seed != "standard_start" else initial_board()
    history = record.get("move_history") or []
    if not isinstance(history, list) or not history:
        return []
    bucket = _split_bucket(str(record.get("replay_id") or ""), int(eval_mod or 1))
    source_label = "user_games_quarantine" if from_quarantine else "user_games_trusted"
    samples: list[PreparedSample] = []
    for move_index, entry in enumerate(history, start=1):
        if not isinstance(entry, dict):
            continue
        move_side = str(entry.get("by") or "").strip().lower()
        from_square = str(entry.get("from") or "").strip().lower()
        to_square = str(entry.get("to") or "").strip().lower()
        promotion = entry.get("promotion")
        target = _move_target(move_side, record.get("winner_color"), include_losing_moves=include_losing_moves)
        try:
            validated = validate_move(board, move_side, from_square, to_square, promotion)
        except Exception:
            break
        if target is not None:
            uci = f"{from_square}{to_square}{promotion or ''}"
            sample = {
                "fen": str(board.get("__fen__") or ""),
                "move_uci": uci,
                "side": move_side,
                "target": target,
                "weight": _source_weight(record, from_quarantine=from_quarantine),
                "quality_weight": _source_weight(record, from_quarantine=from_quarantine),
                "source": source_label,
                "replay_id": str(record.get("replay_id") or ""),
                "source_game_id": int(record.get("match_id") or 0),
                "source_move_index": int(move_index),
                "source_stage": str(source_stage_label or "final"),
                "accepted_reason": "trusted_replay" if not from_quarantine else "quarantine_override",
            }
            samples.append(PreparedSample(sample=sample, bucket=bucket))
        board = validated["board"]
    return samples


def _write_jsonl(path: Path, rows: list[dict], *, append: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_report(summary: dict, report_dir: Path) -> dict:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = summary["generated_at"].replace(":", "").replace("-", "").replace("T", "_").replace("Z", "")
    json_path = report_dir / f"chess_replay_prepare_{stamp}.json"
    md_path = report_dir / f"chess_replay_prepare_{stamp}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# chess_replay_prepare",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- trusted_replays_seen: `{summary['trusted_replays_seen']}`",
        f"- quarantine_replays_seen: `{summary['quarantine_replays_seen']}`",
        f"- accepted_train_samples: `{summary['accepted_train_samples']}`",
        f"- accepted_eval_samples: `{summary['accepted_eval_samples']}`",
        f"- skipped_replays: `{summary['skipped_replays']}`",
        f"- train_path: `{summary['train_path']}`",
        f"- eval_path: `{summary['eval_path']}`",
        "",
        "## Reasons",
        "",
    ]
    for key, value in sorted((summary.get("skip_reasons") or {}).items()):
        lines.append(f"- {key}: `{value}`")
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"json_report": str(json_path), "md_report": str(md_path)}


args = parse_args()


def main() -> int:
    trusted_path = Path(args.trusted_replay_path).expanduser().resolve() if args.trusted_replay_path else default_chess_replay_buffer_path()
    quarantine_path = Path(args.quarantine_replay_path).expanduser().resolve() if args.quarantine_replay_path else default_chess_replay_quarantine_path()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else _default_dataset_dir()
    train_path = Path(args.train_path).expanduser().resolve() if args.train_path else output_dir / "train.jsonl"
    eval_path = Path(args.eval_path).expanduser().resolve() if args.eval_path else output_dir / "eval.jsonl"

    train_rows: list[dict] = []
    eval_rows: list[dict] = []
    skip_reasons: dict[str, int] = {}
    trusted_seen = 0
    quarantine_seen = 0

    def mark_skip(reason: str) -> None:
        skip_reasons[reason] = int(skip_reasons.get(reason) or 0) + 1

    for record in _iter_jsonl(trusted_path):
        trusted_seen += 1
        if int(record.get("move_count") or 0) < int(args.min_move_count or 0):
            mark_skip("trusted_too_short")
            continue
        prepared = _prepared_samples_from_record(
            record,
            include_losing_moves=bool(args.include_losing_moves),
            from_quarantine=False,
            eval_mod=int(args.eval_mod or 1),
            source_stage_label=str(args.source_stage_label or "final"),
        )
        if not prepared:
            mark_skip("trusted_no_samples")
            continue
        for row in prepared:
            if row.bucket == "eval":
                eval_rows.append(row.sample)
            else:
                train_rows.append(row.sample)

    if args.include_quarantine:
        for record in _iter_jsonl(quarantine_path):
            quarantine_seen += 1
            if int(record.get("move_count") or 0) < int(args.min_move_count or 0):
                mark_skip("quarantine_too_short")
                continue
            prepared = _prepared_samples_from_record(
                record,
                include_losing_moves=bool(args.include_losing_moves),
                from_quarantine=True,
                eval_mod=int(args.eval_mod or 1),
                source_stage_label=str(args.source_stage_label or "final"),
            )
            if not prepared:
                mark_skip("quarantine_no_samples")
                continue
            for row in prepared:
                if row.bucket == "eval":
                    eval_rows.append(row.sample)
                else:
                    train_rows.append(row.sample)

    if not eval_rows and len(train_rows) > 1:
        eval_rows.append(train_rows.pop())

    _write_jsonl(train_path, train_rows, append=not bool(args.replace_output))
    _write_jsonl(eval_path, eval_rows, append=not bool(args.replace_output))

    summary = {
        "ok": True,
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "trusted_replay_path": str(trusted_path),
        "quarantine_replay_path": str(quarantine_path),
        "include_quarantine": bool(args.include_quarantine),
        "source_stage_label": str(args.source_stage_label or "final"),
        "trusted_replays_seen": trusted_seen,
        "quarantine_replays_seen": quarantine_seen,
        "accepted_train_samples": len(train_rows),
        "accepted_eval_samples": len(eval_rows),
        "skipped_replays": sum(skip_reasons.values()),
        "skip_reasons": skip_reasons,
        "train_path": str(train_path),
        "eval_path": str(eval_path),
        "min_move_count": int(args.min_move_count or 0),
        "include_losing_moves": bool(args.include_losing_moves),
        "replace_output": bool(args.replace_output),
    }
    summary["reports"] = _write_report(summary, default_chess_reports_dir())
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
