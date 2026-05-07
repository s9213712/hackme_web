"""Self-play and teacher-play training helpers for chess experiment models.

This module trains the two existing runtime-backed chess learning artifacts:

- ``experiment`` memory DB: ``runtime/database/chess_experiment.db``
- ``experiment 2:nn`` model: ``runtime/models/chess_experiment_2_nn.json``

The training loop intentionally includes a stronger search-based teacher.
Pure student-vs-student self-play tends to collapse into repetitive openings
and noisy rewards. The teacher provides a more stable signal so the two
experimental learners can be pushed toward legal, higher-value play instead of
just reinforcing each other's mistakes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
from services.games.chess_nn import (
    EXPERIMENT_NN_DIFFICULTY,
    choose_experiment_nn_move,
    default_chess_nn_model_path,
    record_experiment_nn_learning,
)


TEACHER_DIFFICULTY = "teacher"
DEFAULT_MAX_PLIES = 180
DEFAULT_TEACHER_DEPTH = 3
DEFAULT_STUDENT_EXPLORATION_RATE = 0.12
DEFAULT_REPORT_BASENAME = "chess_self_play_train"
_INFINITY = 10**9
_MATE_SCORE = 10**7
_TEACHER_PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 335,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20000,
}
_TEACHER_CENTER = {chess.D4, chess.E4, chess.D5, chess.E5}


@dataclass
class TrainingMatch:
    white_engine: str
    black_engine: str
    winner_color: str | None
    reason: str
    move_count: int
    final_fen: str
    uci_moves: list[str]
    student_updates: dict[str, int]
    teacher_guidance_updates: dict[str, int]


def default_training_report_dir() -> Path:
    runtime_dir = os.environ.get("HACKME_RUNTIME_DIR", "").strip()
    if not runtime_dir:
        runtime_dir = os.path.join(os.getcwd(), "runtime")
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
    if abs(score) <= 80:
        return None, "max_plies_draw"
    return ("white" if score > 0 else "black"), "adjudicated_material"


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


def _teacher_quiescence(board: chess.Board, alpha: int, beta: int, color_sign: int) -> int:
    stand_pat = color_sign * _teacher_static_eval(board)
    if stand_pat >= beta:
        return beta
    if stand_pat > alpha:
        alpha = stand_pat
    captures = [move for move in board.legal_moves if board.is_capture(move) or move.promotion or board.gives_check(move)]
    captures.sort(key=lambda mv: _teacher_move_order(board, mv), reverse=True)
    for move in captures:
        board.push(move)
        score = -_teacher_quiescence(board, -beta, -alpha, -color_sign)
        board.pop()
        if score >= beta:
            return beta
        if score > alpha:
            alpha = score
    return alpha


def _teacher_negamax(board: chess.Board, depth: int, alpha: int, beta: int, color_sign: int, transposition: dict) -> int:
    key = (_board_position_key(board), depth, color_sign)
    cached = transposition.get(key)
    if cached is not None:
        return cached
    if depth <= 0 or board.is_game_over():
        score = _teacher_quiescence(board, alpha, beta, color_sign)
        transposition[key] = score
        return score

    best = -_INFINITY
    moves = sorted(board.legal_moves, key=lambda mv: _teacher_move_order(board, mv), reverse=True)
    for move in moves:
        board.push(move)
        score = -_teacher_negamax(board, depth - 1, -beta, -alpha, -color_sign, transposition)
        board.pop()
        if score > best:
            best = score
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    transposition[key] = best
    return best


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
    root_sign = 1 if board.turn == chess.WHITE else -1
    transposition: dict[tuple[str, int, int], int] = {}
    best_move = None
    best_score = -_INFINITY
    alpha = -_INFINITY
    beta = _INFINITY
    moves = sorted(board.legal_moves, key=lambda mv: _teacher_move_order(board, mv), reverse=True)
    for move in moves:
        board.push(move)
        immediate_mate = board.is_checkmate()
        score = -_teacher_negamax(board, depth - 1, -beta, -alpha, -root_sign, transposition)
        if immediate_mate:
            score += _MATE_SCORE
        board.pop()
        if best_move is None or score > best_score or (score == best_score and move.uci() < best_move.uci()):
            best_move = move
            best_score = score
        if score > alpha:
            alpha = score
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


def _choose_student_move(board_state, side: str, difficulty: str, *, store: ChessExperimentStore, nn_model_path: Path, rng: random.Random, exploration_rate: float):
    if exploration_rate > 0 and rng.random() < exploration_rate:
        return _random_legal_move(board_state, side, rng=rng)
    if difficulty == EXPERIMENT_DIFFICULTY:
        return choose_experiment_move(board_state, side, store=store, difficulty=EXPERIMENT_DIFFICULTY)
    if difficulty == EXPERIMENT_NN_DIFFICULTY:
        return choose_experiment_nn_move(board_state, side, model_path=nn_model_path)
    raise ValueError(f"unsupported student difficulty: {difficulty}")


def _choose_training_move(board_state, side: str, difficulty: str, *, store: ChessExperimentStore, nn_model_path: Path, rng: random.Random, teacher_depth: int, exploration_rate: float):
    if difficulty == TEACHER_DIFFICULTY:
        return choose_teacher_move(board_state, side, depth=teacher_depth)
    return _choose_student_move(
        board_state,
        side,
        difficulty,
        store=store,
        nn_model_path=nn_model_path,
        rng=rng,
        exploration_rate=exploration_rate,
    )


def _record_row_for_side(*, difficulty: str, side: str, move_history: list[dict], winner_color: str | None, store: ChessExperimentStore, nn_model_path: Path) -> int:
    row = {
        "mode": "computer",
        "computer_difficulty": difficulty,
        "human_side": opponent(side),
        "move_history_json": json.dumps(move_history, ensure_ascii=False),
    }
    if difficulty == EXPERIMENT_DIFFICULTY:
        return record_experiment_learning(row, winner_color=winner_color, store=store)
    if difficulty == EXPERIMENT_NN_DIFFICULTY:
        return record_experiment_nn_learning(row, winner_color=winner_color, model_path=nn_model_path)
    return 0


def _apply_training(white_engine: str, black_engine: str, move_history: list[dict], winner_color: str | None, *, store: ChessExperimentStore, nn_model_path: Path) -> tuple[dict[str, int], dict[str, int]]:
    student_updates = {
        EXPERIMENT_DIFFICULTY: 0,
        EXPERIMENT_NN_DIFFICULTY: 0,
    }
    teacher_guidance = {
        EXPERIMENT_DIFFICULTY: 0,
        EXPERIMENT_NN_DIFFICULTY: 0,
    }
    engines_by_side = {"white": white_engine, "black": black_engine}
    for side, difficulty in engines_by_side.items():
        if difficulty in {EXPERIMENT_DIFFICULTY, EXPERIMENT_NN_DIFFICULTY}:
            student_updates[difficulty] += _record_row_for_side(
                difficulty=difficulty,
                side=side,
                move_history=move_history,
                winner_color=winner_color,
                store=store,
                nn_model_path=nn_model_path,
            )
    teacher_side = None
    for side, difficulty in engines_by_side.items():
        if difficulty == TEACHER_DIFFICULTY:
            teacher_side = side
            break
    if teacher_side and winner_color in {teacher_side, None}:
        for target_difficulty in (EXPERIMENT_DIFFICULTY, EXPERIMENT_NN_DIFFICULTY):
            if target_difficulty in engines_by_side.values():
                teacher_guidance[target_difficulty] += _record_row_for_side(
                    difficulty=target_difficulty,
                    side=teacher_side,
                    move_history=move_history,
                    winner_color=teacher_side if winner_color == teacher_side else None,
                    store=store,
                    nn_model_path=nn_model_path,
                )
    return student_updates, teacher_guidance


def play_training_match(
    *,
    white_engine: str,
    black_engine: str,
    store: ChessExperimentStore,
    nn_model_path: Path,
    rng: random.Random,
    teacher_depth: int = DEFAULT_TEACHER_DEPTH,
    student_exploration_rate: float = DEFAULT_STUDENT_EXPLORATION_RATE,
    max_plies: int = DEFAULT_MAX_PLIES,
) -> TrainingMatch:
    board = initial_board()
    turn = "white"
    move_history: list[dict] = []
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

    student_updates, teacher_guidance = _apply_training(
        white_engine,
        black_engine,
        move_history,
        winner_color,
        store=store,
        nn_model_path=nn_model_path,
    )
    final_board = to_chess_board(board, turn)
    return TrainingMatch(
        white_engine=white_engine,
        black_engine=black_engine,
        winner_color=winner_color,
        reason=reason,
        move_count=len(move_history),
        final_fen=final_board.fen() if move_history else START_FEN,
        uci_moves=[entry["uci"] for entry in move_history],
        student_updates=student_updates,
        teacher_guidance_updates=teacher_guidance,
    )


def run_training_session(
    *,
    exp1_teacher_games: int = 12,
    exp2_teacher_games: int = 12,
    cross_games: int = 6,
    teacher_depth: int = DEFAULT_TEACHER_DEPTH,
    max_plies: int = DEFAULT_MAX_PLIES,
    student_exploration_rate: float = DEFAULT_STUDENT_EXPLORATION_RATE,
    seed: int = 20260507,
    store: ChessExperimentStore | None = None,
    nn_model_path: Path | None = None,
) -> dict:
    rng = random.Random(seed)
    store = store or ChessExperimentStore()
    nn_model_path = Path(nn_model_path or default_chess_nn_model_path())
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
    for index in range(max(0, int(cross_games or 0))):
        if index % 2 == 0:
            schedule.append((EXPERIMENT_DIFFICULTY, EXPERIMENT_NN_DIFFICULTY))
        else:
            schedule.append((EXPERIMENT_NN_DIFFICULTY, EXPERIMENT_DIFFICULTY))

    summary = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "seed": seed,
        "teacher_depth": teacher_depth,
        "max_plies": max_plies,
        "student_exploration_rate": student_exploration_rate,
        "experiment_db_path": str(store.db_path),
        "experiment_2_nn_model_path": str(nn_model_path),
        "requested_games": {
            "teacher_vs_exp1": int(exp1_teacher_games or 0),
            "teacher_vs_exp2": int(exp2_teacher_games or 0),
            "cross_play": int(cross_games or 0),
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
            "teacher_guidance_exp1": 0,
            "teacher_guidance_exp2": 0,
        },
        "matches": [],
    }

    for white_engine, black_engine in schedule:
        match = play_training_match(
            white_engine=white_engine,
            black_engine=black_engine,
            store=store,
            nn_model_path=nn_model_path,
            rng=rng,
            teacher_depth=teacher_depth,
            student_exploration_rate=student_exploration_rate,
            max_plies=max_plies,
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
        summary["updates"]["teacher_guidance_exp1"] += int(match.teacher_guidance_updates.get(EXPERIMENT_DIFFICULTY) or 0)
        summary["updates"]["teacher_guidance_exp2"] += int(match.teacher_guidance_updates.get(EXPERIMENT_NN_DIFFICULTY) or 0)
        summary["matches"].append(
            {
                "white_engine": match.white_engine,
                "black_engine": match.black_engine,
                "winner_color": match.winner_color,
                "reason": match.reason,
                "move_count": match.move_count,
                "final_fen": match.final_fen,
                "uci_moves": match.uci_moves,
                "student_updates": match.student_updates,
                "teacher_guidance_updates": match.teacher_guidance_updates,
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
        f"- teacher_guidance_exp1: `{summary.get('updates', {}).get('teacher_guidance_exp1', 0)}`",
        f"- teacher_guidance_exp2: `{summary.get('updates', {}).get('teacher_guidance_exp2', 0)}`",
        "",
        "## Recent Matches",
        "",
    ]
    for match in summary.get("matches", [])[-10:]:
        lines.append(
            f"- {match['white_engine']} vs {match['black_engine']}: "
            f"`winner={match['winner_color'] or 'draw'}`, "
            f"`reason={match['reason']}`, "
            f"`plies={match['move_count']}`"
        )
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {
        "json_report": str(json_path),
        "md_report": str(md_path),
    }
