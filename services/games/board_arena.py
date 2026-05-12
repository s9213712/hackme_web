"""Benchmark helpers for non-chess local board-game AIs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
import json
import os
from pathlib import Path
import random
import time

from services.games.board_ai import (
    BOARD_AI_DIFFICULTIES,
    BOARD_AI_GAME_KEYS,
    BOARD_AI_SIZES,
    choose_board_game_ai_move,
    go_apply_move,
    go_legal_moves,
    gomoku_has_five,
    opponent,
    reversi_apply_move,
    reversi_legal_moves,
)
from services.server.runtime import default_runtime_root_path


BOARD_ARENA_ENGINES = ("random", "easy", "normal", "hard")
DEFAULT_BOARD_ARENA_GAMES = ("reversi", "go", "gomoku")
DEFAULT_BOARD_ARENA_MAX_PLIES = {
    "reversi": 128,
    "go": 120,
    "gomoku": 120,
}
BOARD_ARENA_REPORT_BASENAME = "board_ai_benchmark"
_ELO_START = 1500.0
_ELO_K = 24.0


@dataclass(frozen=True)
class BoardSkillCase:
    game_key: str
    case_id: str
    board: tuple[str, ...]
    turn: str
    expected_indices: tuple[int, ...] = ()
    expected_action: str = "move"


def default_board_reports_dir() -> Path:
    runtime_dir = os.environ.get("HACKME_RUNTIME_DIR", "").strip() or str(default_runtime_root_path())
    reports_root = os.environ.get("HTML_LEARNING_REPORTS_DIR", "").strip() or os.path.join(runtime_dir, "reports")
    return Path(reports_root) / "games"


def initial_board(game_key: str) -> tuple[str, ...]:
    game_key = _normalize_game_key(game_key)
    size = BOARD_AI_SIZES[game_key]
    board = [""] * (size * size)
    if game_key == "reversi":
        board[3 * size + 3] = "white"
        board[4 * size + 4] = "white"
        board[3 * size + 4] = "black"
        board[4 * size + 3] = "black"
    return tuple(board)


def legal_moves(game_key: str, board: tuple[str, ...], turn: str) -> list[int]:
    game_key = _normalize_game_key(game_key)
    if game_key == "reversi":
        return reversi_legal_moves(board, turn)
    if game_key == "go":
        return go_legal_moves(board, turn)
    return [index for index, value in enumerate(board) if not value]


def apply_board_move(game_key: str, board: tuple[str, ...], move: int, turn: str) -> tuple[tuple[str, ...] | None, dict]:
    game_key = _normalize_game_key(game_key)
    move = int(move)
    if move < 0 or move >= len(board):
        return None, {"invalid": "move-out-of-range"}
    if game_key == "reversi":
        next_board = reversi_apply_move(board, move, turn)
        return next_board, {"captured": 0}
    if game_key == "go":
        next_board, captured = go_apply_move(board, move, turn)
        return next_board, {"captured": int(captured)}
    if board[move]:
        return None, {"invalid": "occupied"}
    next_board = list(board)
    next_board[move] = turn
    return tuple(next_board), {"captured": 0, "made_five": gomoku_has_five(tuple(next_board), move, turn)}


def play_board_ai_match(
    game_key: str,
    black_engine: str,
    white_engine: str,
    *,
    seed: int = 0,
    max_plies: int | None = None,
    include_history: bool = True,
) -> dict:
    game_key = _normalize_game_key(game_key)
    black_engine = _normalize_engine(black_engine)
    white_engine = _normalize_engine(white_engine)
    max_plies = int(max_plies or DEFAULT_BOARD_ARENA_MAX_PLIES[game_key])
    rng = random.Random(int(seed))
    board = initial_board(game_key)
    turn = "black"
    pass_count = 0
    illegal_moves = []
    history = []
    timings = {
        black_engine: {"moves": 0, "seconds": 0.0},
        white_engine: {"moves": 0, "seconds": 0.0},
    }

    def active_engine() -> str:
        return black_engine if turn == "black" else white_engine

    winner_color = ""
    reason = "max_plies"
    for ply in range(max_plies):
        engine = active_engine()
        started = time.perf_counter()
        decision = _choose_engine_decision(game_key, engine, board, turn, rng)
        elapsed = time.perf_counter() - started
        timings.setdefault(engine, {"moves": 0, "seconds": 0.0})
        timings[engine]["moves"] += 1
        timings[engine]["seconds"] += elapsed

        action = str(decision.get("action") or "").strip().lower()
        move_payload = decision.get("move") if isinstance(decision.get("move"), dict) else {}
        move = move_payload.get("index")
        if action in {"pass", "finish"}:
            pass_count += 1
            if include_history:
                history.append({"ply": ply + 1, "turn": turn, "engine": engine, "action": action})
            if action == "finish" or pass_count >= 2:
                reason = action if action == "finish" else "double-pass"
                break
            turn = opponent(turn)
            continue

        if action != "move" or move is None:
            illegal_moves.append({"ply": ply + 1, "engine": engine, "turn": turn, "reason": "missing-move"})
            winner_color = opponent(turn)
            reason = "illegal-move"
            break
        move = int(move)
        if move not in legal_moves(game_key, board, turn):
            illegal_moves.append({"ply": ply + 1, "engine": engine, "turn": turn, "move": move, "reason": "illegal-move"})
            winner_color = opponent(turn)
            reason = "illegal-move"
            break
        next_board, meta = apply_board_move(game_key, board, move, turn)
        if next_board is None:
            illegal_moves.append({"ply": ply + 1, "engine": engine, "turn": turn, "move": move, "reason": meta.get("invalid") or "apply-failed"})
            winner_color = opponent(turn)
            reason = "illegal-move"
            break
        board = next_board
        pass_count = 0
        if include_history:
            x, y = move % BOARD_AI_SIZES[game_key], move // BOARD_AI_SIZES[game_key]
            history.append({"ply": ply + 1, "turn": turn, "engine": engine, "action": "move", "move": move, "x": x, "y": y})
        if game_key == "gomoku" and meta.get("made_five"):
            winner_color = turn
            reason = "five-in-row"
            break
        if game_key == "reversi" and _is_reversi_terminal(board):
            reason = "reversi-terminal"
            break
        if not any(not cell for cell in board):
            reason = "board-full"
            break
        turn = opponent(turn)

    black_score, white_score = score_board(game_key, board)
    if not winner_color:
        if black_score > white_score:
            winner_color = "black"
        elif white_score > black_score:
            winner_color = "white"
    winner_engine = black_engine if winner_color == "black" else white_engine if winner_color == "white" else ""
    result = "draw" if not winner_color else f"{winner_color}_win"
    plies = len(history) if include_history else sum(stats["moves"] for stats in timings.values())
    return {
        "game_key": game_key,
        "black_engine": black_engine,
        "white_engine": white_engine,
        "winner_color": winner_color,
        "winner_engine": winner_engine,
        "result": result,
        "reason": reason,
        "plies": int(plies),
        "max_plies": max_plies,
        "black_score": int(black_score),
        "white_score": int(white_score),
        "illegal_moves": illegal_moves,
        "engine_timings": _timing_summary(timings),
        "final_board": list(board),
        "moves": history,
    }


def score_board(game_key: str, board: tuple[str, ...]) -> tuple[int, int]:
    game_key = _normalize_game_key(game_key)
    if game_key in {"reversi", "gomoku"}:
        return board.count("black"), board.count("white")
    black = board.count("black")
    white = board.count("white")
    size = BOARD_AI_SIZES["go"]
    for index, value in enumerate(board):
        if value:
            continue
        adjacent = {board[n] for n in _neighbors(index, size) if board[n]}
        if adjacent == {"black"}:
            black += 1
        elif adjacent == {"white"}:
            white += 1
    return black, white


def run_board_skill_suite(engines: list[str] | tuple[str, ...] = BOARD_ARENA_ENGINES) -> dict:
    engines = [_normalize_engine(engine) for engine in engines]
    cases = _skill_cases()
    rows = []
    by_engine = {engine: {"engine": engine, "cases": 0, "passed": 0, "pass_rate": 0.0} for engine in engines}
    by_game = {}
    for case in cases:
        by_game.setdefault(case.game_key, {"game_key": case.game_key, "cases": 0, "passed": 0, "pass_rate": 0.0})
        for engine in engines:
            rng = random.Random(_stable_seed(case.game_key, case.case_id, engine))
            decision = _choose_engine_decision(case.game_key, engine, case.board, case.turn, rng)
            actual_action = str(decision.get("action") or "")
            actual_index = ((decision.get("move") or {}).get("index") if isinstance(decision.get("move"), dict) else None)
            passed = actual_action == case.expected_action and (
                not case.expected_indices or int(actual_index) in set(case.expected_indices)
            )
            row = {
                "game_key": case.game_key,
                "case_id": case.case_id,
                "engine": engine,
                "passed": bool(passed),
                "expected_action": case.expected_action,
                "expected_indices": list(case.expected_indices),
                "actual_action": actual_action,
                "actual_index": actual_index,
            }
            rows.append(row)
            by_engine[engine]["cases"] += 1
            by_game[case.game_key]["cases"] += 1
            if passed:
                by_engine[engine]["passed"] += 1
                by_game[case.game_key]["passed"] += 1
    for bucket in list(by_engine.values()) + list(by_game.values()):
        bucket["pass_rate"] = round(bucket["passed"] / max(1, bucket["cases"]), 4)
    return {
        "cases": len(cases),
        "results": rows,
        "by_engine": sorted(by_engine.values(), key=lambda item: item["engine"]),
        "by_game": sorted(by_game.values(), key=lambda item: item["game_key"]),
    }


def run_board_ai_benchmark(
    *,
    game_keys: list[str] | tuple[str, ...] = DEFAULT_BOARD_ARENA_GAMES,
    engines: list[str] | tuple[str, ...] = BOARD_ARENA_ENGINES,
    rounds: int = 1,
    max_plies: int | None = None,
    seed: int = 20260513,
) -> dict:
    game_keys = [_normalize_game_key(game_key) for game_key in game_keys]
    engines = [_normalize_engine(engine) for engine in engines]
    if len(set(engines)) < 2:
        raise ValueError("at least two engines are required")
    rounds = max(1, int(rounds))
    matches = []
    match_index = 0
    for game_index, game_key in enumerate(game_keys):
        for engine_a, engine_b in combinations(engines, 2):
            for round_index in range(rounds):
                for black_engine, white_engine in ((engine_a, engine_b), (engine_b, engine_a)):
                    match_seed = _stable_seed(seed, game_key, game_index, engine_a, engine_b, round_index, black_engine)
                    matches.append(play_board_ai_match(
                        game_key,
                        black_engine,
                        white_engine,
                        seed=match_seed,
                        max_plies=max_plies,
                        include_history=True,
                    ))
                    match_index += 1
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "seed": int(seed),
        "games": game_keys,
        "engines": engines,
        "rounds": rounds,
        "games_played": len(matches),
        "matches": matches,
        "standings": _standings(matches, engines),
        "elo": _elo_summary(matches, engines),
        "matrix": _head_to_head_matrix(matches, engines),
        "skill_suite": run_board_skill_suite(engines),
    }


def write_board_ai_benchmark_report(report: dict, *, output_dir: str | Path | None = None, basename: str = BOARD_ARENA_REPORT_BASENAME) -> Path:
    output_root = Path(output_dir) if output_dir else default_board_reports_dir()
    output_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = output_root / f"{basename}_{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _choose_engine_decision(game_key: str, engine: str, board: tuple[str, ...], turn: str, rng: random.Random) -> dict:
    if engine == "random":
        moves = legal_moves(game_key, board, turn)
        if moves:
            move = int(rng.choice(moves))
            size = BOARD_AI_SIZES[game_key]
            return {
                "game_key": game_key,
                "turn": turn,
                "difficulty": "random",
                "action": "move",
                "move": {"index": move, "x": move % size, "y": move // size},
                "score": 0,
                "reason": "random-legal",
            }
        action = "finish" if game_key in {"reversi", "gomoku"} else "pass"
        return {"game_key": game_key, "turn": turn, "difficulty": "random", "action": action, "score": 0, "reason": "no-legal-move"}
    return choose_board_game_ai_move(game_key, list(board), turn, engine)


def _skill_cases() -> tuple[BoardSkillCase, ...]:
    reversi = list(initial_board("reversi"))
    go = list(initial_board("go"))
    go_size = BOARD_AI_SIZES["go"]
    go[4 * go_size + 4] = "white"
    go[4 * go_size + 3] = "black"
    go[4 * go_size + 5] = "black"
    go[3 * go_size + 4] = "black"
    gomoku_win = list(initial_board("gomoku"))
    gomoku_size = BOARD_AI_SIZES["gomoku"]
    for x in range(4):
        gomoku_win[7 * gomoku_size + x + 5] = "black"
    gomoku_block = list(initial_board("gomoku"))
    for x in range(4):
        gomoku_block[7 * gomoku_size + x + 5] = "white"
    return (
        BoardSkillCase("reversi", "opening_legal_move", tuple(reversi), "black", tuple(reversi_legal_moves(tuple(reversi), "black"))),
        BoardSkillCase("go", "capture_single_stone", tuple(go), "black", (5 * go_size + 4,)),
        BoardSkillCase("gomoku", "win_open_four", tuple(gomoku_win), "black", (7 * gomoku_size + 4, 7 * gomoku_size + 9)),
        BoardSkillCase("gomoku", "block_open_four", tuple(gomoku_block), "black", (7 * gomoku_size + 4, 7 * gomoku_size + 9)),
    )


def _standings(matches: list[dict], engines: list[str]) -> list[dict]:
    rows = {engine: {
        "engine": engine,
        "games": 0,
        "wins": 0,
        "draws": 0,
        "losses": 0,
        "score": 0.0,
        "score_rate": 0.0,
        "illegal_moves": 0,
        "avg_ms_per_move": 0.0,
        "_seconds": 0.0,
        "_timed_moves": 0,
    } for engine in engines}
    for match in matches:
        black = match["black_engine"]
        white = match["white_engine"]
        winner = match.get("winner_engine") or ""
        for engine in (black, white):
            rows[engine]["games"] += 1
            rows[engine]["illegal_moves"] += sum(1 for item in match.get("illegal_moves", []) if item.get("engine") == engine)
            timing = (match.get("engine_timings") or {}).get(engine) or {}
            rows[engine]["_seconds"] += float(timing.get("seconds") or 0.0)
            rows[engine]["_timed_moves"] += int(timing.get("moves") or 0)
        if not winner:
            rows[black]["draws"] += 1
            rows[white]["draws"] += 1
            rows[black]["score"] += 0.5
            rows[white]["score"] += 0.5
        else:
            loser = white if winner == black else black
            rows[winner]["wins"] += 1
            rows[winner]["score"] += 1.0
            rows[loser]["losses"] += 1
    for row in rows.values():
        row["score"] = round(row["score"], 2)
        row["score_rate"] = round(float(row["score"]) / max(1, row["games"]), 4)
        row["avg_ms_per_move"] = round((row.pop("_seconds") / max(1, row.pop("_timed_moves"))) * 1000.0, 3)
    return sorted(rows.values(), key=lambda item: (-item["score_rate"], -item["score"], item["engine"]))


def _head_to_head_matrix(matches: list[dict], engines: list[str]) -> dict:
    matrix = {a: {b: {"games": 0, "wins": 0, "draws": 0, "losses": 0, "score": 0.0} for b in engines if b != a} for a in engines}
    for match in matches:
        black = match["black_engine"]
        white = match["white_engine"]
        winner = match.get("winner_engine") or ""
        for engine, other_engine in ((black, white), (white, black)):
            cell = matrix[engine][other_engine]
            cell["games"] += 1
            if not winner:
                cell["draws"] += 1
                cell["score"] += 0.5
            elif winner == engine:
                cell["wins"] += 1
                cell["score"] += 1.0
            else:
                cell["losses"] += 1
    for opponents in matrix.values():
        for cell in opponents.values():
            cell["score"] = round(cell["score"], 2)
            cell["score_rate"] = round(cell["score"] / max(1, cell["games"]), 4)
    return matrix


def _elo_summary(matches: list[dict], engines: list[str]) -> list[dict]:
    ratings = {engine: _ELO_START for engine in engines}
    played = {engine: 0 for engine in engines}
    for match in matches:
        black = match["black_engine"]
        white = match["white_engine"]
        played[black] += 1
        played[white] += 1
        winner = match.get("winner_engine") or ""
        if winner == black:
            black_actual, white_actual = 1.0, 0.0
        elif winner == white:
            black_actual, white_actual = 0.0, 1.0
        else:
            black_actual = white_actual = 0.5
        black_expected = _expected_score(ratings[black], ratings[white])
        white_expected = _expected_score(ratings[white], ratings[black])
        ratings[black] += _ELO_K * (black_actual - black_expected)
        ratings[white] += _ELO_K * (white_actual - white_expected)
    rows = [{"engine": engine, "elo": round(rating, 2), "games": played[engine]} for engine, rating in ratings.items()]
    return sorted(rows, key=lambda item: (-item["elo"], item["engine"]))


def _expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def _timing_summary(timings: dict) -> dict:
    summary = {}
    for engine, stats in timings.items():
        moves = int(stats.get("moves") or 0)
        seconds = float(stats.get("seconds") or 0.0)
        summary[engine] = {
            "moves": moves,
            "seconds": round(seconds, 6),
            "avg_ms_per_move": round((seconds / max(1, moves)) * 1000.0, 3),
        }
    return summary


def _is_reversi_terminal(board: tuple[str, ...]) -> bool:
    return not any(not cell for cell in board) or (
        not reversi_legal_moves(board, "black") and not reversi_legal_moves(board, "white")
    )


def _neighbors(index: int, size: int):
    x, y = index % size, index // size
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < size and 0 <= ny < size:
            yield ny * size + nx


def _normalize_game_key(game_key: str) -> str:
    game_key = str(game_key or "").strip().lower()
    if game_key not in BOARD_AI_GAME_KEYS:
        raise ValueError(f"unsupported board game: {game_key}")
    return game_key


def _normalize_engine(engine: str) -> str:
    engine = str(engine or "").strip().lower()
    if engine == "random" or engine in BOARD_AI_DIFFICULTIES:
        return engine
    raise ValueError(f"unsupported board AI engine: {engine}")


def _stable_seed(*parts) -> int:
    payload = "|".join(str(part) for part in parts)
    return sum((index + 1) * ord(char) for index, char in enumerate(payload)) % (2**31 - 1)
