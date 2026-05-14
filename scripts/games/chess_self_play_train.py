#!/usr/bin/env python3
"""Train the chess practice engines through automated play.

The script uses these match sources:

- teacher vs experiment
- teacher vs experiment 2:nn
- teacher vs experiment 3:dl
- teacher vs experiment 4:pv
- hard vs experiment
- hard vs experiment 2:nn
- hard vs experiment 3:dl
- hard vs experiment 4:pv
- experiment vs experiment 2:nn
- experiment vs experiment 3:dl
- experiment 2:nn vs experiment 3:dl
- experiment vs experiment 4:pv
- experiment 2:nn vs experiment 4:pv
- experiment 3:dl vs experiment 4:pv

All generated artifacts stay under ``runtime/``:

- exp1 memory DB: ``runtime/games/models/chess_experiment.db``
- exp2 model: ``runtime/games/models/chess_experiment_2_nn.json``
- exp3 model: ``runtime/games/models/chess_experiment_3_dl.json``
- exp4 model: ``runtime/games/models/chess_experiment_4_pv.json``
- exp5 model: ``runtime/games/models/chess_experiment_5_nnue.json``
- training reports: ``runtime/reports/games/``
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.self_play_training import (  # noqa: E402
    DEFAULT_MAX_PLIES,
    DEFAULT_STUDENT_EXPLORATION_RATE,
    DEFAULT_TEACHER_DEPTH,
    ChessExperimentStore,
    default_chess_dl_model_path,
    default_chess_nn_model_path,
    default_chess_nnue_model_path,
    default_chess_pv_model_path,
    default_training_report_dir,
    run_post_training_smoke_evaluation,
    run_round_robin_benchmark,
    run_training_session,
    write_training_report,
)
import services.games.chess_dl as chess_dl_service  # noqa: E402
import services.games.chess_pv as chess_pv_service  # noqa: E402


def _progress_log(event: dict) -> None:
    phase = str(event.get("phase") or "")
    if phase == "training_started":
        sys.stderr.write(f"[chess-self-play] training 0/{event.get('total', 0)}\n")
    elif phase == "training_match_completed":
        sys.stderr.write(
            "[chess-self-play] "
            f"{event.get('completed', 0)}/{event.get('total', 0)} "
            f"{event.get('white_engine')} vs {event.get('black_engine')} "
            f"winner={event.get('winner_color') or 'draw'} "
            f"plies={event.get('plies', 0)} reason={event.get('reason')}\n"
        )
    elif phase == "training_finished":
        sys.stderr.write(
            f"[chess-self-play] training finished {event.get('completed', 0)}/{event.get('total', 0)} "
            f"games={event.get('games_played', 0)}\n"
        )
    sys.stderr.flush()


def _progress(message: str) -> None:
    sys.stderr.write(f"[chess-self-play] {message}\n")
    sys.stderr.flush()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auto-play trainer for chess experiment / experiment 2:nn."
    )
    parser.add_argument("--exp1-games", type=int, default=12, help="Teacher vs experiment games.")
    parser.add_argument("--exp2-games", type=int, default=12, help="Teacher vs experiment 2:nn games.")
    parser.add_argument("--exp3-games", type=int, default=12, help="Teacher vs experiment 3:dl games.")
    parser.add_argument("--exp4-games", type=int, default=12, help="Teacher vs experiment 4:pv games.")
    parser.add_argument("--hard-exp1-games", type=int, default=8, help="Hard vs experiment games.")
    parser.add_argument("--hard-exp2-games", type=int, default=8, help="Hard vs experiment 2:nn games.")
    parser.add_argument("--hard-exp3-games", type=int, default=8, help="Hard vs experiment 3:dl games.")
    parser.add_argument("--hard-exp4-games", type=int, default=8, help="Hard vs experiment 4:pv games.")
    parser.add_argument("--cross-games", type=int, default=6, help="experiment vs experiment 2:nn games.")
    parser.add_argument("--cross-exp1-exp3-games", type=int, default=6, help="experiment vs experiment 3:dl games.")
    parser.add_argument("--cross-exp2-exp3-games", type=int, default=6, help="experiment 2:nn vs experiment 3:dl games.")
    parser.add_argument("--cross-exp1-exp4-games", type=int, default=6, help="experiment vs experiment 4:pv games.")
    parser.add_argument("--cross-exp2-exp4-games", type=int, default=6, help="experiment 2:nn vs experiment 4:pv games.")
    parser.add_argument("--cross-exp3-exp4-games", type=int, default=6, help="experiment 3:dl vs experiment 4:pv games.")
    parser.add_argument("--teacher-depth", type=int, default=DEFAULT_TEACHER_DEPTH, help="Teacher alpha-beta depth.")
    parser.add_argument("--max-plies", type=int, default=DEFAULT_MAX_PLIES, help="Max plies per match before adjudication.")
    parser.add_argument("--smoke-games-per-pair", type=int, default=1, help="Post-training smoke games per target/reference pairing.")
    parser.add_argument("--benchmark-rounds", type=int, default=2, help="Round-robin rounds per unordered engine pair (each round includes both colors).")
    parser.add_argument(
        "--student-exploration-rate",
        type=float,
        default=DEFAULT_STUDENT_EXPLORATION_RATE,
        help="Random move chance for student engines during training.",
    )
    parser.add_argument("--seed", type=int, default=20260507)
    parser.add_argument("--dl-search-depth", type=int, default=-1)
    parser.add_argument("--dl-quiescence-depth", type=int, default=-1)
    parser.add_argument("--pv-search-depth", type=int, default=-1)
    parser.add_argument("--pv-quiescence-depth", type=int, default=-1)
    parser.add_argument("--report-dir", default=str(default_training_report_dir()))
    parser.add_argument("--experiment-db-path", default="")
    parser.add_argument("--experiment-2-model-path", default="")
    parser.add_argument("--experiment-3-model-path", default="")
    parser.add_argument("--experiment-4-model-path", default="")
    parser.add_argument("--experiment-5-model-path", default="")
    return parser.parse_args()


@contextmanager
def _temporary_search_depths(args: argparse.Namespace):
    old_dl_depth = chess_dl_service._SEARCH_DEPTH
    old_dl_qdepth = chess_dl_service._SEARCH_QUIESCENCE_DEPTH
    old_pv_depth = chess_pv_service._SEARCH_DEPTH
    old_pv_qdepth = chess_pv_service._SEARCH_QUIESCENCE_DEPTH
    if int(args.dl_search_depth) > 0:
        chess_dl_service._SEARCH_DEPTH = int(args.dl_search_depth)
    if int(args.dl_quiescence_depth) >= 0:
        chess_dl_service._SEARCH_QUIESCENCE_DEPTH = int(args.dl_quiescence_depth)
    if int(args.pv_search_depth) > 0:
        chess_pv_service._SEARCH_DEPTH = int(args.pv_search_depth)
    if int(args.pv_quiescence_depth) >= 0:
        chess_pv_service._SEARCH_QUIESCENCE_DEPTH = int(args.pv_quiescence_depth)
    try:
        yield
    finally:
        chess_dl_service._SEARCH_DEPTH = old_dl_depth
        chess_dl_service._SEARCH_QUIESCENCE_DEPTH = old_dl_qdepth
        chess_pv_service._SEARCH_DEPTH = old_pv_depth
        chess_pv_service._SEARCH_QUIESCENCE_DEPTH = old_pv_qdepth


def main() -> int:
    args = parse_args()
    runtime_dir = os.environ.get("HACKME_RUNTIME_DIR", "").strip()
    if runtime_dir:
        Path(runtime_dir).mkdir(parents=True, exist_ok=True)

    store = ChessExperimentStore(args.experiment_db_path or None)
    nn_model_path = Path(args.experiment_2_model_path or default_chess_nn_model_path())
    dl_model_path = Path(args.experiment_3_model_path or default_chess_dl_model_path())
    pv_model_path = Path(args.experiment_4_model_path or default_chess_pv_model_path())
    nnue_model_path = Path(args.experiment_5_model_path or default_chess_nnue_model_path())
    _progress(f"runtime dir: {runtime_dir or '<default runtime>'}")
    _progress(f"target exp1 db: {Path(args.experiment_db_path) if args.experiment_db_path else '<default>'}")
    _progress(f"target exp2 model: {nn_model_path}")
    _progress(f"target exp3 model: {dl_model_path}")
    _progress(f"target exp4 model: {pv_model_path}")
    _progress(f"target exp5 model: {nnue_model_path}")
    _progress(f"report dir: {Path(args.report_dir)}")
    _progress("phase self-play training started")
    with _temporary_search_depths(args):
        summary = run_training_session(
            exp1_teacher_games=args.exp1_games,
            exp2_teacher_games=args.exp2_games,
            exp3_teacher_games=args.exp3_games,
            exp4_teacher_games=args.exp4_games,
            hard_exp1_games=args.hard_exp1_games,
            hard_exp2_games=args.hard_exp2_games,
            hard_exp3_games=args.hard_exp3_games,
            hard_exp4_games=args.hard_exp4_games,
            cross_games=args.cross_games,
            cross_exp1_exp3_games=args.cross_exp1_exp3_games,
            cross_exp2_exp3_games=args.cross_exp2_exp3_games,
            cross_exp1_exp4_games=args.cross_exp1_exp4_games,
            cross_exp2_exp4_games=args.cross_exp2_exp4_games,
            cross_exp3_exp4_games=args.cross_exp3_exp4_games,
            teacher_depth=args.teacher_depth,
            max_plies=args.max_plies,
            student_exploration_rate=args.student_exploration_rate,
            seed=args.seed,
            store=store,
            nn_model_path=nn_model_path,
            dl_model_path=dl_model_path,
            pv_model_path=pv_model_path,
            nnue_model_path=nnue_model_path,
            progress_hook=_progress_log,
        )
        sys.stderr.write("[chess-self-play] smoke evaluation started\n")
        sys.stderr.flush()
        summary["smoke_evaluation"] = run_post_training_smoke_evaluation(
            store=store,
            nn_model_path=nn_model_path,
            dl_model_path=dl_model_path,
            pv_model_path=pv_model_path,
            nnue_model_path=nnue_model_path,
            teacher_depth=args.teacher_depth,
            max_plies=args.max_plies,
            games_per_pair=args.smoke_games_per_pair,
            seed=args.seed + 101,
        )
        sys.stderr.write("[chess-self-play] smoke evaluation finished\n")
        sys.stderr.flush()
        sys.stderr.write("[chess-self-play] benchmark started\n")
        sys.stderr.flush()
        summary["benchmark"] = run_round_robin_benchmark(
            store=store,
            nn_model_path=nn_model_path,
            dl_model_path=dl_model_path,
            pv_model_path=pv_model_path,
            nnue_model_path=nnue_model_path,
            teacher_depth=args.teacher_depth,
            max_plies=args.max_plies,
            rounds=args.benchmark_rounds,
            seed=args.seed + 202,
        )
        sys.stderr.write("[chess-self-play] benchmark finished\n")
        sys.stderr.flush()
    reports = write_training_report(summary, report_dir=Path(args.report_dir))
    summary["reports"] = reports
    _progress(f"phase result report: json={reports.get('json_report')} md={reports.get('md_report')}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    _progress("phase result self-play training: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _progress(f"FAIL: {exc}")
        _progress("failure hint: check runtime/model/report paths and reduce game counts for a focused repro")
        raise
