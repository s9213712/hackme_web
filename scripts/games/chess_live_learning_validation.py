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
)
from services.games.chess_engine import ChessExperimentStore, EXPERIMENT_DIFFICULTY, record_experiment_learning  # noqa: E402
from services.games.chess_pipeline import latest_pipeline_autorun_status, maybe_launch_chess_train_pipeline  # noqa: E402
from services.games.chess_promotion import ensure_warm_start_chess_environment, production_engine_inventory  # noqa: E402
from services.games.chess_pv import (  # noqa: E402
    EXPERIMENT_PV_DIFFICULTY,
    choose_experiment_pv_move,
    explain_experiment_pv_decision,
    rank_experiment_pv_policy_moves,
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
SANITY_EASY_TRAIN_VARIANT_COUNT = 6
SANITY_MEDIUM_TRAIN_VARIANT_COUNT = 6
SANITY_HARD_TRAIN_VARIANT_COUNT = 3
SANITY_EARLY_HARD_TRAIN_VARIANT_COUNT = 6
SANITY_EARLY_HARD_HELD_OUT_VARIANT_COUNT = 3
SANITY_EASY_VALIDATION_VARIANT_COUNT = 3
SANITY_MEDIUM_VALIDATION_VARIANT_COUNT = 3
SANITY_HARD_VARIANT_COUNT = 6
SANITY_VARIANT_DIFFICULTY_PAIRS = {"easy": 1, "medium": 2, "hard": 3}
SANITY_COMMON_HARD_NEGATIVES = ("e7e5", "d7d5", "c7c5", "a7a5", "f8a3", "b8c6", "h7h5", "a6c4", "c6b4", "e5d4", "f8b4", "c5d4")
FUSION_MODES = ("strict_search", "balanced_fusion", "policy_preferred")
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


def _progress(message: str) -> None:
    sys.stderr.write(f"[chess-live-learning-validation] {message}\n")
    sys.stderr.flush()


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
    parser.add_argument("--engines", default="", help="Required engine alias. Use one of: exp1,exp3,exp4. exp2 was removed in favor of exp3.")
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
    return parser.parse_args()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_dump(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _jsonl_dump(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
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
                        "game_id": int(record.get("match_id") or 0),
                        "game_label": str(record.get("replay_id") or ""),
                        "category": str(record.get("quick_category") or "unknown"),
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
    }


def _trainer_key(engine_alias: str) -> str:
    return {
        "exp3": "exp3_refine",
        "exp4": "exp4_refine",
    }[engine_alias]


def _evaluate_move_agreement(engine_alias: str, model_path: Path, samples: list[dict]) -> dict:
    if engine_alias not in {"exp1", "exp3", "exp4"}:
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
        else:
            move = choose_experiment_pv_move(board_state, str(sample["side"] or "white"), model_path=model_path, search_profile="fast")
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
        )
    return None


def _rank_deterministic_top3(engine_alias: str, board_state: dict, side: str, model_path: Path, top1_move: dict | None) -> list[str]:
    top1 = _move_uci_from_engine_move(top1_move)
    board_obj = chess.Board(str(board_state.get("__fen__") or chess.STARTING_FEN))
    legal_uci = {move.uci() for move in board_obj.legal_moves}
    scored: list[tuple[int, str]] = []
    for move in board_obj.legal_moves:
        after = board_obj.copy(stack=False)
        after.push(move)
        score = _probe_position_score({"__fen__": after.fen()}, opponent(side))
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
    for case in cases:
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
    unseen_variants = list(((final_probe.get("unseen_variants") or {}).get("cases") or []))
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
    if engine_alias not in {"exp1", "exp3", "exp4"}:
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
    ordered_samples = mistake_samples + [sample for sample in samples if sample not in mistake_samples]
    for sample in ordered_samples:
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
    if not samples:
        return {
            "supported": False,
            "reason": "no_old_samples",
            "counted_as_game": False,
            "expected_move": "",
            "before_move": "",
            "after_move": "",
            "avoided_old_mistake": False,
            "avoided_same_error": False,
            "matched_expected": False,
            "result_kind": "fail",
            "learning_signal": False,
            "learning_signal_reason": "no old trusted move sample was available for a mistake-retention probe",
            "human_explanation": "目前沒有足夠證據證明 retrain 改善了該錯誤，因為沒有可重測的舊題目。",
        }
    sample = _select_mistake_probe_sample(engine_alias, before_model_path, samples)
    if not sample:
        sample = dict(samples[0])
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
            "supported": retained_expected,
            "reason": "retained_expected_move" if retained_expected else "regressed_from_expected_move" if regressed_from_expected else "no_prior_mistake_sample",
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
            "avoided_old_mistake": False,
            "avoided_same_error": False,
            "matched_expected": after_uci == expected_move,
            "result_kind": "retained_expected" if retained_expected else "regressed_from_expected" if regressed_from_expected else "not_prior_mistake",
            "model_response_changed": before_uci != after_uci,
            "sample_count": len(samples),
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
    board_state = {"__fen__": str(sample.get("fen") or "")}
    side = str(sample.get("side") or "white")
    expected_move = str(sample.get("move_uci") or "").lower()
    before_uci = str(sample.get("before_move") or "")
    after_move = _choose_engine_move_for_eval(engine_alias, board_state, side, after_model_path)
    after_uci = _move_uci(after_move or {})
    before_failed = before_uci != expected_move
    after_fixed = after_uci == expected_move
    avoided_old_mistake = bool(before_failed and after_uci != before_uci)
    avoided_same_error = avoided_old_mistake
    matched_expected = bool(after_fixed)
    probe_case_id = f"game:{int(sample.get('game_id') or 0)}:ply:{int(sample.get('ply') or 0)}:{expected_move}"
    if before_failed and after_fixed:
        result_kind = "matched_expected"
        reason = "before model failed the old mistake case and after model selected the expected move"
        explanation = "舊錯題已被修正，這提供 retrain 改善該錯誤的直接證據。"
    elif before_failed and avoided_old_mistake:
        result_kind = "avoided_old_but_not_expected"
        reason = "after model avoided the same wrong move but still did not select the expected move"
        explanation = "模型避開了同一個錯誤，但尚未走到預期正解，因此不能視為學習成功。"
    elif before_failed:
        result_kind = "repeated_old_mistake"
        reason = "after model repeated the same wrong move"
        explanation = "目前沒有足夠證據證明 retrain 改善了該錯誤，因為 after model 仍重複同一錯誤。"
    else:
        result_kind = "not_prior_mistake"
        reason = "selected probe was not a prior mistake"
        explanation = "目前沒有足夠證據證明 retrain 改善了該錯誤，因為此 probe 不是 before model 的舊錯題。"
    return {
        "supported": True,
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
        "before_failed": before_failed,
        "after_fixed": after_fixed,
        "avoided_old_mistake": avoided_old_mistake,
        "avoided_same_error": avoided_same_error,
        "matched_expected": matched_expected,
        "result_kind": result_kind,
        "model_response_changed": before_uci != after_uci,
        "learning_signal": bool(before_failed and matched_expected),
        "learning_signal_reason": reason,
        "human_explanation": explanation,
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
    for candidate_index, decoy_move in enumerate(legal_quiet, start=1):
        if candidate_index <= int(offset):
            continue
        variant_board, variation_moves = _build_sanity_variant_board(
            base_board,
            expected_move=expected_move,
            first_decoy=decoy_move,
            difficulty=difficulty,
            candidate_index=candidate_index,
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


def _sanity_label_quality_audit(variants: list[dict]) -> dict:
    rows = []
    warnings = []
    for variant in variants or []:
        fen = str(variant.get("fen") or "")
        side = str(variant.get("side") or "")
        expected = str(variant.get("expected_move") or "").lower()
        try:
            board = chess.Board(fen)
            board.turn = chess.WHITE if side == "white" else chess.BLACK
            expected_move = chess.Move.from_uci(expected)
        except Exception as exc:
            rows.append({"case_id": variant.get("case_id"), "expected_move": expected, "legal": False, "label_quality_warning": True, "reason": str(exc)})
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
            rows.append({"case_id": variant.get("case_id"), "expected_move": expected, "legal": False, "label_quality_warning": True, "reason": "expected move is illegal"})
            warnings.append(f"{variant.get('case_id')}: expected move {expected} is illegal")
            continue
        expected_score = material_after(expected_move)
        best_score = max((material_after(move) for move in board.legal_moves), default=expected_score)
        static_delta = int(expected_score - best_score)
        warning = static_delta < -300
        if warning:
            warnings.append(f"{variant.get('case_id')}: expected move static material delta {static_delta}cp vs best legal")
        rows.append(
            {
                "case_id": variant.get("case_id"),
                "variant_split": variant.get("variant_split"),
                "variant_difficulty": variant.get("variant_difficulty"),
                "expected_move": expected,
                "legal": True,
                "static_delta_vs_best_cp": static_delta,
                "label_quality_warning": warning,
                "reason": "expected move appears materially questionable" if warning else "expected move is legal and not materially dominated",
            }
        )
    return {
        "checked_count": len(rows),
        "warning_count": len([row for row in rows if row.get("label_quality_warning")]),
        "label_quality_warning": bool(warnings),
        "warnings": warnings,
        "cases": rows,
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
    hard_held_out_count = SANITY_EARLY_HARD_HELD_OUT_VARIANT_COUNT if early_warmup else SANITY_HARD_VARIANT_COUNT
    hard_train = _sanity_learning_variants(
        case,
        limit=hard_train_count,
        offset=0,
        split="train",
        difficulty="hard",
    )
    train = easy_train + medium_train + hard_train
    train_hashes = {str(row.get("normalized_fen_hash") or "") for row in train}
    hard_candidates = _sanity_learning_variants(
        case,
        limit=SANITY_HARD_VARIANT_COUNT * 3,
        offset=hard_train_count,
        split="held_out",
        difficulty="hard",
    )
    hard_held_out = []
    seen_held_hashes: set[str] = set()
    for variant in hard_candidates:
        variant_hash = str(variant.get("normalized_fen_hash") or "")
        if not variant_hash or variant_hash in train_hashes or variant_hash in seen_held_hashes:
            continue
        hard_held_out.append(variant)
        seen_held_hashes.add(variant_hash)
        if len(hard_held_out) >= hard_held_out_count:
            break
    validation = easy_validation + medium_validation
    held_out = hard_held_out
    return {
        "train": train,
        "validation": validation,
        "held_out": held_out,
        "seen": train,
        "unseen": validation + held_out,
        "split_counts": {
            "train": len(train),
            "validation": len(validation),
            "held_out": len(held_out),
        },
        "warmup": {
            "trusted_replays": int(trusted_replays or 0),
            "early_checkpoint_warmup": early_warmup,
            "hard_train_variant_count": hard_train_count,
            "hard_held_out_variant_count": hard_held_out_count,
            "note": "checkpoint@10 uses fewer hard held-out cases and more hard train warmup; checkpoint@20 uses the full hard held-out gate",
        },
        "by_difficulty": {
            "easy": {"train": easy_train, "validation": easy_validation, "held_out": [], "seen": easy_train, "unseen": easy_validation},
            "medium": {"train": medium_train, "validation": medium_validation, "held_out": [], "seen": medium_train, "unseen": medium_validation},
            "hard": {"train": hard_train, "validation": [], "held_out": hard_held_out, "seen": hard_train, "unseen": hard_held_out},
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
            "hard_negatives": exact_hard_negatives,
            "invariance_group_id": invariance_group_id,
            "pairwise_role": "positive_anchor",
            "curriculum_stage": "exact_fen",
        }
    ]
    for variant in train_variants:
        hard_negatives = _legal_sanity_hard_negatives(
            variant["fen"],
            variant["side"],
            variant["expected_move"],
            old_move=old_move,
            limit=hard_negative_limit,
        )
        rows.append(
            {
                "fen": variant["fen"],
                "side": variant["side"],
                "move_uci": variant["expected_move"],
                "target": 1.0,
                "weight": 1.45 if variant.get("variant_difficulty") == "easy" else 1.3 if variant.get("variant_difficulty") == "medium" else 1.1,
                "source": "sanity_curriculum_variant_replay",
                "category": "mistake_retention",
                "case_id": case.get("case_id"),
                "variant_id": variant.get("variant_id"),
                "variant_split": "train",
                "variant_difficulty": variant.get("variant_difficulty"),
                "normalized_fen_hash": variant.get("normalized_fen_hash"),
                "expected_move": variant["expected_move"],
                "hard_negatives": hard_negatives,
                "invariance_group_id": invariance_group_id,
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
                "hard_negatives": prior_hard_negatives,
                "invariance_group_id": _sanity_invariance_group_id(prior_case),
                "pairwise_role": "retention_anchor",
                "curriculum_stage": "prior_exact_retention",
            }
        )
    rows.extend(retention_rows)
    return {
        "case": case,
        "before_exact": before_exact,
        "rows": rows,
        "seen_variants": train_variants,
        "train_variants": train_variants,
        "retention_rows": retention_rows,
        "curriculum": curriculum,
        "smoothing": {
            "trusted_replays": int(trusted_replays or 0),
            "hard_negative_limit": hard_negative_limit,
            "retention_rows_added": len(retention_rows),
            "hard_train_variants_added": len([row for row in train_variants if str(row.get("variant_difficulty") or "") == "hard"]),
            "early_checkpoint_warmup": bool((curriculum.get("warmup") or {}).get("early_checkpoint_warmup")),
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
    before_seen_variants = [_evaluate_sanity_learning_position(engine_alias, before_model_path, variant) for variant in seen_variants]
    after_seen_variants = [_evaluate_sanity_learning_position(engine_alias, after_model_path, variant) for variant in seen_variants]
    before_unseen_variants = [_evaluate_sanity_learning_position(engine_alias, before_model_path, variant) for variant in unseen_variants]
    after_unseen_variants = [_evaluate_sanity_learning_position(engine_alias, after_model_path, variant) for variant in unseen_variants]
    raw_seen_before = [_evaluate_engine_raw_policy_position(engine_alias, before_model_path, variant, old_move=old_move) for variant in seen_variants]
    raw_unseen_before = [_evaluate_engine_raw_policy_position(engine_alias, before_model_path, variant, old_move=old_move) for variant in unseen_variants]
    raw_seen_after = [_evaluate_engine_raw_policy_position(engine_alias, after_model_path, variant, old_move=old_move) for variant in seen_variants]
    raw_unseen_after = [_evaluate_engine_raw_policy_position(engine_alias, after_model_path, variant, old_move=old_move) for variant in unseen_variants]
    label_quality = _sanity_label_quality_audit(unseen_variants)
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
    generalized = bool(exact_learned and seen_passed and unseen_passed)
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
                "final_top1": final_row.get("top1"),
                "final_top3": final_row.get("top3"),
                "raw_policy_top1": raw_row.get("raw_policy_top1"),
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
    for variant, raw_before_row, raw_after_row in zip(
        [case] + seen_variants + unseen_variants,
        [raw_before] + raw_seen_before + raw_unseen_before,
        [raw_after] + raw_seen_after + raw_unseen_after,
    ):
        hard_negatives = _legal_sanity_hard_negatives(
            str(variant.get("fen") or ""),
            str(variant.get("side") or ""),
            str(variant.get("expected_move") or ""),
            old_move=old_move,
        )
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
                "hard_negative": negative,
                "margin_before": margin_before,
                "margin_after": margin_after,
                "margin_delta": round(margin_after - float(margin_before), 8) if margin_before is not None else None,
                "expected_rank_before": raw_before_row.get("expected_rank"),
                "expected_rank_after": raw_after_row.get("expected_rank"),
            }
            margins.append(
                {
                    "hard_negative": negative,
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
    if generalized:
        result_kind = "generalized_to_variants"
        explanation = "模型修正原始 FEN，且 seen/unseen 相似變體都達到泛化門檻。"
    elif exact_learned and seen_passed and unseen_count == 0:
        result_kind = "partial_seen_variants_only"
        explanation = "模型修正原始 FEN 並通過 seen variants，但沒有 unseen variants，不能證明泛化。"
    elif exact_learned and seen_passed:
        result_kind = "partial_seen_variants_only"
        explanation = "模型修正原始 FEN 並通過 seen variants，但 unseen variants 未達門檻，不能 promotion。"
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
            },
            "label_quality": label_quality,
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
            else "exact FEN and seen variants passed, but unseen generalization was not proven"
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
        "final_unseen_min": SANITY_UNSEEN_VARIANT_PASS_THRESHOLD,
        "hard_held_out_min_exclusive": 0.0,
        "embedding_drift_drop_limit": -0.05,
        "policy_margin_min": 0.0,
    }
    for checkpoint in checkpoints:
        trusted = checkpoint.get("trusted_count") or checkpoint.get("trusted_replays")
        probe = checkpoint.get("sanity_learning_probe") or {}
        training = checkpoint.get("sanity_variant_training") or {}
        prior_retention = probe.get("prior_learned_case_retention") or {}
        exact_retention = bool(probe.get("exact_fen_pass"))
        seen_retention = float(probe.get("seen_variant_pass_rate") or 0.0)
        unseen_retention = float(probe.get("final_decision_unseen_generalization_rate") or 0.0)
        raw_unseen_retention = float(probe.get("raw_policy_unseen_generalization_rate") or 0.0)
        hard_retention = float(probe.get("hard_unseen_pass_rate") or 0.0)
        prior_failed = int(prior_retention.get("failed_count") or 0)
        embedding_after = _checkpoint_probe_embedding_after(probe)
        embedding_delta = _checkpoint_probe_embedding_delta(probe)
        hard_margin = _checkpoint_probe_hard_negative_margin(probe)
        feature_debug = probe.get("feature_generalization_debug") or {}
        hard_margin_debug = feature_debug.get("expected_vs_hard_negative_margin") or {}
        label_quality = feature_debug.get("label_quality") or {}
        row_reasons: list[str] = []
        if not exact_retention:
            row_reasons.append("exact retention failed")
        if seen_retention < SANITY_SEEN_VARIANT_PASS_THRESHOLD:
            row_reasons.append("seen retention below threshold")
        if unseen_retention < SANITY_UNSEEN_VARIANT_PASS_THRESHOLD:
            row_reasons.append("final unseen retention below threshold")
        if hard_retention <= 0.0:
            row_reasons.append("hard held-out retention is zero")
        if prior_failed > 0:
            row_reasons.append("prior learned case retention regressed")
        if hard_margin is not None and hard_margin < 0.0:
            row_reasons.append("hard-negative margin is negative")
        if embedding_delta is not None and embedding_delta < thresholds["embedding_drift_drop_limit"]:
            row_reasons.append("embedding similarity decreased after retrain")
        row = {
            "trusted_count": trusted,
            "exact_retention": exact_retention,
            "seen_retention": round(seen_retention, 4),
            "unseen_retention": round(unseen_retention, 4),
            "raw_unseen_retention": round(raw_unseen_retention, 4),
            "hard_held_out_retention": round(hard_retention, 4),
            "result_kind": probe.get("result_kind"),
            "prior_retention_failed_count": prior_failed,
            "hard_negative_min_margin": round(hard_margin, 6) if hard_margin is not None else None,
            "embedding_similarity_after": round(embedding_after, 6) if embedding_after is not None else None,
            "embedding_similarity_delta": round(embedding_delta, 6) if embedding_delta is not None else None,
            "hard_negative_margin_table": hard_margin_debug.get("hard_negative_margin_table") or [],
            "early_checkpoint_failure_analysis": feature_debug.get("early_checkpoint_failure_analysis") or {},
            "embedding_similarity_delta_by_group": feature_debug.get("embedding_similarity_delta_by_group") or {},
            "invariance_context_key_examples": training.get("invariance_context_key_examples") or [],
            "label_quality": label_quality,
            "label_quality_warning": bool(label_quality.get("label_quality_warning")),
            "curriculum_split": training.get("split") or {},
            "smoothing": training.get("sanity_smoothing") or training.get("smoothing") or {},
            "passed": not row_reasons,
            "reasons": row_reasons,
        }
        if previous_row:
            unseen_delta = round(row["unseen_retention"] - previous_row["unseen_retention"], 4)
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
                row["reasons"].append("final unseen retention dropped from previous checkpoint")
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
            elif float(sanity_probe.get("unseen_variant_pass_rate") or 0.0) < SANITY_UNSEEN_VARIANT_PASS_THRESHOLD:
                reasons.append(f"sanity unseen variant pass rate below threshold at trusted={trusted}")
            if float(sanity_probe.get("raw_policy_unseen_generalization_rate") or 0.0) < SANITY_UNSEEN_VARIANT_PASS_THRESHOLD:
                reasons.append(f"sanity raw policy unseen generalization below threshold at trusted={trusted}")
            if float(sanity_probe.get("final_decision_unseen_generalization_rate") or 0.0) < SANITY_UNSEEN_VARIANT_PASS_THRESHOLD:
                reasons.append(f"sanity final decision unseen generalization below threshold at trusted={trusted}")
            if float(sanity_probe.get("hard_unseen_pass_rate") or 0.0) <= 0.0:
                reasons.append(f"sanity hard held-out pass rate is zero at trusted={trusted}")
            if float(sanity_probe.get("final_decision_generalization_rate") or 0.0) < SANITY_FINAL_DECISION_GENERALIZATION_THRESHOLD:
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
        "fusion_mode_comparison": summary.get("fusion_mode_comparison") or {},
        "stochastic_auxiliary_benchmark": summary.get("stochastic_auxiliary_benchmark") or {},
        "perft": summary.get("perft") or {},
        "retrain_stability_report": summary.get("retrain_stability_report") or {},
        "checkpoint_consistency": summary.get("checkpoint_consistency") or {},
        "replay_fixture_health": summary.get("replay_fixture_health") or {},
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
                f"embedding_after=`{item.get('embedding_similarity_after')}` "
                f"margin=`{item.get('hard_negative_min_margin')}` passed=`{item.get('passed')}`"
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
        if (row.get("replay_fixture_health") or {}) != (summary.get("replay_fixture_health") or {}):
            issues.append(f"{alias}: replay fixture health mismatch")
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
    else:
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp4_dataset_train.py"),
            "--input-jsonl",
            str(probe_dataset_path),
            "--model-path",
            str(probe_model_path),
        ]
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
                f"prior_failed=`{item.get('prior_retention_failed_count')}` "
                f"embedding_after=`{item.get('embedding_similarity_after')}` "
                f"embedding_delta=`{item.get('embedding_similarity_delta')}` "
                f"policy_margin=`{item.get('hard_negative_min_margin')}` passed=`{item.get('passed')}`"
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
            lines.append(
                f"- trusted=`{item.get('trusted_count')}` checked=`{quality.get('checked_count')}` "
                f"warnings=`{quality.get('warning_count')}` label_quality_warning=`{quality.get('label_quality_warning')}`"
            )
            for warning in quality.get("warnings") or []:
                lines.append(f"- trusted=`{item.get('trusted_count')}` label_warning: `{warning}`")
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
) -> tuple[dict, Path]:
    checkpoint_started = time.perf_counter()
    checkpoint_started_at = _utc_now()
    checkpoint_dir = engine_dir / "checkpoints" / f"{trusted_replays:02d}"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    fixture_write = _write_quick_replay_fixture(records, trusted_count=trusted_replays)
    dataset_result = _prepare_formal_dataset(engine_dir, runtime_dir, artifact_dir=checkpoint_dir, invalid_game_ids=set())
    accepted_rows = _read_jsonl(checkpoint_dir / "train_dataset.jsonl")
    rejected_rows = _read_jsonl(checkpoint_dir / "rejected_dataset.jsonl")
    before_model_meta = _model_meta(target_model_path)
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
        dataset_result["sanity_curriculum_rows"] = len(variant_rows)
        dataset_result["sanity_train_variant_rows"] = len([row for row in variant_rows if str(row.get("variant_split") or "") == "train"])
        dataset_result["sanity_seen_variant_rows"] = dataset_result["sanity_train_variant_rows"]
        dataset_result["sanity_exact_rows"] = len([row for row in variant_rows if str(row.get("variant_split") or "") == "exact"])
        dataset_result["sanity_train_variant_hashes"] = [str(row.get("normalized_fen_hash") or "") for row in variant_rows if str(row.get("variant_split") or "") == "train"]
        dataset_result["sanity_seen_variant_hashes"] = dataset_result["sanity_train_variant_hashes"]
        dataset_result["sanity_hard_negative_count"] = sum(len(row.get("hard_negatives") or []) for row in variant_rows)
        dataset_result["sanity_supervised_split"] = {
            "train": len((variant_training.get("curriculum") or {}).get("train") or []),
            "validation": len((variant_training.get("curriculum") or {}).get("validation") or []),
            "held_out": len((variant_training.get("curriculum") or {}).get("held_out") or []),
            "held_out_in_training": False,
        }
    move_agreement_before = _evaluate_move_agreement(engine_alias, target_model_path, evaluation_samples)
    fixed_probes_before = _evaluate_fixed_probe_positions(engine_alias, target_model_path)
    replay_loss_before = _quick_replay_loss(engine_alias, target_model_path, accepted_rows)
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
    else:
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp4_dataset_train.py"),
            "--input-jsonl",
            str(checkpoint_dir / "train_dataset.jsonl"),
            "--model-path",
            str(candidate_model_path),
            "--max-samples",
            str(max(1, int(max_samples))),
        ]
        trainer_epochs = 1
        trainer_learning_rate = 0.008
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
    retrain_duration_seconds = round(time.perf_counter() - retrain_started, 3)
    retrain_finished_at = _utc_now()
    after_model_meta = _model_meta(candidate_model_path)
    replay_loss_after = _quick_replay_loss(engine_alias, candidate_model_path, accepted_rows)
    move_agreement_after = _evaluate_move_agreement(engine_alias, candidate_model_path, evaluation_samples)
    fixed_probes_after = _evaluate_fixed_probe_positions(engine_alias, candidate_model_path)
    retention_probe = _evaluate_retention_probe(engine_alias, target_model_path, candidate_model_path, evaluation_samples)
    mistake_retention_probe = _evaluate_mistake_retention_probe(engine_alias, target_model_path, candidate_model_path, evaluation_samples)
    sanity_learning_probe = _evaluate_sanity_learning_probe(
        engine_alias,
        target_model_path,
        candidate_model_path,
        evaluation_samples,
        trusted_replays=int(trusted_replays),
    )
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
    elif float(sanity_learning_probe.get("unseen_variant_pass_rate") or 0.0) < SANITY_UNSEEN_VARIANT_PASS_THRESHOLD:
        checkpoint_gate["passed"] = False
        checkpoint_gate.setdefault("reasons", []).append("sanity unseen variant pass rate below threshold")
    if float(sanity_learning_probe.get("raw_policy_unseen_generalization_rate") or 0.0) < SANITY_UNSEEN_VARIANT_PASS_THRESHOLD:
        checkpoint_gate["passed"] = False
        checkpoint_gate.setdefault("reasons", []).append("sanity raw policy unseen generalization below threshold")
    if float(sanity_learning_probe.get("final_decision_unseen_generalization_rate") or 0.0) < SANITY_UNSEEN_VARIANT_PASS_THRESHOLD:
        checkpoint_gate["passed"] = False
        checkpoint_gate.setdefault("reasons", []).append("sanity final decision unseen generalization below threshold")
    if float(sanity_learning_probe.get("hard_unseen_pass_rate") or 0.0) <= 0.0:
        checkpoint_gate["passed"] = False
        checkpoint_gate.setdefault("reasons", []).append("sanity hard held-out pass rate is zero")
    if (sanity_learning_probe.get("final_decision_learning") or {}).get("learning_signal") is False:
        checkpoint_gate["passed"] = False
        checkpoint_gate.setdefault("reasons", []).append("sanity final decision learning failed")
    if int((sanity_learning_probe.get("prior_learned_case_retention") or {}).get("failed_count") or 0) > 0:
        checkpoint_gate["passed"] = False
        checkpoint_gate.setdefault("reasons", []).append("prior learned sanity case retention regressed")
    if not bool(train_result.get("ok")):
        checkpoint_gate["passed"] = False
        checkpoint_gate.setdefault("reasons", []).append("quick retrain command failed")
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
        "dataset_sha256": dataset_result.get("dataset_sha256", ""),
        "dataset_hash": f"sha256:{dataset_result.get('dataset_sha256', '')}",
        "trainer_result": train_result,
        "trainer_hyperparameters": {
            "fixed_seed": int(seed),
            "epochs": trainer_epochs,
            "max_samples": max(1, int(max_samples)),
            "max_seconds": max(1, int(max_seconds)),
            "learning_rate": trainer_learning_rate,
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
        "sanity_learning_probe": sanity_learning_probe,
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
        "verdict": "PASS" if bool(train_result.get("ok")) and not checkpoint_gate.get("reasons") else "PARTIAL",
    }
    _json_dump(checkpoint_dir / "retrain_result.json", checkpoint)
    _json_dump(checkpoint_dir / "before_after_eval.json", checkpoint)
    return checkpoint, candidate_model_path


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
        )
        retrain_seconds_total += float(checkpoint.get("retrain_duration_seconds") or 0.0)
        checkpoints.append(checkpoint)

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
    fusion_mode_comparison = _fusion_mode_comparison(
        engine_alias=engine_alias,
        model_path=after_model_path,
        deterministic_cases=deterministic_cases,
        deterministic_report=deterministic_strength,
        checkpoints=checkpoints,
        seed=seed,
    )
    deterministic_eval_seconds = round(time.perf_counter() - deterministic_started, 3)
    _json_dump(engine_dir / "deterministic_strength_snapshot.json", deterministic_strength)
    _json_dump(engine_dir / "policy_override_audit.json", policy_override_audit)
    _json_dump(engine_dir / "fusion_mode_comparison.json", fusion_mode_comparison)

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
        "trainer_result": (checkpoints[-1].get("trainer_result") if checkpoints else {}),
    }
    retrain_timing = _checkpoint_timing_summary(checkpoints)
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
        "fusion_mode_comparison": fusion_mode_comparison,
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
    fusion_mode_comparison = _fusion_mode_comparison(
        engine_alias=engine_alias,
        model_path=after_model_path,
        deterministic_cases=deterministic_cases,
        deterministic_report=deterministic_strength,
        checkpoints=checkpoints,
        seed=seed,
    )
    _json_dump(engine_dir / "deterministic_strength_snapshot.json", deterministic_strength)
    _json_dump(engine_dir / "policy_override_audit.json", policy_override_audit)
    _json_dump(engine_dir / "fusion_mode_comparison.json", fusion_mode_comparison)
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
        "fusion_mode_comparison": fusion_mode_comparison,
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
            if engine_alias not in {"exp3", "exp4"}:
                _progress("FAIL: --quick-retrain-gate currently supports exp3 and exp4 only")
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
