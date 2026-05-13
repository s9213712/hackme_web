#!/usr/bin/env python3
"""Holdout-style behavioral probes for chess ``experiment 5:nnue``.

The probe is deliberately separate from the main score probe. It mixes
synthetic traps with imported PGN human/elite positions so improvements are
checked against fresh surfaces rather than only against the fixed score cases.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import chess


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess import FEN_KEY  # noqa: E402
from services.games.chess_nnue import choose_experiment_nnue_move  # noqa: E402


EXP5 = "experiment 5:nnue"
PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}


@dataclass(frozen=True)
class HoldoutCase:
    case_id: str
    fen: str
    side: str
    kind: str
    description: str
    min_capture_value: int = 0
    reference_move: str = ""
    source: str = "synthetic"
    difficulty: str = "basic"
    tags: tuple[str, ...] = ()


def _board_state(board: chess.Board) -> dict[str, str]:
    state = {chess.square_name(square): piece.symbol() for square, piece in board.piece_map().items()}
    state[FEN_KEY] = board.fen()
    return state


def _move_uci(move: dict[str, Any] | None) -> str:
    if not move:
        return ""
    return f"{move.get('from')}{move.get('to')}{move.get('promotion') or ''}".lower()


def _mate_in_one_moves(board: chess.Board) -> list[str]:
    mates: list[str] = []
    for move in board.legal_moves:
        after = board.copy(stack=False)
        after.push(move)
        if after.is_checkmate():
            mates.append(move.uci())
    return sorted(mates)


def _forced_mate_in_two_moves(board: chess.Board) -> list[str]:
    forced: list[str] = []
    for move in board.legal_moves:
        after = board.copy(stack=False)
        after.push(move)
        if after.is_checkmate() or after.is_stalemate():
            continue
        replies = list(after.legal_moves)
        if not replies:
            continue
        ok = True
        for reply in replies:
            reply_board = after.copy(stack=False)
            reply_board.push(reply)
            if not _mate_in_one_moves(reply_board):
                ok = False
                break
        if ok:
            forced.append(move.uci())
    return sorted(forced)


def _mate_threats_if_side_passed(board: chess.Board) -> list[str]:
    other = board.copy(stack=False)
    other.turn = not board.turn
    return _mate_in_one_moves(other)


def _blunders_allowing_mate_in_one(board: chess.Board) -> list[str]:
    blunders: list[str] = []
    for move in board.legal_moves:
        after = board.copy(stack=False)
        after.push(move)
        if _mate_in_one_moves(after):
            blunders.append(move.uci())
    return sorted(blunders)


def _captured_value(board: chess.Board, move: chess.Move) -> int:
    if board.is_en_passant(move):
        square = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
    else:
        square = move.to_square
    captured = board.piece_at(square)
    return PIECE_VALUES.get(captured.piece_type, 0) if captured else 0


def _dangerous_pawn_capture(board: chess.Board, move: chess.Move) -> bool:
    captured = board.piece_at(move.to_square)
    if captured is None or captured.piece_type != chess.PAWN:
        return False
    rank = chess.square_rank(move.to_square)
    return (captured.color == chess.BLACK and rank <= 1) or (captured.color == chess.WHITE and rank >= 6)


def _side_material_margin(board: chess.Board, color: chess.Color) -> int:
    margin = 0
    for piece_type, value in PIECE_VALUES.items():
        if piece_type == chess.KING:
            continue
        margin += len(board.pieces(piece_type, color)) * value
        margin -= len(board.pieces(piece_type, not color)) * value
    return margin


def _worst_immediate_reply_margin(board: chess.Board, color: chess.Color) -> int:
    """Material margin after the opponent's best immediate capture/checkmate."""
    worst = _side_material_margin(board, color)
    for reply in board.legal_moves:
        after = board.copy(stack=False)
        after.push(reply)
        if after.is_checkmate():
            return -99999
        if board.is_capture(reply):
            worst = min(worst, _side_material_margin(after, color))
    return worst


def _is_development_move(board: chess.Board, move: chess.Move) -> bool:
    piece = board.piece_at(move.from_square)
    if piece is None:
        return False
    if board.is_castling(move):
        return True
    if board.is_capture(move) and _captured_value(board, move) >= PIECE_VALUES[chess.KNIGHT]:
        return True
    if piece.piece_type in {chess.KNIGHT, chess.BISHOP}:
        home_rank = 0 if piece.color == chess.WHITE else 7
        return chess.square_rank(move.from_square) == home_rank
    if piece.piece_type == chess.PAWN:
        return chess.square_file(move.from_square) in {2, 3, 4, 5}
    return False


