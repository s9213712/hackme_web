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
from services.games.chess_dl import EXPERIMENT_DL_DIFFICULTY, choose_experiment_dl_move  # noqa: E402
from services.games.chess_engine import ChessExperimentStore, EXPERIMENT_DIFFICULTY, record_experiment_learning  # noqa: E402
from services.games.chess_nn import EXPERIMENT_NN_DIFFICULTY, choose_experiment_nn_move  # noqa: E402
from services.games.chess_pipeline import latest_pipeline_autorun_status, maybe_launch_chess_train_pipeline  # noqa: E402
from services.games.chess_promotion import ensure_warm_start_chess_environment, production_engine_inventory  # noqa: E402
from services.games.chess_pv import EXPERIMENT_PV_DIFFICULTY, choose_experiment_pv_move  # noqa: E402
from services.games.chess_replay_buffer import (  # noqa: E402
    build_replay_record,
    classify_replay_record,
    collect_match_replay,
    replay_buffer_summary,
)
from services.games.self_play_training import run_round_robin_benchmark  # noqa: E402


ENGINE_MATRIX = [
    ("exp1", EXPERIMENT_DIFFICULTY),
    ("exp2", EXPERIMENT_NN_DIFFICULTY),
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
RETRAIN_ENGINE_ALIASES = {"exp2", "exp3", "exp4"}
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
    parser.add_argument("--engines", default="", help="Required engine alias. Use one of: exp1,exp2,exp3,exp4.")
    parser.add_argument("--allow-multi-engine", action="store_true", help="Allow comma-separated --engines for intentional multi-engine validation.")
    parser.add_argument("--autorun-threshold", type=int, default=AUTORUN_THRESHOLD, help="Trusted replay count required before auto-retrain is launched for exp2/exp3/exp4.")
    parser.add_argument("--fast-retrain", action="store_true", help="Skip retrain checkpoint benchmarks plus autorun pipeline benchmark/promotion.")
    parser.add_argument("--skip-autorun-benchmark", action="store_true", help="Set HTML_LEARNING_CHESS_AUTORUN_SKIP_BENCHMARK=1 before launching autorun retrain.")
    parser.add_argument("--skip-autorun-promote", action="store_true", help="Set HTML_LEARNING_CHESS_AUTORUN_SKIP_PROMOTE=1 before launching autorun retrain.")
    parser.add_argument("--skip-retrain-benchmark-snapshots", action="store_true", help="Skip validation benchmark snapshots before/after each retrain checkpoint.")
    parser.add_argument("--benchmark-rounds", type=int, default=1, help="Round-robin benchmark rounds per pairing for formal validation snapshots.")
    parser.add_argument("--benchmark-max-plies", type=int, default=90, help="Maximum plies per formal benchmark game.")
    parser.add_argument("--benchmark-teacher-depth", type=int, default=2, help="Teacher search depth used by formal benchmark snapshots.")
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
        raise ValueError("pass exactly one --engines alias, e.g. --engines exp2")
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
    if summary.get("engine_alias") == "exp1":
        risk = str((summary.get("exp1_live_learning") or {}).get("contamination_risk") or "").upper()
        if risk in {"HIGH", "FAIL", "HIGH RISK"}:
            return "HIGH_RISK"
        return "PASS"
    checkpoints = summary.get("before_after_eval", {}).get("checkpoints") or []
    expected_checkpoints = max(1, VALID_GAMES // max(1, int(summary.get("autorun_threshold") or 1)))
    if len(checkpoints) < expected_checkpoints:
        return "FAIL"
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
        "exp2": "experiment 2:nn",
        "exp3": "experiment 3:dl",
        "exp4": "experiment 4:pv",
    }[engine_alias]


def _engine_model_slot(engine_alias: str) -> str:
    return {
        "exp2": "nn",
        "exp3": "dl",
        "exp4": "pv",
    }[engine_alias]


def _inventory_model_overrides(inventory_map: dict[str, dict]) -> dict[str, Path]:
    return {
        "nn": Path(str(inventory_map.get("experiment 2:nn", {}).get("path") or "")),
        "dl": Path(str(inventory_map.get("experiment 3:dl", {}).get("path") or "")),
        "pv": Path(str(inventory_map.get("experiment 4:pv", {}).get("path") or "")),
    }


def _trainer_key(engine_alias: str) -> str:
    return {
        "exp2": "exp2_refine",
        "exp3": "exp3_refine",
        "exp4": "exp4_refine",
    }[engine_alias]


def _evaluate_move_agreement(engine_alias: str, model_path: Path, samples: list[dict]) -> dict:
    if engine_alias not in {"exp1", "exp2", "exp3", "exp4"}:
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
        elif engine_alias == "exp2":
            move = choose_experiment_nn_move(board_state, str(sample["side"] or "white"), model_path=model_path)
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


def _choose_engine_move_for_eval(engine_alias: str, board_state: dict, side: str, model_path: Path) -> dict | None:
    if engine_alias == "exp1":
        return choose_computer_move(board_state, side, EXPERIMENT_DIFFICULTY, learning_store=ChessExperimentStore(db_path=model_path))
    if engine_alias == "exp2":
        return choose_experiment_nn_move(board_state, side, model_path=model_path)
    if engine_alias == "exp3":
        return choose_experiment_dl_move(board_state, side, model_path=model_path, search_profile="fast")
    if engine_alias == "exp4":
        return choose_experiment_pv_move(board_state, side, model_path=model_path, search_profile="fast")
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
    for sample in samples[:3]:
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
) -> dict:
    model_meta = _model_meta(model_path)
    rows = []
    for case in cases:
        fen = str(case.get("fen") or "")
        side = str(case.get("side") or "white")
        expected = [str(move).lower() for move in (case.get("expected_best_moves") or [])]
        board_state = {"__fen__": fen}
        started = time.perf_counter()
        move = _choose_engine_move_for_eval(engine_alias, board_state, side, model_path)
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


