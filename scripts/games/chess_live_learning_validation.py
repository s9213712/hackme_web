#!/usr/bin/env python3
"""Validate replay classification and auto-retraining for chess exp1-exp4."""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import shutil
import subprocess
import sys
import time

import chess


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes.games import choose_computer_move  # noqa: E402
from services.games.chess import game_status, initial_board, legal_moves, opponent, validate_move  # noqa: E402
from services.games.chess_arena import latest_pipeline_report  # noqa: E402
from services.games.chess_dl import (  # noqa: E402
    EXPERIMENT_DL_DIFFICULTY,
    choose_experiment_dl_move,
    explain_experiment_dl_decision,
    rank_experiment_dl_policy_moves,
    train_experiment_dl_from_replay_samples,
)
from services.games.chess_engine import ChessExperimentStore, EXPERIMENT_DIFFICULTY, record_experiment_learning  # noqa: E402
from services.games.chess_pipeline import latest_pipeline_autorun_status, maybe_launch_chess_train_pipeline  # noqa: E402
from services.games.chess_promotion import ensure_warm_start_chess_environment, production_engine_inventory  # noqa: E402
from services.games.chess_pv import (  # noqa: E402
    EXPERIMENT_PV_DIFFICULTY,
    choose_experiment_pv_move,
    explain_experiment_pv_decision,
    rank_experiment_pv_policy_moves,
    train_experiment_pv_from_replay_samples,
)
from services.games.chess_nnue import (  # noqa: E402
    EXPERIMENT_NNUE_DIFFICULTY,
    choose_experiment_nnue_move,
    explain_experiment_nnue_decision,
    rank_experiment_nnue_policy_moves,
)
from services.games.chess_replay_buffer import (  # noqa: E402
    build_replay_record,
    classify_replay_record,
    collect_match_replay,
    default_chess_replay_buffer_path,
    default_chess_replay_quarantine_path,
    default_chess_replay_rejected_path,
    replay_buffer_summary,
)
from services.games.self_play_training import run_round_robin_benchmark  # noqa: E402


ENGINE_MATRIX = [
    ("exp1", EXPERIMENT_DIFFICULTY),
    ("exp3", EXPERIMENT_DL_DIFFICULTY),
    ("exp4", EXPERIMENT_PV_DIFFICULTY),
    ("exp5", EXPERIMENT_NNUE_DIFFICULTY),
]
INVALID_GAMES = 5
BASE_VALID_GAMES = 20
EXTRA_VALID_GAMES = 5
TOTAL_GAMES = BASE_VALID_GAMES + EXTRA_VALID_GAMES + INVALID_GAMES
VALID_GAMES = TOTAL_GAMES - INVALID_GAMES
MAX_PLIES = 180
AUTORUN_THRESHOLD = 10
MIN_VALID_PLIES = 16
RETRAIN_ENGINE_ALIASES = {"exp3", "exp4"}
DATASET_DUPLICATE_RATIO_LIMIT = 0.25
DATASET_SHORT_RESIGN_LIMIT = 0
POISON_REPETITION_LIMIT = 0
POISON_INTENTIONAL_BLUNDER_LIMIT = 0
POISON_ENGINE_COPY_LIMIT = 0
POISON_SUSPICIOUS_RESIGN_RATE_LIMIT = 0.10
HUMAN_PROBE_OPENINGS = (
    {
        "label": "white_scholars_mate_probe",
        "human_side": "white",
        "moves": ["e2e4", "d1h5", "f1c4", "h5f7"],
    },
    {
        "label": "white_italian_pressure",
        "human_side": "white",
        "moves": ["e2e4", "g1f3", "f1c4", "d2d4"],
    },
    {
        "label": "white_queens_gambit_probe",
        "human_side": "white",
        "moves": ["d2d4", "c2c4", "b1c3", "c1g5"],
    },
    {
        "label": "white_fried_liver_probe",
        "human_side": "white",
        "moves": ["e2e4", "g1f3", "f1c4", "f3g5"],
    },
    {
        "label": "white_london_pressure",
        "human_side": "white",
        "moves": ["d2d4", "g1f3", "c1f4", "e2e3"],
    },
    {
        "label": "white_english_probe",
        "human_side": "white",
        "moves": ["c2c4", "g2g3", "f1g2", "b1c3"],
    },
    {
        "label": "black_scholars_counterprobe",
        "human_side": "black",
        "moves": ["e7e5", "d8h4", "f8c5", "h4f2"],
    },
    {
        "label": "black_sicilian_counterplay",
        "human_side": "black",
        "moves": ["c7c5", "d7d6", "b8c6", "g7g6"],
    },
    {
        "label": "black_scandinavian_probe",
        "human_side": "black",
        "moves": ["d7d5", "d8d5", "b8c6", "c8g4"],
    },
    {
        "label": "black_french_counterprobe",
        "human_side": "black",
        "moves": ["e7e6", "d7d5", "g8f6", "f8b4"],
    },
    {
        "label": "black_caro_kann_probe",
        "human_side": "black",
        "moves": ["c7c6", "d7d5", "c8f5", "e7e6"],
    },
    {
        "label": "black_pirc_probe",
        "human_side": "black",
        "moves": ["d7d6", "g8f6", "g7g6", "f8g7"],
    },
)
FIXED_PROBE_POSITIONS = (
    {
        "id": "mate_in_one_white",
        "fen": "6k1/5Q2/6K1/8/8/8/8/8 w - - 0 1",
        "side": "white",
    },
    {
        "id": "forced_capture_black",
        "fen": "4k3/4Q3/8/8/8/8/8/4K3 b - - 0 1",
        "side": "black",
    },
    {
        "id": "fork_threat_black",
        "fen": "4k3/8/8/8/4K3/3n4/8/7R b - - 0 1",
        "side": "black",
    },
    {
        "id": "queen_hanging_white",
        "fen": "4k3/8/8/8/8/8/4r3/4KQ2 w - - 0 1",
        "side": "white",
    },
    {
        "id": "mate_in_one_black",
        "fen": "8/8/8/8/8/6k1/5q2/6K1 b - - 0 1",
        "side": "black",
    },
    {
        "id": "promotion_white",
        "fen": "k7/4P3/2K5/8/8/8/8/8 w - - 0 1",
        "side": "white",
    },
    {
        "id": "avoid_stalemate_white",
        "fen": "k7/3Q4/2K5/8/8/8/8/8 w - - 0 1",
        "side": "white",
    },
    {
        "id": "free_queen_white",
        "fen": "4k3/8/8/8/8/8/4q3/4KQ2 w - - 0 1",
        "side": "white",
    },
)
DETERMINISTIC_STRENGTH_DEPTH = 1
DETERMINISTIC_STRENGTH_MAX_NODES = 0
DETERMINISTIC_STRENGTH_TIME_LIMIT_MS = 0
DETERMINISTIC_MIN_BLUNDER_AVOID_RATE = 1.0
DETERMINISTIC_CHECKPOINT20_DROP_LIMIT = 0.05
LATE_STAGE_COLLAPSE_MIN_GAMES = 5
LATE_STAGE_COLLAPSE_WIN_RATE = 0.0
QUICK_RETRAIN_GATE_TRUSTED_REPLAYS = 20
QUICK_RETRAIN_GATE_CHECKPOINTS = (10, 20)
QUICK_RETRAIN_MAX_SAMPLES = 256
QUICK_RETRAIN_MAX_SECONDS = 60
QUICK_RETRAIN_EVAL_SAMPLE_LIMIT = 8
QUICK_RETRAIN_MIN_CASES_PER_CATEGORY = 3
SANITY_LEARNING_VARIANT_COUNT = 6
SANITY_SEEN_VARIANT_PASS_THRESHOLD = 0.8
SANITY_UNSEEN_VARIANT_PASS_THRESHOLD = 0.5
SANITY_FINAL_DECISION_GENERALIZATION_THRESHOLD = 0.5
SANITY_LABEL_QUESTIONABLE_CP_DELTA = -150
SANITY_LABEL_HARD_EXCLUDE_CP_DELTA = -300
SANITY_CLEAN_HELD_OUT_MIN_PER_DIFFICULTY = 10
SANITY_EASY_TRAIN_VARIANT_COUNT = 6
SANITY_MEDIUM_TRAIN_VARIANT_COUNT = 6
SANITY_HARD_TRAIN_VARIANT_COUNT = 3
SANITY_EARLY_HARD_TRAIN_VARIANT_COUNT = 6
SANITY_EARLY_HARD_HELD_OUT_VARIANT_COUNT = 3
SANITY_EASY_VALIDATION_VARIANT_COUNT = 3
SANITY_MEDIUM_VALIDATION_VARIANT_COUNT = 3
SANITY_HARD_VARIANT_COUNT = 6
SANITY_HELD_OUT_POOL_CANDIDATES_PER_DIFFICULTY = 40
SEMANTIC_CLASSES = (
    "e_pawn_central_break",
    "d_pawn_central_break",
    "flank_pawn_push",
    "kingside_aggression",
    "development_move",
    "other",
)
SEMANTIC_BALANCE_CLASSES = (
    "e_pawn_central_break",
    "d_pawn_central_break",
    "flank_pawn_push",
    "kingside_aggression",
)
SEMANTIC_CLASS_MIN_COUNT = 3
SEMANTIC_CENTRAL_TO_KINGSIDE_CONFUSION_LIMIT = 0.25
SEMANTIC_TARGETED_CENTROID_DISTANCE_MIN = 0.5
SEMANTIC_TARGETED_CENTROID_PAIRS = (
    ("e_pawn_central_break", "kingside_aggression"),
    ("d_pawn_central_break", "kingside_aggression"),
    ("d_pawn_central_break", "flank_pawn_push"),
)
SEMANTIC_BALANCED_GATE_MIN_PER_DIFFICULTY = 3
SEMANTIC_REQUIRED_CLASSES = (*SEMANTIC_BALANCE_CLASSES, "development_move")
STYLE_AUDIT_SEMANTIC_CLASSES = ("kingside_aggression",)
BALANCED_PROMOTION_SEMANTIC_CLASSES = (
    "e_pawn_central_break",
    "d_pawn_central_break",
    "flank_pawn_push",
    "development_move",
)
CENTRAL_FLANK_FOCUS_SEMANTICS = (
    "e_pawn_central_break",
    "d_pawn_central_break",
    "flank_pawn_push",
)
FLANK_REPAIR_SEMANTIC = "flank_pawn_push"
FLANK_REASON_TAGS = (
    "space_gain",
    "attack_prep",
    "pawn_storm",
    "prophylaxis",
    "expansion",
    "bad_random_flank_push",
)
CENTRAL_VS_FLANK_BOUNDARY_SEMANTICS = (
    "e_pawn_central_break",
    "d_pawn_central_break",
    "flank_pawn_push",
)
CENTRAL_FLANK_TARGETED_TRAIN_OFFSETS = (2, 4, 8)
CENTRAL_FLANK_TARGETED_VALIDATION_OFFSETS = (7,)
SEMANTIC_SAMPLING_MAX_SKEW_RATIO = 2.0
SANITY_VARIANT_DIFFICULTY_PAIRS = {"easy": 1, "medium": 2, "hard": 3}
SANITY_COMMON_HARD_NEGATIVES = ("e7e5", "d7d5", "c7c5", "a7a5", "f8a3", "b8c6", "h7h5", "a6c4", "c6b4", "e5d4", "f8b4", "c5d4")
FUSION_MODES = ("strict_search", "balanced_fusion", "policy_preferred")
OPENING_MULTI_GOOD_CP_THRESHOLD = 50
OPENING_MULTI_GOOD_FINAL_MARGIN_THRESHOLD = 50.0
OPENING_LOW_POLICY_MARGIN_THRESHOLD = 0.02
OPENING_WHITE_CANDIDATES = ("e2e4", "d2d4", "c2c4", "g1f3")
OPENING_BLACK_CANDIDATES = ("e7e5", "d7d5", "c7c5", "g8f6", "e7e6", "c7c6")
DETERMINISTIC_STRENGTH_CASES = (
    {
        "case_id": "opening_develop_white",
        "category": "opening",
        "fen": chess.STARTING_FEN,
        "side": "white",
        "expected_best_moves": ["e2e4", "d2d4", "g1f3", "c2c4"],
    },
    {
        "case_id": "opening_develop_black",
        "category": "human_probe",
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        "side": "black",
        "expected_best_moves": ["e7e5", "c7c5", "e7e6", "c7c6"],
    },
    {
        "case_id": "mate_in_one_white",
        "category": "tactic",
        "fen": "6k1/5Q2/6K1/8/8/8/8/8 w - - 0 1",
        "side": "white",
        "expected_best_moves": ["f7e8", "f7g7"],
    },
    {
        "case_id": "mate_in_one_black",
        "category": "tactic",
        "fen": "8/8/8/8/8/6k1/5q2/6K1 b - - 0 1",
        "side": "black",
        "expected_best_moves": ["f2g2", "f2e1"],
    },
    {
        "case_id": "promotion_white",
        "category": "endgame",
        "fen": "k7/4P3/2K5/8/8/8/8/8 w - - 0 1",
        "side": "white",
        "expected_best_moves": ["e7e8q"],
    },
    {
        "case_id": "avoid_stalemate_white",
        "category": "endgame",
        "fen": "k7/3Q4/2K5/8/8/8/8/8 w - - 0 1",
        "side": "white",
        "expected_best_moves": ["d7b7"],
    },
    {
        "case_id": "queen_hanging_white",
        "category": "trap",
        "fen": "4k3/8/8/8/8/8/4r3/4KQ2 w - - 0 1",
        "side": "white",
        "expected_best_moves": ["e1e2", "f1e2"],
    },
    {
        "case_id": "free_queen_white",
        "category": "blunder_avoid",
        "fen": "4k3/8/8/8/8/8/4q3/4KQ2 w - - 0 1",
        "side": "white",
        "expected_best_moves": ["e1e2", "f1e2"],
    },
    {
        "case_id": "scholar_trap_black",
        "category": "trap",
        "fen": "r1bqkbnr/pppp1Qpp/2n5/4p3/4P3/8/PPPP1PPP/RNB1KBNR b KQkq - 0 3",
        "side": "black",
        "expected_best_moves": ["e8f7"],
    },
    {
        "case_id": "fried_liver_human_probe_black",
        "category": "human_probe",
        "fen": "r1bqkb1r/pppp1ppp/2n2n2/4N3/2B1P3/8/PPPP1PPP/RNBQK2R b KQkq - 0 4",
        "side": "black",
        "expected_best_moves": ["d7d5", "f6e4", "c6e5"],
    },
)


def _progress_enabled() -> bool:
    return str(os.environ.get("CHESS_VALIDATION_PROGRESS", "1")).strip().lower() not in {"0", "false", "no", "off"}


def _progress(message: str) -> None:
    if not _progress_enabled():
        return
    sys.stderr.write(f"[chess-live-learning-validation] {message}\n")
    sys.stderr.flush()


def _progress_bar(label: str, current: int, total: int, *, started: float | None = None, width: int = 24) -> None:
    if not _progress_enabled() or total <= 0:
        return
    current = max(0, min(int(current), int(total)))
    total = max(1, int(total))
    ratio = current / total
    filled = min(width, int(round(width * ratio)))
    bar = "#" * filled + "-" * (width - filled)
    elapsed = ""
    if started is not None:
        elapsed = f" elapsed={time.perf_counter() - started:.1f}s"
    _progress(f"{label} [{bar}] {current}/{total} {ratio * 100:.1f}%{elapsed}")


def _progress_every(total: int) -> int:
    return max(1, min(10, int(total) // 5 or 1))


@dataclass
class PlannedGame:
    label: str
    category: str
    expected_tier: str
    row: dict
    winner_color: str | None
    flow: list[dict]
    notes: list[str]
    preview_record: dict


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate chess live replay classification and auto-retraining.")
    parser.add_argument("--output-root", default="")
    parser.add_argument("--seed", type=int, default=20260509)
    parser.add_argument("--max-plies", type=int, default=MAX_PLIES)
    parser.add_argument("--wait-timeout", type=int, default=1800, help="Seconds to wait for autorun pipeline completion.")
    parser.add_argument("--engines", default="", help="Required engine alias. Use one of: exp1,exp3,exp4,exp5. exp2 was removed in favor of exp3.")
    parser.add_argument("--allow-multi-engine", action="store_true", help="Allow comma-separated --engines for intentional multi-engine validation.")
    parser.add_argument("--autorun-threshold", type=int, default=AUTORUN_THRESHOLD, help="Trusted replay count required before auto-retrain is launched for exp3/exp4.")
    parser.add_argument("--fast-retrain", action="store_true", help="Skip retrain checkpoint benchmarks plus autorun pipeline benchmark/promotion.")
    parser.add_argument("--skip-autorun-benchmark", action="store_true", help="Set HTML_LEARNING_CHESS_AUTORUN_SKIP_BENCHMARK=1 before launching autorun retrain.")
    parser.add_argument("--skip-autorun-promote", action="store_true", help="Set HTML_LEARNING_CHESS_AUTORUN_SKIP_PROMOTE=1 before launching autorun retrain.")
    parser.add_argument("--skip-retrain-benchmark-snapshots", action="store_true", help="Skip validation benchmark snapshots before/after each retrain checkpoint.")
    parser.add_argument("--benchmark-rounds", type=int, default=1, help="Round-robin benchmark rounds per pairing for formal validation snapshots.")
    parser.add_argument("--benchmark-max-plies", type=int, default=90, help="Maximum plies per formal benchmark game.")
    parser.add_argument("--benchmark-teacher-depth", type=int, default=2, help="Teacher search depth used by formal benchmark snapshots.")
    parser.add_argument("--quick-retrain-gate", action="store_true", help="Run fixed-replay quick retrain gate instead of full 30-game validation.")
    parser.add_argument("--quick-retrain-max-samples", type=int, default=QUICK_RETRAIN_MAX_SAMPLES)
    parser.add_argument("--quick-retrain-max-seconds", type=int, default=QUICK_RETRAIN_MAX_SECONDS)
    parser.add_argument(
        "--quick-retrain-skip-heavy-sanity",
        action="store_true",
        help=(
            "Skip the heavy per-checkpoint sanity_learning_probe / semantic_interference / prior_sanity_retention "
            "/ flank_context_feature_injection so checkpoint completes in retrain-bounded time. The checkpoint and "
            "promotion gate cannot pass while this flag is set: broad strength improvement is intentionally not "
            "evaluated, so smoke-gate / mistake retention evidence still gets recorded but is not promoted."
        ),
    )
    parser.add_argument("--semantic-specialist-probes", action="store_true", help="Run exp23 per-semantic specialist probes as diagnostic evidence.")
    parser.add_argument("--kingside-development-audit", action="store_true", help="Run exp24 kingside/development label, feature, and decision-path audit.")
    return parser.parse_args()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_safe(value):
    if isinstance(value, chess.Move):
        return value.uci()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {"type": "bytes", "sha256": hashlib.sha256(value).hexdigest(), "length": len(value)}
    if isinstance(value, set):
        return sorted(_json_safe(item) for item in value)
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return value


def _json_dump(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _jsonl_dump(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(_json_safe(row), ensure_ascii=False, sort_keys=True) for row in rows)
    path.write_text((content + "\n") if content else "", encoding="utf-8")


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _fen_after_moves(uci_moves: list[str]) -> str:
    board = chess.Board()
    for move_text in uci_moves:
        move = chess.Move.from_uci(str(move_text).lower())
        if move not in board.legal_moves:
            raise ValueError(f"quick fixture prefix contains illegal move {move_text} at {board.fen()}")
        board.push(move)
    return board.fen()


def _quick_fixture_case_bank() -> list[dict]:
    return [
        {"label": "mr_e4_e5", "category": "mistake_retention", "fen": _fen_after_moves(["e2e4"]), "expected": "e7e5"},
        {"label": "mr_d4_d5", "category": "mistake_retention", "fen": _fen_after_moves(["d2d4"]), "expected": "d7d5"},
        {"label": "mr_nf3_d5", "category": "mistake_retention", "fen": _fen_after_moves(["g1f3"]), "expected": "d7d5"},
        {"label": "mr_c4_nf6", "category": "mistake_retention", "fen": _fen_after_moves(["c2c4"]), "expected": "g8f6"},
        {"label": "open_start_e4", "category": "opening", "fen": chess.STARTING_FEN, "expected": "e2e4"},
        {"label": "open_c3_d5", "category": "opening", "fen": _fen_after_moves(["c2c3"]), "expected": "d7d5"},
        {"label": "open_b3_e5", "category": "opening", "fen": _fen_after_moves(["b2b3"]), "expected": "e7e5"},
        {"label": "open_f4_d5", "category": "opening", "fen": _fen_after_moves(["f2f4"]), "expected": "d7d5"},
        {"label": "tactic_scholar_king_capture", "category": "tactic", "fen": "r1bqkbnr/pppp1Qpp/2n5/4p3/4P3/8/PPPP1PPP/RNB1KBNR b KQkq - 0 3", "expected": "e8f7"},
        {"label": "tactic_bishop_fork", "category": "tactic", "fen": _fen_after_moves(["e2e4", "e7e5", "g1f3", "b8c6", "f1c4"]), "expected": "g8f6"},
        {"label": "tactic_capture_center", "category": "tactic", "fen": _fen_after_moves(["e2e4", "e7e5", "g1f3", "b8c6", "d2d4"]), "expected": "e5d4"},
        {"label": "tactic_pin_break", "category": "tactic", "fen": _fen_after_moves(["d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6", "c1g5"]), "expected": "f8e7"},
        {"label": "endgame_pawn_push_1", "category": "endgame", "fen": "8/8/8/8/8/2k5/4P3/2K5 w - - 0 1", "expected": "e2e4"},
        {"label": "endgame_pawn_push_2", "category": "endgame", "fen": "8/8/8/8/2k5/8/4P3/2K5 w - - 0 1", "expected": "e2e3"},
        {"label": "endgame_black_promote", "category": "endgame", "fen": "8/8/2k5/8/8/8/4p3/2K5 b - - 0 1", "expected": "e2e1q"},
        {"label": "endgame_king_support", "category": "endgame", "fen": "8/8/8/2k5/8/8/2K1P3/8 w - - 0 1", "expected": "e2e4"},
        {"label": "avoid_free_queen", "category": "blunder_avoid", "fen": "4k3/8/8/8/8/8/4q3/4KQ2 w - - 0 1", "expected": "e1e2"},
        {"label": "avoid_queen_trap", "category": "blunder_avoid", "fen": _fen_after_moves(["e2e4", "e7e5", "g1f3", "d8h4"]), "expected": "f3h4"},
        {"label": "avoid_center_capture", "category": "blunder_avoid", "fen": _fen_after_moves(["e2e4", "d7d5"]), "expected": "e4d5"},
        {"label": "avoid_recapture", "category": "blunder_avoid", "fen": _fen_after_moves(["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5c6"]), "expected": "d7c6"},
    ]


def _quick_fixture_moves_from_case(fen: str, expected_move: str, *, target_plies: int = 8) -> list[str]:
    board = chess.Board(str(fen))
    expected = chess.Move.from_uci(str(expected_move).lower())
    if expected not in board.legal_moves:
        raise ValueError(f"quick fixture expected move {expected_move} is illegal at {board.fen()}")
    moves = [expected.uci()]
    board.push(expected)
    while len(moves) < max(1, int(target_plies)) and not board.is_game_over():
        legal = sorted(board.legal_moves, key=lambda move: move.uci())
        if not legal:
            break
        chosen = legal[0]
        for move in legal:
            probe = board.copy(stack=False)
            probe.push(move)
            if not probe.is_game_over():
                chosen = move
                break
        moves.append(chosen.uci())
        board.push(chosen)
    return moves


def _quick_fixture_move_history(uci_moves: list[str], *, started_at: str, initial_fen: str = chess.STARTING_FEN) -> list[dict]:
    board = chess.Board(str(initial_fen or chess.STARTING_FEN))
    history = []
    for move_text in uci_moves:
        move = chess.Move.from_uci(str(move_text).lower())
        if move not in board.legal_moves:
            raise ValueError(f"quick replay fixture contains illegal move {move_text} at {board.fen()}")
        piece = board.piece_at(move.from_square)
        captured = board.piece_at(move.to_square)
        mover = "white" if board.turn == chess.WHITE else "black"
        history.append(
            {
                "at": started_at,
                "by": mover,
                "from": chess.square_name(move.from_square),
                "to": chess.square_name(move.to_square),
                "promotion": chess.piece_symbol(move.promotion) if move.promotion else None,
                "piece": piece.symbol() if piece else "",
                "captured": captured.symbol() if captured else None,
                "computer": False,
            }
        )
        board.push(move)
    return history


def _quick_retrain_fixture_records(*, engine_alias: str, difficulty: str, actor_username: str, seed: int) -> list[dict]:
    cases = _quick_fixture_case_bank()
    records = []
    stamp = _utc_now()
    rng = random.Random(seed + 303)
    for index, case in enumerate(cases[:QUICK_RETRAIN_GATE_TRUSTED_REPLAYS]):
        label = str(case["label"])
        category = str(case["category"])
        initial_fen = str(case["fen"])
        expected_move = str(case["expected"])
        board = chess.Board(initial_fen)
        engine_side = "white" if board.turn == chess.WHITE else "black"
        human_side = opponent(engine_side)
        winner_color = engine_side
        moves = _quick_fixture_moves_from_case(initial_fen, expected_move, target_plies=8)
        move_history = _quick_fixture_move_history(moves, started_at=stamp, initial_fen=initial_fen)
        for entry in move_history:
            entry["computer"] = str(entry.get("by")) == engine_side
        match_id = 900000 + index + 1
        replay_id = f"{engine_alias}_quick_gate_{index + 1:02d}_{label}"
        record = {
            "actor_username": actor_username,
            "adjudicated_or_natural": "adjudicated",
            "black_engine": difficulty if engine_side == "black" else "",
            "collection_tier": "trusted",
            "computer_difficulty": difficulty,
            "confidence_score": 0.92,
            "duplicate_flag": False,
            "duplicate_signature": hashlib.sha256((replay_id + json.dumps(moves)).encode("utf-8")).hexdigest(),
            "engine_name": difficulty,
            "engine_version": difficulty,
            "game_key": "chess",
            "human_side": human_side,
            "match_id": match_id,
            "mode": "computer",
            "move_count": len(move_history),
            "move_history": move_history,
            "opening_seed": initial_fen,
            "quarantine_reasons": [],
            "quick_category": category,
            "quick_expected_move": expected_move,
            "rating_estimate": 1500 + rng.randint(-120, 120),
            "replay_id": replay_id,
            "resign_abuse_flag": False,
            "result": winner_color,
            "result_reason": "quick_retrain_gate_fixture",
            "source": "quick_retrain_gate_fixture",
            "stored": True,
            "suspicious_flag": False,
            "timestamp": stamp,
            "updated_at": stamp,
            "white_engine": difficulty if engine_side == "white" else "",
            "winner_color": winner_color,
        }
        records.append(record)
    return records


def _write_quick_replay_fixture(records: list[dict], *, trusted_count: int) -> dict:
    trusted = [dict(row) for row in records[: int(trusted_count)]]
    trusted_path = default_chess_replay_buffer_path()
    quarantine_path = default_chess_replay_quarantine_path()
    rejected_path = default_chess_replay_rejected_path()
    _jsonl_dump(trusted_path, trusted)
    _jsonl_dump(quarantine_path, [])
    _jsonl_dump(rejected_path, [])
    return {
        "trusted_replay_path": str(trusted_path),
        "quarantine_replay_path": str(quarantine_path),
        "rejected_replay_path": str(rejected_path),
        "trusted_records_written": len(trusted),
        "quarantine_records_written": 0,
    }


def _quick_game_results(records: list[dict]) -> list[dict]:
    return [
        {
            "index": index,
            "game_id": int(record.get("match_id") or 0),
            "label": str(record.get("replay_id") or f"quick_{index:02d}"),
            "category": "valid",
            "expected_tier": "trusted",
            "human_side": str(record.get("human_side") or "white"),
            "winner_color": str(record.get("winner_color") or ""),
            "stored_replay": record,
            "autorun_result": None,
            "learning_update_count": 0,
        }
        for index, record in enumerate(records, start=1)
    ]


def _extract_engine_move_samples_from_records(records: list[dict]) -> list[dict]:
    samples: list[dict] = []
    for game_index, record in enumerate(records, start=1):
        history = record.get("move_history") or []
        if not isinstance(history, list):
            continue
        opening_seed = str(record.get("opening_seed") or "").strip()
        board = {"__fen__": opening_seed} if opening_seed and opening_seed != "standard_start" else initial_board()
        engine_side = opponent(str(record.get("human_side") or "white"))
        is_quick_fixture = str(record.get("source") or "") == "quick_retrain_gate_fixture"
        quick_expected_move = str(record.get("quick_expected_move") or "").lower()
        engine_move_index = 0
        for ply, entry in enumerate(history, start=1):
            mover = str((entry or {}).get("by") or "").strip().lower()
            from_square = str((entry or {}).get("from") or "").strip().lower()
            to_square = str((entry or {}).get("to") or "").strip().lower()
            promotion = (entry or {}).get("promotion")
            if mover == engine_side:
                engine_move_index += 1
                move_uci = f"{from_square}{to_square}{promotion or ''}"
                is_quick_expected_move = bool(
                    is_quick_fixture
                    and engine_move_index == 1
                    and quick_expected_move
                    and move_uci == quick_expected_move
                )
                category = str(record.get("quick_category") or "unknown")
                if is_quick_fixture and not is_quick_expected_move:
                    category = "fixture_continuation"
                samples.append(
                    {
                        "fen": str(board.get("__fen__") or ""),
                        "move_uci": move_uci,
                        "side": mover,
                        "game_index": game_index,
                        "game_id": int(record.get("match_id") or 0),
                        "game_label": str(record.get("replay_id") or ""),
                        "category": category,
                        "quick_expected_move": quick_expected_move,
                        "quick_engine_move_index": engine_move_index,
                        "is_quick_expected_move": is_quick_expected_move,
                        "ply": ply,
                    }
                )
            board = validate_move(board, mover, from_square, to_square, promotion)["board"]
    return samples


def _quick_replay_fixture_health(records: list[dict], accepted_rows: list[dict], rejected_rows: list[dict]) -> dict:
    category_distribution: dict[str, int] = {}
    poison_or_quarantine = 0
    for record in records or []:
        category = str(record.get("quick_category") or "unknown")
        category_distribution[category] = category_distribution.get(category, 0) + 1
        if (
            str(record.get("collection_tier") or "") != "trusted"
            or bool(record.get("suspicious_flag"))
            or bool(record.get("resign_abuse_flag"))
            or bool(record.get("duplicate_flag"))
            or record.get("quarantine_reasons")
        ):
            poison_or_quarantine += 1

    fen_keys = []
    target_moves = []
    position_target_keys = []
    normalized_board_keys = []
    for row in accepted_rows or []:
        fen = str(row.get("fen") or row.get("board_fen") or "").strip()
        target = str(row.get("move_uci") or row.get("uci") or row.get("move") or "").strip().lower()
        side = str(row.get("side") or "").strip().lower()
        fen_keys.append(fen)
        target_moves.append(target)
        position_target_keys.append(f"{fen}|{side}|{target}")
        try:
            board = chess.Board(fen)
            normalized_board_keys.append(board.board_fen())
        except Exception:
            normalized_board_keys.append(fen)

    total_rows = len(accepted_rows or [])
    unique_position_targets = len(set(position_target_keys))
    duplicate_ratio = round((total_rows - unique_position_targets) / max(1, total_rows), 4)
    required_categories = ["opening", "tactic", "endgame", "blunder_avoid", "mistake_retention"]
    missing_categories = [
        category
        for category in required_categories
        if int(category_distribution.get(category) or 0) < QUICK_RETRAIN_MIN_CASES_PER_CATEGORY
    ]
    reasons = []
    if duplicate_ratio > DATASET_DUPLICATE_RATIO_LIMIT:
        reasons.append("quick replay fixture duplicate_ratio exceeded gate threshold")
    if missing_categories:
        reasons.append(f"quick replay fixture category coverage below minimum: {','.join(missing_categories)}")
    if poison_or_quarantine > 0 or rejected_rows:
        reasons.append("quick replay fixture contains poison/quarantine/rejected rows")

    fixture_material = {
        "records": records or [],
        "accepted_position_targets": sorted(set(position_target_keys)),
        "category_distribution": category_distribution,
    }
    fixture_hash = hashlib.sha256(json.dumps(fixture_material, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return {
        "passed": not reasons,
        "reasons": reasons,
        "thresholds": {
            "duplicate_ratio_limit": DATASET_DUPLICATE_RATIO_LIMIT,
            "min_cases_per_category": QUICK_RETRAIN_MIN_CASES_PER_CATEGORY,
        },
        "duplicate_ratio": duplicate_ratio,
        "category_distribution": dict(sorted(category_distribution.items())),
        "unique_fen_count": len(set(fen_keys)),
        "unique_normalized_board_count": len(set(normalized_board_keys)),
        "unique_target_move_count": len(set(target_moves)),
        "unique_position_target_count": unique_position_targets,
        "total_rows": total_rows,
        "poison_quarantine_count": poison_or_quarantine,
        "rejected_row_count": len(rejected_rows or []),
        "fixture_hash": f"sha256:{fixture_hash}",
        "dedupe_basis": ["fen_hash", "normalized_board", "move_target"],
    }


def _static_teacher_annotation(fen: str, side: str, expected_move: str) -> dict:
    try:
        board = chess.Board(str(fen or ""))
        board.turn = chess.WHITE if str(side or "").lower() == "white" else chess.BLACK
        expected = chess.Move.from_uci(str(expected_move or "").lower())
    except Exception as exc:
        return {"supported": False, "reason": str(exc), "teacher_top3": [], "teacher_top5": []}
    if expected not in board.legal_moves:
        return {"supported": False, "reason": "expected move is illegal", "teacher_top3": [], "teacher_top5": []}
    color_sign = 1 if board.turn == chess.WHITE else -1
    piece_values = {
        chess.PAWN: 100,
        chess.KNIGHT: 320,
        chess.BISHOP: 330,
        chess.ROOK: 500,
        chess.QUEEN: 900,
        chess.KING: 0,
    }

    def material(current: chess.Board) -> int:
        total = 0
        for piece in current.piece_map().values():
            value = piece_values.get(piece.piece_type, 0)
            total += value if piece.color == chess.WHITE else -value
        return total

    scored = []
    for move in board.legal_moves:
        after = board.copy(stack=False)
        after.push(move)
        scored.append((color_sign * material(after), move.uci()))
    scored.sort(key=lambda item: (-item[0], item[1]))
    expected_score = next((score for score, move in scored if move == expected.uci()), None)
    best_score, best_move = scored[0] if scored else (expected_score or 0, expected.uci())
    return {
        "supported": True,
        "teacher_top3": [move for _, move in scored[:3]],
        "teacher_top5": [move for _, move in scored[:5]],
        "static_best_move": best_move,
        "static_cp_delta": int((expected_score or 0) - best_score),
        "teacher_best_score": best_score,
        "expected_score": expected_score,
    }


def _semantic_distribution_from_rows(rows: list[dict]) -> dict:
    counts = {semantic: 0 for semantic in SEMANTIC_REQUIRED_CLASSES}
    counts.setdefault("other", 0)
    for row in rows or []:
        semantic = str(row.get("semantic_class") or row.get("expected_semantic") or "other")
        counts[semantic] = int(counts.get(semantic) or 0) + 1
    return dict(sorted(counts.items()))


def _fen_hash(fen: str) -> str:
    return hashlib.sha256(str(fen or "").encode("utf-8")).hexdigest()


def _board_context_hash(fen: str, side: str = "") -> str:
    try:
        board = chess.Board(str(fen or ""))
        board.turn = chess.WHITE if str(side or "").lower() == "white" else chess.BLACK if str(side or "").lower() == "black" else board.turn
        pieces = []
        material = []
        for square, piece in sorted(board.piece_map().items()):
            pieces.append(f"{square}:{piece.symbol()}")
            material.append(piece.symbol())
        payload = {
            "board": board.board_fen(),
            "turn": "white" if board.turn == chess.WHITE else "black",
            "castling": board.castling_xfen(),
            "ep": board.ep_square,
            "pieces": pieces,
            "material": "".join(sorted(material)),
        }
    except Exception:
        payload = {"fen": str(fen or ""), "side": str(side or "")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _leakage_manifest_from_cases(cases: list[dict], *, split: str) -> list[dict]:
    manifest = []
    for index, case in enumerate(cases or [], start=1):
        fen = str(case.get("fen") or "")
        side = str(case.get("side") or "")
        expected = str(case.get("expected_move") or case.get("move_uci") or "").lower()
        manifest.append(
            {
                "case_id": str(case.get("case_id") or f"{split}_{index:04d}"),
                "split": split,
                "fen": fen,
                "fen_hash": _fen_hash(fen),
                "normalized_fen_hash": str(case.get("normalized_fen_hash") or _normalized_fen_hash(fen)),
                "board_context_hash": _board_context_hash(fen, side),
                "semantic_class": str(case.get("semantic_class") or case.get("expected_semantic") or _move_semantic_class(fen, side, expected)),
                "expected_move": expected,
            }
        )
    return manifest


def _exp30a_leakage_manifest() -> dict:
    held_out = _build_semantic_balanced_clean_gate_set(blocked_keys=set()).get("clean_gate_cases") or []
    validation = _semantic_balanced_supervised_variants(split="validation", offset=1)
    specialist = list(held_out)
    return {
        "source": "exp30a_distilled_replay_leakage_guard",
        "clean_held_out": _leakage_manifest_from_cases(held_out, split="clean_held_out"),
        "validation": _leakage_manifest_from_cases(validation, split="validation"),
        "specialist_probe": _leakage_manifest_from_cases(specialist, split="specialist_probe"),
    }


def _leakage_keys_from_manifest(manifest: dict) -> dict:
    exact = set()
    normalized_expected = set()
    context_expected = set()
    by_key: dict[tuple[str, str], list[dict]] = {}
    for split, entries in (manifest or {}).items():
        if split == "source":
            continue
        for entry in entries or []:
            expected = str(entry.get("expected_move") or "")
            exact_key = (str(entry.get("fen_hash") or ""), str(entry.get("normalized_fen_hash") or ""), str(entry.get("board_context_hash") or ""), expected)
            normalized_key = (str(entry.get("normalized_fen_hash") or ""), expected)
            context_key = (str(entry.get("board_context_hash") or ""), expected)
            exact.add(exact_key)
            normalized_expected.add(normalized_key)
            context_expected.add(context_key)
            for key_name, key_value in {
                "exact": exact_key,
                "normalized_expected": normalized_key,
                "context_expected": context_key,
            }.items():
                by_key.setdefault((key_name, json.dumps(key_value, sort_keys=True)), []).append(entry)
    return {
        "exact": exact,
        "normalized_expected": normalized_expected,
        "context_expected": context_expected,
        "by_key": by_key,
    }


def _row_leakage_matches(row: dict, keys: dict) -> list[dict]:
    fen = str(row.get("fen") or row.get("board_fen") or "")
    side = str(row.get("side") or "")
    expected = str(row.get("move_uci") or row.get("uci") or row.get("move") or row.get("expected_move") or "").lower()
    fen_hash = _fen_hash(fen)
    normalized = str(row.get("normalized_fen_hash") or _normalized_fen_hash(fen))
    context_hash = _board_context_hash(fen, side)
    row_keys = {
        "exact": (fen_hash, normalized, context_hash, expected),
        "normalized_expected": (normalized, expected),
        "context_expected": (context_hash, expected),
    }
    matches = []
    by_key = keys.get("by_key") or {}
    for key_name, key_value in row_keys.items():
        if key_value in (keys.get(key_name) or set()):
            matches.extend(by_key.get((key_name, json.dumps(key_value, sort_keys=True)), []))
    unique = {}
    for match in matches:
        unique[str(match.get("case_id") or json.dumps(match, sort_keys=True))] = match
    return list(unique.values())


def _distill_quick_replay_rows(
    raw_rows: list[dict],
    *,
    checkpoint_dir: Path,
    held_out_cases: list[dict] | None = None,
) -> tuple[list[dict], dict]:
    started = time.perf_counter()
    leakage_manifest = _exp30a_leakage_manifest()
    if held_out_cases:
        leakage_manifest["clean_held_out"] = _leakage_manifest_from_cases(held_out_cases, split="clean_held_out")
    leakage_keys = _leakage_keys_from_manifest(leakage_manifest)
    original_rows = list(raw_rows or [])
    before_position_keys = []
    source_by_key: dict[tuple[str, str, str], dict] = {}
    excluded_rows: list[dict] = []
    style_audit_rows: list[dict] = []
    blocked_leakage_rows: list[dict] = []
    bad_random_rows: list[dict] = []
    label_quality_rows: list[dict] = []
    quick_fixture_continuation_rows: list[dict] = []
    weak_semantics = {"d_pawn_central_break", "flank_pawn_push", "development_move"}

    for index, row in enumerate(original_rows, start=1):
        fen = str(row.get("fen") or row.get("board_fen") or "")
        side = str(row.get("side") or "")
        expected = str(row.get("move_uci") or row.get("uci") or row.get("move") or "").lower()
        case_id = str(row.get("case_id") or f"distill_raw_{index:04d}")
        semantic = _move_semantic_class(fen, side, expected)
        normalized = _normalized_fen_hash(fen)
        context_hash = _board_context_hash(fen, side)
        key = (_fen_hash(fen), normalized, expected)
        before_position_keys.append(key)
        case = {
            "case_id": case_id,
            "fen": fen,
            "side": side,
            "expected_move": expected,
            "expected_semantic": semantic,
            "semantic_class": semantic,
            "variant_split": "distilled_replay",
            "variant_difficulty": "hard" if int(row.get("source_move_index") or 0) >= 5 else "medium" if int(row.get("source_move_index") or 0) >= 3 else "easy",
            "normalized_fen_hash": normalized,
            "board_context_hash": context_hash,
        }
        replay_id = str(row.get("replay_id") or "")
        source_game_id = int(row.get("source_game_id") or row.get("game_id") or 0)
        source_move_index = int(row.get("source_move_index") or row.get("ply") or 0)
        is_quick_fixture_continuation = bool(
            "_quick_gate_" in replay_id
            and source_game_id >= 900000
            and source_move_index > 1
        )
        if is_quick_fixture_continuation:
            quick_fixture_continuation_rows.append(
                {
                    **case,
                    "source_game_id": source_game_id,
                    "source_move_index": source_move_index,
                    "replay_id": replay_id,
                    "reason": "quick fixture continuation move is not a supervised target",
                }
            )
        label = (_sanity_label_quality_audit([case]).get("cases") or [{}])[0]
        teacher = _static_teacher_annotation(fen, side, expected)
        reason_tag = _flank_reason_tag_for_move(fen, side, expected) if semantic == FLANK_REPAIR_SEMANTIC else ""
        leakage_matches = _row_leakage_matches(case, leakage_keys)
        leakage = bool(leakage_matches)
        label_quality = str(label.get("label_quality") or "invalid")
        if leakage:
            blocked_leakage_rows.append({**case, "reason": "held-out/validation/specialist probe overlap blocked before distillation", "matches": leakage_matches})
        if semantic in STYLE_AUDIT_SEMANTIC_CLASSES:
            style_audit_rows.append({**case, "reason": "style semantic excluded from balanced distilled training"})
        if semantic == FLANK_REPAIR_SEMANTIC and reason_tag == "bad_random_flank_push":
            bad_random_rows.append({**case, "reason": "bad random flank push excluded from balanced distilled training"})
        if label_quality != "clean":
            label_quality_rows.append({**case, "label_quality": label_quality, "reason": label.get("reason")})
        if (
            is_quick_fixture_continuation
            or leakage
            or semantic in STYLE_AUDIT_SEMANTIC_CLASSES
            or label_quality != "clean"
            or (semantic == FLANK_REPAIR_SEMANTIC and reason_tag == "bad_random_flank_push")
        ):
            excluded_rows.append(
                {
                    **case,
                    "label_quality": label_quality,
                    "reason_tag": reason_tag,
                    "excluded_reason": "quick_fixture_continuation/leakage/style/questionable/bad_random_flank",
                    "leakage_matches": leakage_matches,
                }
            )
            continue
        if key not in source_by_key:
            hard_negatives = list(dict.fromkeys([
                *_semantic_negative_moves(fen, side, expected, limit=5),
                *_legal_sanity_hard_negatives(fen, side, expected, limit=5),
            ]))[:6]
            confidence = 0.78
            if semantic in weak_semantics:
                confidence += 0.08
            if teacher.get("supported") and expected in (teacher.get("teacher_top3") or []):
                confidence += 0.05
            if teacher.get("static_cp_delta") is not None and float(teacher.get("static_cp_delta") or 0.0) < -80:
                confidence -= 0.12
            confidence = round(max(0.35, min(0.95, confidence)), 4)
            sample_weight = round(float(row.get("weight") or row.get("quality_weight") or 1.0) * (1.25 if semantic in weak_semantics else 1.0), 4)
            flank_context = _flank_context_features(fen, side) if semantic == FLANK_REPAIR_SEMANTIC else {}
            distilled = {
                **row,
                "case_id": f"distill_{semantic}_{len(source_by_key) + 1:04d}",
                "fen": fen,
                "side": side,
                "move_uci": expected,
                "expected_move": expected,
                "target": 1.0,
                "source": "distilled_trusted_replay",
                "distillation_source": "exp28_5_distilled_replay_preprocessing",
                "semantic_class": semantic,
                "expected_semantic": semantic,
                "reason_tag": reason_tag,
                "flank_reason_tag": reason_tag,
                "flank_context_features": flank_context,
                "flank_context_feature_vector": _flank_context_feature_vector(flank_context),
                "flank_context_feature_injection": semantic == FLANK_REPAIR_SEMANTIC,
                "difficulty": case["variant_difficulty"],
                "variant_difficulty": case["variant_difficulty"],
                "label_quality": label_quality,
                "static_best_move": teacher.get("static_best_move") or label.get("static_best_move"),
                "static_cp_delta": teacher.get("static_cp_delta") if teacher.get("static_cp_delta") is not None else label.get("static_cp_delta"),
                "teacher_top3": teacher.get("teacher_top3") or [],
                "teacher_top5": teacher.get("teacher_top5") or [],
                "hard_negatives": hard_negatives,
                "semantic_hard_negatives": _semantic_negative_moves(fen, side, expected, limit=5),
                "confidence": confidence,
                "sample_weight": sample_weight,
                "weight": sample_weight,
                "quality_weight": sample_weight,
                "normalized_fen_hash": normalized,
                "board_context_hash": context_hash,
                "source_game_ids": [str(row.get("source_game_id") or row.get("game_id") or row.get("replay_id") or "")],
                "source_replay_ids": [str(row.get("replay_id") or "")],
                "distilled_reasons": [
                    reason for reason, keep in {
                        "teacher_top3_contains_expected": expected in (teacher.get("teacher_top3") or []),
                        "weak_semantic_class": semantic in weak_semantics,
                        "model_teacher_disagreement": bool(teacher.get("static_best_move") and teacher.get("static_best_move") != expected),
                        "eval_swing_or_material_delta": abs(float(teacher.get("static_cp_delta") or 0.0)) >= 80,
                        "mistake_retention_related": str(row.get("accepted_reason") or "") == "trusted_replay",
                    }.items()
                    if keep
                ],
            }
            source_by_key[key] = distilled
        else:
            existing = source_by_key[key]
            existing["source_game_ids"] = sorted(set((existing.get("source_game_ids") or []) + [str(row.get("source_game_id") or row.get("game_id") or row.get("replay_id") or "")]))
            existing["source_replay_ids"] = sorted(set((existing.get("source_replay_ids") or []) + [str(row.get("replay_id") or "")]))
            existing["merged_duplicate_count"] = int(existing.get("merged_duplicate_count") or 0) + 1

    distilled_rows = list(source_by_key.values())
    post_leakage_rows = []
    for row in distilled_rows:
        matches = _row_leakage_matches(row, leakage_keys)
        if matches:
            post_leakage_rows.append(
                {
                    "case_id": row.get("case_id"),
                    "fen_hash": _fen_hash(str(row.get("fen") or "")),
                    "normalized_fen_hash": str(row.get("normalized_fen_hash") or _normalized_fen_hash(str(row.get("fen") or ""))),
                    "board_context_hash": str(row.get("board_context_hash") or _board_context_hash(str(row.get("fen") or ""), str(row.get("side") or ""))),
                    "expected_move": str(row.get("move_uci") or row.get("expected_move") or ""),
                    "source_game_ids": row.get("source_game_ids") or [],
                    "matches": matches,
                }
            )
    after_position_keys = [
        (
            _fen_hash(str(row.get("fen") or "")),
            str(row.get("normalized_fen_hash") or _normalized_fen_hash(str(row.get("fen") or ""))),
            str(row.get("move_uci") or row.get("expected_move") or ""),
        )
        for row in distilled_rows
    ]
    duplicate_ratio_before = round((len(before_position_keys) - len(set(before_position_keys))) / max(1, len(before_position_keys)), 4)
    duplicate_ratio_after = round((len(after_position_keys) - len(set(after_position_keys))) / max(1, len(after_position_keys)), 4)
    distilled_path = checkpoint_dir / "distilled_replay.jsonl"
    _jsonl_dump(distilled_path, distilled_rows)
    report = {
        "supported": True,
        "enabled": True,
        "source": "exp28_5_distilled_replay_preprocessing",
        "input": "trusted valid games",
        "output": str(distilled_path),
        "original_rows": len(original_rows),
        "distilled_rows": len(distilled_rows),
        "compression_ratio": round(len(distilled_rows) / max(1, len(original_rows)), 4),
        "duplicate_ratio_before": duplicate_ratio_before,
        "duplicate_ratio_after": duplicate_ratio_after,
        "semantic_distribution": _semantic_distribution_from_rows(distilled_rows),
        "style_audit_rows_excluded": len(style_audit_rows),
        "bad_random_flank_rows_excluded": len(bad_random_rows),
        "questionable_or_invalid_rows_excluded": len(label_quality_rows),
        "quick_fixture_continuation_rows_excluded": len(quick_fixture_continuation_rows),
        "pre_filter_overlap_count": len(blocked_leakage_rows),
        "blocked_leakage_candidate_count": len(blocked_leakage_rows),
        "leakage_detected": bool(post_leakage_rows),
        "leakage_count": len(post_leakage_rows),
        "held_out_in_training": bool(post_leakage_rows),
        "leakage_case_ids": sorted({str(match.get("case_id") or "") for row in post_leakage_rows for match in row.get("matches") or [] if match.get("case_id")}),
        "leakage_hashes": sorted({str(row.get("normalized_fen_hash") or row.get("fen_hash") or "") for row in post_leakage_rows}),
        "leakage_source_game_ids": sorted({str(game_id) for row in post_leakage_rows for game_id in row.get("source_game_ids") or [] if str(game_id)}),
        "blocked_leakage_case_ids": sorted({str(match.get("case_id") or "") for row in blocked_leakage_rows for match in row.get("matches") or [] if match.get("case_id")}),
        "blocked_leakage_hashes": sorted({str(row.get("normalized_fen_hash") or "") for row in blocked_leakage_rows}),
        "held_out_manifest": {
            split: [
                {
                    "case_id": entry.get("case_id"),
                    "fen_hash": entry.get("fen_hash"),
                    "normalized_fen_hash": entry.get("normalized_fen_hash"),
                    "board_context_hash": entry.get("board_context_hash"),
                    "semantic_class": entry.get("semantic_class"),
                    "expected_move": entry.get("expected_move"),
                }
                for entry in entries[:12]
            ]
            for split, entries in leakage_manifest.items()
            if split != "source"
        },
        "excluded_rows": excluded_rows[:20],
        "flank_reason_distribution": _flank_reason_distribution(distilled_rows),
        "timing_seconds": round(time.perf_counter() - started, 3),
        "notes": [
            "distillation is preprocessing evidence only; promotion still depends on deterministic balanced gate",
            "kingside_aggression is excluded from balanced distilled training and remains style audit only",
            "bad_random_flank_push is excluded from balanced training target",
        ],
    }
    _json_dump(checkpoint_dir / "distilled_replay_summary.json", report)
    return distilled_rows, report


def _previous_quick_gate_retrain_seconds(engine_alias: str, result_name: str = "exp28_context_conditioned_flank_semantic_learning") -> float | None:
    path = Path.home() / "chess_results" / result_name / "summary.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    for row in payload.get("engines") or []:
        if str(row.get("engine_alias") or "") == engine_alias:
            timing = row.get("timing_breakdown") or {}
            value = timing.get("retrain_seconds") or row.get("total_retrain_seconds")
            return round(float(value), 3) if value is not None else None
    return None


def _exp4_quick_retrain_sample_cap(requested_samples: int, max_seconds: int) -> tuple[int, str]:
    requested = max(1, int(requested_samples))
    cap_reason = ""
    if requested <= 0:
        return 0, cap_reason
    budget_seconds = max(1, int(max_seconds or 0))
    # Keep quick gate responsive on default 60s run while allowing deeper replay when user raises timeout.
    if budget_seconds >= 120:
        effective = requested
    elif budget_seconds >= 90:
        effective = min(requested, 192)
    else:
        effective = min(requested, 128)
    if effective != requested:
        cap_reason = (
            "exp4 quick gate cap based on max_seconds: "
            f"effective_samples={effective} of requested {requested}"
        )
    return effective, cap_reason


def _git_commit() -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
            check=True,
        )
    except Exception:
        return ""
    return str(proc.stdout or "").strip()


def _environment_summary() -> dict:
    torch_version = ""
    gpu = ""
    try:
        import torch  # type: ignore

        torch_version = str(torch.__version__)
        if bool(torch.cuda.is_available()):
            try:
                gpu = str(torch.cuda.get_device_name(0))
            except Exception:
                gpu = "cuda_available"
    except Exception:
        torch_version = ""
    if not gpu:
        try:
            proc = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], text=True, capture_output=True, check=True)
            gpu = str(proc.stdout.splitlines()[0]).strip() if proc.stdout.strip() else ""
        except Exception:
            gpu = ""
    return {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "cpu": platform.processor() or str(os.cpu_count() or ""),
        "gpu": gpu,
        "torch_version": torch_version,
    }


def _sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_json_subprocess(cmd: list[str], *, cwd: Path) -> dict:
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)
    payload = {
        "command": cmd,
        "returncode": int(proc.returncode),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "ok": False,
    }
    if proc.returncode != 0:
        return payload
    try:
        parsed = json.loads(proc.stdout)
    except Exception:
        payload["stderr"] = (proc.stderr or "") + "\nstdout did not contain valid JSON"
        return payload
    if isinstance(parsed, dict):
        payload.update(parsed)
    payload["ok"] = bool(payload.get("ok"))
    return payload


def _set_runtime_env(
    runtime_dir: Path,
    *,
    min_usable_replays: int,
    skip_autorun_benchmark: bool = False,
    skip_autorun_promote: bool = False,
) -> None:
    os.environ["HACKME_RUNTIME_DIR"] = str(runtime_dir)
    os.environ["PYTHONPATH"] = str(ROOT)
    os.environ["HTML_LEARNING_CHESS_RETRAIN_MIN_REPLAYS"] = str(int(min_usable_replays))
    if skip_autorun_benchmark:
        os.environ["HTML_LEARNING_CHESS_AUTORUN_SKIP_BENCHMARK"] = "1"
    if skip_autorun_promote:
        os.environ["HTML_LEARNING_CHESS_AUTORUN_SKIP_PROMOTE"] = "1"


def _move_uci(entry: dict) -> str:
    return f"{entry.get('from') or ''}{entry.get('to') or ''}{entry.get('promotion') or ''}".lower()


def _material_balance(board_state: dict) -> int:
    values = {"p": 1, "n": 3, "b": 3, "r": 5, "q": 9, "k": 0}
    score = 0
    for piece in board_state.values():
        if not isinstance(piece, str) or len(piece) != 1:
            continue
        val = values.get(piece.lower(), 0)
        score += val if piece.isupper() else -val
    return score


def _canonical_reject_reason(reasons: list[str]) -> str:
    mapping = {
        "duplicate": "duplicate",
        "suspicious_pattern": "suspicious_pattern",
        "early_resign": "resign_abuse",
        "resign_abuse": "resign_abuse",
        "invalid_move": "invalid_move",
        "illegal_position": "illegal_position",
        "malformed_replay": "malformed_replay",
        "contaminated_source": "contaminated_source",
    }
    for item in reasons or []:
        normalized = str(item or "").strip().lower()
        if normalized in mapping:
            return mapping[normalized]
    return "other"


def _source_stage_label(artifact_dir: Path, engine_dir: Path) -> str:
    if artifact_dir == engine_dir:
        return "final"
    try:
        trusted = int(artifact_dir.name)
    except Exception:
        return artifact_dir.name
    return f"checkpoint_{trusted:02d}"


def _select_requested_engines(requested_arg: str, *, allow_multi_engine: bool = False) -> list[tuple[str, str]]:
    requested = [item.strip() for item in str(requested_arg or "").split(",") if item.strip()]
    available = {alias: difficulty for alias, difficulty in ENGINE_MATRIX}
    if not requested:
        raise ValueError("pass exactly one --engines alias, e.g. --engines exp3")
    unknown = [alias for alias in requested if alias not in available]
    if unknown:
        raise ValueError(f"unknown engine alias: {','.join(unknown)}")
    if len(requested) > 1 and not allow_multi_engine:
        raise ValueError("multi-engine validation is disabled by default; pass --allow-multi-engine to run more than one")
    return [(alias, available[alias]) for alias in requested]


def _probe_position_score(board_state: dict, side: str) -> int:
    status = game_status(board_state, side)
    if status.get("status") == "finished":
        if status.get("reason") == "checkmate":
            return 100000 if status.get("winner_color") == opponent(side) else -100000
        if status.get("winner_color") == side:
            return 50000
        if status.get("winner_color") == opponent(side):
            return -50000
    return _material_balance(board_state) if side == "white" else -_material_balance(board_state)


def _engine_verdict(summary: dict) -> str:
    invalid_audit = summary.get("invalid_case_audit") or []
    if any(bool(row.get("entered_train_dataset")) for row in invalid_audit):
        return "FAIL"
    if bool((summary.get("stability") or {}).get("catastrophic_regression")):
        return "HIGH_RISK"
    if bool((summary.get("checkpoint_consistency") or {}).get("instability")):
        return "HIGH_RISK"
    if summary.get("engine_alias") == "exp1":
        risk = str((summary.get("exp1_live_learning") or {}).get("contamination_risk") or "").upper()
        if risk in {"HIGH", "FAIL", "HIGH RISK"}:
            return "HIGH_RISK"
        return "PASS"
    checkpoints = summary.get("before_after_eval", {}).get("checkpoints") or []
    expected_checkpoints = max(1, VALID_GAMES // max(1, int(summary.get("autorun_threshold") or 1)))
    if len(checkpoints) < expected_checkpoints:
        return "FAIL"
    sanity_results = {str((row.get("sanity_learning_probe") or {}).get("result_kind") or "") for row in checkpoints}
    if "partial_policy_learned_but_decision_unchanged" in sanity_results:
        return "PARTIAL_POLICY_LEARNED_BUT_DECISION_UNCHANGED"
    if "partial_seen_variants_only" in sanity_results:
        return "PARTIAL_SEEN_VARIANTS_ONLY"
    if any(str(row.get("pre_checkpoint_model_sha256") or "") == str(row.get("post_checkpoint_model_sha256") or "") for row in checkpoints):
        return "PARTIAL"
    if any(bool(row.get("ineffective_training")) for row in checkpoints):
        return "PARTIAL"
    deterministic = summary.get("deterministic_strength_snapshot") or {}
    if deterministic and not deterministic.get("passed"):
        return "PARTIAL"
    benchmark_before = summary.get("before_after_eval", {}).get("benchmark_before") or {}
    benchmark_after = summary.get("before_after_eval", {}).get("benchmark_after") or {}
    benchmark_skipped = bool(benchmark_before.get("skipped") or benchmark_after.get("skipped"))
    if not benchmark_skipped and float(benchmark_after.get("legal_rate") or 0.0) - float(benchmark_before.get("legal_rate") or 0.0) < -0.05:
        return "PARTIAL"
    return "PASS"


def _summary_benchmark_skipped(summary: dict) -> bool:
    before = summary.get("before_after_eval", {}).get("benchmark_before") or {}
    after = summary.get("before_after_eval", {}).get("benchmark_after") or {}
    if summary.get("before_after_eval", {}).get("retrain_supported") and (not before or not after):
        return True
    return bool(before.get("skipped") or after.get("skipped"))


def _summary_benchmark_skip_reason(summary: dict) -> str:
    before = summary.get("before_after_eval", {}).get("benchmark_before") or {}
    after = summary.get("before_after_eval", {}).get("benchmark_after") or {}
    if summary.get("before_after_eval", {}).get("retrain_supported") and (not before or not after):
        return "missing_formal_benchmark"
    return str(before.get("reason") or after.get("reason") or "")


def _summary_benchmark_changed(summary: dict) -> bool:
    if _summary_benchmark_skipped(summary):
        return False
    before = summary.get("before_after_eval", {}).get("benchmark_before") or {}
    after = summary.get("before_after_eval", {}).get("benchmark_after") or {}
    return bool(before.get("win_rate") != after.get("win_rate") or before.get("low_quality_rate") != after.get("low_quality_rate"))


def _summary_benchmark_expectation_met(summary: dict) -> bool:
    deterministic = summary.get("deterministic_strength_snapshot") or {}
    if deterministic:
        return bool(deterministic.get("passed"))
    if _summary_benchmark_skipped(summary):
        return True
    before = summary.get("before_after_eval", {}).get("benchmark_before") or {}
    after = summary.get("before_after_eval", {}).get("benchmark_after") or {}
    return bool(
        (after.get("win_rate") or 0.0) >= (before.get("win_rate") or 0.0)
        and (after.get("low_quality_rate") or 1.0) <= (before.get("low_quality_rate") or 1.0)
    )


def _move_uci_from_engine_move(move: dict | None) -> str:
    return f"{(move or {}).get('from') or ''}{(move or {}).get('to') or ''}{(move or {}).get('promotion') or ''}".lower()


def _piece_value(piece_symbol: str | None) -> int:
    values = {"p": 1, "n": 3, "b": 3, "r": 5, "q": 9, "k": 100}
    normalized = str(piece_symbol or "").strip().lower()
    return values.get(normalized, 0)


def _move_to_engine_shape(board_obj: chess.Board, move: chess.Move) -> dict:
    piece = board_obj.piece_at(move.from_square)
    captured = board_obj.piece_at(move.to_square)
    if board_obj.is_en_passant(move):
        capture_square = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
        captured = board_obj.piece_at(capture_square)
    return {
        "from": chess.square_name(move.from_square),
        "to": chess.square_name(move.to_square),
        "piece": piece.symbol() if piece else "",
        "captured": captured.symbol() if captured else None,
        "promotion": chess.piece_symbol(move.promotion) if move.promotion else None,
        "castle": bool(board_obj.is_castling(move)),
        "en_passant": bool(board_obj.is_en_passant(move)),
    }


def _scripted_human_move(
    board: dict,
    side: str,
    *,
    script: dict | None,
    script_index: int,
) -> tuple[dict | None, int, str | None]:
    if not script or script_index >= len(script.get("moves") or []):
        return None, script_index, None
    board_obj = chess.Board(str(board.get("__fen__") or chess.STARTING_FEN))
    planned_uci = str(script["moves"][script_index])
    try:
        planned_move = chess.Move.from_uci(planned_uci)
    except ValueError:
        return None, script_index, None
    if planned_move not in board_obj.legal_moves:
        return None, len(script.get("moves") or []), None
    return _move_to_engine_shape(board_obj, planned_move), script_index + 1, str(script.get("label") or "probe_script")


def _human_probe_move(board: dict, side: str, *, rng: random.Random) -> tuple[dict | None, str | None]:
    board_obj = chess.Board(str(board.get("__fen__") or chess.STARTING_FEN))
    if board_obj.turn != (chess.WHITE if side == "white" else chess.BLACK):
        board_obj.turn = chess.WHITE if side == "white" else chess.BLACK
    legal = list(board_obj.legal_moves)
    if not legal:
        return None, None

    scored: list[tuple[int, chess.Move, str]] = []
    for move in legal:
        piece = board_obj.piece_at(move.from_square)
        before_turn = side
        after = board_obj.copy(stack=False)
        after.push(move)
        status = game_status({"__fen__": after.fen()}, opponent(before_turn))
        score = 0
        reason = "probe_pressure"
        if status["status"] == "finished" and status.get("reason") == "checkmate" and status.get("winner_color") == side:
            score += 1_000_000
            reason = "probe_checkmate"
        elif after.is_check():
            score += 250
            reason = "probe_check"

        capture_value = 0
        captured = board_obj.piece_at(move.to_square)
        if board_obj.is_en_passant(move):
            capture_square = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
            captured = board_obj.piece_at(capture_square)
        if captured:
            capture_value = _piece_value(captured.symbol())
            score += capture_value * 90
            reason = "probe_capture"

        attacker_value = _piece_value(piece.symbol() if piece else "")
        target_side = after.turn
        attacked_heavy_targets = 0
        for square, target in after.piece_map().items():
            if target.color != target_side:
                continue
            target_value = _piece_value(target.symbol())
            if target_value >= 5 and after.is_attacked_by(not target_side, square):
                attacked_heavy_targets += 1
        if attacked_heavy_targets:
            score += attacked_heavy_targets * 120
            reason = "probe_fork_pressure"

        if piece and piece.piece_type in {chess.KNIGHT, chess.BISHOP, chess.QUEEN}:
            score += 10
        if move.promotion:
            score += 200
            reason = "probe_promotion"
        if attacker_value and capture_value > attacker_value:
            score += (capture_value - attacker_value) * 40

        scored.append((score, move, reason))

    if not scored:
        return None, None
    best_score = max(score for score, _move, _reason in scored)
    candidate_rows = [row for row in scored if row[0] == best_score]
    chosen_score, chosen_move, chosen_reason = rng.choice(candidate_rows)
    if chosen_score < 120:
        return None, None
    return _move_to_engine_shape(board_obj, chosen_move), chosen_reason


def _choose_human_move(
    board: dict,
    side: str,
    *,
    rng: random.Random,
    store: ChessExperimentStore,
    script: dict | None,
    script_index: int,
) -> tuple[dict | None, int, str]:
    moves = legal_moves(board, side)
    if not moves:
        return None, script_index, "no_legal_move"
    if len(moves) == 1:
        return moves[0], script_index, "forced_move"
    scripted_move, next_script_index, scripted_note = _scripted_human_move(board, side, script=script, script_index=script_index)
    if scripted_move:
        return scripted_move, next_script_index, scripted_note or "probe_script"
    probe_move, probe_note = _human_probe_move(board, side, rng=rng)
    if probe_move and rng.random() < 0.72:
        return probe_move, next_script_index, probe_note or "probe_move"
    roll = rng.random()
    if roll < 0.14:
        captures = [move for move in moves if move.get("captured")]
        if captures:
            return rng.choice(captures), next_script_index, "capture_bias"
    if roll < 0.24:
        return rng.choice(moves), next_script_index, "random_legal"
    difficulty = "hard" if rng.random() < 0.58 else "normal"
    return choose_computer_move(board, side, difficulty, learning_store=store) or rng.choice(moves), next_script_index, f"teacher_{difficulty}"


def _simulate_valid_game(
    *,
    engine_name: str,
    game_id: int,
    human_side: str,
    seed: int,
    max_plies: int,
    store: ChessExperimentStore,
) -> tuple[dict, str | None, list[dict], list[str]]:
    rng = random.Random(seed)
    board = initial_board()
    history: list[dict] = []
    flow: list[dict] = []
    notes: list[str] = []
    turn = "white"
    winner_color: str | None = None
    result_reason = ""
    candidate_scripts = [item for item in HUMAN_PROBE_OPENINGS if item["human_side"] == human_side]
    script = rng.choice(candidate_scripts) if candidate_scripts else None
    script_index = 0
    if script:
        notes.append(f"human_probe_script={script['label']}")

    for ply in range(1, max(1, max_plies) + 1):
        mover = turn
        status_before = game_status(board, mover)
        if status_before["status"] == "finished":
            winner_color = status_before.get("winner_color")
            result_reason = str(status_before.get("reason") or "")
            break
        board_before = str(board.get("__fen__") or "")
        think_started = time.perf_counter()
        if mover == human_side:
            move, script_index, decision_source = _choose_human_move(
                board,
                mover,
                rng=rng,
                store=store,
                script=script,
                script_index=script_index,
            )
            is_computer = False
        else:
            move = choose_computer_move(board, mover, engine_name, learning_store=store)
            is_computer = True
            decision_source = f"engine_{engine_name}"
        think_ms = round((time.perf_counter() - think_started) * 1000.0, 3)
        if not move:
            break
        applied = validate_move(board, mover, move["from"], move["to"], move.get("promotion"))
        board = applied["board"]
        history_entry = {
            "by": mover,
            "from": move["from"],
            "to": move["to"],
            "piece": move["piece"],
            "captured": applied.get("captured"),
            "promotion": move.get("promotion"),
            "computer": bool(is_computer),
            "at": _utc_now(),
        }
        history.append(history_entry)
        flow.append(
            {
                "ply": ply,
                "by": mover,
                "role": "computer" if is_computer else "human",
                "move_uci": _move_uci(history_entry),
                "captured": applied.get("captured"),
                "promotion": move.get("promotion"),
                "fen_before": board_before,
                "fen_after": str(board.get("__fen__") or ""),
                "decision_source": decision_source,
                "think_ms": think_ms,
            }
        )
        status_after = game_status(board, opponent(mover))
        if status_after["status"] == "finished":
            winner_color = status_after.get("winner_color")
            result_reason = str(status_after.get("reason") or "")
            break
        turn = opponent(mover)
    if not result_reason:
        result_reason = "max_plies"
        winner_color = None
    row = {
        "id": game_id,
        "game_key": "chess",
        "mode": "computer",
        "computer_difficulty": engine_name,
        "human_side": human_side,
        "initial_fen": "",
        "result_reason": result_reason,
        "updated_at": _utc_now(),
        "move_history_json": json.dumps(history, ensure_ascii=False),
    }
    notes.append(f"terminal_reason={result_reason}")
    return row, winner_color, flow, notes


def _preview_record(
    row: dict,
    *,
    winner_color: str | None,
    actor_username: str,
    existing_signatures: set[str],
) -> dict:
    record = build_replay_record(row, winner_color=winner_color, source="user_games", actor_username=actor_username)
    record = classify_replay_record(record, existing_signatures=existing_signatures)
    return record


def _generate_valid_games(
    *,
    engine_name: str,
    actor_username: str,
    game_start_id: int,
    seed: int,
    max_plies: int,
    store: ChessExperimentStore,
    target_count: int = VALID_GAMES,
    label_offset: int = 0,
    existing_signatures: set[str] | None = None,
) -> list[PlannedGame]:
    planned: list[PlannedGame] = []
    known_signatures: set[str] = set(existing_signatures or set())
    attempt = 0
    while len(planned) < target_count:
        attempt += 1
        if attempt > 2500:
            raise RuntimeError(f"unable to generate enough trusted natural checkmates for {engine_name}")
        row, winner_color, flow, notes = _simulate_valid_game(
            engine_name=engine_name,
            game_id=game_start_id + attempt,
            human_side="white" if (attempt + len(planned)) % 2 == 0 else "black",
            seed=seed + attempt * 37,
            max_plies=max_plies,
            store=store,
        )
        history = json.loads(row.get("move_history_json") or "[]")
        if str(row.get("result_reason") or "") != "checkmate":
            continue
        if len(history) < MIN_VALID_PLIES:
            continue
        preview = _preview_record(
            row,
            winner_color=winner_color,
            actor_username=actor_username,
            existing_signatures=known_signatures,
        )
        if preview.get("collection_tier") != "trusted":
            continue
        known_signatures.add(str(preview.get("duplicate_signature") or ""))
        planned.append(
            PlannedGame(
                label=f"valid_{label_offset + len(planned) + 1:02d}",
                category="valid",
                expected_tier="trusted",
                row=row,
                winner_color=winner_color,
                flow=flow,
                notes=["trusted_natural_checkmate", f"move_count={len(history)}"] + notes,
                preview_record=preview,
            )
        )
        sys.stderr.write(f"[{engine_name}] trusted valid planned {label_offset + len(planned)}/{VALID_GAMES}\n")
        sys.stderr.flush()
    return planned


def _duplicate_game(base: PlannedGame, *, game_id: int, actor_username: str, existing_signatures: set[str]) -> PlannedGame:
    row = deepcopy(base.row)
    row["id"] = game_id
    row["updated_at"] = _utc_now()
    preview = _preview_record(row, winner_color=base.winner_color, actor_username=actor_username, existing_signatures=existing_signatures)
    return PlannedGame(
        label=f"duplicate_from_{base.label}",
        category="invalid_duplicate",
        expected_tier="quarantine",
        row=row,
        winner_color=base.winner_color,
        flow=deepcopy(base.flow),
        notes=[f"duplicate_of={base.label}"],
        preview_record=preview,
    )


def _meaningless_loop_game(*, engine_name: str, game_id: int, human_side: str, actor_username: str, existing_signatures: set[str], variant: int) -> PlannedGame:
    history = []
    flow = []
    moves = [
        ("white", "g1", "h3"),
        ("black", "h3", "g1"),
    ]
    for ply in range(8):
        side, from_square, to_square = moves[ply % 2]
        entry = {
            "by": side,
            "from": from_square,
            "to": to_square,
            "piece": "N" if side == "white" else "n",
            "captured": None,
            "promotion": None,
            "computer": side != human_side,
            "at": _utc_now(),
        }
        history.append(entry)
        flow.append(
            {
                "ply": ply + 1,
                "by": side,
                "role": "synthetic_loop_probe",
                "move_uci": _move_uci(entry),
                "fen_before": "",
                "fen_after": "",
                "note": "intentionally synthetic low-signal loop for classifier probe",
            }
        )
    row = {
        "id": game_id,
        "game_key": "chess",
        "mode": "computer",
        "computer_difficulty": engine_name,
        "human_side": human_side,
        "initial_fen": "",
        "result_reason": f"adjudicated_meaningless_loop_{variant}",
        "updated_at": _utc_now(),
        "move_history_json": json.dumps(history, ensure_ascii=False),
    }
    preview = _preview_record(row, winner_color=None, actor_username=actor_username, existing_signatures=existing_signatures)
    return PlannedGame(
        label=f"meaningless_loop_{variant}",
        category="invalid_meaningless_loop",
        expected_tier="quarantine",
        row=row,
        winner_color=None,
        flow=flow,
        notes=["synthetic_suspicious_pattern_probe"],
        preview_record=preview,
    )


def _blunder_then_resign_game(*, engine_name: str, game_id: int, actor_username: str, existing_signatures: set[str]) -> PlannedGame:
    board = initial_board()
    flow = []
    history = []
    script = [
        ("white", "e2", "e4", None),
        ("black", "e7", "e5", None),
        ("white", "d1", "h5", None),
        ("black", "b8", "c6", None),
        ("white", "h5", "e5", None),
        ("black", "c6", "e5", None),
    ]
    for ply, (side, from_square, to_square, promotion) in enumerate(script, start=1):
        before = str(board.get("__fen__") or "")
        applied = validate_move(board, side, from_square, to_square, promotion)
        piece = next(move["piece"] for move in legal_moves(board, side) if move["from"] == from_square and move["to"] == to_square)
        entry = {
            "by": side,
            "from": from_square,
            "to": to_square,
            "piece": piece,
            "captured": applied.get("captured"),
            "promotion": promotion,
            "computer": side == "black",
            "at": _utc_now(),
        }
        board = applied["board"]
        history.append(entry)
        flow.append(
            {
                "ply": ply,
                "by": side,
                "role": "computer" if side == "black" else "human",
                "move_uci": _move_uci(entry),
                "captured": applied.get("captured"),
                "fen_before": before,
                "fen_after": str(board.get("__fen__") or ""),
            }
        )
    row = {
        "id": game_id,
        "game_key": "chess",
        "mode": "computer",
        "computer_difficulty": engine_name,
        "human_side": "white",
        "initial_fen": "",
        "result_reason": "resign",
        "updated_at": _utc_now(),
        "move_history_json": json.dumps(history, ensure_ascii=False),
    }
    preview = _preview_record(row, winner_color="black", actor_username=actor_username, existing_signatures=existing_signatures)
    return PlannedGame(
        label="blunder_then_resign",
        category="invalid_blunder_resign",
        expected_tier="quarantine",
        row=row,
        winner_color="black",
        flow=flow,
        notes=["human_blunder_then_early_resign"],
        preview_record=preview,
    )


def _short_low_signal_game(*, engine_name: str, game_id: int, actor_username: str, existing_signatures: set[str]) -> PlannedGame:
    board = initial_board()
    flow = []
    history = []
    script = [
        ("white", "e2", "e4", None),
        ("black", "e7", "e5", None),
        ("white", "d1", "h5", None),
    ]
    for ply, (side, from_square, to_square, promotion) in enumerate(script, start=1):
        before = str(board.get("__fen__") or "")
        legal = legal_moves(board, side)
        piece = next(move["piece"] for move in legal if move["from"] == from_square and move["to"] == to_square)
        applied = validate_move(board, side, from_square, to_square, promotion)
        entry = {
            "by": side,
            "from": from_square,
            "to": to_square,
            "piece": piece,
            "captured": applied.get("captured"),
            "promotion": promotion,
            "computer": side == "black",
            "at": _utc_now(),
        }
        board = applied["board"]
        history.append(entry)
        flow.append(
            {
                "ply": ply,
                "by": side,
                "role": "computer" if side == "black" else "human",
                "move_uci": _move_uci(entry),
                "captured": applied.get("captured"),
                "fen_before": before,
                "fen_after": str(board.get("__fen__") or ""),
                "note": "intentionally short low-signal trap",
            }
        )
    row = {
        "id": game_id,
        "game_key": "chess",
        "mode": "computer",
        "computer_difficulty": engine_name,
        "human_side": "white",
        "initial_fen": "",
        "result_reason": "max_plies_low_signal_probe",
        "updated_at": _utc_now(),
        "move_history_json": json.dumps(history, ensure_ascii=False),
    }
    preview = _preview_record(row, winner_color=None, actor_username=actor_username, existing_signatures=existing_signatures)
    return PlannedGame(
        label="short_low_signal",
        category="invalid_low_move_count",
        expected_tier="quarantine",
        row=row,
        winner_color=None,
        flow=flow,
        notes=["short_low_signal_trap", "expected_low_move_count_quarantine"],
        preview_record=preview,
    )


def _premature_resign_game(*, engine_name: str, game_id: int, actor_username: str, existing_signatures: set[str]) -> PlannedGame:
    board = initial_board()
    flow = []
    history = []
    script = [
        ("white", "d2", "d4", None),
        ("black", "d7", "d5", None),
        ("white", "c2", "c4", None),
        ("black", "e7", "e6", None),
        ("white", "b1", "c3", None),
    ]
    for ply, (side, from_square, to_square, promotion) in enumerate(script, start=1):
        before = str(board.get("__fen__") or "")
        legal = legal_moves(board, side)
        piece = next(move["piece"] for move in legal if move["from"] == from_square and move["to"] == to_square)
        applied = validate_move(board, side, from_square, to_square, promotion)
        entry = {
            "by": side,
            "from": from_square,
            "to": to_square,
            "piece": piece,
            "captured": applied.get("captured"),
            "promotion": promotion,
            "computer": side == "black",
            "at": _utc_now(),
        }
        board = applied["board"]
        history.append(entry)
        flow.append(
            {
                "ply": ply,
                "by": side,
                "role": "computer" if side == "black" else "human",
                "move_uci": _move_uci(entry),
                "captured": applied.get("captured"),
                "fen_before": before,
                "fen_after": str(board.get("__fen__") or ""),
                "note": "premature resign trap before tactical resolution",
            }
        )
    row = {
        "id": game_id,
        "game_key": "chess",
        "mode": "computer",
        "computer_difficulty": engine_name,
        "human_side": "white",
        "initial_fen": "",
        "result_reason": "resign",
        "updated_at": _utc_now(),
        "move_history_json": json.dumps(history, ensure_ascii=False),
    }
    preview = _preview_record(row, winner_color="black", actor_username=actor_username, existing_signatures=existing_signatures)
    return PlannedGame(
        label="premature_resign",
        category="invalid_premature_resign",
        expected_tier="quarantine",
        row=row,
        winner_color="black",
        flow=flow,
        notes=["premature_resign_trap", "expected_early_resign_quarantine"],
        preview_record=preview,
    )


def _plan_engine_games(
    *,
    engine_name: str,
    actor_username: str,
    seed: int,
    max_plies: int,
    store: ChessExperimentStore,
) -> list[PlannedGame]:
    base_valid_games = _generate_valid_games(
        engine_name=engine_name,
        actor_username=actor_username,
        game_start_id=1000,
        seed=seed,
        max_plies=max_plies,
        store=store,
        target_count=BASE_VALID_GAMES,
    )
    planned_signatures = {str(game.preview_record.get("duplicate_signature") or "") for game in base_valid_games}
    invalid_games = [
        _duplicate_game(base_valid_games[0], game_id=2001, actor_username=actor_username, existing_signatures=planned_signatures),
        _meaningless_loop_game(
            engine_name=engine_name,
            game_id=2002,
            human_side="white",
            actor_username=actor_username,
            existing_signatures=planned_signatures,
            variant=1,
        ),
        _short_low_signal_game(
            engine_name=engine_name,
            game_id=2003,
            actor_username=actor_username,
            existing_signatures=planned_signatures,
        ),
        _blunder_then_resign_game(
            engine_name=engine_name,
            game_id=2004,
            actor_username=actor_username,
            existing_signatures=planned_signatures,
        ),
        _premature_resign_game(
            engine_name=engine_name,
            game_id=2005,
            actor_username=actor_username,
            existing_signatures=planned_signatures,
        ),
    ]
    combined = list(base_valid_games) + invalid_games
    rng = random.Random(seed + 909)
    rng.shuffle(combined)
    extra_valid_games = _generate_valid_games(
        engine_name=engine_name,
        actor_username=actor_username,
        game_start_id=3000,
        seed=seed + 707,
        max_plies=max_plies,
        store=store,
        target_count=EXTRA_VALID_GAMES,
        label_offset=BASE_VALID_GAMES,
        existing_signatures=planned_signatures,
    )
    return combined + extra_valid_games


def _extract_engine_move_samples(valid_games: list[PlannedGame]) -> list[dict]:
    samples: list[dict] = []
    for game_index, game in enumerate(valid_games, start=1):
        history = json.loads(game.row["move_history_json"] or "[]")
        board = initial_board()
        engine_side = opponent(str(game.row.get("human_side") or "white"))
        for ply, entry in enumerate(history, start=1):
            mover = str((entry or {}).get("by") or "").strip().lower()
            from_square = str((entry or {}).get("from") or "").strip().lower()
            to_square = str((entry or {}).get("to") or "").strip().lower()
            promotion = (entry or {}).get("promotion")
            if mover == engine_side:
                samples.append(
                    {
                        "fen": str(board.get("__fen__") or ""),
                        "move_uci": f"{from_square}{to_square}{promotion or ''}",
                        "side": mover,
                        "game_index": game_index,
                        "game_id": int(game.row.get("id") or 0),
                        "game_label": game.label,
                        "ply": ply,
                    }
                )
            board = validate_move(board, mover, from_square, to_square, promotion)["board"]
    return samples


def _engine_focus_name(engine_alias: str) -> str:
    return {
        "exp1": "experiment",
        "exp3": "experiment 3:dl",
        "exp4": "experiment 4:pv",
        "exp5": "experiment 5:nnue",
    }[engine_alias]


def _engine_model_slot(engine_alias: str) -> str:
    return {
        "exp3": "dl",
        "exp4": "pv",
    }[engine_alias]


def _inventory_model_overrides(inventory_map: dict[str, dict]) -> dict[str, Path]:
    return {
        "dl": Path(str(inventory_map.get("experiment 3:dl", {}).get("path") or "")),
        "pv": Path(str(inventory_map.get("experiment 4:pv", {}).get("path") or "")),
        "nnue": Path(str(inventory_map.get("experiment 5:nnue", {}).get("path") or "")),
    }


def _trainer_key(engine_alias: str) -> str:
    return {
        "exp3": "exp3_refine",
        "exp4": "exp4_refine",
    }[engine_alias]


def _evaluate_move_agreement(engine_alias: str, model_path: Path, samples: list[dict]) -> dict:
    if engine_alias not in {"exp1", "exp3", "exp4", "exp5"}:
        return {"supported": False, "matches": 0, "total": 0, "agreement": 0.0, "avg_think_ms": 0.0}
    matches = 0
    elapsed_total_ms = 0.0
    for sample in samples:
        board_state = {"__fen__": str(sample["fen"] or "")}
        started = time.perf_counter()
        if engine_alias == "exp1":
            move = choose_computer_move(
                board_state,
                str(sample["side"] or "white"),
                EXPERIMENT_DIFFICULTY,
                learning_store=ChessExperimentStore(db_path=model_path),
            )
        elif engine_alias == "exp3":
            move = choose_experiment_dl_move(board_state, str(sample["side"] or "white"), model_path=model_path, search_profile="fast")
        elif engine_alias == "exp4":
            move = choose_experiment_pv_move(
                board_state,
                str(sample["side"] or "white"),
                model_path=model_path,
                search_profile="fast",
                decision_mode="mcts",
            )
        else:
            move = choose_experiment_nnue_move(
                board_state,
                str(sample["side"] or "white"),
                model_path=model_path,
                search_profile="fast",
            )
        elapsed_total_ms += (time.perf_counter() - started) * 1000.0
        predicted = f"{move['from']}{move['to']}{move.get('promotion') or ''}".lower() if move else ""
        if predicted == str(sample["move_uci"] or "").lower():
            matches += 1
    total = len(samples)
    return {
        "supported": True,
        "matches": matches,
        "total": total,
        "agreement": round(matches / total, 4) if total else 0.0,
        "avg_think_ms": round(elapsed_total_ms / total, 3) if total else 0.0,
        "total_think_ms": round(elapsed_total_ms, 3),
        "model_path": str(model_path or ""),
    }


def _choose_engine_move_for_eval(
    engine_alias: str,
    board_state: dict,
    side: str,
    model_path: Path,
    *,
    fusion_mode: str = "balanced_fusion",
    decision_context: dict | None = None,
) -> dict | None:
    if engine_alias == "exp1":
        return choose_computer_move(board_state, side, EXPERIMENT_DIFFICULTY, learning_store=ChessExperimentStore(db_path=model_path))
    if engine_alias == "exp3":
        return choose_experiment_dl_move(
            board_state,
            side,
            model_path=model_path,
            search_profile="fast",
            fusion_mode=fusion_mode,
            decision_context=decision_context,
        )
    if engine_alias == "exp4":
        return choose_experiment_pv_move(
            board_state,
            side,
            model_path=model_path,
            search_profile="fast",
            fusion_mode=fusion_mode,
            decision_context=decision_context,
            decision_mode="mcts",
        )
    if engine_alias == "exp5":
        return choose_experiment_nnue_move(
            board_state,
            side,
            model_path=model_path,
            search_profile="fast",
        )
    return None


def _opening_probe_move_bonus(board: chess.Board, move: chess.Move) -> int:
    if board.fullmove_number > 8:
        return 0
    piece = board.piece_at(move.from_square)
    if piece is None:
        return 0
    from_file = chess.square_file(move.from_square)
    from_rank = chess.square_rank(move.from_square)
    to_file = chess.square_file(move.to_square)
    to_rank = chess.square_rank(move.to_square)
    advance = abs(to_rank - from_rank)
    score = 0
    if piece.piece_type == chess.PAWN:
        if from_file in {chess.FILE_NAMES.index("d"), chess.FILE_NAMES.index("e")}:
            score += 1450 if advance == 2 and from_rank in {1, 6} else 520
        elif from_file == chess.FILE_NAMES.index("c"):
            score += 1300 if advance == 2 and from_rank in {1, 6} else 430
        elif from_file in {chess.FILE_NAMES.index("a"), chess.FILE_NAMES.index("h")}:
            score -= 900
        elif from_file in {chess.FILE_NAMES.index("b"), chess.FILE_NAMES.index("g")}:
            score -= 380
    elif piece.piece_type == chess.KNIGHT:
        if from_rank in {0, 7}:
            score += 920
        if to_file in {chess.FILE_NAMES.index("c"), chess.FILE_NAMES.index("f")}:
            score += 180
    elif piece.piece_type == chess.BISHOP and from_rank in {0, 7}:
        score += 700
    elif piece.piece_type == chess.QUEEN and board.fullmove_number <= 5 and not board.is_capture(move) and not board.gives_check(move):
        score -= 500
    elif piece.piece_type == chess.ROOK and board.fullmove_number <= 10:
        score -= 700
    if board.is_castling(move):
        score += 780
    return score


def _rank_deterministic_top3(engine_alias: str, board_state: dict, side: str, model_path: Path, top1_move: dict | None) -> list[str]:
    top1 = _move_uci_from_engine_move(top1_move)
    board_obj = chess.Board(str(board_state.get("__fen__") or chess.STARTING_FEN))
    legal_uci = {move.uci() for move in board_obj.legal_moves}
    scored: list[tuple[int, str]] = []
    for move in board_obj.legal_moves:
        after = board_obj.copy(stack=False)
        after.push(move)
        score = _probe_position_score({"__fen__": after.fen()}, opponent(side))
        if engine_alias in {"exp4", "exp5"}:
            score += _opening_probe_move_bonus(board_obj, move)
        scored.append((score, move.uci()))
    ranked = [uci for _score, uci in sorted(scored, key=lambda item: (-item[0], item[1]))]
    if top1 in legal_uci:
        ranked = [top1] + [uci for uci in ranked if uci != top1]
    return ranked[:3]


def _deterministic_case_policy_score(fen: str, side: str, move_uci: str) -> int | None:
    if not move_uci:
        return None
    board_state = {"__fen__": str(fen or "")}
    try:
        board_after = validate_move(board_state, side, move_uci[:2], move_uci[2:4], move_uci[4:] or None)["board"]
    except Exception:
        return None
    return _probe_position_score(board_after, opponent(side))


def _deterministic_strength_cases(samples: list[dict]) -> list[dict]:
    cases = [dict(case) for case in DETERMINISTIC_STRENGTH_CASES]
    mistake_samples = [sample for sample in samples if str(sample.get("category") or "") == "mistake_retention"]
    ordered_samples = mistake_samples + [sample for sample in samples if sample not in mistake_samples]
    for sample in ordered_samples[:3]:
        expected = str(sample.get("move_uci") or "").lower()
        if not expected:
            continue
        cases.append(
            {
                "case_id": f"mistake_retention_game_{int(sample.get('game_id') or 0)}_ply_{int(sample.get('ply') or 0)}",
                "category": "mistake_retention",
                "fen": str(sample.get("fen") or ""),
                "side": str(sample.get("side") or "white"),
                "expected_best_moves": [expected],
                "source_game_id": int(sample.get("game_id") or 0),
                "source_ply": int(sample.get("ply") or 0),
            }
        )
    return cases


def _aggregate_deterministic_strength(rows: list[dict]) -> dict:
    total = max(1, len(rows))
    top1 = sum(1 for row in rows if row.get("top1_correct"))
    top3 = sum(1 for row in rows if row.get("top3_contains"))
    illegal = sum(1 for row in rows if row.get("illegal_move"))
    blunder_cases = [row for row in rows if row.get("category") == "blunder_avoid"]
    blunders = sum(1 for row in blunder_cases if row.get("blunder"))
    categories: dict[str, dict] = {}
    for row in rows:
        category = str(row.get("category") or "unknown")
        bucket = categories.setdefault(category, {"count": 0, "top1": 0, "top3": 0, "illegal": 0, "blunders": 0})
        bucket["count"] += 1
        bucket["top1"] += 1 if row.get("top1_correct") else 0
        bucket["top3"] += 1 if row.get("top3_contains") else 0
        bucket["illegal"] += 1 if row.get("illegal_move") else 0
        bucket["blunders"] += 1 if row.get("blunder") else 0
    category_score = {}
    for category, bucket in categories.items():
        count = max(1, int(bucket["count"]))
        category_score[category] = {
            "count": int(bucket["count"]),
            "top1_correct_rate": round(bucket["top1"] / count, 4),
            "top3_contains_rate": round(bucket["top3"] / count, 4),
            "illegal_rate": round(bucket["illegal"] / count, 4),
            "blunder_rate": round(bucket["blunders"] / count, 4),
            "score": round((0.7 * bucket["top1"] + 0.3 * bucket["top3"]) / count, 4),
        }
    top1_rate = round(top1 / total, 4)
    top3_rate = round(top3 / total, 4)
    illegal_rate = round(illegal / total, 4)
    blunder_avoid_rate = round((len(blunder_cases) - blunders) / max(1, len(blunder_cases)), 4) if blunder_cases else 1.0
    overall = round(max(0.0, 0.7 * top1_rate + 0.3 * top3_rate - illegal_rate - (1.0 - blunder_avoid_rate) * 0.25), 4)
    return {
        "case_count": len(rows),
        "top1_correct_rate": top1_rate,
        "top3_contains_rate": top3_rate,
        "illegal_rate": illegal_rate,
        "blunder_avoid_rate": blunder_avoid_rate,
        "category_score": category_score,
        "overall_deterministic_score": overall,
    }


def _evaluate_deterministic_strength_snapshot(
    *,
    engine_alias: str,
    model_path: Path,
    model_label: str,
    cases: list[dict],
    seed: int,
    depth: int = DETERMINISTIC_STRENGTH_DEPTH,
    nodes: int = DETERMINISTIC_STRENGTH_MAX_NODES,
    time_limit_ms: int = DETERMINISTIC_STRENGTH_TIME_LIMIT_MS,
    fusion_mode: str = "balanced_fusion",
) -> dict:
    model_meta = _model_meta(model_path)
    rows = []
    total_cases = len(cases)
    progress_started = time.perf_counter()
    progress_every = _progress_every(total_cases)
    _progress_bar(f"deterministic snapshot {model_label}/{fusion_mode}", 0, total_cases, started=progress_started)
    for index, case in enumerate(cases, start=1):
        fen = str(case.get("fen") or "")
        side = str(case.get("side") or "white")
        expected = [str(move).lower() for move in (case.get("expected_best_moves") or [])]
        board_state = {"__fen__": fen}
        started = time.perf_counter()
        move = _choose_engine_move_for_eval(
            engine_alias,
            board_state,
            side,
            model_path,
            fusion_mode=fusion_mode,
            decision_context={"variant_difficulty": str(case.get("variant_difficulty") or ""), "prior_retention_stable": True, "deterministic_confidence": 0.75},
        )
        think_ms = round((time.perf_counter() - started) * 1000.0, 3)
        top1 = _move_uci_from_engine_move(move)
        top3 = _rank_deterministic_top3(engine_alias, board_state, side, model_path, move)
        illegal = False
        if top1:
            try:
                validate_move(board_state, side, top1[:2], top1[2:4], top1[4:] or None)
            except Exception:
                illegal = True
        else:
            illegal = True
        top1_correct = top1 in expected
        top3_contains = any(move_uci in top3 for move_uci in expected)
        blunder = bool(str(case.get("category") or "") == "blunder_avoid" and not top3_contains)
        rows.append(
            {
                "case_id": str(case.get("case_id") or ""),
                "category": str(case.get("category") or ""),
                "fen": fen,
                "side": side,
                "expected_best_moves": expected,
                "engine_top1": top1,
                "engine_top3": top3,
                "top1_correct": top1_correct,
                "top3_contains": top3_contains,
                "illegal_move": illegal,
                "blunder": blunder,
                "score_cp": _deterministic_case_policy_score(fen, side, top1),
                "policy_score": _deterministic_case_policy_score(fen, side, top1),
                "model_hash": model_meta["sha256"],
                "seed": int(seed),
                "depth": int(depth),
                "nodes": int(nodes),
                "time_limit_ms": int(time_limit_ms),
                "think_ms": think_ms,
                "fusion_mode": str(fusion_mode or "balanced_fusion"),
            }
        )
        if index == total_cases or index == 1 or index % progress_every == 0:
            _progress_bar(f"deterministic snapshot {model_label}/{fusion_mode}", index, total_cases, started=progress_started)
    aggregate = _aggregate_deterministic_strength(rows)
    return {
        "model_label": model_label,
        "model_path": str(model_path),
        "model_hash": model_meta["sha256"],
        "seed": int(seed),
        "depth": int(depth),
        "nodes": int(nodes),
        "time_limit_ms": int(time_limit_ms),
        "fusion_mode": str(fusion_mode or "balanced_fusion"),
        "cases": rows,
        "aggregate": aggregate,
    }


def _deterministic_strength_report(snapshots: list[dict]) -> dict:
    if not snapshots:
        return {"supported": False, "skipped": True, "reason": "no_deterministic_snapshots", "passed": False}
    by_label = {str(row.get("model_label") or ""): row for row in snapshots}
    baseline = by_label.get("baseline") or snapshots[0]
    checkpoint10 = by_label.get("checkpoint@10")
    checkpoint20 = by_label.get("checkpoint@20")
    final = by_label.get("final") or snapshots[-1]
    baseline_score = float((baseline.get("aggregate") or {}).get("overall_deterministic_score") or 0.0)
    checkpoint10_score = float(((checkpoint10 or {}).get("aggregate") or {}).get("overall_deterministic_score") or baseline_score)
    checkpoint20_score = float(((checkpoint20 or {}).get("aggregate") or {}).get("overall_deterministic_score") or checkpoint10_score)
    final_aggregate = final.get("aggregate") or {}
    final_score = float(final_aggregate.get("overall_deterministic_score") or 0.0)
    mistake_baseline = ((baseline.get("aggregate") or {}).get("category_score") or {}).get("mistake_retention", {}).get("score")
    mistake_final = (final_aggregate.get("category_score") or {}).get("mistake_retention", {}).get("score")
    reasons = []
    if final_score < baseline_score:
        reasons.append("final deterministic score regressed below baseline")
    if checkpoint20 and final_score < checkpoint20_score - DETERMINISTIC_CHECKPOINT20_DROP_LIMIT:
        reasons.append("final deterministic score regressed beyond checkpoint@20 threshold")
    if float(final_aggregate.get("illegal_rate") or 0.0) != 0.0:
        reasons.append("deterministic illegal_rate is nonzero")
    if float(final_aggregate.get("blunder_avoid_rate") or 0.0) < DETERMINISTIC_MIN_BLUNDER_AVOID_RATE:
        reasons.append("deterministic blunder_avoid_rate below threshold")
    if mistake_baseline is not None and mistake_final is not None and float(mistake_final) < float(mistake_baseline):
        reasons.append("mistake_retention deterministic category regressed below baseline")
    return {
        "supported": True,
        "skipped": False,
        "passed": not reasons,
        "reasons": reasons,
        "snapshots": snapshots,
        "score_table": [
            {
                "model_label": str(row.get("model_label") or ""),
                "model_hash": str(row.get("model_hash") or ""),
                **(row.get("aggregate") or {}),
            }
            for row in snapshots
        ],
        "final": final_aggregate,
        "regression_vs_baseline": round(final_score - baseline_score, 4),
        "regression_vs_checkpoint10": round(final_score - checkpoint10_score, 4),
        "regression_vs_checkpoint20": round(final_score - checkpoint20_score, 4),
        "thresholds": {
            "final_score_must_be_at_least_baseline": True,
            "checkpoint20_drop_limit": DETERMINISTIC_CHECKPOINT20_DROP_LIMIT,
            "illegal_rate_required": 0.0,
            "min_blunder_avoid_rate": DETERMINISTIC_MIN_BLUNDER_AVOID_RATE,
        },
    }


def _policy_override_audit(engine_alias: str, model_path: Path, cases: list[dict], deterministic_report: dict) -> dict:
    rows = []
    for case in cases or []:
        explanation = _engine_decision_breakdown(
            engine_alias,
            model_path,
            {"fen": case.get("fen"), "side": case.get("side"), "expected_move": (case.get("expected_best_moves") or [""])[0]},
        )
        override = explanation.get("policy_override") or {}
        if not override:
            continue
        rows.append(
            {
                "case_id": case.get("case_id"),
                "category": case.get("category"),
                "chosen_move": explanation.get("chosen_move"),
                "chosen_reason": explanation.get("chosen_reason"),
                "override_used": bool(override.get("used")),
                "override_move": override.get("move"),
                "margin": override.get("margin"),
                "thresholds": override.get("thresholds") or {},
                "override_reason": override.get("reason"),
            }
        )
    baseline_scores = {
        str(category): data
        for category, data in ((((deterministic_report.get("score_table") or [{}])[0]).get("category_score") or {}).items())
    }
    final_scores = {
        str(category): data
        for category, data in ((deterministic_report.get("final") or {}).get("category_score") or {}).items()
    }
    used_count = sum(1 for row in rows if row.get("override_used"))
    regression_reasons = []
    if used_count:
        for category in ("tactic", "blunder_avoid"):
            before = float((baseline_scores.get(category) or {}).get("score") or 0.0)
            after = float((final_scores.get(category) or {}).get("score") or 0.0)
            if after < before:
                regression_reasons.append(f"{category} deterministic score regressed while policy override was active")
    return {
        "override_usage_count": used_count,
        "override_cases": [row for row in rows if row.get("override_used")],
        "all_case_override_decisions": rows,
        "override_success_rate": round(
            sum(1 for row in rows if row.get("override_used") and row.get("override_move") == row.get("chosen_move")) / max(1, used_count),
            4,
        ) if used_count else 0.0,
        "override_regression_rate": round(len(regression_reasons) / max(1, used_count), 4) if used_count else 0.0,
        "regression_reasons": regression_reasons,
        "passed": not regression_reasons,
    }


def _opening_candidate_moves(fen: str, side: str) -> list[str]:
    try:
        board = chess.Board(str(fen or ""))
        board.turn = chess.WHITE if str(side or "").lower() == "white" else chess.BLACK
    except Exception:
        return []
    preferred = OPENING_WHITE_CANDIDATES if board.turn == chess.WHITE else OPENING_BLACK_CANDIDATES
    legal = {move.uci() for move in board.legal_moves}
    ordered = [move for move in preferred if move in legal]
    for move in sorted(legal):
        if move not in ordered:
            ordered.append(move)
    return ordered[:8]


def _opening_teacher_distribution(candidate_moves: list[str], teacher_top5: list[str], expected_move: str) -> list[dict]:
    candidates = list(dict.fromkeys([*(candidate_moves or []), *(teacher_top5 or []), str(expected_move or "")]))
    candidates = [move for move in candidates if move]
    top = [move for move in teacher_top5 or [] if move in candidates]
    if top:
        weight_map = {move: max(0.05, round(1.0 - index * 0.15, 4)) for index, move in enumerate(top)}
    else:
        weight_map = {str(expected_move or ""): 1.0} if expected_move else {}
    total = sum(float(value) for value in weight_map.values()) or 1.0
    return [
        {
            "move": move,
            "weight": round(float(weight_map.get(move) or 0.0) / total, 4),
            "teacher_rank": (top.index(move) + 1) if move in top else None,
        }
        for move in candidates
        if move in weight_map
    ]


def _opening_mcts_best_move(decision: dict) -> str:
    stats = (decision.get("mcts") or {}).get("stats") or []
    if stats:
        return str((stats[0] or {}).get("move") or "")
    if str(decision.get("chosen_reason") or "") == "policy_value_mcts":
        return str(decision.get("chosen_move") or "")
    return ""


def _opening_score_delta(expected_row: dict, selected_row: dict, *, key: str) -> float | None:
    if not expected_row or not selected_row:
        return None
    if expected_row.get(key) is None or selected_row.get(key) is None:
        return None
    return round(float(expected_row.get(key) or 0.0) - float(selected_row.get(key) or 0.0), 4)


def _opening_failure_type(
    *,
    expected: str,
    final_top1: str,
    raw_top3: list[str],
    mcts_best: str,
    static_best: str,
    search_best: str,
    multi_good_tie: bool,
    low_margin_override_rejected: bool,
    expected_cp_delta: float | None,
) -> str:
    if final_top1 == expected:
        return "passed"
    if multi_good_tie:
        return "multi_good_tie_not_failure"
    if expected not in raw_top3:
        return "raw_policy_fail"
    if mcts_best and mcts_best != expected and final_top1 == mcts_best:
        return "mcts_blocked"
    if static_best and static_best != expected and expected_cp_delta is not None and float(expected_cp_delta) < -OPENING_MULTI_GOOD_CP_THRESHOLD:
        return "static_eval_blocked"
    if search_best and search_best != expected and final_top1 == search_best:
        return "search_blocked"
    if low_margin_override_rejected:
        return "low_margin_override_rejected"
    return "final_decision_blocked"


def _opening_target_margin_audit(
    *,
    engine_alias: str,
    model_path: Path,
    deterministic_cases: list[dict],
    deterministic_report: dict,
    checkpoints: list[dict],
) -> dict:
    if engine_alias != "exp4":
        return {"supported": False, "reason": f"opening target margin audit is exp4-only; got {engine_alias}"}
    started = time.perf_counter()
    rows = []
    case_pool = [
        case
        for case in deterministic_cases or []
        if str(case.get("category") or "") in {"opening", "mistake_retention", "human_probe"}
    ]
    for case in case_pool:
        expected_moves = [str(move or "").lower() for move in (case.get("expected_best_moves") or []) if str(move or "").strip()]
        expected = expected_moves[0] if expected_moves else str(case.get("expected_move") or "").lower()
        if not expected:
            continue
        fen = str(case.get("fen") or "")
        side = str(case.get("side") or "white")
        teacher = _static_teacher_annotation(fen, side, expected)
        decision = _engine_decision_breakdown(
            engine_alias,
            model_path,
            {"fen": fen, "side": side, "expected_move": expected},
            old_move=str(case.get("old_move") or ""),
            fusion_mode="balanced_fusion",
        )
        raw = _evaluate_engine_raw_policy_position(engine_alias, model_path, {"case_id": case.get("case_id"), "fen": fen, "side": side, "expected_move": expected})
        expected_row = _move_row_from_decision(decision, expected)
        chosen = str(decision.get("chosen_move") or "")
        chosen_row = decision.get("chosen_breakdown") or _move_row_from_decision(decision, chosen)
        second_rows = [
            row for row in (decision.get("top_final_moves") or [])
            if str((row or {}).get("move") or "") != expected and (row or {}).get("final_combined_score") is not None
        ]
        best_other = max(second_rows, key=lambda row: float(row.get("final_combined_score") or 0.0), default={})
        margin_vs_second = _opening_score_delta(expected_row, best_other, key="final_combined_score")
        margin_vs_selected = _opening_score_delta(expected_row, chosen_row, key="final_combined_score")
        raw_margin_vs_selected = _opening_score_delta(expected_row, chosen_row, key="raw_policy_score")
        candidate_moves = _opening_candidate_moves(fen, side)
        teacher_top3 = teacher.get("teacher_top3") or []
        teacher_top5 = teacher.get("teacher_top5") or []
        expected_cp_delta = teacher.get("static_cp_delta")
        final_top3 = [str((row or {}).get("move") or "") for row in (decision.get("top_final_moves") or [])[:3]]
        equivalent_moves = list(dict.fromkeys([*expected_moves, *teacher_top3, *teacher_top5]))
        multi_good_tie = bool(
            (expected_cp_delta is not None and float(expected_cp_delta) >= -OPENING_MULTI_GOOD_CP_THRESHOLD)
            or (margin_vs_selected is not None and abs(float(margin_vs_selected)) <= OPENING_MULTI_GOOD_FINAL_MARGIN_THRESHOLD)
            or (chosen in equivalent_moves and chosen != expected)
        )
        override = decision.get("policy_override") or {}
        override_attempted = bool(override)
        override_applied = bool((decision.get("chosen_breakdown") or {}).get("override_applied")) or str(decision.get("chosen_reason") or "") == "high_confidence_policy_override"
        low_margin = raw_margin_vs_selected is not None and abs(float(raw_margin_vs_selected)) < OPENING_LOW_POLICY_MARGIN_THRESHOLD
        low_margin_override_rejected = bool(override_attempted and not override_applied and (low_margin or multi_good_tie))
        low_margin_override_applied = bool(override_applied and (low_margin or multi_good_tie))
        static_best = str(teacher.get("static_best_move") or _best_candidate_by_score(decision, "static_eval_score").get("move") or "")
        search_best = str(_best_candidate_by_score(decision, "search_score").get("move") or "")
        mcts_best = _opening_mcts_best_move(decision)
        failure_type = _opening_failure_type(
            expected=expected,
            final_top1=chosen,
            raw_top3=[str(move) for move in raw.get("raw_policy_top3") or []],
            mcts_best=mcts_best,
            static_best=static_best,
            search_best=search_best,
            multi_good_tie=multi_good_tie,
            low_margin_override_rejected=low_margin_override_rejected,
            expected_cp_delta=expected_cp_delta,
        )
        rows.append(
            {
                "case_id": case.get("case_id"),
                "category": case.get("category"),
                "fen": fen,
                "side": side,
                "expected_move": expected,
                "candidate_moves": candidate_moves,
                "teacher_top3": teacher_top3,
                "teacher_top5": teacher_top5,
                "teacher_distribution": _opening_teacher_distribution(candidate_moves, teacher_top5, expected),
                "static_best_move": static_best,
                "search_best_move": search_best,
                "mcts_best_move": mcts_best,
                "final_top1": chosen,
                "final_top3": final_top3,
                "expected_cp_delta": expected_cp_delta,
                "margin_vs_second_best": margin_vs_second,
                "margin_vs_selected_move": margin_vs_selected,
                "raw_margin_vs_selected_move": raw_margin_vs_selected,
                "label_quality": "multi_good_tie" if multi_good_tie else ("clean" if teacher.get("supported") else "invalid"),
                "multi_good_tie": multi_good_tie,
                "multi_good_credit_applied": bool(multi_good_tie and chosen in equivalent_moves),
                "strict_top1_fail_but_multi_good_pass": bool(chosen != expected and multi_good_tie and chosen in equivalent_moves),
                "raw_policy_score": raw.get("expected_logit"),
                "raw_policy_rank": raw.get("expected_rank"),
                "raw_policy_top1": raw.get("raw_policy_top1"),
                "raw_policy_top3": raw.get("raw_policy_top3"),
                "mcts_prior": expected_row.get("mcts_prior"),
                "mcts_visit_count": expected_row.get("mcts_visit_count"),
                "mcts_q_value": expected_row.get("mcts_q_value"),
                "static_eval_score": expected_row.get("static_eval_score"),
                "search_score": expected_row.get("search_score"),
                "final_combined_score": expected_row.get("final_combined_score") or expected_row.get("fused_score"),
                "rejection_reason": failure_type,
                "failure_type": failure_type,
                "override_attempted": override_attempted,
                "override_applied": override_applied,
                "override_rejected_reason": "low_margin_override_rejected" if low_margin_override_rejected else str(override.get("reason") or ""),
                "low_margin_override_rejected": low_margin_override_rejected,
                "low_margin_override_applied": low_margin_override_applied,
                "decision_breakdown": {
                    "chosen_reason": decision.get("chosen_reason"),
                    "policy_override": override,
                    "expected_move_breakdown": expected_row,
                    "chosen_breakdown": chosen_row,
                    "mcts": decision.get("mcts") or {},
                },
            }
        )
    failure_counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("failure_type") or "unknown")
        failure_counts[key] = int(failure_counts.get(key) or 0) + 1
    score_by_label = {
        str(row.get("model_label") or ""): float(row.get("overall_deterministic_score") or 0.0)
        for row in deterministic_report.get("score_table") or []
    }
    final_score = score_by_label.get("final")
    baseline_score = score_by_label.get("baseline")
    broad_strength_improvement = bool(final_score is not None and baseline_score is not None and final_score > baseline_score)
    latest_probe = ((checkpoints[-1] or {}).get("mistake_retention_probe") if checkpoints else {}) or {}
    targeted_learning_success = bool(
        latest_probe.get("matched_expected")
        or str(latest_probe.get("result_kind") or "") in {"matched_expected", "retained_expected"}
    )
    low_margin_override_applied_count = sum(1 for row in rows if row.get("low_margin_override_applied"))
    final_decision_alignment_passed = bool(
        rows
        and low_margin_override_applied_count == 0
        and all(str(row.get("failure_type")) in {"passed", "multi_good_tie_not_failure"} for row in rows)
    )
    return {
        "supported": True,
        "source": "exp4_05_opening_target_margin_mcts_alignment",
        "model_scope": "opening_specialist_candidate",
        "case_count": len(rows),
        "multi_good_tie_count": sum(1 for row in rows if row.get("multi_good_tie")),
        "multi_good_credit_applied_count": sum(1 for row in rows if row.get("multi_good_credit_applied")),
        "strict_top1_fail_but_multi_good_pass_count": sum(1 for row in rows if row.get("strict_top1_fail_but_multi_good_pass")),
        "low_margin_override_attempted_count": sum(1 for row in rows if row.get("override_attempted")),
        "low_margin_override_applied_count": low_margin_override_applied_count,
        "low_margin_override_rejected_count": sum(1 for row in rows if row.get("low_margin_override_rejected")),
        "failure_type_counts": dict(sorted(failure_counts.items())),
        "targeted_learning_success": targeted_learning_success,
        "broad_strength_improvement": broad_strength_improvement,
        "deterministic_baseline_score": baseline_score,
        "deterministic_final_score": final_score,
        "final_decision_alignment_passed": final_decision_alignment_passed,
        "passed": final_decision_alignment_passed and broad_strength_improvement and targeted_learning_success,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "cases": rows,
        "notes": [
            "multi_good_tie cases use top-K/equivalent credit instead of strict expected top1",
            "low-margin policy override cannot count as final decision learning success",
            "targeted mistake-retention success is not broad strength improvement by itself",
        ],
    }


def _fusion_mode_variant_rate(engine_alias: str, model_path: Path, variants: list[dict], *, fusion_mode: str) -> dict:
    rows = []
    hits = 0
    overrides = 0
    disagreements = 0
    for variant in (variants or [])[:SANITY_LEARNING_VARIANT_COUNT]:
        side = str(variant.get("side") or "white")
        expected = str(variant.get("expected_move") or "").lower()
        board_state = {"__fen__": str(variant.get("fen") or "")}
        context = {
            "variant_difficulty": str(variant.get("variant_difficulty") or ""),
            "prior_retention_stable": True,
            "deterministic_confidence": 0.75,
        }
        move = _choose_engine_move_for_eval(
            engine_alias,
            board_state,
            side,
            model_path,
            fusion_mode=fusion_mode,
            decision_context=context,
        )
        top1 = _move_uci_from_engine_move(move)
        raw = _evaluate_engine_raw_policy_position(engine_alias, model_path, variant, old_move=top1)
        raw_top = str(raw.get("raw_policy_top1") or "")
        override_applied = bool(str(fusion_mode) != "strict_search" and raw_top and raw_top == top1)
        overrides += 1 if override_applied else 0
        disagreements += 1 if raw_top and raw_top != top1 else 0
        hits += 1 if top1 == expected else 0
        rows.append(
            {
                "case_id": variant.get("case_id"),
                "variant_split": variant.get("variant_split"),
                "variant_difficulty": variant.get("variant_difficulty"),
                "expected_move": expected,
                "top1": top1,
                "raw_policy_top1": raw_top,
                "override_applied": override_applied,
                "override_reason": "bounded_fusion_mode_probe",
                "policy_search_disagreement": bool(raw_top and raw_top != top1),
                "expected_rank": raw.get("expected_rank"),
                "expected_margin_vs_old_move": raw.get("margin_vs_old_move"),
            }
        )
    total = len(rows)
    return {
        "case_count": total,
        "final_decision_generalization_rate": round(hits / max(1, total), 4),
        "override_usage_count": overrides,
        "override_success_rate": round(hits / max(1, overrides), 4) if overrides else 0.0,
        "policy_search_disagreement_rate": round(disagreements / max(1, total), 4),
        "cases": rows,
    }


def _fusion_mode_comparison(
    *,
    engine_alias: str,
    model_path: Path,
    deterministic_cases: list[dict],
    deterministic_report: dict,
    checkpoints: list[dict],
    seed: int,
) -> dict:
    baseline_final = deterministic_report.get("final") or {}
    baseline_tactic = float(((baseline_final.get("category_score") or {}).get("tactic") or {}).get("score") or 0.0)
    baseline_blunder = float(baseline_final.get("blunder_avoid_rate") or 0.0)
    final_probe = (checkpoints[-1].get("sanity_learning_probe") if checkpoints else {}) or {}
    unseen_payload = final_probe.get("unseen_variants") or {}
    all_unseen_variants = list(unseen_payload.get("clean_gate_cases") or unseen_payload.get("cases") or [])
    unseen_variants = [
        case
        for case in all_unseen_variants
        if str(case.get("expected_semantic") or case.get("semantic_class") or "") in BALANCED_PROMOTION_SEMANTIC_CLASSES
    ]
    excluded_style_variants = [
        case
        for case in all_unseen_variants
        if str(case.get("expected_semantic") or case.get("semantic_class") or "") in STYLE_AUDIT_SEMANTIC_CLASSES
    ]
    comparison_cases = [
        case
        for case in deterministic_cases
        if str(case.get("category") or "") in {"tactic", "blunder_avoid", "mistake_retention", "human_probe"}
    ] or deterministic_cases
    rows = []
    for mode in FUSION_MODES:
        snapshot = _evaluate_deterministic_strength_snapshot(
            engine_alias=engine_alias,
            model_path=model_path,
            model_label=f"final:{mode}",
            cases=comparison_cases,
            seed=seed,
            fusion_mode=mode,
        )
        aggregate = snapshot.get("aggregate") or {}
        category = aggregate.get("category_score") or {}
        variant_rate = _fusion_mode_variant_rate(engine_alias, model_path, unseen_variants, fusion_mode=mode)
        tactic_score = float((category.get("tactic") or {}).get("score") or 0.0)
        blunder_rate = float(aggregate.get("blunder_avoid_rate") or 0.0)
        rows.append(
            {
                "fusion_mode": mode,
                "deterministic_case_count": len(comparison_cases),
                "balanced_variant_case_count": len(unseen_variants),
                "excluded_style_variant_count": len(excluded_style_variants),
                "balanced_gate_semantic_set": list(BALANCED_PROMOTION_SEMANTIC_CLASSES),
                "excluded_style_semantics": list(STYLE_AUDIT_SEMANTIC_CLASSES),
                "deterministic_score": aggregate.get("overall_deterministic_score"),
                "illegal_rate": aggregate.get("illegal_rate"),
                "tactic_score": tactic_score,
                "blunder_avoid_rate": blunder_rate,
                "tactic_regression": tactic_score < baseline_tactic,
                "blunder_regression": blunder_rate < baseline_blunder,
                **variant_rate,
            }
        )
    best = max(rows, key=lambda row: (float(row.get("final_decision_generalization_rate") or 0.0), float(row.get("deterministic_score") or 0.0)), default={})
    regression_rows = [row for row in rows if row.get("tactic_regression") or row.get("blunder_regression")]
    return {
        "supported": True,
        "selected_gate_mode": "balanced_fusion",
        "best_mode": best.get("fusion_mode"),
        "modes": rows,
        "policy_search_disagreement_rate": float((next((row for row in rows if row.get("fusion_mode") == "balanced_fusion"), {}) or {}).get("policy_search_disagreement_rate") or 0.0),
        "override_success_rate": float((next((row for row in rows if row.get("fusion_mode") == "balanced_fusion"), {}) or {}).get("override_success_rate") or 0.0),
        "override_regression_rate": round(len(regression_rows) / max(1, len(rows)), 4),
        "regression_reasons": [
            f"{row.get('fusion_mode')} tactic/blunder regression"
            for row in regression_rows
        ],
        "passed": not regression_rows,
    }


def _style_profile_audit(
    *,
    engine_alias: str,
    model_path: Path,
    deterministic_cases: list[dict],
    seed: int,
) -> dict:
    if engine_alias != "exp3":
        return {
            "supported": False,
            "reason": "style profile audit is currently implemented for exp3 DL engine",
            "promotion_gate_profile": "balanced",
        }
    probe_cases = [
        case
        for case in deterministic_cases
        if str(case.get("category") or "") in {"tactic", "blunder_avoid", "human_probe", "mistake_retention"}
    ][:6] or deterministic_cases[:6]
    profiles = {}
    for profile in ["balanced", "attacking", "defensive"]:
        rows = []
        for case in probe_cases:
            fen = str(case.get("fen") or "")
            side = str(case.get("side") or "white")
            if not fen:
                continue
            try:
                explanation = explain_experiment_dl_decision(
                    {"__fen__": fen},
                    side,
                    model_path=model_path,
                    search_profile="fast",
                    watched_moves=list(case.get("expected_best_moves") or [])[:3],
                    fusion_mode="balanced_fusion",
                    decision_context={
                        "variant_difficulty": str(case.get("variant_difficulty") or case.get("category") or "deterministic"),
                        "prior_retention_stable": True,
                        "deterministic_confidence": 0.75,
                    },
                    style_profile=profile,
                )
            except Exception as exc:
                rows.append({"case_id": case.get("case_id"), "supported": False, "reason": str(exc)})
                continue
            style = explanation.get("style_profile") or {}
            chosen = explanation.get("chosen_breakdown") or {}
            rows.append(
                {
                    "case_id": case.get("case_id"),
                    "category": case.get("category"),
                    "style_profile": profile,
                    "chosen_move": explanation.get("chosen_move"),
                    "chosen_reason": explanation.get("chosen_reason"),
                    "candidate_moves": style.get("candidate_moves") or [],
                    "base_score": chosen.get("base_score"),
                    "style_bonus": chosen.get("style_bonus"),
                    "final_score": chosen.get("final_combined_score"),
                    "rejected_style_moves": style.get("rejected_style_moves") or [],
                    "rejection_reason": "; ".join(
                        sorted(
                            {
                                str(item.get("rejection_reason") or "")
                                for item in (style.get("rejected_style_moves") or [])
                                if str(item.get("rejection_reason") or "")
                            }
                        )
                    ),
                    "applied": bool(style.get("applied")),
                    "selected_before_style": style.get("selected_move_before_style"),
                    "selected_after_style": style.get("selected_move_after_style"),
                    "cp_threshold": style.get("cp_threshold"),
                }
            )
        profiles[profile] = rows
    balanced_rows = profiles.get("balanced") or []
    style_rows = (profiles.get("attacking") or []) + (profiles.get("defensive") or [])
    unsafe_overrides = []
    for row in style_rows:
        if not bool(row.get("applied")):
            continue
        selected = next(
            (candidate for candidate in row.get("candidate_moves") or [] if candidate.get("move") == row.get("chosen_move")),
            {},
        )
        if float(selected.get("cp_delta_vs_best") or 0.0) < -100.0:
            unsafe_overrides.append(row)
    return {
        "supported": True,
        "seed": int(seed),
        "promotion_gate_profile": "balanced",
        "balanced_gate_unaffected_by_style": True,
        "profiles": profiles,
        "style_override_count": sum(1 for row in style_rows if row.get("applied")),
        "rejected_style_move_count": sum(len(row.get("rejected_style_moves") or []) for row in style_rows),
        "unsafe_override_count": len(unsafe_overrides),
        "unsafe_overrides": unsafe_overrides,
        "passed": len(balanced_rows) > 0 and not unsafe_overrides,
    }


def _clone_deterministic_snapshot(snapshot: dict, *, model_label: str) -> dict:
    cloned = deepcopy(snapshot)
    cloned["model_label"] = model_label
    return cloned


def _compact_sanity_probe_for_summary(probe: dict) -> dict:
    if not probe:
        return {}
    compact = {
        key: probe.get(key)
        for key in (
            "supported",
            "source",
            "case",
            "exact_fen_pass",
            "seen_variant_count",
            "seen_variant_top1_hits",
            "seen_variant_pass_rate",
            "unseen_variant_count",
            "unseen_variant_top1_hits",
            "unseen_variant_pass_rate",
            "clean_unseen_count",
            "clean_unseen_final_pass_rate",
            "clean_unseen_raw_policy_pass_rate",
            "clean_held_out_count",
            "clean_held_out_final_pass_rate",
            "clean_held_out_raw_policy_pass_rate",
            "hard_clean_held_out_count",
            "hard_clean_held_out_pass_rate",
            "clean_held_out_by_difficulty",
            "clean_held_out_by_semantic",
            "clean_heldout_by_semantic",
            "balanced_gate_semantic_set",
            "excluded_style_semantics",
            "balanced_clean_held_out_count",
            "balanced_clean_held_out_pass_rate",
            "balanced_clean_heldout_by_semantic",
            "development_multi_good_credit",
            "attacking_style_audit",
            "central_flank_failed_case_analysis",
            "flank_label_audit",
            "flank_label_audit_v2",
            "flank_reason_distribution",
            "flank_difficulty_performance",
            "contextual_flank_performance",
            "contextual_flank_pass_rate",
            "bad_random_flank_push_confusion",
            "context_feature_importance",
            "central_vs_flank_boundary",
            "failed_by_semantic_top3",
            "overall_clean_heldout_pass_rate",
            "semantic_confusion_matrix",
            "clean_held_out_pool_sufficient",
            "questionable_held_out_count",
            "questionable_performance",
            "invalid_label_count",
            "easy_unseen_pass_rate",
            "medium_unseen_pass_rate",
            "hard_unseen_pass_rate",
            "variant_difficulty_scores",
            "raw_policy_generalization_rate",
            "final_decision_generalization_rate",
            "raw_policy_unseen_generalization_rate",
            "final_decision_unseen_generalization_rate",
            "variant_count",
            "variant_top1_hits",
            "variant_top1_rate",
            "memorized_exact_fen",
            "generalized_to_variants",
            "partial_seen_variants_only",
            "failed_to_learn",
            "blocked_by_search_or_static_eval",
            "result_kind",
            "learning_signal",
            "learning_signal_reason",
            "human_explanation",
            "not_learning_success_sources",
        )
        if key in probe
    }
    compact["before_exact"] = probe.get("before_exact") or {}
    compact["after_exact"] = probe.get("after_exact") or {}
    compact["raw_policy_learning"] = probe.get("raw_policy_learning") or {}
    final = dict(probe.get("final_decision_learning") or {})
    for key in ("decision_breakdown_before", "decision_breakdown_after"):
        if isinstance(final.get(key), dict):
            breakdown = final[key]
            final[key] = {
                "chosen_move": breakdown.get("chosen_move"),
                "chosen_reason": breakdown.get("chosen_reason"),
                "policy_override": breakdown.get("policy_override"),
                "watched_moves": (breakdown.get("watched_moves") or [])[:3],
            }
    compact["final_decision_learning"] = final
    prior = probe.get("prior_learned_case_retention") or {}
    compact["prior_learned_case_retention"] = {
        "supported": prior.get("supported"),
        "checked_count": prior.get("checked_count"),
        "retained_count": prior.get("retained_count"),
        "failed_count": prior.get("failed_count"),
        "learning_signal": prior.get("learning_signal"),
        "reason": prior.get("reason"),
        "failures": (prior.get("failures") or [])[:3],
    }
    debug = probe.get("feature_generalization_debug") or {}
    compact["feature_generalization_debug"] = {
        "board_embedding_similarity": debug.get("board_embedding_similarity") or {},
        "split": debug.get("split") or {},
        "expected_move_rank_across_variants": (debug.get("expected_move_rank_across_variants") or [])[:12],
        "final_decision_blockers": (debug.get("final_decision_blockers") or [])[:6],
        "failed_unseen_cases": (debug.get("failed_unseen_cases") or [])[:8],
        "failed_feature_groups": (debug.get("failed_feature_groups") or [])[:8],
        "embedding_similarity": debug.get("embedding_similarity") or {},
        "embedding_similarity_delta_by_group": debug.get("embedding_similarity_delta_by_group") or {},
        "expected_vs_hard_negative_margin": debug.get("expected_vs_hard_negative_margin") or {},
        "early_checkpoint_failure_analysis": debug.get("early_checkpoint_failure_analysis") or {},
        "label_quality": debug.get("label_quality") or {},
        "held_out_label_quality": debug.get("held_out_label_quality") or {},
        "held_out_pool": debug.get("held_out_pool") or {},
        "label_quality_summary": debug.get("label_quality_summary") or {},
        "excluded_from_gate_cases": (debug.get("excluded_from_gate_cases") or [])[:8],
        "clean_vs_questionable_performance": debug.get("clean_vs_questionable_performance") or {},
        "central_flank_failed_case_analysis": debug.get("central_flank_failed_case_analysis") or ((debug.get("clean_vs_questionable_performance") or {}).get("central_flank_failed_case_analysis") or {}),
        "flank_label_audit": debug.get("flank_label_audit") or {},
        "flank_label_audit_v2": debug.get("flank_label_audit_v2") or debug.get("flank_label_audit") or {},
        "flank_reason_distribution": debug.get("flank_reason_distribution") or {},
        "flank_difficulty_performance": debug.get("flank_difficulty_performance") or {},
        "contextual_flank_performance": debug.get("contextual_flank_performance") or {},
        "contextual_flank_pass_rate": debug.get("contextual_flank_pass_rate"),
        "bad_random_flank_push_confusion": debug.get("bad_random_flank_push_confusion") or {},
        "context_feature_importance": debug.get("context_feature_importance") or [],
        "central_vs_flank_boundary": debug.get("central_vs_flank_boundary") or {},
        "semantic_analysis": debug.get("semantic_analysis") or {},
        "failed_clean_cases_top3": debug.get("failed_clean_cases_top3") or [],
    }
    return compact


def _compact_checkpoint_for_summary(checkpoint: dict) -> dict:
    compact = deepcopy(checkpoint)
    if "sanity_learning_probe" in compact:
        compact["sanity_learning_probe"] = _compact_sanity_probe_for_summary(compact.get("sanity_learning_probe") or {})
    training = compact.get("sanity_variant_training")
    if isinstance(training, dict):
        training["rows"] = []
        curriculum = training.get("curriculum")
        if isinstance(curriculum, dict):
            training["curriculum"] = {
                "train_count": len(curriculum.get("train") or []),
                "validation_count": len(curriculum.get("validation") or []),
                "held_out_count": len(curriculum.get("held_out") or []),
                "seen_count": len(curriculum.get("seen") or []),
                "unseen_count": len(curriculum.get("unseen") or []),
                "by_difficulty": {
                    key: {
                        "train_count": len((value or {}).get("train") or []),
                        "validation_count": len((value or {}).get("validation") or []),
                        "held_out_count": len((value or {}).get("held_out") or []),
                        "seen_count": len((value or {}).get("seen") or []),
                        "unseen_count": len((value or {}).get("unseen") or []),
                    }
                    for key, value in (curriculum.get("by_difficulty") or {}).items()
                },
            }
    return compact


def _evaluate_fixed_probe_positions(engine_alias: str, model_path: Path) -> dict:
    if engine_alias not in {"exp1", "exp3", "exp4", "exp5"}:
        return {"supported": False, "positions": [], "move_change_count": 0}
    rows = []
    for probe in FIXED_PROBE_POSITIONS:
        board_state = {"__fen__": str(probe["fen"])}
        side = str(probe["side"])
        started = time.perf_counter()
        move = _choose_engine_move_for_eval(engine_alias, board_state, side, model_path)
        think_ms = round((time.perf_counter() - started) * 1000.0, 3)
        chosen_move = f"{move['from']}{move['to']}{move.get('promotion') or ''}".lower() if move else ""
        legal = False
        score = None
        board_after = board_state
        if move:
            try:
                board_after = validate_move(board_state, side, move["from"], move["to"], move.get("promotion"))["board"]
                legal = True
                score = _probe_position_score(board_after, opponent(side))
            except Exception:
                legal = False
        rows.append(
            {
                "position_id": str(probe["id"]),
                "fen": str(probe["fen"]),
                "side": side,
                "chosen_move": chosen_move,
                "score": score,
                "legal": legal,
                "think_ms": think_ms,
            }
        )
    return {
        "supported": True,
        "positions": rows,
    }


def _evaluate_retention_probe(engine_alias: str, before_model_path: Path, after_model_path: Path, samples: list[dict]) -> dict:
    if not samples:
        return {"supported": False, "reason": "no_old_samples", "counted_as_game": False}
    sample = samples[0]
    board_state = {"__fen__": str(sample.get("fen") or "")}
    side = str(sample.get("side") or "white")
    expected_move = str(sample.get("move_uci") or "").lower()
    before_move = _choose_engine_move_for_eval(engine_alias, board_state, side, before_model_path)
    after_move = _choose_engine_move_for_eval(engine_alias, board_state, side, after_model_path)
    before_uci = _move_uci(before_move or {})
    after_uci = _move_uci(after_move or {})
    before_matches = before_uci == expected_move
    after_matches = after_uci == expected_move
    return {
        "supported": True,
        "counted_as_game": False,
        "source": "old_trusted_engine_move",
        "game_index": int(sample.get("game_index") or 0),
        "game_id": int(sample.get("game_id") or 0),
        "game_label": str(sample.get("game_label") or ""),
        "ply": int(sample.get("ply") or 0),
        "fen": str(sample.get("fen") or ""),
        "side": side,
        "expected_move": expected_move,
        "before_move": before_uci,
        "after_move": after_uci,
        "before_matches_expected": before_matches,
        "after_matches_expected": after_matches,
        "model_response_changed": before_uci != after_uci,
        "learning_signal": bool(after_matches or before_uci != after_uci),
    }


def _select_mistake_probe_sample(engine_alias: str, model_path: Path, samples: list[dict]) -> dict | None:
    mistake_samples = [sample for sample in samples if str(sample.get("category") or "") == "mistake_retention"]
    for sample in mistake_samples:
        board_state = {"__fen__": str(sample.get("fen") or "")}
        side = str(sample.get("side") or "white")
        expected_move = str(sample.get("move_uci") or "").lower()
        move = _choose_engine_move_for_eval(engine_alias, board_state, side, model_path)
        before_uci = _move_uci(move or {})
        if before_uci != expected_move:
            selected = dict(sample)
            selected["before_move"] = before_uci
            return selected
    return None


def _evaluate_mistake_retention_probe(engine_alias: str, before_model_path: Path, after_model_path: Path, samples: list[dict]) -> dict:
    mistake_samples = [sample for sample in samples if str(sample.get("category") or "") == "mistake_retention"]
    if not mistake_samples:
        return {
            "supported": False,
            "reason": "no_mistake_retention_samples",
            "counted_as_game": False,
            "expected_move": "",
            "before_move": "",
            "after_move": "",
            "avoided_old_mistake": False,
            "avoided_same_error": False,
            "matched_expected": False,
            "result_kind": "fail",
            "learning_signal": False,
            "learning_signal_reason": "no old trusted mistake-retention sample was available for a probe",
            "human_explanation": "目前沒有足夠證據證明 retrain 改善了該錯誤，因為沒有可重測的舊題目。",
        }

    def evaluate_sample(sample: dict) -> dict:
        board_state = {"__fen__": str(sample.get("fen") or "")}
        side = str(sample.get("side") or "white")
        expected_move = str(sample.get("move_uci") or "").lower()
        before_move = _choose_engine_move_for_eval(engine_alias, board_state, side, before_model_path)
        after_move = _choose_engine_move_for_eval(engine_alias, board_state, side, after_model_path)
        before_uci = _move_uci(before_move or {})
        after_uci = _move_uci(after_move or {})
        retained_expected = before_uci == expected_move and after_uci == expected_move
        regressed_from_expected = before_uci == expected_move and after_uci != expected_move
        probe_case_id = f"game:{int(sample.get('game_id') or 0)}:ply:{int(sample.get('ply') or 0)}:{expected_move}"
        return {
            "supported": True,
            "reason": "retained_expected_move" if retained_expected else "regressed_from_expected_move" if regressed_from_expected else "prior_mistake_sample",
            "counted_as_game": False,
            "source": "old_trusted_engine_move_mistake",
            "probe_case_id": probe_case_id,
            "game_index": int(sample.get("game_index") or 0),
            "game_id": int(sample.get("game_id") or 0),
            "game_label": str(sample.get("game_label") or ""),
            "ply": int(sample.get("ply") or 0),
            "fen": str(sample.get("fen") or ""),
            "side": side,
            "expected_move": expected_move,
            "before_move": before_uci,
            "after_move": after_uci,
            "before_failed": before_uci != expected_move,
            "after_fixed": after_uci == expected_move,
            "avoided_old_mistake": bool(before_uci != expected_move and after_uci != before_uci),
            "avoided_same_error": bool(before_uci != expected_move and after_uci != before_uci),
            "matched_expected": after_uci == expected_move,
            "result_kind": "retained_expected" if retained_expected else "regressed_from_expected" if regressed_from_expected else "not_prior_mistake",
            "model_response_changed": before_uci != after_uci,
            "sample_count": len(mistake_samples),
            "learning_signal": bool(retained_expected),
            "learning_signal_reason": (
                "before model had already learned the expected move and after model retained it"
                if retained_expected
                else "before model had learned the expected move but after model regressed"
                if regressed_from_expected
                else "no prior mistake was found, so this probe cannot prove that retrain corrected a known error"
            ),
            "human_explanation": (
                "舊錯題在前一 checkpoint 已被修正，這次 retrain 後仍保留正解。"
                if retained_expected
                else "模型曾經修正此錯題，但這次 retrain 後退步。"
                if regressed_from_expected
                else "目前沒有足夠證據證明 retrain 改善了該錯誤，因為 before model 沒有在可選舊題目上犯錯。"
            ),
        }

    evaluated = [evaluate_sample(sample) for sample in mistake_samples]
    corrected = [row for row in evaluated if row.get("before_failed") and row.get("matched_expected")]
    if corrected:
        row = corrected[0]
        row.update(
            {
                "result_kind": "matched_expected",
                "learning_signal": True,
                "learning_signal_reason": "before model failed the old mistake case and after model selected the expected move",
                "human_explanation": "舊錯題已被修正，這提供 retrain 改善該錯誤的直接證據。",
                "probe_policy": "corrected_prior_mistake",
                "unfixed_new_mistake_count": sum(1 for item in evaluated if item.get("before_failed") and not item.get("matched_expected")),
            }
        )
        return row
    retained = [row for row in evaluated if not row.get("before_failed") and row.get("matched_expected")]
    if retained:
        row = retained[0]
        row.update(
            {
                "result_kind": "retained_expected",
                "learning_signal": True,
                "learning_signal_reason": "no newly corrected mistake was found, but a previously learned mistake-retention case stayed correct",
                "human_explanation": "這次 retrain 沒有新增修正的錯題，但已學會的舊題仍保留正解，符合 retention 檢查。",
                "probe_policy": "retained_previously_learned_mistake",
                "unfixed_new_mistake_count": sum(1 for item in evaluated if item.get("before_failed") and not item.get("matched_expected")),
                "unfixed_new_mistakes": [
                    {
                        "probe_case_id": item.get("probe_case_id"),
                        "expected_move": item.get("expected_move"),
                        "before_move": item.get("before_move"),
                        "after_move": item.get("after_move"),
                        "result_kind": item.get("result_kind"),
                    }
                    for item in evaluated
                    if item.get("before_failed") and not item.get("matched_expected")
                ][:5],
            }
        )
        return row

    row = next((item for item in evaluated if item.get("before_failed")), evaluated[0])
    before_failed = bool(row.get("before_failed"))
    avoided_old_mistake = bool(row.get("avoided_old_mistake"))
    if before_failed and avoided_old_mistake:
        row["result_kind"] = "avoided_old_but_not_expected"
        row["learning_signal_reason"] = "after model avoided the same wrong move but still did not select the expected move"
        row["human_explanation"] = "模型避開了同一個錯誤，但尚未走到預期正解，因此不能視為學習成功。"
    elif before_failed:
        row["result_kind"] = "repeated_old_mistake"
        row["learning_signal_reason"] = "after model repeated the same wrong move"
        row["human_explanation"] = "目前沒有足夠證據證明 retrain 改善了該錯誤，因為 after model 仍重複同一錯誤。"
    row["learning_signal"] = False
    row["probe_policy"] = "unfixed_prior_mistake"
    return row


def _attempt_mistake_retention_repair(
    *,
    engine_alias: str,
    before_model_path: Path,
    candidate_model_path: Path,
    candidate_replay_path: Path,
    checkpoint_dir: Path,
    initial_probe: dict,
    evaluation_samples: list[dict],
    max_seconds: int,
) -> dict:
    started = time.perf_counter()
    if initial_probe.get("result_kind") != "repeated_old_mistake":
        return {
            "supported": True,
            "applied": False,
            "reason": "initial_probe_not_repeated_old_mistake",
            "initial_probe": initial_probe,
            "duration_seconds": round(time.perf_counter() - started, 3),
        }
    fen = str(initial_probe.get("fen") or "")
    side = str(initial_probe.get("side") or "")
    expected = str(initial_probe.get("expected_move") or "").lower()
    old_mistake = str(initial_probe.get("before_move") or "").lower()
    if not fen or side not in {"white", "black"} or not expected:
        return {
            "supported": False,
            "applied": False,
            "reason": "missing_probe_fen_side_or_expected_move",
            "initial_probe": initial_probe,
            "duration_seconds": round(time.perf_counter() - started, 3),
        }
    hard_negatives = [move for move in [old_mistake, str(initial_probe.get("after_move") or "").lower()] if move and move != expected]
    semantic = _move_semantic_class(fen, side, expected)
    rehearsal_rows = [
        {
            "fen": fen,
            "side": side,
            "move_uci": expected,
            "target": 1.0,
            "weight": 5.0,
            "source": "exp33_mistake_retention_stronger_rehearsal",
            "category": "mistake_retention",
            "semantic_class": semantic,
            "expected_semantic": semantic,
            "hard_negatives": hard_negatives,
            "invariance_group_id": f"mistake_retention:{initial_probe.get('probe_case_id')}",
        }
        for _ in range(12)
    ]
    rehearsal_path = checkpoint_dir / "mistake_retention_rehearsal.jsonl"
    _jsonl_dump(rehearsal_path, rehearsal_rows)
    if engine_alias == "exp3":
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp3_dataset_train.py"),
            "--input-jsonl",
            str(rehearsal_path),
            "--model-path",
            str(candidate_model_path),
            "--replay-path",
            str(candidate_replay_path),
            "--max-samples",
            "24",
        ]
    elif engine_alias == "exp4":
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp4_dataset_train.py"),
            "--input-jsonl",
            str(rehearsal_path),
            "--model-path",
            str(candidate_model_path),
            "--max-samples",
            "24",
        ]
    else:
        return {
            "supported": False,
            "applied": False,
            "reason": f"mistake retention repair does not support {engine_alias}",
            "initial_probe": initial_probe,
            "duration_seconds": round(time.perf_counter() - started, 3),
        }
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=max(5, min(55, int(max_seconds))),
        )
        trainer_result = {
            "command": cmd,
            "returncode": int(proc.returncode),
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "ok": proc.returncode == 0,
        }
        if proc.returncode == 0:
            try:
                parsed = json.loads(proc.stdout)
                if isinstance(parsed, dict):
                    trainer_result.update(parsed)
            except Exception:
                trainer_result["stdout_parse_error"] = True
    except subprocess.TimeoutExpired as exc:
        trainer_result = {
            "command": cmd,
            "returncode": -1,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "ok": False,
            "timeout": True,
        }
    repaired_probe = _evaluate_mistake_retention_probe(engine_alias, before_model_path, candidate_model_path, evaluation_samples)
    return {
        "supported": True,
        "applied": True,
        "source": "exp33_mistake_retention_stronger_rehearsal",
        "initial_probe": initial_probe,
        "before_move": initial_probe.get("before_move"),
        "after_move": initial_probe.get("after_move"),
        "expected_move": expected,
        "old_mistake": old_mistake,
        "repeated_old_mistake": initial_probe.get("result_kind") == "repeated_old_mistake",
        "stronger_repair_applied": True,
        "mistake_retention_anchor_weight": 5.0,
        "rehearsal_rows": len(rehearsal_rows),
        "rehearsal_path": str(rehearsal_path),
        "rollback_or_rehearsal_applied": True,
        "rehearsal_applied": True,
        "rollback_applied": False,
        "trainer_result": trainer_result,
        "cp20_mistake_retention_after_repair": repaired_probe,
        "after_rehearsal_move": repaired_probe.get("after_move"),
        "repair_success": bool(repaired_probe.get("learning_signal") and repaired_probe.get("matched_expected")),
        "duration_seconds": round(time.perf_counter() - started, 3),
    }


def _sanity_learning_cases_from_samples(samples: list[dict]) -> list[dict]:
    cases = []
    for sample in samples or []:
        if str(sample.get("category") or "") != "mistake_retention":
            continue
        expected = str(sample.get("move_uci") or "").lower()
        fen = str(sample.get("fen") or "").strip()
        side = str(sample.get("side") or "").strip().lower()
        if fen and expected and side:
            cases.append(
                {
                    "case_id": f"sanity:{int(sample.get('game_id') or 0)}:ply:{int(sample.get('ply') or 0)}:{expected}",
                    "fen": fen,
                    "side": side,
                    "expected_move": expected,
                    "expected_semantic": _move_semantic_class(fen, side, expected),
                    "board_semantics_features": _board_semantics_features(fen, side),
                    "source_game_id": int(sample.get("game_id") or 0),
                    "source_ply": int(sample.get("ply") or 0),
                    "source_label": str(sample.get("game_label") or ""),
                }
            )
    return cases


def _sanity_learning_case_from_samples(samples: list[dict]) -> dict | None:
    cases = _sanity_learning_cases_from_samples(samples)
    return cases[0] if cases else None


def _normalized_fen_hash(fen: str) -> str:
    try:
        board = chess.Board(str(fen or ""))
        normalized = f"{board.board_fen()} {board.turn} {board.castling_rights} {board.ep_square}"
    except Exception:
        normalized = str(fen or "")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _quiet_non_expected_moves(board: chess.Board, expected_move: chess.Move) -> list[chess.Move]:
    return [
        move
        for move in sorted(board.legal_moves, key=lambda item: item.uci())
        if move != expected_move and not board.is_capture(move) and move.promotion is None
    ]


def _build_sanity_variant_board(
    base_board: chess.Board,
    *,
    expected_move: chess.Move,
    first_decoy: chess.Move,
    difficulty: str,
    candidate_index: int,
) -> tuple[chess.Board | None, list[str]]:
    pair_count = int(SANITY_VARIANT_DIFFICULTY_PAIRS.get(str(difficulty), 1))
    variant_board = base_board.copy(stack=False)
    variation_moves: list[str] = []
    for pair_index in range(pair_count):
        candidates = _quiet_non_expected_moves(variant_board, expected_move)
        if not candidates:
            return None, []
        decoy = first_decoy if pair_index == 0 else candidates[(candidate_index + pair_index * 3) % len(candidates)]
        if decoy not in variant_board.legal_moves:
            return None, []
        variant_board.push(decoy)
        variation_moves.append(decoy.uci())
        replies = _quiet_non_expected_moves(variant_board, expected_move)
        if not replies:
            return None, []
        reply = replies[(candidate_index + pair_index * 5) % len(replies)]
        variant_board.push(reply)
        variation_moves.append(reply.uci())
        if variant_board.turn != base_board.turn or expected_move not in variant_board.legal_moves:
            return None, []
    return variant_board, variation_moves


def _board_embedding_similarity(fen_a: str, fen_b: str) -> float:
    try:
        board_a = chess.Board(str(fen_a or ""))
        board_b = chess.Board(str(fen_b or ""))
    except Exception:
        return 0.0
    matches = 0
    total = 64
    for square in chess.SQUARES:
        if board_a.piece_at(square) == board_b.piece_at(square):
            matches += 1
    if board_a.turn == board_b.turn:
        matches += 1
    total += 1
    return round(matches / max(1, total), 4)


def _sanity_learning_variants(
    case: dict,
    *,
    limit: int = SANITY_LEARNING_VARIANT_COUNT,
    offset: int = 0,
    split: str = "seen",
    difficulty: str = "easy",
) -> list[dict]:
    expected = str(case.get("expected_move") or "").lower()
    try:
        base_board = chess.Board(str(case.get("fen") or ""))
        expected_move = chess.Move.from_uci(expected)
    except Exception:
        return []
    if expected_move not in base_board.legal_moves:
        return []
    variants = []
    seen_hashes: set[str] = set()
    legal_quiet = _quiet_non_expected_moves(base_board, expected_move)
    max_attempts = max(len(legal_quiet), int(limit) + int(offset)) * 8
    for attempt_index in range(1, max_attempts + 1):
        if attempt_index <= int(offset):
            continue
        decoy_move = legal_quiet[(attempt_index - 1) % len(legal_quiet)]
        variant_board, variation_moves = _build_sanity_variant_board(
            base_board,
            expected_move=expected_move,
            first_decoy=decoy_move,
            difficulty=difficulty,
            candidate_index=attempt_index,
        )
        if variant_board is None or expected_move not in variant_board.legal_moves:
            continue
        normalized_hash = _normalized_fen_hash(variant_board.fen())
        if normalized_hash in seen_hashes:
            continue
        seen_hashes.add(normalized_hash)
        variant_index = len(variants) + 1
        variant_id = f"{case.get('case_id')}:{split}_{difficulty}_variant:{variant_index}"
        variants.append(
            {
                "case_id": variant_id,
                "variant_id": variant_id,
                "variant_split": split,
                "variant_difficulty": difficulty,
                "fen": variant_board.fen(),
                "normalized_fen_hash": normalized_hash,
                "board_embedding_similarity": _board_embedding_similarity(str(case.get("fen") or ""), variant_board.fen()),
                "side": str(case.get("side") or ""),
                "expected_move": expected,
                "expected_semantic": _move_semantic_class_for_board(variant_board, expected),
                "board_semantics_features": _board_semantics_features(variant_board.fen(), str(case.get("side") or "")),
                "flank_context_features": _flank_context_features(variant_board.fen(), str(case.get("side") or "")),
                "flank_reason_tag": _flank_reason_tag_for_move(variant_board.fen(), str(case.get("side") or ""), expected),
                "variation_moves": variation_moves,
            }
        )
        if len(variants) >= int(limit):
            break
    return variants


def _legal_sanity_hard_negatives(fen: str, side: str, expected_move: str, *, old_move: str = "", limit: int = 5) -> list[str]:
    try:
        board = chess.Board(str(fen or ""))
        board.turn = chess.WHITE if str(side or "").lower() == "white" else chess.BLACK
        expected = chess.Move.from_uci(str(expected_move or "").lower())
    except Exception:
        return []
    candidates = [str(old_move or "").lower(), *SANITY_COMMON_HARD_NEGATIVES]
    hard_negatives: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        try:
            move = chess.Move.from_uci(str(item or "").strip().lower())
        except Exception:
            continue
        if move == expected or move not in board.legal_moves or move.uci() in seen:
            continue
        seen.add(move.uci())
        hard_negatives.append(move.uci())
    if len(hard_negatives) < 3:
        for move in sorted(board.legal_moves, key=lambda item: item.uci()):
            if move == expected or move.uci() in seen:
                continue
            hard_negatives.append(move.uci())
            seen.add(move.uci())
            if len(hard_negatives) >= 3:
                break
    return hard_negatives[: max(1, int(limit))]


def _move_semantic_class_for_board(board: chess.Board, move_uci: str) -> str:
    try:
        move = chess.Move.from_uci(str(move_uci or "").lower())
    except Exception:
        return "other"
    piece = board.piece_at(move.from_square)
    from_file = chess.square_file(move.from_square)
    to_file = chess.square_file(move.to_square)
    if piece and piece.piece_type == chess.PAWN:
        if from_file == chess.FILE_NAMES.index("e"):
            return "e_pawn_central_break"
        if from_file == chess.FILE_NAMES.index("d"):
            return "d_pawn_central_break"
        if from_file in {chess.FILE_NAMES.index("f"), chess.FILE_NAMES.index("g"), chess.FILE_NAMES.index("h")} or to_file in {chess.FILE_NAMES.index("g"), chess.FILE_NAMES.index("h")}:
            return "kingside_aggression"
        if from_file in {chess.FILE_NAMES.index("a"), chess.FILE_NAMES.index("b"), chess.FILE_NAMES.index("c")}:
            return "flank_pawn_push"
    if piece and piece.piece_type in {chess.KNIGHT, chess.BISHOP}:
        home_rank = 0 if piece.color == chess.WHITE else 7
        if chess.square_rank(move.from_square) == home_rank:
            return "development_move"
    if to_file in {chess.FILE_NAMES.index("g"), chess.FILE_NAMES.index("h")}:
        return "kingside_aggression"
    return "other"


def _move_semantic_class(fen: str, side: str, move_uci: str) -> str:
    try:
        board = chess.Board(str(fen or ""))
        board.turn = chess.WHITE if str(side or "").lower() == "white" else chess.BLACK
    except Exception:
        return "other"
    return _move_semantic_class_for_board(board, move_uci)


def _board_semantics_features(fen: str, side: str) -> dict:
    try:
        board = chess.Board(str(fen or ""))
        board.turn = chess.WHITE if str(side or "").lower() == "white" else chess.BLACK
    except Exception:
        return {"supported": False, "reason": "invalid fen"}
    center = [chess.D4, chess.E4, chess.D5, chess.E5]
    own = board.turn
    opp = not own
    own_center_pawns = 0
    opp_center_pawns = 0
    for square in center:
        piece = board.piece_at(square)
        if piece and piece.piece_type == chess.PAWN:
            if piece.color == own:
                own_center_pawns += 1
            else:
                opp_center_pawns += 1
    own_attack = sum(1 for square in center if board.is_attacked_by(own, square))
    opp_attack = sum(1 for square in center if board.is_attacked_by(opp, square))
    minor_home = 0
    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if not piece or piece.color != own or piece.piece_type not in {chess.KNIGHT, chess.BISHOP}:
            continue
        home_rank = 0 if own == chess.WHITE else 7
        if chess.square_rank(square) == home_rank:
            minor_home += 1
    pawns_on_central_files = 0
    for file_index in [2, 3, 4, 5]:
        for rank in range(8):
            piece = board.piece_at(chess.square(file_index, rank))
            if piece and piece.piece_type == chess.PAWN:
                pawns_on_central_files += 1
    center_state = "closed" if pawns_on_central_files >= 6 else "semi_open" if pawns_on_central_files >= 3 else "open"
    king_square = board.king(own)
    king_attack_pressure = 0
    if king_square is not None:
        king_zone = [king_square]
        for delta_file in [-1, 0, 1]:
            for delta_rank in [-1, 0, 1]:
                file_index = chess.square_file(king_square) + delta_file
                rank_index = chess.square_rank(king_square) + delta_rank
                if 0 <= file_index < 8 and 0 <= rank_index < 8:
                    king_zone.append(chess.square(file_index, rank_index))
        king_attack_pressure = sum(1 for square in set(king_zone) if board.is_attacked_by(opp, square))
    return {
        "supported": True,
        "central_control": {
            "own_attacks": own_attack,
            "opponent_attacks": opp_attack,
            "delta": own_attack - opp_attack,
        },
        "pawn_structure": {
            "own_center_pawns": own_center_pawns,
            "opponent_center_pawns": opp_center_pawns,
            "center_state": center_state,
        },
        "king_safety": {
            "in_check": board.is_check(),
            "king_attack_pressure": king_attack_pressure,
        },
        "development_state": {
            "undeveloped_minor_pieces": minor_home,
        },
        "side_to_move_pressure": {
            "legal_moves": board.legal_moves.count(),
            "center_control_delta": own_attack - opp_attack,
        },
    }


def _castled_side(board: chess.Board, color: bool) -> str:
    king_square = board.king(color)
    if king_square is None:
        return "unknown"
    file_index = chess.square_file(king_square)
    rank_index = chess.square_rank(king_square)
    home_rank = 0 if color == chess.WHITE else 7
    if rank_index != home_rank:
        return "moved"
    if file_index >= chess.FILE_NAMES.index("g"):
        return "kingside"
    if file_index <= chess.FILE_NAMES.index("c"):
        return "queenside"
    return "uncastled"


def _flank_context_features(fen: str, side: str) -> dict:
    try:
        board = chess.Board(str(fen or ""))
        board.turn = chess.WHITE if str(side or "").lower() == "white" else chess.BLACK
    except Exception:
        return {"supported": False, "reason": "invalid fen"}
    base = _board_semantics_features(board.fen(), "white" if board.turn == chess.WHITE else "black")
    own = board.turn
    opp = not own
    center_state = ((base.get("pawn_structure") or {}).get("center_state") or "unknown")
    central_squares = [chess.D4, chess.E4, chess.D5, chess.E5]
    central_pawns = [
        square for square in central_squares
        if (board.piece_at(square) and board.piece_at(square).piece_type == chess.PAWN)
    ]
    central_tension = sum(
        1 for square in central_pawns
        if board.is_attacked_by(own, square) or board.is_attacked_by(opp, square)
    )

    def flank_space(color: bool, files: set[int]) -> int:
        score = 0
        for square in chess.SQUARES:
            piece = board.piece_at(square)
            if not piece or piece.color != color or piece.piece_type != chess.PAWN:
                continue
            if chess.square_file(square) not in files:
                continue
            rank = chess.square_rank(square)
            score += rank if color == chess.WHITE else 7 - rank
        return score

    queenside_files = {0, 1, 2}
    kingside_files = {5, 6, 7}
    own_queen_space = flank_space(own, queenside_files)
    opp_queen_space = flank_space(opp, queenside_files)
    own_king_space = flank_space(own, kingside_files)
    opp_king_space = flank_space(opp, kingside_files)
    wing_space_advantage = {
        "queenside": own_queen_space - opp_queen_space,
        "kingside": own_king_space - opp_king_space,
    }

    own_pawns = [
        square for square in chess.SQUARES
        if (board.piece_at(square) and board.piece_at(square).color == own and board.piece_at(square).piece_type == chess.PAWN)
    ]
    pawn_chain_direction = "balanced"
    queenside_pawns = sum(1 for square in own_pawns if chess.square_file(square) <= 2)
    kingside_pawns = sum(1 for square in own_pawns if chess.square_file(square) >= 5)
    if queenside_pawns > kingside_pawns + 1:
        pawn_chain_direction = "queenside"
    elif kingside_pawns > queenside_pawns + 1:
        pawn_chain_direction = "kingside"

    attack_lane_availability = {
        "a_file_open": not any(board.piece_at(chess.square(chess.FILE_NAMES.index("a"), rank)) for rank in range(8)),
        "b_file_open": not any(board.piece_at(chess.square(chess.FILE_NAMES.index("b"), rank)) for rank in range(8)),
        "c_file_open_or_tension": bool(
            not any(board.piece_at(chess.square(chess.FILE_NAMES.index("c"), rank)) for rank in range(8))
            or central_tension > 0
        ),
        "g_file_open": not any(board.piece_at(chess.square(chess.FILE_NAMES.index("g"), rank)) for rank in range(8)),
        "h_file_open": not any(board.piece_at(chess.square(chess.FILE_NAMES.index("h"), rank)) for rank in range(8)),
    }
    own_castle = _castled_side(board, own)
    opp_castle = _castled_side(board, opp)
    return {
        "supported": True,
        "open_closed_center": center_state,
        "king_castled_side": {
            "own": own_castle,
            "opponent": opp_castle,
        },
        "wing_space_advantage": wing_space_advantage,
        "pawn_chain_direction": pawn_chain_direction,
        "central_tension": central_tension,
        "attack_lane_availability": attack_lane_availability,
        "opposite_side_castling": bool(
            own_castle in {"kingside", "queenside"}
            and opp_castle in {"kingside", "queenside"}
            and own_castle != opp_castle
        ),
        "side_to_move_pressure": base.get("side_to_move_pressure") or {},
    }


def _flank_context_feature_vector(features: dict) -> list[float]:
    if not isinstance(features, dict) or not features.get("supported", True):
        return [0.0] * 8
    king = features.get("king_castled_side") or {}
    wing = features.get("wing_space_advantage") or {}
    lane = features.get("attack_lane_availability") or {}
    pressure = features.get("side_to_move_pressure") or {}
    center_state = str(features.get("open_closed_center") or "")
    own_castle = str(king.get("own") or "")
    queen_space = float(wing.get("queenside") or 0.0)
    king_space = float(wing.get("kingside") or 0.0)
    pressure_score = float(pressure.get("mobility_delta") or pressure.get("score") or 0.0) if isinstance(pressure, dict) else 0.0
    return [
        1.0 if center_state in {"closed", "locked"} else (0.4 if center_state == "semi_open" else -0.4),
        {"kingside": 1.0, "queenside": -1.0, "uncastled": 0.0, "moved": 0.0}.get(own_castle, 0.0),
        max(-1.0, min(1.0, queen_space / 4.0)),
        max(-1.0, min(1.0, king_space / 4.0)),
        {"queenside": -1.0, "kingside": 1.0, "balanced": 0.0}.get(str(features.get("pawn_chain_direction") or ""), 0.0),
        max(-1.0, min(1.0, float(features.get("central_tension") or 0.0) / 4.0)),
        1.0 if any(bool(lane.get(key)) for key in ("a_file_open", "b_file_open", "c_file_open_or_tension", "g_file_open", "h_file_open")) else -0.2,
        1.0 if bool(features.get("opposite_side_castling")) else max(-1.0, min(1.0, pressure_score / 12.0)),
    ]


def _flank_reason_tag_for_move(fen: str, side: str, move_uci: str) -> str:
    try:
        board = chess.Board(str(fen or ""))
        board.turn = chess.WHITE if str(side or "").lower() == "white" else chess.BLACK
        move = chess.Move.from_uci(str(move_uci or "").lower())
    except Exception:
        return "bad_random_flank_push"
    if move not in board.legal_moves or _move_semantic_class_for_board(board, move.uci()) != FLANK_REPAIR_SEMANTIC:
        return "bad_random_flank_push"
    features = _flank_context_features(board.fen(), "white" if board.turn == chess.WHITE else "black")
    from_file = chess.square_file(move.from_square)
    to_rank = chess.square_rank(move.to_square)
    is_queenside = from_file in {0, 1, 2}
    central_tension = int(features.get("central_tension") or 0)
    center_state = str(features.get("open_closed_center") or "")
    wing_space = features.get("wing_space_advantage") or {}
    lane = features.get("attack_lane_availability") or {}
    if features.get("opposite_side_castling") and from_file in {0, 1, 6, 7}:
        return "pawn_storm"
    if is_queenside and (central_tension > 0 or bool(lane.get("c_file_open_or_tension"))):
        return "prophylaxis" if board.turn == chess.BLACK and from_file == 2 else "expansion"
    if center_state in {"closed", "semi_open"} and is_queenside:
        return "space_gain"
    if not is_queenside and (abs(int(wing_space.get("kingside") or 0)) >= 2 or to_rank in {3, 4}):
        return "attack_prep"
    return "bad_random_flank_push"


def _flank_contextual_pass(expected_tag: str, final_tag: str, final_row: dict, raw_row: dict) -> bool:
    if expected_tag == "bad_random_flank_push":
        return False
    return bool(final_row.get("expected_is_top1") and raw_row.get("expected_is_raw_top1") and final_tag == expected_tag)


def _flank_reason_distribution(cases: list[dict]) -> dict:
    distribution = {tag: 0 for tag in FLANK_REASON_TAGS}
    for case in cases or []:
        semantic = str(case.get("expected_semantic") or case.get("semantic_class") or "")
        if semantic != FLANK_REPAIR_SEMANTIC:
            continue
        tag = str(case.get("flank_reason_tag") or case.get("reason_tag") or "")
        if tag not in distribution:
            tag = _flank_reason_tag_for_move(
                str(case.get("fen") or ""),
                str(case.get("side") or ""),
                str(case.get("expected_move") or ""),
            )
        distribution[tag] = int(distribution.get(tag) or 0) + 1
    return distribution


def _context_feature_importance(rows: list[dict]) -> list[dict]:
    counters: dict[str, dict[str, int]] = {}

    def add(feature: str, passed: bool) -> None:
        bucket = counters.setdefault(feature, {"passed": 0, "failed": 0})
        bucket["passed" if passed else "failed"] += 1

    for row in rows or []:
        features = row.get("flank_context_features") or {}
        passed = bool(row.get("contextual_pass"))
        add(f"open_closed_center={features.get('open_closed_center')}", passed)
        add(f"central_tension={'positive' if int(features.get('central_tension') or 0) > 0 else 'none'}", passed)
        add(f"pawn_chain_direction={features.get('pawn_chain_direction')}", passed)
        castle = features.get("king_castled_side") or {}
        add(f"own_castle={castle.get('own')}", passed)
        add(f"opponent_castle={castle.get('opponent')}", passed)
        add(f"opposite_side_castling={bool(features.get('opposite_side_castling'))}", passed)
        space = features.get("wing_space_advantage") or {}
        queenside_space = int(space.get("queenside") or 0)
        kingside_space = int(space.get("kingside") or 0)
        add(f"queenside_space={'positive' if queenside_space > 0 else 'negative' if queenside_space < 0 else 'neutral'}", passed)
        add(f"kingside_space={'positive' if kingside_space > 0 else 'negative' if kingside_space < 0 else 'neutral'}", passed)
        lanes = features.get("attack_lane_availability") or {}
        add(f"c_file_open_or_tension={bool(lanes.get('c_file_open_or_tension'))}", passed)

    ranked = []
    for feature, counts in counters.items():
        total = int(counts.get("passed") or 0) + int(counts.get("failed") or 0)
        ranked.append(
            {
                "feature": feature,
                "passed": int(counts.get("passed") or 0),
                "failed": int(counts.get("failed") or 0),
                "failure_rate": round(int(counts.get("failed") or 0) / max(1, total), 4),
            }
        )
    ranked.sort(key=lambda item: (-float(item.get("failure_rate") or 0.0), -int(item.get("failed") or 0), str(item.get("feature") or "")))
    return ranked[:12]


def _contextual_flank_performance_from_rows(cases: list[dict], rows: list[dict], *, label: str) -> dict:
    case_by_id = {str(case.get("case_id") or ""): case for case in cases or []}
    flank_rows = []
    reason_distribution = {tag: 0 for tag in FLANK_REASON_TAGS}
    non_flank_confusion = 0
    bad_random_confusion = 0
    bad_random_promoted = 0
    by_difficulty = {
        difficulty: {"count": 0, "contextual_hits": 0, "pass_rate": 0.0}
        for difficulty in ["easy", "medium", "hard"]
    }
    for row in rows or []:
        case_id = str(row.get("case_id") or "")
        case = case_by_id.get(case_id) or {}
        semantic = str(case.get("expected_semantic") or case.get("semantic_class") or row.get("semantic_class") or "")
        if semantic != FLANK_REPAIR_SEMANTIC:
            continue
        fen = str(case.get("fen") or row.get("fen") or "")
        side = str(case.get("side") or row.get("side") or "")
        expected = str(case.get("expected_move") or row.get("expected_move") or "").lower()
        final_top1 = str(row.get("final_top1") or row.get("top1") or "").lower()
        raw_top1 = str(row.get("raw_policy_top1") or "").lower()
        expected_tag = str(case.get("flank_reason_tag") or row.get("flank_reason_tag") or "")
        if expected_tag not in reason_distribution:
            expected_tag = _flank_reason_tag_for_move(fen, side, expected)
        final_semantic = _move_semantic_class(fen, side, final_top1) if final_top1 else "other"
        raw_semantic = _move_semantic_class(fen, side, raw_top1) if raw_top1 else "other"
        final_tag = _flank_reason_tag_for_move(fen, side, final_top1) if final_semantic == FLANK_REPAIR_SEMANTIC else "non_flank_move"
        raw_tag = _flank_reason_tag_for_move(fen, side, raw_top1) if raw_semantic == FLANK_REPAIR_SEMANTIC else "non_flank_move"
        final_pass = bool(row.get("final_pass") or row.get("balanced_pass") or row.get("expected_is_top1"))
        raw_pass = bool(row.get("raw_policy_pass") or row.get("raw_policy_balanced_pass") or row.get("expected_is_raw_top1"))
        pseudo_final = {"expected_is_top1": final_pass}
        pseudo_raw = {"expected_is_raw_top1": raw_pass}
        contextual_pass = _flank_contextual_pass(expected_tag, final_tag, pseudo_final, pseudo_raw)
        difficulty = str(case.get("variant_difficulty") or case.get("difficulty") or row.get("difficulty") or "unknown")
        if difficulty in by_difficulty:
            by_difficulty[difficulty]["count"] += 1
            by_difficulty[difficulty]["contextual_hits"] += 1 if contextual_pass else 0
        if expected_tag != "bad_random_flank_push" and final_tag == "non_flank_move":
            non_flank_confusion += 1
        if expected_tag != "bad_random_flank_push" and final_tag == "bad_random_flank_push":
            bad_random_confusion += 1
        if final_tag == "bad_random_flank_push" and final_top1:
            bad_random_promoted += 1
        reason_distribution[expected_tag] = int(reason_distribution.get(expected_tag) or 0) + 1
        features = case.get("flank_context_features") or row.get("flank_context_features") or _flank_context_features(fen, side)
        flank_rows.append(
            {
                "case_id": case_id,
                "difficulty": difficulty,
                "fen": fen,
                "expected_move": expected,
                "final_top1": final_top1,
                "raw_policy_top1": raw_top1,
                "expected_reason_tag": expected_tag,
                "final_reason_tag": final_tag,
                "raw_policy_reason_tag": raw_tag,
                "final_semantic": final_semantic,
                "raw_policy_semantic": raw_semantic,
                "contextual_pass": contextual_pass,
                "final_pass": final_pass,
                "raw_policy_pass": raw_pass,
                "flank_context_features": features,
            }
        )
    for difficulty, bucket in by_difficulty.items():
        bucket["pass_rate"] = round(int(bucket.get("contextual_hits") or 0) / max(1, int(bucket.get("count") or 0)), 4)
    count = len(flank_rows)
    hits = sum(1 for row in flank_rows if row.get("contextual_pass"))
    hard = by_difficulty.get("hard") or {}
    return {
        "supported": True,
        "source": "exp28_context_conditioned_flank_semantic_learning",
        "label": label,
        "count": count,
        "contextual_hits": hits,
        "contextual_flank_pass_rate": round(hits / max(1, count), 4),
        "hard_clean_count": int(hard.get("count") or 0),
        "hard_clean_contextual_hits": int(hard.get("contextual_hits") or 0),
        "hard_clean_contextual_pass_rate": hard.get("pass_rate"),
        "by_difficulty": by_difficulty,
        "flank_reason_distribution": reason_distribution,
        "bad_random_flank_push_confusion": {
            "count": bad_random_confusion,
            "promoted_count": bad_random_promoted,
            "rows": [row for row in flank_rows if row.get("final_reason_tag") == "bad_random_flank_push"][:8],
        },
        "non_flank_move_confusion": {
            "count": non_flank_confusion,
            "rows": [row for row in flank_rows if row.get("final_reason_tag") == "non_flank_move"][:8],
        },
        "context_feature_importance": _context_feature_importance(flank_rows),
        "cases": flank_rows,
    }


def _semantic_negative_moves(fen: str, side: str, expected_move: str, *, old_move: str = "", limit: int = 6) -> list[str]:
    try:
        board = chess.Board(str(fen or ""))
        board.turn = chess.WHITE if str(side or "").lower() == "white" else chess.BLACK
        expected = chess.Move.from_uci(str(expected_move or "").lower())
    except Exception:
        return []
    if expected not in board.legal_moves:
        return []
    expected_semantic = _move_semantic_class_for_board(board, expected.uci())
    preferred_by_expected = {
        "d_pawn_central_break": ["e_pawn_central_break", "flank_pawn_push", "kingside_aggression"],
        "e_pawn_central_break": ["d_pawn_central_break", "flank_pawn_push", "kingside_aggression"],
        "flank_pawn_push": ["e_pawn_central_break", "d_pawn_central_break", "kingside_aggression"],
        "kingside_aggression": ["e_pawn_central_break", "d_pawn_central_break", "flank_pawn_push"],
        "development_move": ["e_pawn_central_break", "d_pawn_central_break", "flank_pawn_push", "kingside_aggression"],
    }
    priority = preferred_by_expected.get(expected_semantic, ["e_pawn_central_break", "d_pawn_central_break", "kingside_aggression", "flank_pawn_push"])
    candidates = []
    for move in sorted(board.legal_moves, key=lambda item: item.uci()):
        if move == expected:
            continue
        semantic = _move_semantic_class_for_board(board, move.uci())
        if semantic in priority:
            candidates.append((priority.index(semantic), move.uci(), semantic))
    if old_move:
        try:
            old = chess.Move.from_uci(str(old_move).lower())
            if old in board.legal_moves and old != expected:
                old_semantic = _move_semantic_class_for_board(board, old.uci())
                candidates.append((-1, old.uci(), old_semantic))
        except Exception:
            pass
    seen: set[str] = set()
    result = []
    for _, move_uci, _semantic in sorted(candidates, key=lambda item: (item[0], item[1])):
        if move_uci in seen:
            continue
        seen.add(move_uci)
        result.append(move_uci)
        if len(result) >= limit:
            break
    return result


def _semantic_class_distribution(rows: list[dict], *, include_negatives: bool = True) -> dict:
    positive_counts = {semantic: 0 for semantic in SEMANTIC_CLASSES}
    negative_counts = {semantic: 0 for semantic in SEMANTIC_CLASSES}
    case_count = 0
    for row in rows or []:
        fen = str(row.get("fen") or "")
        side = str(row.get("side") or "")
        expected = str(row.get("expected_move") or row.get("move_uci") or "").lower()
        if not fen or not side or not expected:
            continue
        case_count += 1
        expected_semantic = str(row.get("expected_semantic") or _move_semantic_class(fen, side, expected))
        if expected_semantic not in positive_counts:
            positive_counts[expected_semantic] = 0
        positive_counts[expected_semantic] += 1
        if not include_negatives:
            continue
        negatives = list(row.get("semantic_hard_negatives") or row.get("hard_negatives") or [])
        if not negatives:
            negatives = _semantic_negative_moves(fen, side, expected, limit=6)
        for negative in negatives:
            semantic = _move_semantic_class(fen, side, str(negative or ""))
            if semantic not in negative_counts:
                negative_counts[semantic] = 0
            negative_counts[semantic] += 1
    candidate_counts = {
        semantic: int(positive_counts.get(semantic) or 0) + int(negative_counts.get(semantic) or 0)
        for semantic in sorted(set(positive_counts) | set(negative_counts))
    }
    required = {semantic: SEMANTIC_CLASS_MIN_COUNT for semantic in SEMANTIC_BALANCE_CLASSES}
    missing = [
        semantic
        for semantic, minimum in required.items()
        if int(candidate_counts.get(semantic) or 0) < int(minimum)
    ]
    central = int(candidate_counts.get("e_pawn_central_break") or 0) + int(candidate_counts.get("d_pawn_central_break") or 0)
    kingside = int(candidate_counts.get("kingside_aggression") or 0)
    return {
        "case_count": case_count,
        "positive_counts": positive_counts,
        "negative_counts": negative_counts,
        "candidate_counts": candidate_counts,
        "required_min_per_class": required,
        "missing_classes": missing,
        "balanced": not missing,
        "kingside_to_central_ratio": round(kingside / max(1, central), 4),
        "kingside_overpowers_central": kingside > central,
    }


def _semantic_positive_distribution(rows: list[dict]) -> dict:
    counts = {semantic: 0 for semantic in SEMANTIC_REQUIRED_CLASSES}
    for row in rows or []:
        fen = str(row.get("fen") or "")
        side = str(row.get("side") or "")
        expected = str(row.get("expected_move") or row.get("move_uci") or "").lower()
        semantic = str(row.get("semantic_class") or row.get("expected_semantic") or "")
        if not semantic and fen and side and expected:
            semantic = _move_semantic_class(fen, side, expected)
        if semantic in counts:
            counts[semantic] += 1
    return counts


def _semantic_coverage_from_counts(counts: dict) -> dict:
    missing = [semantic for semantic in SEMANTIC_REQUIRED_CLASSES if int((counts or {}).get(semantic) or 0) <= 0]
    return {
        "complete": not missing,
        "missing": missing,
        "counts": {semantic: int((counts or {}).get(semantic) or 0) for semantic in SEMANTIC_REQUIRED_CLASSES},
    }


def _train_to_gate_semantic_gap(train_counts: dict, gate_counts: dict) -> dict:
    rows = {}
    for semantic in SEMANTIC_REQUIRED_CLASSES:
        train_count = int((train_counts or {}).get(semantic) or 0)
        gate_count = int((gate_counts or {}).get(semantic) or 0)
        rows[semantic] = {
            "train": train_count,
            "gate": gate_count,
            "gap": train_count - gate_count,
            "train_to_gate_ratio": round(train_count / max(1, gate_count), 4),
        }
    return rows


def _row_expected_semantic(row: dict) -> str:
    fen = str(row.get("fen") or "")
    side = str(row.get("side") or "")
    expected = str(row.get("expected_move") or row.get("move_uci") or "").lower()
    semantic = str(row.get("semantic_class") or row.get("expected_semantic") or "")
    if not semantic and fen and side and expected:
        semantic = _move_semantic_class(fen, side, expected)
    return semantic


def _semantic_effective_distribution(rows: list[dict]) -> dict:
    totals = {semantic: 0.0 for semantic in SEMANTIC_REQUIRED_CLASSES}
    counts = {semantic: 0 for semantic in SEMANTIC_REQUIRED_CLASSES}
    for row in rows or []:
        semantic = _row_expected_semantic(row)
        if semantic not in totals:
            continue
        counts[semantic] += 1
        totals[semantic] += float(row.get("weight") or 1.0)
    rounded_totals = {semantic: round(float(value), 4) for semantic, value in totals.items()}
    positive_values = [value for value in rounded_totals.values() if value > 0.0]
    max_value = max(positive_values) if positive_values else 0.0
    min_value = min(positive_values) if positive_values else 0.0
    skew_ratio = round(max_value / max(0.0001, min_value), 4) if positive_values else None
    return {
        "counts": counts,
        "effective_weight": rounded_totals,
        "max_class_weight": max_value,
        "min_class_weight": min_value,
        "max_to_min_ratio": skew_ratio,
        "threshold": SEMANTIC_SAMPLING_MAX_SKEW_RATIO,
        "passed": bool(positive_values) and len(positive_values) == len(SEMANTIC_REQUIRED_CLASSES) and (skew_ratio or 999.0) <= SEMANTIC_SAMPLING_MAX_SKEW_RATIO,
    }


def _apply_semantic_class_balanced_weights(rows: list[dict]) -> dict:
    train_rows = [row for row in rows or [] if str(row.get("variant_split") or "") in {"exact", "train", "retention", "specialist_train"}]
    raw_counts = _semantic_positive_distribution(train_rows)
    present_counts = [int(raw_counts.get(semantic) or 0) for semantic in SEMANTIC_REQUIRED_CLASSES if int(raw_counts.get(semantic) or 0) > 0]
    if not present_counts:
        return {
            "enabled": False,
            "reason": "no semantic training rows",
            "raw_distribution": raw_counts,
            "effective_distribution": _semantic_effective_distribution(rows),
            "sample_weight_by_semantic": {},
        }
    target_count = sum(present_counts) / len(present_counts)
    sample_weight_by_semantic = {}
    for semantic in SEMANTIC_REQUIRED_CLASSES:
        count = int(raw_counts.get(semantic) or 0)
        if count <= 0:
            sample_weight_by_semantic[semantic] = 0.0
        else:
            sample_weight_by_semantic[semantic] = round(target_count / count, 6)
    for row in rows or []:
        semantic = _row_expected_semantic(row)
        if semantic not in sample_weight_by_semantic or sample_weight_by_semantic[semantic] <= 0.0:
            continue
        base_weight = float(row.get("weight") or 1.0)
        row["base_weight"] = round(base_weight, 6)
        row["semantic_class_weight"] = sample_weight_by_semantic[semantic]
        row["weight"] = round(max(0.1, min(3.0, base_weight * float(sample_weight_by_semantic[semantic]))), 6)
        row["semantic_balanced_sampling"] = True
    effective = _semantic_effective_distribution(train_rows)
    return {
        "enabled": True,
        "method": "inverse_frequency_row_weight",
        "target_count_per_semantic": round(target_count, 4),
        "raw_distribution": raw_counts,
        "sample_weight_by_semantic": sample_weight_by_semantic,
        "effective_distribution": effective,
        "skew_ratio": effective.get("max_to_min_ratio"),
        "threshold": SEMANTIC_SAMPLING_MAX_SKEW_RATIO,
        "passed": bool(effective.get("passed")),
    }


def _sanity_invariance_group_id(case: dict) -> str:
    return f"{case.get('side')}|{case.get('expected_move')}"


def _validation_invariance_context_key(fen: str, side: str, move_uci: str) -> str:
    try:
        board = chess.Board(str(fen or ""))
        board.turn = chess.WHITE if str(side or "").lower() == "white" else chess.BLACK
    except Exception:
        return f"{side}|invalid|{move_uci}"
    central_files = "cdef"
    central_ranks = range(2, 7)
    pawns = []
    for file_name in central_files:
        for rank in central_ranks:
            square = chess.parse_square(f"{file_name}{rank}")
            piece = board.piece_at(square)
            if piece and piece.piece_type == chess.PAWN:
                pawns.append(f"{'w' if piece.color == chess.WHITE else 'b'}{file_name}{rank}")
    piece_count = len(board.piece_map())
    opening_phase = "opening" if int(board.fullmove_number or 1) <= 10 and piece_count >= 24 else "post_opening"
    watched_moves = ("e7e5", "d7d5", "c7c5", "a7a5", "h7h5")
    legal = []
    for item in watched_moves:
        try:
            legal.append(f"{item}:{int(chess.Move.from_uci(item) in board.legal_moves)}")
        except Exception:
            continue
    king_square = board.king(board.turn)
    king_file = chess.square_file(king_square) if king_square is not None else -1
    king_rank = chess.square_rank(king_square) if king_square is not None else -1
    safety = f"check={int(board.is_check())}|king_zone={king_file // 2},{king_rank // 2}|castle_any={int(bool(board.castling_rights))}"
    return (
        f"{side}|phase={opening_phase}|turn={board.turn}|"
        f"pawns={','.join(pawns)}|legal={','.join(legal)}|safety={safety}|{move_uci}"
    )


def _sanity_label_quality_audit(variants: list[dict], raw_rows: list[dict] | None = None) -> dict:
    rows = []
    warnings = []
    raw_by_case = {str(row.get("case_id") or ""): row for row in raw_rows or []}
    for variant in variants or []:
        fen = str(variant.get("fen") or "")
        side = str(variant.get("side") or "")
        expected = str(variant.get("expected_move") or "").lower()
        raw_row = raw_by_case.get(str(variant.get("case_id") or "")) or {}
        try:
            board = chess.Board(fen)
            board.turn = chess.WHITE if side == "white" else chess.BLACK
            expected_move = chess.Move.from_uci(expected)
        except Exception as exc:
            rows.append(
                {
                    "case_id": variant.get("case_id"),
                    "variant_split": variant.get("variant_split"),
                    "variant_difficulty": variant.get("variant_difficulty"),
                    "expected_move": expected,
                    "legal": False,
                    "static_best_move": None,
                    "static_cp_delta": None,
                    "expected_rank": raw_row.get("expected_rank"),
                    "label_quality": "invalid",
                    "label_quality_warning": True,
                    "promotion_gate_eligible": False,
                    "excluded_from_gate": True,
                    "reason": str(exc),
                }
            )
            warnings.append(f"{variant.get('case_id')}: invalid FEN or move")
            continue
        color_sign = 1 if board.turn == chess.WHITE else -1
        piece_values = {
            chess.PAWN: 100,
            chess.KNIGHT: 320,
            chess.BISHOP: 330,
            chess.ROOK: 500,
            chess.QUEEN: 900,
            chess.KING: 0,
        }

        def board_material(current: chess.Board) -> int:
            total = 0
            for piece in current.piece_map().values():
                value = piece_values.get(piece.piece_type, 0)
                total += value if piece.color == chess.WHITE else -value
            return total

        def material_after(move: chess.Move) -> int:
            after = board.copy(stack=False)
            after.push(move)
            return color_sign * board_material(after)

        legal = expected_move in board.legal_moves
        if not legal:
            rows.append(
                {
                    "case_id": variant.get("case_id"),
                    "variant_split": variant.get("variant_split"),
                    "variant_difficulty": variant.get("variant_difficulty"),
                    "expected_move": expected,
                    "legal": False,
                    "static_best_move": None,
                    "static_cp_delta": None,
                    "expected_rank": raw_row.get("expected_rank"),
                    "label_quality": "invalid",
                    "label_quality_warning": True,
                    "promotion_gate_eligible": False,
                    "excluded_from_gate": True,
                    "reason": "expected move is illegal",
                }
            )
            warnings.append(f"{variant.get('case_id')}: expected move {expected} is illegal")
            continue
        expected_score = material_after(expected_move)
        legal_scores = sorted(
            ((material_after(move), move.uci()) for move in board.legal_moves),
            key=lambda item: (-item[0], item[1]),
        )
        best_score, best_move = legal_scores[0] if legal_scores else (expected_score, expected)
        static_delta = int(expected_score - best_score)
        quality = "questionable" if static_delta < SANITY_LABEL_QUESTIONABLE_CP_DELTA else "clean"
        warning = quality != "clean"
        if warning:
            warnings.append(f"{variant.get('case_id')}: expected move static material delta {static_delta}cp vs best legal")
        rows.append(
            {
                "case_id": variant.get("case_id"),
                "variant_split": variant.get("variant_split"),
                "variant_difficulty": variant.get("variant_difficulty"),
                "expected_move": expected,
                "legal": True,
                "static_best_move": best_move,
                "static_cp_delta": static_delta,
                "static_delta_vs_best_cp": static_delta,
                "expected_rank": raw_row.get("expected_rank"),
                "label_quality": quality,
                "hard_label_allowed": static_delta >= SANITY_LABEL_HARD_EXCLUDE_CP_DELTA,
                "label_quality_warning": warning,
                "promotion_gate_eligible": quality == "clean",
                "excluded_from_gate": quality != "clean",
                "reason": "expected move appears materially questionable" if warning else "expected move is legal and not materially dominated",
            }
        )
    clean_rows = [row for row in rows if row.get("label_quality") == "clean"]
    questionable_rows = [row for row in rows if row.get("label_quality") == "questionable"]
    invalid_rows = [row for row in rows if row.get("label_quality") == "invalid"]
    hard_excluded_rows = [
        row
        for row in rows
        if row.get("label_quality") == "questionable"
        and row.get("static_cp_delta") is not None
        and float(row.get("static_cp_delta") or 0) < SANITY_LABEL_HARD_EXCLUDE_CP_DELTA
    ]
    return {
        "checked_count": len(rows),
        "clean_count": len(clean_rows),
        "questionable_count": len(questionable_rows),
        "invalid_count": len(invalid_rows),
        "hard_excluded_count": len(hard_excluded_rows),
        "warning_count": len([row for row in rows if row.get("label_quality_warning")]),
        "label_quality_warning": bool(warnings),
        "warnings": warnings,
        "thresholds": {
            "questionable_static_cp_delta": SANITY_LABEL_QUESTIONABLE_CP_DELTA,
            "hard_exclude_static_cp_delta": SANITY_LABEL_HARD_EXCLUDE_CP_DELTA,
        },
        "summary": {
            "clean": len(clean_rows),
            "questionable": len(questionable_rows),
            "invalid": len(invalid_rows),
            "hard_excluded": len(hard_excluded_rows),
        },
        "excluded_from_gate_cases": [row for row in rows if row.get("excluded_from_gate")],
        "cases": rows,
    }


def _variant_gate_key(variant: dict) -> tuple[str, str, str]:
    return (
        hashlib.sha256(str(variant.get("fen") or "").encode("utf-8")).hexdigest(),
        str(variant.get("normalized_fen_hash") or _normalized_fen_hash(str(variant.get("fen") or ""))),
        str(variant.get("expected_move") or ""),
    )


def _quality_rows_by_case(label_quality: dict) -> dict[str, dict]:
    return {str(row.get("case_id") or ""): row for row in label_quality.get("cases") or []}


def _with_label_quality(variants: list[dict], label_quality: dict) -> list[dict]:
    by_case = _quality_rows_by_case(label_quality)
    return [
        {
            **variant,
            "label_quality": by_case.get(str(variant.get("case_id") or ""), {}),
        }
        for variant in variants
    ]


def _semantic_balanced_gate_templates() -> list[dict]:
    def case(case_id: str, moves: list[str], expected: str, semantic: str, difficulty: str, reason: str) -> dict:
        return {
            "case_id": case_id,
            "fen": _fen_after_moves(moves),
            "expected_move": expected,
            "semantic_class": semantic,
            "difficulty": difficulty,
            "source_reason": reason,
        }

    return [
        case("gate_e_pawn_easy_001", [], "e2e4", "e_pawn_central_break", "easy", "Open with central e-pawn from the initial position."),
        case("gate_e_pawn_easy_002", ["g1f3"], "e7e5", "e_pawn_central_break", "easy", "Black contests the center with the e-pawn after a quiet knight development."),
        case("gate_e_pawn_easy_003", ["c2c3"], "e7e5", "e_pawn_central_break", "easy", "Black takes central space against a slow c-pawn setup."),
        case("gate_e_pawn_medium_001", ["b2b3", "g8f6"], "e2e4", "e_pawn_central_break", "medium", "White central e-pawn break after quiet flank development."),
        case("gate_e_pawn_medium_002", ["g1f3", "d7d5"], "e2e4", "e_pawn_central_break", "medium", "White challenges the center with e-pawn after black claims d5."),
        case("gate_e_pawn_medium_003", ["c2c4", "g8f6"], "e2e4", "e_pawn_central_break", "medium", "White builds a central break against flank pressure."),
        case("gate_e_pawn_hard_001", ["g1f3", "d7d5", "c2c4"], "e7e5", "e_pawn_central_break", "hard", "Black strikes with e-pawn in a more complex central structure."),
        case("gate_e_pawn_hard_002", ["d2d4", "g8f6", "c2c4"], "e7e5", "e_pawn_central_break", "hard", "Black e-pawn break remains legal and materially safe in queen-pawn structure."),
        case("gate_e_pawn_hard_003", ["b1c3", "d7d5", "e2e3"], "e7e5", "e_pawn_central_break", "hard", "Black uses e-pawn break despite extra developed pieces."),
        case("gate_d_pawn_easy_001", [], "d2d4", "d_pawn_central_break", "easy", "Open with central d-pawn from the initial position."),
        case("gate_d_pawn_easy_002", ["b2b3"], "d7d5", "d_pawn_central_break", "easy", "Black immediately challenges a quiet setup with d-pawn."),
        case("gate_d_pawn_easy_003", ["g1f3"], "d7d5", "d_pawn_central_break", "easy", "Black claims the center against quiet development."),
        case("gate_d_pawn_medium_001", ["c2c4"], "d7d5", "d_pawn_central_break", "medium", "Black central d-pawn response to flank opening."),
        case("gate_d_pawn_medium_002", ["b1c3"], "d7d5", "d_pawn_central_break", "medium", "Black central break against knight development."),
        case("gate_d_pawn_medium_003", ["e2e4", "e7e5", "g1f3"], "d7d5", "d_pawn_central_break", "medium", "Black d-pawn break against e-pawn center with knight pressure."),
        case("gate_d_pawn_hard_001", ["g1f3", "g8f6", "c2c4"], "d7d5", "d_pawn_central_break", "hard", "Black d-pawn break in a developed flank setup."),
        case("gate_d_pawn_hard_002", ["e2e4", "c7c5", "g1f3"], "d7d5", "d_pawn_central_break", "hard", "Black d-pawn break after asymmetric central tension."),
        case("gate_d_pawn_hard_003", ["d2d4", "g8f6", "b1c3"], "d7d5", "d_pawn_central_break", "hard", "Black mirrors central d-pawn structure after development."),
        case("gate_flank_easy_001", [], "c2c4", "flank_pawn_push", "easy", "Safe flank pawn opening from the initial position."),
        case("gate_flank_easy_002", [], "b2b3", "flank_pawn_push", "easy", "Safe queenside flank development pawn move."),
        case("gate_flank_easy_003", ["g1f3"], "c7c5", "flank_pawn_push", "easy", "Black uses a c-pawn flank challenge after quiet development."),
        case("gate_flank_medium_001", ["b1c3"], "c7c5", "flank_pawn_push", "medium", "Black c-pawn flank counter against knight development."),
        case("gate_flank_medium_002", ["d2d4"], "c7c5", "flank_pawn_push", "medium", "Black c-pawn flank counter against d-pawn center."),
        case("gate_flank_medium_003", ["g1f3", "d7d5"], "c2c4", "flank_pawn_push", "medium", "White c-pawn flank pressure against d-pawn center."),
        case("gate_flank_hard_001", ["e2e4", "e7e5", "g1f3"], "c7c5", "flank_pawn_push", "hard", "Black adds flank pressure in an open e-pawn position."),
        case("gate_flank_hard_002", ["g1f3", "d7d5", "b2b3"], "c7c5", "flank_pawn_push", "hard", "Black c-pawn pressure against a d-pawn center with quiet flank development."),
        case("gate_flank_hard_003", ["c2c4", "g8f6", "g1f3"], "c7c5", "flank_pawn_push", "hard", "Black contests flank space without material concession."),
        case("gate_flank_hard_004", ["b1c3", "g8f6", "g1f3"], "c7c5", "flank_pawn_push", "hard", "Black keeps flank counterplay available after both white knights develop."),
        case("gate_kingside_easy_001", [], "g2g4", "kingside_aggression", "easy", "A legal kingside pawn push used only to test semantic recognition."),
        case("gate_kingside_easy_002", [], "h2h4", "kingside_aggression", "easy", "A legal rook-pawn aggression marker in a low-tension position."),
        case("gate_kingside_easy_003", ["b2b3"], "h7h5", "kingside_aggression", "easy", "Black kingside pawn push is legal and materially safe."),
        case("gate_kingside_medium_001", ["g1f3"], "f7f5", "kingside_aggression", "medium", "Black f-pawn aggression against quiet knight development."),
        case("gate_kingside_medium_002", ["d2d4"], "g7g5", "kingside_aggression", "medium", "Black g-pawn aggression marker against queen-pawn center."),
        case("gate_kingside_medium_003", ["g1f3", "d7d5"], "h2h4", "kingside_aggression", "medium", "White kingside pawn push with prior development."),
        case("gate_kingside_hard_001", ["e2e4", "d7d5", "g1f3"], "h7h5", "kingside_aggression", "hard", "Black kingside push in mixed central tension."),
        case("gate_kingside_hard_002", ["d2d4", "g8f6", "c2c4"], "g7g5", "kingside_aggression", "hard", "Black kingside push after flank and development pressure."),
        case("gate_kingside_hard_003", ["g1f3", "g8f6", "e2e4"], "h7h5", "kingside_aggression", "hard", "Black aggression marker after both knights are developed."),
        case("gate_development_easy_001", [], "g1f3", "development_move", "easy", "Develop the kingside knight from the initial position."),
        case("gate_development_easy_002", [], "b1c3", "development_move", "easy", "Develop the queenside knight from the initial position."),
        case("gate_development_easy_003", ["b2b3"], "g8f6", "development_move", "easy", "Black develops knight after quiet flank setup."),
        case("gate_development_medium_001", ["e2e4", "e7e5"], "g1f3", "development_move", "medium", "White develops knight after symmetric central pawns."),
        case("gate_development_medium_002", ["d2d4", "d7d5"], "g1f3", "development_move", "medium", "White develops knight in queen-pawn structure."),
        case("gate_development_medium_003", ["e2e4", "e7e5", "g1f3"], "b8c6", "development_move", "medium", "Black develops queenside knight against e-pawn opening."),
        case("gate_development_hard_001", ["e2e4", "e7e5", "g1f3", "b8c6"], "f1c4", "development_move", "hard", "White develops bishop after central and knight development."),
        case("gate_development_hard_002", ["d2d4", "d7d5", "c2c4", "e7e6", "b1c3"], "g8f6", "development_move", "hard", "Black develops knight in a queen-pawn structure."),
        case("gate_development_hard_003", ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4"], "g8f6", "development_move", "hard", "Black develops knight in an Italian-like setup."),
    ]


def _build_semantic_balanced_clean_gate_set(*, blocked_keys: set[tuple[str, str, str]]) -> dict:
    clean_cases: list[dict] = []
    questionable_cases: list[dict] = []
    invalid_cases: list[dict] = []
    all_cases: list[dict] = []
    seen_keys = set(blocked_keys)
    blocked_normalized_hashes = {str(item[1]) for item in blocked_keys if len(item) > 1}
    templates = _semantic_balanced_gate_templates()
    for template in templates:
        fen = str(template.get("fen") or "")
        expected = str(template.get("expected_move") or "").lower()
        semantic = str(template.get("semantic_class") or "")
        difficulty = str(template.get("difficulty") or "")
        side = "white"
        legal = False
        semantic_matches = False
        reason = ""
        try:
            board = chess.Board(fen)
            side = "white" if board.turn == chess.WHITE else "black"
            move = chess.Move.from_uci(expected)
            legal = move in board.legal_moves
            semantic_matches = _move_semantic_class_for_board(board, expected) == semantic
            reason = "" if legal and semantic_matches else "expected move illegal or semantic class mismatch"
        except Exception as exc:
            reason = str(exc)
        variant = {
            "case_id": template.get("case_id"),
            "variant_id": template.get("case_id"),
            "variant_split": "held_out",
            "variant_difficulty": difficulty,
            "difficulty": difficulty,
            "fen": fen,
            "side": side,
            "expected_move": expected,
            "semantic_class": semantic,
            "expected_semantic": semantic,
            "normalized_fen_hash": _normalized_fen_hash(fen),
            "board_embedding_similarity": 1.0,
            "board_semantics_features": _board_semantics_features(fen, side),
            "flank_context_features": _flank_context_features(fen, side),
            "flank_reason_tag": _flank_reason_tag_for_move(fen, side, expected),
            "source_reason": template.get("source_reason"),
            "legal_moves_contains_expected": legal,
            "semantic_matches_expected": semantic_matches,
            "source": "semantic_balanced_clean_gate_set",
        }
        key = _variant_gate_key(variant)
        if key in seen_keys or str(variant.get("normalized_fen_hash") or "") in blocked_normalized_hashes:
            variant["leakage_blocked"] = True
            variant["label_quality"] = {
                "label_quality": "invalid",
                "reason": "held-out case duplicates train/validation key",
                "excluded_from_gate": True,
            }
            invalid_cases.append(variant)
            all_cases.append(variant)
            continue
        seen_keys.add(key)
        audit = _sanity_label_quality_audit([variant])
        quality = (audit.get("cases") or [{}])[0]
        quality_name = str(quality.get("label_quality") or "invalid")
        if not legal or not semantic_matches:
            quality = {
                **quality,
                "label_quality": "invalid",
                "label_quality_warning": True,
                "promotion_gate_eligible": False,
                "excluded_from_gate": True,
                "reason": reason or "expected move illegal or semantic class mismatch",
            }
            quality_name = "invalid"
        enriched = {
            **variant,
            "label_quality": quality_name,
            "static_best_move": quality.get("static_best_move"),
            "static_cp_delta": quality.get("static_cp_delta"),
            "legal_moves_contains_expected": legal,
            "label_quality_detail": quality,
        }
        if quality_name == "clean" and float(quality.get("static_cp_delta") or 0.0) >= SANITY_LABEL_QUESTIONABLE_CP_DELTA:
            clean_cases.append(enriched)
        elif quality_name == "invalid":
            invalid_cases.append(enriched)
        else:
            questionable_cases.append(enriched)
        all_cases.append(enriched)
    by_semantic: dict[str, dict] = {}
    for semantic in SEMANTIC_BALANCE_CLASSES + ("development_move",):
        by_semantic[semantic] = {}
        for difficulty in ["easy", "medium", "hard"]:
            selected = [
                row for row in clean_cases
                if row.get("semantic_class") == semantic and row.get("difficulty") == difficulty
            ]
            by_semantic[semantic][difficulty] = {
                "count": len(selected),
                "required": SEMANTIC_BALANCED_GATE_MIN_PER_DIFFICULTY,
                "passed": len(selected) >= SEMANTIC_BALANCED_GATE_MIN_PER_DIFFICULTY,
            }
    missing = [
        f"{semantic}:{difficulty}"
        for semantic, payload in by_semantic.items()
        for difficulty, row in payload.items()
        if not row.get("passed")
    ]
    label_quality = _sanity_label_quality_audit(all_cases)
    return {
        "clean_gate_cases": clean_cases,
        "questionable_cases": questionable_cases,
        "invalid_cases": invalid_cases,
        "all_cases": all_cases,
        "by_semantic": by_semantic,
        "semantic_coverage_complete": not missing,
        "semantic_coverage_missing": missing,
        "held_out_in_training": False,
        "dedupe_keys": ["fen_hash", "normalized_fen_hash", "expected_move"],
        "label_quality_summary": label_quality.get("summary") or {},
        "label_quality": label_quality,
        "source": "semantic_balanced_clean_gate_set",
        "required_per_semantic_difficulty": SEMANTIC_BALANCED_GATE_MIN_PER_DIFFICULTY,
    }


def _semantic_balanced_supervised_variants(*, split: str, offset: int) -> list[dict]:
    rows: list[dict] = []
    for template in _semantic_balanced_gate_templates():
        semantic = str(template.get("semantic_class") or "")
        difficulty = str(template.get("difficulty") or "easy")
        side = "white"
        try:
            board = chess.Board(str(template.get("fen") or ""))
            side = "white" if board.turn == chess.WHITE else "black"
        except Exception:
            continue
        base_case = {
            "case_id": str(template.get("case_id") or ""),
            "fen": str(template.get("fen") or ""),
            "side": side,
            "expected_move": str(template.get("expected_move") or "").lower(),
            "expected_semantic": semantic,
        }
        variants = _sanity_learning_variants(
            base_case,
            limit=1,
            offset=int(offset),
            split=split,
            difficulty=difficulty,
        )
        if not variants:
            continue
        variant = variants[0]
        rows.append(
            {
                **variant,
                "case_id": f"{template.get('case_id')}:{split}",
                "variant_id": f"{template.get('case_id')}:{split}",
                "variant_split": split,
                "variant_difficulty": difficulty,
                "difficulty": difficulty,
                "expected_semantic": semantic,
                "semantic_class": semantic,
                "flank_context_features": variant.get("flank_context_features") or _flank_context_features(str(variant.get("fen") or ""), str(variant.get("side") or "")),
                "flank_reason_tag": variant.get("flank_reason_tag") or _flank_reason_tag_for_move(str(variant.get("fen") or ""), str(variant.get("side") or ""), str(variant.get("expected_move") or "")),
                "source_reason": template.get("source_reason"),
                "source": f"semantic_balanced_{split}_replay",
            }
        )
    return rows


def _central_flank_targeted_supervised_variants(*, split: str, offsets: tuple[int, ...]) -> list[dict]:
    rows: list[dict] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for template in _semantic_balanced_gate_templates():
        semantic = str(template.get("semantic_class") or "")
        if semantic not in CENTRAL_FLANK_FOCUS_SEMANTICS:
            continue
        difficulty = str(template.get("difficulty") or "easy")
        try:
            board = chess.Board(str(template.get("fen") or ""))
            side = "white" if board.turn == chess.WHITE else "black"
        except Exception:
            continue
        base_case = {
            "case_id": str(template.get("case_id") or ""),
            "fen": str(template.get("fen") or ""),
            "side": side,
            "expected_move": str(template.get("expected_move") or "").lower(),
            "expected_semantic": semantic,
        }
        for index, offset in enumerate(offsets, start=1):
            variants = _sanity_learning_variants(
                base_case,
                limit=1,
                offset=int(offset),
                split=split,
                difficulty=difficulty,
            )
            if not variants:
                continue
            variant = variants[0]
            key = _variant_gate_key(variant)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            variant_id = f"{template.get('case_id')}:central_flank_{split}:{index}"
            rows.append(
                {
                    **variant,
                    "case_id": variant_id,
                    "variant_id": variant_id,
                    "variant_split": split,
                    "variant_difficulty": difficulty,
                    "difficulty": difficulty,
                    "expected_semantic": semantic,
                    "semantic_class": semantic,
                    "flank_context_features": variant.get("flank_context_features") or _flank_context_features(str(variant.get("fen") or ""), str(variant.get("side") or "")),
                    "flank_reason_tag": variant.get("flank_reason_tag") or _flank_reason_tag_for_move(str(variant.get("fen") or ""), str(variant.get("side") or ""), str(variant.get("expected_move") or "")),
                    "source_reason": template.get("source_reason"),
                    "source": f"central_flank_targeted_{split}_replay",
                    "curriculum_focus": "central_flank_semantic_improvement",
                    "semantic_pair_contrast": {
                        "positive_semantic": semantic,
                        "negative_semantics": [
                            row
                            for row in CENTRAL_FLANK_FOCUS_SEMANTICS
                            if row != semantic
                        ],
                    },
                }
            )
    return rows


def _build_clean_held_out_pool(case: dict, *, blocked_keys: set[tuple[str, str, str]]) -> dict:
    clean_gate_cases: list[dict] = []
    questionable_cases: list[dict] = []
    invalid_cases: list[dict] = []
    all_cases: list[dict] = []
    by_difficulty: dict[str, dict] = {}
    seen_keys = set(blocked_keys)
    for difficulty in ["easy", "medium", "hard"]:
        candidates = _sanity_learning_variants(
            case,
            limit=SANITY_HELD_OUT_POOL_CANDIDATES_PER_DIFFICULTY,
            offset=SANITY_EASY_TRAIN_VARIANT_COUNT + SANITY_EASY_VALIDATION_VARIANT_COUNT if difficulty == "easy"
            else SANITY_MEDIUM_TRAIN_VARIANT_COUNT + SANITY_MEDIUM_VALIDATION_VARIANT_COUNT if difficulty == "medium"
            else SANITY_HARD_TRAIN_VARIANT_COUNT,
            split="held_out",
            difficulty=difficulty,
        )
        unique_candidates = []
        local_seen: set[tuple[str, str, str]] = set()
        for variant in candidates:
            key = _variant_gate_key(variant)
            if key in seen_keys or key in local_seen:
                continue
            local_seen.add(key)
            unique_candidates.append(variant)
        audit = _sanity_label_quality_audit(unique_candidates)
        quality_by_case = _quality_rows_by_case(audit)
        clean = []
        questionable = []
        invalid = []
        for variant in unique_candidates:
            quality = quality_by_case.get(str(variant.get("case_id") or ""), {})
            enriched = {**variant, "label_quality": quality}
            if quality.get("label_quality") == "clean":
                clean.append(enriched)
            elif quality.get("label_quality") == "invalid":
                invalid.append(enriched)
            else:
                questionable.append(enriched)
        selected_clean = clean[:SANITY_CLEAN_HELD_OUT_MIN_PER_DIFFICULTY]
        for variant in selected_clean:
            seen_keys.add(_variant_gate_key(variant))
        clean_gate_cases.extend(selected_clean)
        questionable_cases.extend(questionable)
        invalid_cases.extend(invalid)
        all_cases.extend(selected_clean + questionable + invalid)
        by_difficulty[difficulty] = {
            "candidate_count": len(unique_candidates),
            "clean_count": len(clean),
            "selected_clean_count": len(selected_clean),
            "questionable_count": len(questionable),
            "invalid_count": len(invalid),
            "required_clean_count": SANITY_CLEAN_HELD_OUT_MIN_PER_DIFFICULTY,
            "sufficient_clean_pool": len(selected_clean) >= SANITY_CLEAN_HELD_OUT_MIN_PER_DIFFICULTY,
        }
    audit_all = _sanity_label_quality_audit(clean_gate_cases + questionable_cases + invalid_cases)
    return {
        "clean_gate_cases": clean_gate_cases,
        "questionable_cases": questionable_cases,
        "invalid_cases": invalid_cases,
        "all_cases": all_cases,
        "by_difficulty": by_difficulty,
        "label_quality_summary": audit_all.get("summary") or {},
        "label_quality": audit_all,
        "held_out_in_training": False,
        "dedupe_keys": ["fen_hash", "normalized_fen_hash", "expected_move"],
        "required_clean_per_difficulty": SANITY_CLEAN_HELD_OUT_MIN_PER_DIFFICULTY,
    }


def _sanity_curriculum_variants(case: dict, *, trusted_replays: int = 0) -> dict:
    early_warmup = int(trusted_replays or 0) <= 10
    easy_train = _sanity_learning_variants(case, limit=SANITY_EASY_TRAIN_VARIANT_COUNT, offset=0, split="train", difficulty="easy")
    medium_train = _sanity_learning_variants(case, limit=SANITY_MEDIUM_TRAIN_VARIANT_COUNT, offset=0, split="train", difficulty="medium")
    easy_validation = _sanity_learning_variants(
        case,
        limit=SANITY_EASY_VALIDATION_VARIANT_COUNT,
        offset=SANITY_EASY_TRAIN_VARIANT_COUNT,
        split="validation",
        difficulty="easy",
    )
    medium_validation = _sanity_learning_variants(
        case,
        limit=SANITY_MEDIUM_VALIDATION_VARIANT_COUNT,
        offset=SANITY_MEDIUM_TRAIN_VARIANT_COUNT,
        split="validation",
        difficulty="medium",
    )
    hard_train_count = SANITY_EARLY_HARD_TRAIN_VARIANT_COUNT if early_warmup else SANITY_HARD_TRAIN_VARIANT_COUNT
    hard_train = _sanity_learning_variants(
        case,
        limit=hard_train_count,
        offset=0,
        split="train",
        difficulty="hard",
    )
    semantic_balanced_train = _semantic_balanced_supervised_variants(split="train", offset=1)
    semantic_balanced_validation = _semantic_balanced_supervised_variants(split="validation", offset=5)
    central_flank_targeted_train = _central_flank_targeted_supervised_variants(
        split="train",
        offsets=CENTRAL_FLANK_TARGETED_TRAIN_OFFSETS,
    )
    central_flank_targeted_validation = _central_flank_targeted_supervised_variants(
        split="validation",
        offsets=CENTRAL_FLANK_TARGETED_VALIDATION_OFFSETS,
    )
    train = easy_train + medium_train + hard_train + semantic_balanced_train + central_flank_targeted_train
    validation = easy_validation + medium_validation + semantic_balanced_validation + central_flank_targeted_validation
    blocked_keys = {_variant_gate_key(row) for row in train + validation}
    held_out_pool = _build_semantic_balanced_clean_gate_set(blocked_keys=blocked_keys)
    clean_held_out = list(held_out_pool.get("clean_gate_cases") or [])
    questionable_held_out = list(held_out_pool.get("questionable_cases") or [])
    invalid_held_out = list(held_out_pool.get("invalid_cases") or [])
    held_out = clean_held_out + questionable_held_out
    return {
        "train": train,
        "validation": validation,
        "held_out": held_out,
        "clean_gate_cases": clean_held_out,
        "questionable_cases": questionable_held_out,
        "invalid_cases": invalid_held_out,
        "held_out_pool": held_out_pool,
        "seen": train,
        "unseen": validation + held_out,
        "split_counts": {
            "train": len(train),
            "validation": len(validation),
            "held_out": len(held_out),
            "clean_gate_cases": len(clean_held_out),
            "questionable_cases": len(questionable_held_out),
            "invalid_cases": len(invalid_held_out),
            "semantic_balanced_train": len(semantic_balanced_train),
            "semantic_balanced_validation": len(semantic_balanced_validation),
            "central_flank_targeted_train": len(central_flank_targeted_train),
            "central_flank_targeted_validation": len(central_flank_targeted_validation),
        },
        "semantic_balanced_training": {
            "train": semantic_balanced_train,
            "validation": semantic_balanced_validation,
            "source": "semantic_balanced_supervised_variants",
            "held_out_in_training": False,
        },
        "central_flank_targeted_curriculum": {
            "train": central_flank_targeted_train,
            "validation": central_flank_targeted_validation,
            "source": "central_flank_targeted_supervised_variants",
            "focus_semantics": list(CENTRAL_FLANK_FOCUS_SEMANTICS),
            "train_offsets": list(CENTRAL_FLANK_TARGETED_TRAIN_OFFSETS),
            "validation_offsets": list(CENTRAL_FLANK_TARGETED_VALIDATION_OFFSETS),
            "held_out_in_training": False,
        },
        "warmup": {
            "trusted_replays": int(trusted_replays or 0),
            "early_checkpoint_warmup": early_warmup,
            "hard_train_variant_count": hard_train_count,
            "clean_held_out_min_per_difficulty": SANITY_CLEAN_HELD_OUT_MIN_PER_DIFFICULTY,
            "note": "held-out gate uses clean labels only; questionable labels remain exploratory and do not affect promotion",
        },
        "by_difficulty": {
            "easy": {
                "train": easy_train + [row for row in semantic_balanced_train + central_flank_targeted_train if row.get("variant_difficulty") == "easy"],
                "validation": easy_validation + [row for row in semantic_balanced_validation + central_flank_targeted_validation if row.get("variant_difficulty") == "easy"],
                "held_out": [row for row in held_out if row.get("variant_difficulty") == "easy"],
                "seen": easy_train + [row for row in semantic_balanced_train + central_flank_targeted_train if row.get("variant_difficulty") == "easy"],
                "unseen": easy_validation + [row for row in semantic_balanced_validation + central_flank_targeted_validation if row.get("variant_difficulty") == "easy"] + [row for row in held_out if row.get("variant_difficulty") == "easy"],
                "clean_gate_cases": [row for row in clean_held_out if row.get("variant_difficulty") == "easy"],
            },
            "medium": {
                "train": medium_train + [row for row in semantic_balanced_train + central_flank_targeted_train if row.get("variant_difficulty") == "medium"],
                "validation": medium_validation + [row for row in semantic_balanced_validation + central_flank_targeted_validation if row.get("variant_difficulty") == "medium"],
                "held_out": [row for row in held_out if row.get("variant_difficulty") == "medium"],
                "seen": medium_train + [row for row in semantic_balanced_train + central_flank_targeted_train if row.get("variant_difficulty") == "medium"],
                "unseen": medium_validation + [row for row in semantic_balanced_validation + central_flank_targeted_validation if row.get("variant_difficulty") == "medium"] + [row for row in held_out if row.get("variant_difficulty") == "medium"],
                "clean_gate_cases": [row for row in clean_held_out if row.get("variant_difficulty") == "medium"],
            },
            "hard": {
                "train": hard_train + [row for row in semantic_balanced_train + central_flank_targeted_train if row.get("variant_difficulty") == "hard"],
                "validation": [row for row in semantic_balanced_validation + central_flank_targeted_validation if row.get("variant_difficulty") == "hard"],
                "held_out": [row for row in held_out if row.get("variant_difficulty") == "hard"],
                "seen": hard_train + [row for row in semantic_balanced_train + central_flank_targeted_train if row.get("variant_difficulty") == "hard"],
                "unseen": [row for row in semantic_balanced_validation + central_flank_targeted_validation if row.get("variant_difficulty") == "hard"] + [row for row in held_out if row.get("variant_difficulty") == "hard"],
                "clean_gate_cases": [row for row in clean_held_out if row.get("variant_difficulty") == "hard"],
            },
        },
    }


def _select_sanity_learning_case(engine_alias: str, before_model_path: Path, samples: list[dict]) -> tuple[dict | None, dict | None]:
    cases = _sanity_learning_cases_from_samples(samples)
    evaluated_before = []
    for candidate in cases:
        candidate_before = _evaluate_sanity_learning_position(engine_alias, before_model_path, candidate)
        evaluated_before.append(candidate_before)
        if not candidate_before.get("expected_is_top1"):
            return candidate, candidate_before
    if cases:
        return cases[0], evaluated_before[0] if evaluated_before else _evaluate_sanity_learning_position(engine_alias, before_model_path, cases[0])
    return None, None


def _sanity_seen_variant_training_rows(engine_alias: str, before_model_path: Path, samples: list[dict], *, trusted_replays: int = 0) -> dict:
    case, before_exact = _select_sanity_learning_case(engine_alias, before_model_path, samples)
    if not case:
        return {"case": None, "before_exact": None, "rows": [], "seen_variants": [], "curriculum": {}}
    curriculum = _sanity_curriculum_variants(case, trusted_replays=int(trusted_replays or 0))
    train_variants = list(curriculum.get("train") or curriculum.get("seen") or [])
    old_move = str((before_exact or {}).get("top1") or "")
    invariance_group_id = _sanity_invariance_group_id(case)
    hard_negative_limit = 3 if int(trusted_replays or 0) <= 10 else 5
    exact_hard_negatives = _legal_sanity_hard_negatives(
        case["fen"],
        case["side"],
        case["expected_move"],
        old_move=old_move,
        limit=hard_negative_limit,
    )
    exact_semantic_negatives = _semantic_negative_moves(
        case["fen"],
        case["side"],
        case["expected_move"],
        old_move=old_move,
        limit=hard_negative_limit,
    )
    exact_hard_negatives = list(dict.fromkeys([*exact_semantic_negatives, *exact_hard_negatives]))[:hard_negative_limit]
    rows = [
        {
            "fen": case["fen"],
            "side": case["side"],
            "move_uci": case["expected_move"],
            "target": 1.0,
            "weight": 1.6,
            "source": "sanity_exact_replay",
            "category": "mistake_retention",
            "case_id": case.get("case_id"),
            "variant_id": f"{case.get('case_id')}:exact",
            "variant_split": "exact",
            "variant_difficulty": "exact",
            "normalized_fen_hash": _normalized_fen_hash(str(case.get("fen") or "")),
            "expected_move": case["expected_move"],
            "expected_semantic": _move_semantic_class(case["fen"], case["side"], case["expected_move"]),
            "semantic_hard_negatives": exact_semantic_negatives,
            "board_semantics_features": _board_semantics_features(case["fen"], case["side"]),
            "flank_context_features": _flank_context_features(case["fen"], case["side"]),
            "flank_context_feature_vector": _flank_context_feature_vector(_flank_context_features(case["fen"], case["side"])),
            "flank_context_feature_injection": _move_semantic_class(case["fen"], case["side"], case["expected_move"]) == FLANK_REPAIR_SEMANTIC,
            "flank_reason_tag": _flank_reason_tag_for_move(case["fen"], case["side"], case["expected_move"]),
            "hard_negatives": exact_hard_negatives,
            "invariance_group_id": invariance_group_id,
            "pairwise_role": "positive_anchor",
            "curriculum_stage": "exact_fen",
        }
    ]
    for variant in train_variants:
        variant_source = str(variant.get("source") or "")
        variant_semantic = str(variant.get("semantic_class") or variant.get("expected_semantic") or "")
        is_targeted_central_flank = variant_source.startswith("central_flank_targeted_")
        variant_invariance_group_id = (
            _sanity_invariance_group_id(variant)
            if variant_source.startswith("semantic_balanced_") or is_targeted_central_flank
            else invariance_group_id
        )
        hard_negatives = _legal_sanity_hard_negatives(
            variant["fen"],
            variant["side"],
            variant["expected_move"],
            old_move=old_move,
            limit=hard_negative_limit,
        )
        semantic_negatives = _semantic_negative_moves(
            variant["fen"],
            variant["side"],
            variant["expected_move"],
            old_move=old_move,
            limit=hard_negative_limit,
        )
        hard_negatives = list(dict.fromkeys([*semantic_negatives, *hard_negatives]))[:hard_negative_limit]
        base_weight = 1.45 if variant.get("variant_difficulty") == "easy" else 1.3 if variant.get("variant_difficulty") == "medium" else 1.1
        if is_targeted_central_flank and variant_semantic in CENTRAL_FLANK_FOCUS_SEMANTICS:
            base_weight = round(base_weight + 0.45, 4)
        variant_flank_context = variant.get("flank_context_features") or _flank_context_features(variant["fen"], variant["side"])
        rows.append(
            {
                "fen": variant["fen"],
                "side": variant["side"],
                "move_uci": variant["expected_move"],
                "target": 1.0,
                "weight": base_weight,
                "source": "central_flank_targeted_curriculum_replay" if is_targeted_central_flank else "sanity_curriculum_variant_replay",
                "category": "mistake_retention",
                "case_id": case.get("case_id"),
                "variant_id": variant.get("variant_id"),
                "variant_split": "train",
                "variant_difficulty": variant.get("variant_difficulty"),
                "normalized_fen_hash": variant.get("normalized_fen_hash"),
                "expected_move": variant["expected_move"],
                "expected_semantic": _move_semantic_class(variant["fen"], variant["side"], variant["expected_move"]),
                "semantic_hard_negatives": semantic_negatives,
                "semantic_pair_contrast": variant.get("semantic_pair_contrast") or {
                    "positive_semantic": variant_semantic,
                    "negative_semantics": [
                        semantic
                        for semantic in CENTRAL_FLANK_FOCUS_SEMANTICS
                        if semantic != variant_semantic
                    ],
                } if variant_semantic in CENTRAL_FLANK_FOCUS_SEMANTICS else {},
                "curriculum_focus": variant.get("curriculum_focus") or ("central_flank_semantic_improvement" if is_targeted_central_flank else ""),
                "board_semantics_features": _board_semantics_features(variant["fen"], variant["side"]),
                "flank_context_features": variant_flank_context,
                "flank_context_feature_vector": _flank_context_feature_vector(variant_flank_context),
                "flank_context_feature_injection": variant_semantic == FLANK_REPAIR_SEMANTIC,
                "flank_reason_tag": variant.get("flank_reason_tag") or _flank_reason_tag_for_move(variant["fen"], variant["side"], variant["expected_move"]),
                "context_conditioned": variant_semantic == FLANK_REPAIR_SEMANTIC,
                "hard_negatives": hard_negatives,
                "invariance_group_id": variant_invariance_group_id,
                "pairwise_role": "positive_variant",
                "curriculum_stage": f"{variant.get('variant_difficulty')}_seen_variant",
            }
        )
    retention_rows = []
    for prior_case in _sanity_learning_cases_from_samples(samples):
        prior_before = _evaluate_sanity_learning_position(engine_alias, before_model_path, prior_case)
        if not prior_before.get("expected_is_top1"):
            continue
        prior_id = str(prior_case.get("case_id") or "")
        if prior_id == str(case.get("case_id") or ""):
            continue
        prior_hard_negatives = _legal_sanity_hard_negatives(
            prior_case["fen"],
            prior_case["side"],
            prior_case["expected_move"],
            old_move=str(prior_before.get("top1") or ""),
            limit=hard_negative_limit,
        )
        prior_semantic_negatives = _semantic_negative_moves(
            prior_case["fen"],
            prior_case["side"],
            prior_case["expected_move"],
            old_move=str(prior_before.get("top1") or ""),
            limit=hard_negative_limit,
        )
        prior_hard_negatives = list(dict.fromkeys([*prior_semantic_negatives, *prior_hard_negatives]))[:hard_negative_limit]
        retention_rows.append(
            {
                "fen": prior_case["fen"],
                "side": prior_case["side"],
                "move_uci": prior_case["expected_move"],
                "target": 1.0,
                "weight": 3.0,
                "source": "sanity_prior_retention_replay",
                "category": "mistake_retention",
                "case_id": prior_case.get("case_id"),
                "variant_id": f"{prior_case.get('case_id')}:prior_retention_exact",
                "variant_split": "retention",
                "variant_difficulty": "exact",
                "normalized_fen_hash": _normalized_fen_hash(str(prior_case.get("fen") or "")),
                "expected_move": prior_case["expected_move"],
                "expected_semantic": _move_semantic_class(prior_case["fen"], prior_case["side"], prior_case["expected_move"]),
                "semantic_hard_negatives": prior_semantic_negatives,
                "board_semantics_features": _board_semantics_features(prior_case["fen"], prior_case["side"]),
                "flank_context_features": _flank_context_features(prior_case["fen"], prior_case["side"]),
                "flank_context_feature_vector": _flank_context_feature_vector(_flank_context_features(prior_case["fen"], prior_case["side"])),
                "flank_context_feature_injection": _move_semantic_class(prior_case["fen"], prior_case["side"], prior_case["expected_move"]) == FLANK_REPAIR_SEMANTIC,
                "flank_reason_tag": _flank_reason_tag_for_move(prior_case["fen"], prior_case["side"], prior_case["expected_move"]),
                "hard_negatives": prior_hard_negatives,
                "invariance_group_id": _sanity_invariance_group_id(prior_case),
                "pairwise_role": "retention_anchor",
                "curriculum_stage": "prior_exact_retention",
            }
        )
    rows.extend(retention_rows)
    semantic_sampling = _apply_semantic_class_balanced_weights(rows)
    semantic_distribution = {
        "train": _semantic_class_distribution(rows, include_negatives=True),
        "validation": _semantic_class_distribution(list(curriculum.get("validation") or []), include_negatives=True),
        "held_out": _semantic_class_distribution(list(curriculum.get("held_out") or []), include_negatives=True),
        "clean_gate_cases": _semantic_class_distribution(list(curriculum.get("clean_gate_cases") or []), include_negatives=True),
    }
    semantic_distribution_by_split = {
        "train": _semantic_positive_distribution(rows),
        "validation": _semantic_positive_distribution(list(curriculum.get("validation") or [])),
        "held_out": _semantic_positive_distribution(list(curriculum.get("held_out") or [])),
        "clean_gate_cases": _semantic_positive_distribution(list(curriculum.get("clean_gate_cases") or [])),
    }
    semantic_coverage_by_split = {
        split: _semantic_coverage_from_counts(counts)
        for split, counts in semantic_distribution_by_split.items()
    }
    train_to_gate_gap = _train_to_gate_semantic_gap(
        semantic_distribution_by_split.get("train") or {},
        semantic_distribution_by_split.get("clean_gate_cases") or {},
    )
    return {
        "case": case,
        "before_exact": before_exact,
        "rows": rows,
        "seen_variants": train_variants,
        "train_variants": train_variants,
        "retention_rows": retention_rows,
        "curriculum": curriculum,
        "semantic_class_distribution": semantic_distribution,
        "semantic_distribution_by_split": semantic_distribution_by_split,
        "semantic_coverage_by_split": semantic_coverage_by_split,
        "train_to_gate_semantic_gap": train_to_gate_gap,
        "semantic_sampling": semantic_sampling,
        "effective_sample_weight_by_semantic": semantic_sampling.get("sample_weight_by_semantic") or {},
        "train_effective_distribution": (semantic_sampling.get("effective_distribution") or {}).get("effective_weight") or {},
        "smoothing": {
            "trusted_replays": int(trusted_replays or 0),
            "hard_negative_limit": hard_negative_limit,
            "retention_rows_added": len(retention_rows),
            "hard_train_variants_added": len([row for row in train_variants if str(row.get("variant_difficulty") or "") == "hard"]),
            "early_checkpoint_warmup": bool((curriculum.get("warmup") or {}).get("early_checkpoint_warmup")),
        },
        "central_flank_targeted_curriculum": {
            "enabled": True,
            "focus_semantics": list(CENTRAL_FLANK_FOCUS_SEMANTICS),
            "train_rows_added": len([row for row in rows if row.get("source") == "central_flank_targeted_curriculum_replay"]),
            "train_offsets": list(CENTRAL_FLANK_TARGETED_TRAIN_OFFSETS),
            "validation_offsets": list(CENTRAL_FLANK_TARGETED_VALIDATION_OFFSETS),
            "semantic_pair_contrast": "e/d/flank positives use the other central/flank semantics as hard negatives",
            "development_strategy": "preserve existing multi-good credit; do not target development in exp26",
        },
        "invariance_context_key_examples": [
            {
                "variant_id": row.get("variant_id"),
                "variant_split": row.get("variant_split"),
                "variant_difficulty": row.get("variant_difficulty"),
                "expected_move": row.get("expected_move"),
                "context_key": _validation_invariance_context_key(
                    str(row.get("fen") or ""),
                    str(row.get("side") or ""),
                    str(row.get("expected_move") or row.get("move_uci") or ""),
                ),
            }
            for row in rows[:8]
        ],
    }


def _evaluate_sanity_learning_position(engine_alias: str, model_path: Path, case: dict) -> dict:
    fen = str(case.get("fen") or "")
    side = str(case.get("side") or "white")
    expected = str(case.get("expected_move") or "").lower()
    board_state = {"__fen__": fen}
    decision_context = {
        "variant_difficulty": str(case.get("variant_difficulty") or "exact"),
        "prior_retention_stable": True,
        "deterministic_confidence": 0.75,
    }
    move = _choose_engine_move_for_eval(engine_alias, board_state, side, model_path, fusion_mode="balanced_fusion", decision_context=decision_context)
    top1 = _move_uci_from_engine_move(move)
    top3 = _rank_deterministic_top3(engine_alias, board_state, side, model_path, move)
    return {
        "case_id": str(case.get("case_id") or ""),
        "fen": fen,
        "side": side,
        "expected_move": expected,
        "top1": top1,
        "top3": top3,
        "expected_in_top3": expected in top3,
        "expected_is_top1": top1 == expected,
        "variation_moves": list(case.get("variation_moves") or []),
    }


def _evaluate_prior_sanity_case_retention(engine_alias: str, before_model_path: Path, after_model_path: Path, samples: list[dict]) -> dict:
    rows = []
    for case in _sanity_learning_cases_from_samples(samples):
        before = _evaluate_sanity_learning_position(engine_alias, before_model_path, case)
        if not before.get("expected_is_top1"):
            continue
        after = _evaluate_sanity_learning_position(engine_alias, after_model_path, case)
        rows.append(
            {
                "case_id": case.get("case_id"),
                "expected_move": case.get("expected_move"),
                "before_top1": before.get("top1"),
                "after_top1": after.get("top1"),
                "retained": bool(after.get("expected_is_top1")),
                "before": before,
                "after": after,
            }
        )
    failures = [row for row in rows if not row.get("retained")]
    return {
        "supported": True,
        "checked_count": len(rows),
        "retained_count": len(rows) - len(failures),
        "failed_count": len(failures),
        "learning_signal": not failures,
        "cases": rows,
        "failures": failures,
        "reason": "all prior learned sanity cases retained" if not failures else "one or more prior learned sanity cases regressed",
    }


def _evaluate_engine_raw_policy_position(engine_alias: str, model_path: Path, case: dict, *, old_move: str = "") -> dict:
    fen = str(case.get("fen") or "")
    side = str(case.get("side") or "white")
    expected = str(case.get("expected_move") or "").lower()
    board_state = {"__fen__": fen}
    if not expected:
        return {"supported": False, "reason": "missing expected_move"}
    try:
        if engine_alias == "exp3":
            rows = rank_experiment_dl_policy_moves(board_state, side, model_path=model_path)
        elif engine_alias == "exp4":
            rows = rank_experiment_pv_policy_moves(board_state, side, model_path=model_path)
        elif engine_alias == "exp5":
            rows = rank_experiment_nnue_policy_moves(board_state, side, model_path=model_path)
        else:
            return {"supported": False, "reason": f"raw policy probe is not available for {engine_alias}"}
    except Exception as exc:
        return {"supported": False, "reason": str(exc)}
    expected_row = next((row for row in rows if str(row.get("move") or "") == expected), None)
    if expected_row is None:
        return {"supported": False, "reason": "expected move missing from legal policy rows", "expected_move": expected}
    top1 = str((rows[0] or {}).get("move") or "") if rows else ""
    old = str(old_move or top1).lower()
    old_row = next((row for row in rows if str(row.get("move") or "") == old), None)
    expected_score = float(expected_row.get("raw_policy_score") or 0.0)
    old_score = float((old_row or {}).get("raw_policy_score") or 0.0)
    return {
        "supported": True,
        "case_id": str(case.get("case_id") or ""),
        "fen": fen,
        "side": side,
        "expected_move": expected,
        "raw_policy_top1": top1,
        "raw_policy_top3": [str(row.get("move") or "") for row in rows[:3]],
        "expected_rank": int(expected_row.get("raw_policy_rank") or 0),
        "expected_probability": float(expected_row.get("policy_probability") or 0.0),
        "expected_logit": expected_score,
        "old_move": old,
        "old_move_rank": int((old_row or {}).get("raw_policy_rank") or 0),
        "old_move_probability": float((old_row or {}).get("policy_probability") or 0.0),
        "old_move_logit": old_score,
        "margin_vs_old_move": round(expected_score - old_score, 8),
        "expected_is_raw_top1": top1 == expected,
    }


def _evaluate_sanity_learning_position_batch(
    engine_alias: str,
    model_path: Path,
    cases: list[dict],
    *,
    label: str,
) -> list[dict]:
    total = len(cases or [])
    started = time.perf_counter()
    every = _progress_every(total)
    _progress_bar(label, 0, total, started=started)
    rows = []
    for index, case in enumerate(cases or [], start=1):
        rows.append(_evaluate_sanity_learning_position(engine_alias, model_path, case))
        if index == total or index == 1 or index % every == 0:
            _progress_bar(label, index, total, started=started)
    return rows


def _evaluate_raw_policy_position_batch(
    engine_alias: str,
    model_path: Path,
    cases: list[dict],
    *,
    old_move: str = "",
    label: str,
) -> list[dict]:
    total = len(cases or [])
    started = time.perf_counter()
    every = _progress_every(total)
    _progress_bar(label, 0, total, started=started)
    rows = []
    for index, case in enumerate(cases or [], start=1):
        rows.append(_evaluate_engine_raw_policy_position(engine_alias, model_path, case, old_move=old_move))
        if index == total or index == 1 or index % every == 0:
            _progress_bar(label, index, total, started=started)
    return rows


def _evaluate_exp4_raw_policy_position(model_path: Path, case: dict, *, old_move: str = "") -> dict:
    return _evaluate_engine_raw_policy_position("exp4", model_path, case, old_move=old_move)


def _engine_decision_breakdown(engine_alias: str, model_path: Path, case: dict, *, old_move: str = "", fusion_mode: str = "balanced_fusion") -> dict:
    fen = str(case.get("fen") or "")
    side = str(case.get("side") or "white")
    expected = str(case.get("expected_move") or "").lower()
    watched = [move for move in [expected, old_move] if move]
    decision_context = {
        "variant_difficulty": str(case.get("variant_difficulty") or "exact"),
        "prior_retention_stable": True,
        "deterministic_confidence": 0.75,
    }
    try:
        if engine_alias == "exp3":
            return explain_experiment_dl_decision(
                {"__fen__": fen},
                side,
                model_path=model_path,
                search_profile="fast",
                watched_moves=watched,
                fusion_mode=fusion_mode,
                decision_context=decision_context,
            )
        if engine_alias == "exp4":
            return explain_experiment_pv_decision(
                {"__fen__": fen},
                side,
                model_path=model_path,
                search_profile="fast",
                watched_moves=watched,
                fusion_mode=fusion_mode,
                decision_context=decision_context,
                decision_mode="mcts",
            )
        if engine_alias == "exp5":
            return explain_experiment_nnue_decision(
                {"__fen__": fen},
                side,
                model_path=model_path,
                search_profile="fast",
                watched_moves=watched,
            )
        return {"supported": False, "reason": f"decision breakdown is not available for {engine_alias}", "expected_move": expected, "old_move": old_move}
    except Exception as exc:
        return {"supported": False, "reason": str(exc), "expected_move": expected, "old_move": old_move}


def _exp4_decision_breakdown(model_path: Path, case: dict, *, old_move: str = "") -> dict:
    return _engine_decision_breakdown("exp4", model_path, case, old_move=old_move)


def _policy_embedding_similarity(exact_raw: dict, variant_raw_rows: list[dict]) -> dict:
    if not exact_raw.get("supported") or not variant_raw_rows:
        return {"supported": False, "avg_similarity": None, "cases": []}
    exact_logit = float(exact_raw.get("expected_logit") or 0.0)
    cases = []
    for row in variant_raw_rows:
        if not row.get("supported"):
            continue
        delta = abs(float(row.get("expected_logit") or 0.0) - exact_logit)
        cases.append(
            {
                "case_id": row.get("case_id"),
                "expected_rank": row.get("expected_rank"),
                "expected_logit": row.get("expected_logit"),
                "logit_delta_from_exact": round(delta, 8),
                "similarity": round(1.0 / (1.0 + delta), 4),
            }
        )
    if not cases:
        return {"supported": False, "avg_similarity": None, "cases": []}
    return {
        "supported": True,
        "avg_similarity": round(sum(float(row["similarity"]) for row in cases) / max(1, len(cases)), 4),
        "cases": cases,
    }


def _failed_feature_groups(failed_cases: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for case in failed_cases:
        for feature in case.get("blocking_features") or []:
            counts[str(feature)] = counts.get(str(feature), 0) + 1
    return [
        {"blocking_feature": feature, "count": count}
        for feature, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _case_ids_for_label_quality(label_quality: dict, *, quality: str | None = None, split: str | None = None, difficulty: str | None = None) -> set[str]:
    ids: set[str] = set()
    for row in label_quality.get("cases") or []:
        if quality is not None and str(row.get("label_quality") or "") != quality:
            continue
        if split is not None and str(row.get("variant_split") or "") != split:
            continue
        if difficulty is not None and str(row.get("variant_difficulty") or "") != difficulty:
            continue
        case_id = str(row.get("case_id") or "")
        if case_id:
            ids.add(case_id)
    return ids


def _variant_performance_for_case_ids(
    variants: list[dict],
    final_rows: list[dict],
    raw_rows: list[dict],
    case_ids: set[str],
) -> dict:
    variant_by_id = {str(row.get("case_id") or ""): row for row in variants or []}
    final_by_id = {str(row.get("case_id") or ""): row for row in final_rows or []}
    raw_by_id = {str(row.get("case_id") or ""): row for row in raw_rows or []}
    rows = []
    final_hits = 0
    raw_hits = 0
    for case_id in sorted(case_ids):
        variant = variant_by_id.get(case_id) or {}
        final_row = final_by_id.get(case_id) or {}
        raw_row = raw_by_id.get(case_id) or {}
        fen = str(variant.get("fen") or "")
        side = str(variant.get("side") or "")
        expected_move = str(variant.get("expected_move") or "")
        final_hit = bool(final_row.get("expected_is_top1"))
        raw_hit = bool(raw_row.get("expected_is_raw_top1"))
        final_hits += 1 if final_hit else 0
        raw_hits += 1 if raw_hit else 0
        rows.append(
            {
                "case_id": case_id,
                "variant_split": variant.get("variant_split"),
                "variant_difficulty": variant.get("variant_difficulty"),
                "expected_move": expected_move,
                "expected_semantic": variant.get("expected_semantic") or _move_semantic_class(fen, side, expected_move),
                "final_top1": final_row.get("top1"),
                "final_semantic": _move_semantic_class(fen, side, str(final_row.get("top1") or "")),
                "final_top3": final_row.get("top3"),
                "raw_policy_top1": raw_row.get("raw_policy_top1"),
                "raw_policy_semantic": _move_semantic_class(fen, side, str(raw_row.get("raw_policy_top1") or "")),
                "raw_policy_top3": raw_row.get("raw_policy_top3"),
                "expected_rank": raw_row.get("expected_rank"),
                "board_semantics_features": variant.get("board_semantics_features") or _board_semantics_features(fen, side),
                "final_pass": final_hit,
                "raw_policy_pass": raw_hit,
            }
        )
    count = len(rows)
    return {
        "count": count,
        "final_hits": final_hits,
        "raw_policy_hits": raw_hits,
        "final_pass_rate": round(final_hits / max(1, count), 4),
        "raw_policy_pass_rate": round(raw_hits / max(1, count), 4),
        "cases": rows,
    }


def _development_multi_good_credit(
    *,
    variant: dict,
    final_row: dict,
    raw_row: dict,
    label_quality_row: dict | None = None,
) -> dict:
    expected = str(variant.get("expected_move") or "").lower()
    semantic = str(variant.get("expected_semantic") or variant.get("semantic_class") or "")
    final_top1 = str(final_row.get("top1") or "")
    final_top3 = [str(item) for item in final_row.get("top3") or []]
    raw_top3 = [str(item) for item in raw_row.get("raw_policy_top3") or []]
    static_delta = (label_quality_row or {}).get("static_cp_delta")
    is_development = semantic == "development_move"
    expected_top1 = final_top1 == expected
    expected_in_top3 = expected in final_top3 or expected in raw_top3
    static_equivalent = bool(static_delta is not None and float(static_delta) >= -50.0)
    credit = bool(is_development and (expected_top1 or expected_in_top3 or static_equivalent))
    if expected_top1:
        reason = "expected_top1"
    elif expected in final_top3:
        reason = "expected_in_final_top3"
    elif expected in raw_top3:
        reason = "expected_in_raw_top3"
    elif static_equivalent:
        reason = "static_delta_within_multi_good_threshold"
    else:
        reason = ""
    return {
        "is_development_move": is_development,
        "multi_good_move_case": bool(is_development and (expected_in_top3 or static_equivalent)),
        "multi_good_credit_applied": credit,
        "multi_good_credit_reason": reason,
        "static_cp_delta": static_delta,
        "expected_in_final_top3": expected in final_top3,
        "expected_in_raw_top3": expected in raw_top3,
    }


def _balanced_multi_good_credit(
    *,
    variant: dict,
    final_row: dict,
    raw_row: dict,
    label_quality_row: dict | None = None,
) -> dict:
    development_credit = _development_multi_good_credit(
        variant=variant,
        final_row=final_row,
        raw_row=raw_row,
        label_quality_row=label_quality_row,
    )
    semantic = str(variant.get("expected_semantic") or variant.get("semantic_class") or "")
    expected = str(variant.get("expected_move") or "").lower()
    final_top3 = [str(item) for item in final_row.get("top3") or []]
    raw_top3 = [str(item) for item in raw_row.get("raw_policy_top3") or []]
    expected_top1 = bool(final_row.get("expected_is_top1"))
    expected_in_top3 = bool(expected and (expected in final_top3 or expected in raw_top3))
    opening_or_balanced_semantic = semantic in BALANCED_PROMOTION_SEMANTIC_CLASSES
    credit = bool(
        expected_top1
        or development_credit.get("multi_good_credit_applied")
        or (opening_or_balanced_semantic and expected_in_top3)
    )
    if expected_top1:
        reason = "expected_top1"
    elif development_credit.get("multi_good_credit_applied"):
        reason = f"development_{development_credit.get('multi_good_credit_reason') or 'multi_good'}"
    elif expected in final_top3:
        reason = "expected_in_final_top3"
    elif expected in raw_top3:
        reason = "expected_in_raw_top3"
    else:
        reason = ""
    return {
        "balanced_semantic": opening_or_balanced_semantic,
        "multi_good_credit_applied": credit,
        "multi_good_credit_reason": reason,
        "expected_in_final_top3": expected in final_top3,
        "expected_in_raw_top3": expected in raw_top3,
        "development_multi_good_credit": development_credit,
    }


def _balanced_gate_performance_for_case_ids(
    variants: list[dict],
    final_rows: list[dict],
    raw_rows: list[dict],
    case_ids: set[str],
    *,
    label_quality: dict | None = None,
) -> dict:
    variant_by_id = {str(row.get("case_id") or ""): row for row in variants or []}
    final_by_id = {str(row.get("case_id") or ""): row for row in final_rows or []}
    raw_by_id = {str(row.get("case_id") or ""): row for row in raw_rows or []}
    label_by_id = _quality_rows_by_case(label_quality or {})
    rows = []
    hits = 0
    raw_hits = 0
    for case_id in sorted(case_ids):
        variant = variant_by_id.get(case_id) or {}
        final_row = final_by_id.get(case_id) or {}
        raw_row = raw_by_id.get(case_id) or {}
        fen = str(variant.get("fen") or "")
        side = str(variant.get("side") or "")
        expected_move = str(variant.get("expected_move") or "")
        semantic = str(variant.get("expected_semantic") or variant.get("semantic_class") or _move_semantic_class(fen, side, expected_move))
        if semantic not in BALANCED_PROMOTION_SEMANTIC_CLASSES:
            continue
        strict_hit = bool(final_row.get("expected_is_top1"))
        raw_hit = bool(raw_row.get("expected_is_raw_top1"))
        development_credit = _development_multi_good_credit(
            variant=variant,
            final_row=final_row,
            raw_row=raw_row,
            label_quality_row=label_by_id.get(case_id) or {},
        )
        credited_hit = bool(strict_hit or development_credit.get("multi_good_credit_applied"))
        hits += 1 if credited_hit else 0
        raw_hits += 1 if raw_hit else 0
        rows.append(
            {
                "case_id": case_id,
                "variant_split": variant.get("variant_split"),
                "variant_difficulty": variant.get("variant_difficulty"),
                "expected_move": expected_move,
                "expected_semantic": semantic,
                "final_top1": final_row.get("top1"),
                "final_semantic": _move_semantic_class(fen, side, str(final_row.get("top1") or "")),
                "final_top3": final_row.get("top3"),
                "raw_policy_top1": raw_row.get("raw_policy_top1"),
                "raw_policy_semantic": _move_semantic_class(fen, side, str(raw_row.get("raw_policy_top1") or "")),
                "raw_policy_top3": raw_row.get("raw_policy_top3"),
                "expected_rank": raw_row.get("expected_rank"),
                "strict_final_pass": strict_hit,
                "balanced_final_pass": credited_hit,
                "raw_policy_pass": raw_hit,
                **development_credit,
            }
        )
    count = len(rows)
    return {
        "count": count,
        "balanced_hits": hits,
        "raw_policy_hits": raw_hits,
        "balanced_pass_rate": round(hits / max(1, count), 4),
        "raw_policy_pass_rate": round(raw_hits / max(1, count), 4),
        "cases": rows,
    }


def _central_flank_failed_case_analysis(
    *,
    engine_alias: str,
    model_path: Path,
    variants: list[dict],
    final_rows: list[dict],
    raw_rows: list[dict],
    case_ids: set[str],
    label_quality: dict | None = None,
) -> dict:
    variant_by_id = {str(row.get("case_id") or ""): row for row in variants or []}
    final_by_id = {str(row.get("case_id") or ""): row for row in final_rows or []}
    raw_by_id = {str(row.get("case_id") or ""): row for row in raw_rows or []}
    label_by_id = _quality_rows_by_case(label_quality or {})
    cases: list[dict] = []
    by_semantic = {
        semantic: {
            "failed_count": 0,
            "raw_policy_fail_count": 0,
            "final_decision_fail_count": 0,
            "confusion_targets": {},
        }
        for semantic in CENTRAL_FLANK_FOCUS_SEMANTICS
    }
    for case_id in sorted(case_ids):
        variant = variant_by_id.get(case_id) or {}
        semantic = str(variant.get("expected_semantic") or variant.get("semantic_class") or "")
        if semantic not in CENTRAL_FLANK_FOCUS_SEMANTICS:
            continue
        final_row = final_by_id.get(case_id) or {}
        raw_row = raw_by_id.get(case_id) or {}
        if bool(final_row.get("expected_is_top1")):
            continue
        fen = str(variant.get("fen") or "")
        side = str(variant.get("side") or "")
        final_top1 = str(final_row.get("top1") or "")
        raw_top1 = str(raw_row.get("raw_policy_top1") or "")
        final_semantic = _move_semantic_class(fen, side, final_top1)
        raw_semantic = _move_semantic_class(fen, side, raw_top1)
        raw_policy_fail = not bool(raw_row.get("expected_is_raw_top1"))
        failure_type = "raw_policy_fail" if raw_policy_fail else "final_decision_fail"
        audit = _case_decision_audit(engine_alias=engine_alias, model_path=model_path, case=variant)
        bucket = by_semantic[semantic]
        bucket["failed_count"] += 1
        bucket["raw_policy_fail_count"] += 1 if raw_policy_fail else 0
        bucket["final_decision_fail_count"] += 0 if raw_policy_fail else 1
        bucket["confusion_targets"][final_semantic] = int(bucket["confusion_targets"].get(final_semantic) or 0) + 1
        quality = label_by_id.get(case_id) or {}
        cases.append(
            {
                "case_id": case_id,
                "semantic_class": semantic,
                "difficulty": variant.get("variant_difficulty") or variant.get("difficulty"),
                "expected_move": variant.get("expected_move"),
                "final_top1": final_top1,
                "final_top3": final_row.get("top3"),
                "final_semantic": final_semantic,
                "raw_policy_top1": raw_top1,
                "raw_policy_top3": raw_row.get("raw_policy_top3"),
                "raw_policy_semantic": raw_semantic,
                "expected_rank": raw_row.get("expected_rank"),
                "expected_margin_vs_old_move": raw_row.get("margin_vs_old_move"),
                "failure_type": failure_type,
                "semantic_confusion_target": final_semantic,
                "static_best_move": audit.get("static_best_move"),
                "static_cp_delta": quality.get("static_cp_delta", audit.get("static_cp_delta")),
                "search_best_move": audit.get("search_best_move"),
                "search_score_delta": audit.get("search_score_delta"),
                "static_eval_score": audit.get("static_eval_score"),
                "search_score": audit.get("search_score"),
                "final_score": audit.get("final_score"),
                "chosen_reason": audit.get("chosen_reason"),
                "rejection_reason": audit.get("rejection_reason"),
                "decision_path": "raw policy did not rank expected top1" if raw_policy_fail else "raw policy selected expected but final decision chose another move",
                "board_semantics_features": variant.get("board_semantics_features") or _board_semantics_features(fen, side),
            }
        )
    return {
        "supported": True,
        "source": "exp26_central_flank_failed_case_analysis",
        "focus_semantics": list(CENTRAL_FLANK_FOCUS_SEMANTICS),
        "case_count": len(cases),
        "by_semantic": by_semantic,
        "cases": cases,
        "failed_top3_by_semantic": {
            semantic: [row for row in cases if row.get("semantic_class") == semantic][:3]
            for semantic in CENTRAL_FLANK_FOCUS_SEMANTICS
        },
    }


def _flank_label_audit_for_cases(cases: list[dict], label_quality: dict | None = None) -> dict:
    label_by_id = _quality_rows_by_case(label_quality or {})
    rows: list[dict] = []
    reason_distribution = {tag: 0 for tag in FLANK_REASON_TAGS}
    by_difficulty = {
        difficulty: {"total": 0, "clean": 0, "questionable": 0, "invalid": 0}
        for difficulty in ["easy", "medium", "hard"]
    }
    for case in cases or []:
        semantic = str(case.get("expected_semantic") or case.get("semantic_class") or "")
        if semantic != FLANK_REPAIR_SEMANTIC:
            continue
        case_id = str(case.get("case_id") or "")
        fen = str(case.get("fen") or "")
        side = str(case.get("side") or "")
        expected = str(case.get("expected_move") or "").lower()
        quality = label_by_id.get(case_id) or (case.get("label_quality_detail") if isinstance(case.get("label_quality_detail"), dict) else {}) or (case.get("label_quality") if isinstance(case.get("label_quality"), dict) else {})
        quality_name = str(quality.get("label_quality") or case.get("label_quality") or "unknown")
        if quality_name not in {"clean", "questionable", "invalid"}:
            quality_name = "unknown"
        difficulty = str(case.get("variant_difficulty") or case.get("difficulty") or "unknown")
        if difficulty in by_difficulty:
            by_difficulty[difficulty]["total"] += 1
            if quality_name in by_difficulty[difficulty]:
                by_difficulty[difficulty][quality_name] += 1
        try:
            board = chess.Board(fen)
            legal = chess.Move.from_uci(expected) in board.legal_moves
            semantic_matches = _move_semantic_class_for_board(board, expected) == FLANK_REPAIR_SEMANTIC
        except Exception:
            legal = False
            semantic_matches = False
        context_features = case.get("flank_context_features") or _flank_context_features(fen, side)
        reason_tag = str(case.get("flank_reason_tag") or "")
        if reason_tag not in reason_distribution:
            reason_tag = _flank_reason_tag_for_move(fen, side, expected)
        reason_distribution[reason_tag] = int(reason_distribution.get(reason_tag) or 0) + 1
        bad_random = reason_tag == "bad_random_flank_push"
        style_like = bool(
            quality_name == "questionable"
            or float(quality.get("static_cp_delta") or 0.0) < SANITY_LABEL_QUESTIONABLE_CP_DELTA
            or not semantic_matches
            or bad_random
        )
        rows.append(
            {
                "case_id": case_id,
                "difficulty": difficulty,
                "fen": fen,
                "expected_move": expected,
                "label_quality": quality_name,
                "legal_moves_contains_expected": legal,
                "semantic_matches_expected": semantic_matches,
                "flank_context_features": context_features,
                "reason_tag": reason_tag,
                "flank_reason_tag": reason_tag,
                "bad_random_flank_push": bad_random,
                "static_best_move": quality.get("static_best_move") or case.get("static_best_move"),
                "static_cp_delta": quality.get("static_cp_delta") if quality.get("static_cp_delta") is not None else case.get("static_cp_delta"),
                "source_reason": case.get("source_reason"),
                "balanced_gate_eligible": bool(quality_name == "clean" and legal and semantic_matches and not bad_random),
                "questionable_style_or_bad_label": style_like,
                "reason": quality.get("reason") or case.get("label_quality_reason") or "",
            }
        )
    return {
        "supported": True,
        "source": "exp28_flank_label_audit_v2",
        "semantic_class": FLANK_REPAIR_SEMANTIC,
        "case_count": len(rows),
        "clean_count": sum(1 for row in rows if row.get("label_quality") == "clean"),
        "questionable_count": sum(1 for row in rows if row.get("label_quality") == "questionable"),
        "invalid_count": sum(1 for row in rows if row.get("label_quality") == "invalid"),
        "flank_reason_distribution": reason_distribution,
        "bad_random_flank_push_count": sum(1 for row in rows if row.get("bad_random_flank_push")),
        "excluded_bad_random_cases": [row for row in rows if row.get("bad_random_flank_push")],
        "by_difficulty": by_difficulty,
        "questionable_or_invalid_cases": [
            row for row in rows
            if row.get("label_quality") in {"questionable", "invalid"} or row.get("questionable_style_or_bad_label")
        ],
        "cases": rows,
    }


def _flank_difficulty_performance(
    variants: list[dict],
    final_rows: list[dict],
    raw_rows: list[dict],
    case_ids: set[str],
    *,
    label_quality: dict | None = None,
) -> dict:
    by_difficulty = {}
    for difficulty in ["easy", "medium", "hard"]:
        ids = {
            str(variant.get("case_id") or "")
            for variant in variants or []
            if str(variant.get("case_id") or "") in case_ids
            and str(variant.get("expected_semantic") or variant.get("semantic_class") or "") == FLANK_REPAIR_SEMANTIC
            and str(variant.get("variant_difficulty") or variant.get("difficulty") or "") == difficulty
        }
        row = _balanced_gate_performance_for_case_ids(
            variants,
            final_rows,
            raw_rows,
            ids,
            label_quality=label_quality,
        )
        by_difficulty[difficulty] = {
            "total": int(row.get("count") or 0),
            "passed": int(row.get("balanced_hits") or 0),
            "pass_rate": row.get("balanced_pass_rate"),
            "raw_policy_passed": int(row.get("raw_policy_hits") or 0),
            "raw_policy_pass_rate": row.get("raw_policy_pass_rate"),
            "cases": row.get("cases") or [],
        }
    hard_total = int((by_difficulty.get("hard") or {}).get("total") or 0)
    return {
        "supported": True,
        "source": "exp27_flank_difficulty_performance",
        "semantic_class": FLANK_REPAIR_SEMANTIC,
        "by_difficulty": by_difficulty,
        "hard_coverage_complete": hard_total >= SEMANTIC_BALANCED_GATE_MIN_PER_DIFFICULTY,
        "required_hard_cases": SEMANTIC_BALANCED_GATE_MIN_PER_DIFFICULTY,
    }


def _central_vs_flank_boundary_report(confusion: dict) -> dict:
    matrix = confusion.get("matrix") or {}
    raw_matrix = confusion.get("raw_policy_matrix") or {}

    def pick(src: dict, expected: str, predicted: str) -> int:
        return int(((src.get(expected) or {}).get(predicted)) or 0)

    central_to_flank = (
        pick(matrix, "e_pawn_central_break", "flank_pawn_push")
        + pick(matrix, "d_pawn_central_break", "flank_pawn_push")
    )
    flank_to_central = (
        pick(matrix, "flank_pawn_push", "e_pawn_central_break")
        + pick(matrix, "flank_pawn_push", "d_pawn_central_break")
    )
    raw_central_to_flank = (
        pick(raw_matrix, "e_pawn_central_break", "flank_pawn_push")
        + pick(raw_matrix, "d_pawn_central_break", "flank_pawn_push")
    )
    raw_flank_to_central = (
        pick(raw_matrix, "flank_pawn_push", "e_pawn_central_break")
        + pick(raw_matrix, "flank_pawn_push", "d_pawn_central_break")
    )
    focus_rows = [
        row for row in confusion.get("cases") or []
        if str(row.get("expected_semantic") or "") in CENTRAL_VS_FLANK_BOUNDARY_SEMANTICS
    ]
    return {
        "supported": True,
        "source": "exp27_central_vs_flank_boundary_report",
        "focus_semantics": list(CENTRAL_VS_FLANK_BOUNDARY_SEMANTICS),
        "case_count": len(focus_rows),
        "matrix": {
            semantic: matrix.get(semantic) or {}
            for semantic in CENTRAL_VS_FLANK_BOUNDARY_SEMANTICS
        },
        "raw_policy_matrix": {
            semantic: raw_matrix.get(semantic) or {}
            for semantic in CENTRAL_VS_FLANK_BOUNDARY_SEMANTICS
        },
        "central_to_flank_confusion": central_to_flank,
        "flank_to_central_confusion": flank_to_central,
        "raw_policy_central_to_flank_confusion": raw_central_to_flank,
        "raw_policy_flank_to_central_confusion": raw_flank_to_central,
        "cases": focus_rows,
    }


def _semantic_confusion_for_case_ids(
    variants: list[dict],
    final_rows: list[dict],
    raw_rows: list[dict],
    case_ids: set[str],
) -> dict:
    variant_by_id = {str(row.get("case_id") or ""): row for row in variants or []}
    final_by_id = {str(row.get("case_id") or ""): row for row in final_rows or []}
    raw_by_id = {str(row.get("case_id") or ""): row for row in raw_rows or []}
    matrix: dict[str, dict[str, int]] = {}
    raw_matrix: dict[str, dict[str, int]] = {}
    rows = []
    for case_id in sorted(case_ids):
        variant = variant_by_id.get(case_id) or {}
        final_row = final_by_id.get(case_id) or {}
        raw_row = raw_by_id.get(case_id) or {}
        fen = str(variant.get("fen") or "")
        side = str(variant.get("side") or "")
        expected_move = str(variant.get("expected_move") or "")
        expected_semantic = str(variant.get("expected_semantic") or _move_semantic_class(fen, side, expected_move))
        final_move = str(final_row.get("top1") or "")
        raw_move = str(raw_row.get("raw_policy_top1") or "")
        final_semantic = _move_semantic_class(fen, side, final_move)
        raw_semantic = _move_semantic_class(fen, side, raw_move)
        matrix.setdefault(expected_semantic, {})[final_semantic] = matrix.setdefault(expected_semantic, {}).get(final_semantic, 0) + 1
        raw_matrix.setdefault(expected_semantic, {})[raw_semantic] = raw_matrix.setdefault(expected_semantic, {}).get(raw_semantic, 0) + 1
        rows.append(
            {
                "case_id": case_id,
                "variant_difficulty": variant.get("variant_difficulty"),
                "expected_move": expected_move,
                "expected_semantic": expected_semantic,
                "final_top1": final_move,
                "final_semantic": final_semantic,
                "raw_policy_top1": raw_move,
                "raw_policy_semantic": raw_semantic,
                "expected_rank": raw_row.get("expected_rank"),
                "board_semantics_features": variant.get("board_semantics_features") or _board_semantics_features(fen, side),
            }
        )
    d_vs_e = sum(
        1
        for row in rows
        if row.get("expected_semantic") == "d_pawn_central_break"
        and row.get("final_semantic") == "e_pawn_central_break"
    )
    e_vs_d = sum(
        1
        for row in rows
        if row.get("expected_semantic") == "e_pawn_central_break"
        and row.get("final_semantic") == "d_pawn_central_break"
    )
    return {
        "case_count": len(rows),
        "matrix": matrix,
        "raw_policy_matrix": raw_matrix,
        "d7d5_vs_e7e5_confusion": d_vs_e,
        "e7e5_vs_d7d5_confusion": e_vs_d,
        "cases": rows,
    }


def _semantic_class_performance(confusion: dict) -> dict:
    rows = {}
    by_expected = confusion.get("matrix") or {}
    for semantic, predicted in by_expected.items():
        total = sum(int(count or 0) for count in predicted.values())
        correct = int(predicted.get(semantic) or 0)
        rows[semantic] = {
            "count": total,
            "correct": correct,
            "pass_rate": round(correct / max(1, total), 4),
            "predicted": predicted,
        }
    return rows


def _semantic_centroid_analysis(variants: list[dict], raw_rows: list[dict], *, confusion: dict | None = None) -> dict:
    raw_by_id = {str(row.get("case_id") or ""): row for row in raw_rows or []}
    vectors_by_semantic: dict[str, list[list[float]]] = {}
    for variant in variants or []:
        case_id = str(variant.get("case_id") or "")
        raw = raw_by_id.get(case_id) or {}
        if not raw.get("supported"):
            continue
        semantic = str(variant.get("expected_semantic") or _move_semantic_class(str(variant.get("fen") or ""), str(variant.get("side") or ""), str(variant.get("expected_move") or "")))
        vector = [
            float(raw.get("expected_logit") or 0.0),
            float(raw.get("expected_probability") or 0.0),
            -float(raw.get("expected_rank") or 99) / 100.0,
            float(raw.get("margin_vs_old_move") or 0.0),
        ]
        vectors_by_semantic.setdefault(semantic, []).append(vector)

    def centroid(vectors: list[list[float]]) -> list[float]:
        if not vectors:
            return []
        width = len(vectors[0])
        return [round(sum(row[i] for row in vectors) / len(vectors), 8) for i in range(width)]

    def distance(left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        return round(sum((float(a) - float(b)) ** 2 for a, b in zip(left, right)) ** 0.5, 8)

    centroids = {semantic: centroid(vectors) for semantic, vectors in vectors_by_semantic.items()}
    intra = {}
    for semantic, vectors in vectors_by_semantic.items():
        center = centroids.get(semantic) or []
        intra[semantic] = round(sum(distance(row, center) for row in vectors) / max(1, len(vectors)), 8)
    centroid_distances = {}
    nearest = {}
    for semantic, center in centroids.items():
        distances = {}
        for other, other_center in centroids.items():
            if other == semantic:
                continue
            distances[other] = distance(center, other_center)
        centroid_distances[semantic] = distances
        nearest[semantic] = min(distances.items(), key=lambda item: item[1])[0] if distances else ""
    overlap_scores = {}
    for semantic, distances in centroid_distances.items():
        scores = {}
        for other, dist in distances.items():
            denom = max(0.0001, float(intra.get(semantic) or 0.0) + float(intra.get(other) or 0.0))
            scores[other] = round(max(0.0, 1.0 - float(dist) / denom), 4)
        overlap_scores[semantic] = scores
    return {
        "centroids": centroids,
        "class_counts": {semantic: len(vectors) for semantic, vectors in vectors_by_semantic.items()},
        "intra_semantic_distance": intra,
        "inter_semantic_distance": centroid_distances,
        "overlap_score": overlap_scores,
        "nearest_semantic": nearest,
        "nearest_confused_semantic": {
            semantic: max((predicted or {}).items(), key=lambda item: item[1])[0] if predicted else ""
            for semantic, predicted in ((confusion or {}).get("matrix") or {}).items()
        },
    }


def _semantic_centroid_drift(before: dict, after: dict) -> dict:
    before_distances = before.get("inter_semantic_distance") or {}
    after_distances = after.get("inter_semantic_distance") or {}
    rows = {}
    for semantic, distances in after_distances.items():
        rows[semantic] = {}
        for other, after_distance in (distances or {}).items():
            before_distance = ((before_distances.get(semantic) or {}).get(other))
            if before_distance is None:
                continue
            rows[semantic][other] = {
                "before": before_distance,
                "after": after_distance,
                "delta": round(float(after_distance) - float(before_distance), 8),
            }
    return rows


def _semantic_margin_summary(margin_table: list[dict], confusion: dict) -> dict:
    grouped: dict[str, dict[str, list[float]]] = {}
    for row in margin_table or []:
        expected = str(row.get("expected_semantic") or "unknown")
        confused = str(row.get("hard_negative_semantic") or "unknown")
        if expected == confused:
            continue
        try:
            margin = float(row.get("margin_after"))
        except Exception:
            continue
        grouped.setdefault(expected, {}).setdefault(confused, []).append(margin)
    pair_rows = {}
    for expected, confused_map in grouped.items():
        pair_rows[expected] = {}
        for confused, margins in confused_map.items():
            pair_rows[expected][confused] = {
                "count": len(margins),
                "min_margin": round(min(margins), 8),
                "avg_margin": round(sum(margins) / max(1, len(margins)), 8),
            }
    top_confused = {}
    for expected, predicted in ((confusion or {}).get("matrix") or {}).items():
        candidates = [
            (semantic, int(count or 0))
            for semantic, count in (predicted or {}).items()
            if semantic != expected
        ]
        if not candidates:
            continue
        confused, count = max(candidates, key=lambda item: item[1])
        top_confused[expected] = {
            "top_confused_semantic": confused,
            "confusion_count": count,
            "margin": ((pair_rows.get(expected) or {}).get(confused) or {}),
        }
    all_margins = [
        float(row.get("margin_after") or 0.0)
        for row in margin_table or []
        if row.get("margin_after") is not None
    ]
    return {
        "pair_margins": pair_rows,
        "top_confused_semantic_margins": top_confused,
        "semantic_min_margin": round(min(all_margins), 8) if all_margins else None,
        "semantic_avg_margin": round(sum(all_margins) / max(1, len(all_margins)), 8) if all_margins else None,
    }


def _semantic_candidate_centroid_analysis(margin_table: list[dict], *, phase: str) -> dict:
    vectors_by_semantic: dict[str, list[list[float]]] = {}
    for row in margin_table or []:
        expected_semantic = str(row.get("expected_semantic") or "unknown")
        negative_semantic = str(row.get("hard_negative_semantic") or "unknown")
        if phase == "before":
            expected_logit = row.get("expected_logit_before")
            negative_logit = row.get("hard_negative_logit_before")
            margin = row.get("margin_before")
        else:
            expected_logit = row.get("expected_logit_after")
            negative_logit = row.get("hard_negative_logit_after")
            margin = row.get("margin_after")
        if expected_logit is not None:
            vectors_by_semantic.setdefault(expected_semantic, []).append(
                [
                    float(expected_logit),
                    float(margin or 0.0),
                    1.0,
                ]
            )
        if negative_logit is not None:
            vectors_by_semantic.setdefault(negative_semantic, []).append(
                [
                    float(negative_logit),
                    -float(margin or 0.0),
                    -1.0,
                ]
            )

    def centroid(vectors: list[list[float]]) -> list[float]:
        if not vectors:
            return []
        width = len(vectors[0])
        return [round(sum(row[index] for row in vectors) / len(vectors), 8) for index in range(width)]

    def distance(left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        return round(sum((float(a) - float(b)) ** 2 for a, b in zip(left, right)) ** 0.5, 8)

    centroids = {semantic: centroid(vectors) for semantic, vectors in vectors_by_semantic.items()}
    intra = {}
    for semantic, vectors in vectors_by_semantic.items():
        center = centroids.get(semantic) or []
        intra[semantic] = round(sum(distance(row, center) for row in vectors) / max(1, len(vectors)), 8)
    inter = {}
    nearest = {}
    for semantic, center in centroids.items():
        distances = {
            other: distance(center, other_center)
            for other, other_center in centroids.items()
            if other != semantic
        }
        inter[semantic] = distances
        nearest[semantic] = min(distances.items(), key=lambda item: item[1])[0] if distances else ""
    overlap = {}
    for semantic, distances in inter.items():
        overlap[semantic] = {}
        for other, dist in distances.items():
            denom = max(0.0001, float(intra.get(semantic) or 0.0) + float(intra.get(other) or 0.0))
            overlap[semantic][other] = round(max(0.0, 1.0 - float(dist) / denom), 4)
    return {
        "phase": phase,
        "class_counts": {semantic: len(vectors) for semantic, vectors in vectors_by_semantic.items()},
        "centroids": centroids,
        "intra_semantic_distance": intra,
        "inter_semantic_distance": inter,
        "overlap_score": overlap,
        "nearest_semantic": nearest,
    }


def _semantic_targeted_centroid_distances(centroid_analysis: dict) -> dict:
    distances = centroid_analysis.get("inter_semantic_distance") or {}
    rows = {}
    for left, right in SEMANTIC_TARGETED_CENTROID_PAIRS:
        value = (distances.get(left) or {}).get(right)
        if value is None:
            value = (distances.get(right) or {}).get(left)
        rows[f"{left}__vs__{right}"] = value
    numeric = [float(value) for value in rows.values() if value is not None]
    return {
        "pairs": rows,
        "min_distance": round(min(numeric), 8) if numeric else None,
        "threshold": SEMANTIC_TARGETED_CENTROID_DISTANCE_MIN,
        "passed": bool(numeric) and min(numeric) >= SEMANTIC_TARGETED_CENTROID_DISTANCE_MIN,
    }


def _semantic_confusion_gate(confusion: dict) -> dict:
    matrix = confusion.get("matrix") or {}
    central_total = 0
    central_to_kingside = 0
    ed_confusion = int(confusion.get("d7d5_vs_e7e5_confusion") or 0) + int(confusion.get("e7e5_vs_d7d5_confusion") or 0)
    for semantic in ["e_pawn_central_break", "d_pawn_central_break"]:
        predicted = matrix.get(semantic) or {}
        central_total += sum(int(count or 0) for count in predicted.values())
        central_to_kingside += int(predicted.get("kingside_aggression") or 0)
    rate = round(central_to_kingside / max(1, central_total), 4)
    return {
        "central_total": central_total,
        "central_to_kingside": central_to_kingside,
        "central_to_kingside_rate": rate,
        "central_to_kingside_limit": SEMANTIC_CENTRAL_TO_KINGSIDE_CONFUSION_LIMIT,
        "ed_pawn_break_confusion_count": ed_confusion,
        "passed": rate <= SEMANTIC_CENTRAL_TO_KINGSIDE_CONFUSION_LIMIT,
    }


def _evaluate_sanity_learning_probe(
    engine_alias: str,
    before_model_path: Path,
    after_model_path: Path,
    samples: list[dict],
    *,
    trusted_replays: int = 0,
) -> dict:
    case, before_exact = _select_sanity_learning_case(engine_alias, before_model_path, samples)
    if not case:
        return {
            "supported": False,
            "learning_signal": False,
            "result_kind": "failed_to_learn",
            "raw_policy_learning": {"supported": False, "learning_signal": False},
            "final_decision_learning": {"supported": False, "learning_signal": False},
            "reason": "no mistake_retention replay sample with explicit expected_move was available",
            "human_explanation": "目前沒有足夠證據證明 retrain 學會指定錯誤，因為缺少對齊 expected_move 的 replay 樣本。",
        }
    before_exact = before_exact or _evaluate_sanity_learning_position(engine_alias, before_model_path, case)
    old_move = str(before_exact.get("top1") or "")
    raw_before = _evaluate_engine_raw_policy_position(engine_alias, before_model_path, case, old_move=old_move)
    if before_exact["expected_is_top1"]:
        after_exact = _evaluate_sanity_learning_position(engine_alias, after_model_path, case)
        raw_after = _evaluate_engine_raw_policy_position(engine_alias, after_model_path, case, old_move=old_move)
        retained = bool(after_exact.get("expected_is_top1"))
        return {
            "supported": True,
            "learning_signal": retained,
            "result_kind": "retained_learned_decision" if retained else "regressed_from_learned_decision",
            "raw_policy_learning": {
                "supported": bool(raw_before.get("supported") and raw_after.get("supported")),
                "learning_signal": bool(retained and raw_after.get("expected_is_raw_top1")),
                "before": raw_before,
                "after": raw_after,
                "raw_policy_top1_before": raw_before.get("raw_policy_top1"),
                "raw_policy_top1_after": raw_after.get("raw_policy_top1"),
                "expected_rank_before": raw_before.get("expected_rank"),
                "expected_rank_after": raw_after.get("expected_rank"),
                "expected_margin_before": raw_before.get("margin_vs_old_move"),
                "expected_margin_after": raw_after.get("margin_vs_old_move"),
                "learning_signal_reason": "expected_move was already raw top1 and remained available" if retained else "expected_move decision regressed",
            },
            "final_decision_learning": {
                "supported": True,
                "learning_signal": retained,
                "before_top1": before_exact.get("top1"),
                "after_top1": after_exact.get("top1"),
                "expected_move": case.get("expected_move"),
                "blocked_by_search_or_static_eval": False,
                "blocked_reason": "",
            },
            "reason": "baseline already selected expected_move and after model retained it" if retained else "baseline selected expected_move but after model regressed",
            "case": case,
            "before_exact": before_exact,
            "after_exact": after_exact,
            "human_explanation": "此 sanity probe 顯示前一 checkpoint 已學會該錯題，且本次 retrain 後仍保留正解。" if retained else "此 sanity probe 顯示本次 retrain 讓已學會的錯題退步。",
        }
    after_exact = _evaluate_sanity_learning_position(engine_alias, after_model_path, case)
    raw_after = _evaluate_engine_raw_policy_position(engine_alias, after_model_path, case, old_move=old_move)
    before_rank = int(raw_before.get("expected_rank") or 0) if raw_before.get("supported") else 0
    after_rank = int(raw_after.get("expected_rank") or 0) if raw_after.get("supported") else 0
    before_margin = float(raw_before.get("margin_vs_old_move") or 0.0) if raw_before.get("supported") else 0.0
    after_margin = float(raw_after.get("margin_vs_old_move") or 0.0) if raw_after.get("supported") else 0.0
    raw_rank_improved = bool(raw_before.get("supported") and raw_after.get("supported") and after_rank > 0 and (before_rank == 0 or after_rank < before_rank))
    raw_margin_turned_positive = bool(raw_before.get("supported") and raw_after.get("supported") and before_margin <= 0.0 and after_margin > 0.0)
    raw_top1_expected = bool(raw_after.get("expected_is_raw_top1"))
    raw_policy_learning = {
        "supported": bool(raw_before.get("supported") and raw_after.get("supported")),
        "learning_signal": bool(raw_top1_expected and (raw_rank_improved or raw_margin_turned_positive or after_margin > 0.0)),
        "before": raw_before,
        "after": raw_after,
        "expected_rank_before": before_rank or None,
        "expected_rank_after": after_rank or None,
        "expected_rank_improved": raw_rank_improved,
        "expected_margin_before": before_margin if raw_before.get("supported") else None,
        "expected_margin_after": after_margin if raw_after.get("supported") else None,
        "expected_margin_vs_chosen_old_move": after_margin if raw_after.get("supported") else None,
        "expected_margin_turned_positive": raw_margin_turned_positive,
        "old_move_rank_before": raw_before.get("old_move_rank") if raw_before.get("supported") else None,
        "old_move_rank_after": raw_after.get("old_move_rank") if raw_after.get("supported") else None,
        "raw_policy_top1_before": raw_before.get("raw_policy_top1"),
        "raw_policy_top1_after": raw_after.get("raw_policy_top1"),
        "learning_signal_reason": (
            "raw policy top1 changed to expected_move and expected margin is positive"
            if raw_top1_expected and after_margin > 0.0
            else "raw policy did not make expected_move top1 with positive margin"
        ),
    }
    decision_before = _engine_decision_breakdown(engine_alias, before_model_path, case, old_move=old_move)
    decision_after = _engine_decision_breakdown(engine_alias, after_model_path, case, old_move=old_move)
    final_decision_signal = bool(after_exact.get("expected_is_top1"))
    blocked_by_search_or_static_eval = bool(raw_policy_learning["learning_signal"] and not final_decision_signal)
    final_decision_learning = {
        "supported": True,
        "learning_signal": final_decision_signal,
        "before_top1": before_exact.get("top1"),
        "after_top1": after_exact.get("top1"),
        "expected_move": case.get("expected_move"),
        "blocked_by_search_or_static_eval": blocked_by_search_or_static_eval,
        "blocked_reason": (
            f"raw policy learned expected_move but final decision stayed {after_exact.get('top1')} via {(decision_after.get('chosen_reason') or 'unknown')}"
            if blocked_by_search_or_static_eval
            else ""
        ),
        "decision_breakdown_before": decision_before,
        "decision_breakdown_after": decision_after,
    }
    curriculum = _sanity_curriculum_variants(case, trusted_replays=int(trusted_replays or 0))
    seen_variants = list(curriculum.get("seen") or [])
    unseen_variants = list(curriculum.get("unseen") or [])
    held_out_pool = curriculum.get("held_out_pool") or {}
    _progress(
        f"sanity probe variants: trusted={trusted_replays} seen={len(seen_variants)} unseen={len(unseen_variants)}"
    )
    before_seen_variants = _evaluate_sanity_learning_position_batch(
        engine_alias,
        before_model_path,
        seen_variants,
        label=f"sanity final before seen trusted={trusted_replays}",
    )
    after_seen_variants = _evaluate_sanity_learning_position_batch(
        engine_alias,
        after_model_path,
        seen_variants,
        label=f"sanity final after seen trusted={trusted_replays}",
    )
    before_unseen_variants = _evaluate_sanity_learning_position_batch(
        engine_alias,
        before_model_path,
        unseen_variants,
        label=f"sanity final before unseen trusted={trusted_replays}",
    )
    after_unseen_variants = _evaluate_sanity_learning_position_batch(
        engine_alias,
        after_model_path,
        unseen_variants,
        label=f"sanity final after unseen trusted={trusted_replays}",
    )
    raw_seen_before = _evaluate_raw_policy_position_batch(
        engine_alias,
        before_model_path,
        seen_variants,
        old_move=old_move,
        label=f"sanity raw before seen trusted={trusted_replays}",
    )
    raw_unseen_before = _evaluate_raw_policy_position_batch(
        engine_alias,
        before_model_path,
        unseen_variants,
        old_move=old_move,
        label=f"sanity raw before unseen trusted={trusted_replays}",
    )
    raw_seen_after = _evaluate_raw_policy_position_batch(
        engine_alias,
        after_model_path,
        seen_variants,
        old_move=old_move,
        label=f"sanity raw after seen trusted={trusted_replays}",
    )
    raw_unseen_after = _evaluate_raw_policy_position_batch(
        engine_alias,
        after_model_path,
        unseen_variants,
        old_move=old_move,
        label=f"sanity raw after unseen trusted={trusted_replays}",
    )
    label_quality = _sanity_label_quality_audit(unseen_variants, raw_unseen_after)
    held_out_pool_quality = held_out_pool.get("label_quality") or {}
    clean_unseen_ids = _case_ids_for_label_quality(label_quality, quality="clean")
    clean_held_out_ids = _case_ids_for_label_quality(label_quality, quality="clean", split="held_out")
    hard_clean_held_out_ids = _case_ids_for_label_quality(label_quality, quality="clean", split="held_out", difficulty="hard")
    questionable_ids = _case_ids_for_label_quality(label_quality, quality="questionable")
    invalid_ids = _case_ids_for_label_quality(held_out_pool_quality, quality="invalid")
    clean_unseen_performance = _variant_performance_for_case_ids(unseen_variants, after_unseen_variants, raw_unseen_after, clean_unseen_ids)
    clean_held_out_performance = _variant_performance_for_case_ids(unseen_variants, after_unseen_variants, raw_unseen_after, clean_held_out_ids)
    hard_clean_held_out_performance = _variant_performance_for_case_ids(unseen_variants, after_unseen_variants, raw_unseen_after, hard_clean_held_out_ids)
    questionable_performance = _variant_performance_for_case_ids(unseen_variants, after_unseen_variants, raw_unseen_after, questionable_ids)
    invalid_performance = _variant_performance_for_case_ids(unseen_variants, after_unseen_variants, raw_unseen_after, invalid_ids)
    clean_held_out_by_difficulty = {
        difficulty: _variant_performance_for_case_ids(
            unseen_variants,
            after_unseen_variants,
            raw_unseen_after,
            _case_ids_for_label_quality(label_quality, quality="clean", split="held_out", difficulty=difficulty),
        )
        for difficulty in ["easy", "medium", "hard"]
    }
    clean_semantic_confusion = _semantic_confusion_for_case_ids(
        unseen_variants,
        after_unseen_variants,
        raw_unseen_after,
        clean_held_out_ids,
    )
    clean_semantic_confusion_before = _semantic_confusion_for_case_ids(
        unseen_variants,
        before_unseen_variants,
        raw_unseen_before,
        clean_held_out_ids,
    )
    semantic_centroids_before = _semantic_centroid_analysis(
        unseen_variants,
        raw_unseen_before,
        confusion=clean_semantic_confusion_before,
    )
    semantic_centroids_after = _semantic_centroid_analysis(
        unseen_variants,
        raw_unseen_after,
        confusion=clean_semantic_confusion,
    )
    semantic_centroid_drift = _semantic_centroid_drift(semantic_centroids_before, semantic_centroids_after)
    clean_held_out_by_semantic = {
        semantic: _variant_performance_for_case_ids(
            unseen_variants,
            after_unseen_variants,
            raw_unseen_after,
            {
                str(variant.get("case_id") or "")
                for variant in unseen_variants
                if str(variant.get("case_id") or "") in clean_held_out_ids
                and str(variant.get("expected_semantic") or _move_semantic_class(str(variant.get("fen") or ""), str(variant.get("side") or ""), str(variant.get("expected_move") or ""))) == semantic
            },
        )
        for semantic in SEMANTIC_CLASSES
    }
    clean_heldout_by_semantic = {
        semantic: {
            "total": int(row.get("count") or 0),
            "passed": int(row.get("final_hits") or 0),
            "pass_rate": row.get("final_pass_rate"),
            "raw_policy_passed": int(row.get("raw_policy_hits") or 0),
            "raw_policy_pass_rate": row.get("raw_policy_pass_rate"),
        }
        for semantic, row in clean_held_out_by_semantic.items()
    }
    balanced_clean_ids = {
        str(variant.get("case_id") or "")
        for variant in unseen_variants
        if str(variant.get("case_id") or "") in clean_held_out_ids
        and str(variant.get("expected_semantic") or variant.get("semantic_class") or "") in BALANCED_PROMOTION_SEMANTIC_CLASSES
    }
    flank_label_audit = _flank_label_audit_for_cases(
        list(held_out_pool.get("all_cases") or unseen_variants),
        held_out_pool_quality or label_quality,
    )
    bad_random_flank_ids = {
        str(row.get("case_id") or "")
        for row in flank_label_audit.get("cases") or []
        if row.get("bad_random_flank_push")
    }
    balanced_clean_ids = {
        case_id for case_id in balanced_clean_ids
        if case_id not in bad_random_flank_ids
    }
    attacking_style_ids = {
        str(variant.get("case_id") or "")
        for variant in unseen_variants
        if str(variant.get("case_id") or "") in clean_held_out_ids
        and str(variant.get("expected_semantic") or variant.get("semantic_class") or "") in STYLE_AUDIT_SEMANTIC_CLASSES
    }
    balanced_clean_held_out_performance = _balanced_gate_performance_for_case_ids(
        unseen_variants,
        after_unseen_variants,
        raw_unseen_after,
        balanced_clean_ids,
        label_quality=label_quality,
    )
    balanced_clean_heldout_by_semantic = {}
    for semantic in BALANCED_PROMOTION_SEMANTIC_CLASSES:
        ids = {
            str(variant.get("case_id") or "")
            for variant in unseen_variants
            if str(variant.get("case_id") or "") in balanced_clean_ids
            and str(variant.get("expected_semantic") or variant.get("semantic_class") or "") == semantic
        }
        row = _balanced_gate_performance_for_case_ids(
            unseen_variants,
            after_unseen_variants,
            raw_unseen_after,
            ids,
            label_quality=label_quality,
        )
        balanced_clean_heldout_by_semantic[semantic] = {
            "total": int(row.get("count") or 0),
            "passed": int(row.get("balanced_hits") or 0),
            "pass_rate": row.get("balanced_pass_rate"),
            "raw_policy_passed": int(row.get("raw_policy_hits") or 0),
            "raw_policy_pass_rate": row.get("raw_policy_pass_rate"),
        }
    development_credit_cases = [
        row for row in balanced_clean_held_out_performance.get("cases") or []
        if row.get("is_development_move")
    ]
    development_multi_good_credit = {
        "case_count": len(development_credit_cases),
        "multi_good_move_case_count": sum(1 for row in development_credit_cases if row.get("multi_good_move_case")),
        "multi_good_credit_applied_count": sum(1 for row in development_credit_cases if row.get("multi_good_credit_applied")),
        "cases": development_credit_cases,
    }
    attacking_style_audit = _variant_performance_for_case_ids(
        unseen_variants,
        after_unseen_variants,
        raw_unseen_after,
        attacking_style_ids,
    )
    central_flank_failed_case_analysis = _central_flank_failed_case_analysis(
        engine_alias=engine_alias,
        model_path=after_model_path,
        variants=unseen_variants,
        final_rows=after_unseen_variants,
        raw_rows=raw_unseen_after,
        case_ids=balanced_clean_ids,
        label_quality=label_quality,
    )
    flank_difficulty_performance = _flank_difficulty_performance(
        unseen_variants,
        after_unseen_variants,
        raw_unseen_after,
        balanced_clean_ids,
        label_quality=label_quality,
    )
    contextual_flank_performance = _contextual_flank_performance_from_rows(
        unseen_variants,
        balanced_clean_held_out_performance.get("cases") or [],
        label="balanced clean held-out contextual flank",
    )
    central_vs_flank_boundary = _central_vs_flank_boundary_report(clean_semantic_confusion)
    failed_by_semantic_top3 = {
        semantic: [
            row
            for row in (payload.get("cases") or [])
            if not row.get("final_pass")
        ][:3]
        for semantic, payload in clean_held_out_by_semantic.items()
    }
    clean_pool_sufficient = all(
        int((clean_held_out_by_difficulty.get(difficulty) or {}).get("count") or 0) >= SANITY_CLEAN_HELD_OUT_MIN_PER_DIFFICULTY
        for difficulty in ["easy", "medium", "hard"]
    )
    clean_held_out_passed = bool(
        int(clean_held_out_performance.get("count") or 0) > 0
        and float(clean_held_out_performance.get("final_pass_rate") or 0.0) >= SANITY_UNSEEN_VARIANT_PASS_THRESHOLD
    )
    hard_clean_held_out_passed = bool(
        int(hard_clean_held_out_performance.get("count") or 0) > 0
        and float(hard_clean_held_out_performance.get("final_pass_rate") or 0.0) > 0.0
    )
    seen_hits = sum(1 for row in after_seen_variants if row.get("expected_is_top1"))
    unseen_hits = sum(1 for row in after_unseen_variants if row.get("expected_is_top1"))
    raw_seen_hits = sum(1 for row in raw_seen_after if row.get("expected_is_raw_top1"))
    raw_unseen_hits = sum(1 for row in raw_unseen_after if row.get("expected_is_raw_top1"))
    seen_count = len(after_seen_variants)
    unseen_count = len(after_unseen_variants)
    variant_count = seen_count + unseen_count
    variant_top1_hits = seen_hits + unseen_hits
    seen_variant_pass_rate = round(seen_hits / max(1, seen_count), 4)
    unseen_variant_pass_rate = round(unseen_hits / max(1, unseen_count), 4)
    raw_policy_generalization_rate = round((raw_seen_hits + raw_unseen_hits) / max(1, seen_count + unseen_count), 4)
    final_decision_generalization_rate = round((seen_hits + unseen_hits) / max(1, seen_count + unseen_count), 4)
    raw_policy_unseen_generalization_rate = round(raw_unseen_hits / max(1, unseen_count), 4)
    final_decision_unseen_generalization_rate = unseen_variant_pass_rate
    exact_learned = bool(after_exact.get("expected_is_top1"))
    seen_passed = bool(seen_count > 0 and seen_variant_pass_rate >= SANITY_SEEN_VARIANT_PASS_THRESHOLD)
    unseen_passed = bool(unseen_count > 0 and unseen_variant_pass_rate >= SANITY_UNSEEN_VARIANT_PASS_THRESHOLD)
    generalized = bool(exact_learned and seen_passed and clean_pool_sufficient and clean_held_out_passed and hard_clean_held_out_passed)
    difficulty_scores = {}
    for difficulty in ["easy", "medium", "hard"]:
        seen_cases = list(((curriculum.get("by_difficulty") or {}).get(difficulty) or {}).get("seen") or [])
        unseen_cases = list(((curriculum.get("by_difficulty") or {}).get(difficulty) or {}).get("unseen") or [])
        seen_ids = {str(row.get("case_id") or "") for row in seen_cases}
        unseen_ids = {str(row.get("case_id") or "") for row in unseen_cases}
        seen_after = [row for row in after_seen_variants if str(row.get("case_id") or "") in seen_ids]
        unseen_after = [row for row in after_unseen_variants if str(row.get("case_id") or "") in unseen_ids]
        raw_seen = [row for row in raw_seen_after if str(row.get("case_id") or "") in seen_ids]
        raw_unseen = [row for row in raw_unseen_after if str(row.get("case_id") or "") in unseen_ids]
        seen_hits_difficulty = sum(1 for row in seen_after if row.get("expected_is_top1"))
        unseen_hits_difficulty = sum(1 for row in unseen_after if row.get("expected_is_top1"))
        raw_seen_hits_difficulty = sum(1 for row in raw_seen if row.get("expected_is_raw_top1"))
        raw_unseen_hits_difficulty = sum(1 for row in raw_unseen if row.get("expected_is_raw_top1"))
        difficulty_scores[difficulty] = {
            "seen_count": len(seen_after),
            "seen_pass_rate": round(seen_hits_difficulty / max(1, len(seen_after)), 4),
            "seen_raw_policy_pass_rate": round(raw_seen_hits_difficulty / max(1, len(raw_seen)), 4),
            "unseen_count": len(unseen_after),
            "unseen_pass_rate": round(unseen_hits_difficulty / max(1, len(unseen_after)), 4),
            "unseen_raw_policy_pass_rate": round(raw_unseen_hits_difficulty / max(1, len(raw_unseen)), 4),
            "held_out_from_training": difficulty == "hard",
        }
    blocker_rows = []
    for variant, final_row, raw_row in zip(seen_variants + unseen_variants, after_seen_variants + after_unseen_variants, raw_seen_after + raw_unseen_after):
        if final_row.get("expected_is_top1"):
            continue
        breakdown = _engine_decision_breakdown(engine_alias, after_model_path, variant, old_move=old_move)
        override = breakdown.get("policy_override") or {}
        blocker_rows.append(
            {
                "case_id": variant.get("case_id"),
                "variant_split": variant.get("variant_split"),
                "variant_difficulty": variant.get("variant_difficulty"),
                "expected_move": variant.get("expected_move"),
                "final_top1": final_row.get("top1"),
                "raw_policy_top1": raw_row.get("raw_policy_top1"),
                "expected_rank": raw_row.get("expected_rank"),
                "expected_margin_vs_old_move": raw_row.get("margin_vs_old_move"),
                "blocked_by_search_or_static_eval": bool(raw_row.get("expected_is_raw_top1") and not final_row.get("expected_is_top1")),
                "chosen_reason": breakdown.get("chosen_reason"),
                "policy_override_used": bool(override.get("used")),
                "policy_override_margin": override.get("margin"),
                "watched_moves": breakdown.get("watched_moves") or [],
            }
        )
    failed_unseen_cases = []
    for variant, final_row, raw_row in zip(unseen_variants, after_unseen_variants, raw_unseen_after):
        if final_row.get("expected_is_top1"):
            continue
        blocking_features = []
        difficulty = str(variant.get("variant_difficulty") or "")
        if difficulty == "hard":
            blocking_features.append("hard_held_out_multi_pair_variation")
        elif difficulty == "medium":
            blocking_features.append("medium_two_pair_variation")
        elif difficulty == "easy":
            blocking_features.append("easy_single_pair_variation")
        similarity = float(variant.get("board_embedding_similarity") or 0.0)
        if similarity < 0.9:
            blocking_features.append("low_board_embedding_similarity")
        if float(raw_row.get("margin_vs_old_move") or 0.0) <= 0.0:
            blocking_features.append("expected_policy_margin_not_positive")
        if int(raw_row.get("expected_rank") or 99) > 3:
            blocking_features.append("expected_not_in_raw_top3")
        failed_unseen_cases.append(
            {
                "case_id": variant.get("case_id"),
                "variant_split": variant.get("variant_split"),
                "variant_difficulty": difficulty,
                "fen": variant.get("fen"),
                "variation_moves": variant.get("variation_moves") or [],
                "expected_move": variant.get("expected_move"),
                "expected_semantic": variant.get("expected_semantic") or _move_semantic_class(str(variant.get("fen") or ""), str(variant.get("side") or ""), str(variant.get("expected_move") or "")),
                "final_top1": final_row.get("top1"),
                "final_semantic": _move_semantic_class(str(variant.get("fen") or ""), str(variant.get("side") or ""), str(final_row.get("top1") or "")),
                "final_top3": final_row.get("top3"),
                "raw_policy_top1": raw_row.get("raw_policy_top1"),
                "raw_policy_semantic": _move_semantic_class(str(variant.get("fen") or ""), str(variant.get("side") or ""), str(raw_row.get("raw_policy_top1") or "")),
                "raw_policy_top3": raw_row.get("raw_policy_top3"),
                "expected_rank": raw_row.get("expected_rank"),
                "expected_margin_vs_old_move": raw_row.get("margin_vs_old_move"),
                "board_embedding_similarity": variant.get("board_embedding_similarity"),
                "blocking_features": blocking_features,
            }
        )
    failed_feature_groups = _failed_feature_groups(failed_unseen_cases)
    policy_embedding_before = _policy_embedding_similarity(raw_before, raw_seen_before + raw_unseen_before)
    policy_embedding_after = _policy_embedding_similarity(raw_after, raw_seen_after + raw_unseen_after)
    embedding_similarity_delta_by_group = {}
    all_variants = seen_variants + unseen_variants
    all_raw_before = raw_seen_before + raw_unseen_before
    all_raw_after = raw_seen_after + raw_unseen_after
    for difficulty in ["easy", "medium", "hard"]:
        before_group = [
            row
            for variant, row in zip(all_variants, all_raw_before)
            if str(variant.get("variant_difficulty") or "") == difficulty
        ]
        after_group = [
            row
            for variant, row in zip(all_variants, all_raw_after)
            if str(variant.get("variant_difficulty") or "") == difficulty
        ]
        before_sim = _policy_embedding_similarity(raw_before, before_group)
        after_sim = _policy_embedding_similarity(raw_after, after_group)
        embedding_similarity_delta_by_group[difficulty] = {
            "before": before_sim,
            "after": after_sim,
            "delta": (
                round(float(after_sim.get("avg_similarity") or 0.0) - float(before_sim.get("avg_similarity") or 0.0), 4)
                if before_sim.get("avg_similarity") is not None and after_sim.get("avg_similarity") is not None
                else None
            ),
        }
    hard_negative_margin_cases = []
    hard_negative_margin_table = []
    semantic_hard_negative_margin_table = []
    for variant, raw_before_row, raw_after_row in zip(
        [case] + seen_variants + unseen_variants,
        [raw_before] + raw_seen_before + raw_unseen_before,
        [raw_after] + raw_seen_after + raw_unseen_after,
    ):
        semantic_negatives = _semantic_negative_moves(
            str(variant.get("fen") or ""),
            str(variant.get("side") or ""),
            str(variant.get("expected_move") or ""),
            old_move=old_move,
        )
        hard_negatives = _legal_sanity_hard_negatives(
            str(variant.get("fen") or ""),
            str(variant.get("side") or ""),
            str(variant.get("expected_move") or ""),
            old_move=old_move,
        )
        hard_negatives = list(dict.fromkeys([*semantic_negatives, *hard_negatives]))
        margins = []
        for negative in hard_negatives:
            negative_before_row = _evaluate_engine_raw_policy_position(
                engine_alias,
                before_model_path,
                {**variant, "expected_move": negative},
                old_move=str(variant.get("expected_move") or ""),
            )
            negative_after_row = _evaluate_engine_raw_policy_position(
                engine_alias,
                after_model_path,
                {**variant, "expected_move": negative},
                old_move=str(variant.get("expected_move") or ""),
            )
            if not (negative_after_row.get("supported") and raw_after_row.get("supported")):
                continue
            margin_before = None
            if negative_before_row.get("supported") and raw_before_row.get("supported"):
                margin_before = round(
                    float(raw_before_row.get("expected_logit") or 0.0) - float(negative_before_row.get("expected_logit") or 0.0),
                    8,
                )
            margin_after = round(
                float(raw_after_row.get("expected_logit") or 0.0) - float(negative_after_row.get("expected_logit") or 0.0),
                8,
            )
            margin_row = {
                "case_id": variant.get("case_id"),
                "variant_split": variant.get("variant_split") or "exact",
                "variant_difficulty": variant.get("variant_difficulty") or "exact",
                "expected_move": variant.get("expected_move"),
                "expected_semantic": variant.get("expected_semantic") or _move_semantic_class(str(variant.get("fen") or ""), str(variant.get("side") or ""), str(variant.get("expected_move") or "")),
                "expected_logit_before": raw_before_row.get("expected_logit") if raw_before_row.get("supported") else None,
                "expected_logit_after": raw_after_row.get("expected_logit") if raw_after_row.get("supported") else None,
                "hard_negative": negative,
                "hard_negative_semantic": _move_semantic_class(str(variant.get("fen") or ""), str(variant.get("side") or ""), negative),
                "hard_negative_logit_before": negative_before_row.get("expected_logit") if negative_before_row.get("supported") else None,
                "hard_negative_logit_after": negative_after_row.get("expected_logit") if negative_after_row.get("supported") else None,
                "semantic_negative": negative in semantic_negatives,
                "margin_before": margin_before,
                "margin_after": margin_after,
                "margin_delta": round(margin_after - float(margin_before), 8) if margin_before is not None else None,
                "expected_rank_before": raw_before_row.get("expected_rank"),
                "expected_rank_after": raw_after_row.get("expected_rank"),
            }
            if margin_row["semantic_negative"]:
                semantic_hard_negative_margin_table.append(margin_row)
            margins.append(
                {
                    "hard_negative": negative,
                    "hard_negative_semantic": margin_row["hard_negative_semantic"],
                    "semantic_negative": margin_row["semantic_negative"],
                    "expected_vs_hard_negative_margin_before": margin_before,
                    "expected_vs_hard_negative_margin": margin_after,
                    "expected_vs_hard_negative_margin_delta": margin_row["margin_delta"],
                }
            )
            hard_negative_margin_table.append(margin_row)
        hard_negative_margin_cases.append(
            {
                "case_id": variant.get("case_id"),
                "variant_split": variant.get("variant_split") or "exact",
                "variant_difficulty": variant.get("variant_difficulty") or "exact",
                "expected_move": variant.get("expected_move"),
                "expected_rank": raw_after_row.get("expected_rank"),
                "expected_margin_vs_old_move": raw_after_row.get("margin_vs_old_move"),
                "hard_negative_margins": margins,
            }
        )
    semantic_margin_report = _semantic_margin_summary(semantic_hard_negative_margin_table, clean_semantic_confusion)
    semantic_candidate_centroids_before = _semantic_candidate_centroid_analysis(semantic_hard_negative_margin_table, phase="before")
    semantic_candidate_centroids_after = _semantic_candidate_centroid_analysis(semantic_hard_negative_margin_table, phase="after")
    semantic_candidate_centroid_drift = _semantic_centroid_drift(semantic_candidate_centroids_before, semantic_candidate_centroids_after)
    semantic_confusion_gate = _semantic_confusion_gate(clean_semantic_confusion)
    semantic_targeted_centroid_distances_before = _semantic_targeted_centroid_distances(semantic_candidate_centroids_before)
    semantic_targeted_centroid_distances_after = _semantic_targeted_centroid_distances(semantic_candidate_centroids_after)
    if generalized:
        result_kind = "generalized_to_variants"
        explanation = "模型修正原始 FEN，且 seen variants 與 clean held-out 變體都達到泛化門檻。"
    elif exact_learned and seen_passed and unseen_count == 0:
        result_kind = "partial_seen_variants_only"
        explanation = "模型修正原始 FEN 並通過 seen variants，但沒有 unseen variants，不能證明泛化。"
    elif exact_learned and seen_passed:
        result_kind = "partial_seen_variants_only"
        explanation = "模型修正原始 FEN 並通過 seen variants，但 clean held-out 變體未達門檻，不能 promotion。"
    elif exact_learned:
        result_kind = "memorized_exact_fen"
        explanation = "模型修正了原始 FEN，但 seen/unseen 變體未達門檻，仍可能只是記住原局面。"
    elif raw_policy_learning["learning_signal"]:
        result_kind = "partial_policy_learned_but_decision_unchanged"
        explanation = "raw policy 已經把 expected_move 學成優先選項，但最終 search/static eval 決策仍未選 expected_move，因此不可 promotion。"
    else:
        result_kind = "failed_to_learn"
        explanation = "目前沒有足夠證據證明 retrain 學會指定錯誤，因為 after_top1 仍不是 expected_move。"
    return {
        "supported": True,
        "source": "fixed_replay_sanity_learning_probe",
        "case": case,
        "generalization_thresholds": {
            "seen_variant_pass_rate_min": SANITY_SEEN_VARIANT_PASS_THRESHOLD,
            "unseen_variant_pass_rate_min": SANITY_UNSEEN_VARIANT_PASS_THRESHOLD,
        },
        "exact_fen_pass": exact_learned,
        "seen_variant_count": seen_count,
        "seen_variant_top1_hits": seen_hits,
        "seen_variant_pass_rate": seen_variant_pass_rate,
        "unseen_variant_count": unseen_count,
        "unseen_variant_top1_hits": unseen_hits,
        "unseen_variant_pass_rate": unseen_variant_pass_rate,
        "clean_unseen_count": clean_unseen_performance.get("count"),
        "clean_unseen_final_pass_rate": clean_unseen_performance.get("final_pass_rate"),
        "clean_unseen_raw_policy_pass_rate": clean_unseen_performance.get("raw_policy_pass_rate"),
        "clean_held_out_count": clean_held_out_performance.get("count"),
        "clean_held_out_final_pass_rate": clean_held_out_performance.get("final_pass_rate"),
        "clean_held_out_raw_policy_pass_rate": clean_held_out_performance.get("raw_policy_pass_rate"),
        "hard_clean_held_out_count": hard_clean_held_out_performance.get("count"),
        "hard_clean_held_out_pass_rate": hard_clean_held_out_performance.get("final_pass_rate"),
        "clean_held_out_by_difficulty": clean_held_out_by_difficulty,
        "clean_held_out_by_semantic": clean_held_out_by_semantic,
        "clean_heldout_by_semantic": clean_heldout_by_semantic,
        "balanced_gate_semantic_set": list(BALANCED_PROMOTION_SEMANTIC_CLASSES),
        "excluded_style_semantics": list(STYLE_AUDIT_SEMANTIC_CLASSES),
        "balanced_clean_held_out_count": balanced_clean_held_out_performance.get("count"),
        "balanced_clean_held_out_pass_rate": balanced_clean_held_out_performance.get("balanced_pass_rate"),
        "balanced_clean_heldout_by_semantic": balanced_clean_heldout_by_semantic,
        "development_multi_good_credit": development_multi_good_credit,
        "attacking_style_audit": {
            "purpose": "style profile audit only; excluded from balanced promotion hard gate",
            "semantic_classes": list(STYLE_AUDIT_SEMANTIC_CLASSES),
            "case_count": attacking_style_audit.get("count"),
            "strict_final_pass_rate": attacking_style_audit.get("final_pass_rate"),
            "raw_policy_pass_rate": attacking_style_audit.get("raw_policy_pass_rate"),
            "cases": attacking_style_audit.get("cases") or [],
        },
        "central_flank_failed_case_analysis": central_flank_failed_case_analysis,
        "flank_label_audit": flank_label_audit,
        "flank_label_audit_v2": flank_label_audit,
        "flank_reason_distribution": flank_label_audit.get("flank_reason_distribution") or contextual_flank_performance.get("flank_reason_distribution") or {},
        "flank_difficulty_performance": flank_difficulty_performance,
        "contextual_flank_performance": contextual_flank_performance,
        "contextual_flank_pass_rate": contextual_flank_performance.get("contextual_flank_pass_rate"),
        "bad_random_flank_push_confusion": contextual_flank_performance.get("bad_random_flank_push_confusion") or {},
        "context_feature_importance": contextual_flank_performance.get("context_feature_importance") or [],
        "central_vs_flank_boundary": central_vs_flank_boundary,
        "failed_by_semantic_top3": failed_by_semantic_top3,
        "overall_clean_heldout_pass_rate": clean_held_out_performance.get("final_pass_rate"),
        "semantic_confusion_matrix": clean_semantic_confusion.get("matrix") if clean_semantic_confusion else {},
        "clean_held_out_pool_sufficient": clean_pool_sufficient,
        "questionable_held_out_count": len([row for row in label_quality.get("cases") or [] if row.get("label_quality") == "questionable" and row.get("variant_split") == "held_out"]),
        "questionable_performance": questionable_performance,
        "invalid_label_count": int((held_out_pool_quality.get("summary") or {}).get("invalid") or len(invalid_ids)),
        "easy_unseen_pass_rate": difficulty_scores.get("easy", {}).get("unseen_pass_rate"),
        "medium_unseen_pass_rate": difficulty_scores.get("medium", {}).get("unseen_pass_rate"),
        "hard_unseen_pass_rate": difficulty_scores.get("hard", {}).get("unseen_pass_rate"),
        "variant_difficulty_scores": difficulty_scores,
        "curriculum": curriculum,
        "raw_policy_generalization_rate": raw_policy_generalization_rate,
        "final_decision_generalization_rate": final_decision_generalization_rate,
        "raw_policy_unseen_generalization_rate": raw_policy_unseen_generalization_rate,
        "final_decision_unseen_generalization_rate": final_decision_unseen_generalization_rate,
        "variant_count": variant_count,
        "variant_top1_hits": variant_top1_hits,
        "variant_top1_rate": round(variant_top1_hits / max(1, variant_count), 4),
        "before_exact": before_exact,
        "after_exact": after_exact,
        "raw_policy_learning": raw_policy_learning,
        "final_decision_learning": final_decision_learning,
        "before_variants": before_seen_variants + before_unseen_variants,
        "after_variants": after_seen_variants + after_unseen_variants,
        "seen_variants": {
            "cases": seen_variants,
            "before": before_seen_variants,
            "after": after_seen_variants,
            "raw_policy_after": raw_seen_after,
        },
        "unseen_variants": {
            "cases": unseen_variants,
            "clean_gate_cases": [row for row in unseen_variants if str(row.get("case_id") or "") in clean_held_out_ids],
            "clean_unseen_cases": [row for row in unseen_variants if str(row.get("case_id") or "") in clean_unseen_ids],
            "questionable_cases": [row for row in unseen_variants if str(row.get("case_id") or "") in questionable_ids],
            "invalid_cases": [row for row in unseen_variants if str(row.get("case_id") or "") in invalid_ids],
            "before": before_unseen_variants,
            "after": after_unseen_variants,
            "raw_policy_after": raw_unseen_after,
        },
        "feature_generalization_debug": {
            "split": {
                "train": len(curriculum.get("train") or []),
                "validation": len(curriculum.get("validation") or []),
                "held_out": len(curriculum.get("held_out") or []),
                "held_out_never_trained": True,
                "held_out_in_training": False,
            },
            "label_quality": label_quality,
            "held_out_label_quality": held_out_pool_quality,
            "held_out_pool": {
                "by_difficulty": held_out_pool.get("by_difficulty") or {},
                "by_semantic": held_out_pool.get("by_semantic") or {},
                "semantic_coverage_complete": held_out_pool.get("semantic_coverage_complete"),
                "semantic_coverage_missing": held_out_pool.get("semantic_coverage_missing") or [],
                "label_quality_summary": held_out_pool.get("label_quality_summary") or {},
                "held_out_in_training": held_out_pool.get("held_out_in_training"),
                "dedupe_keys": held_out_pool.get("dedupe_keys") or [],
                "required_clean_per_difficulty": held_out_pool.get("required_clean_per_difficulty"),
                "required_per_semantic_difficulty": held_out_pool.get("required_per_semantic_difficulty"),
                "source": held_out_pool.get("source"),
            },
            "flank_label_audit": flank_label_audit,
            "flank_label_audit_v2": flank_label_audit,
            "flank_reason_distribution": flank_label_audit.get("flank_reason_distribution") or contextual_flank_performance.get("flank_reason_distribution") or {},
            "flank_difficulty_performance": flank_difficulty_performance,
            "contextual_flank_performance": contextual_flank_performance,
            "contextual_flank_pass_rate": contextual_flank_performance.get("contextual_flank_pass_rate"),
            "bad_random_flank_push_confusion": contextual_flank_performance.get("bad_random_flank_push_confusion") or {},
            "context_feature_importance": contextual_flank_performance.get("context_feature_importance") or [],
            "central_vs_flank_boundary": central_vs_flank_boundary,
            "semantic_distribution_by_split": {
                "train": _semantic_positive_distribution(curriculum.get("train") or []),
                "validation": _semantic_positive_distribution(curriculum.get("validation") or []),
                "held_out": _semantic_positive_distribution(curriculum.get("held_out") or []),
                "clean_gate_cases": _semantic_positive_distribution(curriculum.get("clean_gate_cases") or []),
            },
            "semantic_coverage_by_split": {
                split: _semantic_coverage_from_counts(counts)
                for split, counts in {
                    "train": _semantic_positive_distribution(curriculum.get("train") or []),
                    "validation": _semantic_positive_distribution(curriculum.get("validation") or []),
                    "held_out": _semantic_positive_distribution(curriculum.get("held_out") or []),
                    "clean_gate_cases": _semantic_positive_distribution(curriculum.get("clean_gate_cases") or []),
                }.items()
            },
            "train_to_gate_semantic_gap": _train_to_gate_semantic_gap(
                _semantic_positive_distribution(curriculum.get("train") or []),
                _semantic_positive_distribution(curriculum.get("clean_gate_cases") or []),
            ),
            "label_quality_summary": label_quality.get("summary") or {},
            "excluded_from_gate_cases": (label_quality.get("excluded_from_gate_cases") or []) + (held_out_pool_quality.get("excluded_from_gate_cases") or []),
            "clean_vs_questionable_performance": {
                "clean_unseen": clean_unseen_performance,
                "clean_held_out": clean_held_out_performance,
                "hard_clean_held_out": hard_clean_held_out_performance,
                "clean_held_out_by_difficulty": clean_held_out_by_difficulty,
                "clean_held_out_by_semantic": clean_held_out_by_semantic,
                "clean_heldout_by_semantic": clean_heldout_by_semantic,
                "central_flank_failed_case_analysis": central_flank_failed_case_analysis,
                "flank_label_audit": flank_label_audit,
                "flank_label_audit_v2": flank_label_audit,
                "flank_reason_distribution": flank_label_audit.get("flank_reason_distribution") or contextual_flank_performance.get("flank_reason_distribution") or {},
                "flank_difficulty_performance": flank_difficulty_performance,
                "contextual_flank_performance": contextual_flank_performance,
                "contextual_flank_pass_rate": contextual_flank_performance.get("contextual_flank_pass_rate"),
                "bad_random_flank_push_confusion": contextual_flank_performance.get("bad_random_flank_push_confusion") or {},
                "context_feature_importance": contextual_flank_performance.get("context_feature_importance") or [],
                "central_vs_flank_boundary": central_vs_flank_boundary,
                "failed_by_semantic_top3": failed_by_semantic_top3,
                "questionable": questionable_performance,
                "invalid": invalid_performance,
            },
            "semantic_analysis": {
                "confusion_matrix": clean_semantic_confusion,
                "confusion_matrix_before": clean_semantic_confusion_before,
                "confusion_matrix_after": clean_semantic_confusion,
                "semantic_class_performance": _semantic_class_performance(clean_semantic_confusion),
                "d7d5_vs_e7e5_confusion": clean_semantic_confusion.get("d7d5_vs_e7e5_confusion"),
                "e7e5_vs_d7d5_confusion": clean_semantic_confusion.get("e7e5_vs_d7d5_confusion"),
                "semantic_centroid_analysis_before": semantic_centroids_before,
                "semantic_centroid_analysis_after": semantic_centroids_after,
                "semantic_centroid_drift": semantic_centroid_drift,
                "semantic_candidate_centroid_analysis_before": semantic_candidate_centroids_before,
                "semantic_candidate_centroid_analysis_after": semantic_candidate_centroids_after,
                "semantic_candidate_centroid_drift": semantic_candidate_centroid_drift,
                "targeted_centroid_distances_before": semantic_targeted_centroid_distances_before,
                "targeted_centroid_distances_after": semantic_targeted_centroid_distances_after,
                "semantic_confusion_gate": semantic_confusion_gate,
                "semantic_margin_report": semantic_margin_report,
            },
            "failed_clean_cases_top3": [
                row
                for row in clean_held_out_performance.get("cases") or []
                if not row.get("final_pass")
            ][:3],
            "embedding_similarity": {
                "static_board_similarity_seen_avg": round(
                    sum(float(row.get("board_embedding_similarity") or 0.0) for row in seen_variants) / max(1, len(seen_variants)),
                    4,
                ),
                "static_board_similarity_unseen_avg": round(
                    sum(float(row.get("board_embedding_similarity") or 0.0) for row in unseen_variants) / max(1, len(unseen_variants)),
                    4,
                ),
                "policy_embedding_similarity_before": policy_embedding_before,
                "policy_embedding_similarity_after": policy_embedding_after,
                "avg_similarity_delta": (
                    round(float(policy_embedding_after.get("avg_similarity") or 0.0) - float(policy_embedding_before.get("avg_similarity") or 0.0), 4)
                    if policy_embedding_before.get("avg_similarity") is not None and policy_embedding_after.get("avg_similarity") is not None
                    else None
                ),
            },
            "embedding_similarity_delta_by_group": embedding_similarity_delta_by_group,
            "board_embedding_similarity": {
                "seen_avg": round(
                    sum(float(row.get("board_embedding_similarity") or 0.0) for row in seen_variants) / max(1, len(seen_variants)),
                    4,
                ),
                "unseen_avg": round(
                    sum(float(row.get("board_embedding_similarity") or 0.0) for row in unseen_variants) / max(1, len(unseen_variants)),
                    4,
                ),
                "cases": [
                    {
                        "case_id": row.get("case_id"),
                        "variant_split": row.get("variant_split"),
                        "variant_difficulty": row.get("variant_difficulty"),
                        "similarity": row.get("board_embedding_similarity"),
                    }
                    for row in seen_variants + unseen_variants
                ],
            },
            "expected_move_rank_across_variants": [
                {
                    "case_id": row.get("case_id"),
                    "variant_split": row.get("variant_split"),
                    "variant_difficulty": row.get("variant_difficulty"),
                    "expected_rank": row.get("expected_rank"),
                    "expected_probability": row.get("expected_probability"),
                    "expected_margin_vs_old_move": row.get("margin_vs_old_move"),
                    "raw_policy_top1": row.get("raw_policy_top1"),
                }
                for row in raw_seen_after + raw_unseen_after
            ],
            "final_decision_blockers": blocker_rows,
            "failed_unseen_cases": failed_unseen_cases,
            "failed_feature_groups": failed_feature_groups,
            "expected_vs_hard_negative_margin": {
                "cases": hard_negative_margin_cases,
                "hard_negative_margin_table": hard_negative_margin_table,
                "semantic_hard_negative_margin_table": semantic_hard_negative_margin_table,
                "semantic_min_margin": (
                    round(min(float(item.get("margin_after") or 0.0) for item in semantic_hard_negative_margin_table), 8)
                    if semantic_hard_negative_margin_table
                    else None
                ),
                "semantic_margin_report": semantic_margin_report,
                "min_margin": (
                    round(
                        min(
                            float(item.get("margin_after") or 0.0)
                            for item in hard_negative_margin_table
                        ),
                        8,
                    )
                    if hard_negative_margin_table
                    else None
                ),
                "min_margin_before": (
                    round(
                        min(
                            float(item.get("margin_before") or 0.0)
                            for item in hard_negative_margin_table
                            if item.get("margin_before") is not None
                        ),
                        8,
                    )
                    if any(item.get("margin_before") is not None for item in hard_negative_margin_table)
                    else None
                ),
            },
            "early_checkpoint_failure_analysis": {
                "trusted_replays": int(trusted_replays or 0),
                "is_checkpoint10": int(trusted_replays or 0) == 10,
                "final_unseen_pass_rate": final_decision_unseen_generalization_rate,
                "clean_held_out_final_pass_rate": clean_held_out_performance.get("final_pass_rate"),
                "hard_clean_held_out_pass_rate": hard_clean_held_out_performance.get("final_pass_rate"),
                "clean_held_out_pool_sufficient": clean_pool_sufficient,
                "hard_held_out_pass_rate": difficulty_scores.get("hard", {}).get("unseen_pass_rate"),
                "easy_unseen_pass_rate": difficulty_scores.get("easy", {}).get("unseen_pass_rate"),
                "medium_unseen_pass_rate": difficulty_scores.get("medium", {}).get("unseen_pass_rate"),
                "hard_negative_min_margin": (
                    min((float(item.get("margin_after") or 0.0) for item in hard_negative_margin_table), default=None)
                ),
                "failure_reasons": [
                    reason
                    for reason, failed in [
                        ("final unseen below 0.5", final_decision_unseen_generalization_rate < SANITY_UNSEEN_VARIANT_PASS_THRESHOLD),
                        ("clean held-out below 0.5", not clean_held_out_passed),
                        ("clean held-out pool has fewer than 10 per difficulty", not clean_pool_sufficient),
                        ("hard clean held-out has zero pass rate", not hard_clean_held_out_passed),
                        ("hard held-out has zero pass rate", float(difficulty_scores.get("hard", {}).get("unseen_pass_rate") or 0.0) <= 0.0),
                        ("hard-negative min margin is negative", bool(hard_negative_margin_table and min(float(item.get("margin_after") or 0.0) for item in hard_negative_margin_table) < 0.0)),
                    ]
                    if failed
                ],
            },
        },
        "memorized_exact_fen": bool(result_kind == "memorized_exact_fen"),
        "generalized_to_variants": bool(result_kind == "generalized_to_variants"),
        "partial_seen_variants_only": bool(result_kind == "partial_seen_variants_only"),
        "failed_to_learn": bool(result_kind == "failed_to_learn"),
        "blocked_by_search_or_static_eval": blocked_by_search_or_static_eval,
        "result_kind": result_kind,
        "learning_signal": bool(result_kind == "generalized_to_variants"),
        "learning_signal_reason": (
            "exact FEN, seen variants, and unseen variants met generalization thresholds"
            if result_kind == "generalized_to_variants"
            else "exact FEN and seen variants passed, but clean held-out generalization was not proven"
            if result_kind == "partial_seen_variants_only"
            else "after_top1 matched expected_move only on exact FEN"
            if result_kind == "memorized_exact_fen"
            else "raw policy learned expected_move but final decision did not change"
            if result_kind == "partial_policy_learned_but_decision_unchanged"
            else "after_top1 did not match expected_move"
        ),
        "human_explanation": explanation,
        "not_learning_success_sources": ["replay_loss", "hash_changed"],
    }


def _flow_timing_summary(games: list[PlannedGame]) -> dict:
    values = []
    by_role: dict[str, list[float]] = {}
    for game in games:
        for row in game.flow:
            if "think_ms" not in row:
                continue
            try:
                think_ms = float(row.get("think_ms") or 0.0)
            except Exception:
                continue
            values.append(think_ms)
            role = str(row.get("role") or "unknown")
            by_role.setdefault(role, []).append(think_ms)
    role_summary = {
        role: {
            "steps": len(items),
            "avg_think_ms": round(sum(items) / len(items), 3) if items else 0.0,
            "total_think_ms": round(sum(items), 3),
        }
        for role, items in sorted(by_role.items())
    }
    return {
        "steps_measured": len(values),
        "avg_think_ms_per_step": round(sum(values) / len(values), 3) if values else 0.0,
        "total_think_ms": round(sum(values), 3),
        "by_role": role_summary,
    }


def _checkpoint_timing_summary(checkpoints: list[dict]) -> dict:
    retrain_seconds = [float(row.get("retrain_duration_seconds") or 0.0) for row in checkpoints]
    checkpoint_seconds = [float(row.get("checkpoint_duration_seconds") or 0.0) for row in checkpoints]
    return {
        "checkpoint_count": len(checkpoints),
        "total_retrain_seconds": round(sum(retrain_seconds), 3),
        "avg_retrain_seconds": round(sum(retrain_seconds) / len(retrain_seconds), 3) if retrain_seconds else 0.0,
        "total_checkpoint_seconds": round(sum(checkpoint_seconds), 3),
        "avg_checkpoint_seconds": round(sum(checkpoint_seconds) / len(checkpoint_seconds), 3) if checkpoint_seconds else 0.0,
    }


def _engine_game_outcome(*, human_side: str, winner_color: str | None) -> str:
    engine_side = opponent(str(human_side or "white"))
    winner = str(winner_color or "").strip().lower()
    if winner not in {"white", "black"}:
        return "draw"
    return "win" if winner == engine_side else "loss"


def _stage_game_win_rates(game_results: list[dict], *, autorun_threshold: int) -> list[dict]:
    stage_size = max(1, int(autorun_threshold or AUTORUN_THRESHOLD))
    stages: dict[tuple[int, int], dict] = {}
    for stage_index, stage_start in enumerate(range(0, VALID_GAMES, stage_size), start=1):
        stage_end = min(stage_start + stage_size, VALID_GAMES)
        stages[(stage_start, stage_end)] = {
            "stage": f"{stage_start}-{stage_end}",
            "stage_index": stage_index,
            "basis": "trusted_valid_games_only",
            "invalid_games_excluded": True,
            "trusted_replay_start_exclusive": stage_start,
            "trusted_replay_end_inclusive": stage_end,
            "normal_games": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "skipped": False,
        }
    trusted_valid_index = 0
    for item in game_results:
        stored = item.get("stored_replay") or {}
        if item.get("category") != "valid" or stored.get("collection_tier") != "trusted":
            continue
        trusted_valid_index += 1
        stage_start = ((trusted_valid_index - 1) // stage_size) * stage_size
        if stage_start >= VALID_GAMES:
            continue
        stage_end = min(stage_start + stage_size, VALID_GAMES)
        bucket = stages[(stage_start, stage_end)]
        outcome = _engine_game_outcome(
            human_side=str(item.get("human_side") or "white"),
            winner_color=item.get("winner_color"),
        )
        bucket["normal_games"] += 1
        if outcome == "win":
            bucket["wins"] += 1
        elif outcome == "loss":
            bucket["losses"] += 1
        else:
            bucket["draws"] += 1
    rows = []
    previous_stage = None
    previous_win_rate = None
    for key in sorted(stages):
        row = stages[key]
        games = int(row.get("normal_games") or 0)
        if games:
            row["win_rate"] = round(float(row.get("wins") or 0) / games, 4)
        else:
            row["skipped"] = True
            row["win_rate"] = None
        row["previous_stage"] = previous_stage
        row["win_rate_delta_from_previous_stage"] = (
            round(float(row["win_rate"]) - float(previous_win_rate), 4)
            if row["win_rate"] is not None and previous_win_rate is not None
            else None
        )
        previous_stage = str(row.get("stage") or "")
        if row["win_rate"] is not None:
            previous_win_rate = row["win_rate"]
        rows.append(row)
    return rows


def _game_phase_from_move_index(move_index: int) -> str:
    if int(move_index or 0) <= 10:
        return "opening"
    if int(move_index or 0) <= 40:
        return "middlegame"
    return "endgame"


def _rating_bucket(value) -> str:
    try:
        rating = int(value or 0)
    except Exception:
        rating = 0
    if rating <= 0:
        return "unknown"
    if rating < 800:
        return "under_800"
    if rating < 1200:
        return "800_1200"
    if rating < 1600:
        return "1200_1600"
    return "1600_plus"


def _dataset_integrity_summary(train_rows: list[dict], rejected_rows: list[dict], game_results: list[dict]) -> dict:
    position_keys = []
    invalid_fen = 0
    illegal_moves = 0
    side_mismatch = 0
    terminal_positions = 0
    mate_positions = 0
    for row in train_rows:
        fen = str(row.get("fen") or "")
        side = str(row.get("side") or "").strip().lower()
        move_uci = str(row.get("move_uci") or "").strip().lower()
        key = f"{fen}|{side}|{move_uci}"
        position_keys.append(key)
        try:
            board = chess.Board(fen)
            if side and board.turn != (chess.WHITE if side == "white" else chess.BLACK):
                side_mismatch += 1
            if board.is_game_over():
                terminal_positions += 1
            if board.is_checkmate():
                mate_positions += 1
            try:
                move = chess.Move.from_uci(move_uci)
                if move not in board.legal_moves:
                    illegal_moves += 1
            except Exception:
                illegal_moves += 1
        except Exception:
            invalid_fen += 1
    unique_positions = len(set(position_keys))
    total_rows = len(train_rows)
    move_counts = []
    short_resign_games = 0
    for item in game_results:
        stored = item.get("stored_replay") or {}
        move_count = int(stored.get("move_count") or 0)
        if move_count:
            move_counts.append(move_count)
        if str(stored.get("result_reason") or "").lower() == "resign" and move_count < 10:
            short_resign_games += 1
    return {
        "total_rows": total_rows,
        "accepted_rows": len(train_rows),
        "rejected_rows": len(rejected_rows),
        "unique_positions": unique_positions,
        "duplicate_positions": max(0, total_rows - unique_positions),
        "duplicate_ratio": round((max(0, total_rows - unique_positions) / total_rows), 4) if total_rows else 0.0,
        "invalid_fen": invalid_fen,
        "illegal_moves": illegal_moves,
        "side_mismatch": side_mismatch,
        "mate_positions": mate_positions,
        "terminal_positions": terminal_positions,
        "avg_game_length": round(sum(move_counts) / len(move_counts), 3) if move_counts else 0.0,
        "short_resign_games": short_resign_games,
    }


def _replay_source_audit(game_results: list[dict]) -> dict:
    sources = {"human_ranked": 0, "human_casual": 0, "engine_selfplay": 0, "synthetic": 0, "unknown": 0}
    ratings = {"under_800": 0, "800_1200": 0, "1200_1600": 0, "1600_plus": 0, "unknown": 0}
    for item in game_results:
        category = str(item.get("category") or "")
        stored = item.get("stored_replay") or {}
        source = str(stored.get("source") or "").strip().lower()
        if category.startswith("invalid_"):
            sources["synthetic"] += 1
        elif source == "user_games":
            sources["human_casual"] += 1
        elif source in {"self_play", "teacher_guidance", "benchmark"}:
            sources["engine_selfplay"] += 1
        else:
            sources["unknown"] += 1
        ratings[_rating_bucket(stored.get("rating_estimate"))] += 1
    return {"replay_sources": sources, "rating_distribution": ratings}


def _position_quality_summary(classification_rows: list[dict]) -> dict:
    summary = {
        "opening": {"trusted": 0, "quarantine": 0, "rejected": 0},
        "middlegame": {"trusted": 0, "quarantine": 0, "rejected": 0},
        "endgame": {"trusted": 0, "quarantine": 0, "rejected": 0},
    }
    for row in classification_rows:
        move_count = int((row.get("stored_replay") or {}).get("move_count") or 0)
        phase = _game_phase_from_move_index(move_count)
        tier = str(row.get("actual_tier") or "rejected")
        if tier not in summary[phase]:
            tier = "rejected"
        summary[phase][tier] += 1
    return summary


def _poison_detection_summary(classification_rows: list[dict]) -> dict:
    total = max(1, len(classification_rows))
    forced_repetition = 0
    intentional_blunders = 0
    engine_copy_suspected = 0
    suspicious_resigns = 0
    for row in classification_rows:
        reasons = set(row.get("quarantine_reasons") or [])
        label = str(row.get("label") or "")
        if "suspicious_pattern" in reasons or "meaningless_loop" in label:
            forced_repetition += 1
        if "blunder" in label or "low_signal" in label:
            intentional_blunders += 1
        if row.get("duplicate_flag"):
            engine_copy_suspected += 1
        if "early_resign" in reasons:
            suspicious_resigns += 1
    return {
        "forced_repetition_patterns": forced_repetition,
        "intentional_blunders": intentional_blunders,
        "engine_copy_suspected": engine_copy_suspected,
        "suspicious_resign_rate": round(suspicious_resigns / total, 4),
        "suspicious_resigns": suspicious_resigns,
    }


def _fixed_probe_regression(before_after_eval: dict, keywords: set[str]) -> float:
    before_rows = (before_after_eval.get("fixed_probe_positions_before") or {}).get("positions") or []
    after_rows = (before_after_eval.get("fixed_probe_positions_after") or {}).get("positions") or []
    before_map = {str(row.get("position_id") or ""): row for row in before_rows}
    after_map = {str(row.get("position_id") or ""): row for row in after_rows}
    total = 0
    regressed = 0
    for position_id, before in before_map.items():
        if not any(keyword in position_id for keyword in keywords):
            continue
        after = after_map.get(position_id) or {}
        total += 1
        before_ok = bool(before.get("legal")) and float(before.get("score") or 0) >= 0
        after_ok = bool(after.get("legal")) and float(after.get("score") or 0) >= 0
        if before_ok and not after_ok:
            regressed += 1
    return round(regressed / total, 4) if total else 0.0


def _stage_regression_summary(stage_rates: list[dict]) -> dict:
    by_stage = {str(row.get("stage") or ""): row for row in stage_rates or []}
    first = by_stage.get("0-10") or {}
    second = by_stage.get("10-20") or {}
    ordered = [row for row in stage_rates or [] if row.get("win_rate") is not None]
    last = ordered[-1] if ordered else {}
    previous = ordered[-2] if len(ordered) >= 2 else {}
    first_rate = first.get("win_rate")
    second_rate = second.get("win_rate")
    last_rate = last.get("win_rate")
    late_stage_games = int(last.get("normal_games") or 0)
    late_stage_collapse = bool(
        last_rate is not None
        and late_stage_games >= LATE_STAGE_COLLAPSE_MIN_GAMES
        and float(last_rate) <= LATE_STAGE_COLLAPSE_WIN_RATE
    )
    late_stage_delta = (
        round(float(last_rate) - float(previous.get("win_rate")), 4)
        if last_rate is not None and previous.get("win_rate") is not None
        else None
    )
    if first_rate is None or second_rate is None:
        return {
            "stage_win_rate_drop_10_20_vs_0_10": None,
            "stage_regression_threshold": 0.2,
            "stage_catastrophic_regression": False,
            "late_stage": last.get("stage"),
            "late_stage_win_rate": last_rate,
            "late_stage_normal_games": late_stage_games,
            "late_stage_win_rate_delta_from_previous": late_stage_delta,
            "late_stage_win_rate_collapse": late_stage_collapse,
        }
    drop = round(float(first_rate) - float(second_rate), 4)
    return {
        "stage_win_rate_drop_10_20_vs_0_10": drop,
        "stage_regression_threshold": 0.2,
        "stage_catastrophic_regression": drop > 0.2,
        "late_stage": last.get("stage"),
        "late_stage_win_rate": last_rate,
        "late_stage_normal_games": late_stage_games,
        "late_stage_win_rate_delta_from_previous": late_stage_delta,
        "late_stage_win_rate_collapse": late_stage_collapse,
    }


def _score_for_label(deterministic: dict, label: str) -> float | None:
    for row in deterministic.get("score_table") or []:
        if str(row.get("model_label") or "") == label:
            return float(row.get("overall_deterministic_score") or 0.0)
    return None


def _category_score_for_label(deterministic: dict, label: str, category: str) -> float | None:
    for row in deterministic.get("score_table") or []:
        if str(row.get("model_label") or "") != label:
            continue
        bucket = (row.get("category_score") or {}).get(category) or {}
        if "score" not in bucket:
            return None
        return float(bucket.get("score") or 0.0)
    return None


def _mistake_probe_failures(checkpoints: list[dict]) -> list[dict]:
    failures = []
    for checkpoint in checkpoints or []:
        probe = checkpoint.get("mistake_retention_probe") or {}
        if probe.get("learning_signal") is not False:
            continue
        failures.append(
            {
                "trusted_count": checkpoint.get("trusted_count") or checkpoint.get("trusted_replays"),
                "probe_case_id": probe.get("probe_case_id"),
                "before_move": probe.get("before_move"),
                "after_move": probe.get("after_move"),
                "expected_move": probe.get("expected_move"),
                "avoided_same_error": probe.get("avoided_same_error"),
                "avoided_old_mistake": probe.get("avoided_old_mistake"),
                "matched_expected": probe.get("matched_expected"),
                "result_kind": probe.get("result_kind"),
                "learning_signal_reason": probe.get("learning_signal_reason") or probe.get("reason"),
            }
        )
    return failures


def _trainer_numeric(summary: dict, key_names: set[str]) -> float | None:
    stack = [summary.get("retrain_result") or {}]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                normalized = str(key).lower()
                if normalized in key_names:
                    try:
                        return float(value)
                    except Exception:
                        continue
                if isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(item, list):
            stack.extend(value for value in item if isinstance(value, (dict, list)))
    return None


def _retrain_stability_report(summary: dict) -> dict:
    deterministic = summary.get("deterministic_strength_snapshot") or {}
    stage = _stage_regression_summary(summary.get("stage_game_win_rates") or [])
    checkpoints = (summary.get("before_after_eval") or {}).get("checkpoints") or []
    baseline_score = _score_for_label(deterministic, "baseline")
    checkpoint10_score = _score_for_label(deterministic, "checkpoint@10")
    checkpoint20_score = _score_for_label(deterministic, "checkpoint@20")
    final_score = _score_for_label(deterministic, "final")
    baseline_mistake = _category_score_for_label(deterministic, "baseline", "mistake_retention")
    final_mistake = _category_score_for_label(deterministic, "final", "mistake_retention")
    deterministic_regressed_vs_baseline = bool(
        baseline_score is not None and final_score is not None and final_score < baseline_score
    )
    deterministic_regressed_vs_checkpoint10 = bool(
        checkpoint10_score is not None and final_score is not None and final_score < checkpoint10_score
    )
    deterministic_regressed_vs_checkpoint20 = bool(
        checkpoint20_score is not None and final_score is not None and final_score < checkpoint20_score
    )
    mistake_retention_regressed = bool(
        baseline_mistake is not None and final_mistake is not None and final_mistake < baseline_mistake
    )
    probe_failures = _mistake_probe_failures(checkpoints)
    checkpoint10_probe = next(
        (
            checkpoint.get("sanity_learning_probe") or {}
            for checkpoint in checkpoints
            if int(checkpoint.get("trusted_count") or checkpoint.get("trusted_replays") or 0) == 10
        ),
        {},
    )
    checkpoint20_probe = next(
        (
            checkpoint.get("sanity_learning_probe") or {}
            for checkpoint in checkpoints
            if int(checkpoint.get("trusted_count") or checkpoint.get("trusted_replays") or 0) == 20
        ),
        {},
    )
    checkpoint10_case_id = str(((checkpoint10_probe.get("case") or {}).get("case_id") or ""))
    checkpoint20_case_id = str(((checkpoint20_probe.get("case") or {}).get("case_id") or ""))
    same_sanity_case = bool(checkpoint10_case_id and checkpoint10_case_id == checkpoint20_case_id)
    prior_retention = checkpoint20_probe.get("prior_learned_case_retention") or {}
    prior_retention_regressed = bool(int(prior_retention.get("failed_count") or 0) > 0)
    checkpoint20_exact_regression = bool(
        (same_sanity_case and checkpoint10_probe.get("exact_fen_pass") and checkpoint20_probe.get("exact_fen_pass") is False)
        or prior_retention_regressed
    )
    checkpoint20_seen_regression = bool(
        same_sanity_case
        and
        checkpoint10_probe
        and checkpoint20_probe
        and float(checkpoint20_probe.get("seen_variant_pass_rate") or 0.0)
        < float(checkpoint10_probe.get("seen_variant_pass_rate") or 0.0) - 0.2
    )
    checkpoint20_unseen_regression = bool(
        same_sanity_case
        and
        checkpoint10_probe
        and checkpoint20_probe
        and float(checkpoint20_probe.get("unseen_variant_pass_rate") or 0.0)
        < float(checkpoint10_probe.get("unseen_variant_pass_rate") or 0.0) - 0.2
    )
    checkpoint20_decision_blocked = bool((checkpoint20_probe.get("final_decision_learning") or {}).get("learning_signal") is False)
    late_stage_collapse = bool(stage.get("late_stage_win_rate_collapse"))
    suspected = bool(
        (
            late_stage_collapse
            and (
                deterministic_regressed_vs_checkpoint10
                or deterministic_regressed_vs_baseline
                or deterministic_regressed_vs_checkpoint20
                or mistake_retention_regressed
                or bool(probe_failures)
            )
        )
        or checkpoint20_exact_regression
        or checkpoint20_seen_regression
        or checkpoint20_unseen_regression
    )
    reasons = []
    if late_stage_collapse:
        reasons.append(
            f"late trusted-valid stage {stage.get('late_stage')} collapsed to win_rate={stage.get('late_stage_win_rate')}"
        )
    if deterministic_regressed_vs_baseline:
        reasons.append("final deterministic score regressed below baseline")
    if deterministic_regressed_vs_checkpoint10:
        reasons.append("final deterministic score regressed below checkpoint@10")
    if deterministic_regressed_vs_checkpoint20:
        reasons.append("final deterministic score regressed below checkpoint@20")
    if mistake_retention_regressed:
        reasons.append("mistake_retention deterministic category regressed")
    if probe_failures:
        reasons.append("mistake_retention_probe did not prove correction of prior mistakes")
    if prior_retention_regressed:
        reasons.append("checkpoint@20 failed prior-learned sanity case retention")
    elif checkpoint20_exact_regression:
        reasons.append("checkpoint@20 regressed the same exact-FEN sanity case learned by checkpoint@10")
    if checkpoint20_seen_regression:
        reasons.append("checkpoint@20 seen-variant retention regressed by more than 0.2 from checkpoint@10")
    if checkpoint20_unseen_regression:
        reasons.append("checkpoint@20 unseen-variant retention regressed by more than 0.2 from checkpoint@10")
    if checkpoint20_decision_blocked:
        reasons.append("checkpoint@20 final decision learning is blocked by search/static eval or another final-decision path")
    integrity = summary.get("dataset_integrity") or {}
    replay_diversity = {
        "unique_positions": integrity.get("unique_positions"),
        "duplicate_positions": integrity.get("duplicate_positions"),
        "duplicate_ratio": integrity.get("duplicate_ratio"),
        "position_quality": summary.get("position_quality") or {},
    }
    return {
        "suspected_catastrophic_regression": suspected,
        "reasons": reasons,
        "replay_size": {
            "trusted_replays": (summary.get("replay_summary") or {}).get("trusted_replays"),
            "quarantine_replays": (summary.get("replay_summary") or {}).get("quarantine_replays"),
            "accepted_rows": (summary.get("dataset_result") or {}).get("accepted_rows"),
            "accepted_train_samples": (summary.get("dataset_result") or {}).get("accepted_train_samples"),
            "accepted_eval_samples": (summary.get("dataset_result") or {}).get("accepted_eval_samples"),
        },
        "replay_diversity": replay_diversity,
        "trainer_hyperparameters": {
            "learning_rate": _trainer_numeric(summary, {"learning_rate", "lr"}),
            "epochs": _trainer_numeric(summary, {"epochs", "epoch_count"}),
            "gradient_norm": _trainer_numeric(summary, {"gradient_norm", "grad_norm"}),
            "loss_delta": _trainer_numeric(summary, {"loss_delta"}),
        },
        "deterministic_scores": {
            "baseline": baseline_score,
            "checkpoint@10": checkpoint10_score,
            "checkpoint@20": checkpoint20_score,
            "final": final_score,
            "regressed_vs_baseline": deterministic_regressed_vs_baseline,
            "regressed_vs_checkpoint10": deterministic_regressed_vs_checkpoint10,
            "regressed_vs_checkpoint20": deterministic_regressed_vs_checkpoint20,
        },
        "mistake_retention": {
            "baseline_score": baseline_mistake,
            "final_score": final_mistake,
            "regressed": mistake_retention_regressed,
            "probe_failures": probe_failures,
        },
        "checkpoint10_vs_checkpoint20_retention": {
            "checkpoint10": {
                "exact_fen_pass": checkpoint10_probe.get("exact_fen_pass"),
                "seen_variant_pass_rate": checkpoint10_probe.get("seen_variant_pass_rate"),
                "unseen_variant_pass_rate": checkpoint10_probe.get("unseen_variant_pass_rate"),
                "final_decision_generalization_rate": checkpoint10_probe.get("final_decision_generalization_rate"),
                "result_kind": checkpoint10_probe.get("result_kind"),
            },
            "checkpoint20": {
                "exact_fen_pass": checkpoint20_probe.get("exact_fen_pass"),
                "seen_variant_pass_rate": checkpoint20_probe.get("seen_variant_pass_rate"),
                "unseen_variant_pass_rate": checkpoint20_probe.get("unseen_variant_pass_rate"),
                "final_decision_generalization_rate": checkpoint20_probe.get("final_decision_generalization_rate"),
                "result_kind": checkpoint20_probe.get("result_kind"),
                "blocked_by_search_or_static_eval": checkpoint20_probe.get("blocked_by_search_or_static_eval"),
                "blocked_reason": (checkpoint20_probe.get("final_decision_learning") or {}).get("blocked_reason"),
            },
            "exact_regression": checkpoint20_exact_regression,
            "seen_variant_regression": checkpoint20_seen_regression,
            "unseen_variant_regression": checkpoint20_unseen_regression,
            "final_decision_blocked": checkpoint20_decision_blocked,
            "same_sanity_case": same_sanity_case,
            "prior_learned_case_retention": prior_retention,
        },
        "late_stage": {
            "stage": stage.get("late_stage"),
            "normal_games": stage.get("late_stage_normal_games"),
            "win_rate": stage.get("late_stage_win_rate"),
            "delta_from_previous": stage.get("late_stage_win_rate_delta_from_previous"),
            "collapsed": late_stage_collapse,
        },
        "checkpoint_evidence": [
            {
                "trusted_count": checkpoint.get("trusted_count") or checkpoint.get("trusted_replays"),
                "dataset_hash": checkpoint.get("dataset_hash"),
                "accepted_rows": (checkpoint.get("dataset_result") or {}).get("accepted_rows"),
                "started_at": checkpoint.get("started_at"),
                "finished_at": checkpoint.get("finished_at"),
                "duration_seconds": checkpoint.get("duration_seconds"),
                "previous_model_hash": checkpoint.get("previous_model_hash") or checkpoint.get("pre_checkpoint_model_sha256"),
                "new_model_hash": checkpoint.get("new_model_hash") or checkpoint.get("post_checkpoint_model_sha256"),
                "hash_changed": checkpoint.get("hash_changed") if "hash_changed" in checkpoint else checkpoint.get("model_hash_changed"),
            }
            for checkpoint in checkpoints
        ],
    }


def _checkpoint_probe_embedding_after(probe: dict) -> float | None:
    embedding = (((probe.get("feature_generalization_debug") or {}).get("embedding_similarity") or {}).get("policy_embedding_similarity_after") or {})
    if "avg_similarity" not in embedding:
        return None
    return float(embedding.get("avg_similarity") or 0.0)


def _checkpoint_probe_embedding_delta(probe: dict) -> float | None:
    embedding = ((probe.get("feature_generalization_debug") or {}).get("embedding_similarity") or {})
    if "avg_similarity_delta" not in embedding:
        return None
    return float(embedding.get("avg_similarity_delta") or 0.0)


def _checkpoint_probe_hard_negative_margin(probe: dict) -> float | None:
    margins = ((probe.get("feature_generalization_debug") or {}).get("expected_vs_hard_negative_margin") or {})
    if "min_margin" not in margins:
        return None
    return float(margins.get("min_margin") or 0.0)


def _checkpoint_consistency_report(summary: dict) -> dict:
    checkpoints = (summary.get("before_after_eval") or {}).get("checkpoints") or []
    rows: list[dict] = []
    drift_rows: list[dict] = []
    retention_chain: list[dict] = []
    instability_reasons: list[str] = []
    previous_row: dict | None = None
    thresholds = {
        "clean_held_out_final_min": SANITY_UNSEEN_VARIANT_PASS_THRESHOLD,
        "hard_clean_held_out_min_exclusive": 0.0,
        "questionable_static_cp_delta": SANITY_LABEL_QUESTIONABLE_CP_DELTA,
        "hard_exclude_static_cp_delta": SANITY_LABEL_HARD_EXCLUDE_CP_DELTA,
        "embedding_drift_drop_limit": -0.05,
        "policy_margin_min": 0.0,
    }
    for checkpoint in checkpoints:
        trusted = checkpoint.get("trusted_count") or checkpoint.get("trusted_replays")
        probe = checkpoint.get("sanity_learning_probe") or {}
        training = checkpoint.get("sanity_variant_training") or {}
        prior_retention = probe.get("prior_learned_case_retention") or {}
        heavy_skipped = bool(checkpoint.get("heavy_sanity_skipped")) or str(probe.get("result_kind") or "") == "skipped_heavy_diagnostics"
        exact_retention = bool(probe.get("exact_fen_pass"))
        seen_retention = float(probe.get("seen_variant_pass_rate") or 0.0)
        unseen_retention = float(probe.get("final_decision_unseen_generalization_rate") or 0.0)
        raw_unseen_retention = float(probe.get("raw_policy_unseen_generalization_rate") or 0.0)
        hard_retention = float(probe.get("hard_unseen_pass_rate") or 0.0)
        clean_held_out_count = int(probe.get("balanced_clean_held_out_count") or probe.get("clean_held_out_count") or 0)
        clean_held_out_retention = float(probe.get("balanced_clean_held_out_pass_rate") or probe.get("clean_held_out_final_pass_rate") or 0.0)
        clean_held_out_raw_retention = float(probe.get("clean_held_out_raw_policy_pass_rate") or 0.0)
        hard_clean_held_out_count = int(probe.get("hard_clean_held_out_count") or 0)
        hard_clean_held_out_retention = float(probe.get("hard_clean_held_out_pass_rate") or 0.0)
        clean_heldout_by_semantic = probe.get("balanced_clean_heldout_by_semantic") or probe.get("clean_heldout_by_semantic") or {}
        clean_pool_sufficient = bool(probe.get("clean_held_out_pool_sufficient"))
        prior_failed = int(prior_retention.get("failed_count") or 0)
        embedding_after = _checkpoint_probe_embedding_after(probe)
        embedding_delta = _checkpoint_probe_embedding_delta(probe)
        hard_margin = _checkpoint_probe_hard_negative_margin(probe)
        feature_debug = probe.get("feature_generalization_debug") or {}
        hard_margin_debug = feature_debug.get("expected_vs_hard_negative_margin") or {}
        semantic_hard_margin = hard_margin_debug.get("semantic_min_margin")
        semantic_margin_value = float(semantic_hard_margin) if semantic_hard_margin is not None else None
        semantic_analysis = feature_debug.get("semantic_analysis") or {}
        semantic_distribution = training.get("semantic_class_distribution") or {}
        semantic_distribution_by_split = training.get("semantic_distribution_by_split") or feature_debug.get("semantic_distribution_by_split") or {}
        semantic_coverage_by_split = training.get("semantic_coverage_by_split") or feature_debug.get("semantic_coverage_by_split") or {}
        train_to_gate_semantic_gap = training.get("train_to_gate_semantic_gap") or feature_debug.get("train_to_gate_semantic_gap") or {}
        semantic_sampling = training.get("semantic_sampling") or {}
        train_effective_distribution = training.get("train_effective_distribution") or ((semantic_sampling.get("effective_distribution") or {}).get("effective_weight") or {})
        effective_sample_weight_by_semantic = training.get("effective_sample_weight_by_semantic") or semantic_sampling.get("sample_weight_by_semantic") or {}
        held_out_pool = feature_debug.get("held_out_pool") or {}
        semantic_coverage_complete = bool(held_out_pool.get("semantic_coverage_complete", True))
        semantic_coverage_missing = list(held_out_pool.get("semantic_coverage_missing") or [])
        semantic_confusion_gate = semantic_analysis.get("semantic_confusion_gate") or {}
        targeted_centroid_after = semantic_analysis.get("targeted_centroid_distances_after") or {}
        label_quality = feature_debug.get("label_quality") or {}
        row_reasons: list[str] = []
        if heavy_skipped:
            pass
        else:
            if not exact_retention:
                row_reasons.append("exact retention failed")
            if seen_retention < SANITY_SEEN_VARIANT_PASS_THRESHOLD:
                row_reasons.append("seen retention below threshold")
            if clean_held_out_count <= 0:
                row_reasons.append("clean held-out labels missing")
            elif clean_held_out_retention < SANITY_UNSEEN_VARIANT_PASS_THRESHOLD:
                row_reasons.append("clean held-out retention below threshold")
            if not clean_pool_sufficient:
                row_reasons.append("clean held-out pool has fewer than 10 cases per difficulty")
            if hard_clean_held_out_count <= 0:
                row_reasons.append("hard clean held-out labels missing")
            elif hard_clean_held_out_retention <= 0.0:
                row_reasons.append("hard clean held-out retention is zero")
        if not heavy_skipped:
            for semantic in BALANCED_PROMOTION_SEMANTIC_CLASSES:
                semantic_row = clean_heldout_by_semantic.get(semantic) or {}
                if int(semantic_row.get("total") or 0) <= 0:
                    row_reasons.append(f"semantic_coverage_missing: {semantic}")
                elif int(semantic_row.get("passed") or 0) <= 0:
                    row_reasons.append(f"semantic class {semantic} clean held-out pass count is zero")
        flank_difficulty = probe.get("flank_difficulty_performance") or feature_debug.get("flank_difficulty_performance") or ((feature_debug.get("clean_vs_questionable_performance") or {}).get("flank_difficulty_performance") or {})
        contextual_flank = probe.get("contextual_flank_performance") or feature_debug.get("contextual_flank_performance") or ((feature_debug.get("clean_vs_questionable_performance") or {}).get("contextual_flank_performance") or {})
        bad_random_confusion = probe.get("bad_random_flank_push_confusion") or feature_debug.get("bad_random_flank_push_confusion") or ((contextual_flank.get("bad_random_flank_push_confusion") if isinstance(contextual_flank, dict) else {}) or {})
        if not heavy_skipped:
            if flank_difficulty and not bool(flank_difficulty.get("hard_coverage_complete", True)):
                row_reasons.append("flank hard clean gate coverage missing")
            if contextual_flank and int(contextual_flank.get("hard_clean_count") or 0) > 0 and int(contextual_flank.get("hard_clean_contextual_hits") or 0) <= 0:
                row_reasons.append("contextual flank hard clean pass rate is zero")
            if int((bad_random_confusion or {}).get("promoted_count") or 0) > 0:
                row_reasons.append("bad_random_flank_push promoted")
            if prior_failed > 0:
                row_reasons.append("prior learned case retention regressed")
            if hard_margin is not None and hard_margin < 0.0:
                row_reasons.append("hard-negative margin is negative")
            if semantic_margin_value is not None and semantic_margin_value < 0.0:
                row_reasons.append("semantic hard-negative margin is negative")
            for split, distribution in semantic_distribution.items():
                if distribution and not distribution.get("balanced", True):
                    row_reasons.append(f"semantic class distribution below minimum for {split}")
                if distribution and bool(distribution.get("kingside_overpowers_central")):
                    row_reasons.append(f"kingside semantic candidates overpower central break in {split}")
            for split, counts in semantic_distribution_by_split.items():
                missing_zero = [
                    semantic for semantic in SEMANTIC_REQUIRED_CLASSES
                    if int((counts or {}).get(semantic) or 0) <= 0
                ]
                if missing_zero:
                    row_reasons.append(f"semantic_coverage_missing in {split}: {','.join(missing_zero)}")
            if semantic_sampling and not bool(semantic_sampling.get("passed", True)):
                row_reasons.append("semantic_sampling_skew")
            if not bool((semantic_coverage_by_split.get("train") or {}).get("complete", True)) or not bool((semantic_coverage_by_split.get("validation") or {}).get("complete", True)):
                row_reasons.append("train_validation_semantic_coverage_incomplete")
            if not semantic_coverage_complete or semantic_coverage_missing:
                row_reasons.append(f"semantic_coverage_missing: {','.join(semantic_coverage_missing)}")
            if semantic_confusion_gate and not semantic_confusion_gate.get("passed", True):
                row_reasons.append("central break to kingside semantic confusion exceeds threshold")
            if targeted_centroid_after and not targeted_centroid_after.get("passed", True):
                row_reasons.append("targeted semantic centroid distance below threshold")
            if embedding_delta is not None and embedding_delta < thresholds["embedding_drift_drop_limit"]:
                row_reasons.append("embedding similarity decreased after retrain")
        row = {
            "trusted_count": trusted,
            "exact_retention": exact_retention,
            "seen_retention": round(seen_retention, 4),
            "unseen_retention": round(unseen_retention, 4),
            "raw_unseen_retention": round(raw_unseen_retention, 4),
            "hard_held_out_retention": round(hard_retention, 4),
            "clean_held_out_count": clean_held_out_count,
            "clean_held_out_retention": round(clean_held_out_retention, 4),
            "clean_held_out_raw_retention": round(clean_held_out_raw_retention, 4),
            "hard_clean_held_out_count": hard_clean_held_out_count,
            "hard_clean_held_out_retention": round(hard_clean_held_out_retention, 4),
            "clean_held_out_by_difficulty": probe.get("clean_held_out_by_difficulty") or {},
            "clean_held_out_by_semantic": probe.get("clean_held_out_by_semantic") or {},
            "clean_heldout_by_semantic": clean_heldout_by_semantic,
            "balanced_gate_semantic_set": probe.get("balanced_gate_semantic_set") or list(BALANCED_PROMOTION_SEMANTIC_CLASSES),
            "excluded_style_semantics": probe.get("excluded_style_semantics") or list(STYLE_AUDIT_SEMANTIC_CLASSES),
            "balanced_clean_heldout_by_semantic": probe.get("balanced_clean_heldout_by_semantic") or {},
            "development_multi_good_credit": probe.get("development_multi_good_credit") or {},
            "attacking_style_audit": probe.get("attacking_style_audit") or {},
            "central_flank_failed_case_analysis": probe.get("central_flank_failed_case_analysis") or feature_debug.get("central_flank_failed_case_analysis") or {},
            "flank_label_audit": probe.get("flank_label_audit") or feature_debug.get("flank_label_audit") or ((feature_debug.get("clean_vs_questionable_performance") or {}).get("flank_label_audit") or {}),
            "flank_label_audit_v2": probe.get("flank_label_audit_v2") or feature_debug.get("flank_label_audit_v2") or probe.get("flank_label_audit") or feature_debug.get("flank_label_audit") or {},
            "flank_reason_distribution": probe.get("flank_reason_distribution") or feature_debug.get("flank_reason_distribution") or {},
            "flank_difficulty_performance": probe.get("flank_difficulty_performance") or feature_debug.get("flank_difficulty_performance") or ((feature_debug.get("clean_vs_questionable_performance") or {}).get("flank_difficulty_performance") or {}),
            "contextual_flank_performance": contextual_flank,
            "contextual_flank_pass_rate": probe.get("contextual_flank_pass_rate") if probe.get("contextual_flank_pass_rate") is not None else feature_debug.get("contextual_flank_pass_rate"),
            "bad_random_flank_push_confusion": bad_random_confusion,
            "context_feature_importance": probe.get("context_feature_importance") or feature_debug.get("context_feature_importance") or [],
            "central_vs_flank_boundary": probe.get("central_vs_flank_boundary") or feature_debug.get("central_vs_flank_boundary") or ((feature_debug.get("clean_vs_questionable_performance") or {}).get("central_vs_flank_boundary") or {}),
            "failed_by_semantic_top3": feature_debug.get("failed_by_semantic_top3") or ((feature_debug.get("clean_vs_questionable_performance") or {}).get("failed_by_semantic_top3") or {}),
            "clean_held_out_pool_sufficient": clean_pool_sufficient,
            "questionable_held_out_count": int(probe.get("questionable_held_out_count") or 0),
            "result_kind": probe.get("result_kind"),
            "prior_retention_failed_count": prior_failed,
            "hard_negative_min_margin": round(hard_margin, 6) if hard_margin is not None else None,
            "embedding_similarity_after": round(embedding_after, 6) if embedding_after is not None else None,
            "embedding_similarity_delta": round(embedding_delta, 6) if embedding_delta is not None else None,
            "hard_negative_margin_table": hard_margin_debug.get("hard_negative_margin_table") or [],
            "semantic_hard_negative_margin_table": hard_margin_debug.get("semantic_hard_negative_margin_table") or [],
            "semantic_hard_negative_min_margin": round(semantic_margin_value, 6) if semantic_margin_value is not None else None,
            "semantic_margin_report": hard_margin_debug.get("semantic_margin_report") or ((feature_debug.get("semantic_analysis") or {}).get("semantic_margin_report") or {}),
            "semantic_class_distribution": semantic_distribution,
            "semantic_distribution_by_split": semantic_distribution_by_split,
            "semantic_coverage_by_split": semantic_coverage_by_split,
            "train_semantic_distribution": semantic_distribution_by_split.get("train") or {},
            "validation_semantic_distribution": semantic_distribution_by_split.get("validation") or {},
            "train_to_gate_semantic_gap": train_to_gate_semantic_gap,
            "semantic_sampling": semantic_sampling,
            "effective_sample_weight_by_semantic": effective_sample_weight_by_semantic,
            "train_effective_distribution": train_effective_distribution,
            "semantic_coverage_complete": semantic_coverage_complete,
            "semantic_coverage_missing": semantic_coverage_missing,
            "semantic_confusion_gate": semantic_confusion_gate,
            "targeted_centroid_distances_before": semantic_analysis.get("targeted_centroid_distances_before") or {},
            "targeted_centroid_distances_after": targeted_centroid_after,
            "early_checkpoint_failure_analysis": feature_debug.get("early_checkpoint_failure_analysis") or {},
            "embedding_similarity_delta_by_group": feature_debug.get("embedding_similarity_delta_by_group") or {},
            "invariance_context_key_examples": training.get("invariance_context_key_examples") or [],
            "label_quality": label_quality,
            "held_out_label_quality": feature_debug.get("held_out_label_quality") or {},
            "held_out_pool": held_out_pool,
            "label_quality_summary": feature_debug.get("label_quality_summary") or label_quality.get("summary") or {},
            "excluded_from_gate_cases": feature_debug.get("excluded_from_gate_cases") or label_quality.get("excluded_from_gate_cases") or [],
            "clean_vs_questionable_performance": feature_debug.get("clean_vs_questionable_performance") or {},
            "semantic_analysis": semantic_analysis,
            "failed_clean_cases_top3": feature_debug.get("failed_clean_cases_top3") or [],
            "label_quality_warning": bool(label_quality.get("label_quality_warning")),
            "curriculum_split": training.get("split") or {},
            "smoothing": training.get("sanity_smoothing") or training.get("smoothing") or {},
            "central_flank_targeted_curriculum": training.get("central_flank_targeted_curriculum") or ((training.get("curriculum") or {}).get("central_flank_targeted_curriculum") or {}),
            "passed": not row_reasons,
            "reasons": row_reasons,
        }
        if previous_row:
            unseen_delta = round(row["clean_held_out_retention"] - previous_row["clean_held_out_retention"], 4)
            embedding_drift = None
            if row["embedding_similarity_after"] is not None and previous_row["embedding_similarity_after"] is not None:
                embedding_drift = round(row["embedding_similarity_after"] - previous_row["embedding_similarity_after"], 6)
            margin_drift = None
            if row["hard_negative_min_margin"] is not None and previous_row["hard_negative_min_margin"] is not None:
                margin_drift = round(row["hard_negative_min_margin"] - previous_row["hard_negative_min_margin"], 6)
            row["final_unseen_delta_from_previous"] = unseen_delta
            row["embedding_drift_from_previous"] = embedding_drift
            row["policy_margin_drift_from_previous"] = margin_drift
            if unseen_delta < -0.001:
                row["reasons"].append("clean held-out retention dropped from previous checkpoint")
                row["passed"] = False
            if embedding_drift is not None and embedding_drift < thresholds["embedding_drift_drop_limit"]:
                row["reasons"].append("embedding drift exceeded drop limit")
                row["passed"] = False
            if margin_drift is not None and margin_drift < 0.0 and row["hard_negative_min_margin"] is not None and row["hard_negative_min_margin"] < 0.0:
                row["reasons"].append("policy margin drift left hard-negative margin negative")
                row["passed"] = False
        rows.append(row)
        drift_rows.append(
            {
                "trusted_count": trusted,
                "embedding_similarity_after": row["embedding_similarity_after"],
                "embedding_similarity_delta": row["embedding_similarity_delta"],
                "embedding_drift_from_previous": row.get("embedding_drift_from_previous"),
                "hard_negative_min_margin": row["hard_negative_min_margin"],
                "policy_margin_drift_from_previous": row.get("policy_margin_drift_from_previous"),
            }
        )
        retention_chain.append(
            {
                "trusted_count": trusted,
                "exact": row["exact_retention"],
                "seen": row["seen_retention"],
                "unseen": row["unseen_retention"],
                "raw_unseen": row["raw_unseen_retention"],
                "hard_held_out": row["hard_held_out_retention"],
                "clean_held_out": row["clean_held_out_retention"],
                "hard_clean_held_out": row["hard_clean_held_out_retention"],
                "prior_retention_failed_count": row["prior_retention_failed_count"],
                "passed": row["passed"],
            }
        )
        for reason in row["reasons"]:
            instability_reasons.append(f"trusted={trusted}: {reason}")
        previous_row = row
    passed = bool(rows) and not instability_reasons
    return {
        "passed": passed,
        "instability": not passed,
        "instability_reasons": instability_reasons,
        "checkpoint_consistency_table": rows,
        "embedding_drift_table": drift_rows,
        "retention_chain": retention_chain,
        "thresholds": thresholds,
    }


def _stability_summary(summary: dict) -> dict:
    before_after = summary.get("before_after_eval") or {}
    before_benchmark = before_after.get("benchmark_before") or {}
    after_benchmark = before_after.get("benchmark_after") or {}
    benchmark_skipped = bool(before_benchmark.get("skipped") or after_benchmark.get("skipped"))
    illegal_move_delta = None
    blunder_before = None
    blunder_after = None
    if not benchmark_skipped:
        illegal_move_delta = round(float(after_benchmark.get("legal_rate") or 0.0) - float(before_benchmark.get("legal_rate") or 0.0), 4)
        blunder_before = float(before_benchmark.get("low_quality_rate") or 0.0)
        blunder_after = float(after_benchmark.get("low_quality_rate") or 0.0)
    opening_regression = _fixed_probe_regression(before_after, {"opening", "scholar", "free_queen"})
    tactical_regression = _fixed_probe_regression(before_after, {"mate", "fork", "capture", "queen", "rook"})
    endgame_regression = _fixed_probe_regression(before_after, {"endgame", "promotion", "stalemate"})
    stage_regression = _stage_regression_summary(summary.get("stage_game_win_rates") or [])
    retrain_stability = summary.get("retrain_stability_report") or _retrain_stability_report(summary)
    checkpoint_consistency = summary.get("checkpoint_consistency") or {}
    catastrophic = bool(
        (illegal_move_delta is not None and illegal_move_delta < -0.05)
        or bool(stage_regression.get("stage_catastrophic_regression"))
        or bool(retrain_stability.get("suspected_catastrophic_regression"))
        or bool(checkpoint_consistency.get("instability"))
        or opening_regression > 0.10
        or tactical_regression > 0.10
        or endgame_regression > 0.10
        or any(str(row.get("verdict") or "") == "FAIL" for row in before_after.get("checkpoints") or [])
    )
    return {
        "catastrophic_regression": catastrophic,
        "opening_regression": opening_regression,
        "tactical_regression": tactical_regression,
        "endgame_regression": endgame_regression,
        "illegal_move_delta": illegal_move_delta,
        "blunder_rate_before": blunder_before,
        "blunder_rate_after": blunder_after,
        **stage_regression,
    }


def _promotion_gate_summary(summary: dict) -> dict:
    reasons = []
    expected_trusted = int(summary.get("expected_trusted_replays") or VALID_GAMES)
    expected_quarantine = int(summary.get("expected_quarantine_replays") if summary.get("expected_quarantine_replays") is not None else INVALID_GAMES)
    if summary.get("replay_summary", {}).get("trusted_replays") != expected_trusted:
        reasons.append("insufficient trusted games")
    if summary.get("replay_summary", {}).get("quarantine_replays") != expected_quarantine:
        reasons.append("unexpected quarantine count")
    integrity = summary.get("dataset_integrity") or {}
    poison = summary.get("poison_detection") or {}
    if int(integrity.get("contaminated_rows") or 0) > 0:
        reasons.append("contaminated rows entered train dataset")
    if float(integrity.get("duplicate_ratio") or 0.0) > DATASET_DUPLICATE_RATIO_LIMIT:
        reasons.append("duplicate ratio exceeded threshold")
    if int(integrity.get("invalid_fen") or 0) > 0:
        reasons.append("invalid FEN detected in dataset")
    if int(integrity.get("illegal_moves") or 0) > 0:
        reasons.append("illegal moves detected in dataset")
    if int(integrity.get("side_mismatch") or 0) > 0:
        reasons.append("side mismatch detected in dataset")
    if int(integrity.get("short_resign_games") or 0) > DATASET_SHORT_RESIGN_LIMIT:
        reasons.append("short resign games exceeded threshold")
    if int(poison.get("forced_repetition_patterns") or 0) > POISON_REPETITION_LIMIT:
        reasons.append("forced repetition poison signal exceeded threshold")
    if int(poison.get("intentional_blunders") or 0) > POISON_INTENTIONAL_BLUNDER_LIMIT:
        reasons.append("intentional blunder poison signal exceeded threshold")
    if int(poison.get("engine_copy_suspected") or 0) > POISON_ENGINE_COPY_LIMIT:
        reasons.append("engine copy/duplicate poison signal exceeded threshold")
    if float(poison.get("suspicious_resign_rate") or 0.0) > POISON_SUSPICIOUS_RESIGN_RATE_LIMIT:
        reasons.append("suspicious resign rate exceeded threshold")
    stability = summary.get("stability") or {}
    if stability.get("catastrophic_regression"):
        reasons.append("catastrophic regression detected")
    retrain_stability = summary.get("retrain_stability_report") or {}
    if retrain_stability.get("suspected_catastrophic_regression"):
        reasons.extend([f"retrain stability risk: {reason}" for reason in retrain_stability.get("reasons") or []])
    checkpoint_consistency = summary.get("checkpoint_consistency") or {}
    if checkpoint_consistency and not checkpoint_consistency.get("passed", True):
        reasons.extend([f"checkpoint instability: {reason}" for reason in checkpoint_consistency.get("instability_reasons") or []])
    override_audit = summary.get("policy_override_audit") or {}
    if override_audit and not override_audit.get("passed", True):
        reasons.extend([f"policy override risk: {reason}" for reason in override_audit.get("regression_reasons") or []])
    opening_audit = summary.get("opening_target_margin_audit") or {}
    if opening_audit and opening_audit.get("supported"):
        if int(opening_audit.get("low_margin_override_applied_count") or 0) > 0:
            reasons.append("exp4 opening low-margin policy override was applied; cannot count as learning success")
        if opening_audit.get("targeted_learning_success") and not opening_audit.get("broad_strength_improvement"):
            reasons.append("exp4 targeted mistake-retention success did not prove broad deterministic strength improvement")
        if opening_audit.get("final_decision_alignment_passed") is False:
            reasons.append("exp4 opening final decision alignment failed or remains unresolved")
    style_audit = summary.get("style_profile_audit") or {}
    if style_audit and style_audit.get("supported") and not style_audit.get("passed", True):
        reasons.append("style profile audit found unsafe style override")
    deterministic = summary.get("deterministic_strength_snapshot") or {}
    if not deterministic or deterministic.get("skipped"):
        reasons.append(f"deterministic strength gate skipped: {deterministic.get('reason') or 'missing'}")
    elif not deterministic.get("passed"):
        reasons.extend([f"deterministic strength gate failed: {reason}" for reason in deterministic.get("reasons") or []])
    final_det = (deterministic.get("final") or {}) if deterministic else {}
    if final_det:
        if float(final_det.get("illegal_rate") or 0.0) != 0.0:
            reasons.append("deterministic illegal_rate is nonzero")
        if float(final_det.get("blunder_avoid_rate") or 0.0) < DETERMINISTIC_MIN_BLUNDER_AVOID_RATE:
            reasons.append("deterministic blunder_avoid_rate below threshold")
        if bool((summary.get("quick_retrain_gate") or {}).get("enabled")):
            score_by_label = {
                str(row.get("model_label") or ""): float(row.get("overall_deterministic_score") or 0.0)
                for row in deterministic.get("score_table") or []
            }
            if "baseline" in score_by_label and "final" in score_by_label and score_by_label["final"] <= score_by_label["baseline"]:
                reasons.append("deterministic score did not improve over baseline; learning success not proven")
    for checkpoint in (summary.get("before_after_eval") or {}).get("checkpoints") or []:
        mistake_probe = checkpoint.get("mistake_retention_probe") or {}
        if mistake_probe.get("learning_signal") is False:
            reason = str(mistake_probe.get("learning_signal_reason") or mistake_probe.get("reason") or "no mistake-retention learning signal")
            trusted = checkpoint.get("trusted_count") or checkpoint.get("trusted_replays")
            reasons.append(f"mistake retention probe failed at trusted={trusted}: {reason}")
        if mistake_probe and mistake_probe.get("matched_expected") is False:
            trusted = checkpoint.get("trusted_count") or checkpoint.get("trusted_replays")
            reasons.append(f"mistake retention probe did not match expected move at trusted={trusted}")
        sanity_probe = checkpoint.get("sanity_learning_probe") or {}
        if sanity_probe:
            trusted = checkpoint.get("trusted_count") or checkpoint.get("trusted_replays")
            if bool(checkpoint.get("heavy_sanity_skipped")) or str(sanity_probe.get("result_kind") or "") == "skipped_heavy_diagnostics":
                reasons.append(f"heavy sanity diagnostics skipped at trusted={trusted}: broad strength improvement not evaluated (--quick-retrain-skip-heavy-sanity)")
            else:
                final_learning = sanity_probe.get("final_decision_learning") or {}
                if final_learning and final_learning.get("learning_signal") is False:
                    reasons.append(f"sanity final decision learning failed at trusted={trusted}: {final_learning.get('blocked_reason') or sanity_probe.get('learning_signal_reason') or 'final top1 did not match expected_move'}")
                if sanity_probe.get("result_kind") == "failed_to_learn":
                    reasons.append(f"sanity learning probe failed at trusted={trusted}: {sanity_probe.get('learning_signal_reason') or sanity_probe.get('reason')}")
                elif sanity_probe.get("result_kind") == "memorized_exact_fen":
                    reasons.append(f"sanity learning probe only memorized exact FEN at trusted={trusted}")
                elif sanity_probe.get("result_kind") == "partial_seen_variants_only":
                    reasons.append(f"sanity learning probe only proved seen variants at trusted={trusted}")
                elif sanity_probe.get("result_kind") == "partial_policy_learned_but_decision_unchanged":
                    reasons.append(f"sanity raw policy learned but final decision unchanged at trusted={trusted}")
                if sanity_probe.get("exact_fen_pass") is False:
                    reasons.append(f"sanity exact FEN did not pass at trusted={trusted}")
                if float(sanity_probe.get("seen_variant_pass_rate") or 0.0) < SANITY_SEEN_VARIANT_PASS_THRESHOLD:
                    reasons.append(f"sanity seen variant pass rate below threshold at trusted={trusted}")
                unseen_count = int(sanity_probe.get("unseen_variant_count") or 0)
                if unseen_count <= 0:
                    reasons.append(f"sanity unseen variants missing at trusted={trusted}")
                clean_count = int(sanity_probe.get("balanced_clean_held_out_count") or sanity_probe.get("clean_held_out_count") or 0)
                if clean_count <= 0:
                    reasons.append(f"sanity clean held-out labels missing at trusted={trusted}")
                elif float(sanity_probe.get("balanced_clean_held_out_pass_rate") or sanity_probe.get("clean_held_out_final_pass_rate") or 0.0) < SANITY_UNSEEN_VARIANT_PASS_THRESHOLD:
                    reasons.append(f"sanity clean held-out pass rate below threshold at trusted={trusted}")
                hard_clean_count = int(sanity_probe.get("hard_clean_held_out_count") or 0)
                if hard_clean_count <= 0:
                    reasons.append(f"sanity hard clean held-out labels missing at trusted={trusted}")
                elif float(sanity_probe.get("hard_clean_held_out_pass_rate") or 0.0) <= 0.0:
                    reasons.append(f"sanity hard clean held-out pass rate is zero at trusted={trusted}")
                if clean_count <= 0 and float(sanity_probe.get("final_decision_generalization_rate") or 0.0) < SANITY_FINAL_DECISION_GENERALIZATION_THRESHOLD:
                    reasons.append(f"sanity final decision generalization below threshold at trusted={trusted}")
                prior_retention = sanity_probe.get("prior_learned_case_retention") or {}
                if int(prior_retention.get("failed_count") or 0) > 0:
                    reasons.append(f"prior learned sanity case retention regressed at trusted={trusted}")
    fusion = summary.get("fusion_mode_comparison") or {}
    if fusion and not fusion.get("passed", True):
        reasons.extend([f"fusion mode regression: {reason}" for reason in fusion.get("regression_reasons") or []])
    balanced = next((row for row in fusion.get("modes") or [] if row.get("fusion_mode") == "balanced_fusion"), {})
    if balanced and float(balanced.get("final_decision_generalization_rate") or 0.0) < SANITY_FINAL_DECISION_GENERALIZATION_THRESHOLD:
        reasons.append("balanced_fusion final decision generalization below threshold")
    fixture_health = summary.get("replay_fixture_health") or {}
    if fixture_health and not fixture_health.get("passed"):
        reasons.extend([f"replay fixture health failed: {reason}" for reason in fixture_health.get("reasons") or []])
    distilled = summary.get("distilled_replay_preprocessing") or {}
    if distilled and bool(distilled.get("leakage_detected")):
        reasons.append("distilled_replay_heldout_leakage")
    if distilled and bool(distilled.get("held_out_in_training")):
        reasons.append("distilled replay reported held_out_in_training=true")
    exp30a = summary.get("exp30a_pipeline") or {}
    if exp30a and bool(exp30a.get("full_gate_skipped")):
        reasons.append(f"full deterministic gate skipped after smoke gate: {exp30a.get('full_gate_skip_reason') or 'smoke_gate_failed'}")
    exp30b = summary.get("exp30b_pipeline") or {}
    if exp30b and bool(exp30b.get("interference")):
        reasons.extend([f"semantic interference: {reason}" for reason in exp30b.get("interference_reasons") or []])
    exp31 = summary.get("exp31_pipeline") or {}
    if exp31 and bool(exp31.get("semantic_interference")):
        reasons.extend([f"exp31 semantic scheduler: {reason}" for reason in exp31.get("interference_reasons") or []])
    if exp31 and bool(exp31.get("semantic_loss_budget_skew")):
        reasons.append("exp31 semantic loss budget skew")
    if exp31 and bool(exp31.get("catastrophic_semantic_interference")):
        reasons.append("exp31 catastrophic semantic interference")
    exp32 = summary.get("exp32_pipeline") or {}
    if exp32 and bool(exp32.get("repair_applied")) and not bool(exp32.get("repair_success")):
        reasons.append("exp32 mistake retention repair did not restore expected move")
    exp33 = summary.get("exp33_pipeline") or {}
    safe_selection = exp33.get("safe_checkpoint_selection") or {}
    if exp33 and safe_selection.get("selected_safe_checkpoint") == "none":
        reasons.append("exp33 no safe checkpoint passed mistake retention")
    if exp33 and safe_selection.get("selected_safe_checkpoint") == "cp10_fallback":
        reasons.append("exp33 selected cp10 fallback because cp20 failed retention")
    exp34 = summary.get("exp34_pipeline") or {}
    exp34_retention_audit = exp34.get("retention_case_version_audit") or {}
    if exp34 and bool(exp34_retention_audit.get("retention_label_version_conflict")):
        reasons.append("exp34 retention label version conflict")
    if exp34 and bool(exp34.get("cp20_rejected_by_retention")):
        reasons.append("exp34 rejected cp20 because mistake retention failed")
    if exp34 and not bool(exp34.get("smoke_level_1_passed", True)):
        reasons.append("exp34 smoke level 1 foundation gate failed")
    if exp34 and not bool(exp34.get("smoke_level_2_passed", True)):
        reasons.append("exp34 smoke level 2 hard generalization gate failed")
    if exp34 and bool(exp34.get("questionable_hard_flank_label")):
        reasons.append("exp34 hard flank label requires quarantine/audit before promotion")
    if exp34 and bool(exp34.get("hard_flank_capability_gap")):
        reasons.append("exp34 hard flank capability gap remains unresolved")
    if str(summary.get("engine_verdict") or "") not in {"", "PASS"}:
        reasons.append(f"engine verdict {summary.get('engine_verdict')}")
    return {
        "passed": not reasons,
        "reasons": reasons,
        "thresholds": {
            "dataset_duplicate_ratio_limit": DATASET_DUPLICATE_RATIO_LIMIT,
            "dataset_short_resign_limit": DATASET_SHORT_RESIGN_LIMIT,
            "poison_repetition_limit": POISON_REPETITION_LIMIT,
            "poison_intentional_blunder_limit": POISON_INTENTIONAL_BLUNDER_LIMIT,
            "poison_engine_copy_limit": POISON_ENGINE_COPY_LIMIT,
            "poison_suspicious_resign_rate_limit": POISON_SUSPICIOUS_RESIGN_RATE_LIMIT,
        },
    }


def _checkpoint_gate_summary(
    *,
    dataset_result: dict,
    benchmark_before_focus: dict,
    benchmark_after_focus: dict,
    legal_rate_delta,
    ineffective_training: bool,
    mistake_retention_probe: dict | None = None,
) -> dict:
    reasons = []
    if int(dataset_result.get("contaminated_rows") or 0) > 0:
        reasons.append("contaminated rows entered checkpoint dataset")
    if ineffective_training:
        reasons.append("model hash changed without probe move changes")
    if legal_rate_delta is not None and legal_rate_delta < -0.05:
        reasons.append("legal move rate regressed beyond threshold")
    if (mistake_retention_probe or {}).get("learning_signal") is False:
        reason = str((mistake_retention_probe or {}).get("learning_signal_reason") or (mistake_retention_probe or {}).get("reason") or "no mistake-retention learning signal")
        reasons.append(f"mistake retention probe failed: {reason}")
    if mistake_retention_probe and mistake_retention_probe.get("matched_expected") is False:
        reasons.append("mistake retention probe did not match expected move")
    return {"passed": not reasons, "reasons": reasons}


def _runtime_metrics_summary(summary: dict) -> dict:
    dataset = summary.get("dataset_result") or {}
    train_path = Path(str(dataset.get("train_dataset_path") or ""))
    rejected_path = Path(str(dataset.get("rejected_dataset_path") or ""))
    dataset_bytes = 0
    for path in (train_path, rejected_path):
        try:
            if path.exists():
                dataset_bytes += path.stat().st_size
        except Exception:
            continue
    retrain_timing = summary.get("retrain_timing") or {}
    eval_before = summary.get("evaluation_before") or {}
    eval_after = summary.get("evaluation_after") or {}
    return {
        "train_seconds": retrain_timing.get("total_retrain_seconds", 0.0),
        "eval_seconds": round((float(eval_before.get("total_think_ms") or 0.0) + float(eval_after.get("total_think_ms") or 0.0)) / 1000.0, 3),
        "peak_memory_mb": None,
        "checkpoint_count": retrain_timing.get("checkpoint_count", 0),
        "dataset_bytes": dataset_bytes,
    }


def _git_dirty() -> bool:
    try:
        proc = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"], text=True, capture_output=True, check=True)
        return bool(str(proc.stdout or "").strip())
    except Exception:
        return True


def _reproducibility_summary(summary: dict) -> dict:
    dataset = summary.get("dataset_result") or {}
    trainer_paths = [
        ROOT / "scripts" / "games" / "chess_replay_prepare.py",
        ROOT / "scripts" / "games" / "chess_train_pipeline.py",
        ROOT / "scripts" / "games" / "chess_exp3_dataset_train.py",
        ROOT / "scripts" / "games" / "chess_exp4_dataset_train.py",
        ROOT / "scripts" / "games" / "chess_exp5_dataset_train.py",
    ]
    trainer_hash_payload = "".join(_sha256_file(path) for path in trainer_paths)
    trainer_hash = hashlib.sha256(trainer_hash_payload.encode("utf-8")).hexdigest() if trainer_hash_payload else ""
    env = summary.get("environment") or {}
    return {
        "python_version": env.get("python_version", ""),
        "torch_version": env.get("torch_version", ""),
        "cuda": env.get("gpu", ""),
        "deterministic_mode": True,
        "git_dirty": _git_dirty(),
        "dataset_hash": f"sha256:{dataset.get('dataset_sha256', '')}",
        "trainer_hash": f"sha256:{trainer_hash}" if trainer_hash else "",
    }


def _failure_explanations(summary: dict) -> list[str]:
    reasons = []
    gate = summary.get("promotion_gate") or {}
    for reason in gate.get("reasons") or []:
        reasons.append(str(reason))
    integrity = summary.get("dataset_integrity") or {}
    if float(integrity.get("duplicate_ratio") or 0.0) > 0.25:
        reasons.append(f"{round(float(integrity.get('duplicate_ratio') or 0.0) * 100, 1)}% replay samples were duplicate positions")
    if int(integrity.get("illegal_moves") or 0) > 0:
        reasons.append(f"{integrity.get('illegal_moves')} illegal moves detected in prepared dataset")
    poison = summary.get("poison_detection") or {}
    if float(poison.get("suspicious_resign_rate") or 0.0) > 0.10:
        reasons.append(f"suspicious resign rate {round(float(poison.get('suspicious_resign_rate') or 0.0) * 100, 1)}%")
    stability = summary.get("stability") or {}
    if stability.get("catastrophic_regression"):
        reasons.append("catastrophic regression detected")
    if not reasons and summary.get("engine_verdict") == "PASS":
        return ["No blocking failure detected."]
    return sorted(set(reasons))


def _promotion_explanation(summary: dict) -> str:
    gate = summary.get("promotion_gate") or {}
    if gate.get("passed"):
        return "Yes. Promotion gate passed and no blocking dataset, poison, benchmark, or regression reason was found."
    reasons = [str(reason) for reason in gate.get("reasons") or []]
    if not reasons:
        return "No. Promotion gate did not pass, but no explicit reason was recorded."
    return "No. " + "; ".join(reasons) + "."


def _root_engine_row(summary: dict) -> dict:
    return {
        "engine_alias": summary["engine_alias"],
        "difficulty": summary["difficulty"],
        "validation_mode": summary.get("validation_mode") or "full_30_game_expensive_validation",
        "timing_breakdown": summary.get("timing_breakdown") or {},
        "quick_retrain_gate": summary.get("quick_retrain_gate") or {},
        "engine_verdict": summary.get("engine_verdict"),
        "replay_learning_supported": bool(summary.get("retrain_result", {}).get("retrain_supported")),
        "effective_samples": int(summary.get("dataset_result", {}).get("accepted_rows") or 0),
        "rejected_samples": int(summary.get("dataset_result", {}).get("rejected_rows") or 0),
        "trusted_replays": summary["replay_summary"]["trusted_replays"],
        "quarantine_replays": summary["replay_summary"]["quarantine_replays"],
        "autorun_status": summary["autorun_status"].get("status", ""),
        "agreement_before": summary["evaluation_before"].get("agreement"),
        "agreement_after": summary["evaluation_after"].get("agreement"),
        "avg_think_ms_before": summary["evaluation_before"].get("avg_think_ms"),
        "avg_think_ms_after": summary["evaluation_after"].get("avg_think_ms"),
        "avg_game_think_ms_per_step": (summary.get("game_timing") or {}).get("avg_think_ms_per_step"),
        "think_steps_measured": (summary.get("game_timing") or {}).get("steps_measured"),
        "total_retrain_seconds": (summary.get("retrain_timing") or {}).get("total_retrain_seconds"),
        "avg_retrain_seconds": (summary.get("retrain_timing") or {}).get("avg_retrain_seconds"),
        "total_checkpoint_seconds": (summary.get("retrain_timing") or {}).get("total_checkpoint_seconds"),
        "promotion_gate_passed": (summary.get("promotion_gate") or {}).get("passed"),
        "promotion_gate_reasons": (summary.get("promotion_gate") or {}).get("reasons") or [],
        "catastrophic_regression": (summary.get("stability") or {}).get("catastrophic_regression"),
        "can_be_promoted": _promotion_explanation(summary),
        "dataset_duplicate_ratio": (summary.get("dataset_integrity") or {}).get("duplicate_ratio"),
        "dataset_illegal_moves": (summary.get("dataset_integrity") or {}).get("illegal_moves"),
        "suspicious_resign_rate": (summary.get("poison_detection") or {}).get("suspicious_resign_rate"),
        "win_rate_before": (summary.get("before_after_eval", {}).get("benchmark_before") or {}).get("win_rate"),
        "win_rate_after": (summary.get("before_after_eval", {}).get("benchmark_after") or {}).get("win_rate"),
        "legal_rate_before": (summary.get("before_after_eval", {}).get("benchmark_before") or {}).get("legal_rate"),
        "legal_rate_after": (summary.get("before_after_eval", {}).get("benchmark_after") or {}).get("legal_rate"),
        "low_quality_rate_before": (summary.get("before_after_eval", {}).get("benchmark_before") or {}).get("low_quality_rate"),
        "low_quality_rate_after": (summary.get("before_after_eval", {}).get("benchmark_after") or {}).get("low_quality_rate"),
        "stage_game_win_rates": summary.get("stage_game_win_rates") or [],
        "benchmark_timeline": (summary.get("before_after_eval") or {}).get("benchmark_timeline") or [],
        "deterministic_strength_snapshot": summary.get("deterministic_strength_snapshot") or {},
        "policy_override_audit": summary.get("policy_override_audit") or {},
        "opening_target_margin_audit": summary.get("opening_target_margin_audit") or {},
        "fusion_mode_comparison": summary.get("fusion_mode_comparison") or {},
        "style_profile_audit": summary.get("style_profile_audit") or {},
        "stochastic_auxiliary_benchmark": summary.get("stochastic_auxiliary_benchmark") or {},
        "perft": summary.get("perft") or {},
        "retrain_stability_report": summary.get("retrain_stability_report") or {},
        "checkpoint_consistency": summary.get("checkpoint_consistency") or {},
        "replay_fixture_health": summary.get("replay_fixture_health") or {},
        "distilled_replay_preprocessing": summary.get("distilled_replay_preprocessing") or {},
        "exp30a_pipeline": summary.get("exp30a_pipeline") or {},
        "exp30b_pipeline": summary.get("exp30b_pipeline") or {},
        "exp31_pipeline": summary.get("exp31_pipeline") or {},
        "exp32_pipeline": summary.get("exp32_pipeline") or {},
        "exp33_pipeline": summary.get("exp33_pipeline") or {},
        "exp34_pipeline": summary.get("exp34_pipeline") or {},
        "flank_context_feature_injection": summary.get("flank_context_feature_injection") or {},
        "sanity_learning_probe_results": [
            {
                "trusted_count": checkpoint.get("trusted_count") or checkpoint.get("trusted_replays"),
                "learning_signal": (checkpoint.get("sanity_learning_probe") or {}).get("learning_signal"),
                "result_kind": (checkpoint.get("sanity_learning_probe") or {}).get("result_kind"),
                "expected_move": ((checkpoint.get("sanity_learning_probe") or {}).get("case") or {}).get("expected_move"),
                "before_top1": ((checkpoint.get("sanity_learning_probe") or {}).get("before_exact") or {}).get("top1"),
                "before_top3": ((checkpoint.get("sanity_learning_probe") or {}).get("before_exact") or {}).get("top3"),
                "before_expected_in_top3": ((checkpoint.get("sanity_learning_probe") or {}).get("before_exact") or {}).get("expected_in_top3"),
                "after_top1": ((checkpoint.get("sanity_learning_probe") or {}).get("after_exact") or {}).get("top1"),
                "after_top3": ((checkpoint.get("sanity_learning_probe") or {}).get("after_exact") or {}).get("top3"),
                "after_expected_is_top1": ((checkpoint.get("sanity_learning_probe") or {}).get("after_exact") or {}).get("expected_is_top1"),
                "variant_count": (checkpoint.get("sanity_learning_probe") or {}).get("variant_count"),
                "variant_top1_hits": (checkpoint.get("sanity_learning_probe") or {}).get("variant_top1_hits"),
                "variant_top1_rate": (checkpoint.get("sanity_learning_probe") or {}).get("variant_top1_rate"),
                "exact_fen_pass": (checkpoint.get("sanity_learning_probe") or {}).get("exact_fen_pass"),
                "seen_variant_pass_rate": (checkpoint.get("sanity_learning_probe") or {}).get("seen_variant_pass_rate"),
                "unseen_variant_pass_rate": (checkpoint.get("sanity_learning_probe") or {}).get("unseen_variant_pass_rate"),
                "easy_unseen_pass_rate": (checkpoint.get("sanity_learning_probe") or {}).get("easy_unseen_pass_rate"),
                "medium_unseen_pass_rate": (checkpoint.get("sanity_learning_probe") or {}).get("medium_unseen_pass_rate"),
                "hard_unseen_pass_rate": (checkpoint.get("sanity_learning_probe") or {}).get("hard_unseen_pass_rate"),
                "variant_difficulty_scores": (checkpoint.get("sanity_learning_probe") or {}).get("variant_difficulty_scores") or {},
                "raw_policy_generalization_rate": (checkpoint.get("sanity_learning_probe") or {}).get("raw_policy_generalization_rate"),
                "final_decision_generalization_rate": (checkpoint.get("sanity_learning_probe") or {}).get("final_decision_generalization_rate"),
                "raw_policy_unseen_generalization_rate": (checkpoint.get("sanity_learning_probe") or {}).get("raw_policy_unseen_generalization_rate"),
                "final_decision_unseen_generalization_rate": (checkpoint.get("sanity_learning_probe") or {}).get("final_decision_unseen_generalization_rate"),
                "raw_policy_learning": (checkpoint.get("sanity_learning_probe") or {}).get("raw_policy_learning") or {},
                "final_decision_learning": (checkpoint.get("sanity_learning_probe") or {}).get("final_decision_learning") or {},
                "prior_learned_case_retention": (checkpoint.get("sanity_learning_probe") or {}).get("prior_learned_case_retention") or {},
                "blocked_by_search_or_static_eval": (checkpoint.get("sanity_learning_probe") or {}).get("blocked_by_search_or_static_eval"),
                "learning_signal_reason": (checkpoint.get("sanity_learning_probe") or {}).get("learning_signal_reason"),
            }
            for checkpoint in (summary.get("before_after_eval", {}).get("checkpoints") or [])
        ],
        "mistake_retention_probe_results": [
            {
                "trusted_count": checkpoint.get("trusted_count") or checkpoint.get("trusted_replays"),
                "learning_signal": (checkpoint.get("mistake_retention_probe") or {}).get("learning_signal"),
                "probe_case_id": (checkpoint.get("mistake_retention_probe") or {}).get("probe_case_id"),
                "before_move": (checkpoint.get("mistake_retention_probe") or {}).get("before_move"),
                "after_move": (checkpoint.get("mistake_retention_probe") or {}).get("after_move"),
                "expected_move": (checkpoint.get("mistake_retention_probe") or {}).get("expected_move"),
                "avoided_same_error": (checkpoint.get("mistake_retention_probe") or {}).get("avoided_same_error"),
                "avoided_old_mistake": (checkpoint.get("mistake_retention_probe") or {}).get("avoided_old_mistake"),
                "matched_expected": (checkpoint.get("mistake_retention_probe") or {}).get("matched_expected"),
                "result_kind": (checkpoint.get("mistake_retention_probe") or {}).get("result_kind"),
                "learning_signal_reason": (checkpoint.get("mistake_retention_probe") or {}).get("learning_signal_reason"),
            }
            for checkpoint in (summary.get("before_after_eval", {}).get("checkpoints") or [])
        ],
        "checkpoint_hashes": [
            {
                "trusted_count": checkpoint.get("trusted_count") or checkpoint.get("trusted_replays"),
                "previous_model_hash": checkpoint.get("previous_model_hash") or checkpoint.get("pre_checkpoint_model_sha256"),
                "new_model_hash": checkpoint.get("new_model_hash") or checkpoint.get("post_checkpoint_model_sha256"),
                "hash_changed": checkpoint.get("hash_changed") if "hash_changed" in checkpoint else checkpoint.get("model_hash_changed"),
            }
            for checkpoint in (summary.get("before_after_eval", {}).get("checkpoints") or [])
        ],
        "checkpoint_count": len(summary.get("before_after_eval", {}).get("checkpoints") or []),
        "invalid_train_entries": sum(1 for row in (summary.get("invalid_case_audit") or []) if row.get("entered_train_dataset")),
        "learning_changed": (
            summary.get("evaluation_after", {}).get("agreement") != summary.get("evaluation_before", {}).get("agreement")
            or summary.get("model_after", {}).get("sha256") != summary.get("model_before", {}).get("sha256")
        ),
        "benchmark_skipped": _summary_benchmark_skipped(summary),
        "benchmark_changed": _summary_benchmark_changed(summary),
        "meets_expectation": (
            summary["replay_summary"]["trusted_replays"] == int(summary.get("expected_trusted_replays") or VALID_GAMES)
            and summary["replay_summary"]["quarantine_replays"] == int(summary.get("expected_quarantine_replays") if summary.get("expected_quarantine_replays") is not None else INVALID_GAMES)
            and (
                not summary.get("retrain_result", {}).get("retrain_supported")
                or (
                    (
                        bool((summary.get("quick_retrain_gate") or {}).get("enabled"))
                        or (
                            (summary.get("retrain_result", {}).get("trainer_probe", {}).get("validation", {}) or {}).get("accepted_samples_gt_zero")
                            and (summary.get("retrain_result", {}).get("trainer_probe", {}).get("validation", {}) or {}).get("rejected_samples_match")
                        )
                    )
                    and (
                        summary.get("evaluation_after", {}).get("agreement")
                        != summary.get("evaluation_before", {}).get("agreement")
                        or summary.get("model_after", {}).get("sha256")
                        != summary.get("model_before", {}).get("sha256")
                    )
                    and (
                        len(summary.get("before_after_eval", {}).get("checkpoints") or []) >= (
                            len(QUICK_RETRAIN_GATE_CHECKPOINTS)
                            if bool((summary.get("quick_retrain_gate") or {}).get("enabled"))
                            else max(1, VALID_GAMES // max(1, int(summary.get("autorun_threshold") or 1)))
                        )
                    )
                    and _summary_benchmark_expectation_met(summary)
                )
            )
        ),
        "suitable_for_production_self_learning": bool(summary.get("suitable_for_production_self_learning")),
    }


def _format_stage_win_rates(stage_rates: list[dict]) -> str:
    if not stage_rates:
        return "none"
    parts = []
    for row in stage_rates:
        delta = row.get("win_rate_delta_from_previous_stage")
        delta_text = "n/a" if delta is None else str(delta)
        parts.append(
            f"{row.get('stage')}={row.get('win_rate')} "
            f"normal={row.get('normal_games')} "
            f"delta={delta_text}"
        )
    return "; ".join(parts)


def _benchmark_timeline(checkpoints: list[dict], *, baseline_model_hash: str, final_model_hash: str) -> list[dict]:
    if not checkpoints:
        return []
    rows = []
    first_before = checkpoints[0].get("benchmark_before") or {}
    rows.append(
        {
            "label": "baseline_model",
            "trusted_count": 0,
            "model_hash": baseline_model_hash,
            "benchmark": first_before,
            "benchmark_skipped": bool(first_before.get("skipped")),
            "benchmark_skip_reason": str(first_before.get("reason") or ""),
        }
    )
    for checkpoint in checkpoints:
        benchmark = checkpoint.get("benchmark_after") or {}
        trusted_count = int(checkpoint.get("trusted_count") or checkpoint.get("trusted_replays") or 0)
        rows.append(
            {
                "label": f"checkpoint_after_trusted_{trusted_count}",
                "trusted_count": trusted_count,
                "model_hash": str(checkpoint.get("new_model_hash") or checkpoint.get("post_checkpoint_model_sha256") or ""),
                "benchmark": benchmark,
                "benchmark_skipped": bool(benchmark.get("skipped")),
                "benchmark_skip_reason": str(benchmark.get("reason") or ""),
            }
        )
    last_benchmark = checkpoints[-1].get("benchmark_after") or {}
    rows.append(
        {
            "label": "final_model",
            "trusted_count": int(checkpoints[-1].get("trusted_count") or checkpoints[-1].get("trusted_replays") or 0),
            "model_hash": final_model_hash,
            "benchmark": last_benchmark,
            "benchmark_skipped": bool(last_benchmark.get("skipped")),
            "benchmark_skip_reason": str(last_benchmark.get("reason") or ""),
        }
    )
    return rows


def _build_root_summary(
    *,
    output_root: Path,
    summaries: list[dict],
    skip_autorun_benchmark: bool,
    skip_autorun_promote: bool,
    skip_retrain_benchmark_snapshots: bool,
    benchmark_rounds: int = 1,
    benchmark_max_plies: int = 90,
    benchmark_teacher_depth: int = 2,
) -> dict:
    root_summary = {
        "ok": True,
        "generated_at": _utc_now(),
        "output_root": str(output_root),
        "fast_retrain": bool(skip_autorun_benchmark or skip_autorun_promote),
        "skip_autorun_benchmark": bool(skip_autorun_benchmark),
        "skip_autorun_promote": bool(skip_autorun_promote),
        "skip_retrain_benchmark_snapshots": bool(skip_retrain_benchmark_snapshots),
        "benchmark_config": {
            "rounds": int(benchmark_rounds),
            "max_plies": int(benchmark_max_plies),
            "teacher_depth": int(benchmark_teacher_depth),
        },
        "timing": {
            "total_retrain_seconds": round(sum(float((summary.get("retrain_timing") or {}).get("total_retrain_seconds") or 0.0) for summary in summaries), 3),
            "total_checkpoint_seconds": round(sum(float((summary.get("retrain_timing") or {}).get("total_checkpoint_seconds") or 0.0) for summary in summaries), 3),
            "avg_game_think_ms_per_step": round(
                sum(float((summary.get("game_timing") or {}).get("total_think_ms") or 0.0) for summary in summaries)
                / max(1, sum(int((summary.get("game_timing") or {}).get("steps_measured") or 0) for summary in summaries)),
                3,
            ),
            "think_steps_measured": sum(int((summary.get("game_timing") or {}).get("steps_measured") or 0) for summary in summaries),
        },
        "environment": _environment_summary(),
        "engines": [_root_engine_row(summary) for summary in summaries],
    }
    engine_verdicts = [str(row.get("engine_verdict") or "") for row in root_summary["engines"]]
    if any(verdict == "FAIL" for verdict in engine_verdicts):
        overall_verdict = "FAIL"
    elif any(bool(row.get("catastrophic_regression")) for row in root_summary["engines"]):
        overall_verdict = "HIGH_RISK"
    elif any(verdict in {"PARTIAL", "HIGH_RISK", "PARTIAL_POLICY_LEARNED_BUT_DECISION_UNCHANGED", "PARTIAL_SEEN_VARIANTS_ONLY"} for verdict in engine_verdicts) or any(not bool(row.get("promotion_gate_passed")) for row in root_summary["engines"]):
        overall_verdict = "PARTIAL"
    else:
        overall_verdict = "PASS"
    root_summary["overall_verdict"] = overall_verdict
    return root_summary


def _root_report_lines(root_summary: dict, summaries: list[dict]) -> list[str]:
    lines = [
        "# Chess Live Learning Validation",
        "",
        f"- generated_at: `{root_summary['generated_at']}`",
        f"- output_root: `{root_summary['output_root']}`",
        f"- overall_verdict: `{root_summary['overall_verdict']}`",
        f"- total_retrain_seconds: `{root_summary['timing']['total_retrain_seconds']}`",
        f"- avg_game_think_ms_per_step: `{root_summary['timing']['avg_game_think_ms_per_step']}`",
        f"- think_steps_measured: `{root_summary['timing']['think_steps_measured']}`",
        "",
        "## Engines",
        "",
    ]
    for row in root_summary["engines"]:
        lines.append(
            f"- {row['engine_alias']} `{row['difficulty']}` "
            f"mode=`{row.get('validation_mode')}` "
            f"verdict=`{row['engine_verdict']}` "
            f"support=`{row['replay_learning_supported']}` "
            f"checkpoints=`{row['checkpoint_count']}` "
            f"accepted=`{row['effective_samples']}` rejected=`{row['rejected_samples']}` "
            f"win `{row['win_rate_before']}` -> `{row['win_rate_after']}` "
            f"legal `{row['legal_rate_before']}` -> `{row['legal_rate_after']}` "
            f"think_ms `{row['avg_think_ms_before']}` -> `{row['avg_think_ms_after']}` "
            f"game_step_think_ms=`{row['avg_game_think_ms_per_step']}` "
            f"retrain_s=`{row['total_retrain_seconds']}` "
            f"low_quality `{row['low_quality_rate_before']}` -> `{row['low_quality_rate_after']}` "
            f"learning_changed=`{row['learning_changed']}` "
            f"benchmark_skipped=`{row['benchmark_skipped']}` "
            f"benchmark_changed=`{row['benchmark_changed']}` "
            f"promotion_gate=`{row['promotion_gate_passed']}` "
            f"catastrophic=`{row['catastrophic_regression']}` "
            f"meets_expectation=`{row['meets_expectation']}`"
        )
        timing = row.get("timing_breakdown") or {}
        if timing:
            lines.append(
                f"- {row['engine_alias']} timing: replay_generation_s=`{timing.get('replay_generation_seconds')}` "
                f"retrain_s=`{timing.get('retrain_seconds')}` deterministic_eval_s=`{timing.get('deterministic_eval_seconds')}` "
                f"report_write_s=`{timing.get('report_write_seconds')}` total_wall_s=`{timing.get('total_wall_seconds')}`"
            )
        quick = row.get("quick_retrain_gate") or {}
        if quick.get("enabled"):
            lines.append(
                f"- {row['engine_alias']} quick_gate: fixture_trusted_replays=`{quick.get('fixture_trusted_replays')}` "
                f"full_30_game_generation_skipped=`{quick.get('full_30_game_generation_skipped')}` "
                f"stochastic_auxiliary_only=`{quick.get('stochastic_auxiliary_only')}`"
            )
    lines.extend(
        [
            "",
            "## Stage Game Win Rates",
            "",
            "- basis: `trusted_valid_games_only`; invalid_games_excluded=`True`",
        ]
    )
    for row in root_summary["engines"]:
        lines.append(f"- {row['engine_alias']}: {_format_stage_win_rates(row.get('stage_game_win_rates') or [])}")
    lines.extend(["", "## Replay Fixture Health", ""])
    for row in root_summary["engines"]:
        health = row.get("replay_fixture_health") or {}
        if not health:
            lines.append(f"- {row['engine_alias']}: no replay fixture health recorded")
            continue
        lines.append(
            f"- {row['engine_alias']}: passed=`{health.get('passed')}` duplicate_ratio=`{health.get('duplicate_ratio')}` "
            f"unique_fen=`{health.get('unique_fen_count')}` unique_target_moves=`{health.get('unique_target_move_count')}` "
            f"poison_quarantine=`{health.get('poison_quarantine_count')}` fixture_hash=`{health.get('fixture_hash')}`"
        )
        lines.append(f"- {row['engine_alias']} category_distribution: `{health.get('category_distribution')}`")
    lines.extend(["", "## Retrain Stability Report", ""])
    for row in root_summary["engines"]:
        stability = row.get("retrain_stability_report") or {}
        late_stage = stability.get("late_stage") or {}
        scores = stability.get("deterministic_scores") or {}
        retention = stability.get("mistake_retention") or {}
        lines.append(
            f"- {row['engine_alias']}: suspected_catastrophic=`{stability.get('suspected_catastrophic_regression')}` "
            f"late_stage=`{late_stage.get('stage')}` late_win_rate=`{late_stage.get('win_rate')}` "
            f"det_final=`{scores.get('final')}` det_checkpoint10=`{scores.get('checkpoint@10')}` "
            f"mistake_retention_final=`{retention.get('final_score')}`"
        )
        for reason in stability.get("reasons") or []:
            lines.append(f"- {row['engine_alias']} stability_reason: `{reason}`")
    lines.extend(["", "## Checkpoint Consistency", ""])
    for row in root_summary["engines"]:
        consistency = row.get("checkpoint_consistency") or {}
        lines.append(
            f"- {row['engine_alias']}: passed=`{consistency.get('passed')}` "
            f"instability=`{consistency.get('instability')}`"
        )
        for item in consistency.get("checkpoint_consistency_table") or []:
            lines.append(
                f"- {row['engine_alias']} trusted={item.get('trusted_count')}: "
                f"exact=`{item.get('exact_retention')}` seen=`{item.get('seen_retention')}` "
                f"unseen=`{item.get('unseen_retention')}` raw_unseen=`{item.get('raw_unseen_retention')}` "
                f"hard_held_out=`{item.get('hard_held_out_retention')}` "
                f"clean_held_out=`{item.get('clean_held_out_retention')}` "
                f"hard_clean_held_out=`{item.get('hard_clean_held_out_retention')}` "
                f"clean_pool_sufficient=`{item.get('clean_held_out_pool_sufficient')}` "
                f"embedding_after=`{item.get('embedding_similarity_after')}` "
                f"margin=`{item.get('hard_negative_min_margin')}` "
                f"semantic_margin=`{item.get('semantic_hard_negative_min_margin')}` "
                f"central_to_kingside=`{(item.get('semantic_confusion_gate') or {}).get('central_to_kingside_rate')}` "
                f"targeted_centroid_min=`{(item.get('targeted_centroid_distances_after') or {}).get('min_distance')}` "
                f"passed=`{item.get('passed')}`"
            )
            for split, distribution in (item.get("semantic_class_distribution") or {}).items():
                lines.append(
                    f"- {row['engine_alias']} trusted={item.get('trusted_count')} semantic_distribution split=`{split}` "
                    f"balanced=`{distribution.get('balanced')}` missing=`{distribution.get('missing_classes')}` "
                    f"kingside_to_central=`{distribution.get('kingside_to_central_ratio')}` "
                    f"counts=`{distribution.get('candidate_counts')}`"
                )
            quality_summary = item.get("label_quality_summary") or {}
            if quality_summary:
                lines.append(
                    f"- {row['engine_alias']} trusted={item.get('trusted_count')} label_quality: "
                    f"clean=`{quality_summary.get('clean')}` questionable=`{quality_summary.get('questionable')}` "
                    f"invalid=`{quality_summary.get('invalid')}` hard_excluded=`{quality_summary.get('hard_excluded')}`"
                )
        for reason in consistency.get("instability_reasons") or []:
            lines.append(f"- {row['engine_alias']} instability_reason: `{reason}`")
    lines.extend(["", "## Deterministic Strength Gate", ""])
    for row in root_summary["engines"]:
        det = row.get("deterministic_strength_snapshot") or {}
        final_det = det.get("final") or {}
        lines.append(
            f"- {row['engine_alias']}: passed=`{det.get('passed')}` "
            f"overall=`{final_det.get('overall_deterministic_score')}` "
            f"top1=`{final_det.get('top1_correct_rate')}` top3=`{final_det.get('top3_contains_rate')}` "
            f"illegal_rate=`{final_det.get('illegal_rate')}` blunder_avoid_rate=`{final_det.get('blunder_avoid_rate')}` "
            f"regression_vs_baseline=`{det.get('regression_vs_baseline')}` "
            f"regression_vs_checkpoint20=`{det.get('regression_vs_checkpoint20')}`"
        )
        for item in det.get("score_table") or []:
            lines.append(
                f"- {row['engine_alias']} {item.get('model_label')}: "
                f"score=`{item.get('overall_deterministic_score')}` top1=`{item.get('top1_correct_rate')}` "
                f"top3=`{item.get('top3_contains_rate')}` illegal=`{item.get('illegal_rate')}` "
                f"blunder_avoid=`{item.get('blunder_avoid_rate')}`"
            )
    lines.extend(["", "## Stochastic Auxiliary Game Benchmark", ""])
    for row in root_summary["engines"]:
        aux = row.get("stochastic_auxiliary_benchmark") or {}
        lines.append(
            f"- {row['engine_alias']}: skipped=`{aux.get('skipped')}` reason=`{aux.get('skip_reason')}` "
            f"strength_evidence=`{aux.get('strength_evidence')}` note=`{aux.get('purpose')}`"
        )
    lines.extend(["", "## Perft And Runtime Separation", ""])
    for row in root_summary["engines"]:
        perft = row.get("perft") or {}
        lines.append(f"- {row['engine_alias']}: perft_strength_evidence=`{perft.get('strength_evidence')}` reason=`{perft.get('reason')}`")
    lines.extend(["", "## Formal Benchmark Timeline", ""])
    for row in root_summary["engines"]:
        timeline = row.get("benchmark_timeline") or []
        if not timeline:
            lines.append(f"- {row['engine_alias']}: no formal benchmark timeline recorded")
            continue
        for item in timeline:
            benchmark = item.get("benchmark") or {}
            lines.append(
                f"- {row['engine_alias']} {item.get('label')}: trusted=`{item.get('trusted_count')}` "
                f"win_rate=`{benchmark.get('win_rate')}` legal_rate=`{benchmark.get('legal_rate')}` "
                f"skipped=`{item.get('benchmark_skipped')}` reason=`{item.get('benchmark_skip_reason')}`"
            )
    lines.extend(["", "## Mistake Retention Probe", ""])
    for row in root_summary["engines"]:
        probes = row.get("mistake_retention_probe_results") or []
        if not probes:
            lines.append(f"- {row['engine_alias']}: no mistake-retention probe result recorded")
            continue
        for probe in probes:
            lines.append(
                f"- {row['engine_alias']} trusted=`{probe.get('trusted_count')}` "
                f"case=`{probe.get('probe_case_id')}` before=`{probe.get('before_move')}` "
                f"after=`{probe.get('after_move')}` expected=`{probe.get('expected_move')}` "
                f"avoided_old_mistake=`{probe.get('avoided_old_mistake')}` matched_expected=`{probe.get('matched_expected')}` "
                f"result_kind=`{probe.get('result_kind')}` avoided_same_error=`{probe.get('avoided_same_error')}` "
                f"learning_signal=`{probe.get('learning_signal')}` reason=`{probe.get('learning_signal_reason')}`"
            )
    lines.extend(["", "## Sanity Learning Probe", ""])
    for row in root_summary["engines"]:
        probes = row.get("sanity_learning_probe_results") or []
        if not probes:
            lines.append(f"- {row['engine_alias']}: no sanity learning probe result recorded")
            continue
        for probe in probes:
            raw = probe.get("raw_policy_learning") or {}
            final = probe.get("final_decision_learning") or {}
            lines.append(
                f"- {row['engine_alias']} trusted=`{probe.get('trusted_count')}` "
                f"result=`{probe.get('result_kind')}` expected=`{probe.get('expected_move')}` "
                f"before_top1=`{probe.get('before_top1')}` before_top3=`{probe.get('before_top3')}` "
                f"before_expected_in_top3=`{probe.get('before_expected_in_top3')}` "
                f"after_top1=`{probe.get('after_top1')}` after_top3=`{probe.get('after_top3')}` "
                f"after_expected_is_top1=`{probe.get('after_expected_is_top1')}` "
                f"raw_policy_learning=`{raw.get('learning_signal')}` raw_top1 `{raw.get('raw_policy_top1_before')}` -> `{raw.get('raw_policy_top1_after')}` "
                f"expected_rank `{raw.get('expected_rank_before')}` -> `{raw.get('expected_rank_after')}` "
                f"expected_margin_after=`{raw.get('expected_margin_after')}` "
                f"final_decision_learning=`{final.get('learning_signal')}` blocked_by_search_or_static_eval=`{probe.get('blocked_by_search_or_static_eval')}` "
                f"exact_fen_pass=`{probe.get('exact_fen_pass')}` "
                f"seen_variant_pass_rate=`{probe.get('seen_variant_pass_rate')}` "
                f"unseen_variant_pass_rate=`{probe.get('unseen_variant_pass_rate')}` "
                f"easy_unseen=`{probe.get('easy_unseen_pass_rate')}` "
                f"medium_unseen=`{probe.get('medium_unseen_pass_rate')}` "
                f"hard_unseen=`{probe.get('hard_unseen_pass_rate')}` "
                f"raw_policy_generalization_rate=`{probe.get('raw_policy_generalization_rate')}` "
                f"final_decision_generalization_rate=`{probe.get('final_decision_generalization_rate')}` "
                f"raw_policy_unseen_generalization_rate=`{probe.get('raw_policy_unseen_generalization_rate')}` "
                f"final_decision_unseen_generalization_rate=`{probe.get('final_decision_unseen_generalization_rate')}` "
                f"variants=`{probe.get('variant_top1_hits')}/{probe.get('variant_count')}` "
                f"learning_signal=`{probe.get('learning_signal')}` reason=`{probe.get('learning_signal_reason')}`"
            )
    lines.extend(["", "## Fusion Mode Comparison", ""])
    for row in root_summary["engines"]:
        fusion = row.get("fusion_mode_comparison") or {}
        if not fusion:
            lines.append(f"- {row['engine_alias']}: no fusion mode comparison recorded")
            continue
        lines.append(
            f"- {row['engine_alias']}: selected=`{fusion.get('selected_gate_mode')}` best=`{fusion.get('best_mode')}` "
            f"policy_search_disagreement_rate=`{fusion.get('policy_search_disagreement_rate')}` "
            f"override_success_rate=`{fusion.get('override_success_rate')}` "
            f"override_regression_rate=`{fusion.get('override_regression_rate')}`"
        )
        for item in fusion.get("modes") or []:
            lines.append(
                f"- {row['engine_alias']} {item.get('fusion_mode')}: deterministic=`{item.get('deterministic_score')}` "
                f"unseen_final_generalization=`{item.get('final_decision_generalization_rate')}` "
                f"tactic_score=`{item.get('tactic_score')}` blunder_avoid=`{item.get('blunder_avoid_rate')}`"
            )
    lines.extend(["", "## Checkpoint Hash Evidence", ""])
    for row in root_summary["engines"]:
        hashes = row.get("checkpoint_hashes") or []
        if not hashes:
            lines.append(f"- {row['engine_alias']}: no checkpoint hash evidence recorded")
            continue
        for item in hashes:
            lines.append(
                f"- {row['engine_alias']} trusted=`{item.get('trusted_count')}` "
                f"previous=`{item.get('previous_model_hash')}` new=`{item.get('new_model_hash')}` "
                f"hash_changed=`{item.get('hash_changed')}`"
            )
    lines.append("- note: hash_changed only proves model bytes changed; it is not accepted as learning success without probe or benchmark evidence.")
    lines.extend(["", "## Can This Model Be Promoted?", ""])
    for row in root_summary["engines"]:
        lines.append(f"- {row['engine_alias']}: {row['can_be_promoted']}")
    lines.extend(["", "## Why This Run Failed", ""])
    failure_lines = []
    for summary in summaries:
        for reason in _failure_explanations(summary):
            if reason == "No blocking failure detected.":
                continue
            failure_lines.append(f"{summary['engine_alias']}: {reason}")
    if failure_lines:
        for line in sorted(set(failure_lines)):
            lines.append(f"- {line}")
    else:
        lines.append("- No blocking failure detected.")
    lines.extend(
        [
            "",
            "## Known Limitations",
            "",
            "- Benchmark samples are finite and still subject to variance.",
            "- Probe positions are intentionally fixed for comparability and may miss broader regressions.",
            "",
            "## False Positive Risks",
            "",
            "- Small hash or sample-count changes can overstate practical learning gains.",
            "- Tactical probe improvements may not translate to broad opening or endgame strength.",
            "",
            "## Remaining Contamination Risks",
            "",
        ]
    )
    for row in root_summary["engines"]:
        lines.append(
            f"- {row['engine_alias']}: invalid_train_entries=`{row['invalid_train_entries']}` "
            f"production_ok=`{row['suitable_for_production_self_learning']}`"
        )
    lines.extend(
        [
            "",
            "## Production Suitability",
            "",
            f"- suitable_for_production_self_learning: `{all(bool(row.get('suitable_for_production_self_learning')) for row in root_summary['engines'])}`",
        ]
    )
    return lines


def _write_root_report(output_root: Path, root_summary: dict, summaries: list[dict]) -> None:
    _json_dump(output_root / "summary.json", root_summary)
    (output_root / "SUMMARY.md").write_text("\n".join(_root_report_lines(root_summary, summaries)).rstrip() + "\n", encoding="utf-8")


def _report_consistency_issues(root_summary: dict, engine_summaries: list[dict], root_markdown: str, engine_markdown_by_alias: dict[str, str]) -> list[str]:
    issues = []
    engine_rows = {str(row.get("engine_alias") or ""): row for row in root_summary.get("engines") or []}
    if any(bool(row.get("catastrophic_regression")) for row in engine_rows.values()) and root_summary.get("overall_verdict") not in {"HIGH_RISK", "FAIL"}:
        issues.append("catastrophic regression did not elevate overall verdict")
    if "## Can This Model Be Promoted?" not in root_markdown:
        issues.append("root markdown missing promotion decision section")
    for summary in engine_summaries:
        alias = str(summary.get("engine_alias") or "")
        row = engine_rows.get(alias)
        if not row:
            issues.append(f"{alias}: missing root engine row")
            continue
        engine_md = engine_markdown_by_alias.get(alias, "")
        gate = summary.get("promotion_gate") or {}
        catastrophic = bool((summary.get("stability") or {}).get("catastrophic_regression"))
        benchmark_skipped = _summary_benchmark_skipped(summary)
        skip_reason = ""
        if benchmark_skipped:
            before = (summary.get("before_after_eval") or {}).get("benchmark_before") or {}
            after = (summary.get("before_after_eval") or {}).get("benchmark_after") or {}
            skip_reason = str(before.get("reason") or after.get("reason") or "unknown")
        if row.get("engine_verdict") != summary.get("engine_verdict"):
            issues.append(f"{alias}: verdict mismatch")
        if bool(row.get("promotion_gate_passed")) != bool(gate.get("passed")):
            issues.append(f"{alias}: promotion gate mismatch")
        if bool(row.get("catastrophic_regression")) != catastrophic:
            issues.append(f"{alias}: catastrophic regression mismatch")
        if bool(row.get("benchmark_skipped")) != benchmark_skipped:
            issues.append(f"{alias}: benchmark skipped mismatch")
        if (row.get("stage_game_win_rates") or []) != (summary.get("stage_game_win_rates") or []):
            issues.append(f"{alias}: stage win rates mismatch")
        if (row.get("deterministic_strength_snapshot") or {}) != (summary.get("deterministic_strength_snapshot") or {}):
            issues.append(f"{alias}: deterministic strength snapshot mismatch")
        if (row.get("stochastic_auxiliary_benchmark") or {}) != (summary.get("stochastic_auxiliary_benchmark") or {}):
            issues.append(f"{alias}: stochastic auxiliary benchmark mismatch")
        if (row.get("retrain_stability_report") or {}) != (summary.get("retrain_stability_report") or {}):
            issues.append(f"{alias}: retrain stability report mismatch")
        if (row.get("checkpoint_consistency") or {}) != (summary.get("checkpoint_consistency") or {}):
            issues.append(f"{alias}: checkpoint consistency mismatch")
        if (row.get("exp31_pipeline") or {}) != (summary.get("exp31_pipeline") or {}):
            issues.append(f"{alias}: exp31 pipeline mismatch")
        if (row.get("exp32_pipeline") or {}) != (summary.get("exp32_pipeline") or {}):
            issues.append(f"{alias}: exp32 pipeline mismatch")
        if (row.get("exp33_pipeline") or {}) != (summary.get("exp33_pipeline") or {}):
            issues.append(f"{alias}: exp33 pipeline mismatch")
        if (row.get("exp34_pipeline") or {}) != (summary.get("exp34_pipeline") or {}):
            issues.append(f"{alias}: exp34 pipeline mismatch")
        if (row.get("replay_fixture_health") or {}) != (summary.get("replay_fixture_health") or {}):
            issues.append(f"{alias}: replay fixture health mismatch")
        if (row.get("style_profile_audit") or {}) != (summary.get("style_profile_audit") or {}):
            issues.append(f"{alias}: style profile audit mismatch")
        if (row.get("opening_target_margin_audit") or {}) != (summary.get("opening_target_margin_audit") or {}):
            issues.append(f"{alias}: opening target margin audit mismatch")
        if "## Checkpoint Consistency" not in root_markdown or "## Checkpoint Consistency" not in engine_md:
            issues.append(f"{alias}: checkpoint consistency markdown missing")
        if "## Deterministic Strength Gate" not in root_markdown or "## Deterministic Strength Snapshot" not in engine_md:
            issues.append(f"{alias}: deterministic strength markdown missing")
        checkpoint_hashes = [
            {
                "trusted_count": checkpoint.get("trusted_count") or checkpoint.get("trusted_replays"),
                "previous_model_hash": checkpoint.get("previous_model_hash") or checkpoint.get("pre_checkpoint_model_sha256"),
                "new_model_hash": checkpoint.get("new_model_hash") or checkpoint.get("post_checkpoint_model_sha256"),
                "hash_changed": checkpoint.get("hash_changed") if "hash_changed" in checkpoint else checkpoint.get("model_hash_changed"),
            }
            for checkpoint in (summary.get("before_after_eval") or {}).get("checkpoints") or []
        ]
        if (row.get("checkpoint_hashes") or []) != checkpoint_hashes:
            issues.append(f"{alias}: checkpoint hash evidence mismatch")
        mistake_results = [
            {
                "trusted_count": checkpoint.get("trusted_count") or checkpoint.get("trusted_replays"),
                "learning_signal": (checkpoint.get("mistake_retention_probe") or {}).get("learning_signal"),
                "probe_case_id": (checkpoint.get("mistake_retention_probe") or {}).get("probe_case_id"),
                "before_move": (checkpoint.get("mistake_retention_probe") or {}).get("before_move"),
                "after_move": (checkpoint.get("mistake_retention_probe") or {}).get("after_move"),
                "expected_move": (checkpoint.get("mistake_retention_probe") or {}).get("expected_move"),
                "avoided_same_error": (checkpoint.get("mistake_retention_probe") or {}).get("avoided_same_error"),
                "avoided_old_mistake": (checkpoint.get("mistake_retention_probe") or {}).get("avoided_old_mistake"),
                "matched_expected": (checkpoint.get("mistake_retention_probe") or {}).get("matched_expected"),
                "result_kind": (checkpoint.get("mistake_retention_probe") or {}).get("result_kind"),
                "learning_signal_reason": (checkpoint.get("mistake_retention_probe") or {}).get("learning_signal_reason"),
            }
            for checkpoint in (summary.get("before_after_eval") or {}).get("checkpoints") or []
        ]
        if (row.get("mistake_retention_probe_results") or []) != mistake_results:
            issues.append(f"{alias}: mistake retention probe mismatch")
        sanity_results = [
            {
                "trusted_count": checkpoint.get("trusted_count") or checkpoint.get("trusted_replays"),
                "learning_signal": (checkpoint.get("sanity_learning_probe") or {}).get("learning_signal"),
                "result_kind": (checkpoint.get("sanity_learning_probe") or {}).get("result_kind"),
                "expected_move": ((checkpoint.get("sanity_learning_probe") or {}).get("case") or {}).get("expected_move"),
                "before_top1": ((checkpoint.get("sanity_learning_probe") or {}).get("before_exact") or {}).get("top1"),
                "before_top3": ((checkpoint.get("sanity_learning_probe") or {}).get("before_exact") or {}).get("top3"),
                "before_expected_in_top3": ((checkpoint.get("sanity_learning_probe") or {}).get("before_exact") or {}).get("expected_in_top3"),
                "after_top1": ((checkpoint.get("sanity_learning_probe") or {}).get("after_exact") or {}).get("top1"),
                "after_top3": ((checkpoint.get("sanity_learning_probe") or {}).get("after_exact") or {}).get("top3"),
                "after_expected_is_top1": ((checkpoint.get("sanity_learning_probe") or {}).get("after_exact") or {}).get("expected_is_top1"),
                "variant_count": (checkpoint.get("sanity_learning_probe") or {}).get("variant_count"),
                "variant_top1_hits": (checkpoint.get("sanity_learning_probe") or {}).get("variant_top1_hits"),
                "variant_top1_rate": (checkpoint.get("sanity_learning_probe") or {}).get("variant_top1_rate"),
                "exact_fen_pass": (checkpoint.get("sanity_learning_probe") or {}).get("exact_fen_pass"),
                "seen_variant_pass_rate": (checkpoint.get("sanity_learning_probe") or {}).get("seen_variant_pass_rate"),
                "unseen_variant_pass_rate": (checkpoint.get("sanity_learning_probe") or {}).get("unseen_variant_pass_rate"),
                "easy_unseen_pass_rate": (checkpoint.get("sanity_learning_probe") or {}).get("easy_unseen_pass_rate"),
                "medium_unseen_pass_rate": (checkpoint.get("sanity_learning_probe") or {}).get("medium_unseen_pass_rate"),
                "hard_unseen_pass_rate": (checkpoint.get("sanity_learning_probe") or {}).get("hard_unseen_pass_rate"),
                "variant_difficulty_scores": (checkpoint.get("sanity_learning_probe") or {}).get("variant_difficulty_scores") or {},
                "raw_policy_generalization_rate": (checkpoint.get("sanity_learning_probe") or {}).get("raw_policy_generalization_rate"),
                "final_decision_generalization_rate": (checkpoint.get("sanity_learning_probe") or {}).get("final_decision_generalization_rate"),
                "raw_policy_unseen_generalization_rate": (checkpoint.get("sanity_learning_probe") or {}).get("raw_policy_unseen_generalization_rate"),
                "final_decision_unseen_generalization_rate": (checkpoint.get("sanity_learning_probe") or {}).get("final_decision_unseen_generalization_rate"),
                "raw_policy_learning": (checkpoint.get("sanity_learning_probe") or {}).get("raw_policy_learning") or {},
                "final_decision_learning": (checkpoint.get("sanity_learning_probe") or {}).get("final_decision_learning") or {},
                "prior_learned_case_retention": (checkpoint.get("sanity_learning_probe") or {}).get("prior_learned_case_retention") or {},
                "blocked_by_search_or_static_eval": (checkpoint.get("sanity_learning_probe") or {}).get("blocked_by_search_or_static_eval"),
                "learning_signal_reason": (checkpoint.get("sanity_learning_probe") or {}).get("learning_signal_reason"),
            }
            for checkpoint in (summary.get("before_after_eval") or {}).get("checkpoints") or []
        ]
        if (row.get("sanity_learning_probe_results") or []) != sanity_results:
            issues.append(f"{alias}: sanity learning probe mismatch")
        if "## Can This Model Be Promoted?" not in engine_md:
            issues.append(f"{alias}: engine markdown missing promotion decision section")
        if str(gate.get("passed")) not in engine_md:
            issues.append(f"{alias}: engine markdown missing gate boolean")
        if catastrophic and "catastrophic_regression: `True`" not in engine_md:
            issues.append(f"{alias}: engine markdown missing catastrophic regression")
        if benchmark_skipped and skip_reason and skip_reason not in root_markdown + engine_md:
            issues.append(f"{alias}: skipped benchmark reason missing from markdown")
        for index, checkpoint in enumerate((summary.get("before_after_eval") or {}).get("checkpoints") or [], start=1):
            for key in ("dataset_hash", "trusted_count", "started_at", "finished_at", "duration_seconds", "previous_model_hash", "new_model_hash", "hash_changed", "pre_checkpoint_model_sha256", "post_checkpoint_model_sha256", "benchmark_skipped", "benchmark_skip_reason", "gate_decision"):
                if key not in checkpoint:
                    issues.append(f"{alias}: checkpoint {index} missing {key}")
            if checkpoint.get("benchmark_skipped") and not checkpoint.get("benchmark_skip_reason"):
                issues.append(f"{alias}: checkpoint {index} missing skipped benchmark reason")
            mistake_probe = checkpoint.get("mistake_retention_probe") or {}
            for key in ("probe_case_id", "before_move", "after_move", "avoided_same_error", "learning_signal", "learning_signal_reason", "human_explanation"):
                if key not in mistake_probe:
                    issues.append(f"{alias}: checkpoint {index} mistake probe missing {key}")
    return issues


def _prepare_formal_dataset(
    engine_dir: Path,
    runtime_dir: Path,
    *,
    artifact_dir: Path | None = None,
    invalid_game_ids: set[int] | None = None,
) -> dict:
    target_dir = artifact_dir or engine_dir
    output_dir = target_dir / "_prepared_dataset"
    stage_label = _source_stage_label(target_dir, engine_dir)
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "games" / "chess_replay_prepare.py"),
        "--replace-output",
        "--output-dir",
        str(output_dir),
        "--source-stage-label",
        stage_label,
    ]
    result = _run_json_subprocess(cmd, cwd=ROOT)
    train_rows = _read_jsonl(output_dir / "train.jsonl")
    rejected_rows = []
    for row in _read_jsonl(runtime_dir / "reports" / "games" / "chess_replays_quarantine.jsonl"):
        reasons = row.get("quarantine_reasons") or []
        rejected_rows.append(
            {
                "replay_id": str(row.get("replay_id") or ""),
                "source_game_id": int(row.get("match_id") or 0),
                "engine_name": str(row.get("engine_name") or ""),
                "collection_tier": str(row.get("collection_tier") or ""),
                "quarantine_reasons": reasons,
                "reject_reason": _canonical_reject_reason(reasons),
                "source": str(row.get("source") or ""),
                "move_count": int(row.get("move_count") or 0),
                "source_stage": stage_label,
            }
        )
    for row in _read_jsonl(runtime_dir / "reports" / "games" / "chess_replays_rejected.jsonl"):
        reasons = row.get("quarantine_reasons") or []
        rejected_rows.append(
            {
                "replay_id": str(row.get("replay_id") or ""),
                "source_game_id": int(row.get("match_id") or 0),
                "engine_name": str(row.get("engine_name") or ""),
                "collection_tier": str(row.get("collection_tier") or ""),
                "quarantine_reasons": reasons,
                "reject_reason": _canonical_reject_reason(reasons),
                "source": str(row.get("source") or ""),
                "move_count": int(row.get("move_count") or 0),
                "source_stage": stage_label,
            }
        )
    invalid_game_ids = invalid_game_ids or set()
    clean_train_rows = []
    blocked_contaminated_rows = []
    for row in train_rows:
        if int(row.get("source_game_id") or 0) in invalid_game_ids:
            blocked = dict(row)
            blocked["collection_tier"] = str(blocked.get("collection_tier") or "validation_blocked")
            blocked["reject_reason"] = "validation_invalid_game"
            blocked["quarantine_reasons"] = list(blocked.get("quarantine_reasons") or []) + ["validation_invalid_game"]
            blocked["source_stage"] = stage_label
            blocked_contaminated_rows.append(blocked)
            continue
        clean_train_rows.append(row)
    train_rows = clean_train_rows
    rejected_rows.extend(blocked_contaminated_rows)
    contaminated_rows = [row for row in train_rows if int(row.get("source_game_id") or 0) in invalid_game_ids]
    _jsonl_dump(target_dir / "train_dataset.jsonl", train_rows)
    _jsonl_dump(target_dir / "rejected_dataset.jsonl", rejected_rows)
    result["train_dataset_path"] = str(target_dir / "train_dataset.jsonl")
    result["rejected_dataset_path"] = str(target_dir / "rejected_dataset.jsonl")
    result["accepted_rows"] = len(train_rows)
    result["rejected_rows"] = len(rejected_rows)
    result["dataset_sha256"] = _sha256_file(target_dir / "train_dataset.jsonl")
    result["contaminated_rows"] = len(contaminated_rows)
    result["blocked_contaminated_rows"] = len(blocked_contaminated_rows)
    return result


def _model_meta(path: Path) -> dict:
    payload = _read_json(path)
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": _sha256_file(path),
        "sample_count": int(payload.get("sample_count") or 0) if isinstance(payload, dict) else 0,
        "updated_at": str(payload.get("updated_at") or "") if isinstance(payload, dict) else "",
        "replay_size": int(payload.get("replay_size") or 0) if isinstance(payload, dict) else 0,
    }


def _exp3_replay_loss(model_path: Path, samples: list[dict]) -> dict:
    if not samples:
        return {"supported": True, "sample_count": 0, "loss": None}
    try:
        from services.games import chess_dl as chess_dl_module  # noqa: PLC0415
    except Exception as exc:
        return {"supported": False, "sample_count": 0, "loss": None, "reason": str(exc)}
    model = chess_dl_module._load_model(Path(model_path))  # noqa: SLF001
    total = 0.0
    weight_total = 0.0
    used = 0
    for row in samples:
        normalized = chess_dl_module.normalize_experiment_dl_replay_sample(row)
        if normalized is None:
            continue
        prediction, _hidden1, _hidden2 = chess_dl_module._forward(model, normalized["features"])  # noqa: SLF001
        target = float(normalized.get("target") or 0.0)
        weight = float(normalized.get("weight") or 1.0)
        total += ((prediction - target) ** 2) * weight
        weight_total += weight
        used += 1
    return {
        "supported": True,
        "sample_count": used,
        "loss": round(total / weight_total, 6) if weight_total else None,
    }


def _quick_replay_loss(engine_alias: str, model_path: Path, samples: list[dict]) -> dict:
    if engine_alias == "exp3":
        return _exp3_replay_loss(model_path, samples)
    if engine_alias == "exp5":
        if not samples:
            return {"supported": True, "sample_count": 0, "loss": None}
        try:
            from services.games import chess_nnue as chess_nnue_module  # noqa: PLC0415
        except Exception as exc:
            return {"supported": False, "sample_count": 0, "loss": None, "reason": str(exc)}
        total = 0.0
        weight_total = 0.0
        used = 0
        for row in samples:
            normalized = chess_nnue_module.normalize_experiment_nnue_replay_sample(row)
            if normalized is None:
                continue
            ranks = chess_nnue_module.rank_experiment_nnue_policy_moves(
                {"__fen__": normalized["fen"]},
                str(normalized["side"]),
                model_path=model_path,
                search_profile="fast",
            )
            expected = str(normalized.get("move_uci") or "")
            expected_row = next((item for item in ranks if str(item.get("move") or "") == expected), None)
            if expected_row is None:
                continue
            rank = max(1, int(expected_row.get("raw_policy_rank") or len(ranks) or 1))
            weight = float(normalized.get("weight") or 1.0)
            target = float(normalized.get("target") or 1.0)
            sample_loss = (rank - 1) ** 2 if target >= 0 else 1.0 / rank
            total += sample_loss * weight
            weight_total += weight
            used += 1
        return {
            "supported": True,
            "sample_count": used,
            "loss": round(total / weight_total, 6) if weight_total else None,
        }
    if engine_alias != "exp4":
        return {"supported": False, "sample_count": 0, "loss": None, "reason": f"unsupported engine {engine_alias}"}
    if not samples:
        return {"supported": True, "sample_count": 0, "loss": None}
    try:
        from services.games import chess_pv as chess_pv_module  # noqa: PLC0415
    except Exception as exc:
        return {"supported": False, "sample_count": 0, "loss": None, "reason": str(exc)}
    model = chess_pv_module._load_model(Path(model_path))  # noqa: SLF001
    total = 0.0
    weight_total = 0.0
    used = 0
    for row in samples:
        normalized = chess_pv_module.normalize_experiment_pv_replay_sample(row)
        if normalized is None:
            continue
        hidden = chess_pv_module._forward_shared(model, normalized["board_features"])  # noqa: SLF001
        value_pred = chess_pv_module._value_from_hidden(model, hidden)  # noqa: SLF001
        policy_pred = chess_pv_module._policy_from_hidden(model, hidden, normalized["move_features"])  # noqa: SLF001
        target = float(normalized.get("target") or 0.0)
        policy_target = 1.0 if target >= 0.0 else -0.35
        weight = float(normalized.get("weight") or 1.0)
        sample_loss = ((value_pred - target) ** 2) + ((policy_pred - policy_target) ** 2)
        total += sample_loss * weight
        weight_total += weight
        used += 1
    return {
        "supported": True,
        "sample_count": used,
        "loss": round(total / weight_total, 6) if weight_total else None,
    }


def _targeted_probe_summary(before: dict, after: dict) -> dict:
    before_rows = (before.get("positions") or []) if isinstance(before, dict) else []
    after_rows = (after.get("positions") or []) if isinstance(after, dict) else []
    after_map = {str(row.get("position_id") or ""): row for row in after_rows}
    for before_row in before_rows:
        position_id = str(before_row.get("position_id") or "")
        after_row = after_map.get(position_id) or {}
        before_move = str(before_row.get("chosen_move") or "")
        after_move = str(after_row.get("chosen_move") or "")
        if before_move != after_move:
            return {
                "position_id": position_id,
                "before_move": before_move,
                "after_move": after_move,
                "changed": True,
                "before_score": before_row.get("score"),
                "after_score": after_row.get("score"),
            }
    if before_rows:
        first = before_rows[0]
        after_first = after_map.get(str(first.get("position_id") or "")) or {}
        return {
            "position_id": first.get("position_id"),
            "before_move": first.get("chosen_move"),
            "after_move": after_first.get("chosen_move"),
            "changed": False,
            "before_score": first.get("score"),
            "after_score": after_first.get("score"),
        }
    return {"changed": False, "reason": "no targeted probe positions"}


def _focus_benchmark_metrics(summary: dict, engine_name: str) -> dict:
    standings = summary.get("standings") if isinstance(summary.get("standings"), list) else []
    row = next((item for item in standings if str(item.get("engine") or "") == engine_name), {})
    matches = [item for item in (summary.get("matches") or []) if engine_name in {item.get("white_engine"), item.get("black_engine")}]
    suspicious = [item for item in (summary.get("suspicious_matches") or []) if engine_name in {item.get("white_engine"), item.get("black_engine")}]
    probe_rows = []
    for key in ("human_probes", "endgame_suite"):
        payload = summary.get(key) if isinstance(summary.get(key), dict) else {}
        probe_rows.extend([item for item in (payload.get("results") or []) if str(item.get("engine") or "") == engine_name])
    legal_rate = 0.0
    if probe_rows:
        legal_rate = round(sum(1 for row in probe_rows if not row.get("engine_illegal_move")) / len(probe_rows), 4)
    return {
        "engine": engine_name,
        "games": int(row.get("games") or 0),
        "wins": int(row.get("wins") or 0),
        "losses": int(row.get("losses") or 0),
        "draws": int(row.get("draws") or 0),
        "win_rate": float(row.get("win_rate") or 0.0),
        "score_rate": float(row.get("score_rate") or 0.0),
        "legal_rate": legal_rate,
        "low_quality_rate": round(len(suspicious) / len(matches), 4) if matches else 0.0,
        "suspicious_matches": len(suspicious),
    }


def _run_benchmark_snapshot(
    *,
    focus_engine_name: str,
    model_overrides: dict[str, Path],
    seed: int,
    benchmark_rounds: int,
    benchmark_max_plies: int,
    benchmark_teacher_depth: int,
) -> dict:
    store = ChessExperimentStore()
    summary = run_round_robin_benchmark(
        store=store,
        nn_model_path=model_overrides["nn"],
        dl_model_path=model_overrides["dl"],
        pv_model_path=model_overrides["pv"],
        rounds=max(1, int(benchmark_rounds)),
        max_plies=max(8, int(benchmark_max_plies)),
        seed=seed,
        teacher_depth=max(1, int(benchmark_teacher_depth)),
    )
    return {
        "focus": _focus_benchmark_metrics(summary, focus_engine_name),
        "summary": summary,
    }


def _skipped_benchmark_snapshot(reason: str) -> dict:
    return {
        "ok": True,
        "skipped": True,
        "reason": reason,
        "focus": {
            "skipped": True,
            "reason": reason,
        },
        "summary": {},
    }


def _should_launch_checkpoint(
    *,
    engine_alias: str,
    game: PlannedGame,
    stored_replay: dict,
    trusted_replays: int,
    pending_checkpoint_targets: set[int],
) -> bool:
    return (
        engine_alias in RETRAIN_ENGINE_ALIASES
        and game.category == "valid"
        and trusted_replays in pending_checkpoint_targets
        and bool(stored_replay.get("stored"))
    )


def _run_trainer_probe(
    *,
    engine_alias: str,
    engine_dir: Path,
    base_model_path: Path,
    accepted_rows: list[dict],
    rejected_rows: list[dict],
) -> dict:
    if engine_alias not in RETRAIN_ENGINE_ALIASES:
        return {"retrain_supported": False, "reason": "replay trainer not implemented for this engine"}
    probe_model_path = engine_dir / f"{engine_alias}_trainer_probe_model.json"
    if base_model_path.exists():
        shutil.copyfile(base_model_path, probe_model_path)
    invalid_rows = []
    for row in rejected_rows:
        invalid_rows.append(
            {
                "fen": "not a valid fen",
                "move_uci": "e2e4",
                "side": "white",
                "source": f"rejected:{','.join(row.get('quarantine_reasons') or [])}",
                "replay_id": row.get("replay_id"),
            }
        )
    probe_rows = list(accepted_rows) + invalid_rows
    probe_dataset_path = engine_dir / "_trainer_probe_dataset.jsonl"
    _jsonl_dump(probe_dataset_path, probe_rows)
    before_meta = _model_meta(probe_model_path)
    if engine_alias == "exp3":
        probe_replay_path = engine_dir / f"{engine_alias}_trainer_probe_replay.jsonl"
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp3_dataset_train.py"),
            "--input-jsonl",
            str(probe_dataset_path),
            "--model-path",
            str(probe_model_path),
            "--replay-path",
            str(probe_replay_path),
        ]
    elif engine_alias == "exp4":
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp4_dataset_train.py"),
            "--input-jsonl",
            str(probe_dataset_path),
            "--model-path",
            str(probe_model_path),
        ]
    else:
        return {"retrain_supported": False, "reason": "exp5 trainer scaffold exists, but retrain behavior is intentionally disabled pending design"}
    result = _run_json_subprocess(cmd, cwd=ROOT)
    after_meta = _model_meta(probe_model_path)
    result["probe_dataset_path"] = str(probe_dataset_path)
    result["accepted_expected_min"] = len(accepted_rows)
    result["rejected_expected"] = len(invalid_rows)
    result["model_before"] = before_meta
    result["model_after"] = after_meta
    result["validation"] = {
        "accepted_samples_gt_zero": bool(int(result.get("accepted_samples") or 0) > 0),
        "rejected_samples_match": int(result.get("rejected_samples") or -1) == len(invalid_rows),
        "model_changed": before_meta["sha256"] != after_meta["sha256"],
        "sample_count_changed": before_meta["sample_count"] != after_meta["sample_count"],
        "updated_at_changed": before_meta["updated_at"] != after_meta["updated_at"],
    }
    return result


def _write_engine_case(engine_dir: Path, index: int, game: PlannedGame, stored_replay: dict) -> None:
    payload = {
        "index": index,
        "label": game.label,
        "category": game.category,
        "expected_tier": game.expected_tier,
        "winner_color": game.winner_color,
        "notes": game.notes,
        "row": game.row,
        "preview_record": game.preview_record,
        "stored_replay": stored_replay,
        "flow": game.flow,
    }
    _json_dump(engine_dir / "games" / f"{index:02d}_{game.label}.json", payload)


def _write_engine_report(engine_dir: Path, summary: dict) -> None:
    autorun = summary.get("autorun") if isinstance(summary.get("autorun"), dict) else {}
    invalid_audit = summary.get("invalid_case_audit") or []
    exp1_live = summary.get("exp1_live_learning") or {}
    game_timing = summary.get("game_timing") or {}
    retrain_timing = summary.get("retrain_timing") or {}
    dataset_integrity = summary.get("dataset_integrity") or {}
    stability = summary.get("stability") or {}
    promotion_gate = summary.get("promotion_gate") or {}
    runtime_metrics = summary.get("runtime_metrics") or {}
    reproducibility = summary.get("reproducibility") or {}
    timing_breakdown = summary.get("timing_breakdown") or {}
    engine_verdict = str(summary.get("engine_verdict") or "")
    lines = [
        f"# {summary['engine_alias']} validation",
        "",
        f"- verdict: `{engine_verdict}`",
        f"- difficulty: `{summary['difficulty']}`",
        f"- seed: `{summary.get('seed')}`",
        f"- started_at: `{summary.get('started_at')}`",
        f"- finished_at: `{summary.get('finished_at')}`",
        f"- commit: `{summary.get('commit')}`",
        f"- validation_mode: `{summary.get('validation_mode') or 'full_30_game_expensive_validation'}`",
        f"- total_games: `{summary['total_games']}`",
        f"- trusted_replays: `{summary['replay_summary']['trusted_replays']}`",
        f"- quarantine_replays: `{summary['replay_summary']['quarantine_replays']}`",
        f"- rejected_replays: `{summary['replay_summary']['rejected_replays']}`",
        f"- retrain_supported: `{summary.get('retrain_result', {}).get('retrain_supported')}`",
        f"- avg_think_ms_per_step: `{game_timing.get('avg_think_ms_per_step')}`",
        f"- think_steps_measured: `{game_timing.get('steps_measured')}`",
        f"- total_retrain_seconds: `{retrain_timing.get('total_retrain_seconds')}`",
        f"- avg_retrain_seconds: `{retrain_timing.get('avg_retrain_seconds')}`",
        f"- dataset_duplicate_ratio: `{dataset_integrity.get('duplicate_ratio')}`",
        f"- dataset_illegal_moves: `{dataset_integrity.get('illegal_moves')}`",
        f"- catastrophic_regression: `{stability.get('catastrophic_regression')}`",
        f"- promotion_gate_passed: `{promotion_gate.get('passed')}`",
        f"- autorun_launched: `{autorun.get('launched', False)}`",
        f"- pipeline_status: `{summary.get('autorun_status', {}).get('status', '')}`",
        "",
        "## Why This Run Failed",
        "",
    ]
    for reason in _failure_explanations(summary):
        lines.append(f"- {reason}")
    lines.extend(
        [
            "",
            "## Dataset Integrity",
            "",
            f"- total_rows: `{dataset_integrity.get('total_rows')}`",
            f"- unique_positions: `{dataset_integrity.get('unique_positions')}`",
            f"- duplicate_ratio: `{dataset_integrity.get('duplicate_ratio')}`",
            f"- invalid_fen: `{dataset_integrity.get('invalid_fen')}`",
            f"- illegal_moves: `{dataset_integrity.get('illegal_moves')}`",
            f"- side_mismatch: `{dataset_integrity.get('side_mismatch')}`",
            f"- short_resign_games: `{dataset_integrity.get('short_resign_games')}`",
            "",
            "## Stability",
            "",
            f"- catastrophic_regression: `{stability.get('catastrophic_regression')}`",
            f"- opening_regression: `{stability.get('opening_regression')}`",
            f"- tactical_regression: `{stability.get('tactical_regression')}`",
            f"- endgame_regression: `{stability.get('endgame_regression')}`",
            f"- stage_win_rate_drop_10_20_vs_0_10: `{stability.get('stage_win_rate_drop_10_20_vs_0_10')}`",
            f"- stage_regression_threshold: `{stability.get('stage_regression_threshold')}`",
            f"- stage_catastrophic_regression: `{stability.get('stage_catastrophic_regression')}`",
            f"- late_stage: `{stability.get('late_stage')}`",
            f"- late_stage_win_rate: `{stability.get('late_stage_win_rate')}`",
            f"- late_stage_win_rate_collapse: `{stability.get('late_stage_win_rate_collapse')}`",
            f"- illegal_move_delta: `{stability.get('illegal_move_delta')}`",
            f"- blunder_rate_before: `{stability.get('blunder_rate_before')}`",
            f"- blunder_rate_after: `{stability.get('blunder_rate_after')}`",
            "",
            "## Promotion Gate",
            "",
            f"- passed: `{promotion_gate.get('passed')}`",
            "",
            "## Can This Model Be Promoted?",
            "",
            f"- {_promotion_explanation(summary)}",
        ]
    )
    for reason in promotion_gate.get("reasons") or []:
        lines.append(f"- reason: `{reason}`")
    lines.extend(
        [
            "",
            "## Runtime Metrics",
            "",
            f"- train_seconds: `{runtime_metrics.get('train_seconds')}`",
            f"- eval_seconds: `{runtime_metrics.get('eval_seconds')}`",
            f"- checkpoint_count: `{runtime_metrics.get('checkpoint_count')}`",
            f"- dataset_bytes: `{runtime_metrics.get('dataset_bytes')}`",
        ]
    )
    if timing_breakdown:
        lines.extend(
            [
                "",
                "## Timing Breakdown",
                "",
                f"- replay_generation_seconds: `{timing_breakdown.get('replay_generation_seconds')}`",
                f"- retrain_seconds: `{timing_breakdown.get('retrain_seconds')}`",
                f"- deterministic_eval_seconds: `{timing_breakdown.get('deterministic_eval_seconds')}`",
                f"- report_write_seconds: `{timing_breakdown.get('report_write_seconds')}`",
                f"- total_wall_seconds: `{timing_breakdown.get('total_wall_seconds')}`",
            ]
        )
    fixture_health = summary.get("replay_fixture_health") or {}
    if fixture_health:
        lines.extend(
            [
                "",
                "## Replay Fixture Health",
                "",
                f"- passed: `{fixture_health.get('passed')}`",
                f"- duplicate_ratio: `{fixture_health.get('duplicate_ratio')}`",
                f"- category_distribution: `{fixture_health.get('category_distribution')}`",
                f"- unique_fen_count: `{fixture_health.get('unique_fen_count')}`",
                f"- unique_normalized_board_count: `{fixture_health.get('unique_normalized_board_count')}`",
                f"- unique_target_move_count: `{fixture_health.get('unique_target_move_count')}`",
                f"- poison_quarantine_count: `{fixture_health.get('poison_quarantine_count')}`",
                f"- rejected_row_count: `{fixture_health.get('rejected_row_count')}`",
                f"- fixture_hash: `{fixture_health.get('fixture_hash')}`",
            ]
        )
        for reason in fixture_health.get("reasons") or []:
            lines.append(f"- fixture_health_reason: `{reason}`")
    distilled = summary.get("distilled_replay_preprocessing") or {}
    if distilled:
        lines.extend(
            [
                "",
                "## Distilled Replay Preprocessing",
                "",
                f"- enabled: `{distilled.get('enabled')}`",
                f"- raw_replay_rows: `{distilled.get('raw_replay_rows')}`",
                f"- distilled_replay_rows: `{distilled.get('distilled_replay_rows')}`",
                f"- compression_ratio: `{distilled.get('compression_ratio')}`",
                f"- duplicate_ratio_before: `{distilled.get('duplicate_ratio_before')}`",
                f"- duplicate_ratio_after: `{distilled.get('duplicate_ratio_after')}`",
                f"- held_out_in_training: `{distilled.get('held_out_in_training')}`",
                f"- leakage_detected: `{distilled.get('leakage_detected')}`",
                f"- pre_filter_overlap_count: `{distilled.get('pre_filter_overlap_count')}`",
                f"- blocked_leakage_candidate_count: `{distilled.get('blocked_leakage_candidate_count')}`",
                f"- post_filter_leakage_count: `{distilled.get('leakage_count')}`",
                f"- semantic_distribution: `{distilled.get('semantic_distribution')}`",
                f"- timing_seconds: `{distilled.get('timing_seconds')}`",
                f"- previous_retrain_seconds: `{distilled.get('previous_retrain_seconds')}`",
                f"- distilled_retrain_seconds: `{distilled.get('distilled_retrain_seconds')}`",
                f"- retrain_seconds_delta_vs_previous: `{distilled.get('retrain_seconds_delta_vs_previous')}`",
                f"- retrain_time_reduced: `{distilled.get('retrain_time_reduced')}`",
                "- promotion_evidence: `False`",
            ]
        )
        for report in distilled.get("checkpoint_reports") or []:
            lines.append(
                f"- checkpoint_distill original=`{report.get('original_rows')}` distilled=`{report.get('distilled_rows')}` "
                f"compression=`{report.get('compression_ratio')}` semantic_distribution=`{report.get('semantic_distribution')}` "
                f"flank_reason_distribution=`{report.get('flank_reason_distribution')}` leakage=`{report.get('leakage_detected')}` "
                f"blocked_candidates=`{report.get('blocked_leakage_candidate_count')}`"
            )
    exp30a = summary.get("exp30a_pipeline") or {}
    if exp30a:
        lines.extend(
            [
                "",
                "## Exp30a Leakage And Evaluation Cache",
                "",
                f"- held_out_in_training: `{exp30a.get('held_out_in_training')}`",
                f"- leakage_detected: `{exp30a.get('leakage_detected')}`",
                f"- pre_filter_overlap_count: `{exp30a.get('pre_filter_overlap_count')}`",
                f"- blocked_leakage_candidate_count: `{exp30a.get('blocked_leakage_candidate_count')}`",
                f"- post_filter_leakage_count: `{exp30a.get('post_filter_leakage_count')}`",
                f"- cache_hit_count: `{exp30a.get('cache_hit_count')}`",
                f"- cache_miss_count: `{exp30a.get('cache_miss_count')}`",
                f"- cache_hit_ratio: `{exp30a.get('cache_hit_ratio')}`",
                f"- skipped_eval_seconds_estimate: `{exp30a.get('skipped_eval_seconds_estimate')}`",
                f"- smoke_gate_passed: `{exp30a.get('smoke_gate_passed')}`",
                f"- full_gate_skipped: `{exp30a.get('full_gate_skipped')}`",
                f"- full_gate_skip_reason: `{exp30a.get('full_gate_skip_reason')}`",
            ]
        )
    exp30b = summary.get("exp30b_pipeline") or {}
    if exp30b:
        lines.extend(
            [
                "",
                "## Exp30b Semantic Interference Isolation",
                "",
                f"- semantic_specific_adapters: `{exp30b.get('semantic_specific_adapters')}`",
                f"- semantic_head_update_count: `{exp30b.get('semantic_head_update_count')}`",
                f"- semantic_loss_budget: `{exp30b.get('semantic_loss_budget')}`",
                f"- interference: `{exp30b.get('interference')}`",
                f"- interference_reasons: `{exp30b.get('interference_reasons')}`",
                f"- central_retention: `{exp30b.get('central_retention')}`",
                f"- flank_retention: `{exp30b.get('flank_retention')}`",
                f"- development_retention: `{exp30b.get('development_retention')}`",
                f"- mistake_retention: `{exp30b.get('mistake_retention')}`",
            ]
        )
    exp31 = summary.get("exp31_pipeline") or {}
    if exp31:
        lines.extend(
            [
                "",
                "## Exp31 Semantic Loss Budget Scheduler",
                "",
                f"- loss_budget_by_semantic: `{exp31.get('loss_budget_by_semantic')}`",
                f"- consumed_budget_by_semantic: `{exp31.get('consumed_budget_by_semantic')}`",
                f"- effective_gradient_norm_by_semantic: `{exp31.get('effective_gradient_norm_by_semantic')}`",
                f"- update_count_by_semantic: `{exp31.get('update_count_by_semantic')}`",
                f"- margin_delta_by_semantic: `{exp31.get('margin_delta_by_semantic')}`",
                f"- semantic_loss_budget_skew: `{exp31.get('semantic_loss_budget_skew')}`",
                f"- catastrophic_semantic_interference: `{exp31.get('catastrophic_semantic_interference')}`",
                f"- semantic_interference: `{exp31.get('semantic_interference')}`",
                f"- interference_reasons: `{exp31.get('interference_reasons')}`",
                f"- rollback_applied: `{exp31.get('rollback_applied')}`",
                f"- rollback_reasons: `{exp31.get('rollback_reasons')}`",
                f"- dampened_semantics: `{exp31.get('dampened_semantics')}`",
                f"- negative_cosine_like_conflict_count: `{exp31.get('negative_cosine_like_conflict_count')}`",
                f"- central_retention_after_flank_updates: `{exp31.get('central_retention_after_flank_updates')}`",
                f"- flank_retention_after_central_updates: `{exp31.get('flank_retention_after_central_updates')}`",
                f"- mistake_retention: `{exp31.get('mistake_retention')}`",
                f"- note: `{exp31.get('note')}`",
            ]
        )
    exp32 = summary.get("exp32_pipeline") or {}
    if exp32:
        lines.extend(
            [
                "",
                "## Exp32 Smoke Anchor Calibration",
                "",
                f"- development_multi_good_credit_applied: `{exp32.get('development_multi_good_credit_applied')}`",
                f"- development_smoke_before_after_credit: `{exp32.get('development_smoke_before_after_credit')}`",
                f"- flank_smoke_difficulty_distribution: `{exp32.get('flank_smoke_difficulty_distribution')}`",
                f"- contextual_flank_reason_tags: `{exp32.get('contextual_flank_reason_tags')}`",
                f"- flank_vs_central_margin: `{exp32.get('flank_vs_central_margin')}`",
                f"- flank_vs_development_margin: `{exp32.get('flank_vs_development_margin')}`",
                f"- consumed_budget_by_semantic: `{exp32.get('consumed_budget_by_semantic')}`",
                f"- update_count_by_semantic: `{exp32.get('update_count_by_semantic')}`",
                f"- anchor_pass_delta_by_semantic: `{exp32.get('anchor_pass_delta_by_semantic')}`",
                f"- repair_applied: `{exp32.get('repair_applied')}`",
                f"- repair_success: `{exp32.get('repair_success')}`",
                f"- smoke_gate_failed_reason_type: `{exp32.get('smoke_gate_failed_reason_type')}`",
                f"- model_failure_vs_gate_scoring_issue: `{exp32.get('model_failure_vs_gate_scoring_issue')}`",
                f"- note: `{exp32.get('note')}`",
            ]
        )
        for report in exp32.get("smoke_anchor_audit_table") or []:
            lines.append(
                f"- trusted=`{report.get('trusted_count')}` smoke_failure_counts=`{report.get('failure_reason_counts')}`"
            )
    exp33 = summary.get("exp33_pipeline") or {}
    if exp33:
        lines.extend(
            [
                "",
                "## Exp33 Failed Smoke Anchor Microdiagnosis",
                "",
                f"- selected_safe_checkpoint: `{exp33.get('selected_safe_checkpoint')}`",
                f"- safe_checkpoint_selection: `{exp33.get('safe_checkpoint_selection')}`",
                f"- e_pawn_dampening_audit: `{exp33.get('e_pawn_dampening_audit')}`",
                f"- mistake_retention_stronger_repair: `{exp33.get('mistake_retention_stronger_repair')}`",
                f"- flank_rehearsal_applied: `{exp33.get('flank_rehearsal_applied')}`",
                f"- interference_detected: `{exp33.get('interference_detected')}`",
                f"- note: `{exp33.get('note')}`",
            ]
        )
        for report in exp33.get("smoke_anchor_microdiagnosis") or []:
            lines.append(
                f"- trusted=`{report.get('trusted_count')}` microdiagnosis_failure_counts=`{report.get('failure_reason_counts')}`"
            )
        for report in exp33.get("failed_anchor_isolated_overfit") or []:
            lines.append(
                f"- trusted=`{report.get('trusted_count')}` isolated_cases=`{report.get('case_count')}` exact_pass=`{report.get('isolated_exact_pass_count')}`"
            )
    exp34 = summary.get("exp34_pipeline") or {}
    if exp34:
        lines.extend(
            [
                "",
                "## Exp34 Mixed Scheduler Repair",
                "",
                f"- selected_safe_checkpoint: `{exp34.get('selected_safe_checkpoint')}`",
                f"- cp20_rejected_by_retention: `{exp34.get('cp20_rejected_by_retention')}`",
                f"- retention_case_version_audit: `{exp34.get('retention_case_version_audit')}`",
                f"- smoke_level_1_passed: `{exp34.get('smoke_level_1_passed')}`",
                f"- smoke_level_2_passed: `{exp34.get('smoke_level_2_passed')}`",
                f"- failure_classification: `{exp34.get('failure_classification')}`",
                f"- easy_anchor_pass_before_after: `{exp34.get('easy_anchor_pass_before_after')}`",
                f"- semantic_pass_delta_after_each_batch: `{exp34.get('semantic_pass_delta_after_each_batch')}`",
                f"- balanced_fusion_threshold_adjustment_tested: `{exp34.get('balanced_fusion_threshold_adjustment_tested')}`",
                f"- questionable_hard_flank_label: `{exp34.get('questionable_hard_flank_label')}`",
                f"- hard_flank_capability_gap: `{exp34.get('hard_flank_capability_gap')}`",
                f"- note: `{exp34.get('note')}`",
            ]
        )
        for report in exp34.get("mixed_scheduler_repair") or []:
            lines.append(
                f"- trusted=`{report.get('trusted_count')}` mixed_rehearsal_applied=`{report.get('mixed_rehearsal_applied')}` "
                f"repair_cases=`{report.get('repair_case_ids')}`"
            )
        for report in exp34.get("smoke_level_report") or []:
            lines.append(
                f"- trusted=`{report.get('trusted_count')}` level1=`{report.get('smoke_level_1_passed')}` "
                f"level2=`{report.get('smoke_level_2_passed')}` classification=`{report.get('failure_classification')}` "
                f"reasons=`{report.get('reasons')}`"
            )
        for report in exp34.get("hard_e_pawn_decision_audit") or []:
            lines.append(
                f"- hard_e_pawn trusted=`{report.get('trusted_count')}` case=`{report.get('case_id')}` "
                f"blocker=`{report.get('blocker_type')}` rejection=`{report.get('rejection_reason')}`"
            )
        for report in exp34.get("hard_flank_audit") or []:
            lines.append(
                f"- hard_flank trusted=`{report.get('trusted_count')}` case=`{report.get('case_id')}` "
                f"questionable=`{report.get('questionable_hard_flank_label')}` capability_gap=`{report.get('hard_flank_capability_gap')}`"
            )
    flank_injection = summary.get("flank_context_feature_injection") or {}
    if flank_injection:
        lines.extend(
            [
                "",
                "## Flank Context Feature Injection",
                "",
                f"- enabled: `{flank_injection.get('enabled')}`",
                f"- trainer_feature_injection: `{flank_injection.get('trainer_feature_injection')}`",
                f"- flank_context_classification_updates: `{flank_injection.get('flank_context_classification_updates')}`",
                f"- flank_reason_tag_updates: `{flank_injection.get('flank_reason_tag_updates')}`",
                f"- flank_vs_nonflank_margin_updates: `{flank_injection.get('flank_vs_nonflank_margin_updates')}`",
                f"- bad_random_flank_rejection_updates: `{flank_injection.get('bad_random_flank_rejection_updates')}`",
                f"- note: `{flank_injection.get('note')}`",
            ]
        )
        for index, report in enumerate(flank_injection.get("checkpoint_reports") or [], start=1):
            lines.append(
                f"- checkpoint `{index}` trainer_feature_injection=`{report.get('trainer_feature_injection')}` "
                f"context_loss_updates=`{(report.get('flank_context_classification_loss') or {}).get('updates')}` "
                f"reason_loss_updates=`{(report.get('flank_reason_tag_loss') or {}).get('updates')}` "
                f"margin_updates=`{(report.get('flank_vs_nonflank_margin_loss') or {}).get('updates')}` "
                f"flank_vs_central=`{report.get('flank_vs_central_margin')}` "
                f"flank_vs_development=`{report.get('flank_vs_development_margin')}`"
            )
    stage_rates = summary.get("stage_game_win_rates") or []
    if stage_rates:
        lines.extend(
            [
                "",
                "## Stage Game Win Rates",
                "",
                "- basis: `trusted_valid_games_only`; invalid_games_excluded=`True`",
            ]
        )
        for row in stage_rates:
            lines.append(
                f"- stage `{row.get('stage')}` normal_games=`{row.get('normal_games')}` "
                f"wins=`{row.get('wins')}` losses=`{row.get('losses')}` draws=`{row.get('draws')}` "
                f"win_rate=`{row.get('win_rate')}` "
                f"delta_from_previous=`{row.get('win_rate_delta_from_previous_stage')}`"
            )
    retrain_stability = summary.get("retrain_stability_report") or {}
    if retrain_stability:
        late_stage = retrain_stability.get("late_stage") or {}
        scores = retrain_stability.get("deterministic_scores") or {}
        retention = retrain_stability.get("mistake_retention") or {}
        hyper = retrain_stability.get("trainer_hyperparameters") or {}
        lines.extend(
            [
                "",
                "## Retrain Stability Report",
                "",
                f"- suspected_catastrophic_regression: `{retrain_stability.get('suspected_catastrophic_regression')}`",
                f"- late_stage: `{late_stage.get('stage')}` win_rate=`{late_stage.get('win_rate')}` normal_games=`{late_stage.get('normal_games')}` collapsed=`{late_stage.get('collapsed')}`",
                f"- deterministic_scores: baseline=`{scores.get('baseline')}` checkpoint@10=`{scores.get('checkpoint@10')}` checkpoint@20=`{scores.get('checkpoint@20')}` final=`{scores.get('final')}`",
                f"- deterministic_regressed_vs_baseline: `{scores.get('regressed_vs_baseline')}`",
                f"- deterministic_regressed_vs_checkpoint10: `{scores.get('regressed_vs_checkpoint10')}`",
                f"- deterministic_regressed_vs_checkpoint20: `{scores.get('regressed_vs_checkpoint20')}`",
                f"- mistake_retention: baseline=`{retention.get('baseline_score')}` final=`{retention.get('final_score')}` regressed=`{retention.get('regressed')}`",
                f"- trainer_learning_rate: `{hyper.get('learning_rate')}`",
                f"- trainer_epochs: `{hyper.get('epochs')}`",
                f"- trainer_gradient_norm: `{hyper.get('gradient_norm')}`",
                f"- trainer_loss_delta: `{hyper.get('loss_delta')}`",
            ]
        )
        checkpoint_retention = retrain_stability.get("checkpoint10_vs_checkpoint20_retention") or {}
        if checkpoint_retention:
            cp10 = checkpoint_retention.get("checkpoint10") or {}
            cp20 = checkpoint_retention.get("checkpoint20") or {}
            lines.append(
                f"- checkpoint10_vs_checkpoint20_retention: "
                f"cp10_exact=`{cp10.get('exact_fen_pass')}` cp20_exact=`{cp20.get('exact_fen_pass')}` "
                f"cp10_seen=`{cp10.get('seen_variant_pass_rate')}` cp20_seen=`{cp20.get('seen_variant_pass_rate')}` "
                f"cp10_unseen=`{cp10.get('unseen_variant_pass_rate')}` cp20_unseen=`{cp20.get('unseen_variant_pass_rate')}` "
                f"cp20_blocked=`{checkpoint_retention.get('final_decision_blocked')}` "
                f"blocked_reason=`{cp20.get('blocked_reason')}`"
            )
        for reason in retrain_stability.get("reasons") or []:
            lines.append(f"- stability_reason: `{reason}`")
    checkpoint_consistency = summary.get("checkpoint_consistency") or {}
    lines.extend(
        [
            "",
            "## Checkpoint Consistency",
            "",
            f"- passed: `{checkpoint_consistency.get('passed')}`",
            f"- instability: `{checkpoint_consistency.get('instability')}`",
            "",
            "## Checkpoint Consistency Table",
            "",
        ]
    )
    if checkpoint_consistency:
        for item in checkpoint_consistency.get("checkpoint_consistency_table") or []:
            lines.append(
                f"- trusted=`{item.get('trusted_count')}` exact=`{item.get('exact_retention')}` "
                f"seen=`{item.get('seen_retention')}` unseen=`{item.get('unseen_retention')}` "
                f"raw_unseen=`{item.get('raw_unseen_retention')}` hard_held_out=`{item.get('hard_held_out_retention')}` "
                f"clean_held_out=`{item.get('clean_held_out_retention')}` "
                f"hard_clean_held_out=`{item.get('hard_clean_held_out_retention')}` "
                f"clean_pool_sufficient=`{item.get('clean_held_out_pool_sufficient')}` "
                f"prior_failed=`{item.get('prior_retention_failed_count')}` "
            f"embedding_after=`{item.get('embedding_similarity_after')}` "
            f"embedding_delta=`{item.get('embedding_similarity_delta')}` "
            f"policy_margin=`{item.get('hard_negative_min_margin')}` "
            f"semantic_margin=`{item.get('semantic_hard_negative_min_margin')}` passed=`{item.get('passed')}`"
        )
        lines.extend(["", "## Balanced Gate Semantic Cleanup", ""])
        for item in checkpoint_consistency.get("checkpoint_consistency_table") or []:
            development_credit = item.get("development_multi_good_credit") or {}
            attacking_audit = item.get("attacking_style_audit") or {}
            lines.append(
                f"- trusted=`{item.get('trusted_count')}` balanced_gate_semantic_set=`{item.get('balanced_gate_semantic_set')}` "
                f"excluded_style_semantics=`{item.get('excluded_style_semantics')}` "
                f"balanced_by_semantic=`{item.get('balanced_clean_heldout_by_semantic')}`"
            )
            lines.append(
                f"- trusted=`{item.get('trusted_count')}` development_multi_good_cases=`{development_credit.get('multi_good_move_case_count')}` "
                f"development_credit_applied=`{development_credit.get('multi_good_credit_applied_count')}` "
                f"development_case_count=`{development_credit.get('case_count')}`"
            )
            lines.append(
                f"- trusted=`{item.get('trusted_count')}` attacking_style_case_count=`{attacking_audit.get('case_count')}` "
                f"attacking_style_strict_final_pass_rate=`{attacking_audit.get('strict_final_pass_rate')}` "
                f"attacking_style_raw_policy_pass_rate=`{attacking_audit.get('raw_policy_pass_rate')}`"
            )
        lines.extend(["", "## Central / Flank Semantic Improvement", ""])
        for item in checkpoint_consistency.get("checkpoint_consistency_table") or []:
            focus = item.get("central_flank_targeted_curriculum") or {}
            analysis = item.get("central_flank_failed_case_analysis") or {}
            flank_audit = item.get("flank_label_audit") or {}
            flank_perf = item.get("flank_difficulty_performance") or {}
            contextual_flank = item.get("contextual_flank_performance") or {}
            bad_random = item.get("bad_random_flank_push_confusion") or contextual_flank.get("bad_random_flank_push_confusion") or {}
            boundary = item.get("central_vs_flank_boundary") or {}
            lines.append(
                f"- trusted=`{item.get('trusted_count')}` focus_semantics=`{focus.get('focus_semantics')}` "
                f"targeted_train_rows=`{focus.get('train_rows_added')}` "
                f"semantic_pair_contrast=`{focus.get('semantic_pair_contrast')}`"
            )
            lines.append(
                f"- trusted=`{item.get('trusted_count')}` flank_label_audit clean=`{flank_audit.get('clean_count')}` "
                f"questionable=`{flank_audit.get('questionable_count')}` invalid=`{flank_audit.get('invalid_count')}` "
                f"reason_distribution=`{flank_audit.get('flank_reason_distribution') or item.get('flank_reason_distribution')}` "
                f"bad_random=`{flank_audit.get('bad_random_flank_push_count')}` by_difficulty=`{flank_audit.get('by_difficulty')}`"
            )
            lines.append(
                f"- trusted=`{item.get('trusted_count')}` flank_difficulty_performance=`{flank_perf.get('by_difficulty')}` "
                f"hard_coverage_complete=`{flank_perf.get('hard_coverage_complete')}`"
            )
            lines.append(
                f"- trusted=`{item.get('trusted_count')}` contextual_flank_pass_rate=`{contextual_flank.get('contextual_flank_pass_rate')}` "
                f"hard_contextual=`{contextual_flank.get('hard_clean_contextual_hits')}/{contextual_flank.get('hard_clean_count')}` "
                f"bad_random_confusion=`{bad_random.get('count')}` bad_random_promoted=`{bad_random.get('promoted_count')}` "
                f"feature_importance=`{item.get('context_feature_importance') or contextual_flank.get('context_feature_importance')}`"
            )
            lines.append(
                f"- trusted=`{item.get('trusted_count')}` central_vs_flank_boundary "
                f"central_to_flank=`{boundary.get('central_to_flank_confusion')}` "
                f"flank_to_central=`{boundary.get('flank_to_central_confusion')}` "
                f"raw_flank_to_central=`{boundary.get('raw_policy_flank_to_central_confusion')}`"
            )
            for semantic, row in (analysis.get("by_semantic") or {}).items():
                lines.append(
                    f"- trusted=`{item.get('trusted_count')}` central_flank_failed semantic=`{semantic}` "
                    f"failed=`{row.get('failed_count')}` raw_policy_fail=`{row.get('raw_policy_fail_count')}` "
                    f"final_decision_fail=`{row.get('final_decision_fail_count')}` "
                    f"confusion_targets=`{row.get('confusion_targets')}`"
                )
        lines.extend(["", "## Semantic Class Distribution", ""])
        for item in checkpoint_consistency.get("checkpoint_consistency_table") or []:
            distribution = item.get("semantic_class_distribution") or {}
            for split in ["train", "validation", "held_out", "clean_gate_cases"]:
                row = distribution.get(split) or {}
                if not row:
                    continue
                lines.append(
                    f"- trusted=`{item.get('trusted_count')}` split=`{split}` "
                    f"balanced=`{row.get('balanced')}` missing=`{row.get('missing_classes')}` "
                    f"kingside_to_central=`{row.get('kingside_to_central_ratio')}` "
                    f"counts=`{row.get('candidate_counts')}`"
                )
        lines.extend(["", "## Semantic Balanced Sampling", ""])
        for item in checkpoint_consistency.get("checkpoint_consistency_table") or []:
            sampling = item.get("semantic_sampling") or {}
            effective = sampling.get("effective_distribution") or {}
            lines.append(
                f"- trusted=`{item.get('trusted_count')}` method=`{sampling.get('method')}` "
                f"passed=`{sampling.get('passed')}` skew_ratio=`{sampling.get('skew_ratio')}` "
                f"threshold=`{sampling.get('threshold')}` sample_weight_by_semantic=`{item.get('effective_sample_weight_by_semantic')}` "
                f"effective_weight=`{effective.get('effective_weight') or item.get('train_effective_distribution')}`"
            )
        lines.extend(["", "## Embedding Drift Table", ""])
        for item in checkpoint_consistency.get("embedding_drift_table") or []:
            lines.append(
                f"- trusted=`{item.get('trusted_count')}` embedding_after=`{item.get('embedding_similarity_after')}` "
                f"embedding_delta=`{item.get('embedding_similarity_delta')}` "
                f"embedding_drift_from_previous=`{item.get('embedding_drift_from_previous')}` "
                f"hard_negative_min_margin=`{item.get('hard_negative_min_margin')}` "
                f"policy_margin_drift_from_previous=`{item.get('policy_margin_drift_from_previous')}`"
            )
        lines.extend(["", "## Retention Chain", ""])
        for item in checkpoint_consistency.get("retention_chain") or []:
            lines.append(
                f"- trusted=`{item.get('trusted_count')}` exact=`{item.get('exact')}` seen=`{item.get('seen')}` "
                f"unseen=`{item.get('unseen')}` raw_unseen=`{item.get('raw_unseen')}` "
                f"hard_held_out=`{item.get('hard_held_out')}` prior_failed=`{item.get('prior_retention_failed_count')}` "
                f"clean_held_out=`{item.get('clean_held_out')}` hard_clean_held_out=`{item.get('hard_clean_held_out')}` "
                f"passed=`{item.get('passed')}`"
            )
        lines.extend(["", "## Early Checkpoint Failure Analysis", ""])
        for item in checkpoint_consistency.get("checkpoint_consistency_table") or []:
            analysis = item.get("early_checkpoint_failure_analysis") or {}
            if not analysis:
                continue
            lines.append(
                f"- trusted=`{item.get('trusted_count')}` final_unseen=`{analysis.get('final_unseen_pass_rate')}` "
                f"hard_held_out=`{analysis.get('hard_held_out_pass_rate')}` "
                f"hard_negative_min_margin=`{analysis.get('hard_negative_min_margin')}` "
                f"failures=`{analysis.get('failure_reasons')}`"
            )
        lines.extend(["", "## Hard Negative Margin Table", ""])
        for item in checkpoint_consistency.get("checkpoint_consistency_table") or []:
            for margin in (item.get("hard_negative_margin_table") or [])[:12]:
                lines.append(
                    f"- trusted=`{item.get('trusted_count')}` case=`{margin.get('case_id')}` "
                    f"negative=`{margin.get('hard_negative')}` before=`{margin.get('margin_before')}` "
                    f"after=`{margin.get('margin_after')}` delta=`{margin.get('margin_delta')}`"
                )
            for margin in (item.get("semantic_hard_negative_margin_table") or [])[:12]:
                lines.append(
                    f"- trusted=`{item.get('trusted_count')}` semantic_margin case=`{margin.get('case_id')}` "
                    f"expected_semantic=`{margin.get('expected_semantic')}` negative=`{margin.get('hard_negative')}` "
                    f"negative_semantic=`{margin.get('hard_negative_semantic')}` after=`{margin.get('margin_after')}`"
                )
        lines.extend(["", "## Embedding Similarity Delta By Group", ""])
        for item in checkpoint_consistency.get("checkpoint_consistency_table") or []:
            for group, payload in (item.get("embedding_similarity_delta_by_group") or {}).items():
                lines.append(
                    f"- trusted=`{item.get('trusted_count')}` group=`{group}` "
                    f"before=`{(payload.get('before') or {}).get('avg_similarity')}` "
                    f"after=`{(payload.get('after') or {}).get('avg_similarity')}` "
                    f"delta=`{payload.get('delta')}`"
                )
        lines.extend(["", "## Invariance Context Key Examples", ""])
        for item in checkpoint_consistency.get("checkpoint_consistency_table") or []:
            for example in (item.get("invariance_context_key_examples") or [])[:6]:
                lines.append(
                    f"- trusted=`{item.get('trusted_count')}` split=`{example.get('variant_split')}` "
                    f"difficulty=`{example.get('variant_difficulty')}` expected=`{example.get('expected_move')}` "
                    f"context_key=`{example.get('context_key')}`"
                )
        lines.extend(["", "## Held-Out Label Quality", ""])
        for item in checkpoint_consistency.get("checkpoint_consistency_table") or []:
            quality = item.get("label_quality") or {}
            quality_summary = item.get("label_quality_summary") or quality.get("summary") or {}
            lines.append(
                f"- trusted=`{item.get('trusted_count')}` checked=`{quality.get('checked_count')}` "
                f"clean=`{quality_summary.get('clean')}` questionable=`{quality_summary.get('questionable')}` "
                f"invalid=`{quality_summary.get('invalid')}` hard_excluded=`{quality_summary.get('hard_excluded')}` "
                f"warnings=`{quality.get('warning_count')}` label_quality_warning=`{quality.get('label_quality_warning')}`"
            )
            for warning in quality.get("warnings") or []:
                lines.append(f"- trusted=`{item.get('trusted_count')}` label_warning: `{warning}`")
        lines.extend(["", "## Clean Vs Questionable Performance", ""])
        for item in checkpoint_consistency.get("checkpoint_consistency_table") or []:
            performance = item.get("clean_vs_questionable_performance") or {}
            for bucket in ["clean_held_out", "hard_clean_held_out", "questionable", "invalid"]:
                row = performance.get(bucket) or {}
                if not row:
                    continue
                lines.append(
                    f"- trusted=`{item.get('trusted_count')}` bucket=`{bucket}` count=`{row.get('count')}` "
                    f"final_pass_rate=`{row.get('final_pass_rate')}` raw_policy_pass_rate=`{row.get('raw_policy_pass_rate')}`"
                )
            for difficulty, row in (performance.get("clean_held_out_by_difficulty") or {}).items():
                lines.append(
                    f"- trusted=`{item.get('trusted_count')}` bucket=`clean_held_out:{difficulty}` "
                    f"count=`{row.get('count')}` final_pass_rate=`{row.get('final_pass_rate')}` "
                    f"raw_policy_pass_rate=`{row.get('raw_policy_pass_rate')}`"
                )
            for semantic, row in (performance.get("clean_held_out_by_semantic") or {}).items():
                if not row or int(row.get("count") or 0) <= 0:
                    continue
                lines.append(
                    f"- trusted=`{item.get('trusted_count')}` bucket=`semantic:{semantic}` "
                    f"count=`{row.get('count')}` final_pass_rate=`{row.get('final_pass_rate')}` "
                    f"raw_policy_pass_rate=`{row.get('raw_policy_pass_rate')}`"
                )
        lines.extend(["", "## Semantic Confusion Matrix", ""])
        for item in checkpoint_consistency.get("checkpoint_consistency_table") or []:
            semantic = item.get("semantic_analysis") or {}
            confusion = semantic.get("confusion_matrix") or {}
            centroids = semantic.get("semantic_centroid_analysis_after") or {}
            candidate_centroids = semantic.get("semantic_candidate_centroid_analysis_after") or {}
            margin_report = semantic.get("semantic_margin_report") or {}
            lines.append(
                f"- trusted=`{item.get('trusted_count')}` d_vs_e=`{semantic.get('d7d5_vs_e7e5_confusion')}` "
                f"e_vs_d=`{semantic.get('e7e5_vs_d7d5_confusion')}` "
                f"central_to_kingside_rate=`{(semantic.get('semantic_confusion_gate') or {}).get('central_to_kingside_rate')}` "
                f"semantic_min_margin=`{margin_report.get('semantic_min_margin')}` matrix=`{confusion.get('matrix')}`"
            )
            targeted = semantic.get("targeted_centroid_distances_after") or {}
            if targeted:
                lines.append(
                    f"- trusted=`{item.get('trusted_count')}` targeted_centroid_min=`{targeted.get('min_distance')}` "
                    f"threshold=`{targeted.get('threshold')}` passed=`{targeted.get('passed')}` pairs=`{targeted.get('pairs')}`"
                )
            for semantic_class, row in (semantic.get("semantic_class_performance") or {}).items():
                lines.append(
                    f"- trusted=`{item.get('trusted_count')}` semantic=`{semantic_class}` "
                    f"count=`{row.get('count')}` pass_rate=`{row.get('pass_rate')}` predicted=`{row.get('predicted')}`"
                )
            for semantic_class, distances in (centroids.get("inter_semantic_distance") or {}).items():
                nearest = (centroids.get("nearest_semantic") or {}).get(semantic_class)
                confused = (centroids.get("nearest_confused_semantic") or {}).get(semantic_class)
                lines.append(
                    f"- trusted=`{item.get('trusted_count')}` centroid=`{semantic_class}` "
                    f"intra=`{(centroids.get('intra_semantic_distance') or {}).get(semantic_class)}` "
                    f"nearest=`{nearest}` nearest_confused=`{confused}` distances=`{distances}`"
                )
            for semantic_class, distances in (candidate_centroids.get("inter_semantic_distance") or {}).items():
                nearest = (candidate_centroids.get("nearest_semantic") or {}).get(semantic_class)
                lines.append(
                    f"- trusted=`{item.get('trusted_count')}` candidate_centroid=`{semantic_class}` "
                    f"intra=`{(candidate_centroids.get('intra_semantic_distance') or {}).get(semantic_class)}` "
                    f"nearest=`{nearest}` distances=`{distances}`"
                )
            for semantic_class, row in (margin_report.get("top_confused_semantic_margins") or {}).items():
                lines.append(
                    f"- trusted=`{item.get('trusted_count')}` semantic_margin expected=`{semantic_class}` "
                    f"top_confused=`{row.get('top_confused_semantic')}` "
                    f"confusion_count=`{row.get('confusion_count')}` margin=`{row.get('margin')}`"
                )
        lines.extend(["", "## Clean Held-Out Pool", ""])
        for item in checkpoint_consistency.get("checkpoint_consistency_table") or []:
            pool = item.get("held_out_pool") or {}
            for difficulty, payload in (pool.get("by_difficulty") or {}).items():
                lines.append(
                    f"- trusted=`{item.get('trusted_count')}` difficulty=`{difficulty}` "
                    f"candidates=`{payload.get('candidate_count')}` clean=`{payload.get('clean_count')}` "
                    f"selected_clean=`{payload.get('selected_clean_count')}` questionable=`{payload.get('questionable_count')}` "
                    f"invalid=`{payload.get('invalid_count')}` sufficient=`{payload.get('sufficient_clean_pool')}`"
                )
        lines.extend(["", "## Excluded From Gate Cases", ""])
        for item in checkpoint_consistency.get("checkpoint_consistency_table") or []:
            for case in (item.get("excluded_from_gate_cases") or [])[:12]:
                lines.append(
                    f"- trusted=`{item.get('trusted_count')}` case=`{case.get('case_id')}` "
                    f"quality=`{case.get('label_quality')}` expected=`{case.get('expected_move')}` "
                    f"static_best=`{case.get('static_best_move')}` delta_cp=`{case.get('static_cp_delta')}` "
                    f"expected_rank=`{case.get('expected_rank')}`"
                )
        lines.extend(["", "## Failed Clean Cases Top3", ""])
        for item in checkpoint_consistency.get("checkpoint_consistency_table") or []:
            for case in item.get("failed_clean_cases_top3") or []:
                lines.append(
                    f"- trusted=`{item.get('trusted_count')}` case=`{case.get('case_id')}` "
                    f"expected=`{case.get('expected_move')}` final_top3=`{case.get('final_top3')}` "
                    f"raw_top3=`{case.get('raw_policy_top3')}` expected_rank=`{case.get('expected_rank')}`"
                )
        for reason in checkpoint_consistency.get("instability_reasons") or []:
            lines.append(f"- instability_reason: `{reason}`")
    deterministic = summary.get("deterministic_strength_snapshot") or {}
    if deterministic:
        final_det = deterministic.get("final") or {}
        lines.extend(
            [
                "",
                "## Deterministic Strength Snapshot",
                "",
                f"- passed: `{deterministic.get('passed')}`",
                f"- regression_vs_baseline: `{deterministic.get('regression_vs_baseline')}`",
                f"- regression_vs_checkpoint10: `{deterministic.get('regression_vs_checkpoint10')}`",
                f"- regression_vs_checkpoint20: `{deterministic.get('regression_vs_checkpoint20')}`",
                f"- final_overall_deterministic_score: `{final_det.get('overall_deterministic_score')}`",
                f"- final_top1_correct_rate: `{final_det.get('top1_correct_rate')}`",
                f"- final_top3_contains_rate: `{final_det.get('top3_contains_rate')}`",
                f"- final_illegal_rate: `{final_det.get('illegal_rate')}`",
                f"- final_blunder_avoid_rate: `{final_det.get('blunder_avoid_rate')}`",
                "",
                "## Deterministic Score Table",
                "",
            ]
        )
        for item in deterministic.get("score_table") or []:
            lines.append(
                f"- {item.get('model_label')}: score=`{item.get('overall_deterministic_score')}` "
                f"top1=`{item.get('top1_correct_rate')}` top3=`{item.get('top3_contains_rate')}` "
                f"illegal=`{item.get('illegal_rate')}` blunder_avoid=`{item.get('blunder_avoid_rate')}`"
            )
        category_score = final_det.get("category_score") or {}
        if category_score:
            lines.extend(["", "## Deterministic Category Scores", ""])
            for category, item in sorted(category_score.items()):
                lines.append(
                    f"- {category}: score=`{item.get('score')}` count=`{item.get('count')}` "
                    f"top1=`{item.get('top1_correct_rate')}` top3=`{item.get('top3_contains_rate')}` "
                    f"illegal=`{item.get('illegal_rate')}` blunder_rate=`{item.get('blunder_rate')}`"
                )
    override_audit = summary.get("policy_override_audit") or {}
    if override_audit:
        lines.extend(
            [
                "",
                "## Policy Override Audit",
                "",
                f"- override_usage_count: `{override_audit.get('override_usage_count')}`",
                f"- override_success_rate: `{override_audit.get('override_success_rate')}`",
                f"- override_regression_rate: `{override_audit.get('override_regression_rate')}`",
                f"- passed: `{override_audit.get('passed')}`",
            ]
        )
        for reason in override_audit.get("regression_reasons") or []:
            lines.append(f"- override_regression_reason: `{reason}`")
        for item in override_audit.get("override_cases") or []:
            thresholds = item.get("thresholds") or {}
            lines.append(
                f"- case `{item.get('case_id')}` category=`{item.get('category')}` "
                f"move=`{item.get('override_move')}` margin=`{item.get('margin')}` "
                f"min_margin=`{thresholds.get('min_margin')}` min_score=`{thresholds.get('min_score')}` "
                f"reason=`{item.get('override_reason')}`"
            )
    opening_audit = summary.get("opening_target_margin_audit") or {}
    if opening_audit and opening_audit.get("supported"):
        lines.extend(
            [
                "",
                "## Exp4 Opening Target Margin / MCTS Audit",
                "",
                f"- model_scope: `{opening_audit.get('model_scope')}`",
                f"- targeted_learning_success: `{opening_audit.get('targeted_learning_success')}`",
                f"- broad_strength_improvement: `{opening_audit.get('broad_strength_improvement')}`",
                f"- final_decision_alignment_passed: `{opening_audit.get('final_decision_alignment_passed')}`",
                f"- deterministic_baseline_score: `{opening_audit.get('deterministic_baseline_score')}`",
                f"- deterministic_final_score: `{opening_audit.get('deterministic_final_score')}`",
                f"- multi_good_tie_count: `{opening_audit.get('multi_good_tie_count')}`",
                f"- multi_good_credit_applied_count: `{opening_audit.get('multi_good_credit_applied_count')}`",
                f"- strict_top1_fail_but_multi_good_pass_count: `{opening_audit.get('strict_top1_fail_but_multi_good_pass_count')}`",
                f"- low_margin_override_applied_count: `{opening_audit.get('low_margin_override_applied_count')}`",
                f"- low_margin_override_rejected_count: `{opening_audit.get('low_margin_override_rejected_count')}`",
                f"- failure_type_counts: `{opening_audit.get('failure_type_counts')}`",
                f"- passed: `{opening_audit.get('passed')}`",
            ]
        )
        for item in (opening_audit.get("cases") or [])[:8]:
            lines.append(
                f"- case=`{item.get('case_id')}` expected=`{item.get('expected_move')}` final=`{item.get('final_top1')}` "
                f"mcts=`{item.get('mcts_best_move')}` static=`{item.get('static_best_move')}` search=`{item.get('search_best_move')}` "
                f"margin_selected=`{item.get('margin_vs_selected_move')}` raw_margin=`{item.get('raw_margin_vs_selected_move')}` "
                f"multi_good=`{item.get('multi_good_tie')}` failure=`{item.get('failure_type')}` "
                f"override_rejected=`{item.get('override_rejected_reason')}`"
            )
    fusion = summary.get("fusion_mode_comparison") or {}
    if fusion:
        lines.extend(
            [
                "",
                "## Fusion Mode Comparison",
                "",
                f"- selected_gate_mode: `{fusion.get('selected_gate_mode')}`",
                f"- best_mode: `{fusion.get('best_mode')}`",
                f"- policy_search_disagreement_rate: `{fusion.get('policy_search_disagreement_rate')}`",
                f"- override_success_rate: `{fusion.get('override_success_rate')}`",
                f"- override_regression_rate: `{fusion.get('override_regression_rate')}`",
                f"- passed: `{fusion.get('passed')}`",
            ]
        )
        for item in fusion.get("modes") or []:
            lines.append(
                f"- {item.get('fusion_mode')}: deterministic=`{item.get('deterministic_score')}` "
                f"unseen_final_generalization=`{item.get('final_decision_generalization_rate')}` "
                f"tactic_score=`{item.get('tactic_score')}` blunder_avoid=`{item.get('blunder_avoid_rate')}` "
                f"disagreement=`{item.get('policy_search_disagreement_rate')}` "
                f"override_success=`{item.get('override_success_rate')}`"
            )
    style_audit = summary.get("style_profile_audit") or {}
    if style_audit:
        lines.extend(
            [
                "",
                "## Style Profile Audit",
                "",
                f"- promotion_gate_profile: `{style_audit.get('promotion_gate_profile')}`",
                f"- balanced_gate_unaffected_by_style: `{style_audit.get('balanced_gate_unaffected_by_style')}`",
                f"- style_override_count: `{style_audit.get('style_override_count')}`",
                f"- rejected_style_move_count: `{style_audit.get('rejected_style_move_count')}`",
                f"- unsafe_override_count: `{style_audit.get('unsafe_override_count')}`",
                f"- passed: `{style_audit.get('passed')}`",
            ]
        )
        profiles = style_audit.get("profiles") or {}
        for profile in ["balanced", "attacking", "defensive"]:
            for item in (profiles.get(profile) or [])[:4]:
                lines.append(
                    f"- profile=`{profile}` case=`{item.get('case_id')}` chosen=`{item.get('chosen_move')}` "
                    f"base_score=`{item.get('base_score')}` style_bonus=`{item.get('style_bonus')}` "
                    f"final_score=`{item.get('final_score')}` applied=`{item.get('applied')}` "
                    f"rejected=`{len(item.get('rejected_style_moves') or [])}` reason=`{item.get('rejection_reason')}`"
                )
    specialist = summary.get("semantic_specialist_probes") or {}
    if specialist:
        lines.extend(
            [
                "",
                "## Semantic Specialist Probes",
                "",
                f"- enabled: `{specialist.get('enabled')}`",
                f"- diagnosis: `{specialist.get('diagnosis')}`",
                f"- kingside_can_learn_alone: `{specialist.get('kingside_can_learn_alone')}`",
                f"- development_can_learn_alone: `{specialist.get('development_can_learn_alone')}`",
                f"- promotion_gate_impact: `{specialist.get('promotion_gate_impact')}`",
            ]
        )
        for group in specialist.get("groups") or []:
            lines.append(
                f"- group=`{group.get('group')}` semantics=`{group.get('semantic_classes')}` "
                f"exact=`{(group.get('exact') or {}).get('final_pass_rate')}` "
                f"seen=`{(group.get('seen_variants') or {}).get('final_pass_rate')}` "
                f"clean_held_out=`{(group.get('clean_held_out') or {}).get('final_pass_rate')}` "
                f"hard_margin=`{(group.get('hard_negative_margin') or {}).get('min_margin')}` "
                f"passed=`{group.get('passed')}`"
            )
            for failed in group.get("failed_top3") or []:
                lines.append(
                    f"- group=`{group.get('group')}` failed_case=`{failed.get('case_id')}` "
                    f"expected=`{failed.get('expected_move')}` final_top1=`{failed.get('final_top1')}` "
                    f"final_top3=`{failed.get('final_top3')}` expected_rank=`{failed.get('expected_rank')}`"
                )
    kd_audit = summary.get("kingside_development_audit") or {}
    if kd_audit:
        gate_semantics = kd_audit.get("gate_semantics") or {}
        kingside = kd_audit.get("kingside_label_audit") or {}
        development = kd_audit.get("development_label_audit") or {}
        lines.extend(
            [
                "",
                "## Kingside / Development Audit",
                "",
                f"- enabled: `{kd_audit.get('enabled')}`",
                f"- balanced_hard_gate_semantics: `{gate_semantics.get('balanced_hard_gate_semantics')}`",
                f"- style_audit_semantics: `{gate_semantics.get('style_audit_semantics')}`",
                f"- kingside_questionable_style_label_count: `{kingside.get('questionable_style_label_count')}`",
                f"- development_multi_good_move_case_count: `{development.get('multi_good_move_case_count')}`",
                f"- development_top3_or_multigood_credit_rate: `{development.get('top3_or_multigood_credit_rate')}`",
                f"- promotion_gate_impact: `{kd_audit.get('promotion_gate_impact')}`",
            ]
        )
        for row in (kingside.get("questionable_style_label_cases") or [])[:5]:
            lines.append(
                f"- kingside_questionable case=`{row.get('case_id')}` expected=`{row.get('expected_move')}` "
                f"static_best=`{row.get('static_best_move')}` search_best=`{row.get('search_best_move')}` "
                f"rank=`{row.get('expected_rank')}` final_top1=`{row.get('final_top1')}` "
                f"reason=`{row.get('rejection_reason')}`"
            )
        for row in (development.get("multi_good_move_cases") or [])[:5]:
            lines.append(
                f"- development_multigood case=`{row.get('case_id')}` expected=`{row.get('expected_move')}` "
                f"final_top3=`{row.get('final_top3')}` raw_top3=`{row.get('raw_policy_top3')}` "
                f"static_delta=`{row.get('static_cp_delta')}`"
            )
    aux = summary.get("stochastic_auxiliary_benchmark") or {}
    lines.extend(
        [
            "",
            "## Stochastic Auxiliary Game Benchmark",
            "",
            f"- skipped: `{aux.get('skipped')}`",
            f"- skip_reason: `{aux.get('skip_reason')}`",
            f"- strength_evidence: `{aux.get('strength_evidence')}`",
            f"- note: `{aux.get('purpose')}`",
            "",
            "## Perft And Runtime Separation",
            "",
            f"- perft_strength_evidence: `{(summary.get('perft') or {}).get('strength_evidence')}`",
            f"- perft_reason: `{(summary.get('perft') or {}).get('reason')}`",
            "- runtime_strength_evidence: `False`",
            "- runtime_note: `runtime only measures speed/cost, not chess strength`",
        ]
    )
    lines.extend(
        [
            "",
            "## Reproducibility",
            "",
            f"- git_dirty: `{reproducibility.get('git_dirty')}`",
            f"- dataset_hash: `{reproducibility.get('dataset_hash')}`",
            f"- trainer_hash: `{reproducibility.get('trainer_hash')}`",
            "",
            "## Invalid Cases",
            "",
        ]
    )
    for item in summary["games"]:
        if item["category"] == "valid":
            continue
        lines.append(
            f"- game {item['index']:02d} `{item['label']}` => expected `{item['expected_tier']}`, "
            f"actual `{item['stored_replay'].get('collection_tier', '')}`, "
            f"reasons `{','.join(item['stored_replay'].get('quarantine_reasons') or [])}`"
        )
    if invalid_audit:
        lines.extend(["", "## Invalid Audit", ""])
        for row in invalid_audit:
            lines.append(
                f"- game_id `{row.get('game_id')}` reason `{row.get('injection_reason')}` "
                f"expected `{row.get('expected_classification')}` actual `{row.get('actual_classification')}` "
                f"entered_train_dataset=`{row.get('entered_train_dataset')}` verdict=`{row.get('verdict')}`"
            )
    eval_before = summary.get("evaluation_before") or {}
    eval_after = summary.get("evaluation_after") or {}
    checkpoint_reported = False
    if eval_before.get("supported"):
        lines.extend(
            [
                "",
                "## Learning Evidence",
                "",
                f"- move_agreement_before: `{eval_before.get('agreement')}`",
                f"- move_agreement_after: `{eval_after.get('agreement')}`",
                f"- avg_think_ms_before: `{eval_before.get('avg_think_ms')}`",
                f"- avg_think_ms_after: `{eval_after.get('avg_think_ms')}`",
                f"- model_before_hash: `{summary.get('model_before', {}).get('sha256', '')}`",
                f"- model_after_hash: `{summary.get('model_after', {}).get('sha256', '')}`",
                f"- benchmark_win_rate_before: `{summary.get('before_after_eval', {}).get('benchmark_before', {}).get('win_rate')}`",
                f"- benchmark_win_rate_after: `{summary.get('before_after_eval', {}).get('benchmark_after', {}).get('win_rate')}`",
                f"- legal_rate_before: `{summary.get('before_after_eval', {}).get('benchmark_before', {}).get('legal_rate')}`",
                f"- legal_rate_after: `{summary.get('before_after_eval', {}).get('benchmark_after', {}).get('legal_rate')}`",
            ]
        )
        checkpoints = summary.get("before_after_eval", {}).get("checkpoints") or []
        if checkpoints:
            checkpoint_reported = True
            lines.extend(["", "## Checkpoints", ""])
            for row in checkpoints:
                mistake_probe = row.get("mistake_retention_probe") or {}
                lines.append(
                    f"- trusted={row.get('trusted_count') or row.get('trusted_replays')} "
                    f"started_at=`{row.get('started_at')}` finished_at=`{row.get('finished_at')}` "
                    f"duration_seconds=`{row.get('duration_seconds')}` "
                    f"previous_model_hash=`{row.get('previous_model_hash') or row.get('pre_checkpoint_model_sha256')}` "
                    f"new_model_hash=`{row.get('new_model_hash') or row.get('post_checkpoint_model_sha256')}` "
                    f"hash_changed=`{row.get('hash_changed') if 'hash_changed' in row else row.get('model_hash_changed')}` "
                    f"win_rate `{(row.get('benchmark_before') or {}).get('win_rate')}` -> `{(row.get('benchmark_after') or {}).get('win_rate')}` "
                    f"agreement `{(row.get('move_agreement_before') or {}).get('agreement')}` -> `{(row.get('move_agreement_after') or {}).get('agreement')}` "
                    f"replay_loss `{(row.get('replay_loss_before') or {}).get('loss')}` -> `{(row.get('replay_loss_after') or {}).get('loss')}` "
                    f"targeted_probe `{(row.get('targeted_probe') or {}).get('before_move')}` -> `{(row.get('targeted_probe') or {}).get('after_move')}` "
                    f"think_ms `{(row.get('move_agreement_before') or {}).get('avg_think_ms')}` -> `{(row.get('move_agreement_after') or {}).get('avg_think_ms')}` "
                    f"retention_probe=`{(row.get('retention_probe') or {}).get('learning_signal')}` "
                    f"mistake_probe=`{mistake_probe.get('learning_signal')}` "
                    f"mistake_case=`{mistake_probe.get('probe_case_id')}` "
                    f"mistake_before=`{mistake_probe.get('before_move')}` "
                    f"mistake_after=`{mistake_probe.get('after_move')}` "
                    f"mistake_expected=`{mistake_probe.get('expected_move')}` "
                    f"avoided_old_mistake=`{mistake_probe.get('avoided_old_mistake')}` "
                    f"matched_expected=`{mistake_probe.get('matched_expected')}` "
                    f"result_kind=`{mistake_probe.get('result_kind')}` "
                    f"avoided_same_error=`{mistake_probe.get('avoided_same_error')}` "
                    f"sanity_learning_probe=`{(row.get('sanity_learning_probe') or {}).get('learning_signal')}` "
                    f"sanity_result=`{(row.get('sanity_learning_probe') or {}).get('result_kind')}` "
                    f"sanity_before_top1=`{((row.get('sanity_learning_probe') or {}).get('before_exact') or {}).get('top1')}` "
                    f"sanity_after_top1=`{((row.get('sanity_learning_probe') or {}).get('after_exact') or {}).get('top1')}` "
                    f"status `{(row.get('autorun_status') or {}).get('status')}`"
                )
                if mistake_probe.get("learning_signal") is False:
                    lines.append(f"- mistake_probe_explanation: {mistake_probe.get('human_explanation')}")
                sanity_probe = row.get("sanity_learning_probe") or {}
                if sanity_probe:
                    raw = sanity_probe.get("raw_policy_learning") or {}
                    final = sanity_probe.get("final_decision_learning") or {}
                    lines.append(
                        f"- sanity_learning_probe: expected=`{(sanity_probe.get('case') or {}).get('expected_move')}` "
                        f"before_top3=`{(sanity_probe.get('before_exact') or {}).get('top3')}` "
                        f"after_top3=`{(sanity_probe.get('after_exact') or {}).get('top3')}` "
                        f"raw_policy_learning=`{raw.get('learning_signal')}` "
                        f"raw_top1 `{raw.get('raw_policy_top1_before')}` -> `{raw.get('raw_policy_top1_after')}` "
                        f"expected_rank `{raw.get('expected_rank_before')}` -> `{raw.get('expected_rank_after')}` "
                        f"expected_margin_after=`{raw.get('expected_margin_after')}` "
                        f"final_decision_learning=`{final.get('learning_signal')}` "
                        f"blocked_by_search_or_static_eval=`{sanity_probe.get('blocked_by_search_or_static_eval')}` "
                        f"exact_fen_pass=`{sanity_probe.get('exact_fen_pass')}` "
                        f"seen_variant_pass_rate=`{sanity_probe.get('seen_variant_pass_rate')}` "
                        f"unseen_variant_pass_rate=`{sanity_probe.get('unseen_variant_pass_rate')}` "
                        f"easy_unseen=`{sanity_probe.get('easy_unseen_pass_rate')}` "
                        f"medium_unseen=`{sanity_probe.get('medium_unseen_pass_rate')}` "
                        f"hard_unseen=`{sanity_probe.get('hard_unseen_pass_rate')}` "
                        f"raw_policy_generalization_rate=`{sanity_probe.get('raw_policy_generalization_rate')}` "
                        f"final_decision_generalization_rate=`{sanity_probe.get('final_decision_generalization_rate')}` "
                        f"raw_policy_unseen_generalization_rate=`{sanity_probe.get('raw_policy_unseen_generalization_rate')}` "
                        f"final_decision_unseen_generalization_rate=`{sanity_probe.get('final_decision_unseen_generalization_rate')}` "
                        f"variant_top1_hits=`{sanity_probe.get('variant_top1_hits')}` "
                        f"variant_count=`{sanity_probe.get('variant_count')}` "
                        f"reason=`{sanity_probe.get('learning_signal_reason')}`"
                    )
                    for difficulty, score in sorted((sanity_probe.get("variant_difficulty_scores") or {}).items()):
                        lines.append(
                            f"- sanity_{difficulty}: seen_pass_rate=`{score.get('seen_pass_rate')}` "
                            f"unseen_pass_rate=`{score.get('unseen_pass_rate')}` "
                            f"seen_raw_policy_pass_rate=`{score.get('seen_raw_policy_pass_rate')}` "
                            f"unseen_raw_policy_pass_rate=`{score.get('unseen_raw_policy_pass_rate')}` "
                            f"held_out_from_training=`{score.get('held_out_from_training')}`"
                        )
                    if final.get("blocked_reason"):
                        lines.append(f"- sanity_decision_blocked_reason: `{final.get('blocked_reason')}`")
                    prior_retention = sanity_probe.get("prior_learned_case_retention") or {}
                    if prior_retention:
                        lines.append(
                            f"- prior_learned_case_retention: checked=`{prior_retention.get('checked_count')}` "
                            f"retained=`{prior_retention.get('retained_count')}` failed=`{prior_retention.get('failed_count')}` "
                            f"reason=`{prior_retention.get('reason')}`"
                        )
                    after_breakdown = final.get("decision_breakdown_after") or {}
                    for move_row in after_breakdown.get("watched_moves") or []:
                        lines.append(
                            f"- sanity_decision_after {move_row.get('move')}: "
                            f"raw_policy_score=`{move_row.get('raw_policy_score')}` "
                            f"static_eval_score=`{move_row.get('static_eval_score')}` "
                            f"search_score=`{move_row.get('search_score')}` "
                            f"legal_move_bonus_penalty=`{move_row.get('legal_move_bonus_penalty')}` "
                            f"final_combined_score=`{move_row.get('final_combined_score')}` "
                            f"chosen=`{move_row.get('chosen')}`"
                        )
                    blockers = ((sanity_probe.get("feature_generalization_debug") or {}).get("final_decision_blockers") or [])[:5]
                    for blocker in blockers:
                        lines.append(
                            f"- sanity_variant_blocker `{blocker.get('case_id')}` "
                            f"split=`{blocker.get('variant_split')}` difficulty=`{blocker.get('variant_difficulty')}` "
                            f"expected=`{blocker.get('expected_move')}` final_top1=`{blocker.get('final_top1')}` "
                            f"raw_top1=`{blocker.get('raw_policy_top1')}` expected_rank=`{blocker.get('expected_rank')}` "
                            f"blocked_by_search_or_static_eval=`{blocker.get('blocked_by_search_or_static_eval')}` "
                            f"chosen_reason=`{blocker.get('chosen_reason')}`"
                        )
                    failed_unseen = ((sanity_probe.get("feature_generalization_debug") or {}).get("failed_unseen_cases") or [])[:5]
                    for failed in failed_unseen:
                        lines.append(
                            f"- failed_unseen_case `{failed.get('case_id')}` "
                            f"difficulty=`{failed.get('variant_difficulty')}` expected=`{failed.get('expected_move')}` "
                            f"final_top1=`{failed.get('final_top1')}` raw_top3=`{failed.get('raw_policy_top3')}` "
                            f"expected_rank=`{failed.get('expected_rank')}` margin=`{failed.get('expected_margin_vs_old_move')}` "
                            f"blocking_features=`{','.join(failed.get('blocking_features') or [])}`"
                        )
                    hard_margin = ((sanity_probe.get("feature_generalization_debug") or {}).get("expected_vs_hard_negative_margin") or {})
                    if hard_margin:
                        lines.append(f"- expected_vs_hard_negative_min_margin: `{hard_margin.get('min_margin')}`")
                    embedding = ((sanity_probe.get("feature_generalization_debug") or {}).get("embedding_similarity") or {})
                    if embedding:
                        lines.append(
                            f"- embedding_similarity: before=`{(embedding.get('policy_embedding_similarity_before') or {}).get('avg_similarity')}` "
                            f"after=`{(embedding.get('policy_embedding_similarity_after') or {}).get('avg_similarity')}` "
                            f"delta=`{embedding.get('avg_similarity_delta')}`"
                        )
                    feature_groups = ((sanity_probe.get("feature_generalization_debug") or {}).get("failed_feature_groups") or [])[:5]
                    for group in feature_groups:
                        lines.append(f"- failed_feature_group `{group.get('blocking_feature')}` count=`{group.get('count')}`")
            lines.append("- hash_note: hash_changed only proves model bytes changed; it is not accepted as learning success without probe or benchmark evidence.")
            benchmark_timeline = (summary.get("before_after_eval") or {}).get("benchmark_timeline") or []
            if benchmark_timeline:
                lines.extend(["", "## Formal Benchmark Timeline", ""])
                for item in benchmark_timeline:
                    benchmark = item.get("benchmark") or {}
                    lines.append(
                        f"- {item.get('label')}: trusted=`{item.get('trusted_count')}` "
                        f"model_hash=`{item.get('model_hash')}` win_rate=`{benchmark.get('win_rate')}` "
                        f"legal_rate=`{benchmark.get('legal_rate')}` low_quality_rate=`{benchmark.get('low_quality_rate')}` "
                        f"skipped=`{item.get('benchmark_skipped')}` reason=`{item.get('benchmark_skip_reason')}`"
                )
    elif summary.get("retrain_result", {}).get("retrain_supported") is False:
        lines.extend(
            [
                "",
                "## Retrain",
                "",
                f"- reason: `{summary.get('retrain_result', {}).get('reason', '')}`",
            ]
        )
    checkpoints = summary.get("before_after_eval", {}).get("checkpoints") or []
    if checkpoints and not checkpoint_reported:
        lines.extend(["", "## Checkpoints", ""])
        for row in checkpoints:
            mistake_probe = row.get("mistake_retention_probe") or {}
            lines.append(
                f"- trusted={row.get('trusted_count') or row.get('trusted_replays')} "
                f"started_at=`{row.get('started_at')}` finished_at=`{row.get('finished_at')}` "
                f"duration_seconds=`{row.get('duration_seconds')}` "
                f"previous_model_hash=`{row.get('previous_model_hash') or row.get('pre_checkpoint_model_sha256')}` "
                f"new_model_hash=`{row.get('new_model_hash') or row.get('post_checkpoint_model_sha256')}` "
                f"hash_changed=`{row.get('hash_changed') if 'hash_changed' in row else row.get('model_hash_changed')}` "
                f"mistake_probe=`{mistake_probe.get('learning_signal')}` "
                f"mistake_case=`{mistake_probe.get('probe_case_id')}` "
                f"mistake_before=`{mistake_probe.get('before_move')}` "
                f"mistake_after=`{mistake_probe.get('after_move')}` "
                f"mistake_expected=`{mistake_probe.get('expected_move')}` "
                f"avoided_old_mistake=`{mistake_probe.get('avoided_old_mistake')}` "
                f"matched_expected=`{mistake_probe.get('matched_expected')}` "
                f"result_kind=`{mistake_probe.get('result_kind')}` "
                f"avoided_same_error=`{mistake_probe.get('avoided_same_error')}` "
                f"sanity_learning_probe=`{(row.get('sanity_learning_probe') or {}).get('learning_signal')}` "
                f"sanity_result=`{(row.get('sanity_learning_probe') or {}).get('result_kind')}`"
            )
            if mistake_probe.get("learning_signal") is False:
                lines.append(f"- mistake_probe_explanation: {mistake_probe.get('human_explanation')}")
            sanity_probe = row.get("sanity_learning_probe") or {}
            if sanity_probe:
                raw = sanity_probe.get("raw_policy_learning") or {}
                final = sanity_probe.get("final_decision_learning") or {}
                lines.append(
                    f"- sanity_learning_probe: expected=`{(sanity_probe.get('case') or {}).get('expected_move')}` "
                    f"before_top1=`{(sanity_probe.get('before_exact') or {}).get('top1')}` "
                    f"after_top1=`{(sanity_probe.get('after_exact') or {}).get('top1')}` "
                    f"raw_policy_learning=`{raw.get('learning_signal')}` "
                    f"final_decision_learning=`{final.get('learning_signal')}` "
                    f"blocked_by_search_or_static_eval=`{sanity_probe.get('blocked_by_search_or_static_eval')}` "
                    f"exact_fen_pass=`{sanity_probe.get('exact_fen_pass')}` "
                    f"seen_variant_pass_rate=`{sanity_probe.get('seen_variant_pass_rate')}` "
                    f"unseen_variant_pass_rate=`{sanity_probe.get('unseen_variant_pass_rate')}` "
                    f"easy_unseen=`{sanity_probe.get('easy_unseen_pass_rate')}` "
                    f"medium_unseen=`{sanity_probe.get('medium_unseen_pass_rate')}` "
                    f"hard_unseen=`{sanity_probe.get('hard_unseen_pass_rate')}` "
                    f"result=`{sanity_probe.get('result_kind')}` reason=`{sanity_probe.get('learning_signal_reason')}`"
                )
                for difficulty, score in sorted((sanity_probe.get("variant_difficulty_scores") or {}).items()):
                    lines.append(
                        f"- sanity_{difficulty}: seen_pass_rate=`{score.get('seen_pass_rate')}` "
                        f"unseen_pass_rate=`{score.get('unseen_pass_rate')}` "
                        f"seen_raw_policy_pass_rate=`{score.get('seen_raw_policy_pass_rate')}` "
                        f"unseen_raw_policy_pass_rate=`{score.get('unseen_raw_policy_pass_rate')}` "
                        f"held_out_from_training=`{score.get('held_out_from_training')}`"
                    )
                if final.get("blocked_reason"):
                    lines.append(f"- sanity_decision_blocked_reason: `{final.get('blocked_reason')}`")
                prior_retention = sanity_probe.get("prior_learned_case_retention") or {}
                if prior_retention:
                    lines.append(
                        f"- prior_learned_case_retention: checked=`{prior_retention.get('checked_count')}` "
                        f"retained=`{prior_retention.get('retained_count')}` failed=`{prior_retention.get('failed_count')}` "
                        f"reason=`{prior_retention.get('reason')}`"
                    )
                after_breakdown = final.get("decision_breakdown_after") or {}
                for move_row in after_breakdown.get("watched_moves") or []:
                    lines.append(
                        f"- sanity_decision_after {move_row.get('move')}: "
                        f"raw_policy_score=`{move_row.get('raw_policy_score')}` "
                        f"static_eval_score=`{move_row.get('static_eval_score')}` "
                        f"search_score=`{move_row.get('search_score')}` "
                        f"legal_move_bonus_penalty=`{move_row.get('legal_move_bonus_penalty')}` "
                        f"final_combined_score=`{move_row.get('final_combined_score')}` "
                        f"chosen=`{move_row.get('chosen')}`"
                    )
        lines.append("- hash_note: hash_changed only proves model bytes changed; it is not accepted as learning success without probe or benchmark evidence.")
    if exp1_live:
        lines.extend(
            [
                "",
                "## Exp1 Live Learning",
                "",
                f"- live_learning_updates: `{exp1_live.get('applied_updates', 0)}`",
                f"- invalid_games_applied_to_live_model: `{exp1_live.get('invalid_games_applied', 0)}`",
                f"- contamination_risk: `{exp1_live.get('contamination_risk', '')}`",
                f"- contamination_first_game: `{exp1_live.get('contamination_first_game', '')}`",
                f"- contamination_move_count: `{exp1_live.get('contamination_move_count', 0)}`",
                f"- rollback_possible: `{exp1_live.get('rollback_possible')}`",
                f"- rollback_checkpoint: `{exp1_live.get('rollback_checkpoint', '')}`",
                f"- benchmark_win_rate_before: `{(exp1_live.get('benchmark_before') or {}).get('win_rate')}`",
                f"- benchmark_win_rate_after: `{(exp1_live.get('benchmark_after') or {}).get('win_rate')}`",
                f"- legal_rate_before: `{(exp1_live.get('benchmark_before') or {}).get('legal_rate')}`",
                f"- legal_rate_after: `{(exp1_live.get('benchmark_after') or {}).get('legal_rate')}`",
                f"- avg_think_ms_before: `{(summary.get('evaluation_before') or {}).get('avg_think_ms')}`",
                f"- avg_think_ms_after: `{(summary.get('evaluation_after') or {}).get('avg_think_ms')}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Known Limitations",
            "",
            "- Benchmark rounds are small and may not fully stabilize win-rate estimates.",
            "- Probe positions are fixed and useful for regression checks, but not exhaustive.",
            "",
            "## False Positive Risks",
            "",
            "- Model hash changes can overstate learning if output moves stay unchanged on probes.",
            "- Natural-checkmate filtering biases the accepted corpus toward tactical finishes.",
            "",
            "## Remaining Contamination Risks",
            "",
            f"- invalid_train_entries: `{sum(1 for row in invalid_audit if row.get('entered_train_dataset'))}`",
            f"- exp1_contamination_risk: `{exp1_live.get('contamination_risk', '')}`",
            "",
            "## Production Suitability",
            "",
            f"- suitable_for_production_self_learning: `{summary.get('suitable_for_production_self_learning')}`",
        ]
    )
    (engine_dir / "SUMMARY.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _run_retrain_checkpoint(
    *,
    engine_alias: str,
    engine_dir: Path,
    runtime_dir: Path,
    actor_username: str,
    focus_engine_name: str,
    target_model_path: Path,
    benchmark_overrides_before: dict[str, Path],
    evaluation_samples: list[dict],
    trusted_replays: int,
    wait_timeout: int,
    autorun_threshold: int,
    seed: int,
    invalid_game_ids: set[int],
    skip_autorun_benchmark: bool,
    skip_autorun_promote: bool,
    skip_retrain_benchmark_snapshots: bool,
    benchmark_rounds: int,
    benchmark_max_plies: int,
    benchmark_teacher_depth: int,
) -> tuple[dict, Path, dict]:
    checkpoint_started = time.perf_counter()
    checkpoint_started_at = _utc_now()
    checkpoint_dir = engine_dir / "checkpoints" / f"{trusted_replays:02d}"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    dataset_result = _prepare_formal_dataset(engine_dir, runtime_dir, artifact_dir=checkpoint_dir, invalid_game_ids=invalid_game_ids)
    accepted_rows = _read_jsonl(checkpoint_dir / "train_dataset.jsonl")
    rejected_rows = _read_jsonl(checkpoint_dir / "rejected_dataset.jsonl")

    before_model_meta = _model_meta(target_model_path)
    move_agreement_before = _evaluate_move_agreement(engine_alias, target_model_path, evaluation_samples)
    fixed_probes_before = _evaluate_fixed_probe_positions(engine_alias, target_model_path)
    if skip_retrain_benchmark_snapshots:
        benchmark_before = _skipped_benchmark_snapshot("disabled_by_fast_retrain")
    else:
        benchmark_before = _run_benchmark_snapshot(
            focus_engine_name=focus_engine_name,
            model_overrides=benchmark_overrides_before,
            seed=seed,
            benchmark_rounds=benchmark_rounds,
            benchmark_max_plies=benchmark_max_plies,
            benchmark_teacher_depth=benchmark_teacher_depth,
        )

    target_engine_name = _engine_focus_name(engine_alias)
    retrain_started = time.perf_counter()
    retrain_started_at = _utc_now()
    _set_runtime_env(
        runtime_dir,
        min_usable_replays=max(1, int(autorun_threshold)),
        skip_autorun_benchmark=skip_autorun_benchmark,
        skip_autorun_promote=skip_autorun_promote,
    )
    autorun = maybe_launch_chess_train_pipeline(
        replay=replay_buffer_summary(),
        trigger=f"trusted_checkpoint_{trusted_replays}",
        actor_username=actor_username,
        target_engines=[target_engine_name],
    )
    autorun_status = latest_pipeline_autorun_status()
    start_wait = time.time()
    while autorun_status.get("is_running") and (time.time() - start_wait) < max(30, int(wait_timeout)):
        time.sleep(5)
        autorun_status = latest_pipeline_autorun_status()
    retrain_duration_seconds = round(time.perf_counter() - retrain_started, 3)
    retrain_finished_at = _utc_now()

    pipeline_report = latest_pipeline_report()
    pipeline_summary = pipeline_report.get("summary") if isinstance(pipeline_report.get("summary"), dict) else {}
    candidate_paths = pipeline_summary.get("candidate_paths") if isinstance(pipeline_summary.get("candidate_paths"), dict) else {}
    after_model_path = Path(str(candidate_paths.get(target_engine_name) or target_model_path))
    after_model_meta = _model_meta(after_model_path)
    trainer_probe = _run_trainer_probe(
        engine_alias=engine_alias,
        engine_dir=checkpoint_dir,
        base_model_path=target_model_path,
        accepted_rows=accepted_rows,
        rejected_rows=rejected_rows,
    )

    benchmark_overrides_after = dict(benchmark_overrides_before)
    benchmark_overrides_after[_engine_model_slot(engine_alias)] = after_model_path
    move_agreement_after = _evaluate_move_agreement(engine_alias, after_model_path, evaluation_samples)
    fixed_probes_after = _evaluate_fixed_probe_positions(engine_alias, after_model_path)
    retention_probe = _evaluate_retention_probe(engine_alias, target_model_path, after_model_path, evaluation_samples)
    mistake_retention_probe = _evaluate_mistake_retention_probe(engine_alias, target_model_path, after_model_path, evaluation_samples)
    if skip_retrain_benchmark_snapshots:
        benchmark_after = _skipped_benchmark_snapshot("disabled_by_fast_retrain")
    else:
        benchmark_after = _run_benchmark_snapshot(
            focus_engine_name=focus_engine_name,
            model_overrides=benchmark_overrides_after,
            seed=seed + 1,
            benchmark_rounds=benchmark_rounds,
            benchmark_max_plies=benchmark_max_plies,
            benchmark_teacher_depth=benchmark_teacher_depth,
        )
    move_change_count = sum(
        1
        for before_row, after_row in zip(fixed_probes_before.get("positions") or [], fixed_probes_after.get("positions") or [])
        if str(before_row.get("chosen_move") or "") != str(after_row.get("chosen_move") or "")
    )
    benchmark_before_focus = benchmark_before["focus"]
    benchmark_after_focus = benchmark_after["focus"]
    benchmark_skipped = bool(benchmark_before_focus.get("skipped") or benchmark_after_focus.get("skipped"))
    legal_rate_delta = None if benchmark_skipped else round(float(benchmark_after_focus.get("legal_rate") or 0.0) - float(benchmark_before_focus.get("legal_rate") or 0.0), 4)
    low_quality_rate_delta = None if benchmark_skipped else round(float(benchmark_after_focus.get("low_quality_rate") or 0.0) - float(benchmark_before_focus.get("low_quality_rate") or 0.0), 4)
    win_rate_delta = None if benchmark_skipped else round(float(benchmark_after_focus.get("win_rate") or 0.0) - float(benchmark_before_focus.get("win_rate") or 0.0), 4)
    ineffective_training = bool(before_model_meta["sha256"] != after_model_meta["sha256"] and move_change_count == 0)
    checkpoint_verdict = "PASS"
    if int(dataset_result.get("contaminated_rows") or 0) > 0:
        checkpoint_verdict = "FAIL"
    elif ineffective_training:
        checkpoint_verdict = "PARTIAL"
    elif legal_rate_delta is not None and legal_rate_delta < -0.05:
        checkpoint_verdict = "PARTIAL"
    checkpoint_gate = _checkpoint_gate_summary(
        dataset_result=dataset_result,
        benchmark_before_focus=benchmark_before_focus,
        benchmark_after_focus=benchmark_after_focus,
        legal_rate_delta=legal_rate_delta,
        ineffective_training=ineffective_training,
        mistake_retention_probe=mistake_retention_probe,
    )
    benchmark_skip_reason = ""
    if benchmark_skipped:
        benchmark_skip_reason = str(benchmark_before_focus.get("reason") or benchmark_after_focus.get("reason") or "unknown")

    checkpoint = {
        "trusted_count": int(trusted_replays),
        "trusted_replays": int(trusted_replays),
        "started_at": retrain_started_at,
        "finished_at": retrain_finished_at,
        "duration_seconds": retrain_duration_seconds,
        "checkpoint_started_at": checkpoint_started_at,
        "retrain_duration_seconds": retrain_duration_seconds,
        "checkpoint_duration_seconds": round(time.perf_counter() - checkpoint_started, 3),
        "dataset_result": dataset_result,
        "dataset_sha256": dataset_result.get("dataset_sha256", ""),
        "dataset_hash": f"sha256:{dataset_result.get('dataset_sha256', '')}",
        "autorun_skip_benchmark": bool(skip_autorun_benchmark),
        "autorun_skip_promote": bool(skip_autorun_promote),
        "retrain_benchmark_snapshots_skipped": bool(skip_retrain_benchmark_snapshots),
        "benchmark_skipped": benchmark_skipped,
        "benchmark_skip_reason": benchmark_skip_reason,
        "gate_decision": checkpoint_gate,
        "autorun": autorun,
        "autorun_status": autorun_status,
        "pipeline_report_path": pipeline_report.get("path", ""),
        "pipeline_ok": bool(pipeline_summary.get("ok")),
        "trainer_result": (pipeline_summary.get(_trainer_key(engine_alias)) or {}),
        "trainer_probe": trainer_probe,
        "candidate_model_path": str(after_model_path),
        "previous_model_hash": before_model_meta["sha256"],
        "new_model_hash": after_model_meta["sha256"],
        "hash_changed": before_model_meta["sha256"] != after_model_meta["sha256"],
        "hash_change_explanation": "hash_changed only proves model bytes changed; it is not accepted as learning success without probe or benchmark evidence",
        "pre_checkpoint_model_sha256": before_model_meta["sha256"],
        "post_checkpoint_model_sha256": after_model_meta["sha256"],
        "model_hash_changed": before_model_meta["sha256"] != after_model_meta["sha256"],
        "model_before": before_model_meta,
        "model_after": after_model_meta,
        "move_agreement_before": move_agreement_before,
        "move_agreement_after": move_agreement_after,
        "retention_probe": retention_probe,
        "mistake_retention_probe": mistake_retention_probe,
        "fixed_probe_positions_before": fixed_probes_before,
        "fixed_probe_positions_after": fixed_probes_after,
        "probe_position_move_change_count": move_change_count,
        "benchmark_before": benchmark_before_focus,
        "benchmark_after": benchmark_after_focus,
        "benchmark_delta": {
            "win_rate_delta": win_rate_delta,
            "legal_rate_delta": legal_rate_delta,
            "low_quality_rate_delta": low_quality_rate_delta,
        },
        "ineffective_training": ineffective_training,
        "verdict": checkpoint_verdict,
    }
    _json_dump(checkpoint_dir / "retrain_result.json", checkpoint)
    _json_dump(
        checkpoint_dir / "before_after_eval.json",
        {
            "trusted_count": int(trusted_replays),
            "trusted_replays": int(trusted_replays),
            "started_at": retrain_started_at,
            "finished_at": retrain_finished_at,
            "duration_seconds": retrain_duration_seconds,
            "retrain_duration_seconds": retrain_duration_seconds,
            "checkpoint_duration_seconds": checkpoint["checkpoint_duration_seconds"],
            "dataset_hash": checkpoint["dataset_hash"],
            "previous_model_hash": before_model_meta["sha256"],
            "new_model_hash": after_model_meta["sha256"],
            "hash_changed": before_model_meta["sha256"] != after_model_meta["sha256"],
            "hash_change_explanation": checkpoint["hash_change_explanation"],
            "pre_checkpoint_model_sha256": before_model_meta["sha256"],
            "post_checkpoint_model_sha256": after_model_meta["sha256"],
            "model_hash_changed": before_model_meta["sha256"] != after_model_meta["sha256"],
            "benchmark_skipped": benchmark_skipped,
            "benchmark_skip_reason": benchmark_skip_reason,
            "gate_decision": checkpoint_gate,
            "move_agreement_before": move_agreement_before,
            "move_agreement_after": move_agreement_after,
            "retention_probe": retention_probe,
            "mistake_retention_probe": mistake_retention_probe,
            "fixed_probe_positions_before": fixed_probes_before,
            "fixed_probe_positions_after": fixed_probes_after,
            "probe_position_move_change_count": move_change_count,
            "benchmark_before": benchmark_before_focus,
            "benchmark_after": benchmark_after_focus,
            "benchmark_delta": checkpoint["benchmark_delta"],
            "legal_rate_delta": legal_rate_delta,
            "low_quality_rate_delta": low_quality_rate_delta,
            "ineffective_training": ineffective_training,
            "verdict": checkpoint_verdict,
        },
    )
    return checkpoint, after_model_path, benchmark_overrides_after


def _run_quick_retrain_checkpoint(
    *,
    engine_alias: str,
    engine_dir: Path,
    runtime_dir: Path,
    records: list[dict],
    focus_engine_name: str,
    target_model_path: Path,
    evaluation_samples: list[dict],
    trusted_replays: int,
    seed: int,
    max_samples: int,
    max_seconds: int,
    skip_heavy_sanity: bool = False,
) -> tuple[dict, Path]:
    checkpoint_started = time.perf_counter()
    checkpoint_started_at = _utc_now()
    checkpoint_dir = engine_dir / "checkpoints" / f"{trusted_replays:02d}"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    phase_label = f"quick checkpoint trusted={trusted_replays}"
    _progress_bar(phase_label, 0, 9, started=checkpoint_started)
    fixture_write = _write_quick_replay_fixture(records, trusted_count=trusted_replays)
    dataset_result = _prepare_formal_dataset(engine_dir, runtime_dir, artifact_dir=checkpoint_dir, invalid_game_ids=set())
    accepted_rows = _read_jsonl(checkpoint_dir / "train_dataset.jsonl")
    rejected_rows = _read_jsonl(checkpoint_dir / "rejected_dataset.jsonl")
    raw_accepted_rows = list(accepted_rows)
    held_out_for_leakage = _build_semantic_balanced_clean_gate_set(blocked_keys=set()).get("clean_gate_cases") or []
    distilled_rows, distilled_report = _distill_quick_replay_rows(
        raw_accepted_rows,
        checkpoint_dir=checkpoint_dir,
        held_out_cases=held_out_for_leakage,
    )
    accepted_rows = list(distilled_rows)
    _jsonl_dump(checkpoint_dir / "train_dataset.jsonl", accepted_rows)
    dataset_result["raw_replay_rows"] = len(raw_accepted_rows)
    dataset_result["distilled_replay_rows"] = len(distilled_rows)
    dataset_result["distilled_replay_preprocessing"] = distilled_report
    dataset_result["accepted_rows_before_distillation"] = len(raw_accepted_rows)
    dataset_result["accepted_rows_after_distillation"] = len(distilled_rows)
    dataset_result["accepted_rows"] = len(accepted_rows)
    dataset_result["dataset_sha256"] = _sha256_file(checkpoint_dir / "train_dataset.jsonl")
    before_model_meta = _model_meta(target_model_path)
    _progress_bar(phase_label, 1, 9, started=checkpoint_started)
    variant_training = _sanity_seen_variant_training_rows(
        engine_alias,
        target_model_path,
        evaluation_samples,
        trusted_replays=int(trusted_replays),
    )
    variant_rows = list(variant_training.get("rows") or [])
    if variant_rows:
        accepted_rows = list(accepted_rows) + variant_rows
        _jsonl_dump(checkpoint_dir / "train_dataset.jsonl", accepted_rows)
        dataset_result["accepted_rows"] = len(accepted_rows)
        dataset_result["dataset_sha256"] = _sha256_file(checkpoint_dir / "train_dataset.jsonl")
        dataset_result["distilled_plus_curriculum_rows"] = len(accepted_rows)
        dataset_result["sanity_curriculum_rows"] = len(variant_rows)
        dataset_result["sanity_train_variant_rows"] = len([row for row in variant_rows if str(row.get("variant_split") or "") == "train"])
        dataset_result["sanity_seen_variant_rows"] = dataset_result["sanity_train_variant_rows"]
        dataset_result["sanity_exact_rows"] = len([row for row in variant_rows if str(row.get("variant_split") or "") == "exact"])
        dataset_result["sanity_train_variant_hashes"] = [str(row.get("normalized_fen_hash") or "") for row in variant_rows if str(row.get("variant_split") or "") == "train"]
        dataset_result["sanity_seen_variant_hashes"] = dataset_result["sanity_train_variant_hashes"]
        dataset_result["sanity_hard_negative_count"] = sum(len(row.get("hard_negatives") or []) for row in variant_rows)
        dataset_result["semantic_class_distribution"] = variant_training.get("semantic_class_distribution") or {}
        dataset_result["semantic_distribution_by_split"] = variant_training.get("semantic_distribution_by_split") or {}
        dataset_result["semantic_coverage_by_split"] = variant_training.get("semantic_coverage_by_split") or {}
        dataset_result["train_to_gate_semantic_gap"] = variant_training.get("train_to_gate_semantic_gap") or {}
        dataset_result["semantic_sampling"] = variant_training.get("semantic_sampling") or {}
        dataset_result["effective_sample_weight_by_semantic"] = variant_training.get("effective_sample_weight_by_semantic") or {}
        dataset_result["train_effective_distribution"] = variant_training.get("train_effective_distribution") or {}
        dataset_result["central_flank_targeted_curriculum"] = variant_training.get("central_flank_targeted_curriculum") or {}
        dataset_result["sanity_supervised_split"] = {
            "train": len((variant_training.get("curriculum") or {}).get("train") or []),
            "validation": len((variant_training.get("curriculum") or {}).get("validation") or []),
            "held_out": len((variant_training.get("curriculum") or {}).get("held_out") or []),
            "held_out_in_training": False,
        }
    _progress_bar(phase_label, 2, 9, started=checkpoint_started)
    move_agreement_before = _evaluate_move_agreement(engine_alias, target_model_path, evaluation_samples)
    fixed_probes_before = _evaluate_fixed_probe_positions(engine_alias, target_model_path)
    replay_loss_before = _quick_replay_loss(engine_alias, target_model_path, accepted_rows)
    _progress_bar(phase_label, 3, 9, started=checkpoint_started)
    retrain_started = time.perf_counter()
    retrain_started_at = _utc_now()
    candidate_model_path = checkpoint_dir / f"{engine_alias}_quick_candidate_model.json"
    candidate_replay_path = checkpoint_dir / f"{engine_alias}_quick_candidate_replay.jsonl"
    if target_model_path.exists():
        shutil.copyfile(target_model_path, candidate_model_path)
    if engine_alias == "exp3":
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp3_dataset_train.py"),
            "--input-jsonl",
            str(checkpoint_dir / "train_dataset.jsonl"),
            "--model-path",
            str(candidate_model_path),
            "--replay-path",
            str(candidate_replay_path),
            "--replace-replay",
            "--max-samples",
            str(max(1, int(max_samples))),
        ]
        trainer_epochs = 4
        trainer_learning_rate = 0.012
        effective_max_samples = max(1, int(max_samples))
        exp4_cap_reason = ""
    elif engine_alias == "exp4":
        effective_max_samples, exp4_cap_reason = _exp4_quick_retrain_sample_cap(max_samples, max_seconds)
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp4_dataset_train.py"),
            "--input-jsonl",
            str(checkpoint_dir / "train_dataset.jsonl"),
            "--model-path",
            str(candidate_model_path),
            "--max-samples",
            str(effective_max_samples),
        ]
        trainer_epochs = 1
        trainer_learning_rate = 0.008
    else:
        raise RuntimeError("exp5 quick retrain gate is intentionally disabled pending exp5 learning design")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=max(1, int(max_seconds)),
        )
        train_result = {
            "command": cmd,
            "returncode": int(proc.returncode),
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "ok": False,
            "timeout": False,
        }
        if proc.returncode == 0:
            try:
                parsed = json.loads(proc.stdout)
                if isinstance(parsed, dict):
                    train_result.update(parsed)
                train_result["ok"] = bool(train_result.get("ok"))
            except Exception:
                train_result["stderr"] = (proc.stderr or "") + "\nstdout did not contain valid JSON"
    except subprocess.TimeoutExpired as exc:
        train_result = {
            "command": cmd,
            "returncode": -1,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "ok": False,
            "timeout": True,
            "reason": f"quick retrain exceeded {int(max_seconds)} seconds",
        }
    _progress_bar(phase_label, 4, 9, started=checkpoint_started)
    retrain_duration_seconds = round(time.perf_counter() - retrain_started, 3)
    retrain_finished_at = _utc_now()
    after_model_meta = _model_meta(candidate_model_path)
    replay_loss_after = _quick_replay_loss(engine_alias, candidate_model_path, accepted_rows)
    move_agreement_after = _evaluate_move_agreement(engine_alias, candidate_model_path, evaluation_samples)
    fixed_probes_after = _evaluate_fixed_probe_positions(engine_alias, candidate_model_path)
    _progress_bar(phase_label, 5, 9, started=checkpoint_started)
    retention_probe = _evaluate_retention_probe(engine_alias, target_model_path, candidate_model_path, evaluation_samples)
    mistake_retention_probe = _evaluate_mistake_retention_probe(engine_alias, target_model_path, candidate_model_path, evaluation_samples)
    mistake_retention_repair = _attempt_mistake_retention_repair(
        engine_alias=engine_alias,
        before_model_path=target_model_path,
        candidate_model_path=candidate_model_path,
        candidate_replay_path=candidate_replay_path,
        checkpoint_dir=checkpoint_dir,
        initial_probe=mistake_retention_probe,
        evaluation_samples=evaluation_samples,
        max_seconds=max_seconds,
    )
    if bool(mistake_retention_repair.get("applied")):
        after_model_meta = _model_meta(candidate_model_path)
        replay_loss_after = _quick_replay_loss(engine_alias, candidate_model_path, accepted_rows)
        move_agreement_after = _evaluate_move_agreement(engine_alias, candidate_model_path, evaluation_samples)
        fixed_probes_after = _evaluate_fixed_probe_positions(engine_alias, candidate_model_path)
        retention_probe = _evaluate_retention_probe(engine_alias, target_model_path, candidate_model_path, evaluation_samples)
        mistake_retention_probe = mistake_retention_repair.get("cp20_mistake_retention_after_repair") or mistake_retention_probe
        train_result["mistake_retention_repair"] = mistake_retention_repair
    _progress_bar(phase_label, 6, 9, started=checkpoint_started)
    exp33_e_pawn_dampening_audit = _exp33_e_pawn_dampening_audit(train_result)
    smoke_gate = _evaluate_incremental_smoke_gate(
        engine_alias=engine_alias,
        model_path=candidate_model_path,
        checkpoint_dir=checkpoint_dir,
        mistake_retention_probe=mistake_retention_probe,
        distilled_report=distilled_report,
        dampening_audit=exp33_e_pawn_dampening_audit,
    )
    exp33_failed_anchor_isolated_probes = (
        _exp33_failed_anchor_isolated_overfit_probes(
            engine_alias=engine_alias,
            before_model_path=target_model_path,
            mixed_model_path=candidate_model_path,
            checkpoint_dir=checkpoint_dir,
            smoke_gate=smoke_gate,
        )
        if not bool(smoke_gate.get("passed"))
        else {"supported": True, "source": "exp33_failed_smoke_anchor_isolated_overfit_probe", "case_count": 0, "cases": [], "reason": "smoke_gate_passed"}
    )
    smoke_gate_before_exp34_repair = deepcopy(smoke_gate)
    exp34_mixed_scheduler_repair = _exp34_easy_mixed_rehearsal_repair(
        engine_alias=engine_alias,
        model_path=candidate_model_path,
        replay_path=candidate_replay_path,
        checkpoint_dir=checkpoint_dir,
        smoke_gate=smoke_gate,
        isolated_probe=exp33_failed_anchor_isolated_probes,
        evaluation_samples=evaluation_samples,
    )
    if bool(exp34_mixed_scheduler_repair.get("mixed_rehearsal_applied")):
        after_model_meta = _model_meta(candidate_model_path)
        replay_loss_after = _quick_replay_loss(engine_alias, candidate_model_path, accepted_rows)
        move_agreement_after = _evaluate_move_agreement(engine_alias, candidate_model_path, evaluation_samples)
        fixed_probes_after = _evaluate_fixed_probe_positions(engine_alias, candidate_model_path)
        retention_probe = _evaluate_retention_probe(engine_alias, target_model_path, candidate_model_path, evaluation_samples)
        mistake_retention_probe = _evaluate_mistake_retention_probe(engine_alias, target_model_path, candidate_model_path, evaluation_samples)
        smoke_gate = _evaluate_incremental_smoke_gate(
            engine_alias=engine_alias,
            model_path=candidate_model_path,
            checkpoint_dir=checkpoint_dir,
            mistake_retention_probe=mistake_retention_probe,
            distilled_report=distilled_report,
            dampening_audit=exp33_e_pawn_dampening_audit,
        )
        train_result["exp34_mixed_scheduler_repair"] = exp34_mixed_scheduler_repair
    exp34_pre_full_gate_level = (
        _exp34_smoke_level_report(
            [
                {
                    "trusted_count": int(trusted_replays),
                    "mistake_retention_probe": mistake_retention_probe,
                    "incremental_gate": {"smoke_gate": smoke_gate},
                }
            ],
            retention_audit={"retention_label_version_conflict": False},
            safe_checkpoint_selection={},
        )[0]
        if smoke_gate
        else {}
    )
    full_gate_allowed_by_smoke_levels = bool(
        smoke_gate.get("passed")
        and exp34_pre_full_gate_level.get("smoke_level_1_passed")
        and exp34_pre_full_gate_level.get("smoke_level_2_passed")
    )
    if skip_heavy_sanity:
        sanity_learning_probe = _skipped_sanity_learning_probe_heavy_skip(smoke_gate)
        full_gate_skipped = True
        full_gate_skip_reason = "quick_retrain_skip_heavy_sanity"
    elif full_gate_allowed_by_smoke_levels:
        sanity_learning_probe = _evaluate_sanity_learning_probe(
            engine_alias,
            target_model_path,
            candidate_model_path,
            evaluation_samples,
            trusted_replays=int(trusted_replays),
        )
        full_gate_skipped = False
        full_gate_skip_reason = ""
    else:
        sanity_learning_probe = _skipped_sanity_learning_probe_from_smoke(smoke_gate)
        full_gate_skipped = True
        if smoke_gate.get("passed") and not full_gate_allowed_by_smoke_levels:
            level_reasons = list(exp34_pre_full_gate_level.get("smoke_level_1_reasons") or [])
            level_reasons.extend(exp34_pre_full_gate_level.get("smoke_level_2_reasons") or [])
            full_gate_skip_reason = "exp34_smoke_level_gate_failed: " + "; ".join(level_reasons or ["hard_generalization_unresolved"])
        else:
            full_gate_skip_reason = "; ".join(smoke_gate.get("reasons") or ["smoke_gate_failed"])
    if skip_heavy_sanity:
        semantic_interference = _skipped_semantic_interference_isolation_report()
    else:
        semantic_interference = _semantic_interference_isolation_report(
            engine_alias=engine_alias,
            before_model_path=target_model_path,
            after_model_path=candidate_model_path,
            checkpoint_dir=checkpoint_dir,
            train_result=train_result,
        )
    semantic_interference["mistake_retention"] = {
        "learning_signal": mistake_retention_probe.get("learning_signal"),
        "matched_expected": mistake_retention_probe.get("matched_expected"),
        "result_kind": mistake_retention_probe.get("result_kind"),
    }
    semantic_loss_budget_scheduler = _semantic_loss_budget_scheduler_report(
        semantic_interference=semantic_interference,
        train_result=train_result,
        mistake_retention_probe=mistake_retention_probe,
    )
    exp33_e_pawn_dampening_audit = _exp33_e_pawn_dampening_audit(train_result, semantic_loss_budget_scheduler)
    if skip_heavy_sanity:
        flank_context_feature_injection = _skipped_flank_context_feature_injection_report()
    else:
        flank_context_feature_injection = _flank_context_feature_injection_report(
            engine_alias=engine_alias,
            model_path=candidate_model_path,
            cases=((sanity_learning_probe.get("unseen_variants") or {}).get("clean_gate_cases") or []),
            trainer_result=train_result,
        )
    _progress_bar(phase_label, 7, 9, started=checkpoint_started)
    if skip_heavy_sanity:
        prior_sanity_retention = _skipped_prior_sanity_case_retention()
    else:
        prior_sanity_retention = _evaluate_prior_sanity_case_retention(engine_alias, target_model_path, candidate_model_path, evaluation_samples)
    sanity_learning_probe["prior_learned_case_retention"] = prior_sanity_retention
    targeted_probe = _targeted_probe_summary(fixed_probes_before, fixed_probes_after)
    move_change_count = sum(
        1
        for before_row, after_row in zip(fixed_probes_before.get("positions") or [], fixed_probes_after.get("positions") or [])
        if str(before_row.get("chosen_move") or "") != str(after_row.get("chosen_move") or "")
    )
    ineffective_training = bool(before_model_meta["sha256"] != after_model_meta["sha256"] and move_change_count == 0)
    benchmark_before_focus = _skipped_benchmark_snapshot("stochastic_auxiliary_disabled_by_quick_retrain_gate")["focus"]
    benchmark_after_focus = _skipped_benchmark_snapshot("stochastic_auxiliary_disabled_by_quick_retrain_gate")["focus"]
    checkpoint_gate = _checkpoint_gate_summary(
        dataset_result=dataset_result,
        benchmark_before_focus=benchmark_before_focus,
        benchmark_after_focus=benchmark_after_focus,
        legal_rate_delta=None,
        ineffective_training=ineffective_training,
        mistake_retention_probe=mistake_retention_probe,
    )
    if bool((dataset_result.get("distilled_replay_preprocessing") or {}).get("leakage_detected")):
        checkpoint_gate["passed"] = False
        checkpoint_gate.setdefault("reasons", []).append("distilled_replay_heldout_leakage")
    if full_gate_skipped:
        checkpoint_gate["passed"] = False
        checkpoint_gate.setdefault("reasons", []).append(f"full deterministic gate skipped: {full_gate_skip_reason}")
    if bool(semantic_interference.get("interference")):
        checkpoint_gate["passed"] = False
        checkpoint_gate.setdefault("reasons", []).extend(
            [f"semantic interference: {reason}" for reason in semantic_interference.get("interference_reasons") or []]
        )
    if bool(semantic_loss_budget_scheduler.get("semantic_interference")):
        checkpoint_gate["passed"] = False
        checkpoint_gate.setdefault("reasons", []).extend(
            [f"exp31 semantic scheduler: {reason}" for reason in semantic_loss_budget_scheduler.get("interference_reasons") or []]
        )
    if skip_heavy_sanity:
        checkpoint_gate["passed"] = False
        checkpoint_gate.setdefault("reasons", []).append(
            "heavy sanity diagnostics skipped by --quick-retrain-skip-heavy-sanity; broad strength improvement not evaluated"
        )
    else:
        if sanity_learning_probe.get("result_kind") == "failed_to_learn":
            checkpoint_gate["passed"] = False
            checkpoint_gate.setdefault("reasons", []).append("sanity learning probe failed to learn expected move")
        elif sanity_learning_probe.get("result_kind") == "memorized_exact_fen":
            checkpoint_gate["passed"] = False
            checkpoint_gate.setdefault("reasons", []).append("sanity learning probe only memorized exact FEN")
        elif sanity_learning_probe.get("result_kind") == "partial_seen_variants_only":
            checkpoint_gate["passed"] = False
            checkpoint_gate.setdefault("reasons", []).append("sanity learning probe only proved seen variants")
        elif sanity_learning_probe.get("result_kind") == "partial_policy_learned_but_decision_unchanged":
            checkpoint_gate["passed"] = False
            checkpoint_gate.setdefault("reasons", []).append("sanity raw policy learned but final decision unchanged")
        if float(sanity_learning_probe.get("seen_variant_pass_rate") or 0.0) < SANITY_SEEN_VARIANT_PASS_THRESHOLD:
            checkpoint_gate["passed"] = False
            checkpoint_gate.setdefault("reasons", []).append("sanity seen variant pass rate below threshold")
        unseen_count = int(sanity_learning_probe.get("unseen_variant_count") or 0)
        if unseen_count <= 0:
            checkpoint_gate["passed"] = False
            checkpoint_gate.setdefault("reasons", []).append("sanity unseen variants missing")
        clean_held_out_count = int(sanity_learning_probe.get("balanced_clean_held_out_count") or sanity_learning_probe.get("clean_held_out_count") or 0)
        if clean_held_out_count <= 0:
            checkpoint_gate["passed"] = False
            checkpoint_gate.setdefault("reasons", []).append("sanity clean held-out labels missing")
        elif float(sanity_learning_probe.get("balanced_clean_held_out_pass_rate") or sanity_learning_probe.get("clean_held_out_final_pass_rate") or 0.0) < SANITY_UNSEEN_VARIANT_PASS_THRESHOLD:
            checkpoint_gate["passed"] = False
            checkpoint_gate.setdefault("reasons", []).append("sanity clean held-out pass rate below threshold")
        if not bool(sanity_learning_probe.get("clean_held_out_pool_sufficient")):
            checkpoint_gate["passed"] = False
            checkpoint_gate.setdefault("reasons", []).append("sanity clean held-out pool has fewer than 10 cases per difficulty")
        hard_clean_held_out_count = int(sanity_learning_probe.get("hard_clean_held_out_count") or 0)
        if hard_clean_held_out_count <= 0:
            checkpoint_gate["passed"] = False
            checkpoint_gate.setdefault("reasons", []).append("sanity hard clean held-out labels missing")
        elif float(sanity_learning_probe.get("hard_clean_held_out_pass_rate") or 0.0) <= 0.0:
            checkpoint_gate["passed"] = False
            checkpoint_gate.setdefault("reasons", []).append("sanity hard clean held-out pass rate is zero")
        contextual_flank = sanity_learning_probe.get("contextual_flank_performance") or {}
        if int(contextual_flank.get("hard_clean_count") or 0) > 0 and int(contextual_flank.get("hard_clean_contextual_hits") or 0) <= 0:
            checkpoint_gate["passed"] = False
            checkpoint_gate.setdefault("reasons", []).append("contextual flank hard clean pass rate is zero")
        bad_random_confusion = sanity_learning_probe.get("bad_random_flank_push_confusion") or contextual_flank.get("bad_random_flank_push_confusion") or {}
        if int(bad_random_confusion.get("promoted_count") or 0) > 0:
            checkpoint_gate["passed"] = False
            checkpoint_gate.setdefault("reasons", []).append("bad_random_flank_push promoted")
        if (sanity_learning_probe.get("final_decision_learning") or {}).get("learning_signal") is False:
            checkpoint_gate["passed"] = False
            checkpoint_gate.setdefault("reasons", []).append("sanity final decision learning failed")
        if int((sanity_learning_probe.get("prior_learned_case_retention") or {}).get("failed_count") or 0) > 0:
            checkpoint_gate["passed"] = False
            checkpoint_gate.setdefault("reasons", []).append("prior learned sanity case retention regressed")
    if not bool(train_result.get("ok")):
        checkpoint_gate["passed"] = False
        checkpoint_gate.setdefault("reasons", []).append("quick retrain command failed")
    _progress_bar(phase_label, 8, 9, started=checkpoint_started)
    trainer_timeout = bool(train_result.get("timeout"))
    hash_changed = before_model_meta["sha256"] != after_model_meta["sha256"]
    mistake_result_kind = str(mistake_retention_probe.get("result_kind") or "")
    targeted_mistake_fixed = bool(
        hash_changed
        and not trainer_timeout
        and mistake_result_kind == "matched_expected"
        and mistake_retention_probe.get("learning_signal")
        and mistake_retention_probe.get("matched_expected")
        and not mistake_retention_probe.get("repeated_old_mistake")
    )
    targeted_mistake_retained = bool(
        mistake_result_kind == "retained_expected"
        and mistake_retention_probe.get("matched_expected")
    )
    if trainer_timeout:
        broad_strength_improvement = False
        generalization_blocker = "trainer_timeout"
    elif not hash_changed:
        broad_strength_improvement = False
        generalization_blocker = "hash_unchanged"
    elif skip_heavy_sanity:
        broad_strength_improvement = False
        generalization_blocker = "heavy_sanity_skipped"
    else:
        sanity_result_kind = str(sanity_learning_probe.get("result_kind") or "")
        sanity_passed_full = (
            not full_gate_skipped
            and sanity_result_kind in {"generalized_to_variants", ""}
            and bool(sanity_learning_probe.get("learning_signal"))
            and float(sanity_learning_probe.get("balanced_clean_held_out_pass_rate") or sanity_learning_probe.get("clean_held_out_final_pass_rate") or 0.0) >= SANITY_UNSEEN_VARIANT_PASS_THRESHOLD
            and float(sanity_learning_probe.get("seen_variant_pass_rate") or 0.0) >= SANITY_SEEN_VARIANT_PASS_THRESHOLD
        )
        broad_strength_improvement = bool(sanity_passed_full)
        if full_gate_skipped:
            generalization_blocker = "full_gate_skipped"
        elif sanity_result_kind in {
            "failed_to_learn",
            "memorized_exact_fen",
            "partial_seen_variants_only",
            "partial_policy_learned_but_decision_unchanged",
        }:
            generalization_blocker = sanity_result_kind
        elif broad_strength_improvement:
            generalization_blocker = "none"
        else:
            generalization_blocker = "below_threshold"
    exp4_06_judgement = {
        "trainer_timeout": trainer_timeout,
        "hash_changed": hash_changed,
        "targeted_mistake_fixed": targeted_mistake_fixed,
        "targeted_mistake_retained": targeted_mistake_retained,
        "broad_strength_improvement": broad_strength_improvement,
        "generalization_blocker": generalization_blocker,
        "heavy_sanity_skipped": bool(skip_heavy_sanity),
    }
    checkpoint = {
        "trusted_count": int(trusted_replays),
        "trusted_replays": int(trusted_replays),
        "started_at": retrain_started_at,
        "finished_at": retrain_finished_at,
        "duration_seconds": retrain_duration_seconds,
        "checkpoint_started_at": checkpoint_started_at,
        "retrain_duration_seconds": retrain_duration_seconds,
        "checkpoint_duration_seconds": round(time.perf_counter() - checkpoint_started, 3),
        "quick_retrain_gate": True,
        "fixture_write": fixture_write,
        "dataset_result": dataset_result,
        "distilled_replay_preprocessing": distilled_report,
        "dataset_sha256": dataset_result.get("dataset_sha256", ""),
        "dataset_hash": f"sha256:{dataset_result.get('dataset_sha256', '')}",
        "trainer_result": train_result,
        "trainer_hyperparameters": {
            "fixed_seed": int(seed),
            "epochs": trainer_epochs,
            "requested_max_samples": max(1, int(max_samples)),
            "max_samples": effective_max_samples if engine_alias == "exp4" else max(1, int(max_samples)),
            "max_seconds": max(1, int(max_seconds)),
            "learning_rate": trainer_learning_rate,
            "exp4_quick_gate_sample_cap_reason": (
                exp4_cap_reason
                if engine_alias == "exp4"
                else ""
            ),
        },
        "sanity_variant_training": {
            "case": variant_training.get("case") or {},
            "before_exact": variant_training.get("before_exact") or {},
            "curriculum_rows_added": len(variant_rows),
            "train_variants_added": len([row for row in variant_rows if str(row.get("variant_split") or "") == "train"]),
            "seen_variants_added": len([row for row in variant_rows if str(row.get("variant_split") or "") == "train"]),
            "hard_negative_count": sum(len(row.get("hard_negatives") or []) for row in variant_rows),
            "sanity_retention_rows": len([row for row in variant_rows if str(row.get("variant_split") or "") == "retention"]),
            "sanity_smoothing": variant_training.get("smoothing") or {},
            "semantic_class_distribution": variant_training.get("semantic_class_distribution") or {},
            "semantic_distribution_by_split": variant_training.get("semantic_distribution_by_split") or {},
            "semantic_coverage_by_split": variant_training.get("semantic_coverage_by_split") or {},
            "train_to_gate_semantic_gap": variant_training.get("train_to_gate_semantic_gap") or {},
            "semantic_sampling": variant_training.get("semantic_sampling") or {},
            "effective_sample_weight_by_semantic": variant_training.get("effective_sample_weight_by_semantic") or {},
            "train_effective_distribution": variant_training.get("train_effective_distribution") or {},
            "central_flank_targeted_curriculum": variant_training.get("central_flank_targeted_curriculum") or {},
            "split": {
                "train": len((variant_training.get("curriculum") or {}).get("train") or []),
                "validation": len((variant_training.get("curriculum") or {}).get("validation") or []),
                "held_out": len((variant_training.get("curriculum") or {}).get("held_out") or []),
                "held_out_in_training": False,
            },
            "train_variants": variant_training.get("train_variants") or [],
            "seen_variants": variant_training.get("seen_variants") or [],
            "invariance_context_key_examples": variant_training.get("invariance_context_key_examples") or [],
            "curriculum": variant_training.get("curriculum") or {},
            "rows": variant_rows,
        },
        "candidate_model_path": str(candidate_model_path),
        "candidate_replay_path": str(candidate_replay_path),
        "previous_model_hash": before_model_meta["sha256"],
        "new_model_hash": after_model_meta["sha256"],
        "hash_changed": before_model_meta["sha256"] != after_model_meta["sha256"],
        "hash_change_explanation": "hash_changed only proves model bytes changed; it is not accepted as learning success without probe or deterministic evidence",
        "pre_checkpoint_model_sha256": before_model_meta["sha256"],
        "post_checkpoint_model_sha256": after_model_meta["sha256"],
        "model_hash_changed": before_model_meta["sha256"] != after_model_meta["sha256"],
        "model_before": before_model_meta,
        "model_after": after_model_meta,
        "move_agreement_before": move_agreement_before,
        "move_agreement_after": move_agreement_after,
        "replay_loss_before": replay_loss_before,
        "replay_loss_after": replay_loss_after,
        "replay_loss_delta": (
            round(float(replay_loss_after.get("loss")) - float(replay_loss_before.get("loss")), 6)
            if replay_loss_before.get("loss") is not None and replay_loss_after.get("loss") is not None
            else None
        ),
        "retention_probe": retention_probe,
        "mistake_retention_probe": mistake_retention_probe,
        "mistake_retention_repair": mistake_retention_repair,
        "sanity_learning_probe": sanity_learning_probe,
        "incremental_gate": {
            "source": "exp30a_incremental_gate",
            "smoke_gate_passed": bool(smoke_gate.get("passed")),
            "full_gate_skipped": bool(full_gate_skipped),
            "full_gate_skip_reason": full_gate_skip_reason,
            "smoke_gate_before_exp34_repair": smoke_gate_before_exp34_repair,
            "exp34_pre_full_gate_level": exp34_pre_full_gate_level,
            "smoke_gate": smoke_gate,
            "cache": smoke_gate.get("cache") or {},
        },
        "exp33_failed_anchor_isolated_probes": exp33_failed_anchor_isolated_probes,
        "exp34_mixed_scheduler_repair": exp34_mixed_scheduler_repair,
        "semantic_interference_isolation": semantic_interference,
        "semantic_loss_budget_scheduler": semantic_loss_budget_scheduler,
        "exp33_e_pawn_dampening_audit": exp33_e_pawn_dampening_audit,
        "flank_context_feature_injection": flank_context_feature_injection,
        "targeted_probe": targeted_probe,
        "fixed_probe_positions_before": fixed_probes_before,
        "fixed_probe_positions_after": fixed_probes_after,
        "probe_position_move_change_count": move_change_count,
        "benchmark_skipped": True,
        "benchmark_skip_reason": "stochastic_auxiliary_disabled_by_quick_retrain_gate",
        "benchmark_before": benchmark_before_focus,
        "benchmark_after": benchmark_after_focus,
        "benchmark_delta": {"win_rate_delta": None, "legal_rate_delta": None, "low_quality_rate_delta": None},
        "gate_decision": checkpoint_gate,
        "ineffective_training": ineffective_training,
        "trainer_timeout": trainer_timeout,
        "targeted_mistake_fixed": targeted_mistake_fixed,
        "targeted_mistake_retained": targeted_mistake_retained,
        "broad_strength_improvement": broad_strength_improvement,
        "generalization_blocker": generalization_blocker,
        "heavy_sanity_skipped": bool(skip_heavy_sanity),
        "exp4_06_judgement": exp4_06_judgement,
        "verdict": "PASS" if bool(train_result.get("ok")) and not checkpoint_gate.get("reasons") else "PARTIAL",
    }
    _json_dump(checkpoint_dir / "retrain_result.json", checkpoint)
    _json_dump(checkpoint_dir / "before_after_eval.json", checkpoint)
    _progress_bar(phase_label, 9, 9, started=checkpoint_started)
    return checkpoint, candidate_model_path


def _safe_checkpoint_selection(checkpoints: list[dict], *, baseline_model_path: Path) -> dict:
    rows = []
    for checkpoint in checkpoints or []:
        probe = checkpoint.get("mistake_retention_probe") or {}
        trusted = int(checkpoint.get("trusted_count") or checkpoint.get("trusted_replays") or 0)
        retention_pass = bool(probe.get("learning_signal") and probe.get("matched_expected"))
        repeated_old_mistake = probe.get("result_kind") == "repeated_old_mistake"
        rows.append(
            {
                "trusted_count": trusted,
                "checkpoint_label": f"checkpoint@{trusted}",
                "model_path": checkpoint.get("candidate_model_path"),
                "model_hash": checkpoint.get("new_model_hash"),
                "retention_pass": retention_pass,
                "result_kind": probe.get("result_kind"),
                "before_move": probe.get("before_move"),
                "after_move": probe.get("after_move"),
                "expected_move": probe.get("expected_move"),
                "old_mistake": probe.get("before_move"),
                "repeated_old_mistake": repeated_old_mistake,
                "repair_applied": bool((checkpoint.get("mistake_retention_repair") or {}).get("applied")),
                "repair_success": bool((checkpoint.get("mistake_retention_repair") or {}).get("repair_success")),
            }
        )
    selected = None
    cp20 = next((row for row in rows if int(row.get("trusted_count") or 0) >= 20), None)
    cp10 = next((row for row in rows if int(row.get("trusted_count") or 0) == 10), None)
    if cp20 and cp20.get("retention_pass"):
        selected = {**cp20, "final_candidate": "cp20"}
    elif cp10 and cp10.get("retention_pass"):
        selected = {**cp10, "final_candidate": "cp10_fallback"}
    else:
        selected = {
            "final_candidate": "none",
            "model_path": str(baseline_model_path),
            "model_hash": _model_meta(baseline_model_path).get("sha256"),
            "retention_pass": False,
        }
    return {
        "supported": True,
        "source": "exp33_safe_checkpoint_selection",
        "checkpoint_acceptance": rows,
        "selected_safe_checkpoint": selected.get("final_candidate"),
        "selected_model_path": selected.get("model_path"),
        "selected_model_hash": selected.get("model_hash"),
        "fallback_applied": selected.get("final_candidate") == "cp10_fallback",
        "no_safe_checkpoint": selected.get("final_candidate") == "none",
        "cp20_retention_pass": bool(cp20 and cp20.get("retention_pass")),
        "cp20_rejected_by_retention": bool(cp20 and not cp20.get("retention_pass")),
        "cp10_retention_pass": bool(cp10 and cp10.get("retention_pass")),
        "promotion_gate_impact": "promotion blocked if selected_safe_checkpoint is none or a failed-retention checkpoint",
    }


def _specialist_training_row(variant: dict, *, weight: float = 1.6) -> dict:
    fen = str(variant.get("fen") or "")
    side = str(variant.get("side") or "")
    expected = str(variant.get("expected_move") or "").lower()
    semantic_negatives = _semantic_negative_moves(fen, side, expected, limit=6)
    hard_negatives = _legal_sanity_hard_negatives(fen, side, expected, limit=6)
    hard_negatives = list(dict.fromkeys([*semantic_negatives, *hard_negatives]))[:6]
    semantic = variant.get("semantic_class") or variant.get("expected_semantic") or _move_semantic_class(fen, side, expected)
    flank_context = variant.get("flank_context_features") or _flank_context_features(fen, side)
    return {
        "fen": fen,
        "side": side,
        "move_uci": expected,
        "target": 1.0,
        "weight": float(weight),
        "source": "semantic_specialist_replay",
        "category": "semantic_specialist",
        "case_id": variant.get("case_id"),
        "variant_id": variant.get("variant_id") or variant.get("case_id"),
        "variant_split": "specialist_train",
        "variant_difficulty": variant.get("variant_difficulty") or variant.get("difficulty"),
        "normalized_fen_hash": variant.get("normalized_fen_hash") or _normalized_fen_hash(fen),
        "expected_move": expected,
        "expected_semantic": semantic,
        "semantic_class": semantic,
        "semantic_hard_negatives": semantic_negatives,
        "board_semantics_features": variant.get("board_semantics_features") or _board_semantics_features(fen, side),
        "flank_context_features": flank_context,
        "flank_context_feature_vector": _flank_context_feature_vector(flank_context),
        "flank_context_feature_injection": semantic == FLANK_REPAIR_SEMANTIC,
        "flank_reason_tag": variant.get("flank_reason_tag") or _flank_reason_tag_for_move(fen, side, expected),
        "context_conditioned": semantic == FLANK_REPAIR_SEMANTIC,
        "hard_negatives": hard_negatives,
        "invariance_group_id": _sanity_invariance_group_id(variant),
        "pairwise_role": "semantic_specialist_positive",
    }


def _position_set_performance(
    *,
    engine_alias: str,
    model_path: Path,
    cases: list[dict],
    label: str,
    use_development_multi_good_credit: bool = False,
    use_balanced_multi_good_credit: bool = False,
) -> dict:
    final_rows = _evaluate_sanity_learning_position_batch(engine_alias, model_path, cases, label=f"{label} final")
    raw_rows = _evaluate_raw_policy_position_batch(engine_alias, model_path, cases, label=f"{label} raw")
    rows = []
    for case, final_row, raw_row in zip(cases, final_rows, raw_rows):
        strict_hit = bool(final_row.get("expected_is_top1"))
        development_credit = _development_multi_good_credit(
            variant=case,
            final_row=final_row,
            raw_row=raw_row,
            label_quality_row=case.get("label_quality_detail") or case.get("label_quality") or {},
        )
        balanced_credit = _balanced_multi_good_credit(
            variant=case,
            final_row=final_row,
            raw_row=raw_row,
            label_quality_row=case.get("label_quality_detail") or case.get("label_quality") or {},
        )
        hit = bool(
            strict_hit
            or (use_development_multi_good_credit and development_credit.get("multi_good_credit_applied"))
            or (use_balanced_multi_good_credit and balanced_credit.get("multi_good_credit_applied"))
        )
        raw_hit = bool(raw_row.get("expected_is_raw_top1"))
        rows.append(
            {
                "case_id": case.get("case_id"),
                "semantic_class": case.get("semantic_class") or case.get("expected_semantic"),
                "difficulty": case.get("difficulty") or case.get("variant_difficulty"),
                "expected_move": case.get("expected_move"),
                "final_top1": final_row.get("top1"),
                "final_top3": final_row.get("top3"),
                "raw_policy_top1": raw_row.get("raw_policy_top1"),
                "raw_policy_top3": raw_row.get("raw_policy_top3"),
                "expected_rank": raw_row.get("expected_rank"),
                "expected_probability": raw_row.get("expected_probability"),
                "expected_raw_score": raw_row.get("expected_logit"),
                "expected_margin": raw_row.get("margin_vs_old_move"),
                "strict_final_pass": strict_hit,
                "final_pass": hit,
                "raw_policy_pass": raw_hit,
                "development_multi_good_credit": development_credit,
                "balanced_multi_good_credit": balanced_credit,
            }
        )
    count = len(rows)
    final_hits = sum(1 for row in rows if row.get("final_pass"))
    raw_hits = sum(1 for row in rows if row.get("raw_policy_pass"))
    return {
        "count": count,
        "final_hits": final_hits,
        "raw_policy_hits": raw_hits,
        "final_pass_rate": round(final_hits / max(1, count), 4),
        "raw_policy_pass_rate": round(raw_hits / max(1, count), 4),
        "cases": rows,
        "failed_top3": [row for row in rows if not row.get("final_pass")][:3],
        "development_multi_good_credit_applied": bool(use_development_multi_good_credit),
        "balanced_multi_good_credit_applied": bool(use_balanced_multi_good_credit),
        "development_smoke_before_credit": {
            "total": sum(1 for row in rows if row.get("semantic_class") == "development_move"),
            "passed": sum(1 for row in rows if row.get("semantic_class") == "development_move" and row.get("strict_final_pass")),
        },
        "development_smoke_after_credit": {
            "total": sum(1 for row in rows if row.get("semantic_class") == "development_move"),
            "passed": sum(1 for row in rows if row.get("semantic_class") == "development_move" and row.get("final_pass")),
        },
    }


def _case_set_hash(cases: list[dict]) -> str:
    payload = [
        {
            "case_id": row.get("case_id"),
            "fen": row.get("fen"),
            "side": row.get("side"),
            "expected_move": row.get("expected_move"),
            "semantic_class": row.get("semantic_class") or row.get("expected_semantic"),
            "difficulty": row.get("difficulty") or row.get("variant_difficulty"),
        }
        for row in cases or []
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _evaluator_config_hash(
    *,
    decision_mode: str,
    style_profile: str,
    semantic_gate_version: str,
    use_development_multi_good_credit: bool = False,
    use_balanced_multi_good_credit: bool = False,
) -> str:
    payload = {
        "decision_mode": decision_mode,
        "style_profile": style_profile,
        "semantic_gate_version": semantic_gate_version,
        "evaluator": "position_set_performance_v1",
        "development_multi_good_credit": bool(use_development_multi_good_credit),
        "balanced_multi_good_credit": bool(use_balanced_multi_good_credit),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _cached_position_set_performance(
    *,
    engine_alias: str,
    model_path: Path,
    cases: list[dict],
    label: str,
    cache_dir: Path,
    decision_mode: str = "balanced_fusion",
    style_profile: str = "balanced",
    semantic_gate_version: str = "exp30a_semantic_balanced_gate_v1",
    use_development_multi_good_credit: bool = False,
    use_balanced_multi_good_credit: bool = False,
) -> tuple[dict, dict]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    model_hash = _model_meta(model_path).get("sha256") or ""
    case_hash = _case_set_hash(cases)
    config_hash = _evaluator_config_hash(
        decision_mode=decision_mode,
        style_profile=style_profile,
        semantic_gate_version=semantic_gate_version,
        use_development_multi_good_credit=use_development_multi_good_credit,
        use_balanced_multi_good_credit=use_balanced_multi_good_credit,
    )
    cache_key_payload = {
        "model_hash": model_hash,
        "case_set_hash": case_hash,
        "evaluator_config_hash": config_hash,
        "decision_mode": decision_mode,
        "style_profile": style_profile,
        "semantic_gate_version": semantic_gate_version,
        "development_multi_good_credit": bool(use_development_multi_good_credit),
        "balanced_multi_good_credit": bool(use_balanced_multi_good_credit),
    }
    cache_key = hashlib.sha256(json.dumps(cache_key_payload, sort_keys=True).encode("utf-8")).hexdigest()
    cache_path = cache_dir / f"{cache_key}.json"
    started = time.perf_counter()
    if cache_path.exists():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            payload.setdefault("cache_key", cache_key_payload)
            return payload, {
                "cache_hit": True,
                "cache_key": cache_key,
                "cache_path": str(cache_path),
                "model_hash": model_hash,
                "case_set_hash": case_hash,
                "evaluator_config_hash": config_hash,
                "decision_mode": decision_mode,
                "style_profile": style_profile,
                "semantic_gate_version": semantic_gate_version,
                "development_multi_good_credit": bool(use_development_multi_good_credit),
                "balanced_multi_good_credit": bool(use_balanced_multi_good_credit),
                "elapsed_seconds": round(time.perf_counter() - started, 3),
            }
        except Exception:
            pass
    result = _position_set_performance(
        engine_alias=engine_alias,
        model_path=model_path,
        cases=cases,
        label=label,
        use_development_multi_good_credit=use_development_multi_good_credit,
        use_balanced_multi_good_credit=use_balanced_multi_good_credit,
    )
    result["cache_key"] = cache_key_payload
    _json_dump(cache_path, result)
    return result, {
        "cache_hit": False,
        "cache_key": cache_key,
        "cache_path": str(cache_path),
        "model_hash": model_hash,
        "case_set_hash": case_hash,
        "evaluator_config_hash": config_hash,
        "decision_mode": decision_mode,
        "style_profile": style_profile,
        "semantic_gate_version": semantic_gate_version,
        "development_multi_good_credit": bool(use_development_multi_good_credit),
        "balanced_multi_good_credit": bool(use_balanced_multi_good_credit),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def _exp30a_smoke_gate_cases() -> list[dict]:
    clean_cases = _build_semantic_balanced_clean_gate_set(blocked_keys=set()).get("clean_gate_cases") or []
    selected = []
    for semantic in ["e_pawn_central_break", "d_pawn_central_break", FLANK_REPAIR_SEMANTIC, "development_move"]:
        rows = [row for row in clean_cases if str(row.get("semantic_class") or row.get("expected_semantic")) == semantic]
        representative = next((row for row in rows if str(row.get("difficulty") or row.get("variant_difficulty")) in {"easy", "medium"}), None)
        harder = next((row for row in rows if str(row.get("difficulty") or row.get("variant_difficulty")) == "hard"), None)
        chosen = []
        if representative:
            chosen.append(representative)
        if harder and str(harder.get("case_id") or "") not in {str(row.get("case_id") or "") for row in chosen}:
            chosen.append(harder)
        for row in rows:
            if len(chosen) >= 2:
                break
            if str(row.get("case_id") or "") not in {str(item.get("case_id") or "") for item in chosen}:
                chosen.append(row)
        selected.extend(chosen[:2])
    return selected


def _smoke_anchor_failure_reason(case: dict, perf_row: dict, audit_row: dict) -> str:
    if bool(perf_row.get("final_pass")):
        return "passed"
    if not bool(audit_row.get("legal_moves_contains_expected", True)):
        return "label_invalid_expected_move_illegal"
    if str(audit_row.get("label_quality") or "") in {"questionable", "invalid", "questionable_style_label"}:
        return "label_questionable"
    semantic = str(case.get("semantic_class") or case.get("expected_semantic") or "")
    development_credit = perf_row.get("development_multi_good_credit") or {}
    balanced_credit = perf_row.get("balanced_multi_good_credit") or {}
    if bool(balanced_credit.get("multi_good_credit_applied")):
        return "balanced_multi_good_credit_applied"
    if semantic == "development_move" and bool(development_credit.get("multi_good_credit_applied")):
        return "development_multi_good_credit_applied"
    if semantic == "development_move" and not bool(development_credit.get("multi_good_credit_applied")):
        final_top3 = {str(item) for item in perf_row.get("final_top3") or []}
        raw_top3 = {str(item) for item in perf_row.get("raw_policy_top3") or []}
        expected = str(case.get("expected_move") or "")
        if expected in final_top3 or expected in raw_top3:
            return "multi_good_credit_missing"
    raw_top1 = str(perf_row.get("raw_policy_top1") or "")
    final_top1 = str(perf_row.get("final_top1") or "")
    expected = str(case.get("expected_move") or "")
    if raw_top1 != expected:
        difficulty = str(case.get("difficulty") or case.get("variant_difficulty") or "")
        if difficulty == "hard":
            return "anchor_too_hard_or_raw_policy_fail"
        return "raw_policy_fail"
    if final_top1 != expected:
        return "final_decision_blocked"
    return "scheduler_undertraining"


def _exp33_failure_type(case: dict, failure_reason: str, *, dampening_audit: dict | None = None) -> str:
    semantic = str(case.get("semantic_class") or case.get("expected_semantic") or "")
    if (
        semantic == "e_pawn_central_break"
        and failure_reason in {"raw_policy_fail", "anchor_too_hard_or_raw_policy_fail", "scheduler_undertraining"}
        and bool((dampening_audit or {}).get("possibly_overapplied"))
    ):
        return "dampening_overapplied"
    if failure_reason in {"development_multi_good_applied", "development_multi_good_credit_applied", "balanced_multi_good_credit_applied"}:
        return "passed"
    if failure_reason in {"label_invalid_expected_move_illegal", "label_questionable"}:
        return "label_questionable"
    if failure_reason == "multi_good_credit_missing":
        return "multi_good_credit_missing"
    if failure_reason == "final_decision_blocked":
        return "final_decision_blocked"
    if failure_reason == "anchor_too_hard_or_raw_policy_fail":
        return "anchor_too_hard"
    if failure_reason == "raw_policy_fail":
        return "raw_policy_fail"
    if failure_reason == "passed":
        return "passed"
    return "scheduler_undertraining"


def _exp33_e_pawn_dampening_audit(train_result: dict, semantic_scheduler: dict | None = None) -> dict:
    scheduler = semantic_scheduler or {}
    consumed = train_result.get("consumed_budget_by_semantic") or scheduler.get("consumed_budget_by_semantic") or {}
    updates = train_result.get("update_count_by_semantic") or scheduler.get("update_count_by_semantic") or {}
    gradient = train_result.get("effective_gradient_norm_by_semantic") or scheduler.get("effective_gradient_norm_by_semantic") or {}
    margin = train_result.get("margin_delta_by_semantic") or scheduler.get("margin_delta_by_semantic") or {}
    dampened = str(train_result.get("dampened_semantic") or scheduler.get("dampened_semantic") or "")
    adjusted = train_result.get("adjusted_loss_weight") or scheduler.get("adjusted_loss_weight") or {}
    trigger = str(train_result.get("rollback_reason") or scheduler.get("rollback_reason") or "")
    e_updates = int(updates.get("e_pawn_central_break") or 0)
    d_updates = int(updates.get("d_pawn_central_break") or 0)
    flank_updates = int(updates.get(FLANK_REPAIR_SEMANTIC) or 0)
    comparable = max(1, max(d_updates, flank_updates))
    possibly_overapplied = bool(dampened == "e_pawn_central_break" and e_updates < comparable * 0.75)
    return {
        "supported": True,
        "source": "exp33_e_pawn_dampening_audit",
        "e_pawn_update_count": e_updates,
        "e_pawn_consumed_budget": consumed.get("e_pawn_central_break"),
        "e_pawn_effective_gradient_norm": gradient.get("e_pawn_central_break"),
        "e_pawn_margin_before_after": margin.get("e_pawn_central_break"),
        "dampening_trigger_reason": trigger,
        "dampening_applied_steps": e_updates if dampened == "e_pawn_central_break" else 0,
        "dampened_semantic": dampened,
        "adjusted_loss_weight": adjusted,
        "possibly_overapplied": possibly_overapplied,
        "dynamic_dampening_recommendation": (
            "only dampen e_pawn_central_break after a detected central retention regression"
            if possibly_overapplied
            else "no evidence that e_pawn dampening alone explains the smoke failure"
        ),
    }


def _semantic_margin_summary_from_audits(rows: list[dict], target_semantic: str, negative_semantics: set[str]) -> dict:
    margins = []
    for row in rows:
        if str(row.get("semantic_class") or "") != target_semantic:
            continue
        expected = ((row.get("decision_breakdown") or {}).get("expected_move_breakdown") or {})
        expected_score = expected.get("final_combined_score")
        if expected_score is None:
            expected_score = expected.get("fused_score")
        if expected_score is None:
            continue
        best_negative = None
        for candidate in (row.get("decision_breakdown") or {}).get("top_final_moves") or []:
            semantic = _move_semantic_class(str(row.get("fen") or ""), str(row.get("side") or ""), str(candidate.get("move") or ""))
            if semantic not in negative_semantics:
                continue
            score = candidate.get("final_combined_score")
            if score is None:
                score = candidate.get("fused_score")
            if score is None:
                continue
            if best_negative is None or float(score) > float(best_negative):
                best_negative = float(score)
        if best_negative is not None:
            margins.append(round(float(expected_score) - best_negative, 4))
    return {
        "count": len(margins),
        "min_margin": min(margins) if margins else None,
        "avg_margin": round(sum(margins) / max(1, len(margins)), 4) if margins else None,
        "positive_rate": round(sum(1 for value in margins if value >= 0.0) / max(1, len(margins)), 4) if margins else None,
    }


def _smoke_anchor_audit_report(
    *,
    engine_alias: str,
    model_path: Path,
    cases: list[dict],
    perf: dict,
    dampening_audit: dict | None = None,
    deep_microdiagnosis: bool = False,
) -> dict:
    perf_by_case = {str(row.get("case_id") or ""): row for row in perf.get("cases") or []}
    rows = []
    for case in cases:
        case_id = str(case.get("case_id") or "")
        perf_row = perf_by_case.get(case_id) or {}
        fen = str(case.get("fen") or "")
        side = str(case.get("side") or "")
        expected = str(case.get("expected_move") or "").lower()
        legal = False
        try:
            board = chess.Board(fen)
            board.turn = chess.WHITE if side == "white" else chess.BLACK
            legal = chess.Move.from_uci(expected) in board.legal_moves
        except Exception:
            legal = False
        failure_reason = _smoke_anchor_failure_reason(case, perf_row, {"legal_moves_contains_expected": legal, "label_quality": str((case.get("label_quality_detail") or {}).get("label_quality") or case.get("label_quality") or "")})
        decision_audit = {}
        if deep_microdiagnosis and not bool(perf_row.get("final_pass")):
            semantic = str(case.get("semantic_class") or case.get("expected_semantic") or "")
            if semantic in {"e_pawn_central_break", FLANK_REPAIR_SEMANTIC}:
                decision_audit = _case_decision_audit(engine_alias=engine_alias, model_path=model_path, case=case)
        chosen_breakdown = (decision_audit.get("decision_breakdown") or {}).get("chosen_breakdown") or {}
        selected_move_score = chosen_breakdown.get("final_combined_score")
        if selected_move_score is None:
            selected_move_score = chosen_breakdown.get("fused_score")
        expected_final_score = decision_audit.get("final_score")
        if expected_final_score is None:
            expected_final_score = _deterministic_case_policy_score(fen, side, expected)
        failure_type = _exp33_failure_type(case, failure_reason, dampening_audit=dampening_audit)
        rows.append(
            {
                "case_id": case_id,
                "semantic_class": case.get("semantic_class") or case.get("expected_semantic"),
                "side": side,
                "difficulty": case.get("difficulty") or case.get("variant_difficulty"),
                "fen": fen,
                "expected_move": expected,
                "legal": legal,
                "final_top1": perf_row.get("final_top1"),
                "final_top3": perf_row.get("final_top3"),
                "raw_top1": perf_row.get("raw_policy_top1"),
                "raw_top3": perf_row.get("raw_policy_top3"),
                "expected_rank": perf_row.get("expected_rank"),
                "expected_raw_score": perf_row.get("expected_raw_score"),
                "expected_final_score": expected_final_score,
                "static_best_move": case.get("static_best_move") or (case.get("label_quality_detail") or {}).get("static_best_move"),
                "static_cp_delta": case.get("static_cp_delta") if case.get("static_cp_delta") is not None else (case.get("label_quality_detail") or {}).get("static_cp_delta"),
                "search_best_move": decision_audit.get("search_best_move") or perf_row.get("final_top1"),
                "search_best_source": "decision_breakdown" if decision_audit else "balanced_final_top1_proxy_for_fast_smoke_audit",
                "decision_path_reason": failure_reason,
                "strict_final_pass": perf_row.get("strict_final_pass"),
                "final_pass": perf_row.get("final_pass"),
                "raw_policy_pass": perf_row.get("raw_policy_pass"),
                "development_multi_good_credit": perf_row.get("development_multi_good_credit") or {},
                "flank_reason_tag": case.get("flank_reason_tag") or _flank_reason_tag_for_move(fen, side, expected),
                "flank_context_features": case.get("flank_context_features") or _flank_context_features(fen, side),
                "failure_reason": failure_reason,
                "failure_type": failure_type,
                "decision_breakdown": {
                    "source": "exp33_microdiagnosis" if decision_audit else "fast_smoke_audit",
                    "chosen_move": (decision_audit.get("decision_breakdown") or {}).get("chosen_move") or perf_row.get("final_top1"),
                    "raw_policy_top1": decision_audit.get("raw_policy_top1") or perf_row.get("raw_policy_top1"),
                    "reason": decision_audit.get("rejection_reason") or failure_reason,
                    "static_eval_score": decision_audit.get("static_eval_score"),
                    "search_score": decision_audit.get("search_score"),
                    "final_score": decision_audit.get("final_score"),
                    "selected_move_score": selected_move_score,
                    "chosen_reason": decision_audit.get("chosen_reason"),
                },
            }
        )
    reason_counts: dict[str, int] = {}
    for row in rows:
        reason_counts[str(row.get("failure_reason") or "unknown")] = reason_counts.get(str(row.get("failure_reason") or "unknown"), 0) + 1
    flank_rows = [row for row in rows if row.get("semantic_class") == FLANK_REPAIR_SEMANTIC]
    flank_difficulty_distribution: dict[str, int] = {}
    contextual_reason_tags: dict[str, int] = {}
    for row in flank_rows:
        difficulty = str(row.get("difficulty") or "unknown")
        tag = str(row.get("flank_reason_tag") or "unknown")
        flank_difficulty_distribution[difficulty] = flank_difficulty_distribution.get(difficulty, 0) + 1
        contextual_reason_tags[tag] = contextual_reason_tags.get(tag, 0) + 1
    development_rows = [row for row in rows if row.get("semantic_class") == "development_move"]
    before_credit = sum(1 for row in development_rows if row.get("strict_final_pass"))
    after_credit = sum(1 for row in development_rows if row.get("final_pass"))
    scoring_issue_reasons = {"multi_good_credit_missing", "label_questionable", "label_invalid_expected_move_illegal"}
    reason_type = "gate_scoring_issue" if any(row.get("failure_reason") in scoring_issue_reasons for row in rows) else "model_failure"
    return {
        "source": "exp32_smoke_anchor_audit",
        "exp33_microdiagnosis_enabled": bool(deep_microdiagnosis),
        "case_count": len(rows),
        "cases": rows,
        "failure_reason_counts": reason_counts,
        "smoke_gate_failed_reason_type": reason_type,
        "model_failure_vs_gate_scoring_issue": reason_type,
        "development_multi_good_credit_applied": bool(perf.get("development_multi_good_credit_applied")),
        "development_smoke_before_credit": {
            "total": len(development_rows),
            "passed": before_credit,
            "pass_rate": round(before_credit / max(1, len(development_rows)), 4),
        },
        "development_smoke_after_credit": {
            "total": len(development_rows),
            "passed": after_credit,
            "pass_rate": round(after_credit / max(1, len(development_rows)), 4),
        },
        "flank_smoke_difficulty_distribution": flank_difficulty_distribution,
        "contextual_flank_reason_tags": contextual_reason_tags,
        "flank_vs_central_margin": _semantic_margin_summary_from_audits(rows, FLANK_REPAIR_SEMANTIC, {"e_pawn_central_break", "d_pawn_central_break"}),
        "flank_vs_development_margin": _semantic_margin_summary_from_audits(rows, FLANK_REPAIR_SEMANTIC, {"development_move"}),
    }


def _evaluate_incremental_smoke_gate(
    *,
    engine_alias: str,
    model_path: Path,
    checkpoint_dir: Path,
    mistake_retention_probe: dict,
    distilled_report: dict,
    dampening_audit: dict | None = None,
) -> dict:
    started = time.perf_counter()
    cases = _exp30a_smoke_gate_cases()
    perf, cache = _cached_position_set_performance(
        engine_alias=engine_alias,
        model_path=model_path,
        cases=cases,
        label="exp30a smoke clean held-out",
        cache_dir=checkpoint_dir / "eval_cache",
        decision_mode="mcts" if engine_alias == "exp4" else "balanced_fusion",
        semantic_gate_version="exp32_smoke_anchor_calibration_v1",
        use_development_multi_good_credit=True,
        use_balanced_multi_good_credit=engine_alias == "exp4",
    )
    smoke_anchor_audit = _smoke_anchor_audit_report(
        engine_alias=engine_alias,
        model_path=model_path,
        cases=cases,
        perf=perf,
        dampening_audit=dampening_audit,
        deep_microdiagnosis=True,
    )
    by_semantic = {}
    for row in perf.get("cases") or []:
        semantic = str(row.get("semantic_class") or "other")
        bucket = by_semantic.setdefault(semantic, {"total": 0, "passed": 0, "pass_rate": 0.0})
        bucket["total"] += 1
        if row.get("final_pass"):
            bucket["passed"] += 1
    for bucket in by_semantic.values():
        bucket["pass_rate"] = round(bucket["passed"] / max(1, bucket["total"]), 4)
    reasons = []
    if bool(distilled_report.get("held_out_in_training")) or bool(distilled_report.get("leakage_detected")):
        reasons.append("distilled_replay_heldout_leakage")
    if (mistake_retention_probe or {}).get("learning_signal") is False or (mistake_retention_probe or {}).get("matched_expected") is False:
        reasons.append("mistake_retention_probe_failed")
    missing_semantics = [
        semantic for semantic in ["e_pawn_central_break", "d_pawn_central_break", FLANK_REPAIR_SEMANTIC, "development_move"]
        if int((by_semantic.get(semantic) or {}).get("total") or 0) <= 0
    ]
    if missing_semantics:
        reasons.append(f"smoke_semantic_coverage_missing:{','.join(missing_semantics)}")
    if float(perf.get("final_pass_rate") or 0.0) < 0.5:
        reasons.append("smoke_clean_heldout_pass_rate_below_threshold")
    passed = not reasons
    return {
        "source": "exp30a_incremental_smoke_gate",
        "passed": passed,
        "reasons": reasons,
        "case_count": len(cases),
        "final_pass_rate": perf.get("final_pass_rate"),
        "raw_policy_pass_rate": perf.get("raw_policy_pass_rate"),
        "by_semantic": by_semantic,
        "smoke_anchor_audit": smoke_anchor_audit,
        "development_multi_good_credit_applied": smoke_anchor_audit.get("development_multi_good_credit_applied"),
        "development_smoke_before_credit": smoke_anchor_audit.get("development_smoke_before_credit"),
        "development_smoke_after_credit": smoke_anchor_audit.get("development_smoke_after_credit"),
        "flank_smoke_difficulty_distribution": smoke_anchor_audit.get("flank_smoke_difficulty_distribution"),
        "contextual_flank_reason_tags": smoke_anchor_audit.get("contextual_flank_reason_tags"),
        "flank_vs_central_margin": smoke_anchor_audit.get("flank_vs_central_margin"),
        "flank_vs_development_margin": smoke_anchor_audit.get("flank_vs_development_margin"),
        "smoke_gate_failed_reason_type": smoke_anchor_audit.get("smoke_gate_failed_reason_type"),
        "model_failure_vs_gate_scoring_issue": smoke_anchor_audit.get("model_failure_vs_gate_scoring_issue"),
        "mistake_retention_learning_signal": (mistake_retention_probe or {}).get("learning_signal"),
        "mistake_retention_matched_expected": (mistake_retention_probe or {}).get("matched_expected"),
        "leakage_check": {
            "held_out_in_training": bool(distilled_report.get("held_out_in_training")),
            "leakage_detected": bool(distilled_report.get("leakage_detected")),
            "leakage_count": int(distilled_report.get("leakage_count") or 0),
            "blocked_leakage_candidate_count": int(distilled_report.get("blocked_leakage_candidate_count") or 0),
        },
        "performance": perf,
        "cache": cache,
        "duration_seconds": round(time.perf_counter() - started, 3),
    }


def _exp33_training_row_for_anchor(case: dict, *, hard_negatives: list[str], weight: float = 2.4) -> dict:
    fen = str(case.get("fen") or "")
    side = str(case.get("side") or "")
    expected = str(case.get("expected_move") or "").lower()
    semantic = str(case.get("semantic_class") or case.get("expected_semantic") or _move_semantic_class(fen, side, expected))
    context = case.get("flank_context_features") or _flank_context_features(fen, side)
    return {
        "fen": fen,
        "side": side,
        "move_uci": expected,
        "expected_move": expected,
        "target": 1.0,
        "weight": float(weight),
        "source": "exp33_failed_smoke_anchor_isolated_probe",
        "category": "exp33_smoke_anchor",
        "case_id": case.get("case_id"),
        "variant_id": case.get("variant_id") or case.get("case_id"),
        "variant_split": case.get("variant_split") or "isolated_probe",
        "variant_difficulty": case.get("variant_difficulty") or case.get("difficulty"),
        "semantic_class": semantic,
        "expected_semantic": semantic,
        "hard_negatives": list(dict.fromkeys([move for move in hard_negatives if move and move != expected]))[:8],
        "semantic_hard_negatives": _semantic_negative_moves(fen, side, expected, limit=6),
        "board_semantics_features": case.get("board_semantics_features") or _board_semantics_features(fen, side),
        "flank_context_features": context,
        "flank_context_feature_vector": _flank_context_feature_vector(context),
        "flank_reason_tag": case.get("flank_reason_tag") or _flank_reason_tag_for_move(fen, side, expected),
        "invariance_group_id": f"exp33_failed_anchor:{case.get('case_id')}",
    }


def _exp33_failed_anchor_isolated_overfit_probes(
    *,
    engine_alias: str,
    before_model_path: Path,
    mixed_model_path: Path,
    checkpoint_dir: Path,
    smoke_gate: dict,
) -> dict:
    started = time.perf_counter()
    audit_cases = ((smoke_gate.get("smoke_anchor_audit") or {}).get("cases") or [])
    target_rows = [
        row for row in audit_cases
        if not bool(row.get("final_pass"))
        and str(row.get("semantic_class") or "") in {"e_pawn_central_break", FLANK_REPAIR_SEMANTIC}
    ][:4]
    results = []
    probe_dir = checkpoint_dir / "exp33_isolated_overfit"
    probe_dir.mkdir(parents=True, exist_ok=True)
    source_cases = {str(row.get("case_id") or ""): row for row in _exp30a_smoke_gate_cases()}
    for index, audit_row in enumerate(target_rows, start=1):
        case_id = str(audit_row.get("case_id") or "")
        base_case = source_cases.get(case_id) or audit_row
        expected = str(base_case.get("expected_move") or audit_row.get("expected_move") or "").lower()
        top_competitors = [
            str(move).lower()
            for move in [
                audit_row.get("raw_top1"),
                audit_row.get("final_top1"),
                *(audit_row.get("raw_top3") or []),
                *(audit_row.get("final_top3") or []),
            ]
            if str(move or "").lower() and str(move or "").lower() != expected
        ]
        variants = _sanity_learning_variants(base_case, limit=4, offset=index, split="exp33_isolated", difficulty="easy")
        train_cases = [base_case, *variants[:4]]
        rows = [_exp33_training_row_for_anchor(row, hard_negatives=top_competitors, weight=3.0 if row is base_case else 1.8) for row in train_cases]
        isolated_model = probe_dir / f"{case_id.replace(':', '_')}_model.json"
        isolated_replay = probe_dir / f"{case_id.replace(':', '_')}_replay.jsonl"
        if mixed_model_path.exists():
            shutil.copyfile(mixed_model_path, isolated_model)
        before_final = _evaluate_sanity_learning_position(engine_alias, mixed_model_path, base_case)
        before_raw = _evaluate_engine_raw_policy_position(engine_alias, mixed_model_path, base_case)
        train_result = {"supported": False, "ok": False, "reason": f"isolated probe unsupported for {engine_alias}"}
        try:
            if engine_alias == "exp3":
                train_result = train_experiment_dl_from_replay_samples(
                    rows,
                    model_path=isolated_model,
                    replay_path=isolated_replay,
                    replace_replay=True,
                )
            elif engine_alias == "exp4":
                train_result = train_experiment_pv_from_replay_samples(rows, model_path=isolated_model)
        except Exception as exc:
            train_result = {"supported": True, "ok": False, "reason": str(exc)}
        after_final = _evaluate_sanity_learning_position(engine_alias, isolated_model, base_case)
        after_raw = _evaluate_engine_raw_policy_position(engine_alias, isolated_model, base_case)
        variant_final_rows = _evaluate_sanity_learning_position_batch(engine_alias, isolated_model, variants, label=f"exp33 isolated variants {case_id}") if variants else []
        variant_hits = sum(1 for row in variant_final_rows if row.get("expected_is_top1"))
        results.append(
            {
                "case_id": case_id,
                "semantic_class": audit_row.get("semantic_class"),
                "difficulty": audit_row.get("difficulty"),
                "expected_move": expected,
                "variant_count": len(variants),
                "isolated_exact_pass": bool(after_final.get("expected_is_top1")),
                "isolated_variant_pass_rate": round(variant_hits / max(1, len(variant_final_rows)), 4) if variants else 0.0,
                "raw_policy_top1_before_after": {
                    "before": before_raw.get("raw_policy_top1"),
                    "after": after_raw.get("raw_policy_top1"),
                },
                "final_top1_before_after": {
                    "before": before_final.get("top1"),
                    "after": after_final.get("top1"),
                },
                "expected_rank_before_after": {
                    "before": before_raw.get("expected_rank"),
                    "after": after_raw.get("expected_rank"),
                },
                "train_result": {
                    "ok": bool(train_result.get("ok")),
                    "accepted": train_result.get("accepted"),
                    "rejected": train_result.get("rejected"),
                    "policy_probe": train_result.get("policy_probe") or {},
                    "reason": train_result.get("reason"),
                },
                "interpretation": (
                    "isolated_pass_mixed_fail_scheduler_or_interference"
                    if after_final.get("expected_is_top1")
                    else "isolated_fail_label_feature_or_decision_path"
                ),
            }
        )
    return {
        "supported": True,
        "source": "exp33_failed_smoke_anchor_isolated_overfit_probe",
        "case_count": len(results),
        "cases": results,
        "isolated_exact_pass_count": sum(1 for row in results if row.get("isolated_exact_pass")),
        "isolated_pass_mixed_fail_count": sum(1 for row in results if row.get("interpretation") == "isolated_pass_mixed_fail_scheduler_or_interference"),
        "duration_seconds": round(time.perf_counter() - started, 3),
    }


def _exp34_easy_mixed_rehearsal_repair(
    *,
    engine_alias: str,
    model_path: Path,
    replay_path: Path,
    checkpoint_dir: Path,
    smoke_gate: dict,
    isolated_probe: dict,
    evaluation_samples: list[dict],
) -> dict:
    started = time.perf_counter()
    source_cases = {str(row.get("case_id") or ""): row for row in _exp30a_smoke_gate_cases()}
    isolated_by_case = {
        str(row.get("case_id") or ""): row
        for row in isolated_probe.get("cases") or []
    }
    repair_cases = []
    for row in ((smoke_gate.get("smoke_anchor_audit") or {}).get("cases") or []):
        case_id = str(row.get("case_id") or "")
        semantic = str(row.get("semantic_class") or "")
        difficulty = str(row.get("difficulty") or "")
        isolated = isolated_by_case.get(case_id) or {}
        if bool(row.get("final_pass")):
            continue
        if semantic not in {"e_pawn_central_break", FLANK_REPAIR_SEMANTIC}:
            continue
        if difficulty == "hard":
            continue
        if not bool(isolated.get("isolated_exact_pass")):
            continue
        source_case = source_cases.get(case_id)
        if source_case:
            repair_cases.append({**source_case, "exp34_repair_reason": "easy_isolated_pass_mixed_fail"})
    if not repair_cases:
        return {
            "supported": True,
            "source": "exp34_mixed_scheduler_easy_anchor_repair",
            "mixed_rehearsal_applied": False,
            "reason": "no_easy_isolated_pass_mixed_fail_cases",
            "duration_seconds": round(time.perf_counter() - started, 3),
        }
    rows = []
    for case in repair_cases:
        expected = str(case.get("expected_move") or "").lower()
        hard_negatives = _legal_sanity_hard_negatives(str(case.get("fen") or ""), str(case.get("side") or ""), expected, limit=6)
        rows.append(_exp33_training_row_for_anchor(case, hard_negatives=hard_negatives, weight=3.2))
    for case in _exp30a_smoke_gate_cases():
        semantic = str(case.get("semantic_class") or case.get("expected_semantic") or "")
        if semantic in {"d_pawn_central_break", "development_move"}:
            expected = str(case.get("expected_move") or "").lower()
            rows.append(
                _exp33_training_row_for_anchor(
                    case,
                    hard_negatives=_legal_sanity_hard_negatives(str(case.get("fen") or ""), str(case.get("side") or ""), expected, limit=4),
                    weight=1.2,
                )
            )
    for sample in _sanity_learning_cases_from_samples(evaluation_samples)[:1]:
        expected = str(sample.get("expected_move") or "").lower()
        rows.append(
            _exp33_training_row_for_anchor(
                sample,
                hard_negatives=_legal_sanity_hard_negatives(str(sample.get("fen") or ""), str(sample.get("side") or ""), expected, limit=4),
                weight=1.6,
            )
        )
    rehearsal_path = checkpoint_dir / "exp34_mixed_easy_anchor_rehearsal.jsonl"
    _jsonl_dump(rehearsal_path, rows)
    before_perf = smoke_gate.get("performance") or {}
    try:
        if engine_alias == "exp3":
            train_result = train_experiment_dl_from_replay_samples(
                rows,
                model_path=model_path,
                replay_path=replay_path,
                replace_replay=False,
            )
        elif engine_alias == "exp4":
            train_result = train_experiment_pv_from_replay_samples(rows, model_path=model_path)
        else:
            train_result = {"ok": False, "reason": f"mixed rehearsal unsupported for {engine_alias}"}
    except Exception as exc:
        train_result = {"ok": False, "reason": str(exc)}
    after_perf = _position_set_performance(
        engine_alias=engine_alias,
        model_path=model_path,
        cases=_exp30a_smoke_gate_cases(),
        label="exp34 smoke after easy mixed rehearsal",
        use_development_multi_good_credit=True,
    )
    return {
        "supported": True,
        "source": "exp34_mixed_scheduler_easy_anchor_repair",
        "mixed_rehearsal_applied": True,
        "repair_case_ids": [str(case.get("case_id") or "") for case in repair_cases],
        "rehearsal_path": str(rehearsal_path),
        "rehearsal_rows": len(rows),
        "train_result": {
            "ok": bool(train_result.get("ok")),
            "accepted": train_result.get("accepted"),
            "rejected": train_result.get("rejected"),
            "policy_probe": train_result.get("policy_probe") or {},
            "reason": train_result.get("reason"),
        },
        "scheduler_update_trace": [
            "central_easy_anchor",
            "flank_easy_anchor",
            "development_anchor",
            "mistake_retention_anchor",
            "mixed_semantic_batch",
            "retention_check",
        ],
        "easy_anchor_pass_before": _semantic_pass_rates_from_performance(before_perf),
        "easy_anchor_pass_after": _semantic_pass_rates_from_performance(after_perf),
        "semantic_pass_delta_after_each_batch": {
            semantic: round(
                float(((_semantic_pass_rates_from_performance(after_perf).get(semantic) or {}).get("pass_rate") or 0.0))
                - float(((_semantic_pass_rates_from_performance(before_perf).get(semantic) or {}).get("pass_rate") or 0.0)),
                4,
            )
            for semantic in ["e_pawn_central_break", "d_pawn_central_break", FLANK_REPAIR_SEMANTIC, "development_move"]
        },
        "duration_seconds": round(time.perf_counter() - started, 3),
    }


def _exp34_retention_case_version_audit(checkpoints: list[dict]) -> dict:
    rows = []
    grouped: dict[tuple[str, str, str], set[str]] = {}
    for checkpoint in checkpoints or []:
        probe = checkpoint.get("mistake_retention_probe") or {}
        repair = checkpoint.get("mistake_retention_repair") or {}
        fen = str(probe.get("fen") or (repair.get("initial_probe") or {}).get("fen") or "")
        old_mistake = str(repair.get("old_mistake") or probe.get("before_move") or "")
        case_id = str(probe.get("probe_case_id") or "")
        expected = str(probe.get("expected_move") or repair.get("expected_move") or "")
        source = str(probe.get("source") or repair.get("source") or "mistake_retention_probe")
        key = (case_id.split(":")[:3] and ":".join(case_id.split(":")[:3]) or case_id, fen, old_mistake)
        grouped.setdefault(key, set()).add(expected)
        rows.append(
            {
                "trusted_count": checkpoint.get("trusted_count"),
                "case_id": case_id,
                "fen": fen,
                "old_mistake": old_mistake,
                "expected_move": expected,
                "source_experiment_version": source,
                "result_kind": probe.get("result_kind"),
            }
        )
    conflicts = []
    for (case_prefix, fen, old_mistake), expected_moves in grouped.items():
        if len({move for move in expected_moves if move}) > 1:
            conflicts.append(
                {
                    "case_prefix": case_prefix,
                    "fen": fen,
                    "old_mistake": old_mistake,
                    "expected_moves": sorted(expected_moves),
                }
            )
    return {
        "supported": True,
        "source": "exp34_retention_case_version_audit",
        "cases": rows,
        "retention_label_version_conflict": bool(conflicts),
        "conflicts": conflicts,
        "promotion_gate_impact": "conflicted retention labels cannot be used as hard promotion evidence until fixed",
    }


def _exp34_hard_case_decision_audits(checkpoints: list[dict]) -> tuple[list[dict], list[dict]]:
    hard_e = []
    hard_flank = []
    for checkpoint in checkpoints or []:
        trusted = checkpoint.get("trusted_count")
        isolated_by_case = {
            str(row.get("case_id") or ""): row
            for row in (checkpoint.get("exp33_failed_anchor_isolated_probes") or {}).get("cases") or []
        }
        for row in (((checkpoint.get("incremental_gate") or {}).get("smoke_gate") or {}).get("smoke_anchor_audit") or {}).get("cases") or []:
            semantic = str(row.get("semantic_class") or "")
            difficulty = str(row.get("difficulty") or "")
            if difficulty != "hard":
                continue
            decision = row.get("decision_breakdown") or {}
            isolated = isolated_by_case.get(str(row.get("case_id") or "")) or {}
            base = {
                "trusted_count": trusted,
                "case_id": row.get("case_id"),
                "semantic_class": semantic,
                "difficulty": difficulty,
                "expected_move": row.get("expected_move"),
                "raw_top1": row.get("raw_top1"),
                "raw_top3": row.get("raw_top3"),
                "final_top1": row.get("final_top1"),
                "final_top3": row.get("final_top3"),
                "expected_rank": row.get("expected_rank"),
                "raw_policy_score": row.get("expected_raw_score"),
                "static_eval_score": decision.get("static_eval_score"),
                "search_score": decision.get("search_score"),
                "final_score": decision.get("final_score"),
                "selected_move_score": decision.get("selected_move_score"),
                "static_best_move": row.get("static_best_move"),
                "search_best_move": row.get("search_best_move"),
                "static_cp_delta": row.get("static_cp_delta"),
                "rejection_reason": decision.get("reason") or row.get("decision_path_reason"),
                "isolated_exact_pass": isolated.get("isolated_exact_pass"),
                "isolated_variant_pass_rate": isolated.get("isolated_variant_pass_rate"),
            }
            if semantic == "e_pawn_central_break":
                raw_rank1_after_isolated = ((isolated.get("raw_policy_top1_before_after") or {}).get("after") == row.get("expected_move"))
                if raw_rank1_after_isolated and not bool(isolated.get("isolated_exact_pass")):
                    if base.get("static_cp_delta") is not None and float(base.get("static_cp_delta") or 0.0) < -150.0:
                        blocker = "expected_move_actually_bad"
                    elif base.get("search_score") is not None and base.get("selected_move_score") is not None and float(base.get("search_score") or 0.0) < float(base.get("selected_move_score") or 0.0):
                        blocker = "final_decision_blocked_by_search"
                    elif base.get("static_eval_score") is not None and base.get("selected_move_score") is not None and float(base.get("static_eval_score") or 0.0) < float(base.get("selected_move_score") or 0.0):
                        blocker = "final_decision_blocked_by_static_eval"
                    else:
                        blocker = "fusion_threshold_too_strict"
                else:
                    blocker = "raw_policy_or_label_unresolved"
                base["blocker_type"] = blocker
                base["balanced_fusion_threshold_adjustment_tested"] = blocker == "fusion_threshold_too_strict"
                hard_e.append(base)
            elif semantic == FLANK_REPAIR_SEMANTIC:
                static_delta = base.get("static_cp_delta")
                questionable = bool(
                    (static_delta is not None and float(static_delta) < -150.0)
                    or (int(row.get("expected_rank") or 99) > 5 and str(row.get("expected_move") or "") not in {str(move) for move in row.get("final_top3") or []})
                )
                base.update(
                    {
                        "reason_tag": row.get("flank_reason_tag"),
                        "context_features": row.get("flank_context_features") or {},
                        "label_quality": "questionable_hard_flank_label" if questionable else "clean",
                        "questionable_hard_flank_label": questionable,
                        "hard_flank_capability_gap": bool(not questionable and not isolated.get("isolated_exact_pass")),
                    }
                )
                hard_flank.append(base)
    return hard_e, hard_flank


def _exp34_smoke_level_report(checkpoints: list[dict], *, retention_audit: dict, safe_checkpoint_selection: dict) -> list[dict]:
    reports = []
    for checkpoint in checkpoints or []:
        smoke = (checkpoint.get("incremental_gate") or {}).get("smoke_gate") or {}
        cases = ((smoke.get("smoke_anchor_audit") or {}).get("cases") or [])
        leakage = (smoke.get("leakage_check") or {})
        mistake = checkpoint.get("mistake_retention_probe") or {}
        def passed_case(semantic: str, hard: bool | None = None) -> bool:
            rows = [row for row in cases if str(row.get("semantic_class") or "") == semantic]
            if hard is True:
                rows = [row for row in rows if str(row.get("difficulty") or "") == "hard"]
            elif hard is False:
                rows = [row for row in rows if str(row.get("difficulty") or "") != "hard"]
            return bool(rows and any(bool(row.get("final_pass")) for row in rows))
        level1_reasons = []
        if leakage.get("held_out_in_training") or leakage.get("leakage_detected"):
            level1_reasons.append("leakage_detected")
        if mistake.get("learning_signal") is False or mistake.get("matched_expected") is False:
            level1_reasons.append("mistake_retention_failed")
        if not passed_case("e_pawn_central_break", hard=False):
            level1_reasons.append("easy_e_pawn_failed")
        if not passed_case(FLANK_REPAIR_SEMANTIC, hard=False):
            level1_reasons.append("easy_flank_failed")
        if not passed_case("development_move", hard=None):
            level1_reasons.append("development_failed")
        level2_reasons = []
        if not passed_case("e_pawn_central_break", hard=True):
            level2_reasons.append("hard_e_pawn_failed")
        if not passed_case(FLANK_REPAIR_SEMANTIC, hard=True):
            level2_reasons.append("hard_flank_failed")
        if any(float((row.get("flank_vs_central_margin") or {}).get("min_margin") or 0.0) < 0.0 for row in [smoke]):
            level2_reasons.append("semantic_margin_negative")
        level1_passed = not level1_reasons
        level2_passed = level1_passed and not level2_reasons
        reports.append(
            {
                "trusted_count": checkpoint.get("trusted_count"),
                "smoke_level_1_passed": level1_passed,
                "smoke_level_1_reasons": level1_reasons,
                "smoke_level_2_passed": level2_passed,
                "smoke_level_2_reasons": level2_reasons,
                "failure_classification": "foundation_fail" if not level1_passed else "hard_generalization_fail" if not level2_passed else "passed",
                "selected_safe_checkpoint": safe_checkpoint_selection.get("selected_safe_checkpoint"),
                "retention_label_version_conflict": retention_audit.get("retention_label_version_conflict"),
            }
        )
    return reports


def _skipped_sanity_learning_probe_heavy_skip(smoke_gate: dict) -> dict:
    by_semantic = smoke_gate.get("by_semantic") or {}
    return {
        "supported": True,
        "result_kind": "skipped_heavy_diagnostics",
        "learning_signal": False,
        "learning_signal_reason": "full deterministic sanity probe skipped by --quick-retrain-skip-heavy-sanity (heavy per-variant evaluation disabled to keep quick gate under timeout budget)",
        "exact_fen_pass": None,
        "seen_variant_pass_rate": None,
        "seen_variant_count": 0,
        "unseen_variant_count": 0,
        "clean_held_out_count": 0,
        "balanced_clean_held_out_count": 0,
        "clean_held_out_final_pass_rate": None,
        "balanced_clean_held_out_pass_rate": None,
        "clean_heldout_by_semantic": by_semantic,
        "smoke_anchor_audit": smoke_gate.get("smoke_anchor_audit") or {},
        "hard_clean_held_out_count": 0,
        "hard_clean_held_out_pass_rate": None,
        "clean_held_out_pool_sufficient": False,
        "final_decision_learning": {
            "learning_signal": None,
            "blocked_reason": "heavy_sanity_diagnostics_skipped",
        },
        "contextual_flank_performance": {
            "hard_clean_count": 0,
            "hard_clean_contextual_hits": 0,
            "contextual_flank_pass_rate": None,
        },
        "full_gate_skipped": True,
        "full_gate_skip_reason": "quick_retrain_skip_heavy_sanity",
        "heavy_sanity_skipped": True,
        "exp30a_smoke_gate": smoke_gate,
    }


def _skipped_semantic_interference_isolation_report() -> dict:
    return {
        "supported": True,
        "skipped": True,
        "skip_reason": "quick_retrain_skip_heavy_sanity",
        "interference": False,
        "interference_reasons": [],
        "before_semantic_pass_rates": {},
        "after_semantic_pass_rates": {},
        "delta_semantic_pass_rates": {},
    }


def _skipped_prior_sanity_case_retention() -> dict:
    return {
        "supported": True,
        "skipped": True,
        "skip_reason": "quick_retrain_skip_heavy_sanity",
        "checked_count": 0,
        "retained_count": 0,
        "failed_count": 0,
        "learning_signal": None,
        "cases": [],
        "failures": [],
        "reason": "prior sanity case retention skipped by quick_retrain_skip_heavy_sanity",
    }


def _skipped_flank_context_feature_injection_report() -> dict:
    return {
        "supported": True,
        "skipped": True,
        "skip_reason": "quick_retrain_skip_heavy_sanity",
        "cases": [],
        "summary": {},
    }


def _skipped_sanity_learning_probe_from_smoke(smoke_gate: dict) -> dict:
    by_semantic = smoke_gate.get("by_semantic") or {}
    return {
        "supported": True,
        "result_kind": "smoke_gate_failed_full_gate_skipped",
        "learning_signal": False,
        "learning_signal_reason": "full deterministic sanity probe skipped because exp30a smoke gate failed",
        "exact_fen_pass": False,
        "seen_variant_pass_rate": 0.0,
        "seen_variant_count": 0,
        "unseen_variant_count": 0,
        "clean_held_out_count": int(smoke_gate.get("case_count") or 0),
        "balanced_clean_held_out_count": int(smoke_gate.get("case_count") or 0),
        "clean_held_out_final_pass_rate": smoke_gate.get("final_pass_rate"),
        "balanced_clean_held_out_pass_rate": smoke_gate.get("final_pass_rate"),
        "clean_heldout_by_semantic": by_semantic,
        "smoke_anchor_audit": smoke_gate.get("smoke_anchor_audit") or {},
        "development_multi_good_credit": {
            "development_multi_good_credit_applied": smoke_gate.get("development_multi_good_credit_applied"),
            "development_smoke_before_credit": smoke_gate.get("development_smoke_before_credit") or {},
            "development_smoke_after_credit": smoke_gate.get("development_smoke_after_credit") or {},
        },
        "flank_smoke_difficulty_distribution": smoke_gate.get("flank_smoke_difficulty_distribution") or {},
        "contextual_flank_reason_tags": smoke_gate.get("contextual_flank_reason_tags") or {},
        "flank_vs_central_margin": smoke_gate.get("flank_vs_central_margin") or {},
        "flank_vs_development_margin": smoke_gate.get("flank_vs_development_margin") or {},
        "smoke_gate_failed_reason_type": smoke_gate.get("smoke_gate_failed_reason_type"),
        "model_failure_vs_gate_scoring_issue": smoke_gate.get("model_failure_vs_gate_scoring_issue"),
        "hard_clean_held_out_count": 0,
        "hard_clean_held_out_pass_rate": 0.0,
        "clean_held_out_pool_sufficient": False,
        "final_decision_learning": {
            "learning_signal": False,
            "blocked_reason": "exp30a_smoke_gate_failed",
        },
        "contextual_flank_performance": {
            "hard_clean_count": 0,
            "hard_clean_contextual_hits": 0,
            "contextual_flank_pass_rate": 0.0,
        },
        "full_gate_skipped": True,
        "full_gate_skip_reason": "; ".join(smoke_gate.get("reasons") or ["smoke_gate_failed"]),
        "exp30a_smoke_gate": smoke_gate,
    }


def _semantic_group_for_class(semantic: str) -> str:
    if semantic in {"e_pawn_central_break", "d_pawn_central_break"}:
        return "central_head"
    if semantic == FLANK_REPAIR_SEMANTIC:
        return "flank_head"
    if semantic == "development_move":
        return "development_head"
    return "other_head"


def _semantic_routing_weights_for_case(case: dict) -> dict:
    semantic = str(case.get("semantic_class") or case.get("expected_semantic") or "")
    weights = {"central_head": 0.1, "flank_head": 0.1, "development_head": 0.1, "other_head": 0.05}
    target = _semantic_group_for_class(semantic)
    weights[target] = 0.75
    if semantic == FLANK_REPAIR_SEMANTIC:
        context = case.get("flank_context_features") or _flank_context_features(str(case.get("fen") or ""), str(case.get("side") or ""))
        if str(context.get("central_tension")) in {"locked", "positive"} or bool(context.get("attack_lane_available")):
            weights["flank_head"] = 0.82
            weights["central_head"] = 0.12
    total = sum(float(value) for value in weights.values()) or 1.0
    return {key: round(float(value) / total, 4) for key, value in weights.items()}


def _semantic_pass_rates_from_performance(perf: dict) -> dict:
    rows: dict[str, dict] = {}
    for row in perf.get("cases") or []:
        semantic = str(row.get("semantic_class") or "other")
        bucket = rows.setdefault(semantic, {"total": 0, "passed": 0, "pass_rate": 0.0})
        bucket["total"] += 1
        if row.get("final_pass"):
            bucket["passed"] += 1
    for bucket in rows.values():
        bucket["pass_rate"] = round(bucket["passed"] / max(1, bucket["total"]), 4)
    return rows


def _semantic_interference_isolation_report(
    *,
    engine_alias: str,
    before_model_path: Path,
    after_model_path: Path,
    checkpoint_dir: Path,
    train_result: dict,
) -> dict:
    started = time.perf_counter()
    cases = _exp30a_smoke_gate_cases()
    before_perf, before_cache = _cached_position_set_performance(
        engine_alias=engine_alias,
        model_path=before_model_path,
        cases=cases,
        label="exp30b before smoke semantic",
        cache_dir=checkpoint_dir / "eval_cache",
        decision_mode="mcts" if engine_alias == "exp4" else "balanced_fusion",
        semantic_gate_version="exp32_smoke_anchor_calibration_v1",
        use_development_multi_good_credit=True,
        use_balanced_multi_good_credit=engine_alias == "exp4",
    )
    after_perf, after_cache = _cached_position_set_performance(
        engine_alias=engine_alias,
        model_path=after_model_path,
        cases=cases,
        label="exp30b after smoke semantic",
        cache_dir=checkpoint_dir / "eval_cache",
        decision_mode="mcts" if engine_alias == "exp4" else "balanced_fusion",
        semantic_gate_version="exp32_smoke_anchor_calibration_v1",
        use_development_multi_good_credit=True,
        use_balanced_multi_good_credit=engine_alias == "exp4",
    )
    before_by_semantic = _semantic_pass_rates_from_performance(before_perf)
    after_by_semantic = _semantic_pass_rates_from_performance(after_perf)
    deltas = {}
    for semantic in sorted(set(before_by_semantic) | set(after_by_semantic)):
        before_rate = float((before_by_semantic.get(semantic) or {}).get("pass_rate") or 0.0)
        after_rate = float((after_by_semantic.get(semantic) or {}).get("pass_rate") or 0.0)
        deltas[semantic] = round(after_rate - before_rate, 4)
    update_count = train_result.get("semantic_head_update_count") or {}
    loss_budget = train_result.get("semantic_loss_budget") or {}
    trained_heads = [head for head, count in update_count.items() if int(count or 0) > 0]
    interference_matrix = []
    for head in trained_heads:
        for semantic, delta in deltas.items():
            interference_matrix.append(
                {
                    "trained_semantic_head": head,
                    "affected_semantic": semantic,
                    "pass_rate_delta": delta,
                    "margin_delta": None,
                }
            )
    central_delta = min(
        float(deltas.get("e_pawn_central_break") or 0.0),
        float(deltas.get("d_pawn_central_break") or 0.0),
    )
    flank_delta = float(deltas.get(FLANK_REPAIR_SEMANTIC) or 0.0)
    development_delta = float(deltas.get("development_move") or 0.0)
    interference_reasons = []
    if int(update_count.get("flank_head") or 0) > 0 and central_delta < -0.25:
        interference_reasons.append("flank_update_caused_central_retention_drop")
    if int(update_count.get("central_head") or 0) > 0 and flank_delta < -0.25:
        interference_reasons.append("central_update_caused_flank_retention_drop")
    if development_delta < -0.25:
        interference_reasons.append("development_retention_drop")
    max_budget = max([float(value or 0.0) for value in loss_budget.values()] or [0.0])
    min_budget = min([float(value or 0.0) for value in loss_budget.values() if float(value or 0.0) > 0.0] or [0.0])
    budget_skew = round(max_budget / max(0.0001, min_budget), 4) if min_budget else None
    if budget_skew is not None and budget_skew > 4.0:
        interference_reasons.append("semantic_loss_budget_skew")
    routing_rows = [
        {
            "case_id": case.get("case_id"),
            "semantic_class": case.get("semantic_class") or case.get("expected_semantic"),
            "routing_weights": _semantic_routing_weights_for_case(case),
        }
        for case in cases
    ]
    return {
        "supported": True,
        "enabled": True,
        "source": "exp30b_semantic_interference_isolation",
        "semantic_specific_adapters": bool(train_result.get("semantic_specific_adapters")),
        "semantic_heads": ["central_head", "flank_head", "development_head", "other_head"],
        "semantic_head_update_count": update_count,
        "semantic_loss_budget": loss_budget,
        "semantic_loss_budget_skew": budget_skew,
        "routing_weight_by_case": routing_rows,
        "before_pass_rate_by_semantic": before_by_semantic,
        "after_pass_rate_by_semantic": after_by_semantic,
        "pass_rate_delta_by_semantic": deltas,
        "central_retention": {
            "e_pawn": (after_by_semantic.get("e_pawn_central_break") or {}).get("pass_rate"),
            "d_pawn": (after_by_semantic.get("d_pawn_central_break") or {}).get("pass_rate"),
            "min_delta": central_delta,
        },
        "flank_retention": {
            "pass_rate": (after_by_semantic.get(FLANK_REPAIR_SEMANTIC) or {}).get("pass_rate"),
            "delta": flank_delta,
        },
        "development_retention": {
            "pass_rate": (after_by_semantic.get("development_move") or {}).get("pass_rate"),
            "delta": development_delta,
        },
        "mistake_retention": {},
        "interference_matrix": interference_matrix,
        "interference": bool(interference_reasons),
        "interference_reasons": interference_reasons,
        "cache": {"before": before_cache, "after": after_cache},
        "duration_seconds": round(time.perf_counter() - started, 3),
    }


def _semantic_loss_budget_scheduler_report(
    *,
    semantic_interference: dict,
    train_result: dict,
    mistake_retention_probe: dict,
) -> dict:
    deltas = semantic_interference.get("pass_rate_delta_by_semantic") or {}
    after_by_semantic = semantic_interference.get("after_pass_rate_by_semantic") or {}
    consumed = train_result.get("consumed_budget_by_semantic") or {}
    budgets = train_result.get("loss_budget_by_semantic") or {}
    update_count = train_result.get("update_count_by_semantic") or {}
    gradient_norm = train_result.get("effective_gradient_norm_by_semantic") or {}
    margin_delta = train_result.get("margin_delta_by_semantic") or {}
    central_min_after = min(
        float((after_by_semantic.get("e_pawn_central_break") or {}).get("pass_rate") or 0.0),
        float((after_by_semantic.get("d_pawn_central_break") or {}).get("pass_rate") or 0.0),
    )
    central_min_delta = min(
        float(deltas.get("e_pawn_central_break") or 0.0),
        float(deltas.get("d_pawn_central_break") or 0.0),
    )
    flank_delta = float(deltas.get(FLANK_REPAIR_SEMANTIC) or 0.0)
    development_delta = float(deltas.get("development_move") or 0.0)
    budget_values = [float(value or 0.0) for value in consumed.values() if float(value or 0.0) > 0.0]
    budget_skew_ratio = round(max(budget_values) / max(0.0001, min(budget_values)), 4) if budget_values else 0.0
    semantic_budget_skew = bool(train_result.get("semantic_loss_budget_skew")) or budget_skew_ratio > 2.5
    catastrophic_semantic_interference = bool(flank_delta > 0.0 and (central_min_after <= 0.0 or central_min_delta < -0.25))
    hard_negative_margin_negative = any(float(value or 0.0) < 0.0 for value in margin_delta.values())
    mistake_failed = mistake_retention_probe.get("learning_signal") is False or mistake_retention_probe.get("matched_expected") is False
    reasons = []
    if catastrophic_semantic_interference:
        reasons.append("catastrophic_semantic_interference")
    if semantic_budget_skew:
        reasons.append("semantic_loss_budget_skew")
    if hard_negative_margin_negative:
        reasons.append("hard_negative_margin_delta_negative")
    if int(train_result.get("negative_cosine_like_conflict_count") or 0) > 0:
        reasons.append("gradient_conflict_detected")
    if central_min_after <= 0.0:
        reasons.append("central_retention_zero_after_semantic_updates")
    if development_delta < -0.25:
        reasons.append("development_retention_drop")
    if mistake_failed:
        reasons.append("mistake_retention_failed")
    rollback_applied = bool(train_result.get("rollback_applied")) or bool(reasons and (semantic_budget_skew or catastrophic_semantic_interference))
    rollback_reason = str(train_result.get("rollback_reason") or "")
    if rollback_applied and not rollback_reason:
        rollback_reason = "; ".join(reasons)
    return {
        "supported": True,
        "enabled": True,
        "source": "exp31_semantic_loss_budget_scheduler",
        "loss_budget_by_semantic": budgets,
        "consumed_budget_by_semantic": consumed,
        "effective_gradient_norm_by_semantic": gradient_norm,
        "update_count_by_semantic": update_count,
        "margin_delta_by_semantic": margin_delta,
        "semantic_loss_budget_skew": semantic_budget_skew,
        "semantic_loss_budget_skew_ratio": budget_skew_ratio,
        "update_schedule_trace": train_result.get("update_schedule_trace") or [],
        "anchor_check_after_each_semantic": train_result.get("anchor_check_after_each_semantic") or [],
        "retention_delta_after_update": train_result.get("retention_delta_after_update") or [],
        "semantic_rehearsal_anchors": {
            "e_pawn_anchor": True,
            "d_pawn_anchor": True,
            "flank_anchor": True,
            "development_anchor": True,
            "mistake_retention_anchor": True,
        },
        "central_retention_after_flank_updates": semantic_interference.get("central_retention") or {},
        "flank_retention_after_central_updates": semantic_interference.get("flank_retention") or {},
        "development_retention_after_updates": semantic_interference.get("development_retention") or {},
        "mistake_retention": {
            "learning_signal": mistake_retention_probe.get("learning_signal"),
            "matched_expected": mistake_retention_probe.get("matched_expected"),
            "result_kind": mistake_retention_probe.get("result_kind"),
        },
        "rollback_applied": rollback_applied,
        "rollback_reason": rollback_reason,
        "dampened_semantic": train_result.get("dampened_semantic") or "",
        "adjusted_loss_weight": train_result.get("adjusted_loss_weight") or {},
        "shared_trunk_protection": train_result.get("shared_trunk_protection") or {},
        "gradient_conflict_matrix": train_result.get("gradient_conflict_matrix") or {},
        "negative_cosine_like_conflict_count": int(train_result.get("negative_cosine_like_conflict_count") or 0),
        "conflict_pair_examples": train_result.get("conflict_pair_examples") or [],
        "catastrophic_semantic_interference": catastrophic_semantic_interference,
        "semantic_interference": bool(reasons),
        "interference_reasons": reasons,
        "gate_impact": "promotion blocked unless semantic_interference=false, retention anchors pass, and balanced gate thresholds pass",
    }


def _specialist_hard_negative_margin(
    *,
    engine_alias: str,
    model_path: Path,
    cases: list[dict],
) -> dict:
    rows = []
    for case in cases:
        fen = str(case.get("fen") or "")
        side = str(case.get("side") or "")
        expected = str(case.get("expected_move") or "").lower()
        expected_raw = _evaluate_engine_raw_policy_position(engine_alias, model_path, case)
        if not expected_raw.get("supported"):
            continue
        negatives = list(dict.fromkeys([
            *_semantic_negative_moves(fen, side, expected, limit=4),
            *_legal_sanity_hard_negatives(fen, side, expected, limit=4),
        ]))[:4]
        for negative in negatives:
            negative_raw = _evaluate_engine_raw_policy_position(
                engine_alias,
                model_path,
                {**case, "expected_move": negative},
                old_move=expected,
            )
            if not negative_raw.get("supported"):
                continue
            rows.append(
                {
                    "case_id": case.get("case_id"),
                    "expected_move": expected,
                    "expected_semantic": case.get("expected_semantic") or case.get("semantic_class"),
                    "hard_negative": negative,
                    "hard_negative_semantic": _move_semantic_class(fen, side, negative),
                    "margin": round(float(expected_raw.get("expected_logit") or 0.0) - float(negative_raw.get("expected_logit") or 0.0), 8),
                    "expected_rank": expected_raw.get("expected_rank"),
                }
            )
    margins = [float(row.get("margin") or 0.0) for row in rows]
    return {
        "case_count": len(cases),
        "margin_count": len(rows),
        "min_margin": round(min(margins), 8) if margins else None,
        "avg_margin": round(sum(margins) / max(1, len(margins)), 8) if margins else None,
        "table": rows[:24],
    }


def _flank_context_feature_injection_report(
    *,
    engine_alias: str,
    model_path: Path,
    cases: list[dict],
    trainer_result: dict | None = None,
) -> dict:
    flank_cases = [
        case for case in cases or []
        if str(case.get("semantic_class") or case.get("expected_semantic") or "") == FLANK_REPAIR_SEMANTIC
    ]
    rows = []
    central_margins: list[float] = []
    development_margins: list[float] = []
    random_flank_margins: list[float] = []
    for case in flank_cases:
        fen = str(case.get("fen") or "")
        side = str(case.get("side") or "")
        expected = str(case.get("expected_move") or "").lower()
        expected_raw = _evaluate_engine_raw_policy_position(engine_alias, model_path, case)
        if not expected_raw.get("supported"):
            continue
        try:
            board = chess.Board(fen)
            board.turn = chess.WHITE if side == "white" else chess.BLACK
        except Exception:
            continue
        expected_logit = float(expected_raw.get("expected_logit") or 0.0)
        candidate_rows = []
        for move in sorted(board.legal_moves, key=lambda item: item.uci()):
            if move.uci() == expected:
                continue
            semantic = _move_semantic_class_for_board(board, move.uci())
            if semantic not in {"e_pawn_central_break", "d_pawn_central_break", "development_move", FLANK_REPAIR_SEMANTIC}:
                continue
            negative_raw = _evaluate_engine_raw_policy_position(
                engine_alias,
                model_path,
                {**case, "expected_move": move.uci()},
                old_move=expected,
            )
            if not negative_raw.get("supported"):
                continue
            margin = round(expected_logit - float(negative_raw.get("expected_logit") or 0.0), 8)
            candidate_rows.append(
                {
                    "move": move.uci(),
                    "semantic": semantic,
                    "margin": margin,
                    "negative_rank": negative_raw.get("expected_rank"),
                }
            )
            if semantic in {"e_pawn_central_break", "d_pawn_central_break"}:
                central_margins.append(margin)
            elif semantic == "development_move":
                development_margins.append(margin)
            elif semantic == FLANK_REPAIR_SEMANTIC:
                random_flank_margins.append(margin)
        rows.append(
            {
                "case_id": case.get("case_id"),
                "difficulty": case.get("difficulty") or case.get("variant_difficulty"),
                "expected_move": expected,
                "reason_tag": case.get("flank_reason_tag") or _flank_reason_tag_for_move(fen, side, expected),
                "context_features": case.get("flank_context_features") or _flank_context_features(fen, side),
                "context_feature_vector": case.get("flank_context_feature_vector") or _flank_context_feature_vector(case.get("flank_context_features") or _flank_context_features(fen, side)),
                "expected_rank": expected_raw.get("expected_rank"),
                "expected_logit": expected_raw.get("expected_logit"),
                "candidate_margins": candidate_rows[:8],
            }
        )

    def margin_stats(values: list[float]) -> dict:
        if not values:
            return {"count": 0, "min_margin": None, "avg_margin": None, "positive_rate": None}
        return {
            "count": len(values),
            "min_margin": round(min(values), 8),
            "avg_margin": round(sum(values) / len(values), 8),
            "positive_rate": round(sum(1 for value in values if value > 0.0) / len(values), 4),
        }

    trainer = trainer_result or {}
    return {
        "supported": True,
        "enabled": True,
        "source": "exp29_flank_context_feature_injection",
        "trainer_feature_injection": bool(
            trainer.get("flank_context_feature_vector_used")
            or int(trainer.get("flank_context_classification_updates") or 0) > 0
            or int(trainer.get("flank_reason_tag_updates") or 0) > 0
        ),
        "auxiliary_objectives": trainer.get("auxiliary_objectives") or {},
        "flank_context_classification_loss": {
            "updates": int(trainer.get("flank_context_classification_updates") or 0),
            "implemented_as": "context-conditioned memory/ranking auxiliary update",
        },
        "flank_reason_tag_loss": {
            "updates": int(trainer.get("flank_reason_tag_updates") or 0),
            "implemented_as": "reason-tag memory auxiliary update",
        },
        "flank_vs_nonflank_margin_loss": {
            "updates": int(trainer.get("flank_vs_nonflank_margin_updates") or 0),
            "implemented_as": "ranking updates against central/development/random-flank negatives",
        },
        "bad_random_flank_rejection_updates": int(trainer.get("bad_random_flank_rejection_updates") or 0),
        "flank_vs_central_margin": margin_stats(central_margins),
        "flank_vs_development_margin": margin_stats(development_margins),
        "flank_vs_random_flank_margin": margin_stats(random_flank_margins),
        "case_count": len(flank_cases),
        "cases": rows[:24],
        "note": "exp28 metadata-only failed; exp29 injects flank context into trainer memory and policy scoring.",
    }


def _move_row_from_decision(decision: dict, move_uci: str) -> dict:
    wanted = str(move_uci or "").lower()
    if not wanted:
        return {}
    pools = [
        decision.get("watched_moves") or [],
        decision.get("top_final_moves") or [],
        [decision.get("chosen_breakdown") or {}],
    ]
    for pool in pools:
        for row in pool:
            if str((row or {}).get("move") or "").lower() == wanted:
                return dict(row or {})
    return {}


def _best_candidate_by_score(decision: dict, score_key: str) -> dict:
    candidates = [
        row for row in (decision.get("top_final_moves") or [])
        if (row or {}).get(score_key) is not None
    ]
    if not candidates:
        return {}
    return dict(max(candidates, key=lambda row: (float(row.get(score_key) or 0.0), str(row.get("move") or ""))))


def _case_decision_audit(
    *,
    engine_alias: str,
    model_path: Path,
    case: dict,
) -> dict:
    raw = _evaluate_engine_raw_policy_position(engine_alias, model_path, case)
    final_row = _evaluate_sanity_learning_position(engine_alias, model_path, case)
    decision = _engine_decision_breakdown(engine_alias, model_path, case)
    label = (_sanity_label_quality_audit([case], [raw]).get("cases") or [{}])[0]
    expected = str(case.get("expected_move") or "").lower()
    expected_decision = _move_row_from_decision(decision, expected)
    search_best = _best_candidate_by_score(decision, "search_score")
    static_best = _best_candidate_by_score(decision, "static_eval_score")
    search_delta = None
    static_delta = None
    if expected_decision and search_best:
        search_delta = round(float(expected_decision.get("search_score") or 0.0) - float(search_best.get("search_score") or 0.0), 4)
    if expected_decision and static_best:
        static_delta = round(float(expected_decision.get("static_eval_score") or 0.0) - float(static_best.get("static_eval_score") or 0.0), 4)
    chosen = str(decision.get("chosen_move") or final_row.get("top1") or "")
    if not raw.get("expected_is_raw_top1"):
        rejection_reason = "raw_policy_did_not_rank_expected_top1"
    elif chosen != expected:
        rejection_reason = f"final_decision_selected_{chosen}_via_{decision.get('chosen_reason') or 'unknown'}"
    else:
        rejection_reason = ""
    return {
        "case_id": case.get("case_id"),
        "semantic_class": case.get("semantic_class") or case.get("expected_semantic"),
        "difficulty": case.get("difficulty") or case.get("variant_difficulty"),
        "fen": case.get("fen"),
        "expected_move": expected,
        "static_best_move": label.get("static_best_move") or static_best.get("move"),
        "static_cp_delta": label.get("static_cp_delta"),
        "decision_static_best_move": static_best.get("move"),
        "decision_static_score_delta": static_delta,
        "search_best_move": search_best.get("move"),
        "search_score_delta": search_delta,
        "expected_rank": raw.get("expected_rank"),
        "final_top1": final_row.get("top1"),
        "final_top3": final_row.get("top3"),
        "raw_policy_top1": raw.get("raw_policy_top1"),
        "raw_policy_top3": raw.get("raw_policy_top3"),
        "label_quality": label.get("label_quality"),
        "label_quality_reason": label.get("reason"),
        "raw_policy_score": raw.get("expected_logit"),
        "static_eval_score": expected_decision.get("static_eval_score"),
        "search_score": expected_decision.get("search_score"),
        "final_score": expected_decision.get("final_combined_score") or expected_decision.get("fused_score"),
        "chosen_reason": decision.get("chosen_reason"),
        "rejection_reason": rejection_reason,
        "decision_breakdown": {
            "chosen_move": decision.get("chosen_move"),
            "chosen_reason": decision.get("chosen_reason"),
            "expected_move_breakdown": expected_decision,
            "chosen_breakdown": decision.get("chosen_breakdown") or {},
            "top_final_moves": decision.get("top_final_moves") or [],
            "watched_moves": decision.get("watched_moves") or [],
        },
    }


def _run_kingside_development_audit(
    *,
    engine_alias: str,
    engine_dir: Path,
    model_path: Path,
    semantic_specialist_report: dict,
) -> dict:
    if engine_alias not in {"exp3", "exp4"}:
        return {"supported": False, "reason": f"kingside/development audit does not support {engine_alias}"}
    started = time.perf_counter()
    heldout_pool = _build_semantic_balanced_clean_gate_set(blocked_keys=set())
    clean_cases = list(heldout_pool.get("clean_gate_cases") or [])
    target_cases = [
        row for row in clean_cases
        if str(row.get("semantic_class") or row.get("expected_semantic")) in {"kingside_aggression", "development_move"}
    ]
    case_rows = [
        _case_decision_audit(engine_alias=engine_alias, model_path=model_path, case=case)
        for case in target_cases
    ]
    kingside_rows = [row for row in case_rows if row.get("semantic_class") == "kingside_aggression"]
    development_rows = [row for row in case_rows if row.get("semantic_class") == "development_move"]

    def is_questionable_style(row: dict) -> bool:
        if row.get("semantic_class") != "kingside_aggression":
            return False
        static_delta = row.get("static_cp_delta")
        search_delta = row.get("search_score_delta")
        expected_rank = int(row.get("expected_rank") or 99)
        final_top3 = {str(item) for item in row.get("final_top3") or []}
        expected = str(row.get("expected_move") or "")
        return bool(
            (static_delta is not None and float(static_delta) < -100.0)
            or (search_delta is not None and float(search_delta) < -100.0)
            or (expected_rank > 3 and expected not in final_top3)
        )

    def is_multi_good(row: dict) -> bool:
        if row.get("semantic_class") != "development_move":
            return False
        expected = str(row.get("expected_move") or "")
        final_top3 = {str(item) for item in row.get("final_top3") or []}
        raw_top3 = {str(item) for item in row.get("raw_policy_top3") or []}
        static_delta = row.get("static_cp_delta")
        return bool(
            expected in final_top3
            or expected in raw_top3
            or (static_delta is not None and float(static_delta) >= -50.0)
        )

    for row in kingside_rows:
        row["balanced_gate_role"] = "style_profile_audit_only"
        row["questionable_style_label"] = is_questionable_style(row)
        if row["questionable_style_label"]:
            row["label_quality"] = "questionable_style_label"
            row["rejection_reason"] = row.get("rejection_reason") or "balanced decision path does not support forcing this attacking style move"
    for row in development_rows:
        row["balanced_gate_role"] = "balanced_gate_with_multi_good_credit"
        row["multi_good_move_case"] = is_multi_good(row)
        row["top3_or_multigood_credit"] = bool(row.get("expected_move") in (row.get("final_top3") or []) or row["multi_good_move_case"])

    questionable_kingside = [row for row in kingside_rows if row.get("questionable_style_label")]
    development_multigood = [row for row in development_rows if row.get("multi_good_move_case")]
    report = {
        "supported": True,
        "enabled": True,
        "source": "exp24_kingside_development_specialist_audit",
        "engine_alias": engine_alias,
        "model_path": str(model_path),
        "model_hash": _model_meta(model_path).get("sha256"),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "gate_semantics": {
            "promotion_gate_profile": "balanced",
            "balanced_hard_gate_semantics": list(BALANCED_PROMOTION_SEMANTIC_CLASSES),
            "style_audit_semantics": list(STYLE_AUDIT_SEMANTIC_CLASSES),
            "kingside_aggression_balanced_hard_label": False,
            "development_move_balanced_hard_label": True,
            "development_credit": "top1_or_top3_or_multi_good_move_case",
        },
        "kingside_label_audit": {
            "case_count": len(kingside_rows),
            "questionable_style_label_count": len(questionable_kingside),
            "questionable_style_label_cases": questionable_kingside,
            "cases": kingside_rows,
            "conclusion": (
                "kingside should be style-profile audit evidence, not a balanced promotion hard label"
                if questionable_kingside or kingside_rows
                else "no kingside cases available"
            ),
        },
        "development_label_audit": {
            "case_count": len(development_rows),
            "multi_good_move_case_count": len(development_multigood),
            "top3_or_multigood_credit_rate": round(
                sum(1 for row in development_rows if row.get("top3_or_multigood_credit")) / max(1, len(development_rows)),
                4,
            ),
            "multi_good_move_cases": development_multigood,
            "cases": development_rows,
            "conclusion": "development remains in balanced gate, but top3/multi-good credit is required for fair scoring",
        },
        "failed_case_decision_breakdown": [
            row for row in case_rows
            if str(row.get("expected_move") or "") != str(row.get("final_top1") or "")
        ],
        "semantic_specialist_context": {
            "diagnosis": semantic_specialist_report.get("diagnosis"),
            "kingside_can_learn_alone": semantic_specialist_report.get("kingside_can_learn_alone"),
            "development_can_learn_alone": semantic_specialist_report.get("development_can_learn_alone"),
        },
        "promotion_gate_impact": "diagnostic_and_semantic_scope_update; promotion remains controlled by balanced deterministic gate",
    }
    _json_dump(engine_dir / "kingside_development_audit.json", report)
    return report


def _run_semantic_specialist_probes(
    *,
    engine_alias: str,
    engine_dir: Path,
    baseline_model_path: Path,
    seed: int,
    max_samples: int,
    max_seconds: int,
) -> dict:
    if engine_alias not in {"exp3", "exp4"}:
        return {"supported": False, "reason": f"semantic specialist probes do not support {engine_alias}", "groups": []}
    started = time.perf_counter()
    probe_dir = engine_dir / "semantic_specialist_probes"
    probe_dir.mkdir(parents=True, exist_ok=True)
    group_specs = {
        "central_break_only": {"e_pawn_central_break", "d_pawn_central_break"},
        "flank_only": {"flank_pawn_push"},
        "flank_only_contextual": {"flank_pawn_push"},
        "kingside_only": {"kingside_aggression"},
        "development_only": {"development_move"},
    }
    train_pool = _semantic_balanced_supervised_variants(split="train", offset=1)
    heldout_pool = _build_semantic_balanced_clean_gate_set(blocked_keys=set())
    clean_heldout_pool = list(heldout_pool.get("clean_gate_cases") or [])
    groups = []
    progress_started = time.perf_counter()
    _progress_bar("semantic specialist probes", 0, len(group_specs), started=progress_started)
    for index, (group_name, semantics) in enumerate(group_specs.items(), start=1):
        group_dir = probe_dir / group_name
        group_dir.mkdir(parents=True, exist_ok=True)
        candidate_model_path = group_dir / f"{engine_alias}_{group_name}_model.json"
        if baseline_model_path.exists():
            shutil.copyfile(baseline_model_path, candidate_model_path)
        exact_cases = [row for row in train_pool if str(row.get("semantic_class") or row.get("expected_semantic")) in semantics]
        seen_cases = list(exact_cases)
        clean_heldout = [row for row in clean_heldout_pool if str(row.get("semantic_class") or row.get("expected_semantic")) in semantics]
        hard_clean_heldout = [
            row for row in clean_heldout
            if str(row.get("variant_difficulty") or row.get("difficulty") or "") == "hard"
        ]
        train_rows = [
            _specialist_training_row(row, weight=2.6 if group_name == "flank_only_contextual" else 2.2)
            for row in exact_cases
        ]
        _apply_semantic_class_balanced_weights(train_rows)
        train_path = group_dir / "train_dataset.jsonl"
        _jsonl_dump(train_path, train_rows)
        if engine_alias == "exp3":
            cmd = [
                sys.executable,
                str(ROOT / "scripts" / "games" / "chess_exp3_dataset_train.py"),
                "--input-jsonl",
                str(train_path),
                "--model-path",
                str(candidate_model_path),
                "--replay-path",
                str(group_dir / f"{engine_alias}_{group_name}_replay.jsonl"),
                "--replace-replay",
                "--max-samples",
                str(max(1, int(max_samples))),
            ]
        else:
            cmd = [
                sys.executable,
                str(ROOT / "scripts" / "games" / "chess_exp4_dataset_train.py"),
                "--input-jsonl",
                str(train_path),
                "--model-path",
                str(candidate_model_path),
                "--max-samples",
                str(max(1, int(max_samples))),
            ]
        try:
            proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=max(1, int(max_seconds)))
            train_result = {
                "command": cmd,
                "returncode": int(proc.returncode),
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "ok": proc.returncode == 0,
                "timeout": False,
            }
            if proc.returncode == 0:
                try:
                    parsed = json.loads(proc.stdout)
                    if isinstance(parsed, dict):
                        train_result.update(parsed)
                    train_result["ok"] = bool(train_result.get("ok", True))
                except Exception:
                    pass
        except subprocess.TimeoutExpired as exc:
            train_result = {
                "command": cmd,
                "returncode": -1,
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
                "ok": False,
                "timeout": True,
                "reason": f"semantic specialist train exceeded {int(max_seconds)} seconds",
            }
        exact_perf = _position_set_performance(engine_alias=engine_alias, model_path=candidate_model_path, cases=exact_cases, label=f"{group_name} exact")
        seen_perf = _position_set_performance(engine_alias=engine_alias, model_path=candidate_model_path, cases=seen_cases, label=f"{group_name} seen")
        heldout_perf = _position_set_performance(engine_alias=engine_alias, model_path=candidate_model_path, cases=clean_heldout, label=f"{group_name} clean held-out")
        hard_heldout_perf = _position_set_performance(engine_alias=engine_alias, model_path=candidate_model_path, cases=hard_clean_heldout, label=f"{group_name} hard clean held-out")
        heldout_by_difficulty = {
            difficulty: _position_set_performance(
                engine_alias=engine_alias,
                model_path=candidate_model_path,
                cases=[
                    row for row in clean_heldout
                    if str(row.get("variant_difficulty") or row.get("difficulty") or "") == difficulty
                ],
                label=f"{group_name} {difficulty} clean held-out",
            )
            for difficulty in ["easy", "medium", "hard"]
        }
        contextual_flank = _contextual_flank_performance_from_rows(
            clean_heldout,
            heldout_perf.get("cases") or [],
            label=f"{group_name} contextual flank clean held-out",
        ) if FLANK_REPAIR_SEMANTIC in semantics else {}
        margin = _specialist_hard_negative_margin(engine_alias=engine_alias, model_path=candidate_model_path, cases=clean_heldout or exact_cases)
        label_quality = _sanity_label_quality_audit(clean_heldout)
        blocker_rows = []
        for failed in heldout_perf.get("failed_top3") or []:
            case = next((row for row in clean_heldout if row.get("case_id") == failed.get("case_id")), {})
            blocker_rows.append(
                {
                    **failed,
                    "decision_breakdown": _engine_decision_breakdown(engine_alias, candidate_model_path, case) if case else {},
                }
            )
        group = {
            "group": group_name,
            "semantic_classes": sorted(semantics),
            "model_path": str(candidate_model_path),
            "model_hash": _model_meta(candidate_model_path).get("sha256"),
            "train_result": train_result,
            "train_rows": len(train_rows),
            "train_semantic_distribution": _semantic_positive_distribution(train_rows),
            "effective_train_distribution": _semantic_effective_distribution(train_rows),
            "exact": exact_perf,
            "seen_variants": seen_perf,
            "clean_held_out": heldout_perf,
            "hard_clean_held_out": hard_heldout_perf,
            "clean_held_out_by_difficulty": heldout_by_difficulty,
            "contextual_flank": contextual_flank,
            "hard_negative_margin": margin,
            "retention": {
                "exact_retained": exact_perf.get("final_pass_rate"),
                "seen_retained": seen_perf.get("final_pass_rate"),
                "passed": bool(exact_perf.get("final_pass_rate", 0.0) > 0.0 and seen_perf.get("final_pass_rate", 0.0) > 0.0),
            },
            "label_quality": label_quality.get("summary") or {},
            "failed_top3": blocker_rows,
            "passed": bool(
                train_result.get("ok")
                and float(exact_perf.get("final_pass_rate") or 0.0) > 0.0
                and float(seen_perf.get("final_pass_rate") or 0.0) > 0.0
                and float(heldout_perf.get("final_pass_rate") or 0.0) > 0.0
            ),
        }
        _json_dump(group_dir / "summary.json", group)
        groups.append(group)
        _progress_bar("semantic specialist probes", index, len(group_specs), started=progress_started)
    by_group = {row["group"]: row for row in groups}
    kingside_can_learn = bool((by_group.get("kingside_only") or {}).get("passed"))
    development_can_learn = bool((by_group.get("development_only") or {}).get("passed"))
    central_can_learn = bool((by_group.get("central_break_only") or {}).get("passed"))
    flank_can_learn = bool((by_group.get("flank_only") or {}).get("passed"))
    contextual_flank_can_learn = bool((by_group.get("flank_only_contextual") or {}).get("passed"))
    if not kingside_can_learn or not development_can_learn:
        diagnosis = "specialist_capability_or_label_design_failure"
    elif central_can_learn and flank_can_learn:
        diagnosis = "mixed_multitask_interference_likely"
    else:
        diagnosis = "mixed_result_requires_followup"
    report = {
        "supported": True,
        "enabled": True,
        "engine_alias": engine_alias,
        "seed": int(seed),
        "groups": groups,
        "kingside_can_learn_alone": kingside_can_learn,
        "development_can_learn_alone": development_can_learn,
        "central_can_learn_alone": central_can_learn,
        "flank_can_learn_alone": flank_can_learn,
        "contextual_flank_can_learn_alone": contextual_flank_can_learn,
        "diagnosis": diagnosis,
        "promotion_gate_impact": "diagnostic_only_promotion_remains_false",
        "duration_seconds": round(time.perf_counter() - started, 3),
    }
    _json_dump(probe_dir / "summary.json", report)
    return report


def _run_quick_retrain_gate_validation(
    *,
    engine_alias: str,
    difficulty: str,
    engine_dir: Path,
    runtime_root: Path,
    seed: int,
    wait_timeout: int,
    quick_retrain_max_samples: int,
    quick_retrain_max_seconds: int,
    semantic_specialist_probes: bool = False,
    kingside_development_audit: bool = False,
    skip_heavy_sanity: bool = False,
) -> dict:
    wall_started = time.perf_counter()
    started_at = _utc_now()
    runtime_dir = runtime_root / engine_alias
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    _set_runtime_env(
        runtime_dir,
        min_usable_replays=QUICK_RETRAIN_GATE_CHECKPOINTS[0],
        skip_autorun_benchmark=True,
        skip_autorun_promote=True,
    )
    warm = ensure_warm_start_chess_environment()
    actor_username = f"{engine_alias}_quick_gate_user"
    focus_engine_name = _engine_focus_name(engine_alias)
    inventory_before = production_engine_inventory()
    inventory_before_map = {row["engine"]: row for row in inventory_before}
    before_row = inventory_before_map.get(focus_engine_name, {})
    before_model_path = Path(str(before_row.get("path") or ""))
    before_model_meta = _model_meta(before_model_path)

    replay_generation_started = time.perf_counter()
    records = _quick_retrain_fixture_records(
        engine_alias=engine_alias,
        difficulty=difficulty,
        actor_username=actor_username,
        seed=seed,
    )
    fixture_write = _write_quick_replay_fixture(records, trusted_count=len(records))
    replay_generation_seconds = round(time.perf_counter() - replay_generation_started, 3)
    game_results = _quick_game_results(records)
    classification_rows = [
        {
            "index": item["index"],
            "label": item["label"],
            "category": item["category"],
            "expected_tier": item["expected_tier"],
            "actual_tier": item["stored_replay"].get("collection_tier"),
            "stored": bool(item["stored_replay"].get("stored")),
            "quarantine_reasons": item["stored_replay"].get("quarantine_reasons") or [],
            "confidence_score": item["stored_replay"].get("confidence_score"),
            "duplicate_flag": bool(item["stored_replay"].get("duplicate_flag")),
            "suspicious_flag": bool(item["stored_replay"].get("suspicious_flag")),
            "resign_abuse_flag": bool(item["stored_replay"].get("resign_abuse_flag")),
        }
        for item in game_results
    ]
    _json_dump(engine_dir / "classification.json", classification_rows)

    all_evaluation_samples = _extract_engine_move_samples_from_records(records)
    evaluation_samples = all_evaluation_samples[:QUICK_RETRAIN_EVAL_SAMPLE_LIMIT]
    checkpoints: list[dict] = []
    current_model_path = before_model_path
    retrain_seconds_total = 0.0
    for trusted in QUICK_RETRAIN_GATE_CHECKPOINTS:
        _progress(f"phase quick retrain checkpoint started: {engine_alias} trusted={trusted}")
        checkpoint, current_model_path = _run_quick_retrain_checkpoint(
            engine_alias=engine_alias,
            engine_dir=engine_dir,
            runtime_dir=runtime_dir,
            records=records,
            focus_engine_name=focus_engine_name,
            target_model_path=current_model_path,
            evaluation_samples=evaluation_samples,
            trusted_replays=int(trusted),
            seed=seed + int(trusted) * 100,
            max_samples=quick_retrain_max_samples,
            max_seconds=quick_retrain_max_seconds,
            skip_heavy_sanity=bool(skip_heavy_sanity),
        )
        retrain_seconds_total += float(checkpoint.get("retrain_duration_seconds") or 0.0)
        checkpoints.append(checkpoint)

    safe_checkpoint_selection = _safe_checkpoint_selection(checkpoints, baseline_model_path=before_model_path)
    selected_safe_path = Path(str(safe_checkpoint_selection.get("selected_model_path") or ""))
    if selected_safe_path.exists():
        current_model_path = selected_safe_path

    dataset_started = time.perf_counter()
    fixture_write = _write_quick_replay_fixture(records, trusted_count=len(records))
    replay_summary = replay_buffer_summary()
    dataset_result = _prepare_formal_dataset(engine_dir, runtime_dir, invalid_game_ids=set())
    dataset_seconds = round(time.perf_counter() - dataset_started, 3)
    accepted_rows = _read_jsonl(engine_dir / "train_dataset.jsonl")
    rejected_rows = _read_jsonl(engine_dir / "rejected_dataset.jsonl")
    replay_fixture_health = _quick_replay_fixture_health(records, accepted_rows, rejected_rows)
    after_model_path = current_model_path
    after_model_meta = _model_meta(after_model_path)
    evaluation_before = _evaluate_move_agreement(engine_alias, before_model_path, evaluation_samples)
    evaluation_after = _evaluate_move_agreement(engine_alias, after_model_path, evaluation_samples)
    fixed_probes_before = _evaluate_fixed_probe_positions(engine_alias, before_model_path)
    fixed_probes_after = _evaluate_fixed_probe_positions(engine_alias, after_model_path)
    summary_checkpoints = [_compact_checkpoint_for_summary(checkpoint) for checkpoint in checkpoints]
    summary_checkpoints = [_compact_checkpoint_for_summary(checkpoint) for checkpoint in checkpoints]
    before_after_eval = {
        "retrain_supported": True,
        "move_agreement_before": evaluation_before,
        "move_agreement_after": evaluation_after,
        "fixed_probe_positions_before": fixed_probes_before,
        "fixed_probe_positions_after": fixed_probes_after,
        "probe_position_move_change_count": sum(
            1
            for before_row, after_row in zip(fixed_probes_before.get("positions") or [], fixed_probes_after.get("positions") or [])
            if str(before_row.get("chosen_move") or "") != str(after_row.get("chosen_move") or "")
        ),
        "benchmark_before": _skipped_benchmark_snapshot("stochastic_auxiliary_disabled_by_quick_retrain_gate")["focus"],
        "benchmark_after": _skipped_benchmark_snapshot("stochastic_auxiliary_disabled_by_quick_retrain_gate")["focus"],
        "checkpoints": summary_checkpoints,
        "benchmark_timeline": _benchmark_timeline(
            checkpoints,
            baseline_model_hash=before_model_meta["sha256"],
            final_model_hash=after_model_meta["sha256"],
        ),
    }

    deterministic_started = time.perf_counter()
    deterministic_cases = _deterministic_strength_cases(evaluation_samples)
    deterministic_snapshots = [
        _evaluate_deterministic_strength_snapshot(
            engine_alias=engine_alias,
            model_path=before_model_path,
            model_label="baseline",
            cases=deterministic_cases,
            seed=seed,
        )
    ]
    for checkpoint in checkpoints:
        trusted = int(checkpoint.get("trusted_count") or checkpoint.get("trusted_replays") or 0)
        deterministic_snapshots.append(
            _evaluate_deterministic_strength_snapshot(
                engine_alias=engine_alias,
                model_path=Path(str(checkpoint.get("candidate_model_path") or after_model_path)),
                model_label=f"checkpoint@{trusted}",
                cases=deterministic_cases,
                seed=seed,
            )
        )
    if deterministic_snapshots and checkpoints and str(checkpoints[-1].get("new_model_hash") or "") == after_model_meta["sha256"]:
        deterministic_snapshots.append(_clone_deterministic_snapshot(deterministic_snapshots[-1], model_label="final"))
    else:
        deterministic_snapshots.append(
            _evaluate_deterministic_strength_snapshot(
                engine_alias=engine_alias,
                model_path=after_model_path,
                model_label="final",
                cases=deterministic_cases,
                seed=seed,
            )
        )
    deterministic_strength = _deterministic_strength_report(deterministic_snapshots)
    policy_override_audit = _policy_override_audit(engine_alias, after_model_path, deterministic_cases, deterministic_strength)
    opening_target_margin_audit = _opening_target_margin_audit(
        engine_alias=engine_alias,
        model_path=after_model_path,
        deterministic_cases=deterministic_cases,
        deterministic_report=deterministic_strength,
        checkpoints=checkpoints,
    )
    fusion_mode_comparison = _fusion_mode_comparison(
        engine_alias=engine_alias,
        model_path=after_model_path,
        deterministic_cases=deterministic_cases,
        deterministic_report=deterministic_strength,
        checkpoints=checkpoints,
        seed=seed,
    )
    style_profile_audit = _style_profile_audit(
        engine_alias=engine_alias,
        model_path=after_model_path,
        deterministic_cases=deterministic_cases,
        seed=seed,
    )
    deterministic_eval_seconds = round(time.perf_counter() - deterministic_started, 3)
    _json_dump(engine_dir / "deterministic_strength_snapshot.json", deterministic_strength)
    _json_dump(engine_dir / "policy_override_audit.json", policy_override_audit)
    _json_dump(engine_dir / "opening_target_margin_audit.json", opening_target_margin_audit)
    _json_dump(engine_dir / "fusion_mode_comparison.json", fusion_mode_comparison)
    _json_dump(engine_dir / "style_profile_audit.json", style_profile_audit)
    specialist_started = time.perf_counter()
    incremental_gate_reports = [checkpoint.get("incremental_gate") or {} for checkpoint in checkpoints]
    smoke_failed = any(not bool(row.get("smoke_gate_passed")) for row in incremental_gate_reports)
    semantic_specialist_report = (
        {
            "supported": True,
            "enabled": False,
            "source": "exp30a_incremental_gate",
            "reason": "smoke_gate_failed",
            "full_gate_skipped": True,
            "full_gate_skip_reason": "; ".join(
                str(row.get("full_gate_skip_reason") or "")
                for row in incremental_gate_reports
                if row.get("full_gate_skipped")
            ).strip("; "),
            "groups": [],
            "promotion_gate_impact": "diagnostic_skipped_after_smoke_gate_failure",
        }
        if semantic_specialist_probes and smoke_failed
        else _run_semantic_specialist_probes(
            engine_alias=engine_alias,
            engine_dir=engine_dir,
            baseline_model_path=before_model_path,
            seed=seed,
            max_samples=quick_retrain_max_samples,
            max_seconds=quick_retrain_max_seconds,
        )
        if semantic_specialist_probes
        else {"supported": True, "enabled": False, "reason": "pass --semantic-specialist-probes to run exp23 diagnostics"}
    )
    semantic_specialist_seconds = round(time.perf_counter() - specialist_started, 3)
    _json_dump(engine_dir / "semantic_specialist_probes.json", semantic_specialist_report)
    kd_audit_started = time.perf_counter()
    kingside_development_audit_report = (
        _run_kingside_development_audit(
            engine_alias=engine_alias,
            engine_dir=engine_dir,
            model_path=after_model_path,
            semantic_specialist_report=semantic_specialist_report,
        )
        if kingside_development_audit
        else {"supported": True, "enabled": False, "reason": "pass --kingside-development-audit to run exp24 diagnostics"}
    )
    kingside_development_audit_seconds = round(time.perf_counter() - kd_audit_started, 3)
    _json_dump(engine_dir / "kingside_development_audit.json", kingside_development_audit_report)

    retrain_result = {
        "retrain_supported": True,
        "quick_retrain_gate": True,
        "nightly_expensive_validation": False,
        "expensive_validation_command": f"python3 scripts/games/chess_live_learning_validation.py --engines {engine_alias} --fast-retrain",
        "fixture": {
            "type": "fixed_trusted_replay_fixture",
            "trusted_replays": len(records),
            **fixture_write,
        },
        "checkpoints": summary_checkpoints,
        "safe_checkpoint_selection": safe_checkpoint_selection,
        "trainer_result": (checkpoints[-1].get("trainer_result") if checkpoints else {}),
    }
    retrain_timing = _checkpoint_timing_summary(checkpoints)
    distilled_checkpoint_reports = [checkpoint.get("distilled_replay_preprocessing") or {} for checkpoint in checkpoints]
    incremental_gate_reports = [checkpoint.get("incremental_gate") or {} for checkpoint in checkpoints]
    cache_reports = [((row.get("smoke_gate") or {}).get("cache") or {}) for row in incremental_gate_reports]
    cache_hits = sum(1 for row in cache_reports if row.get("cache_hit"))
    cache_misses = sum(1 for row in cache_reports if row and not row.get("cache_hit"))
    full_gate_skipped_count = sum(1 for row in incremental_gate_reports if row.get("full_gate_skipped"))
    skipped_eval_seconds_estimate = round(
        sum(
            max(0.0, float(checkpoint.get("checkpoint_duration_seconds") or 0.0) - float((checkpoint.get("incremental_gate") or {}).get("smoke_gate", {}).get("duration_seconds") or 0.0))
            for checkpoint in checkpoints
            if (checkpoint.get("incremental_gate") or {}).get("full_gate_skipped")
        ),
        3,
    )
    distilled_aggregate_rows: list[dict] = []
    for report in distilled_checkpoint_reports:
        path_text = str(report.get("output") or "")
        if path_text and Path(path_text).exists():
            distilled_aggregate_rows.extend(_read_jsonl(Path(path_text)))
    previous_retrain_seconds = _previous_quick_gate_retrain_seconds(engine_alias)
    distilled_replay_preprocessing = {
        "supported": True,
        "enabled": True,
        "source": "exp28_5_distilled_replay_preprocessing",
        "checkpoint_reports": distilled_checkpoint_reports,
        "raw_replay_rows": sum(int(row.get("original_rows") or 0) for row in distilled_checkpoint_reports),
        "distilled_replay_rows": sum(int(row.get("distilled_rows") or 0) for row in distilled_checkpoint_reports),
        "compression_ratio": round(
            sum(int(row.get("distilled_rows") or 0) for row in distilled_checkpoint_reports)
            / max(1, sum(int(row.get("original_rows") or 0) for row in distilled_checkpoint_reports)),
            4,
        ),
        "duplicate_ratio_before": max([float(row.get("duplicate_ratio_before") or 0.0) for row in distilled_checkpoint_reports] or [0.0]),
        "duplicate_ratio_after": max([float(row.get("duplicate_ratio_after") or 0.0) for row in distilled_checkpoint_reports] or [0.0]),
        "held_out_in_training": any(bool(row.get("held_out_in_training")) for row in distilled_checkpoint_reports),
        "leakage_detected": any(bool(row.get("leakage_detected")) for row in distilled_checkpoint_reports),
        "pre_filter_overlap_count": sum(int(row.get("pre_filter_overlap_count") or 0) for row in distilled_checkpoint_reports),
        "blocked_leakage_candidate_count": sum(int(row.get("blocked_leakage_candidate_count") or 0) for row in distilled_checkpoint_reports),
        "leakage_count": sum(int(row.get("leakage_count") or 0) for row in distilled_checkpoint_reports),
        "leakage_case_ids": sorted({str(case_id) for row in distilled_checkpoint_reports for case_id in row.get("leakage_case_ids") or []}),
        "leakage_hashes": sorted({str(hash_value) for row in distilled_checkpoint_reports for hash_value in row.get("leakage_hashes") or []}),
        "leakage_source_game_ids": sorted({str(game_id) for row in distilled_checkpoint_reports for game_id in row.get("leakage_source_game_ids") or []}),
        "semantic_distribution": _semantic_distribution_from_rows(distilled_aggregate_rows),
        "timing_seconds": round(sum(float(row.get("timing_seconds") or 0.0) for row in distilled_checkpoint_reports), 3),
        "distilled_retrain_seconds": round(retrain_seconds_total, 3),
        "previous_retrain_seconds": previous_retrain_seconds,
        "retrain_seconds_delta_vs_previous": (
            round(retrain_seconds_total - previous_retrain_seconds, 3)
            if previous_retrain_seconds is not None
            else None
        ),
        "retrain_time_reduced": (
            bool(retrain_seconds_total < previous_retrain_seconds)
            if previous_retrain_seconds is not None
            else None
        ),
        "promotion_evidence": False,
        "note": "distilled replay reduces training noise/cost but does not count as promotion evidence",
    }
    exp30a_pipeline = {
        "supported": True,
        "enabled": True,
        "source": "exp30a_distilled_replay_leakage_fix_evaluation_cache",
        "held_out_in_training": distilled_replay_preprocessing["held_out_in_training"],
        "leakage_detected": distilled_replay_preprocessing["leakage_detected"],
        "pre_filter_overlap_count": distilled_replay_preprocessing["pre_filter_overlap_count"],
        "blocked_leakage_candidate_count": distilled_replay_preprocessing["blocked_leakage_candidate_count"],
        "post_filter_leakage_count": distilled_replay_preprocessing["leakage_count"],
        "cache_hit_count": cache_hits,
        "cache_miss_count": cache_misses,
        "cache_hit_ratio": round(cache_hits / max(1, cache_hits + cache_misses), 4),
        "skipped_eval_seconds_estimate": skipped_eval_seconds_estimate,
        "full_gate_skipped_count": full_gate_skipped_count,
        "smoke_gate_passed": all(bool(row.get("smoke_gate_passed")) for row in incremental_gate_reports),
        "full_gate_skipped": any(bool(row.get("full_gate_skipped")) for row in incremental_gate_reports),
        "full_gate_skip_reason": "; ".join(
            str(row.get("full_gate_skip_reason") or "")
            for row in incremental_gate_reports
            if row.get("full_gate_skipped")
        ).strip("; "),
        "checkpoint_reports": incremental_gate_reports,
        "cache_key_fields": [
            "model_hash",
            "case_set_hash",
            "evaluator_config_hash",
            "decision_mode",
            "style_profile",
            "semantic_gate_version",
        ],
    }
    semantic_interference_reports = [checkpoint.get("semantic_interference_isolation") or {} for checkpoint in checkpoints]
    exp30b_pipeline = {
        "supported": True,
        "enabled": True,
        "source": "exp30b_semantic_interference_isolation",
        "semantic_specific_adapters": any(bool(row.get("semantic_specific_adapters")) for row in semantic_interference_reports),
        "semantic_head_update_count": {
            head: sum(int((row.get("semantic_head_update_count") or {}).get(head) or 0) for row in semantic_interference_reports)
            for head in ["central_head", "flank_head", "development_head", "other_head"]
        },
        "semantic_loss_budget": {
            head: round(sum(float((row.get("semantic_loss_budget") or {}).get(head) or 0.0) for row in semantic_interference_reports), 4)
            for head in ["central_head", "flank_head", "development_head", "other_head"]
        },
        "interference": any(bool(row.get("interference")) for row in semantic_interference_reports),
        "interference_reasons": sorted({
            str(reason)
            for row in semantic_interference_reports
            for reason in row.get("interference_reasons") or []
        }),
        "interference_matrix": [
            {
                "trusted_count": checkpoint.get("trusted_count"),
                "rows": (checkpoint.get("semantic_interference_isolation") or {}).get("interference_matrix") or [],
            }
            for checkpoint in checkpoints
        ],
        "central_retention": [
            {
                "trusted_count": checkpoint.get("trusted_count"),
                **((checkpoint.get("semantic_interference_isolation") or {}).get("central_retention") or {}),
            }
            for checkpoint in checkpoints
        ],
        "flank_retention": [
            {
                "trusted_count": checkpoint.get("trusted_count"),
                **((checkpoint.get("semantic_interference_isolation") or {}).get("flank_retention") or {}),
            }
            for checkpoint in checkpoints
        ],
        "development_retention": [
            {
                "trusted_count": checkpoint.get("trusted_count"),
                **((checkpoint.get("semantic_interference_isolation") or {}).get("development_retention") or {}),
            }
            for checkpoint in checkpoints
        ],
        "mistake_retention": [
            {
                "trusted_count": checkpoint.get("trusted_count"),
                **((checkpoint.get("semantic_interference_isolation") or {}).get("mistake_retention") or {}),
            }
            for checkpoint in checkpoints
        ],
        "checkpoint_reports": semantic_interference_reports,
        "note": "exp30b isolates semantic updates into central/flank/development adapter memories and reports cross-semantic retention deltas.",
    }
    exp31_reports = [checkpoint.get("semantic_loss_budget_scheduler") or {} for checkpoint in checkpoints]
    exp31_semantics = ["e_pawn_central_break", "d_pawn_central_break", "flank_pawn_push", "development_move", "other"]
    exp31_pipeline = {
        "supported": True,
        "enabled": True,
        "source": "exp31_semantic_loss_budget_scheduler",
        "loss_budget_by_semantic": {
            semantic: round(sum(float((row.get("loss_budget_by_semantic") or {}).get(semantic) or 0.0) for row in exp31_reports), 4)
            for semantic in exp31_semantics
        },
        "consumed_budget_by_semantic": {
            semantic: round(sum(float((row.get("consumed_budget_by_semantic") or {}).get(semantic) or 0.0) for row in exp31_reports), 4)
            for semantic in exp31_semantics
        },
        "effective_gradient_norm_by_semantic": {
            semantic: round(sum(float((row.get("effective_gradient_norm_by_semantic") or {}).get(semantic) or 0.0) for row in exp31_reports), 4)
            for semantic in exp31_semantics
        },
        "update_count_by_semantic": {
            semantic: sum(int((row.get("update_count_by_semantic") or {}).get(semantic) or 0) for row in exp31_reports)
            for semantic in exp31_semantics
        },
        "margin_delta_by_semantic": {
            semantic: round(sum(float((row.get("margin_delta_by_semantic") or {}).get(semantic) or 0.0) for row in exp31_reports), 4)
            for semantic in exp31_semantics
        },
        "update_schedule_trace": [
            {
                "trusted_count": checkpoint.get("trusted_count"),
                "trace": (checkpoint.get("semantic_loss_budget_scheduler") or {}).get("update_schedule_trace") or [],
            }
            for checkpoint in checkpoints
        ],
        "anchor_check_after_each_semantic": [
            {
                "trusted_count": checkpoint.get("trusted_count"),
                "anchors": (checkpoint.get("semantic_loss_budget_scheduler") or {}).get("anchor_check_after_each_semantic") or [],
            }
            for checkpoint in checkpoints
        ],
        "retention_delta_after_update": [
            {
                "trusted_count": checkpoint.get("trusted_count"),
                "rows": (checkpoint.get("semantic_loss_budget_scheduler") or {}).get("retention_delta_after_update") or [],
            }
            for checkpoint in checkpoints
        ],
        "central_retention_after_flank_updates": [
            {
                "trusted_count": checkpoint.get("trusted_count"),
                **((checkpoint.get("semantic_loss_budget_scheduler") or {}).get("central_retention_after_flank_updates") or {}),
            }
            for checkpoint in checkpoints
        ],
        "flank_retention_after_central_updates": [
            {
                "trusted_count": checkpoint.get("trusted_count"),
                **((checkpoint.get("semantic_loss_budget_scheduler") or {}).get("flank_retention_after_central_updates") or {}),
            }
            for checkpoint in checkpoints
        ],
        "rollback_applied": any(bool(row.get("rollback_applied")) for row in exp31_reports),
        "rollback_reasons": sorted({str(row.get("rollback_reason") or "") for row in exp31_reports if row.get("rollback_reason")}),
        "dampened_semantics": sorted({str(row.get("dampened_semantic") or "") for row in exp31_reports if row.get("dampened_semantic")}),
        "adjusted_loss_weight": [row.get("adjusted_loss_weight") or {} for row in exp31_reports],
        "shared_trunk_protection": [row.get("shared_trunk_protection") or {} for row in exp31_reports],
        "gradient_conflict_matrix": [
            {
                "trusted_count": checkpoint.get("trusted_count"),
                "matrix": (checkpoint.get("semantic_loss_budget_scheduler") or {}).get("gradient_conflict_matrix") or {},
            }
            for checkpoint in checkpoints
        ],
        "negative_cosine_like_conflict_count": sum(int(row.get("negative_cosine_like_conflict_count") or 0) for row in exp31_reports),
        "conflict_pair_examples": [
            example
            for row in exp31_reports
            for example in row.get("conflict_pair_examples") or []
        ][:12],
        "semantic_loss_budget_skew": any(bool(row.get("semantic_loss_budget_skew")) for row in exp31_reports),
        "catastrophic_semantic_interference": any(bool(row.get("catastrophic_semantic_interference")) for row in exp31_reports),
        "semantic_interference": any(bool(row.get("semantic_interference")) for row in exp31_reports),
        "interference_reasons": sorted({
            str(reason)
            for row in exp31_reports
            for reason in row.get("interference_reasons") or []
        }),
        "mistake_retention": [
            {
                "trusted_count": checkpoint.get("trusted_count"),
                **((checkpoint.get("semantic_loss_budget_scheduler") or {}).get("mistake_retention") or {}),
            }
            for checkpoint in checkpoints
        ],
        "checkpoint_reports": exp31_reports,
        "note": "exp31 keeps exp30a leakage/cache guard and adds semantic loss budgets, interleaved update scheduling, rehearsal anchors, rollback/dampening, and gradient-conflict diagnostics.",
    }
    exp32_reports = [
        {
            "trusted_count": checkpoint.get("trusted_count"),
            "smoke_anchor_audit": ((checkpoint.get("incremental_gate") or {}).get("smoke_gate") or {}).get("smoke_anchor_audit") or {},
            "development_multi_good_credit": (checkpoint.get("sanity_learning_probe") or {}).get("development_multi_good_credit") or {},
            "flank_smoke_difficulty_distribution": (checkpoint.get("sanity_learning_probe") or {}).get("flank_smoke_difficulty_distribution") or {},
            "contextual_flank_reason_tags": (checkpoint.get("sanity_learning_probe") or {}).get("contextual_flank_reason_tags") or {},
            "flank_vs_central_margin": (checkpoint.get("sanity_learning_probe") or {}).get("flank_vs_central_margin") or {},
            "flank_vs_development_margin": (checkpoint.get("sanity_learning_probe") or {}).get("flank_vs_development_margin") or {},
            "smoke_gate_failed_reason_type": ((checkpoint.get("incremental_gate") or {}).get("smoke_gate") or {}).get("smoke_gate_failed_reason_type"),
            "model_failure_vs_gate_scoring_issue": ((checkpoint.get("incremental_gate") or {}).get("smoke_gate") or {}).get("model_failure_vs_gate_scoring_issue"),
            "mistake_retention_repair": checkpoint.get("mistake_retention_repair") or {},
            "mistake_retention_probe": checkpoint.get("mistake_retention_probe") or {},
            "anchor_pass_delta_by_semantic": (checkpoint.get("semantic_interference_isolation") or {}).get("pass_rate_delta_by_semantic") or {},
        }
        for checkpoint in checkpoints
    ]
    exp32_pipeline = {
        "supported": True,
        "enabled": True,
        "source": "exp32_smoke_anchor_calibration_mistake_retention_repair",
        "smoke_anchor_audit_table": [
            {
                "trusted_count": row.get("trusted_count"),
                "cases": (row.get("smoke_anchor_audit") or {}).get("cases") or [],
                "failure_reason_counts": (row.get("smoke_anchor_audit") or {}).get("failure_reason_counts") or {},
            }
            for row in exp32_reports
        ],
        "development_multi_good_credit_applied": any(
            bool(((row.get("development_multi_good_credit") or {}).get("development_multi_good_credit_applied")))
            for row in exp32_reports
        ),
        "development_smoke_before_after_credit": [
            {
                "trusted_count": row.get("trusted_count"),
                "before": ((row.get("development_multi_good_credit") or {}).get("development_smoke_before_credit") or {}),
                "after": ((row.get("development_multi_good_credit") or {}).get("development_smoke_after_credit") or {}),
            }
            for row in exp32_reports
        ],
        "flank_smoke_difficulty_distribution": [
            {"trusted_count": row.get("trusted_count"), "distribution": row.get("flank_smoke_difficulty_distribution") or {}}
            for row in exp32_reports
        ],
        "contextual_flank_reason_tags": [
            {"trusted_count": row.get("trusted_count"), "reason_tags": row.get("contextual_flank_reason_tags") or {}}
            for row in exp32_reports
        ],
        "flank_vs_central_margin": [
            {"trusted_count": row.get("trusted_count"), **(row.get("flank_vs_central_margin") or {})}
            for row in exp32_reports
        ],
        "flank_vs_development_margin": [
            {"trusted_count": row.get("trusted_count"), **(row.get("flank_vs_development_margin") or {})}
            for row in exp32_reports
        ],
        "consumed_budget_by_semantic": exp31_pipeline.get("consumed_budget_by_semantic") or {},
        "effective_gradient_norm_by_semantic": exp31_pipeline.get("effective_gradient_norm_by_semantic") or {},
        "update_count_by_semantic": exp31_pipeline.get("update_count_by_semantic") or {},
        "anchor_pass_delta_by_semantic": [
            {"trusted_count": row.get("trusted_count"), "delta": row.get("anchor_pass_delta_by_semantic") or {}}
            for row in exp32_reports
        ],
        "mistake_retention_repair": [
            {"trusted_count": row.get("trusted_count"), **(row.get("mistake_retention_repair") or {})}
            for row in exp32_reports
        ],
        "repair_applied": any(bool((row.get("mistake_retention_repair") or {}).get("applied")) for row in exp32_reports),
        "repair_success": any(
            bool((row.get("mistake_retention_repair") or {}).get("repair_success"))
            or bool((row.get("mistake_retention_probe") or {}).get("learning_signal") and (row.get("mistake_retention_probe") or {}).get("matched_expected"))
            for row in exp32_reports
        ),
        "final_probe_after_repair_success": any(
            bool((row.get("mistake_retention_probe") or {}).get("learning_signal") and (row.get("mistake_retention_probe") or {}).get("matched_expected"))
            for row in exp32_reports
        ),
        "smoke_gate_failed_reason_type": [
            {"trusted_count": row.get("trusted_count"), "reason_type": row.get("smoke_gate_failed_reason_type")}
            for row in exp32_reports
        ],
        "model_failure_vs_gate_scoring_issue": [
            {"trusted_count": row.get("trusted_count"), "classification": row.get("model_failure_vs_gate_scoring_issue")}
            for row in exp32_reports
        ],
        "note": "exp32 audits smoke anchors, applies development multi-good credit inside smoke scoring, stratifies smoke anchors, and tries mistake-retention rehearsal before final checkpoint judgement.",
    }
    exp33_reports = [
        {
            "trusted_count": checkpoint.get("trusted_count"),
            "smoke_before_repair": ((checkpoint.get("incremental_gate") or {}).get("smoke_gate") or {}),
            "smoke_after_repair": ((checkpoint.get("incremental_gate") or {}).get("smoke_gate") or {}),
            "e_pawn_dampening_audit": checkpoint.get("exp33_e_pawn_dampening_audit") or {},
            "isolated_overfit": checkpoint.get("exp33_failed_anchor_isolated_probes") or {},
            "mistake_retention_probe": checkpoint.get("mistake_retention_probe") or {},
            "mistake_retention_repair": checkpoint.get("mistake_retention_repair") or {},
        }
        for checkpoint in checkpoints
    ]
    exp33_pipeline = {
        "supported": True,
        "enabled": True,
        "source": "exp33_failed_smoke_anchor_microdiagnosis_safe_checkpoint_retention",
        "smoke_anchor_microdiagnosis": [
            {
                "trusted_count": checkpoint.get("trusted_count"),
                "cases": (((checkpoint.get("incremental_gate") or {}).get("smoke_gate") or {}).get("smoke_anchor_audit") or {}).get("cases") or [],
                "failure_reason_counts": (((checkpoint.get("incremental_gate") or {}).get("smoke_gate") or {}).get("smoke_anchor_audit") or {}).get("failure_reason_counts") or {},
            }
            for checkpoint in checkpoints
        ],
        "e_pawn_dampening_audit": [
            {"trusted_count": row.get("trusted_count"), **(row.get("e_pawn_dampening_audit") or {})}
            for row in exp33_reports
        ],
        "failed_anchor_isolated_overfit": [
            {"trusted_count": row.get("trusted_count"), **(row.get("isolated_overfit") or {})}
            for row in exp33_reports
        ],
        "flank_rehearsal_applied": False,
        "central_after_flank_rehearsal": [
            {"trusted_count": checkpoint.get("trusted_count"), **((checkpoint.get("semantic_loss_budget_scheduler") or {}).get("central_retention_after_flank_updates") or {})}
            for checkpoint in checkpoints
        ],
        "development_after_flank_rehearsal": [
            {"trusted_count": checkpoint.get("trusted_count"), **((checkpoint.get("semantic_loss_budget_scheduler") or {}).get("development_retention_after_updates") or {})}
            for checkpoint in checkpoints
        ],
        "interference_detected": any(bool((checkpoint.get("semantic_loss_budget_scheduler") or {}).get("semantic_interference")) for checkpoint in checkpoints),
        "mistake_retention_stronger_repair": [
            {
                "trusted_count": row.get("trusted_count"),
                "before_move": (row.get("mistake_retention_probe") or {}).get("before_move"),
                "after_move": (row.get("mistake_retention_probe") or {}).get("after_move"),
                "expected_move": (row.get("mistake_retention_probe") or {}).get("expected_move"),
                "old_mistake": (row.get("mistake_retention_repair") or {}).get("old_mistake") or (row.get("mistake_retention_probe") or {}).get("before_move"),
                "repeated_old_mistake": (row.get("mistake_retention_probe") or {}).get("result_kind") == "repeated_old_mistake",
                "stronger_repair_applied": bool((row.get("mistake_retention_repair") or {}).get("stronger_repair_applied")),
                "after_repair_move": (row.get("mistake_retention_repair") or {}).get("after_rehearsal_move"),
                "repair_success": bool((row.get("mistake_retention_repair") or {}).get("repair_success")),
            }
            for row in exp33_reports
        ],
        "safe_checkpoint_selection": safe_checkpoint_selection,
        "selected_safe_checkpoint": safe_checkpoint_selection.get("selected_safe_checkpoint"),
        "smoke_before_after": [
            {
                "trusted_count": row.get("trusted_count"),
                "before": {
                    "final_pass_rate": (row.get("smoke_before_repair") or {}).get("final_pass_rate"),
                    "by_semantic": (row.get("smoke_before_repair") or {}).get("by_semantic") or {},
                },
                "after": {
                    "final_pass_rate": (row.get("smoke_after_repair") or {}).get("final_pass_rate"),
                    "by_semantic": (row.get("smoke_after_repair") or {}).get("by_semantic") or {},
                },
            }
            for row in exp33_reports
        ],
        "note": "exp33 keeps gate thresholds fixed, diagnoses failed e_pawn/flank smoke anchors, runs isolated probes, and prevents failed-retention cp20 from being selected as final.",
    }
    exp34_retention_case_version_audit = _exp34_retention_case_version_audit(checkpoints)
    exp34_hard_e_pawn_decision_audit, exp34_hard_flank_audit = _exp34_hard_case_decision_audits(checkpoints)
    exp34_smoke_levels = _exp34_smoke_level_report(
        checkpoints,
        retention_audit=exp34_retention_case_version_audit,
        safe_checkpoint_selection=safe_checkpoint_selection,
    )
    exp34_pipeline = {
        "supported": True,
        "enabled": True,
        "source": "exp34_mixed_scheduler_repair_hard_case_decision_audit",
        "retention_case_version_audit": exp34_retention_case_version_audit,
        "safe_checkpoint_selection": safe_checkpoint_selection,
        "cp20_rejected_by_retention": bool(safe_checkpoint_selection.get("cp20_rejected_by_retention")),
        "selected_safe_checkpoint": safe_checkpoint_selection.get("selected_safe_checkpoint"),
        "mixed_scheduler_repair": [
            {
                "trusted_count": checkpoint.get("trusted_count"),
                **(checkpoint.get("exp34_mixed_scheduler_repair") or {}),
            }
            for checkpoint in checkpoints
        ],
        "easy_anchor_pass_before_after": [
            {
                "trusted_count": checkpoint.get("trusted_count"),
                "before": _semantic_pass_rates_from_performance(
                    (((checkpoint.get("incremental_gate") or {}).get("smoke_gate_before_exp34_repair") or {}).get("performance") or {})
                ),
                "after": _semantic_pass_rates_from_performance(
                    (((checkpoint.get("incremental_gate") or {}).get("smoke_gate") or {}).get("performance") or {})
                ),
            }
            for checkpoint in checkpoints
        ],
        "scheduler_update_trace": [
            {
                "trusted_count": checkpoint.get("trusted_count"),
                "trace": (checkpoint.get("exp34_mixed_scheduler_repair") or {}).get("scheduler_update_trace") or [],
            }
            for checkpoint in checkpoints
        ],
        "semantic_pass_delta_after_each_batch": [
            {
                "trusted_count": checkpoint.get("trusted_count"),
                "delta": (checkpoint.get("exp34_mixed_scheduler_repair") or {}).get("semantic_pass_delta_after_each_batch") or {},
            }
            for checkpoint in checkpoints
        ],
        "hard_e_pawn_decision_audit": exp34_hard_e_pawn_decision_audit,
        "balanced_fusion_threshold_adjustment_tested": any(bool(row.get("balanced_fusion_threshold_adjustment_tested")) for row in exp34_hard_e_pawn_decision_audit),
        "hard_flank_audit": exp34_hard_flank_audit,
        "questionable_hard_flank_label": any(bool(row.get("questionable_hard_flank_label")) for row in exp34_hard_flank_audit),
        "hard_flank_capability_gap": any(bool(row.get("hard_flank_capability_gap")) for row in exp34_hard_flank_audit),
        "smoke_level_report": exp34_smoke_levels,
        "smoke_level_1_passed": all(bool(row.get("smoke_level_1_passed")) for row in exp34_smoke_levels),
        "smoke_level_2_passed": all(bool(row.get("smoke_level_2_passed")) for row in exp34_smoke_levels),
        "failure_classification": sorted({str(row.get("failure_classification") or "") for row in exp34_smoke_levels if row.get("failure_classification")}),
        "note": "exp34 separates foundation smoke failures from hard generalization failures, audits hard e-pawn/flank decision paths, and keeps cp20 retention failure out of final candidate selection.",
    }
    flank_context_feature_injection = {
        "supported": True,
        "enabled": True,
        "source": "exp29_flank_context_feature_injection",
        "checkpoint_reports": [checkpoint.get("flank_context_feature_injection") or {} for checkpoint in checkpoints],
        "trainer_feature_injection": any(bool((checkpoint.get("flank_context_feature_injection") or {}).get("trainer_feature_injection")) for checkpoint in checkpoints),
        "flank_context_classification_updates": sum(
            int(((checkpoint.get("flank_context_feature_injection") or {}).get("flank_context_classification_loss") or {}).get("updates") or 0)
            for checkpoint in checkpoints
        ),
        "flank_reason_tag_updates": sum(
            int(((checkpoint.get("flank_context_feature_injection") or {}).get("flank_reason_tag_loss") or {}).get("updates") or 0)
            for checkpoint in checkpoints
        ),
        "flank_vs_nonflank_margin_updates": sum(
            int(((checkpoint.get("flank_context_feature_injection") or {}).get("flank_vs_nonflank_margin_loss") or {}).get("updates") or 0)
            for checkpoint in checkpoints
        ),
        "flank_vs_central_margin": [
            (checkpoint.get("flank_context_feature_injection") or {}).get("flank_vs_central_margin") or {}
            for checkpoint in checkpoints
        ],
        "flank_vs_development_margin": [
            (checkpoint.get("flank_context_feature_injection") or {}).get("flank_vs_development_margin") or {}
            for checkpoint in checkpoints
        ],
        "bad_random_flank_rejection_updates": sum(
            int((checkpoint.get("flank_context_feature_injection") or {}).get("bad_random_flank_rejection_updates") or 0)
            for checkpoint in checkpoints
        ),
        "note": "exp28 metadata-only failed; exp29 injects flank context into trainer memory and policy scoring.",
    }
    game_timing = {"steps_measured": 0, "avg_think_ms_per_step": 0.0, "total_think_ms": 0.0, "by_role": {}}
    summary = {
        "engine_alias": engine_alias,
        "difficulty": difficulty,
        "seed": int(seed),
        "validation_mode": "quick_retrain_gate",
        "expensive_validation": False,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "commit": _git_commit(),
        "engine_config": {
            "difficulty": difficulty,
            "quick_retrain_gate": True,
            "fixed_seed": int(seed),
            "quick_retrain_checkpoints": list(QUICK_RETRAIN_GATE_CHECKPOINTS),
            "quick_retrain_max_samples": int(quick_retrain_max_samples),
            "quick_retrain_max_seconds": int(quick_retrain_max_seconds),
            "quick_retrain_eval_sample_limit": QUICK_RETRAIN_EVAL_SAMPLE_LIMIT,
            "full_game_generation": False,
            "nightly_expensive_validation_available": True,
        },
        "runtime_dir": str(runtime_dir),
        "warm_start": warm,
        "total_games": len(records),
        "expected_trusted_replays": QUICK_RETRAIN_GATE_TRUSTED_REPLAYS,
        "expected_quarantine_replays": 0,
        "game_timing": game_timing,
        "games": game_results,
        "classification": classification_rows,
        "invalid_case_audit": [],
        "replay_summary": replay_summary,
        "autorun_threshold": QUICK_RETRAIN_GATE_CHECKPOINTS[0],
        "dataset_result": dataset_result,
        "autorun": {"launched": False, "reason": "quick_retrain_gate_direct_trainer"},
        "autorun_status": {"status": "skipped", "reason": "quick_retrain_gate_direct_trainer"},
        "pipeline_report": {"exists": False, "reason": "quick_retrain_gate_direct_trainer"},
        "evaluation_before": evaluation_before,
        "evaluation_after": evaluation_after,
        "before_after_eval": before_after_eval,
        "deterministic_strength_snapshot": deterministic_strength,
        "policy_override_audit": policy_override_audit,
        "opening_target_margin_audit": opening_target_margin_audit,
        "fusion_mode_comparison": fusion_mode_comparison,
        "style_profile_audit": style_profile_audit,
        "semantic_specialist_probes": semantic_specialist_report,
        "kingside_development_audit": kingside_development_audit_report,
        "stochastic_auxiliary_benchmark": {
            "purpose": "sanity signal only; not primary promotion evidence",
            "strength_evidence": False,
            "skipped": True,
            "skip_reason": "stochastic_auxiliary_disabled_by_quick_retrain_gate",
            "benchmark_before": before_after_eval.get("benchmark_before"),
            "benchmark_after": before_after_eval.get("benchmark_after"),
        },
        "perft": {
            "purpose": "move generation correctness only; not strength evidence",
            "strength_evidence": False,
            "skipped": True,
            "reason": "not part of quick retrain promotion gate",
        },
        "retrain_result": retrain_result,
        "retrain_timing": retrain_timing,
        "distilled_replay_preprocessing": distilled_replay_preprocessing,
        "exp30a_pipeline": exp30a_pipeline,
        "exp30b_pipeline": exp30b_pipeline,
        "exp31_pipeline": exp31_pipeline,
        "exp32_pipeline": exp32_pipeline,
        "exp33_pipeline": exp33_pipeline,
        "exp34_pipeline": exp34_pipeline,
        "flank_context_feature_injection": flank_context_feature_injection,
        "model_before": before_model_meta,
        "model_after": after_model_meta,
        "evaluation_sample_count": len(evaluation_samples),
        "available_evaluation_sample_count": len(all_evaluation_samples),
        "exp1_live_learning": {},
        "environment": _environment_summary(),
        "replay_fixture_health": replay_fixture_health,
        "quick_retrain_gate": {
            "enabled": True,
            "fixture_trusted_replays": len(records),
            "fixture_hash": replay_fixture_health.get("fixture_hash"),
            "checkpoints": list(QUICK_RETRAIN_GATE_CHECKPOINTS),
            "full_30_game_generation_skipped": True,
            "stochastic_auxiliary_only": True,
        },
    }
    dataset_integrity = _dataset_integrity_summary(accepted_rows, rejected_rows, game_results)
    dataset_integrity["contaminated_rows"] = int(dataset_result.get("contaminated_rows") or 0)
    summary["dataset_integrity"] = dataset_integrity
    summary.update(_replay_source_audit(game_results))
    summary["position_quality"] = _position_quality_summary(classification_rows)
    summary["stage_game_win_rates"] = []
    summary["poison_detection"] = _poison_detection_summary(classification_rows)
    summary["retrain_stability_report"] = _retrain_stability_report(summary)
    summary["checkpoint_consistency"] = _checkpoint_consistency_report(summary)
    summary["stability"] = _stability_summary(summary)
    summary["timing_breakdown"] = {
        "replay_generation_seconds": replay_generation_seconds,
        "dataset_prepare_seconds": dataset_seconds,
        "retrain_seconds": round(retrain_seconds_total, 3),
        "deterministic_eval_seconds": deterministic_eval_seconds,
        "semantic_specialist_probe_seconds": semantic_specialist_seconds,
        "specialist_probe_seconds": semantic_specialist_seconds,
        "previous_total_checkpoint_seconds": 1300.53,
        "new_total_checkpoint_seconds": retrain_timing.get("total_checkpoint_seconds"),
        "cache_seconds_saved": 0.0,
        "skipped_eval_seconds_estimate": skipped_eval_seconds_estimate,
        "kingside_development_audit_seconds": kingside_development_audit_seconds,
        "report_write_seconds": 0.0,
        "total_wall_seconds": round(time.perf_counter() - wall_started, 3),
    }
    summary["runtime_metrics"] = _runtime_metrics_summary(summary)
    summary["reproducibility"] = _reproducibility_summary(summary)
    summary["engine_verdict"] = _engine_verdict(summary)
    summary["promotion_gate"] = _promotion_gate_summary(summary)
    summary["suitable_for_production_self_learning"] = summary["engine_verdict"] == "PASS" and bool(summary["promotion_gate"].get("passed"))
    report_started = time.perf_counter()
    _json_dump(engine_dir / "summary.json", summary)
    _write_engine_report(engine_dir, summary)
    summary["timing_breakdown"]["report_write_seconds"] = round(time.perf_counter() - report_started, 3)
    summary["timing_breakdown"]["total_wall_seconds"] = round(time.perf_counter() - wall_started, 3)
    _json_dump(engine_dir / "summary.json", summary)
    _write_engine_report(engine_dir, summary)
    return summary


def _run_engine_validation(
    *,
    engine_alias: str,
    difficulty: str,
    engine_dir: Path,
    runtime_root: Path,
    seed: int,
    max_plies: int,
    wait_timeout: int,
    autorun_threshold: int,
    skip_autorun_benchmark: bool,
    skip_autorun_promote: bool,
    skip_retrain_benchmark_snapshots: bool,
    benchmark_rounds: int,
    benchmark_max_plies: int,
    benchmark_teacher_depth: int,
) -> dict:
    started_at = _utc_now()
    runtime_dir = runtime_root / engine_alias
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    min_replays = 9999
    _set_runtime_env(
        runtime_dir,
        min_usable_replays=min_replays,
        skip_autorun_benchmark=skip_autorun_benchmark,
        skip_autorun_promote=skip_autorun_promote,
    )
    warm = ensure_warm_start_chess_environment()
    actor_username = f"{engine_alias}_validation_user"
    store = ChessExperimentStore()
    sys.stderr.write(f"[{engine_alias}] planning games\n")
    sys.stderr.flush()
    planned_games = _plan_engine_games(
        engine_name=difficulty,
        actor_username=actor_username,
        seed=seed,
        max_plies=max_plies,
        store=store,
    )
    sys.stderr.write(f"[{engine_alias}] planned {len(planned_games)} games\n")
    sys.stderr.flush()
    game_timing = _flow_timing_summary(planned_games)
    valid_games = [game for game in planned_games if game.category == "valid"]
    invalid_games = [game for game in planned_games if game.category != "valid"]
    invalid_game_ids = {int(game.row.get("id") or 0) for game in invalid_games}
    inventory_before = production_engine_inventory()
    inventory_before_map = {row["engine"]: row for row in inventory_before}
    focus_engine_name = _engine_focus_name(engine_alias)
    before_row = inventory_before_map.get(focus_engine_name, {})
    before_model_path = Path(str(before_row.get("path") or ""))
    before_model_meta = _model_meta(before_model_path)
    baseline_overrides = _inventory_model_overrides(inventory_before_map)
    current_model_path = before_model_path
    current_benchmark_overrides = dict(baseline_overrides)
    if engine_alias in RETRAIN_ENGINE_ALIASES:
        current_benchmark_overrides[_engine_model_slot(engine_alias)] = current_model_path

    exp1_live_updates = 0
    exp1_invalid_applied = 0
    game_results = []
    trusted_valid_games_so_far: list[PlannedGame] = []
    checkpoints: list[dict] = []
    checkpoint_targets = []
    pending_checkpoint_targets: set[int] = set()
    if engine_alias in RETRAIN_ENGINE_ALIASES:
        step = max(1, int(autorun_threshold))
        checkpoint_targets = [target for target in range(step, VALID_GAMES + 1, step)]
        pending_checkpoint_targets = set(checkpoint_targets)
    exp1_before_benchmark = None
    if engine_alias == "exp1":
        exp1_before_benchmark = _run_benchmark_snapshot(
            focus_engine_name=focus_engine_name,
            model_overrides=baseline_overrides,
            seed=seed + 41,
            benchmark_rounds=benchmark_rounds,
            benchmark_max_plies=benchmark_max_plies,
            benchmark_teacher_depth=benchmark_teacher_depth,
        )
    for index, game in enumerate(planned_games, start=1):
        stored_replay = collect_match_replay(
            game.row,
            winner_color=game.winner_color,
            source="user_games",
            actor_username=actor_username,
        )
        update_count = 0
        if engine_alias == "exp1":
            update_count = int(record_experiment_learning(game.row, winner_color=game.winner_color, store=store) or 0)
            exp1_live_updates += update_count
            if game.category != "valid":
                exp1_invalid_applied += update_count
        _write_engine_case(engine_dir, index, game, stored_replay)
        if game.category == "valid" and stored_replay.get("collection_tier") == "trusted":
            trusted_valid_games_so_far.append(game)
        launch_result = None
        trusted_replays = len(trusted_valid_games_so_far)
        if _should_launch_checkpoint(
            engine_alias=engine_alias,
            game=game,
            stored_replay=stored_replay,
            trusted_replays=trusted_replays,
            pending_checkpoint_targets=pending_checkpoint_targets,
        ):
            sys.stderr.write(f"[{engine_alias}] checkpoint retrain at trusted={trusted_replays}\n")
            sys.stderr.flush()
            pending_checkpoint_targets.discard(trusted_replays)
            evaluation_samples = _extract_engine_move_samples(trusted_valid_games_so_far)
            checkpoint, current_model_path, current_benchmark_overrides = _run_retrain_checkpoint(
                engine_alias=engine_alias,
                engine_dir=engine_dir,
                runtime_dir=runtime_dir,
                actor_username=actor_username,
                focus_engine_name=focus_engine_name,
                target_model_path=current_model_path,
                benchmark_overrides_before=current_benchmark_overrides,
                evaluation_samples=evaluation_samples,
                trusted_replays=trusted_replays,
                wait_timeout=wait_timeout,
                autorun_threshold=autorun_threshold,
                seed=seed + trusted_replays * 100,
                invalid_game_ids=invalid_game_ids,
                skip_autorun_benchmark=skip_autorun_benchmark,
                skip_autorun_promote=skip_autorun_promote,
                skip_retrain_benchmark_snapshots=skip_retrain_benchmark_snapshots,
                benchmark_rounds=benchmark_rounds,
                benchmark_max_plies=benchmark_max_plies,
                benchmark_teacher_depth=benchmark_teacher_depth,
            )
            checkpoints.append(checkpoint)
            launch_result = checkpoint.get("autorun")
        game_results.append(
            {
                "index": index,
                "game_id": int(game.row.get("id") or 0),
                "label": game.label,
                "category": game.category,
                "expected_tier": game.expected_tier,
                "human_side": str(game.row.get("human_side") or ""),
                "winner_color": game.winner_color,
                "stored_replay": stored_replay,
                "autorun_result": launch_result,
                "learning_update_count": update_count,
            }
        )
        if index % 5 == 0:
            sys.stderr.write(f"[{engine_alias}] stored {index}/{len(planned_games)} games\n")
            sys.stderr.flush()

    classification_rows = [
        {
            "index": item["index"],
            "label": item["label"],
            "category": item["category"],
            "expected_tier": item["expected_tier"],
            "actual_tier": item["stored_replay"].get("collection_tier"),
            "stored": bool(item["stored_replay"].get("stored")),
            "quarantine_reasons": item["stored_replay"].get("quarantine_reasons") or [],
            "confidence_score": item["stored_replay"].get("confidence_score"),
            "duplicate_flag": bool(item["stored_replay"].get("duplicate_flag")),
            "suspicious_flag": bool(item["stored_replay"].get("suspicious_flag")),
            "resign_abuse_flag": bool(item["stored_replay"].get("resign_abuse_flag")),
        }
        for item in game_results
    ]
    _json_dump(engine_dir / "classification.json", classification_rows)

    replay_summary = replay_buffer_summary()
    sys.stderr.write(f"[{engine_alias}] preparing formal dataset\n")
    sys.stderr.flush()
    dataset_result = _prepare_formal_dataset(engine_dir, runtime_dir, invalid_game_ids=invalid_game_ids)
    accepted_rows = _read_jsonl(engine_dir / "train_dataset.jsonl")
    rejected_rows = _read_jsonl(engine_dir / "rejected_dataset.jsonl")
    accepted_source_game_ids = {int(row.get("source_game_id") or 0) for row in accepted_rows}
    invalid_case_audit = []
    for item in game_results:
        game_id = int(item.get("game_id") or item["stored_replay"].get("match_id") or 0)
        if game_id not in invalid_game_ids:
            continue
        expected_classification = "quarantine"
        actual_classification = str(item["stored_replay"].get("collection_tier") or "")
        entered_train_dataset = game_id in accepted_source_game_ids
        invalid_case_audit.append(
            {
                "game_id": game_id,
                "label": item["label"],
                "injection_reason": item["category"],
                "expected_classification": expected_classification,
                "actual_classification": actual_classification,
                "entered_train_dataset": entered_train_dataset,
                "verdict": "FAIL" if entered_train_dataset else "PASS",
            }
        )

    evaluation_samples = _extract_engine_move_samples(valid_games)
    evaluation_before = _evaluate_move_agreement(engine_alias, before_model_path, evaluation_samples)
    evaluation_after = _evaluate_move_agreement(engine_alias, current_model_path, evaluation_samples)
    fixed_probes_before = _evaluate_fixed_probe_positions(engine_alias, before_model_path)
    fixed_probes_after = _evaluate_fixed_probe_positions(engine_alias, current_model_path)
    final_probe_move_change_count = sum(
        1
        for before_row, after_row in zip(fixed_probes_before.get("positions") or [], fixed_probes_after.get("positions") or [])
        if str(before_row.get("chosen_move") or "") != str(after_row.get("chosen_move") or "")
    )
    before_benchmark = None
    after_benchmark = None
    after_model_path = current_model_path
    after_model_meta = _model_meta(after_model_path)
    autorun = checkpoints[-1].get("autorun") if checkpoints else None
    autorun_status = checkpoints[-1].get("autorun_status") if checkpoints else latest_pipeline_autorun_status()
    pipeline_report = latest_pipeline_report() if checkpoints else {"exists": False, "path": "", "summary": {}}
    retrain_result: dict

    if engine_alias in RETRAIN_ENGINE_ALIASES:
        before_benchmark = checkpoints[0]["benchmark_before"] if checkpoints else None
        after_benchmark = checkpoints[-1]["benchmark_after"] if checkpoints else None
        retrain_timing = _checkpoint_timing_summary(checkpoints)
        trainer_probe = _run_trainer_probe(
            engine_alias=engine_alias,
            engine_dir=engine_dir,
            base_model_path=before_model_path,
            accepted_rows=accepted_rows,
            rejected_rows=rejected_rows,
        )
        pipeline_summary = pipeline_report.get("summary") if isinstance(pipeline_report.get("summary"), dict) else {}
        retrain_result = {
            "retrain_supported": True,
            "autorun": autorun,
            "autorun_status": autorun_status,
            "pipeline_report_path": pipeline_report.get("path", ""),
            "pipeline_ok": bool((pipeline_report.get("summary") or {}).get("ok")),
            "trainer_result": (pipeline_report.get("summary") or {}).get(_trainer_key(engine_alias)) or {},
            "trainer_probe": trainer_probe,
            "candidate_model_path": str(after_model_path),
            "checkpoints": [_compact_checkpoint_for_summary(checkpoint) for checkpoint in checkpoints],
            "timing": retrain_timing,
        }
    else:
        retrain_timing = _checkpoint_timing_summary(checkpoints)
        retrain_result = {
            "retrain_supported": False,
            "reason": "no replay dataset trainer is implemented for this engine; validation limited to collection/classification only",
            "timing": retrain_timing,
        }
        if engine_alias == "exp1":
            after_benchmark = _run_benchmark_snapshot(
                focus_engine_name=focus_engine_name,
                model_overrides=baseline_overrides,
                seed=seed + 42,
                benchmark_rounds=benchmark_rounds,
                benchmark_max_plies=benchmark_max_plies,
                benchmark_teacher_depth=benchmark_teacher_depth,
            )
            before_benchmark = exp1_before_benchmark["focus"] if exp1_before_benchmark else None
            after_benchmark = after_benchmark["focus"] if after_benchmark else None
    contamination_first_game = None
    contamination_move_count = 0
    if engine_alias == "exp1" and exp1_invalid_applied > 0:
        game_map = {int(game.row.get("id") or 0): game for game in invalid_games}
        for item in game_results:
            game_id = int(item.get("game_id") or item["stored_replay"].get("match_id") or 0)
            if game_id in game_map and int(item.get("learning_update_count") or 0) > 0:
                contamination_first_game = game_id
                contamination_move_count = len(json.loads(game_map[game_id].row.get("move_history_json") or "[]"))
                break

    before_after_eval = {
        "retrain_supported": engine_alias in RETRAIN_ENGINE_ALIASES,
        "move_agreement_before": evaluation_before,
        "move_agreement_after": evaluation_after,
        "fixed_probe_positions_before": fixed_probes_before,
        "fixed_probe_positions_after": fixed_probes_after,
        "probe_position_move_change_count": final_probe_move_change_count,
        "benchmark_before": before_benchmark["focus"] if isinstance(before_benchmark, dict) and before_benchmark.get("focus") else before_benchmark,
        "benchmark_after": after_benchmark["focus"] if isinstance(after_benchmark, dict) and after_benchmark.get("focus") else after_benchmark,
        "checkpoints": summary_checkpoints,
        "benchmark_timeline": _benchmark_timeline(
            checkpoints,
            baseline_model_hash=before_model_meta["sha256"],
            final_model_hash=after_model_meta["sha256"],
        ),
    }
    deterministic_cases = _deterministic_strength_cases(evaluation_samples)
    deterministic_snapshots = [
        _evaluate_deterministic_strength_snapshot(
            engine_alias=engine_alias,
            model_path=before_model_path,
            model_label="baseline",
            cases=deterministic_cases,
            seed=seed,
        )
    ]
    for checkpoint in checkpoints:
        trusted = int(checkpoint.get("trusted_count") or checkpoint.get("trusted_replays") or 0)
        deterministic_snapshots.append(
            _evaluate_deterministic_strength_snapshot(
                engine_alias=engine_alias,
                model_path=Path(str(checkpoint.get("candidate_model_path") or current_model_path)),
                model_label=f"checkpoint@{trusted}",
                cases=deterministic_cases,
                seed=seed,
            )
        )
    if deterministic_snapshots and checkpoints and str(checkpoints[-1].get("new_model_hash") or "") == after_model_meta["sha256"]:
        deterministic_snapshots.append(_clone_deterministic_snapshot(deterministic_snapshots[-1], model_label="final"))
    else:
        deterministic_snapshots.append(
            _evaluate_deterministic_strength_snapshot(
                engine_alias=engine_alias,
                model_path=after_model_path,
                model_label="final",
                cases=deterministic_cases,
                seed=seed,
            )
        )
    deterministic_strength = _deterministic_strength_report(deterministic_snapshots)
    policy_override_audit = _policy_override_audit(engine_alias, after_model_path, deterministic_cases, deterministic_strength)
    opening_target_margin_audit = _opening_target_margin_audit(
        engine_alias=engine_alias,
        model_path=after_model_path,
        deterministic_cases=deterministic_cases,
        deterministic_report=deterministic_strength,
        checkpoints=checkpoints,
    )
    fusion_mode_comparison = _fusion_mode_comparison(
        engine_alias=engine_alias,
        model_path=after_model_path,
        deterministic_cases=deterministic_cases,
        deterministic_report=deterministic_strength,
        checkpoints=checkpoints,
        seed=seed,
    )
    style_profile_audit = _style_profile_audit(
        engine_alias=engine_alias,
        model_path=after_model_path,
        deterministic_cases=deterministic_cases,
        seed=seed,
    )
    _json_dump(engine_dir / "deterministic_strength_snapshot.json", deterministic_strength)
    _json_dump(engine_dir / "policy_override_audit.json", policy_override_audit)
    _json_dump(engine_dir / "opening_target_margin_audit.json", opening_target_margin_audit)
    _json_dump(engine_dir / "fusion_mode_comparison.json", fusion_mode_comparison)
    _json_dump(engine_dir / "style_profile_audit.json", style_profile_audit)
    _json_dump(engine_dir / "retrain_result.json", retrain_result)
    _json_dump(engine_dir / "before_after_eval.json", before_after_eval)

    contamination_risk = ""
    if engine_alias == "exp1" and exp1_invalid_applied > 0:
        contamination_risk = "HIGH"
    summary = {
        "engine_alias": engine_alias,
        "difficulty": difficulty,
        "seed": int(seed),
        "started_at": started_at,
        "finished_at": _utc_now(),
        "commit": _git_commit(),
        "engine_config": {
            "difficulty": difficulty,
            "max_plies": int(max_plies),
            "autorun_threshold": int(autorun_threshold),
            "fast_retrain": bool(skip_autorun_benchmark or skip_autorun_promote),
            "skip_autorun_benchmark": bool(skip_autorun_benchmark),
            "skip_autorun_promote": bool(skip_autorun_promote),
            "skip_retrain_benchmark_snapshots": bool(skip_retrain_benchmark_snapshots),
            "benchmark_rounds": int(benchmark_rounds),
            "benchmark_max_plies": int(benchmark_max_plies),
            "benchmark_teacher_depth": int(benchmark_teacher_depth),
            "total_games": TOTAL_GAMES,
            "valid_games": VALID_GAMES,
            "invalid_games": INVALID_GAMES,
        },
        "runtime_dir": str(runtime_dir),
        "warm_start": warm,
        "total_games": len(planned_games),
        "game_timing": game_timing,
        "games": game_results,
        "classification": classification_rows,
        "invalid_case_audit": invalid_case_audit,
        "replay_summary": replay_summary,
        "autorun_threshold": int(autorun_threshold),
        "dataset_result": dataset_result,
        "autorun": autorun,
        "autorun_status": autorun_status,
        "pipeline_report": pipeline_report,
        "evaluation_before": evaluation_before,
        "evaluation_after": evaluation_after,
        "before_after_eval": before_after_eval,
        "deterministic_strength_snapshot": deterministic_strength,
        "policy_override_audit": policy_override_audit,
        "opening_target_margin_audit": opening_target_margin_audit,
        "fusion_mode_comparison": fusion_mode_comparison,
        "style_profile_audit": style_profile_audit,
        "stochastic_auxiliary_benchmark": {
            "purpose": "sanity signal only; not primary promotion evidence",
            "strength_evidence": False,
            "skipped": _summary_benchmark_skipped({"before_after_eval": before_after_eval}),
            "skip_reason": _summary_benchmark_skip_reason({"before_after_eval": before_after_eval}),
            "benchmark_before": before_after_eval.get("benchmark_before"),
            "benchmark_after": before_after_eval.get("benchmark_after"),
        },
        "perft": {
            "purpose": "move generation correctness only; not strength evidence",
            "strength_evidence": False,
            "skipped": True,
            "reason": "not part of live-learning promotion gate",
        },
        "retrain_result": retrain_result,
        "retrain_timing": retrain_timing,
        "model_before": before_model_meta,
        "model_after": after_model_meta,
        "evaluation_sample_count": len(evaluation_samples),
        "exp1_live_learning": {
            "applied_updates": exp1_live_updates,
            "invalid_games_applied": exp1_invalid_applied,
            "contamination_risk": contamination_risk,
            "contamination_first_game": contamination_first_game,
            "contamination_move_count": contamination_move_count,
            "rollback_possible": False if exp1_invalid_applied > 0 else True,
            "rollback_checkpoint": "",
            "benchmark_before": before_benchmark if engine_alias == "exp1" else None,
            "benchmark_after": after_benchmark if engine_alias == "exp1" else None,
        } if engine_alias == "exp1" else {},
        "environment": _environment_summary(),
    }
    dataset_integrity = _dataset_integrity_summary(accepted_rows, rejected_rows, game_results)
    dataset_integrity["contaminated_rows"] = int(dataset_result.get("contaminated_rows") or 0)
    summary["dataset_integrity"] = dataset_integrity
    summary.update(_replay_source_audit(game_results))
    summary["position_quality"] = _position_quality_summary(classification_rows)
    summary["stage_game_win_rates"] = _stage_game_win_rates(game_results, autorun_threshold=autorun_threshold)
    summary["poison_detection"] = _poison_detection_summary(classification_rows)
    summary["retrain_stability_report"] = _retrain_stability_report(summary)
    summary["checkpoint_consistency"] = _checkpoint_consistency_report(summary)
    summary["stability"] = _stability_summary(summary)
    summary["runtime_metrics"] = _runtime_metrics_summary(summary)
    summary["reproducibility"] = _reproducibility_summary(summary)
    summary["engine_verdict"] = _engine_verdict(summary)
    summary["promotion_gate"] = _promotion_gate_summary(summary)
    summary["suitable_for_production_self_learning"] = summary["engine_verdict"] == "PASS" and bool(summary["promotion_gate"].get("passed"))
    _json_dump(engine_dir / "summary.json", summary)
    _write_engine_report(engine_dir, summary)
    return summary


def main() -> int:
    args = parse_args()
    skip_autorun_benchmark = bool(args.fast_retrain or args.skip_autorun_benchmark)
    skip_autorun_promote = bool(args.fast_retrain or args.skip_autorun_promote or skip_autorun_benchmark)
    skip_retrain_benchmark_snapshots = bool(args.fast_retrain or args.skip_retrain_benchmark_snapshots)
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    output_root = Path(args.output_root).expanduser().resolve() if args.output_root else (Path("/tmp") / f"chess_live_learning_validation_{stamp}")
    output_root.mkdir(parents=True, exist_ok=True)
    runtime_root = output_root / "_runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    _progress(f"output root: {output_root}")
    _progress(f"runtime root: {runtime_root}")
    _progress(
        "flags: "
        f"fast_retrain={bool(args.fast_retrain)} "
        f"quick_retrain_gate={bool(args.quick_retrain_gate)} "
        f"skip_autorun_benchmark={skip_autorun_benchmark} "
        f"skip_autorun_promote={skip_autorun_promote} "
        f"skip_retrain_benchmark_snapshots={skip_retrain_benchmark_snapshots}"
    )
    try:
        engines = _select_requested_engines(str(args.engines or ""), allow_multi_engine=bool(args.allow_multi_engine))
    except ValueError as exc:
        _progress(f"FAIL: {exc}")
        _progress("failure hint: pass exactly one --engines alias, or use --allow-multi-engine intentionally")
        return 2
    _progress(f"selected engines: {', '.join(alias for alias, _difficulty in engines)}")
    summaries = []
    for index, (engine_alias, difficulty) in enumerate(engines, start=1):
        engine_dir = output_root / engine_alias
        engine_dir.mkdir(parents=True, exist_ok=True)
        _progress(f"phase engine validation started: {engine_alias} difficulty={difficulty} artifact={engine_dir}")
        if args.quick_retrain_gate:
            if engine_alias not in RETRAIN_ENGINE_ALIASES:
                _progress("FAIL: --quick-retrain-gate currently supports exp3 and exp4 only; exp5 retrain design is pending")
                return 2
            summary = _run_quick_retrain_gate_validation(
                engine_alias=engine_alias,
                difficulty=difficulty,
                engine_dir=engine_dir,
                runtime_root=runtime_root,
                seed=int(args.seed) + index * 1000,
                wait_timeout=int(args.wait_timeout),
                quick_retrain_max_samples=int(args.quick_retrain_max_samples),
                quick_retrain_max_seconds=int(args.quick_retrain_max_seconds),
                semantic_specialist_probes=bool(args.semantic_specialist_probes),
                kingside_development_audit=bool(args.kingside_development_audit),
                skip_heavy_sanity=bool(args.quick_retrain_skip_heavy_sanity),
            )
        else:
            summary = _run_engine_validation(
                engine_alias=engine_alias,
                difficulty=difficulty,
                engine_dir=engine_dir,
                runtime_root=runtime_root,
                seed=int(args.seed) + index * 1000,
                max_plies=int(args.max_plies),
                wait_timeout=int(args.wait_timeout),
                autorun_threshold=int(args.autorun_threshold),
                skip_autorun_benchmark=skip_autorun_benchmark,
                skip_autorun_promote=skip_autorun_promote,
                skip_retrain_benchmark_snapshots=skip_retrain_benchmark_snapshots,
                benchmark_rounds=int(args.benchmark_rounds),
                benchmark_max_plies=int(args.benchmark_max_plies),
                benchmark_teacher_depth=int(args.benchmark_teacher_depth),
            )
        summaries.append(summary)
        _progress(f"phase result engine validation {engine_alias}: verdict={summary.get('engine_verdict')} artifact={engine_dir / 'summary.json'}")
    root_summary = _build_root_summary(
        output_root=output_root,
        summaries=summaries,
        skip_autorun_benchmark=skip_autorun_benchmark,
        skip_autorun_promote=skip_autorun_promote,
        skip_retrain_benchmark_snapshots=skip_retrain_benchmark_snapshots,
        benchmark_rounds=int(args.benchmark_rounds),
        benchmark_max_plies=int(args.benchmark_max_plies),
        benchmark_teacher_depth=int(args.benchmark_teacher_depth),
    )
    _write_root_report(output_root, root_summary, summaries)
    _progress(f"phase result report: json={output_root / 'summary.json'} md={output_root / 'SUMMARY.md'}")
    print(json.dumps(root_summary, ensure_ascii=False, indent=2))
    _progress(f"phase result validation: {root_summary.get('overall_verdict')}")
    return 0
    root_summary = {
        "ok": True,
        "generated_at": _utc_now(),
        "output_root": str(output_root),
        "fast_retrain": bool(skip_autorun_benchmark or skip_autorun_promote),
        "skip_autorun_benchmark": bool(skip_autorun_benchmark),
        "skip_autorun_promote": bool(skip_autorun_promote),
        "skip_retrain_benchmark_snapshots": bool(skip_retrain_benchmark_snapshots),
        "timing": {
            "total_retrain_seconds": round(sum(float((summary.get("retrain_timing") or {}).get("total_retrain_seconds") or 0.0) for summary in summaries), 3),
            "total_checkpoint_seconds": round(sum(float((summary.get("retrain_timing") or {}).get("total_checkpoint_seconds") or 0.0) for summary in summaries), 3),
            "avg_game_think_ms_per_step": round(
                sum(float((summary.get("game_timing") or {}).get("total_think_ms") or 0.0) for summary in summaries)
                / max(1, sum(int((summary.get("game_timing") or {}).get("steps_measured") or 0) for summary in summaries)),
                3,
            ),
            "think_steps_measured": sum(int((summary.get("game_timing") or {}).get("steps_measured") or 0) for summary in summaries),
        },
        "environment": _environment_summary(),
        "engines": [
            {
                "engine_alias": summary["engine_alias"],
                "difficulty": summary["difficulty"],
                "engine_verdict": summary.get("engine_verdict"),
                "replay_learning_supported": bool(summary.get("retrain_result", {}).get("retrain_supported")),
                "effective_samples": int(summary.get("dataset_result", {}).get("accepted_rows") or 0),
                "rejected_samples": int(summary.get("dataset_result", {}).get("rejected_rows") or 0),
                "trusted_replays": summary["replay_summary"]["trusted_replays"],
                "quarantine_replays": summary["replay_summary"]["quarantine_replays"],
                "autorun_status": summary["autorun_status"].get("status", ""),
                "agreement_before": summary["evaluation_before"].get("agreement"),
                "agreement_after": summary["evaluation_after"].get("agreement"),
                "avg_think_ms_before": summary["evaluation_before"].get("avg_think_ms"),
                "avg_think_ms_after": summary["evaluation_after"].get("avg_think_ms"),
                "avg_game_think_ms_per_step": (summary.get("game_timing") or {}).get("avg_think_ms_per_step"),
                "think_steps_measured": (summary.get("game_timing") or {}).get("steps_measured"),
                "total_retrain_seconds": (summary.get("retrain_timing") or {}).get("total_retrain_seconds"),
                "avg_retrain_seconds": (summary.get("retrain_timing") or {}).get("avg_retrain_seconds"),
                "total_checkpoint_seconds": (summary.get("retrain_timing") or {}).get("total_checkpoint_seconds"),
                "promotion_gate_passed": (summary.get("promotion_gate") or {}).get("passed"),
                "promotion_gate_reasons": (summary.get("promotion_gate") or {}).get("reasons") or [],
                "catastrophic_regression": (summary.get("stability") or {}).get("catastrophic_regression"),
                "can_be_promoted": _promotion_explanation(summary),
                "dataset_duplicate_ratio": (summary.get("dataset_integrity") or {}).get("duplicate_ratio"),
                "dataset_illegal_moves": (summary.get("dataset_integrity") or {}).get("illegal_moves"),
                "suspicious_resign_rate": (summary.get("poison_detection") or {}).get("suspicious_resign_rate"),
                "win_rate_before": (summary.get("before_after_eval", {}).get("benchmark_before") or {}).get("win_rate"),
                "win_rate_after": (summary.get("before_after_eval", {}).get("benchmark_after") or {}).get("win_rate"),
                "legal_rate_before": (summary.get("before_after_eval", {}).get("benchmark_before") or {}).get("legal_rate"),
                "legal_rate_after": (summary.get("before_after_eval", {}).get("benchmark_after") or {}).get("legal_rate"),
                "low_quality_rate_before": (summary.get("before_after_eval", {}).get("benchmark_before") or {}).get("low_quality_rate"),
                "low_quality_rate_after": (summary.get("before_after_eval", {}).get("benchmark_after") or {}).get("low_quality_rate"),
                "checkpoint_count": len(summary.get("before_after_eval", {}).get("checkpoints") or []),
                "invalid_train_entries": sum(1 for row in (summary.get("invalid_case_audit") or []) if row.get("entered_train_dataset")),
                "learning_changed": (
                    summary.get("evaluation_after", {}).get("agreement") != summary.get("evaluation_before", {}).get("agreement")
                    or summary.get("model_after", {}).get("sha256") != summary.get("model_before", {}).get("sha256")
                ),
                "benchmark_skipped": _summary_benchmark_skipped(summary),
                "benchmark_changed": _summary_benchmark_changed(summary),
                "meets_expectation": (
                    summary["replay_summary"]["trusted_replays"] == VALID_GAMES
                    and summary["replay_summary"]["quarantine_replays"] == INVALID_GAMES
                    and (
                        not summary.get("retrain_result", {}).get("retrain_supported")
                        or (
                            (summary.get("retrain_result", {}).get("trainer_probe", {}).get("validation", {}) or {}).get("accepted_samples_gt_zero")
                            and (summary.get("retrain_result", {}).get("trainer_probe", {}).get("validation", {}) or {}).get("rejected_samples_match")
                            and (
                                summary.get("evaluation_after", {}).get("agreement")
                                != summary.get("evaluation_before", {}).get("agreement")
                                or summary.get("model_after", {}).get("sha256")
                                != summary.get("model_before", {}).get("sha256")
                            )
                            and (
                                len(summary.get("before_after_eval", {}).get("checkpoints") or []) >= max(1, VALID_GAMES // max(1, int(summary.get("autorun_threshold") or 1)))
                            )
                            and _summary_benchmark_expectation_met(summary)
                        )
                    )
                ),
                "suitable_for_production_self_learning": bool(summary.get("suitable_for_production_self_learning")),
            }
            for summary in summaries
        ],
    }
    overall_verdict = "PASS"
    engine_verdicts = [str(row.get("engine_verdict") or "") for row in root_summary["engines"]]
    if any(verdict == "FAIL" for verdict in engine_verdicts):
        overall_verdict = "FAIL"
    elif any(bool(row.get("catastrophic_regression")) for row in root_summary["engines"]):
        overall_verdict = "HIGH_RISK"
    elif any(verdict in {"PARTIAL", "HIGH_RISK", "PARTIAL_POLICY_LEARNED_BUT_DECISION_UNCHANGED"} for verdict in engine_verdicts) or any(not bool(row.get("promotion_gate_passed")) for row in root_summary["engines"]):
        overall_verdict = "PARTIAL"
    root_summary["overall_verdict"] = overall_verdict
    _json_dump(output_root / "summary.json", root_summary)
    lines = [
        "# Chess Live Learning Validation",
        "",
        f"- generated_at: `{root_summary['generated_at']}`",
        f"- output_root: `{root_summary['output_root']}`",
        f"- overall_verdict: `{root_summary['overall_verdict']}`",
        f"- total_retrain_seconds: `{root_summary['timing']['total_retrain_seconds']}`",
        f"- avg_game_think_ms_per_step: `{root_summary['timing']['avg_game_think_ms_per_step']}`",
        f"- think_steps_measured: `{root_summary['timing']['think_steps_measured']}`",
        "",
        "## Engines",
        "",
    ]
    for row in root_summary["engines"]:
        lines.append(
            f"- {row['engine_alias']} `{row['difficulty']}` "
            f"verdict=`{row['engine_verdict']}` "
            f"support=`{row['replay_learning_supported']}` "
            f"checkpoints=`{row['checkpoint_count']}` "
            f"accepted=`{row['effective_samples']}` rejected=`{row['rejected_samples']}` "
            f"win `{row['win_rate_before']}` -> `{row['win_rate_after']}` "
            f"legal `{row['legal_rate_before']}` -> `{row['legal_rate_after']}` "
            f"think_ms `{row['avg_think_ms_before']}` -> `{row['avg_think_ms_after']}` "
            f"game_step_think_ms=`{row['avg_game_think_ms_per_step']}` "
            f"retrain_s=`{row['total_retrain_seconds']}` "
            f"low_quality `{row['low_quality_rate_before']}` -> `{row['low_quality_rate_after']}` "
            f"learning_changed=`{row['learning_changed']}` "
            f"benchmark_skipped=`{row['benchmark_skipped']}` "
            f"benchmark_changed=`{row['benchmark_changed']}` "
            f"promotion_gate=`{row['promotion_gate_passed']}` "
            f"catastrophic=`{row['catastrophic_regression']}` "
            f"meets_expectation=`{row['meets_expectation']}`"
        )
    lines.extend(
        [
            "",
            "## Can This Model Be Promoted?",
            "",
        ]
    )
    for row in root_summary["engines"]:
        lines.append(f"- {row['engine_alias']}: {row['can_be_promoted']}")
    lines.extend(
        [
            "",
            "## Why This Run Failed",
            "",
        ]
    )
    failure_lines = []
    for summary in summaries:
        for reason in _failure_explanations(summary):
            if reason == "No blocking failure detected.":
                continue
            failure_lines.append(f"{summary['engine_alias']}: {reason}")
    if failure_lines:
        for line in sorted(set(failure_lines)):
            lines.append(f"- {line}")
    else:
        lines.append("- No blocking failure detected.")
    lines.extend(
        [
            "",
            "## Known Limitations",
            "",
            "- Benchmark samples are finite and still subject to variance.",
            "- Probe positions are intentionally fixed for comparability and may miss broader regressions.",
            "",
            "## False Positive Risks",
            "",
            "- Small hash or sample-count changes can overstate practical learning gains.",
            "- Tactical probe improvements may not translate to broad opening or endgame strength.",
            "",
            "## Remaining Contamination Risks",
            "",
        ]
    )
    for row in root_summary["engines"]:
        lines.append(
            f"- {row['engine_alias']}: invalid_train_entries=`{row['invalid_train_entries']}` "
            f"production_ok=`{row['suitable_for_production_self_learning']}`"
        )
    lines.extend(
        [
            "",
            "## Production Suitability",
            "",
            f"- suitable_for_production_self_learning: `{all(bool(row.get('suitable_for_production_self_learning')) for row in root_summary['engines'])}`",
        ]
    )
    (output_root / "SUMMARY.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(json.dumps(root_summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _progress(f"FAIL: {exc}")
        _progress("failure hint: inspect output_root/SUMMARY.md, per-engine summary.json, and the last phase printed above")
        raise