def _is_bad_opening_drift(board: chess.Board, move: chess.Move) -> bool:
    piece = board.piece_at(move.from_square)
    if piece is None:
        return True
    if board.is_capture(move) and _captured_value(board, move) >= PIECE_VALUES[chess.ROOK]:
        return False
    if piece.piece_type == chess.PAWN and chess.square_file(move.from_square) in {0, 7} and not board.is_capture(move):
        return True
    if piece.piece_type == chess.ROOK and not board.is_castling(move) and not board.gives_check(move):
        return _captured_value(board, move) < PIECE_VALUES[chess.ROOK]
    if piece.piece_type == chess.QUEEN and not board.is_capture(move) and not board.gives_check(move):
        return True
    return False


def _mirror_uci(move_uci: str) -> str:
    if len(move_uci) < 4:
        return ""
    try:
        move = chess.Move.from_uci(move_uci)
    except ValueError:
        return ""
    mirrored = chess.Move(
        chess.square_mirror(move.from_square),
        chess.square_mirror(move.to_square),
        promotion=move.promotion,
        drop=move.drop,
    )
    return mirrored.uci()


def _mirror_case(case: HoldoutCase) -> HoldoutCase:
    board = chess.Board(case.fen)
    mirrored = board.mirror()
    ref = _mirror_uci(case.reference_move) if case.reference_move else ""
    return HoldoutCase(
        case_id=f"{case.case_id}_mirror",
        fen=mirrored.fen(),
        side="white" if case.side == "black" else "black",
        kind=case.kind,
        description=f"Mirrored holdout: {case.description}",
        min_capture_value=case.min_capture_value,
        reference_move=ref,
        source=case.source,
        difficulty=case.difficulty,
        tags=tuple(sorted(set(case.tags + ("mirror",)))),
    )


