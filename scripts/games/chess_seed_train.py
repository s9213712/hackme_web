#!/usr/bin/env python3
"""Offline seed trainer for directly usable chess experiment models.

This script is the pragmatic answer to the current engine state:

- exp3 / exp4 are weak when cold-started
- startup-time warm-up is too slow for production use

So this tool trains seed artifacts offline under ``runtime/`` (or explicit
paths), then prints a compact JSON summary with model paths you can install
directly.
"""

from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess_dl import bundled_chess_dl_model_path  # noqa: E402
from services.games.chess_engine import bundled_chess_engine_db_path  # noqa: E402
from services.games.chess_nn import bundled_chess_nn_model_path  # noqa: E402
from services.games.chess_nnue import bundled_chess_nnue_model_path  # noqa: E402
from services.games.chess_pv import bundled_chess_pv_model_path  # noqa: E402
from services.games.self_play_training import (  # noqa: E402
    DEFAULT_MAX_PLIES,
    DEFAULT_STUDENT_EXPLORATION_RATE,
    DEFAULT_TEACHER_DEPTH,
    ChessExperimentStore,
    default_training_report_dir,
    run_post_training_smoke_evaluation,
    run_round_robin_benchmark,
    run_training_session,
    write_training_report,
)
import services.games.chess_dl as chess_dl_service  # noqa: E402
import services.games.chess_pv as chess_pv_service  # noqa: E402


