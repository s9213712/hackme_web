"""Aggregated dashboard helpers for chess engine operations."""

from __future__ import annotations

from pathlib import Path

from services.games.chess_arena import (
    default_chess_reports_dir,
    latest_benchmark_report,
    latest_pipeline_report,
    latest_replay_prepare_report,
    latest_seed_training_report,
    latest_training_report,
)
from services.games.chess_pipeline import pipeline_recommendation
from services.games.chess_promotion import ensure_warm_start_chess_environment, production_engine_inventory, promotion_status_summary
from services.games.chess_replay_buffer import replay_buffer_summary


def _pipeline_defaults() -> dict:
    reports_dir = default_chess_reports_dir()
    dataset_dir = reports_dir / "chess_datasets"
    train_path = dataset_dir / "train.jsonl"
    eval_path = dataset_dir / "eval.jsonl"
    return {
        "dataset_dir": str(dataset_dir),
        "train_path": str(train_path),
        "eval_path": str(eval_path),
        "commands": {
            "prepare": f"python3 scripts/games/chess_replay_prepare.py --replace-output --include-quarantine --output-dir {dataset_dir}",
            "seed_train": "python3 scripts/games/chess_seed_train.py --preset standard",
            "exp3_refine": f"python3 scripts/games/chess_exp3_dataset_train.py --input-jsonl {train_path}",
            "benchmark": "python3 scripts/games/chess_self_play_train.py --exp1-games 0 --exp2-games 0 --exp3-games 0 --exp4-games 0 --hard-exp1-games 0 --hard-exp2-games 0 --hard-exp3-games 0 --hard-exp4-games 0 --cross-games 0 --cross-exp1-exp3-games 0 --cross-exp2-exp3-games 0 --cross-exp1-exp4-games 0 --cross-exp2-exp4-games 0 --cross-exp3-exp4-games 0 --benchmark-rounds 1 --smoke-games-per-pair 1",
            "full_pipeline": "python3 scripts/games/chess_train_pipeline.py --preset standard --include-quarantine",
        },
    }


def build_chess_engine_dashboard() -> dict:
    warm_start = ensure_warm_start_chess_environment()
    replay = replay_buffer_summary()
    benchmark = latest_benchmark_report()
    training = latest_training_report()
    prepare = latest_replay_prepare_report()
    seed_training = latest_seed_training_report()
    pipeline_report = latest_pipeline_report()
    promotion = promotion_status_summary()
    recommendation = pipeline_recommendation(replay=replay, pipeline_report=pipeline_report, seed_report=seed_training)
    return {
        "ok": True,
        "warm_start": warm_start,
        "production_models": production_engine_inventory(),
        "replay_buffer": replay,
        "pipeline": _pipeline_defaults(),
        "pipeline_recommendation": recommendation,
        "latest_pipeline_report": pipeline_report,
        "latest_replay_prepare": prepare,
        "latest_seed_training_report": seed_training,
        "latest_training_report": training,
        "latest_benchmark": benchmark,
        "promotion": promotion,
    }
