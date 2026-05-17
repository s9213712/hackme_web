#!/usr/bin/env python3
"""Exp6 search-side ablation harness.

This does not modify the runtime champion. It replays the staged-10
Stockfish gate with the existing Exp6 evaluator and several search-only
variants so we can identify non-training directions worth promoting into
the runtime entry point.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import chess

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess import FEN_KEY  # noqa: E402
from services.games.chess_exp6 import _SEARCH_PROFILES, _move_order_score  # noqa: E402
from services.games.chess_neural import NeuralEvaluator, load_weights  # noqa: E402
from services.games.chess_search import ZobristHasher, opening_sanity_filter, search_best_move  # noqa: E402
from services.games.chess_stockfish_teacher import UciStockfish, analysis_limit, resolve_stockfish_path  # noqa: E402
from services.games.chess_dl import (  # noqa: E402
    _load_model as _load_dl_model,
    _score_candidate_move as _score_dl_candidate_move,
    choose_experiment_dl_move,
    default_chess_dl_model_path,
)

sys.path.insert(0, str(ROOT / "scripts/games"))
import chess_exp6_curriculum as cc  # noqa: E402


PIECE_ORDER_VALUE = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

_DL_MODEL_CACHE: dict[str, dict] = {}


def _state_from_board(board: chess.Board) -> dict:
    state = {chess.square_name(square): piece.symbol() for square, piece in board.piece_map().items()}
    state[FEN_KEY] = board.fen()
    return state


def _dl_model() -> dict:
    path = str(default_chess_dl_model_path())
    model = _DL_MODEL_CACHE.get(path)
    if model is None:
        model = _load_dl_model(Path(path))
        _DL_MODEL_CACHE[path] = model
    return model


def _dl_policy_move(board: chess.Board) -> chess.Move | None:
    side = "white" if board.turn == chess.WHITE else "black"
    payload = choose_experiment_dl_move(
        _state_from_board(board),
        side,
        search_profile="balanced",
        fusion_mode="balanced_fusion",
        style_profile="balanced",
    )
    if not payload:
        return None
    promo = payload.get("promotion") or ""
    try:
        move = chess.Move.from_uci(f"{payload['from']}{payload['to']}{promo}")
    except Exception:
        return None
    return move if move in board.legal_moves else None


def _center_bonus(square: int) -> int:
    file = chess.square_file(square)
    rank = chess.square_rank(square)
    return int(28 - 4 * (abs(file - 3.5) + abs(rank - 3.5)))


def _is_early_unforced_queen_move(board: chess.Board, move: chess.Move) -> bool:
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type != chess.QUEEN:
        return False
    if board.fullmove_number > 10:
        return False
    return not (board.is_capture(move) or board.gives_check(move) or move.promotion)


def _home_rank(color: chess.Color) -> int:
    return 0 if color == chess.WHITE else 7


def _opening_principle_score(board: chess.Board, move: chess.Move) -> int:
    if board.fullmove_number > 12 or board.is_check():
        return 0
    moving = board.piece_at(move.from_square)
    if moving is None:
        return 0
    score = 0
    if board.is_capture(move):
        captured = board.piece_at(move.to_square)
        if captured is not None:
            score += 200 + PIECE_ORDER_VALUE.get(captured.piece_type, 0)
    if board.gives_check(move):
        score += 120
    if move.promotion:
        score += 900
    if board.is_castling(move):
        score += 1200
    home = _home_rank(moving.color)
    from_home = chess.square_rank(move.from_square) == home
    to_file = chess.square_file(move.to_square)
    to_rank = chess.square_rank(move.to_square)
    if moving.piece_type in (chess.KNIGHT, chess.BISHOP):
        if from_home:
            score += 800
        score += _center_bonus(move.to_square) * 6
    elif moving.piece_type == chess.PAWN:
        direction = 1 if moving.color == chess.WHITE else -1
        advanced = (to_rank - chess.square_rank(move.from_square)) * direction
        if to_file in (3, 4):
            score += 650 if advanced == 2 else 520
        elif to_file in (2, 5):
            score += 220
        elif to_file in (0, 7):
            score -= 520
        elif to_file in (1, 6):
            score -= 240
    elif moving.piece_type == chess.QUEEN:
        score -= 460
    elif moving.piece_type == chess.ROOK:
        score -= 520
    elif moving.piece_type == chess.KING and not board.is_castling(move):
        score -= 700
    return score


def _is_bad_early_principle_move(board: chess.Board, move: chess.Move) -> bool:
    if board.fullmove_number > 12 or board.is_check():
        return False
    if board.is_capture(move) or board.gives_check(move) or move.promotion or board.is_castling(move):
        return False
    moving = board.piece_at(move.from_square)
    if moving is None:
        return False
    to_file = chess.square_file(move.to_square)
    if moving.piece_type == chess.PAWN and to_file in (0, 7):
        return True
    if moving.piece_type == chess.PAWN and to_file in (1, 6) and board.fullmove_number <= 8:
        return True
    if moving.piece_type in (chess.QUEEN, chess.ROOK):
        return True
    if moving.piece_type == chess.KING and not board.is_castling(move):
        return True
    return False


def _opening_principle_filter(board: chess.Board, best_move: chess.Move | None) -> chess.Move | None:
    if best_move is None or not _is_bad_early_principle_move(board, best_move):
        return best_move
    legal = list(board.legal_moves)
    if not legal:
        return best_move
    scored = [(move, _opening_principle_score(board, move)) for move in legal]
    candidate, candidate_score = max(scored, key=lambda item: (item[1], item[0].uci()))
    best_score = _opening_principle_score(board, best_move)
    if candidate != best_move and candidate_score >= max(450, best_score + 500):
        return candidate
    return best_move


def _advanced_move_order(board: chess.Board, move: chess.Move, _ply: int) -> int:
    """Move-ordering only. The returned score is deliberately coarse:
    tactical forcing moves first, then development/castling, then quieter
    positional preferences. Since Exp6 uses LMR/futility and time budgets,
    root/child order can change effective strength even at the same depth.
    """
    score = 0
    moving = board.piece_at(move.from_square)
    captured = board.piece_at(move.to_square)
    if captured is None and board.is_en_passant(move):
        captured = chess.Piece(chess.PAWN, not board.turn)
    if board.is_capture(move):
        victim = PIECE_ORDER_VALUE.get(captured.piece_type if captured else chess.PAWN, 100)
        attacker = PIECE_ORDER_VALUE.get(moving.piece_type if moving else chess.PAWN, 100)
        score += 1_000_000 + 16 * victim - attacker
    if move.promotion is not None:
        score += 900_000 + PIECE_ORDER_VALUE.get(move.promotion, 0)
    if board.gives_check(move):
        score += 120_000
    if board.is_castling(move):
        score += 85_000
    if moving is not None:
        if moving.piece_type in (chess.KNIGHT, chess.BISHOP) and board.fullmove_number <= 12:
            home_rank = 0 if moving.color == chess.WHITE else 7
            if chess.square_rank(move.from_square) == home_rank:
                score += 32_000
        if moving.piece_type == chess.PAWN and board.fullmove_number <= 12:
            if chess.square_file(move.to_square) in (3, 4):
                score += 12_000
        if moving.piece_type == chess.KING and not board.is_castling(move) and board.fullmove_number <= 12:
            score -= 45_000
    if _is_early_unforced_queen_move(board, move):
        score -= 35_000
    score += _center_bonus(move.to_square)
    return score


def _q_captures_promos_checks(board: chess.Board, move: chess.Move) -> bool:
    return bool(board.is_capture(move) or move.promotion or board.gives_check(move))


def _check_extension(board: chess.Board, move: chess.Move, _ply: int, _depth: int) -> int:
    return 1 if board.gives_check(move) else 0


def choose_variant_move(board: chess.Board, weights_path: Path, variant: str) -> chess.Move | None:
    for move in board.legal_moves:
        board.push(move)
        is_mate = board.is_checkmate()
        board.pop()
        if is_mate:
            return move

    if variant == "exp3":
        return _dl_policy_move(board)

    weights = load_weights(weights_path)
    evaluator = NeuralEvaluator(weights)
    hasher = ZobristHasher(seed=20260601)
    profile = dict(_SEARCH_PROFILES["balanced"])

    qmove_filter = None
    extension_fn = None
    max_extensions = 0
    move_order_fn = _move_order_score

    if variant in {"qchecks", "qchecks_order", "qchecks_ext", "full"}:
        qmove_filter = _q_captures_promos_checks
    if variant in {"order", "qchecks_order", "full"}:
        move_order_fn = _advanced_move_order
    if variant == "principles_order":
        move_order_fn = lambda current_board, move, ply: _move_order_score(current_board, move, ply) + _opening_principle_score(current_board, move)
    if variant in {"dl_order", "dl_qchecks"}:
        model = _dl_model()

        def _dl_order(current_board: chess.Board, move: chess.Move, _ply: int) -> int:
            side = "white" if current_board.turn == chess.WHITE else "black"
            return int(_score_dl_candidate_move(current_board, move, side, model) * 1000.0)

        move_order_fn = _dl_order
    if variant == "dl_qchecks":
        qmove_filter = _q_captures_promos_checks
    if variant in {"qchecks_ext", "full"}:
        extension_fn = _check_extension
        max_extensions = 1

    result = search_best_move(
        board,
        max_depth=int(profile["depth"]),
        evaluate=evaluator,
        move_order_fn=move_order_fn,
        qmove_filter=qmove_filter,
        extension_fn=extension_fn,
        max_extensions=max_extensions,
        quiescence_depth=int(profile["quiescence_depth"]),
        hasher=hasher,
        time_budget_ms=profile.get("time_budget_ms"),
        enable_pvs=bool(profile.get("enable_pvs")),
        enable_lmr=bool(profile.get("enable_lmr")),
        enable_null_move=bool(profile.get("enable_null_move")),
        enable_futility=bool(profile.get("enable_futility")),
    )
    best = opening_sanity_filter(
        board,
        result.best_move,
        score_move=lambda mv: move_order_fn(board, mv, 0),
    )
    if variant in {"principles", "principles_order"}:
        best = _opening_principle_filter(board, best)
    return best


def play_one_game(variant: str, opening_id: str, opening_moves: list[str], exp6_color_name: str,
                  weights_path: Path, stockfish_depth: int, engine: UciStockfish,
                  max_plies: int = 400) -> dict:
    board = chess.Board()
    for uci in opening_moves:
        board.push_uci(uci)
    exp6_color = chess.WHITE if exp6_color_name == "white" else chess.BLACK
    invalid_actor = None
    exp6_times: list[float] = []
    sf_times: list[float] = []
    wall0 = time.perf_counter()
    moves: list[str] = []
    for _ply in range(max_plies):
        if board.is_game_over(claim_draw=True):
            break
        if board.turn == exp6_color:
            t0 = time.perf_counter()
            move = choose_variant_move(board, weights_path, variant)
            exp6_times.append(time.perf_counter() - t0)
            if move is None or move not in board.legal_moves:
                invalid_actor = "exp6"
                break
        else:
            t0 = time.perf_counter()
            try:
                pv = engine.analyse(board, limit=analysis_limit(depth=stockfish_depth, movetime_ms=0), multipv=1)
            except Exception:
                sf_times.append(time.perf_counter() - t0)
                invalid_actor = "stockfish"
                break
            sf_times.append(time.perf_counter() - t0)
            if not pv:
                invalid_actor = "stockfish"
                break
            try:
                move = chess.Move.from_uci(pv[0]["move"])
            except Exception:
                invalid_actor = "stockfish"
                break
            if move not in board.legal_moves:
                invalid_actor = "stockfish"
                break
        moves.append(move.uci())
        board.push(move)

    outcome = board.outcome(claim_draw=True)
    if invalid_actor:
        winner = "stockfish" if invalid_actor == "exp6" else "exp6"
        result = f"{winner}_win"
        reason = "invalid_move"
    elif outcome is None:
        result = "incomplete"
        reason = "max_plies"
    elif outcome.winner is None:
        result = "draw"
        reason = outcome.termination.name.lower()
    else:
        result = "exp6_win" if outcome.winner == exp6_color else "stockfish_win"
        reason = outcome.termination.name.lower()
    score = cc.SCORE_WIN if result == "exp6_win" else (cc.SCORE_DRAW if result == "draw" else cc.SCORE_LOSS)

    def _mean(xs: list[float]) -> float:
        return float(sum(xs) / len(xs)) if xs else 0.0

    return {
        "variant": variant,
        "opening_id": opening_id,
        "stockfish_depth": stockfish_depth,
        "exp6_color": exp6_color_name,
        "result": result,
        "reason": reason,
        "plies": len(board.move_stack),
        "score_points": score,
        "elapsed_wall_s": round(time.perf_counter() - wall0, 3),
        "exp6_mean_ms": round(_mean(exp6_times) * 1000.0, 1),
        "exp6_max_ms": round((max(exp6_times) if exp6_times else 0.0) * 1000.0, 1),
        "sf_mean_ms": round(_mean(sf_times) * 1000.0, 1),
        "moves": moves,
        "final_fen": board.fen(),
    }


def run_variant(weights_path: Path, variant: str) -> list[dict]:
    rows: list[dict] = []
    sf_path = resolve_stockfish_path()
    if not sf_path:
        raise SystemExit("Stockfish not found")
    schedule = []
    for depth in cc.STAGED_DEPTHS:
        for k in range(cc.STAGED_GAMES_PER_DEPTH):
            opening_id, opening_moves = cc.STAGED_OPENINGS[(depth + k - 1) % len(cc.STAGED_OPENINGS)]
            exp6_color = "white" if k % 2 == 0 else "black"
            schedule.append((opening_id, opening_moves, exp6_color, depth))
    with UciStockfish(sf_path) as engine:
        for i, (opening_id, opening_moves, exp6_color, depth) in enumerate(schedule):
            row = play_one_game(variant, opening_id, opening_moves, exp6_color, weights_path, depth, engine)
            rows.append(row)
            print(
                f"    {variant:13s} g{i+1:02d} d{depth} {opening_id}/exp6={exp6_color}: "
                f"{row['result']:>14s} ({row['reason']}) {row['plies']:3d}p "
                f"exp6_mean={row['exp6_mean_ms']:.0f}ms max={row['exp6_max_ms']:.0f}ms score={row['score_points']:+d}",
                flush=True,
            )
    return rows


def summarize(rows: list[dict]) -> dict:
    wins = sum(1 for row in rows if row["result"] == "exp6_win")
    draws = sum(1 for row in rows if row["result"] == "draw")
    losses = sum(1 for row in rows if row["result"] == "stockfish_win")
    total = sum(int(row["score_points"]) for row in rows)
    return {
        "W": wins,
        "D": draws,
        "L": losses,
        "score_total": total,
        "score_max": len(rows) * cc.SCORE_WIN,
        "mean_exp6_ms": round(sum(row["exp6_mean_ms"] for row in rows) / len(rows), 1) if rows else 0.0,
        "max_exp6_ms": max((row["exp6_max_ms"] for row in rows), default=0.0),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", type=Path, required=True)
    ap.add_argument("--variants", default="baseline,qchecks,order,qchecks_order,qchecks_ext,full")
    ap.add_argument("--out", type=Path, default=Path.home() / "exp6_output/v10_search_ablation.json")
    args = ap.parse_args()

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    all_results: dict[str, dict] = {}
    for variant in variants:
        print(f"\n=== {variant}: staged-10 ===", flush=True)
        rows = run_variant(args.weights, variant)
        summary = summarize(rows)
        all_results[variant] = {"summary": summary, "games": rows}
        print(
            f"  {variant}: {summary['W']}W/{summary['D']}D/{summary['L']}L "
            f"score={summary['score_total']:+d}/{summary['score_max']} "
            f"mean={summary['mean_exp6_ms']:.0f}ms max={summary['max_exp6_ms']:.0f}ms",
            flush=True,
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(all_results, indent=2))
    print(f"\nsaved -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