def base_cases() -> list[HoldoutCase]:
    return [
        HoldoutCase(
            "scholar_qh5_c4",
            "rnbqkbnr/pppp1ppp/8/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 2",
            "black",
            "prevent_mate_in_one",
            "Black must address Qxf7# without using the exact fixed score FEN.",
            source="synthetic_trap",
            difficulty="opening_trap",
            tags=("scholar_mate", "human_probe"),
        ),
        HoldoutCase(
            "scholar_qf3_c4",
            "rnbqkbnr/pppp1ppp/8/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR b KQkq - 3 2",
            "black",
            "prevent_mate_in_one",
            "Queen on f3 and bishop on c4 create the same f7 mate threat.",
            source="synthetic_trap",
            difficulty="opening_trap",
            tags=("scholar_mate", "human_probe"),
        ),
        HoldoutCase(
            "diagonal_qe1_trap_extra_pawn",
            "6k1/5ppp/3b4/8/7q/8/5PPP/6K1 w - - 0 1",
            "white",
            "avoid_creating_mate_in_one",
            "White must not open the diagonal to Qe1#.",
            source="synthetic_trap",
            difficulty="trap",
            tags=("diagonal_mate",),
        ),
        HoldoutCase(
            "diagonal_qe1_capture_defense",
            "6k1/5ppp/8/8/7q/5b2/6PP/6K1 w - - 0 1",
            "white",
            "prevent_mate_in_one",
            "White can solve the mate threat by capturing the attacking bishop.",
            source="synthetic_trap",
            difficulty="trap",
            tags=("diagonal_mate", "capture_defense"),
        ),
        HoldoutCase(
            "simple_queen_mate_white",
            "6k1/5Q2/6K1/8/8/8/8/8 w - - 0 1",
            "white",
            "find_mate_in_one",
            "White has multiple queen mates and should choose one.",
            source="synthetic_tactic",
            difficulty="basic",
            tags=("mate_in_one",),
        ),
        HoldoutCase(
            "corner_queen_mate_white",
            "k7/8/KQ6/8/8/8/8/8 w - - 0 1",
            "white",
            "find_mate_in_one",
            "White must convert a simple corner mate.",
            source="synthetic_tactic",
            difficulty="basic",
            tags=("mate_in_one",),
        ),
        HoldoutCase(
            "minor_recapture_center",
            "r2k1b1r/p1p1ppp1/p6p/3p4/5P2/2N5/PP1B2PP/2Rb1RK1 w - - 0 12",
            "white",
            "capture_material",
            "White should not ignore the bishop that invaded d1.",
            min_capture_value=PIECE_VALUES[chess.BISHOP],
            source="synthetic_tactic",
            difficulty="basic",
            tags=("recapture",),
        ),
        HoldoutCase(
            "queen_hang_rook_capture",
            "k7/8/8/8/8/8/4R2q/4K3 w - - 0 1",
            "white",
            "capture_material",
            "White should capture the hanging queen.",
            min_capture_value=PIECE_VALUES[chess.QUEEN],
            source="synthetic_tactic",
            difficulty="basic",
            tags=("hanging_piece",),
        ),
        HoldoutCase(
            "black_pawn_one_step_from_promotion",
            "8/8/8/8/8/8/R1p5/4K2k w - - 0 1",
            "white",
            "capture_dangerous_pawn",
            "White should clean up a black pawn one move from promotion.",
            source="synthetic_endgame",
            difficulty="basic",
            tags=("promotion_pawn",),
        ),
        HoldoutCase(
            "white_pawn_one_step_from_promotion",
            "4k3/r4P2/8/8/8/8/8/4K3 b - - 0 1",
            "black",
            "capture_dangerous_pawn",
            "Black should clean up a white pawn one move from promotion.",
            source="synthetic_endgame",
            difficulty="basic",
            tags=("promotion_pawn",),
        ),
        HoldoutCase(
            "fools_mate_black",
            "rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq g3 0 2",
            "black",
            "find_mate_in_one",
            "Human blunder probe: black must punish Fool's Mate.",
            source="synthetic_human_probe",
            difficulty="opening_blunder",
            tags=("human_probe", "fools_mate", "mate_in_one"),
        ),
        HoldoutCase(
            "back_rank_rook_white",
            "6k1/5ppp/8/8/8/8/5PPP/4R1K1 w - - 0 1",
            "white",
            "find_mate_in_one",
            "White should see the rook back-rank mate.",
            source="synthetic_human_probe",
            difficulty="basic",
            tags=("back_rank", "mate_in_one"),
        ),
        HoldoutCase(
            "back_rank_queen_white",
            "6k1/5ppp/8/8/8/8/5PPP/4Q1K1 w - - 0 1",
            "white",
            "find_mate_in_one",
            "White should see the queen back-rank mate.",
            source="synthetic_human_probe",
            difficulty="basic",
            tags=("back_rank", "mate_in_one"),
        ),
        HoldoutCase(
            "ladder_rook_white",
            "7k/6pp/8/8/8/8/6PP/R5K1 w - - 0 1",
            "white",
            "find_mate_in_one",
            "White should finish a simple rook mate on the edge.",
            source="synthetic_tactic",
            difficulty="basic",
            tags=("mate_in_one",),
        ),
        HoldoutCase(
            "kqk_mate_two_king_net",
            "6k1/8/6K1/8/8/8/8/5Q2 w - - 0 1",
            "white",
            "find_forced_mate_in_two",
            "Simplified KQK: choose a move that forces mate next move.",
            source="synthetic_deep_tactic",
            difficulty="mate_in_two",
            tags=("mate_in_two", "endgame"),
        ),
        HoldoutCase(
            "kqk_mate_two_file_cut",
            "6k1/8/5K2/8/8/8/8/5Q2 w - - 0 1",
            "white",
            "find_forced_mate_in_two",
            "KQK holdout with a different king net geometry.",
            source="synthetic_deep_tactic",
            difficulty="mate_in_two",
            tags=("mate_in_two", "endgame"),
        ),
        HoldoutCase(
            "kqk_mate_two_corner_net",
            "k7/8/1K6/8/8/8/8/1Q6 w - - 0 1",
            "white",
            "find_forced_mate_in_two",
            "Corner KQK mate-in-two that should not depend on exact coordinates.",
            source="synthetic_deep_tactic",
            difficulty="mate_in_two",
            tags=("mate_in_two", "endgame"),
        ),
        HoldoutCase(
            "en_passant_available",
            "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3",
            "white",
            "en_passant",
            "White should take the legal en-passant capture when it is the forcing rule move.",
            source="synthetic_rule",
            difficulty="rule",
            tags=("en_passant",),
        ),
        HoldoutCase(
            "opening_after_nh3_black",
            "rnbqkbnr/pppppppp/8/8/8/7N/PPPPPPPP/RNBQKB1R b KQkq - 1 1",
            "black",
            "opening_development",
            "After a human rim-knight move, black should develop normally.",
            source="synthetic_human_probe",
            difficulty="opening",
            tags=("human_probe", "opening"),
        ),
        HoldoutCase(
            "opening_after_a4_black",
            "rnbqkbnr/pppppppp/8/8/P7/8/1PPPPPPP/RNBQKBNR b KQkq - 0 1",
            "black",
            "opening_development",
            "After a flank-pawn opening, black should not answer with aimless rook/flank drift.",
            source="synthetic_human_probe",
            difficulty="opening",
            tags=("human_probe", "opening"),
        ),
        HoldoutCase(
            "opening_after_h3_black",
            "rnbqkbnr/pppppppp/8/8/8/7P/PPPPPPP1/RNBQKBNR b KQkq - 0 1",
            "black",
            "opening_development",
            "After a quiet rook-pawn move, black should develop or claim the center.",
            source="synthetic_human_probe",
            difficulty="opening",
            tags=("human_probe", "opening"),
        ),
        HoldoutCase(
            "clean_castle_white",
            "4k3/8/8/8/8/8/8/R3K2R w KQ - 0 1",
            "white",
            "castle_when_clean",
            "With only a clean castling decision available, white should castle.",
            source="synthetic_rule",
            difficulty="rule",
            tags=("castling",),
        ),
        HoldoutCase(
            "king_takes_rook",
            "k7/8/8/8/8/8/4r3/4K3 w - - 0 1",
            "white",
            "capture_material",
            "White king should capture the checking rook if it is free.",
            min_capture_value=PIECE_VALUES[chess.ROOK],
            source="synthetic_tactic",
            difficulty="basic",
            tags=("capture_checking_piece",),
        ),
        HoldoutCase(
            "king_takes_danger_pawn",
            "8/8/8/8/8/8/1p6/2K4k w - - 0 1",
            "white",
            "capture_dangerous_pawn",
            "White king should stop a pawn on the seventh rank.",
            source="synthetic_endgame",
            difficulty="basic",
            tags=("promotion_pawn",),
        ),
        HoldoutCase(
            "prevent_back_rank_rook_threat",
            "6k1/5ppp/8/8/8/8/5PPP/4R1K1 b - - 0 1",
            "black",
            "prevent_mate_in_one",
            "Black must notice the pending Re8# back-rank threat.",
            source="synthetic_trap",
            difficulty="trap",
            tags=("back_rank", "human_probe"),
        ),
        HoldoutCase(
            "prevent_back_rank_queen_threat",
            "6k1/5ppp/8/8/8/8/5PPP/4Q1K1 b - - 0 1",
            "black",
            "prevent_mate_in_one",
            "Black must notice the pending Qe8# back-rank threat.",
            source="synthetic_trap",
            difficulty="trap",
            tags=("back_rank", "human_probe"),
        ),
        HoldoutCase(
            "queen_hang_king_capture",
            "k7/8/8/8/8/8/4q3/4K3 w - - 0 1",
            "white",
            "capture_material",
            "White king should take an undefended adjacent queen.",
            min_capture_value=PIECE_VALUES[chess.QUEEN],
            source="synthetic_tactic",
            difficulty="basic",
            tags=("hanging_piece",),
        ),
        HoldoutCase(
            "rook_takes_hanging_rook",
            "k7/8/8/8/8/8/4R2r/4K3 w - - 0 1",
            "white",
            "capture_material",
            "White rook should take a hanging rook.",
            min_capture_value=PIECE_VALUES[chess.ROOK],
            source="synthetic_tactic",
            difficulty="basic",
            tags=("hanging_piece",),
        ),
        HoldoutCase(
            "bishop_recapture_knight",
            "k7/8/8/8/8/2n5/3B4/4K3 w - - 0 1",
            "white",
            "capture_material",
            "White bishop should recapture the loose knight.",
            min_capture_value=PIECE_VALUES[chess.KNIGHT],
            source="synthetic_tactic",
            difficulty="basic",
            tags=("recapture",),
        ),
        HoldoutCase(
            "knight_takes_hanging_queen",
            "k7/8/8/8/8/2N5/4q3/4K3 w - - 0 1",
            "white",
            "capture_material",
            "White knight should take a loose queen when available.",
            min_capture_value=PIECE_VALUES[chess.QUEEN],
            source="synthetic_tactic",
            difficulty="basic",
            tags=("hanging_piece",),
        ),
        HoldoutCase(
            "opening_after_early_queen_black",
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPQPPP/RNB1KBNR b KQkq - 1 1",
            "black",
            "opening_development",
            "After an early human queen move, black should develop rather than mirror the bad habit.",
            source="synthetic_human_probe",
            difficulty="opening",
            tags=("human_probe", "opening"),
        ),
    ]


