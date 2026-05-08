"""Self-play and teacher-play training helpers for chess experiment models.

This module trains the runtime-backed chess learning artifacts:

- ``experiment`` memory DB: ``runtime/database/chess_experiment.db``
- ``experiment 2:nn`` model: ``runtime/models/chess_experiment_2_nn.json``
- ``experiment 3:dl`` model: ``runtime/models/chess_experiment_3_dl.json``
- ``experiment 4:pv`` model: ``runtime/models/chess_experiment_4_pv.json``

The training loop intentionally includes a stronger search-based teacher.
Pure student-vs-student self-play tends to collapse into repetitive openings
and noisy rewards. The teacher provides a more stable signal so the two
experimental learners can be pushed toward legal, higher-value play instead of
just reinforcing each other's mistakes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
import json
import os
from pathlib import Path
import random

import chess

from services.games.chess import (
    START_FEN,
    game_status,
    initial_board,
    legal_moves,
    move_to_uci,
    opponent,
    to_chess_board,
    validate_move,
)
from services.games.chess_engine import (
    ChessExperimentStore,
    EXPERIMENT_DIFFICULTY,
    choose_experiment_move,
    record_experiment_learning,
)
from services.games.chess_dl import (
    EXPERIMENT_DL_DIFFICULTY,
    choose_experiment_dl_move,
    default_chess_dl_model_path,
    distill_experiment_dl_from_move_history,
    record_experiment_dl_learning,
)
from services.games.chess_pv import (
    EXPERIMENT_PV_DIFFICULTY,
    choose_experiment_pv_move,
    default_chess_pv_model_path,
    record_experiment_pv_learning,
)
from services.games.chess_nn import (
    EXPERIMENT_NN_DIFFICULTY,
    choose_experiment_nn_move,
    default_chess_nn_model_path,
    record_experiment_nn_learning,
)
from services.games.chess_search import ZobristHasher, search_best_move
from services.server.runtime import default_runtime_root_path


TEACHER_DIFFICULTY = "teacher"
HARD_DIFFICULTY = "hard"
BENCHMARK_ENGINES = (
    TEACHER_DIFFICULTY,
    HARD_DIFFICULTY,
    EXPERIMENT_DIFFICULTY,
    EXPERIMENT_NN_DIFFICULTY,
    EXPERIMENT_DL_DIFFICULTY,
    EXPERIMENT_PV_DIFFICULTY,
)
DEFAULT_MAX_PLIES = 180
DEFAULT_TEACHER_DEPTH = 3
DEFAULT_STUDENT_EXPLORATION_RATE = 0.12
DEFAULT_REPORT_BASENAME = "chess_self_play_train"
_INFINITY = 10**9
_MATE_SCORE = 10**7
_ELO_START = 1500.0
_ELO_K = 24.0
_TEACHER_PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 335,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20000,
}
_TEACHER_CENTER = {chess.D4, chess.E4, chess.D5, chess.E5}
_TRAINING_OPENINGS = (
    ("italian", ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5"]),
    ("queens_gambit", ["d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6"]),
    ("caro_kann", ["e2e4", "c7c6", "d2d4", "d7d5", "b1c3", "d5e4"]),
    ("english", ["c2c4", "e7e5", "b1c3", "g8f6", "g2g3", "d7d5"]),
    ("sicilian_closed", ["e2e4", "c7c5", "b1c3", "d7d6", "g2g3", "b8c6"]),
    ("french", ["e2e4", "e7e6", "d2d4", "d7d5", "b1c3", "g8f6"]),
)
_EVAL_OPENINGS = (
    ("ruy_lopez", ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6"]),
    ("slav", ["d2d4", "d7d5", "c2c4", "c7c6", "g1f3", "g8f6"]),
    ("pirc", ["e2e4", "d7d6", "d2d4", "g8f6", "b1c3", "g7g6"]),
    ("kings_indian_attack", ["g1f3", "d7d5", "g2g3", "g8f6", "f1g2", "e7e6"]),
    ("sicilian_open", ["e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4"]),
    ("nimzo_larsen", ["b2b3", "d7d5", "c1b2", "g8f6", "e2e3", "c7c5"]),
)


@dataclass
class TrainingMatch:
    white_engine: str
    black_engine: str
    winner_color: str | None
    reason: str
    move_count: int
    final_fen: str
    uci_moves: list[str]
    opening_label: str
    student_updates: dict[str, int]
    teacher_guidance_updates: dict[str, int]
    teacher_distillation_updates: int


def _evaluation_empty_updates() -> tuple[dict[str, int], dict[str, int]]:
    return (
        {
            EXPERIMENT_DIFFICULTY: 0,
            EXPERIMENT_NN_DIFFICULTY: 0,
            EXPERIMENT_DL_DIFFICULTY: 0,
            EXPERIMENT_PV_DIFFICULTY: 0,
        },
        {
            EXPERIMENT_DIFFICULTY: 0,
            EXPERIMENT_NN_DIFFICULTY: 0,
            EXPERIMENT_DL_DIFFICULTY: 0,
            EXPERIMENT_PV_DIFFICULTY: 0,
        },
    )


def default_training_report_dir() -> Path:
    runtime_dir = os.environ.get("HACKME_RUNTIME_DIR", "").strip()
    if not runtime_dir:
        runtime_dir = str(default_runtime_root_path())
    reports_root = os.environ.get("HTML_LEARNING_REPORTS_DIR", "").strip() or os.path.join(runtime_dir, "reports")
    return Path(reports_root) / "games"


def _timestamp() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def _board_position_key(board: chess.Board) -> str:
    ep = chess.square_name(board.ep_square) if board.ep_square is not None else "-"
    return f"{board.board_fen()} {'w' if board.turn else 'b'} {board.castling_xfen()} {ep}"


def _material_score(board: chess.Board) -> int:
    score = 0
    for piece in board.piece_map().values():
        value = _TEACHER_PIECE_VALUES[piece.piece_type]
        score += value if piece.color == chess.WHITE else -value
    return score


def _adjudicate_by_material(board_state, turn: str) -> tuple[str | None, str]:
    board = to_chess_board(board_state, turn)
    score = _material_score(board)
    queens = len(board.pieces(chess.QUEEN, chess.WHITE)) + len(board.pieces(chess.QUEEN, chess.BLACK))
    rooks = len(board.pieces(chess.ROOK, chess.WHITE)) + len(board.pieces(chess.ROOK, chess.BLACK))
    decisive_threshold = 320 if queens or rooks else 220
    if abs(score) < decisive_threshold:
        return None, "max_plies_draw"
    return ("white" if score > 0 else "black"), "adjudicated_material_decisive"


def _opening_sequence_book(split: str) -> tuple[tuple[str, list[str]], ...]:
    return _EVAL_OPENINGS if split == "eval" else _TRAINING_OPENINGS


def _opening_setup_for_index(index: int, *, split: str) -> tuple[dict, str, str]:
    book = _opening_sequence_book(split)
    if not book:
        return initial_board(), "white", "standard_start"
    label, sequence = book[index % len(book)]
    board = chess.Board()
    for uci in sequence:
        board.push_uci(uci)
    turn = "white" if board.turn == chess.WHITE else "black"
    return {"__fen__": board.fen()}, turn, label


def _expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def _elo_summary(matches: list[dict]) -> list[dict]:
    ratings = {engine: _ELO_START for engine in BENCHMARK_ENGINES}
    played = {engine: 0 for engine in BENCHMARK_ENGINES}
    for match in matches:
        white = str(match["white_engine"])
        black = str(match["black_engine"])
        played[white] += 1
        played[black] += 1
        if match["winner_engine"] == white:
            white_actual, black_actual = 1.0, 0.0
        elif match["winner_engine"] == black:
            white_actual, black_actual = 0.0, 1.0
        else:
            white_actual = black_actual = 0.5
        white_expected = _expected_score(ratings[white], ratings[black])
        black_expected = _expected_score(ratings[black], ratings[white])
        ratings[white] += _ELO_K * (white_actual - white_expected)
        ratings[black] += _ELO_K * (black_actual - black_expected)
    rows = [{"engine": engine, "elo": round(rating, 2), "games": played[engine]} for engine, rating in ratings.items()]
    rows.sort(key=lambda item: (-item["elo"], item["engine"]))
    return rows


def _move_material_value(move: dict) -> int:
    captured = str(move.get("captured") or "").lower()
    promotion = str(move.get("promotion") or "").lower()
    score = _TEACHER_PIECE_VALUES.get(captured, 0)
    if promotion:
        score += max(0, _TEACHER_PIECE_VALUES.get(promotion, 0) - _TEACHER_PIECE_VALUES[chess.PAWN])
    return score


def _teacher_move_order(board: chess.Board, move: chess.Move) -> int:
    captured = board.piece_at(move.to_square)
    if captured is None and board.is_en_passant(move):
        capture_square = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
        captured = board.piece_at(capture_square)
    capture_value = _TEACHER_PIECE_VALUES.get(captured.piece_type, 0) if captured else 0
    moving = board.piece_at(move.from_square)
    moving_value = _TEACHER_PIECE_VALUES.get(moving.piece_type, 0) if moving else 0
    score = capture_value * 10 - moving_value // 25
    if move.promotion:
        score += _TEACHER_PIECE_VALUES.get(move.promotion, 0) * 8
    if board.gives_check(move):
        score += 60
    if board.is_castling(move):
        score += 35
    if move.to_square in _TEACHER_CENTER:
        score += 18
    return score


def _teacher_static_eval(board: chess.Board) -> int:
    if board.is_checkmate():
        return -_MATE_SCORE if board.turn == chess.WHITE else _MATE_SCORE
    if board.is_stalemate() or board.is_insufficient_material():
        return 0
    score = _material_score(board)
    white_mobility = float(board.legal_moves.count()) if board.turn == chess.WHITE else 0.0
    original_turn = board.turn
    board.turn = not board.turn
    try:
        other_mobility = float(board.legal_moves.count())
    finally:
        board.turn = original_turn
    score += int((white_mobility - other_mobility) * 4 if board.turn == chess.WHITE else (other_mobility - white_mobility) * 4)
    if board.is_check():
        score += -28 if board.turn == chess.WHITE else 28
    if board.has_kingside_castling_rights(chess.WHITE):
        score += 10
    if board.has_queenside_castling_rights(chess.WHITE):
        score += 6
    if board.has_kingside_castling_rights(chess.BLACK):
        score -= 10
    if board.has_queenside_castling_rights(chess.BLACK):
        score -= 6
    for square, piece in board.piece_map().items():
        if square in _TEACHER_CENTER:
            score += 12 if piece.color == chess.WHITE else -12
    return score


def choose_teacher_move(board_state, side: str, *, depth: int = DEFAULT_TEACHER_DEPTH):
    board = to_chess_board(board_state, side)
    target_turn = chess.WHITE if side == "white" else chess.BLACK
    if board.turn != target_turn:
        board.turn = target_turn
    if board.is_game_over():
        return None
    forced_mates: list[chess.Move] = []
    for move in board.legal_moves:
        board.push(move)
        if board.is_checkmate():
            forced_mates.append(move)
        board.pop()
    if forced_mates:
        best_move = sorted(forced_mates, key=lambda mv: mv.uci())[0]
        piece = board.piece_at(best_move.from_square)
        captured = board.piece_at(best_move.to_square)
        if board.is_en_passant(best_move):
            capture_square = chess.square(chess.square_file(best_move.to_square), chess.square_rank(best_move.from_square))
            captured = board.piece_at(capture_square)
        return {
            "from": chess.square_name(best_move.from_square),
            "to": chess.square_name(best_move.to_square),
            "piece": piece.symbol() if piece else "",
            "captured": captured.symbol() if captured else None,
            "promotion": chess.piece_symbol(best_move.promotion) if best_move.promotion else None,
            "castle": bool(board.is_castling(best_move)),
            "en_passant": bool(board.is_en_passant(best_move)),
        }
    search = search_best_move(
        board,
        max_depth=max(1, int(depth or DEFAULT_TEACHER_DEPTH)),
        evaluate=_teacher_static_eval,
        move_order_fn=lambda current_board, move, _ply: _teacher_move_order(current_board, move),
        hasher=ZobristHasher(seed=20260517),
    )
    best_move = search.best_move
    if best_move is None:
        return None
    piece = board.piece_at(best_move.from_square)
    captured = board.piece_at(best_move.to_square)
    if board.is_en_passant(best_move):
        capture_square = chess.square(chess.square_file(best_move.to_square), chess.square_rank(best_move.from_square))
        captured = board.piece_at(capture_square)
    return {
        "from": chess.square_name(best_move.from_square),
        "to": chess.square_name(best_move.to_square),
        "piece": piece.symbol() if piece else "",
        "captured": captured.symbol() if captured else None,
        "promotion": chess.piece_symbol(best_move.promotion) if best_move.promotion else None,
        "castle": bool(board.is_castling(best_move)),
        "en_passant": bool(board.is_en_passant(best_move)),
    }


def _random_legal_move(board_state, side: str, *, rng: random.Random):
    candidates = legal_moves(board_state, side)
    if not candidates:
        return None
    choice = rng.choice(candidates)
    return {
        "from": choice["from"],
        "to": choice["to"],
        "piece": choice.get("piece") or "",
        "captured": choice.get("captured"),
        "promotion": choice.get("promotion"),
        "castle": bool(choice.get("castle")),
        "en_passant": bool(choice.get("en_passant")),
    }


def _choose_hard_training_move(board_state, side: str, *, rng: random.Random):
    moves = legal_moves(board_state, side)
    if not moves:
        return None
    scored: list[tuple[int, dict]] = []
    for move in moves:
        try:
            applied = validate_move(board_state, side, move["from"], move["to"], move.get("promotion"))
        except ValueError:
            continue
        next_board = applied["board"]
        status = game_status(next_board, opponent(side))
        score = _move_material_value(move)
        if status["status"] == "finished" and status.get("winner_color") == side:
            score += 100000
        elif status.get("reason") == "check":
            score += 60
        if status["status"] == "active":
            reply_scores = []
            for reply in legal_moves(next_board, opponent(side)):
                try:
                    reply_applied = validate_move(next_board, opponent(side), reply["from"], reply["to"], reply.get("promotion"))
                except ValueError:
                    continue
                reply_score = _move_material_value(reply)
                reply_status = game_status(reply_applied["board"], side)
                if reply_status["status"] == "finished" and reply_status.get("winner_color") == opponent(side):
                    reply_score += 100000
                reply_scores.append(reply_score)
            if reply_scores:
                score -= max(reply_scores)
        scored.append((score, move))
    if not scored:
        return rng.choice(moves)
    best_score = max(score for score, _move in scored)
    best_moves = [move for score, move in scored if score == best_score]
    return rng.choice(best_moves)


def _choose_student_move(
    board_state,
    side: str,
    difficulty: str,
    *,
    store: ChessExperimentStore,
    nn_model_path: Path,
    dl_model_path: Path,
    pv_model_path: Path,
    rng: random.Random,
    exploration_rate: float,
):
    if exploration_rate > 0 and rng.random() < exploration_rate:
        return _random_legal_move(board_state, side, rng=rng)
    if difficulty == HARD_DIFFICULTY:
        return _choose_hard_training_move(board_state, side, rng=rng)
    if difficulty == EXPERIMENT_DIFFICULTY:
        return choose_experiment_move(board_state, side, store=store, difficulty=EXPERIMENT_DIFFICULTY)
    if difficulty == EXPERIMENT_NN_DIFFICULTY:
        return choose_experiment_nn_move(board_state, side, model_path=nn_model_path)
    if difficulty == EXPERIMENT_DL_DIFFICULTY:
        return choose_experiment_dl_move(board_state, side, model_path=dl_model_path)
    if difficulty == EXPERIMENT_PV_DIFFICULTY:
        return choose_experiment_pv_move(board_state, side, model_path=pv_model_path)
    raise ValueError(f"unsupported student difficulty: {difficulty}")


def _choose_training_move(
    board_state,
    side: str,
    difficulty: str,
    *,
    store: ChessExperimentStore,
    nn_model_path: Path,
    dl_model_path: Path,
    pv_model_path: Path,
    rng: random.Random,
    teacher_depth: int,
    exploration_rate: float,
):
    if difficulty == TEACHER_DIFFICULTY:
        return choose_teacher_move(board_state, side, depth=teacher_depth)
    return _choose_student_move(
        board_state,
        side,
        difficulty,
        store=store,
        nn_model_path=nn_model_path,
        dl_model_path=dl_model_path,
        pv_model_path=pv_model_path,
        rng=rng,
        exploration_rate=exploration_rate,
    )


def _record_row_for_side(
    *,
    difficulty: str,
    side: str,
    move_history: list[dict],
    winner_color: str | None,
    initial_fen: str,
    store: ChessExperimentStore,
    nn_model_path: Path,
    dl_model_path: Path,
    pv_model_path: Path,
    learning_source: str = "game",
) -> int:
    row = {
        "mode": "computer",
        "computer_difficulty": difficulty,
        "human_side": opponent(side),
        "initial_fen": initial_fen,
        "move_history_json": json.dumps(move_history, ensure_ascii=False),
        "learning_source": learning_source,
    }
    if difficulty == EXPERIMENT_DIFFICULTY:
        return record_experiment_learning(row, winner_color=winner_color, store=store)
    if difficulty == EXPERIMENT_NN_DIFFICULTY:
        return record_experiment_nn_learning(row, winner_color=winner_color, model_path=nn_model_path)
    if difficulty == EXPERIMENT_DL_DIFFICULTY:
        return record_experiment_dl_learning(row, winner_color=winner_color, model_path=dl_model_path)
    if difficulty == EXPERIMENT_PV_DIFFICULTY:
        return record_experiment_pv_learning(row, winner_color=winner_color, model_path=pv_model_path)
    return 0


def _apply_training(
    white_engine: str,
    black_engine: str,
    move_history: list[dict],
    winner_color: str | None,
    *,
    initial_fen: str,
    store: ChessExperimentStore,
    nn_model_path: Path,
    dl_model_path: Path,
    pv_model_path: Path,
) -> tuple[dict[str, int], dict[str, int], int]:
    student_updates = {
        EXPERIMENT_DIFFICULTY: 0,
        EXPERIMENT_NN_DIFFICULTY: 0,
        EXPERIMENT_DL_DIFFICULTY: 0,
        EXPERIMENT_PV_DIFFICULTY: 0,
    }
    teacher_guidance = {
        EXPERIMENT_DIFFICULTY: 0,
        EXPERIMENT_NN_DIFFICULTY: 0,
        EXPERIMENT_DL_DIFFICULTY: 0,
        EXPERIMENT_PV_DIFFICULTY: 0,
    }
    engines_by_side = {"white": white_engine, "black": black_engine}
    for side, difficulty in engines_by_side.items():
        if difficulty in {EXPERIMENT_DIFFICULTY, EXPERIMENT_NN_DIFFICULTY, EXPERIMENT_DL_DIFFICULTY, EXPERIMENT_PV_DIFFICULTY}:
            student_updates[difficulty] += _record_row_for_side(
                difficulty=difficulty,
                side=side,
                move_history=move_history,
                winner_color=winner_color,
                initial_fen=initial_fen,
                store=store,
                nn_model_path=nn_model_path,
                dl_model_path=dl_model_path,
                pv_model_path=pv_model_path,
                learning_source="self_play",
            )
    teacher_side = None
    for side, difficulty in engines_by_side.items():
        if difficulty == TEACHER_DIFFICULTY:
            teacher_side = side
            break
    if teacher_side and winner_color in {teacher_side, None}:
        for target_difficulty in (EXPERIMENT_DIFFICULTY, EXPERIMENT_NN_DIFFICULTY, EXPERIMENT_DL_DIFFICULTY, EXPERIMENT_PV_DIFFICULTY):
            if target_difficulty in engines_by_side.values():
                teacher_guidance[target_difficulty] += _record_row_for_side(
                    difficulty=target_difficulty,
                    side=teacher_side,
                    move_history=move_history,
                    winner_color=teacher_side if winner_color == teacher_side else None,
                    initial_fen=initial_fen,
                    store=store,
                    nn_model_path=nn_model_path,
                    dl_model_path=dl_model_path,
                    pv_model_path=pv_model_path,
                    learning_source="teacher_guidance",
                )
    teacher_distillation_updates = 0
    if teacher_side:
        teacher_distillation_updates = distill_experiment_dl_from_move_history(
            move_history,
            teacher_side=teacher_side,
            model_path=dl_model_path,
            source="teacher_distillation",
        )
    return student_updates, teacher_guidance, teacher_distillation_updates


def play_training_match(
    *,
    white_engine: str,
    black_engine: str,
    store: ChessExperimentStore,
    nn_model_path: Path,
    dl_model_path: Path,
    pv_model_path: Path,
    rng: random.Random,
    teacher_depth: int = DEFAULT_TEACHER_DEPTH,
    student_exploration_rate: float = DEFAULT_STUDENT_EXPLORATION_RATE,
    max_plies: int = DEFAULT_MAX_PLIES,
    apply_learning: bool = True,
    opening_board_state=None,
    opening_turn: str | None = None,
    opening_label: str = "standard_start",
) -> TrainingMatch:
    board = opening_board_state or initial_board()
    turn = opening_turn or "white"
    move_history: list[dict] = []
    initial_fen = to_chess_board(board, turn).fen()
    repetitions = {_board_position_key(to_chess_board(board, turn)): 1}
    winner_color = None
    reason = "active"

    for _ply in range(max_plies):
        status = game_status(board, turn)
        if status["status"] == "finished":
            winner_color = status["winner_color"]
            reason = status["reason"]
            break
        current_engine = white_engine if turn == "white" else black_engine
        move = _choose_training_move(
            board,
            turn,
            current_engine,
            store=store,
            nn_model_path=nn_model_path,
            dl_model_path=dl_model_path,
            pv_model_path=pv_model_path,
            rng=rng,
            teacher_depth=teacher_depth,
            exploration_rate=student_exploration_rate,
        )
        if not move:
            winner_color = None
            reason = "no_legal_move"
            break
        validated = validate_move(board, turn, move["from"], move["to"], move.get("promotion"))
        move_entry = {
            "by": turn,
            "from": move["from"],
            "to": move["to"],
            "piece": move.get("piece") or "",
            "captured": move.get("captured"),
            "promotion": move.get("promotion"),
            "castle": bool(move.get("castle")),
            "en_passant": bool(move.get("en_passant")),
            "uci": move_to_uci(board, move["from"], move["to"], move.get("promotion"), turn),
        }
        move_history.append(move_entry)
        board = validated["board"]
        turn = opponent(turn)
        board_key = _board_position_key(to_chess_board(board, turn))
        repetitions[board_key] = repetitions.get(board_key, 0) + 1
        if repetitions[board_key] >= 3:
            winner_color = None
            reason = "training_threefold_repetition"
            break
    else:
        winner_color, reason = _adjudicate_by_material(board, turn)

    if apply_learning:
        student_updates, teacher_guidance, teacher_distillation_updates = _apply_training(
            white_engine,
            black_engine,
            move_history,
            winner_color,
            initial_fen=initial_fen,
            store=store,
            nn_model_path=nn_model_path,
            dl_model_path=dl_model_path,
            pv_model_path=pv_model_path,
        )
    else:
        student_updates, teacher_guidance = _evaluation_empty_updates()
        teacher_distillation_updates = 0
    final_board = to_chess_board(board, turn)
    return TrainingMatch(
        white_engine=white_engine,
        black_engine=black_engine,
        winner_color=winner_color,
        reason=reason,
        move_count=len(move_history),
        final_fen=final_board.fen() if move_history else START_FEN,
        uci_moves=[entry["uci"] for entry in move_history],
        opening_label=opening_label,
        student_updates=student_updates,
        teacher_guidance_updates=teacher_guidance,
        teacher_distillation_updates=teacher_distillation_updates,
    )


def _winner_for_engine(match: TrainingMatch, engine: str) -> str:
    if match.winner_color is None:
        return "draw"
    winning_engine = match.white_engine if match.winner_color == "white" else match.black_engine
    return "win" if winning_engine == engine else "loss"


def _engine_bucket_template() -> dict:
    return {
        "games": 0,
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "points": 0.0,
    }


def _run_evaluation_matchups(
    matchups: list[tuple[str, str]],
    *,
    label: str,
    store: ChessExperimentStore,
    nn_model_path: Path,
    dl_model_path: Path,
    pv_model_path: Path,
    teacher_depth: int,
    max_plies: int,
    seed: int,
    opening_split: str,
) -> dict:
    rng = random.Random(seed)
    matches: list[dict] = []
    by_engine = {engine: _engine_bucket_template() for engine in BENCHMARK_ENGINES}
    suspicious_matches: list[dict] = []
    for index, (white_engine, black_engine) in enumerate(matchups, start=1):
        opening_board_state, opening_turn, opening_label = _opening_setup_for_index(seed + index - 1, split=opening_split)
        match = play_training_match(
            white_engine=white_engine,
            black_engine=black_engine,
            store=store,
            nn_model_path=nn_model_path,
            dl_model_path=dl_model_path,
            pv_model_path=pv_model_path,
            rng=rng,
            teacher_depth=teacher_depth,
            student_exploration_rate=0.0,
            max_plies=max_plies,
            apply_learning=False,
            opening_board_state=opening_board_state,
            opening_turn=opening_turn,
            opening_label=opening_label,
        )
        winner_engine = None
        if match.winner_color == "white":
            winner_engine = white_engine
        elif match.winner_color == "black":
            winner_engine = black_engine
        row = {
            "index": index,
            "white_engine": white_engine,
            "black_engine": black_engine,
            "winner_color": match.winner_color,
            "winner_engine": winner_engine,
            "reason": match.reason,
            "move_count": match.move_count,
            "final_fen": match.final_fen,
            "opening_label": match.opening_label,
        }
        matches.append(row)
        for engine in {white_engine, black_engine}:
            bucket = by_engine.setdefault(engine, _engine_bucket_template())
            bucket["games"] += 1
            verdict = _winner_for_engine(match, engine)
            if verdict == "win":
                bucket["wins"] += 1
                bucket["points"] += 1.0
            elif verdict == "loss":
                bucket["losses"] += 1
            else:
                bucket["draws"] += 1
                bucket["points"] += 0.5
        if match.reason == "no_legal_move" or match.move_count < 4:
            suspicious_matches.append(row)
    standings = []
    for engine, bucket in by_engine.items():
        if bucket["games"] <= 0:
            continue
        standings.append({
            "engine": engine,
            **bucket,
            "win_rate": round(bucket["wins"] / bucket["games"], 4),
            "score_rate": round(bucket["points"] / bucket["games"], 4),
        })
    standings.sort(key=lambda item: (-item["points"], -item["wins"], item["engine"]))
    return {
        "label": label,
        "seed": seed,
        "teacher_depth": teacher_depth,
        "max_plies": max_plies,
        "games_played": len(matches),
        "matches": matches,
        "standings": standings,
        "elo": _elo_summary(matches),
        "suspicious_matches": suspicious_matches,
        "opening_split": opening_split,
        "pass": len(suspicious_matches) == 0,
    }


def run_post_training_smoke_evaluation(
    *,
    store: ChessExperimentStore | None = None,
    nn_model_path: Path | None = None,
    dl_model_path: Path | None = None,
    pv_model_path: Path | None = None,
    teacher_depth: int = DEFAULT_TEACHER_DEPTH,
    max_plies: int = DEFAULT_MAX_PLIES,
    games_per_pair: int = 1,
    seed: int = 20260508,
) -> dict:
    store = store or ChessExperimentStore()
    nn_model_path = Path(nn_model_path or default_chess_nn_model_path())
    dl_model_path = Path(dl_model_path or default_chess_dl_model_path())
    pv_model_path = Path(pv_model_path or default_chess_pv_model_path())
    matchups: list[tuple[str, str]] = []
    for _ in range(max(0, int(games_per_pair or 0))):
        matchups.extend([
            (EXPERIMENT_DIFFICULTY, HARD_DIFFICULTY),
            (HARD_DIFFICULTY, EXPERIMENT_DIFFICULTY),
            (EXPERIMENT_DIFFICULTY, TEACHER_DIFFICULTY),
            (TEACHER_DIFFICULTY, EXPERIMENT_DIFFICULTY),
            (EXPERIMENT_NN_DIFFICULTY, HARD_DIFFICULTY),
            (HARD_DIFFICULTY, EXPERIMENT_NN_DIFFICULTY),
            (EXPERIMENT_NN_DIFFICULTY, TEACHER_DIFFICULTY),
            (TEACHER_DIFFICULTY, EXPERIMENT_NN_DIFFICULTY),
            (EXPERIMENT_DL_DIFFICULTY, HARD_DIFFICULTY),
            (HARD_DIFFICULTY, EXPERIMENT_DL_DIFFICULTY),
            (EXPERIMENT_DL_DIFFICULTY, TEACHER_DIFFICULTY),
            (TEACHER_DIFFICULTY, EXPERIMENT_DL_DIFFICULTY),
            (EXPERIMENT_PV_DIFFICULTY, HARD_DIFFICULTY),
            (HARD_DIFFICULTY, EXPERIMENT_PV_DIFFICULTY),
            (EXPERIMENT_PV_DIFFICULTY, TEACHER_DIFFICULTY),
            (TEACHER_DIFFICULTY, EXPERIMENT_PV_DIFFICULTY),
        ])
    summary = _run_evaluation_matchups(
        matchups,
        label="post_training_smoke",
        store=store,
        nn_model_path=nn_model_path,
        dl_model_path=dl_model_path,
        pv_model_path=pv_model_path,
        teacher_depth=teacher_depth,
        max_plies=max_plies,
        seed=seed,
        opening_split="eval",
    )
    summary["target_engines"] = [EXPERIMENT_DIFFICULTY, EXPERIMENT_NN_DIFFICULTY, EXPERIMENT_DL_DIFFICULTY, EXPERIMENT_PV_DIFFICULTY]
    summary["reference_engines"] = [HARD_DIFFICULTY, TEACHER_DIFFICULTY]
    return summary


def run_round_robin_benchmark(
    *,
    store: ChessExperimentStore | None = None,
    nn_model_path: Path | None = None,
    dl_model_path: Path | None = None,
    pv_model_path: Path | None = None,
    teacher_depth: int = DEFAULT_TEACHER_DEPTH,
    max_plies: int = DEFAULT_MAX_PLIES,
    rounds: int = 2,
    seed: int = 20260509,
) -> dict:
    store = store or ChessExperimentStore()
    nn_model_path = Path(nn_model_path or default_chess_nn_model_path())
    dl_model_path = Path(dl_model_path or default_chess_dl_model_path())
    pv_model_path = Path(pv_model_path or default_chess_pv_model_path())
    rounds = max(0, int(rounds or 0))
    matchups: list[tuple[str, str]] = []
    for engine_a, engine_b in combinations(BENCHMARK_ENGINES, 2):
        for _ in range(rounds):
            matchups.append((engine_a, engine_b))
            matchups.append((engine_b, engine_a))
    summary = _run_evaluation_matchups(
        matchups,
        label="round_robin_benchmark",
        store=store,
        nn_model_path=nn_model_path,
        dl_model_path=dl_model_path,
        pv_model_path=pv_model_path,
        teacher_depth=teacher_depth,
        max_plies=max_plies,
        seed=seed,
        opening_split="eval",
    )
    matrix = {}
    head_to_head = []
    for engine in BENCHMARK_ENGINES:
        row = {}
        for opponent_engine in BENCHMARK_ENGINES:
            if opponent_engine == engine:
                row[opponent_engine] = None
                continue
            bucket = {
                "games": 0,
                "wins": 0,
                "losses": 0,
                "draws": 0,
                "points": 0.0,
            }
            for match in summary["matches"]:
                participants = {match["white_engine"], match["black_engine"]}
                if participants != {engine, opponent_engine}:
                    continue
                bucket["games"] += 1
                if match["winner_engine"] == engine:
                    bucket["wins"] += 1
                    bucket["points"] += 1.0
                elif match["winner_engine"] == opponent_engine:
                    bucket["losses"] += 1
                else:
                    bucket["draws"] += 1
                    bucket["points"] += 0.5
            if bucket["games"] > 0:
                bucket["win_rate"] = round(bucket["wins"] / bucket["games"], 4)
                bucket["score_rate"] = round(bucket["points"] / bucket["games"], 4)
                if engine < opponent_engine:
                    head_to_head.append({
                        "engine_a": engine,
                        "engine_b": opponent_engine,
                        **bucket,
                    })
            row[opponent_engine] = bucket
        matrix[engine] = row
    summary["engines"] = list(BENCHMARK_ENGINES)
    summary["rounds"] = rounds
    summary["matrix"] = matrix
    summary["head_to_head"] = sorted(head_to_head, key=lambda item: (-item["score_rate"], item["engine_a"], item["engine_b"]))
    return summary


def run_training_session(
    *,
    exp1_teacher_games: int = 12,
    exp2_teacher_games: int = 12,
    exp3_teacher_games: int = 0,
    exp4_teacher_games: int = 0,
    hard_exp1_games: int = 8,
    hard_exp2_games: int = 8,
    hard_exp3_games: int = 0,
    hard_exp4_games: int = 0,
    cross_games: int = 6,
    cross_exp1_exp3_games: int = 0,
    cross_exp2_exp3_games: int = 0,
    cross_exp1_exp4_games: int = 0,
    cross_exp2_exp4_games: int = 0,
    cross_exp3_exp4_games: int = 0,
    teacher_depth: int = DEFAULT_TEACHER_DEPTH,
    max_plies: int = DEFAULT_MAX_PLIES,
    student_exploration_rate: float = DEFAULT_STUDENT_EXPLORATION_RATE,
    seed: int = 20260507,
    store: ChessExperimentStore | None = None,
    nn_model_path: Path | None = None,
    dl_model_path: Path | None = None,
    pv_model_path: Path | None = None,
) -> dict:
    rng = random.Random(seed)
    store = store or ChessExperimentStore()
    nn_model_path = Path(nn_model_path or default_chess_nn_model_path())
    dl_model_path = Path(dl_model_path or default_chess_dl_model_path())
    pv_model_path = Path(pv_model_path or default_chess_pv_model_path())
    matches: list[TrainingMatch] = []

    schedule: list[tuple[str, str]] = []
    for index in range(max(0, int(exp1_teacher_games or 0))):
        if index % 2 == 0:
            schedule.append((TEACHER_DIFFICULTY, EXPERIMENT_DIFFICULTY))
        else:
            schedule.append((EXPERIMENT_DIFFICULTY, TEACHER_DIFFICULTY))
    for index in range(max(0, int(exp2_teacher_games or 0))):
        if index % 2 == 0:
            schedule.append((TEACHER_DIFFICULTY, EXPERIMENT_NN_DIFFICULTY))
        else:
            schedule.append((EXPERIMENT_NN_DIFFICULTY, TEACHER_DIFFICULTY))
    for index in range(max(0, int(exp3_teacher_games or 0))):
        if index % 2 == 0:
            schedule.append((TEACHER_DIFFICULTY, EXPERIMENT_DL_DIFFICULTY))
        else:
            schedule.append((EXPERIMENT_DL_DIFFICULTY, TEACHER_DIFFICULTY))
    for index in range(max(0, int(exp4_teacher_games or 0))):
        if index % 2 == 0:
            schedule.append((TEACHER_DIFFICULTY, EXPERIMENT_PV_DIFFICULTY))
        else:
            schedule.append((EXPERIMENT_PV_DIFFICULTY, TEACHER_DIFFICULTY))
    for index in range(max(0, int(hard_exp1_games or 0))):
        if index % 2 == 0:
            schedule.append((HARD_DIFFICULTY, EXPERIMENT_DIFFICULTY))
        else:
            schedule.append((EXPERIMENT_DIFFICULTY, HARD_DIFFICULTY))
    for index in range(max(0, int(hard_exp2_games or 0))):
        if index % 2 == 0:
            schedule.append((HARD_DIFFICULTY, EXPERIMENT_NN_DIFFICULTY))
        else:
            schedule.append((EXPERIMENT_NN_DIFFICULTY, HARD_DIFFICULTY))
    for index in range(max(0, int(hard_exp3_games or 0))):
        if index % 2 == 0:
            schedule.append((HARD_DIFFICULTY, EXPERIMENT_DL_DIFFICULTY))
        else:
            schedule.append((EXPERIMENT_DL_DIFFICULTY, HARD_DIFFICULTY))
    for index in range(max(0, int(hard_exp4_games or 0))):
        if index % 2 == 0:
            schedule.append((HARD_DIFFICULTY, EXPERIMENT_PV_DIFFICULTY))
        else:
            schedule.append((EXPERIMENT_PV_DIFFICULTY, HARD_DIFFICULTY))
    for index in range(max(0, int(cross_games or 0))):
        if index % 2 == 0:
            schedule.append((EXPERIMENT_DIFFICULTY, EXPERIMENT_NN_DIFFICULTY))
        else:
            schedule.append((EXPERIMENT_NN_DIFFICULTY, EXPERIMENT_DIFFICULTY))
    for index in range(max(0, int(cross_exp1_exp3_games or 0))):
        if index % 2 == 0:
            schedule.append((EXPERIMENT_DIFFICULTY, EXPERIMENT_DL_DIFFICULTY))
        else:
            schedule.append((EXPERIMENT_DL_DIFFICULTY, EXPERIMENT_DIFFICULTY))
    for index in range(max(0, int(cross_exp2_exp3_games or 0))):
        if index % 2 == 0:
            schedule.append((EXPERIMENT_NN_DIFFICULTY, EXPERIMENT_DL_DIFFICULTY))
        else:
            schedule.append((EXPERIMENT_DL_DIFFICULTY, EXPERIMENT_NN_DIFFICULTY))
    for index in range(max(0, int(cross_exp1_exp4_games or 0))):
        if index % 2 == 0:
            schedule.append((EXPERIMENT_DIFFICULTY, EXPERIMENT_PV_DIFFICULTY))
        else:
            schedule.append((EXPERIMENT_PV_DIFFICULTY, EXPERIMENT_DIFFICULTY))
    for index in range(max(0, int(cross_exp2_exp4_games or 0))):
        if index % 2 == 0:
            schedule.append((EXPERIMENT_NN_DIFFICULTY, EXPERIMENT_PV_DIFFICULTY))
        else:
            schedule.append((EXPERIMENT_PV_DIFFICULTY, EXPERIMENT_NN_DIFFICULTY))
    for index in range(max(0, int(cross_exp3_exp4_games or 0))):
        if index % 2 == 0:
            schedule.append((EXPERIMENT_DL_DIFFICULTY, EXPERIMENT_PV_DIFFICULTY))
        else:
            schedule.append((EXPERIMENT_PV_DIFFICULTY, EXPERIMENT_DL_DIFFICULTY))

    summary = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "seed": seed,
        "teacher_depth": teacher_depth,
        "max_plies": max_plies,
        "student_exploration_rate": student_exploration_rate,
        "experiment_db_path": str(store.db_path),
        "experiment_2_nn_model_path": str(nn_model_path),
        "experiment_3_dl_model_path": str(dl_model_path),
        "experiment_4_pv_model_path": str(pv_model_path),
        "requested_games": {
            "teacher_vs_exp1": int(exp1_teacher_games or 0),
            "teacher_vs_exp2": int(exp2_teacher_games or 0),
            "teacher_vs_exp3": int(exp3_teacher_games or 0),
            "teacher_vs_exp4": int(exp4_teacher_games or 0),
            "hard_vs_exp1": int(hard_exp1_games or 0),
            "hard_vs_exp2": int(hard_exp2_games or 0),
            "hard_vs_exp3": int(hard_exp3_games or 0),
            "hard_vs_exp4": int(hard_exp4_games or 0),
            "cross_play": int(cross_games or 0),
            "cross_exp1_exp3": int(cross_exp1_exp3_games or 0),
            "cross_exp2_exp3": int(cross_exp2_exp3_games or 0),
            "cross_exp1_exp4": int(cross_exp1_exp4_games or 0),
            "cross_exp2_exp4": int(cross_exp2_exp4_games or 0),
            "cross_exp3_exp4": int(cross_exp3_exp4_games or 0),
        },
        "games_played": 0,
        "results": {
            "white_wins": 0,
            "black_wins": 0,
            "draws": 0,
        },
        "updates": {
            EXPERIMENT_DIFFICULTY: 0,
            EXPERIMENT_NN_DIFFICULTY: 0,
            EXPERIMENT_DL_DIFFICULTY: 0,
            EXPERIMENT_PV_DIFFICULTY: 0,
            "teacher_guidance_exp1": 0,
            "teacher_guidance_exp2": 0,
            "teacher_guidance_exp3": 0,
            "teacher_guidance_exp4": 0,
            "teacher_distillation_exp3": 0,
        },
        "matches": [],
    }

    for white_engine, black_engine in schedule:
        opening_board_state, opening_turn, opening_label = _opening_setup_for_index(seed + summary["games_played"], split="train")
        match = play_training_match(
            white_engine=white_engine,
            black_engine=black_engine,
            store=store,
            nn_model_path=nn_model_path,
            dl_model_path=dl_model_path,
            pv_model_path=pv_model_path,
            rng=rng,
            teacher_depth=teacher_depth,
            student_exploration_rate=student_exploration_rate,
            max_plies=max_plies,
            opening_board_state=opening_board_state,
            opening_turn=opening_turn,
            opening_label=opening_label,
        )
        matches.append(match)
        summary["games_played"] += 1
        if match.winner_color == "white":
            summary["results"]["white_wins"] += 1
        elif match.winner_color == "black":
            summary["results"]["black_wins"] += 1
        else:
            summary["results"]["draws"] += 1
        summary["updates"][EXPERIMENT_DIFFICULTY] += int(match.student_updates.get(EXPERIMENT_DIFFICULTY) or 0)
        summary["updates"][EXPERIMENT_NN_DIFFICULTY] += int(match.student_updates.get(EXPERIMENT_NN_DIFFICULTY) or 0)
        summary["updates"][EXPERIMENT_DL_DIFFICULTY] += int(match.student_updates.get(EXPERIMENT_DL_DIFFICULTY) or 0)
        summary["updates"][EXPERIMENT_PV_DIFFICULTY] += int(match.student_updates.get(EXPERIMENT_PV_DIFFICULTY) or 0)
        summary["updates"]["teacher_guidance_exp1"] += int(match.teacher_guidance_updates.get(EXPERIMENT_DIFFICULTY) or 0)
        summary["updates"]["teacher_guidance_exp2"] += int(match.teacher_guidance_updates.get(EXPERIMENT_NN_DIFFICULTY) or 0)
        summary["updates"]["teacher_guidance_exp3"] += int(match.teacher_guidance_updates.get(EXPERIMENT_DL_DIFFICULTY) or 0)
        summary["updates"]["teacher_guidance_exp4"] += int(match.teacher_guidance_updates.get(EXPERIMENT_PV_DIFFICULTY) or 0)
        summary["updates"]["teacher_distillation_exp3"] += int(match.teacher_distillation_updates or 0)
        summary["matches"].append(
            {
                "white_engine": match.white_engine,
                "black_engine": match.black_engine,
                "winner_color": match.winner_color,
                "reason": match.reason,
                "move_count": match.move_count,
                "final_fen": match.final_fen,
                "opening_label": match.opening_label,
                "uci_moves": match.uci_moves,
                "student_updates": match.student_updates,
                "teacher_guidance_updates": match.teacher_guidance_updates,
                "teacher_distillation_updates": match.teacher_distillation_updates,
            }
        )
    return summary


def write_training_report(summary: dict, *, report_dir: Path | None = None, basename: str = DEFAULT_REPORT_BASENAME) -> dict:
    report_dir = Path(report_dir or default_training_report_dir())
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = _timestamp()
    json_path = report_dir / f"{basename}_{stamp}.json"
    md_path = report_dir / f"{basename}_{stamp}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        f"# {basename}",
        "",
        f"- generated_at: `{summary.get('generated_at')}`",
        f"- games_played: `{summary.get('games_played')}`",
        f"- experiment_db_path: `{summary.get('experiment_db_path')}`",
        f"- experiment_2_nn_model_path: `{summary.get('experiment_2_nn_model_path')}`",
        f"- experiment_3_dl_model_path: `{summary.get('experiment_3_dl_model_path')}`",
        f"- experiment_4_pv_model_path: `{summary.get('experiment_4_pv_model_path')}`",
        "",
        "## Results",
        "",
        f"- white_wins: `{summary.get('results', {}).get('white_wins', 0)}`",
        f"- black_wins: `{summary.get('results', {}).get('black_wins', 0)}`",
        f"- draws: `{summary.get('results', {}).get('draws', 0)}`",
        "",
        "## Updates",
        "",
        f"- experiment: `{summary.get('updates', {}).get(EXPERIMENT_DIFFICULTY, 0)}`",
        f"- experiment 2:nn: `{summary.get('updates', {}).get(EXPERIMENT_NN_DIFFICULTY, 0)}`",
        f"- experiment 3:dl: `{summary.get('updates', {}).get(EXPERIMENT_DL_DIFFICULTY, 0)}`",
        f"- experiment 4:pv: `{summary.get('updates', {}).get(EXPERIMENT_PV_DIFFICULTY, 0)}`",
        f"- teacher_guidance_exp1: `{summary.get('updates', {}).get('teacher_guidance_exp1', 0)}`",
        f"- teacher_guidance_exp2: `{summary.get('updates', {}).get('teacher_guidance_exp2', 0)}`",
        f"- teacher_guidance_exp3: `{summary.get('updates', {}).get('teacher_guidance_exp3', 0)}`",
        f"- teacher_guidance_exp4: `{summary.get('updates', {}).get('teacher_guidance_exp4', 0)}`",
        f"- teacher_distillation_exp3: `{summary.get('updates', {}).get('teacher_distillation_exp3', 0)}`",
        "",
        "## Requested Games",
        "",
        f"- teacher_vs_exp1: `{summary.get('requested_games', {}).get('teacher_vs_exp1', 0)}`",
        f"- teacher_vs_exp2: `{summary.get('requested_games', {}).get('teacher_vs_exp2', 0)}`",
        f"- teacher_vs_exp3: `{summary.get('requested_games', {}).get('teacher_vs_exp3', 0)}`",
        f"- teacher_vs_exp4: `{summary.get('requested_games', {}).get('teacher_vs_exp4', 0)}`",
        f"- hard_vs_exp1: `{summary.get('requested_games', {}).get('hard_vs_exp1', 0)}`",
        f"- hard_vs_exp2: `{summary.get('requested_games', {}).get('hard_vs_exp2', 0)}`",
        f"- hard_vs_exp3: `{summary.get('requested_games', {}).get('hard_vs_exp3', 0)}`",
        f"- hard_vs_exp4: `{summary.get('requested_games', {}).get('hard_vs_exp4', 0)}`",
        f"- cross_play: `{summary.get('requested_games', {}).get('cross_play', 0)}`",
        f"- cross_exp1_exp3: `{summary.get('requested_games', {}).get('cross_exp1_exp3', 0)}`",
        f"- cross_exp2_exp3: `{summary.get('requested_games', {}).get('cross_exp2_exp3', 0)}`",
        f"- cross_exp1_exp4: `{summary.get('requested_games', {}).get('cross_exp1_exp4', 0)}`",
        f"- cross_exp2_exp4: `{summary.get('requested_games', {}).get('cross_exp2_exp4', 0)}`",
        f"- cross_exp3_exp4: `{summary.get('requested_games', {}).get('cross_exp3_exp4', 0)}`",
        "",
        "## Recent Matches",
        "",
    ]
    for match in summary.get("matches", [])[-10:]:
        lines.append(
            f"- {match['white_engine']} vs {match['black_engine']}: "
            f"`winner={match['winner_color'] or 'draw'}`, "
            f"`reason={match['reason']}`, "
            f"`plies={match['move_count']}`, "
            f"`opening={match.get('opening_label') or 'standard_start'}`"
        )
    smoke = summary.get("smoke_evaluation") or {}
    if smoke:
        lines.extend([
            "",
            "## Post-Training Smoke",
            "",
            f"- pass: `{bool(smoke.get('pass'))}`",
            f"- games_played: `{smoke.get('games_played', 0)}`",
            f"- suspicious_matches: `{len(smoke.get('suspicious_matches') or [])}`",
            "",
            "### Smoke Standings",
            "",
        ])
        for row in smoke.get("standings", []):
            lines.append(
                f"- {row['engine']}: "
                f"`W={row['wins']}` `L={row['losses']}` `D={row['draws']}` "
                f"`score={row['points']}` `win_rate={row['win_rate']}`"
            )
    benchmark = summary.get("benchmark") or {}
    if benchmark:
        lines.extend([
            "",
            "## Round-Robin Benchmark",
            "",
            f"- rounds: `{benchmark.get('rounds', 0)}`",
            f"- games_played: `{benchmark.get('games_played', 0)}`",
            f"- suspicious_matches: `{len(benchmark.get('suspicious_matches') or [])}`",
            f"- opening_split: `{benchmark.get('opening_split', 'eval')}`",
            "",
            "### Benchmark Standings",
            "",
        ])
        for row in benchmark.get("standings", []):
            lines.append(
                f"- {row['engine']}: "
                f"`W={row['wins']}` `L={row['losses']}` `D={row['draws']}` "
                f"`score={row['points']}` `score_rate={row['score_rate']}`"
            )
        if benchmark.get("elo"):
            lines.extend([
                "",
                "### Benchmark Elo",
                "",
            ])
            for row in benchmark.get("elo", []):
                lines.append(f"- {row['engine']}: `elo={row['elo']}` `games={row['games']}`")
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {
        "json_report": str(json_path),
        "md_report": str(md_path),
    }