PRESETS = {
    "micro": {
        "exp2_teacher_games": 0,
        "exp3_teacher_games": 1,
        "exp4_teacher_games": 1,
        "hard_exp2_games": 0,
        "hard_exp3_games": 1,
        "hard_exp4_games": 1,
        "cross_games": 0,
        "cross_exp1_exp3_games": 0,
        "cross_exp2_exp3_games": 0,
        "cross_exp1_exp4_games": 0,
        "cross_exp2_exp4_games": 0,
        "cross_exp3_exp4_games": 1,
        "teacher_depth": 1,
        "max_plies": 12,
        "student_exploration_rate": 0.12,
    },
    "quick": {
        "exp2_teacher_games": 4,
        "exp3_teacher_games": 6,
        "exp4_teacher_games": 6,
        "hard_exp2_games": 2,
        "hard_exp3_games": 4,
        "hard_exp4_games": 4,
        "cross_games": 0,
        "cross_exp1_exp3_games": 3,
        "cross_exp2_exp3_games": 2,
        "cross_exp1_exp4_games": 3,
        "cross_exp2_exp4_games": 2,
        "cross_exp3_exp4_games": 3,
        "teacher_depth": 1,
        "max_plies": 18,
        "student_exploration_rate": 0.1,
    },
    "standard": {
        "exp2_teacher_games": 8,
        "exp3_teacher_games": 16,
        "exp4_teacher_games": 16,
        "hard_exp2_games": 4,
        "hard_exp3_games": 10,
        "hard_exp4_games": 10,
        "cross_games": 0,
        "cross_exp1_exp3_games": 8,
        "cross_exp2_exp3_games": 6,
        "cross_exp1_exp4_games": 8,
        "cross_exp2_exp4_games": 6,
        "cross_exp3_exp4_games": 8,
        "teacher_depth": 2,
        "max_plies": 28,
        "student_exploration_rate": 0.08,
    },
    "warmup10": {
        "exp2_teacher_games": 12,
        "exp3_teacher_games": 24,
        "exp4_teacher_games": 24,
        "hard_exp2_games": 6,
        "hard_exp3_games": 12,
        "hard_exp4_games": 12,
        "cross_games": 0,
        "cross_exp1_exp3_games": 10,
        "cross_exp2_exp3_games": 8,
        "cross_exp1_exp4_games": 10,
        "cross_exp2_exp4_games": 8,
        "cross_exp3_exp4_games": 10,
        "teacher_depth": 2,
        "max_plies": 24,
        "student_exploration_rate": 0.05,
    },
    "strong": {
        "exp2_teacher_games": 16,
        "exp3_teacher_games": 32,
        "exp4_teacher_games": 32,
        "hard_exp2_games": 8,
        "hard_exp3_games": 20,
        "hard_exp4_games": 20,
        "cross_games": 0,
        "cross_exp1_exp3_games": 14,
        "cross_exp2_exp3_games": 10,
        "cross_exp1_exp4_games": 14,
        "cross_exp2_exp4_games": 10,
        "cross_exp3_exp4_games": 14,
        "teacher_depth": 2,
        "max_plies": 36,
        "student_exploration_rate": 0.06,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline seed trainer for directly usable chess exp2/exp3/exp4 models.")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="standard")
    parser.add_argument("--include-exp2", action="store_true", help="Also train exp2 during seed generation.")
    parser.add_argument("--skip-exp3", action="store_true", help="Skip exp3 training.")
    parser.add_argument("--skip-exp4", action="store_true", help="Skip exp4 training.")
    parser.add_argument("--teacher-depth", type=int, default=-1)
    parser.add_argument("--max-plies", type=int, default=-1)
    parser.add_argument("--student-exploration-rate", type=float, default=-1.0)
    parser.add_argument("--seed", type=int, default=20260508)
    parser.add_argument("--dl-search-depth", type=int, default=1)
    parser.add_argument("--dl-quiescence-depth", type=int, default=1)
    parser.add_argument("--pv-search-depth", type=int, default=1)
    parser.add_argument("--pv-quiescence-depth", type=int, default=1)
    parser.add_argument("--with-smoke", action="store_true")
    parser.add_argument("--with-benchmark", action="store_true")
    parser.add_argument("--smoke-games-per-pair", type=int, default=1)
    parser.add_argument("--benchmark-rounds", type=int, default=1)
    parser.add_argument("--report-dir", default=str(default_training_report_dir()))
    parser.add_argument("--experiment-db-path", default="")
    parser.add_argument("--experiment-2-model-path", default="")
    parser.add_argument("--experiment-3-model-path", default="")
    parser.add_argument("--experiment-4-model-path", default="")
    parser.add_argument("--experiment-5-model-path", default="")
    return parser.parse_args()


def _model_stats(path: Path) -> dict:
    if not path.exists():
        return {"path": str(path), "exists": False, "sample_count": 0}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": str(path),
        "exists": True,
        "sample_count": int(payload.get("sample_count") or 0),
        "architecture": str(payload.get("architecture") or ""),
        "version": int(payload.get("version") or 0),
    }


@contextmanager
def _temporary_search_depths(args: argparse.Namespace):
    old_dl_depth = chess_dl_service._SEARCH_DEPTH
    old_dl_qdepth = chess_dl_service._SEARCH_QUIESCENCE_DEPTH
    old_pv_depth = chess_pv_service._SEARCH_DEPTH
    old_pv_qdepth = chess_pv_service._SEARCH_QUIESCENCE_DEPTH
    chess_dl_service._SEARCH_DEPTH = max(1, int(args.dl_search_depth or 1))
    chess_dl_service._SEARCH_QUIESCENCE_DEPTH = max(0, int(args.dl_quiescence_depth or 0))
    chess_pv_service._SEARCH_DEPTH = max(1, int(args.pv_search_depth or 1))
    chess_pv_service._SEARCH_QUIESCENCE_DEPTH = max(0, int(args.pv_quiescence_depth or 0))
    try:
        yield
    finally:
        chess_dl_service._SEARCH_DEPTH = old_dl_depth
        chess_dl_service._SEARCH_QUIESCENCE_DEPTH = old_dl_qdepth
        chess_pv_service._SEARCH_DEPTH = old_pv_depth
        chess_pv_service._SEARCH_QUIESCENCE_DEPTH = old_pv_qdepth


def _resolved_schedule(args: argparse.Namespace) -> dict:
    schedule = dict(PRESETS[args.preset])
    if int(args.teacher_depth) > 0:
        schedule["teacher_depth"] = int(args.teacher_depth)
    if int(args.max_plies) > 0:
        schedule["max_plies"] = int(args.max_plies)
    if float(args.student_exploration_rate) >= 0:
        schedule["student_exploration_rate"] = float(args.student_exploration_rate)
    if not args.include_exp2:
        schedule["exp2_teacher_games"] = 0
        schedule["hard_exp2_games"] = 0
        schedule["cross_exp2_exp3_games"] = 0
        schedule["cross_exp2_exp4_games"] = 0
    if args.skip_exp3:
        schedule["exp3_teacher_games"] = 0
        schedule["hard_exp3_games"] = 0
        schedule["cross_exp1_exp3_games"] = 0
        schedule["cross_exp2_exp3_games"] = 0
        schedule["cross_exp3_exp4_games"] = 0
    if args.skip_exp4:
        schedule["exp4_teacher_games"] = 0
        schedule["hard_exp4_games"] = 0
        schedule["cross_exp1_exp4_games"] = 0
        schedule["cross_exp2_exp4_games"] = 0
        schedule["cross_exp3_exp4_games"] = 0
    return schedule


def _progress_log(event: dict) -> None:
    phase = str(event.get("phase") or "")
    if phase == "training_started":
        sys.stderr.write(f"[chess-seed-train] training 0/{event.get('total', 0)}\n")
    elif phase == "training_match_completed":
        sys.stderr.write(
            "[chess-seed-train] "
            f"{event.get('completed', 0)}/{event.get('total', 0)} "
            f"{event.get('white_engine')} vs {event.get('black_engine')} "
            f"winner={event.get('winner_color') or 'draw'} "
            f"plies={event.get('plies', 0)} reason={event.get('reason')}\n"
        )
    elif phase == "training_finished":
        sys.stderr.write(
            f"[chess-seed-train] training finished {event.get('completed', 0)}/{event.get('total', 0)} "
            f"games={event.get('games_played', 0)}\n"
        )
    sys.stderr.flush()


def _progress(message: str) -> None:
    sys.stderr.write(f"[chess-seed-train] {message}\n")
    sys.stderr.flush()


def main() -> int:
    args = parse_args()
    schedule = _resolved_schedule(args)
    store = ChessExperimentStore(args.experiment_db_path or bundled_chess_engine_db_path())
    nn_model_path = Path(args.experiment_2_model_path or bundled_chess_nn_model_path())
    dl_model_path = Path(args.experiment_3_model_path or bundled_chess_dl_model_path())
    pv_model_path = Path(args.experiment_4_model_path or bundled_chess_pv_model_path())
    nnue_model_path = Path(args.experiment_5_model_path or bundled_chess_nnue_model_path())
    _progress(f"preset: {args.preset} seed={int(args.seed)}")
    _progress(f"target exp1 db: {Path(args.experiment_db_path or bundled_chess_engine_db_path())}")
    _progress(f"target exp2 model: {nn_model_path}")
    _progress(f"target exp3 model: {dl_model_path}")
    _progress(f"target exp4 model: {pv_model_path}")
    _progress(f"target exp5 model: {nnue_model_path}")
    _progress(f"report dir: {Path(args.report_dir)}")
    _progress("phase seed training started")

    with _temporary_search_depths(args):
        summary = run_training_session(
            exp1_teacher_games=0,
            exp2_teacher_games=int(schedule["exp2_teacher_games"]),
            exp3_teacher_games=int(schedule["exp3_teacher_games"]),
            exp4_teacher_games=int(schedule["exp4_teacher_games"]),
            hard_exp1_games=0,
            hard_exp2_games=int(schedule["hard_exp2_games"]),
            hard_exp3_games=int(schedule["hard_exp3_games"]),
            hard_exp4_games=int(schedule["hard_exp4_games"]),
            cross_games=int(schedule["cross_games"]),
            cross_exp1_exp3_games=int(schedule["cross_exp1_exp3_games"]),
            cross_exp2_exp3_games=int(schedule["cross_exp2_exp3_games"]),
            cross_exp1_exp4_games=int(schedule["cross_exp1_exp4_games"]),
            cross_exp2_exp4_games=int(schedule["cross_exp2_exp4_games"]),
            cross_exp3_exp4_games=int(schedule["cross_exp3_exp4_games"]),
            teacher_depth=int(schedule["teacher_depth"] or DEFAULT_TEACHER_DEPTH),
            max_plies=int(schedule["max_plies"] or DEFAULT_MAX_PLIES),
            student_exploration_rate=float(schedule["student_exploration_rate"] or DEFAULT_STUDENT_EXPLORATION_RATE),
            seed=int(args.seed),
            store=store,
            nn_model_path=nn_model_path,
            dl_model_path=dl_model_path,
            pv_model_path=pv_model_path,
            nnue_model_path=nnue_model_path,
            progress_hook=_progress_log,
        )
        if args.with_smoke:
            sys.stderr.write("[chess-seed-train] smoke evaluation started\n")
            sys.stderr.flush()
            summary["smoke_evaluation"] = run_post_training_smoke_evaluation(
                store=store,
                nn_model_path=nn_model_path,
                dl_model_path=dl_model_path,
                pv_model_path=pv_model_path,
                nnue_model_path=nnue_model_path,
                teacher_depth=int(schedule["teacher_depth"] or DEFAULT_TEACHER_DEPTH),
                max_plies=int(schedule["max_plies"] or DEFAULT_MAX_PLIES),
                games_per_pair=max(0, int(args.smoke_games_per_pair or 0)),
                seed=int(args.seed) + 101,
            )
            sys.stderr.write("[chess-seed-train] smoke evaluation finished\n")
            sys.stderr.flush()
        if args.with_benchmark:
            sys.stderr.write("[chess-seed-train] benchmark started\n")
            sys.stderr.flush()
            summary["benchmark"] = run_round_robin_benchmark(
                store=store,
                nn_model_path=nn_model_path,
                dl_model_path=dl_model_path,
                pv_model_path=pv_model_path,
                nnue_model_path=nnue_model_path,
                teacher_depth=int(schedule["teacher_depth"] or DEFAULT_TEACHER_DEPTH),
                max_plies=int(schedule["max_plies"] or DEFAULT_MAX_PLIES),
                rounds=max(0, int(args.benchmark_rounds or 0)),
                seed=int(args.seed) + 202,
            )
            sys.stderr.write("[chess-seed-train] benchmark finished\n")
            sys.stderr.flush()

    reports = write_training_report(summary, report_dir=Path(args.report_dir), basename="chess_seed_train")
    _progress(f"phase result report: json={reports.get('json_report')} md={reports.get('md_report')}")
    payload = {
        "ok": True,
        "preset": args.preset,
        "seed": int(args.seed),
        "experiment_db_path": str(Path(args.experiment_db_path or bundled_chess_engine_db_path())),
        "games_played": int(summary.get("games_played") or 0),
        "teacher_depth": int(summary.get("teacher_depth") or 0),
        "max_plies": int(summary.get("max_plies") or 0),
        "student_exploration_rate": float(summary.get("student_exploration_rate") or 0.0),
        "schedule": summary.get("requested_games") or {},
        "updates": summary.get("updates") or {},
        "reports": reports,
        "models": {
            "exp2": _model_stats(nn_model_path),
            "exp3": _model_stats(dl_model_path),
            "exp4": _model_stats(pv_model_path),
            "exp5": _model_stats(nnue_model_path),
        },
        "with_smoke": bool(args.with_smoke),
        "with_benchmark": bool(args.with_benchmark),
        "search_depth_overrides": {
            "exp3_depth": max(1, int(args.dl_search_depth or 1)),
            "exp3_qdepth": max(0, int(args.dl_quiescence_depth or 0)),
            "exp4_depth": max(1, int(args.pv_search_depth or 1)),
            "exp4_qdepth": max(0, int(args.pv_quiescence_depth or 0)),
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    _progress("phase result seed training: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _progress(f"FAIL: {exc}")
        _progress("failure hint: check model target paths, report dir permissions, and lower --preset for a smaller repro")
        raise