def _valid_case(case: HoldoutCase) -> bool:
    try:
        board = chess.Board(case.fen)
    except Exception:
        return False
    board.turn = chess.WHITE if case.side == "white" else chess.BLACK
    return board.is_valid()


def synthetic_cases(*, include_mirrors: bool) -> list[HoldoutCase]:
    cases = [case for case in base_cases() if _valid_case(case)]
    if include_mirrors:
        mirrored = []
        for case in cases:
            mirror = _mirror_case(case)
            if _valid_case(mirror):
                mirrored.append(mirror)
        cases = [case for pair in zip(cases, mirrored) for case in pair]
    return cases


def _load_pgn_probe_cases(path: Path, *, limit: int) -> list[HoldoutCase]:
    if limit <= 0 or not path.exists():
        return []
    cases: list[HoldoutCase] = []
    seen: set[tuple[str, str]] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_index, line in enumerate(handle, start=1):
            if len(cases) >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            replay_id = str(record.get("replay_id") or f"line{line_index}")[:10]
            headers = record.get("pgn_headers") if isinstance(record.get("pgn_headers"), dict) else {}
            labels = record.get("pgn_labels") if isinstance(record.get("pgn_labels"), dict) else {}
            source_label = str(labels.get("source_label") or record.get("pgn_source") or "imported_pgn")
            moves = record.get("move_history") if isinstance(record.get("move_history"), list) else []
            for ply_index, item in enumerate(moves, start=1):
                if len(cases) >= limit:
                    break
                if not isinstance(item, dict):
                    continue
                fen = str(item.get("fen_before") or "").strip()
                uci = str(item.get("uci") or "").strip().lower()
                side = str(item.get("by") or "").strip().lower()
                if side not in {"white", "black"} or len(uci) < 4 or not fen:
                    continue
                if ply_index <= 8 and not (item.get("castle") or item.get("captured") or item.get("check_after")):
                    continue
                key = (fen, side)
                if key in seen:
                    continue
                try:
                    board = chess.Board(fen)
                    board.turn = chess.WHITE if side == "white" else chess.BLACK
                    move = chess.Move.from_uci(uci)
                except Exception:
                    continue
                if move not in board.legal_moves or not board.is_valid():
                    continue
                seen.add(key)
                tags = ["pgn_human_probe", str(labels.get("rating_band") or "unknown_rating")]
                if item.get("captured"):
                    tags.append("reference_capture")
                if item.get("check_after"):
                    tags.append("reference_check")
                if item.get("castle"):
                    tags.append("reference_castle")
                if item.get("promotion"):
                    tags.append("reference_promotion")
                cases.append(
                    HoldoutCase(
                        case_id=f"pgn_{replay_id}_{ply_index:03d}",
                        fen=board.fen(),
                        side=side,
                        kind="pgn_human_probe",
                        description=(
                            f"Imported PGN human/elite probe from {source_label}; "
                            f"reference {side} move {uci} ({item.get('san') or ''})."
                        ),
                        reference_move=uci,
                        source="downloaded_pgn_replay",
                        difficulty="human_probe",
                        tags=tuple(tags),
                    )
                )
    return cases


