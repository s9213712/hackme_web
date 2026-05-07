#!/usr/bin/env python3
"""Train the two experimental chess learners through automated play.

The script uses three match sources:

- teacher vs experiment
- teacher vs experiment 2:nn
- experiment vs experiment 2:nn

All generated artifacts stay under ``runtime/``:

- exp1 memory DB: ``runtime/database/chess_experiment.db``
- exp2 model: ``runtime/models/chess_experiment_2_nn.json``
- training reports: ``runtime/reports/games/``
"""

from __future__ import annotations

import argparse
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
    default_chess_nn_model_path,
    default_training_report_dir,
    run_training_session,
    write_training_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auto-play trainer for chess experiment / experiment 2:nn."
    )
    parser.add_argument("--exp1-games", type=int, default=12, help="Teacher vs experiment games.")
    parser.add_argument("--exp2-games", type=int, default=12, help="Teacher vs experiment 2:nn games.")
    parser.add_argument("--cross-games", type=int, default=6, help="experiment vs experiment 2:nn games.")
    parser.add_argument("--teacher-depth", type=int, default=DEFAULT_TEACHER_DEPTH, help="Teacher alpha-beta depth.")
    parser.add_argument("--max-plies", type=int, default=DEFAULT_MAX_PLIES, help="Max plies per match before adjudication.")
    parser.add_argument(
        "--student-exploration-rate",
        type=float,
        default=DEFAULT_STUDENT_EXPLORATION_RATE,
        help="Random move chance for student engines during training.",
    )
    parser.add_argument("--seed", type=int, default=20260507)
    parser.add_argument("--report-dir", default=str(default_training_report_dir()))
    parser.add_argument("--experiment-db-path", default="")
    parser.add_argument("--experiment-2-model-path", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runtime_dir = os.environ.get("HACKME_RUNTIME_DIR", "").strip()
    if runtime_dir:
        Path(runtime_dir).mkdir(parents=True, exist_ok=True)

    store = ChessExperimentStore(args.experiment_db_path or None)
    nn_model_path = Path(args.experiment_2_model_path or default_chess_nn_model_path())
    summary = run_training_session(
        exp1_teacher_games=args.exp1_games,
        exp2_teacher_games=args.exp2_games,
        cross_games=args.cross_games,
        teacher_depth=args.teacher_depth,
        max_plies=args.max_plies,
        student_exploration_rate=args.student_exploration_rate,
        seed=args.seed,
        store=store,
        nn_model_path=nn_model_path,
    )
    reports = write_training_report(summary, report_dir=Path(args.report_dir))
    summary["reports"] = reports
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