def _evaluate_fixed_probe_positions(engine_alias: str, model_path: Path) -> dict:
    if engine_alias not in {"exp1", "exp2", "exp3", "exp4"}:
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
    for sample in samples:
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
        probe_case_id = f"game:{int(sample.get('game_id') or 0)}:ply:{int(sample.get('ply') or 0)}:{expected_move}"
        return {
            "supported": False,
            "reason": "no_prior_mistake_sample",
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
            "before_failed": False,
            "after_fixed": after_uci == expected_move,
            "avoided_same_error": False,
            "model_response_changed": before_uci != after_uci,
            "sample_count": len(samples),
            "learning_signal": False,
            "learning_signal_reason": "no prior mistake was found, so this probe cannot prove that retrain corrected a known error",
            "human_explanation": "目前沒有足夠證據證明 retrain 改善了該錯誤，因為 before model 沒有在可選舊題目上犯錯。",
        }
    board_state = {"__fen__": str(sample.get("fen") or "")}
    side = str(sample.get("side") or "white")
    expected_move = str(sample.get("move_uci") or "").lower()
    before_uci = str(sample.get("before_move") or "")
    after_move = _choose_engine_move_for_eval(engine_alias, board_state, side, after_model_path)
    after_uci = _move_uci(after_move or {})
    before_failed = before_uci != expected_move
    after_fixed = after_uci == expected_move
    avoided_same_error = bool(before_failed and after_uci != before_uci)
    probe_case_id = f"game:{int(sample.get('game_id') or 0)}:ply:{int(sample.get('ply') or 0)}:{expected_move}"
    if before_failed and after_fixed:
        reason = "before model failed the old mistake case and after model selected the expected move"
        explanation = "舊錯題已被修正，這提供 retrain 改善該錯誤的直接證據。"
    elif before_failed and avoided_same_error:
        reason = "after model avoided the same wrong move but still did not select the expected move"
        explanation = "模型避開了同一個錯誤，但尚未走到預期正解，因此不能視為學習成功。"
    elif before_failed:
        reason = "after model repeated the same wrong move"
        explanation = "目前沒有足夠證據證明 retrain 改善了該錯誤，因為 after model 仍重複同一錯誤。"
    else:
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
        "avoided_same_error": avoided_same_error,
        "model_response_changed": before_uci != after_uci,
        "learning_signal": bool(before_failed and after_fixed),
        "learning_signal_reason": reason,
        "human_explanation": explanation,
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
    first_rate = first.get("win_rate")
    second_rate = second.get("win_rate")
    if first_rate is None or second_rate is None:
        return {
            "stage_win_rate_drop_10_20_vs_0_10": None,
            "stage_regression_threshold": 0.2,
            "stage_catastrophic_regression": False,
        }
    drop = round(float(first_rate) - float(second_rate), 4)
    return {
        "stage_win_rate_drop_10_20_vs_0_10": drop,
        "stage_regression_threshold": 0.2,
        "stage_catastrophic_regression": drop > 0.2,
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
    catastrophic = bool(
        (illegal_move_delta is not None and illegal_move_delta < -0.05)
        or bool(stage_regression.get("stage_catastrophic_regression"))
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
    if summary.get("replay_summary", {}).get("trusted_replays") != VALID_GAMES:
        reasons.append("insufficient trusted games")
    if summary.get("replay_summary", {}).get("quarantine_replays") != INVALID_GAMES:
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
    for checkpoint in (summary.get("before_after_eval") or {}).get("checkpoints") or []:
        mistake_probe = checkpoint.get("mistake_retention_probe") or {}
        if mistake_probe.get("learning_signal") is False:
            reason = str(mistake_probe.get("learning_signal_reason") or mistake_probe.get("reason") or "no mistake-retention learning signal")
            trusted = checkpoint.get("trusted_count") or checkpoint.get("trusted_replays")
            reasons.append(f"mistake retention probe failed at trusted={trusted}: {reason}")
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
        ROOT / "scripts" / "games" / "chess_exp2_dataset_train.py",
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
        "stochastic_auxiliary_benchmark": summary.get("stochastic_auxiliary_benchmark") or {},
        "perft": summary.get("perft") or {},
        "mistake_retention_probe_results": [
            {
                "trusted_count": checkpoint.get("trusted_count") or checkpoint.get("trusted_replays"),
                "learning_signal": (checkpoint.get("mistake_retention_probe") or {}).get("learning_signal"),
                "probe_case_id": (checkpoint.get("mistake_retention_probe") or {}).get("probe_case_id"),
                "before_move": (checkpoint.get("mistake_retention_probe") or {}).get("before_move"),
                "after_move": (checkpoint.get("mistake_retention_probe") or {}).get("after_move"),
                "avoided_same_error": (checkpoint.get("mistake_retention_probe") or {}).get("avoided_same_error"),
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
    elif any(verdict in {"PARTIAL", "HIGH_RISK"} for verdict in engine_verdicts) or any(not bool(row.get("promotion_gate_passed")) for row in root_summary["engines"]):
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
            "## Stage Game Win Rates",
            "",
            "- basis: `trusted_valid_games_only`; invalid_games_excluded=`True`",
        ]
    )
    for row in root_summary["engines"]:
        lines.append(f"- {row['engine_alias']}: {_format_stage_win_rates(row.get('stage_game_win_rates') or [])}")
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
                f"after=`{probe.get('after_move')}` avoided_same_error=`{probe.get('avoided_same_error')}` "
                f"learning_signal=`{probe.get('learning_signal')}` reason=`{probe.get('learning_signal_reason')}`"
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
                "avoided_same_error": (checkpoint.get("mistake_retention_probe") or {}).get("avoided_same_error"),
                "learning_signal_reason": (checkpoint.get("mistake_retention_probe") or {}).get("learning_signal_reason"),
            }
            for checkpoint in (summary.get("before_after_eval") or {}).get("checkpoints") or []
        ]
        if (row.get("mistake_retention_probe_results") or []) != mistake_results:
            issues.append(f"{alias}: mistake retention probe mismatch")
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
    if engine_alias == "exp2":
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp2_dataset_train.py"),
            "--input-jsonl",
            str(probe_dataset_path),
            "--model-path",
            str(probe_model_path),
        ]
    elif engine_alias == "exp3":
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
                    f"think_ms `{(row.get('move_agreement_before') or {}).get('avg_think_ms')}` -> `{(row.get('move_agreement_after') or {}).get('avg_think_ms')}` "
                    f"retention_probe=`{(row.get('retention_probe') or {}).get('learning_signal')}` "
                    f"mistake_probe=`{mistake_probe.get('learning_signal')}` "
                    f"mistake_case=`{mistake_probe.get('probe_case_id')}` "
                    f"mistake_before=`{mistake_probe.get('before_move')}` "
                    f"mistake_after=`{mistake_probe.get('after_move')}` "
                    f"avoided_same_error=`{mistake_probe.get('avoided_same_error')}` "
                    f"status `{(row.get('autorun_status') or {}).get('status')}`"
                )
                if mistake_probe.get("learning_signal") is False:
                    lines.append(f"- mistake_probe_explanation: {mistake_probe.get('human_explanation')}")
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
                f"avoided_same_error=`{mistake_probe.get('avoided_same_error')}`"
            )
            if mistake_probe.get("learning_signal") is False:
                lines.append(f"- mistake_probe_explanation: {mistake_probe.get('human_explanation')}")
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
            "checkpoints": checkpoints,
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
        "checkpoints": checkpoints,
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
    _json_dump(engine_dir / "deterministic_strength_snapshot.json", deterministic_strength)
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
    elif any(verdict in {"PARTIAL", "HIGH_RISK"} for verdict in engine_verdicts) or any(not bool(row.get("promotion_gate_passed")) for row in root_summary["engines"]):
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