def holdout_cases(
    *,
    include_mirrors: bool,
    target_cases: int,
    pgn_replay_jsonl: Path | None,
    pgn_case_count: int,
) -> list[HoldoutCase]:
    target = max(0, int(target_cases or 0))
    pgn_count = max(0, int(pgn_case_count or 0))
    synthetic = synthetic_cases(include_mirrors=include_mirrors)
    pgn_cases = _load_pgn_probe_cases(pgn_replay_jsonl, limit=pgn_count) if pgn_replay_jsonl else []
    if target <= 0:
        return synthetic + pgn_cases
    reserve = min(len(pgn_cases), pgn_count, target)
    chosen = synthetic[: max(0, target - reserve)]
    chosen.extend(pgn_cases[:reserve])
    if len(chosen) < target:
        chosen.extend(synthetic[len(chosen):target])
    return chosen[:target]


def _evaluate_pgn_human_probe(board: chess.Board, move: chess.Move, case: HoldoutCase) -> tuple[bool, str, dict[str, Any]]:
    try:
        reference = chess.Move.from_uci(case.reference_move)
    except ValueError:
        return False, "invalid_reference_move", {}
    if reference not in board.legal_moves:
        return False, "reference_move_illegal", {}

    color = chess.WHITE if case.side == "white" else chess.BLACK
    chosen_after = board.copy(stack=False)
    chosen_after.push(move)
    reference_after = board.copy(stack=False)
    reference_after.push(reference)
    chosen_opp_mates = _mate_in_one_moves(chosen_after)
    reference_opp_mates = _mate_in_one_moves(reference_after)
    chosen_worst = _worst_immediate_reply_margin(chosen_after, color)
    reference_worst = _worst_immediate_reply_margin(reference_after, color)
    exact = move == reference
    safe_floor = not chosen_opp_mates and chosen_worst >= reference_worst - 300
    details = {
        "reference_move": reference.uci(),
        "exact_reference_match": exact,
        "reference_san": board.san(reference),
        "chosen_worst_reply_material_margin": chosen_worst,
        "reference_worst_reply_material_margin": reference_worst,
        "reference_opponent_mates_after": reference_opp_mates,
    }
    if exact:
        return True, "matches_imported_reference_move", details
    return bool(safe_floor), "non_blunder_floor_vs_imported_reference" if safe_floor else "below_reference_safety_floor", details


def evaluate_case(case: HoldoutCase, *, search_profile: str) -> dict[str, Any]:
    board = chess.Board(case.fen)
    board.turn = chess.WHITE if case.side == "white" else chess.BLACK
    move_dict = choose_experiment_nnue_move(_board_state(board), case.side, search_profile=search_profile)
    chosen = _move_uci(move_dict)
    valid = False
    passed = False
    reason = ""
    chosen_san = ""
    extra: dict[str, Any] = {}
    legal_mates_before = _mate_threats_if_side_passed(board)
    forced_mate_two_before = _forced_mate_in_two_moves(board)
    try:
        move = chess.Move.from_uci(chosen)
        valid = move in board.legal_moves
    except Exception:
        move = None
    if valid and move is not None:
        chosen_san = board.san(move)
        after = board.copy(stack=False)
        after.push(move)
        opponent_mates_after = _mate_in_one_moves(after)
        if case.kind == "prevent_mate_in_one":
            passed = bool(legal_mates_before) and not opponent_mates_after
            reason = "prevents_mate_in_one" if passed else "opponent_still_has_mate_in_one"
        elif case.kind == "avoid_creating_mate_in_one":
            blunders = _blunders_allowing_mate_in_one(board)
            passed = bool(blunders) and not opponent_mates_after
            reason = "avoids_creating_mate_in_one" if passed else "created_or_failed_to_validate_mate_in_one"
        elif case.kind == "find_mate_in_one":
            passed = after.is_checkmate()
            reason = "chosen_move_checkmates" if passed else "missed_mate_in_one"
        elif case.kind == "find_forced_mate_in_two":
            passed = chosen in forced_mate_two_before
            reason = "chosen_forces_mate_in_two" if passed else "missed_forced_mate_in_two"
        elif case.kind == "capture_material":
            captured_value = _captured_value(board, move)
            passed = captured_value >= int(case.min_capture_value)
            reason = f"captured_value={captured_value}"
        elif case.kind == "capture_dangerous_pawn":
            passed = _dangerous_pawn_capture(board, move)
            reason = "captured_dangerous_pawn" if passed else "did_not_capture_dangerous_pawn"
        elif case.kind == "en_passant":
            passed = board.is_en_passant(move)
            reason = "played_en_passant" if passed else "missed_en_passant"
        elif case.kind == "castle_when_clean":
            passed = board.is_castling(move) or chosen in forced_mate_two_before or after.is_checkmate()
            if board.is_castling(move):
                reason = "castled"
            elif chosen in forced_mate_two_before or after.is_checkmate():
                reason = "found_stronger_forcing_mate"
            else:
                reason = "did_not_castle"
        elif case.kind == "opening_development":
            passed = _is_development_move(board, move) and not _is_bad_opening_drift(board, move)
            reason = "normal_development" if passed else "opening_drift_or_non_development"
        elif case.kind == "pgn_human_probe":
            passed, reason, extra = _evaluate_pgn_human_probe(board, move, case)
        else:
            reason = f"unknown_kind:{case.kind}"
    else:
        opponent_mates_after = []
        reason = "invalid_or_illegal_move"
    return {
        "case_id": case.case_id,
        "fen": case.fen,
        "side": case.side,
        "kind": case.kind,
        "source": case.source,
        "difficulty": case.difficulty,
        "tags": list(case.tags),
        "description": case.description,
        "reference_move": case.reference_move,
        "chosen": chosen,
        "chosen_san": chosen_san,
        "valid": valid,
        "passed": bool(passed),
        "reason": reason,
        "mate_threats_if_side_passed": legal_mates_before,
        "forced_mate_in_two_moves": forced_mate_two_before,
        "blunders_allowing_mate_in_one": _blunders_allowing_mate_in_one(board),
        "opponent_mates_after_chosen": opponent_mates_after,
        **extra,
    }


def _bucket_counts(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, int | float]]:
    out: dict[str, dict[str, int | float]] = {}
    for row in rows:
        bucket = out.setdefault(str(row.get(key) or "unknown"), {"cases": 0, "passed": 0})
        bucket["cases"] = int(bucket["cases"]) + 1
        bucket["passed"] = int(bucket["passed"]) + (1 if row.get("passed") else 0)
    for bucket in out.values():
        bucket["pass_rate"] = round(int(bucket["passed"]) / max(1, int(bucket["cases"])), 4)
    return out


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for row in rows if row.get("passed"))
    pgn_rows = [row for row in rows if row.get("kind") == "pgn_human_probe"]
    exact_pgn = sum(1 for row in pgn_rows if row.get("exact_reference_match"))
    return {
        "cases": len(rows),
        "passed": passed,
        "pass_rate": round(passed / max(1, len(rows)), 4),
        "by_kind": _bucket_counts(rows, "kind"),
        "by_source": _bucket_counts(rows, "source"),
        "by_difficulty": _bucket_counts(rows, "difficulty"),
        "pgn_human_probe": {
            "cases": len(pgn_rows),
            "passed": sum(1 for row in pgn_rows if row.get("passed")),
            "exact_reference_matches": exact_pgn,
            "exact_reference_match_rate": round(exact_pgn / max(1, len(pgn_rows)), 4),
        },
        "failed": [row for row in rows if not row.get("passed")],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run exp5 holdout behavioral probes.")
    parser.add_argument("--search-profile", default="balanced")
    parser.add_argument("--no-mirrors", action="store_true")
    parser.add_argument("--target-cases", type=int, default=100)
    parser.add_argument("--pgn-replay-jsonl", default="")
    parser.add_argument("--pgn-case-count", type=int, default=40)
    parser.add_argument("--output", default=str(ROOT / "docs" / "games" / "2026-05-13_exp5_holdout_probe.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pgn_path = Path(args.pgn_replay_jsonl).expanduser().resolve() if args.pgn_replay_jsonl else None
    cases = holdout_cases(
        include_mirrors=not bool(args.no_mirrors),
        target_cases=int(args.target_cases or 0),
        pgn_replay_jsonl=pgn_path,
        pgn_case_count=int(args.pgn_case_count or 0),
    )
    rows = [evaluate_case(case, search_profile=str(args.search_profile or "balanced")) for case in cases]
    artifact = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "engine": EXP5,
        "search_profile": str(args.search_profile or "balanced"),
        "target_cases": int(args.target_cases or 0),
        "pgn_replay_jsonl": str(pgn_path) if pgn_path else "",
        "pgn_case_count_requested": int(args.pgn_case_count or 0),
        "summary": summarize(rows),
        "cases": rows,
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
