#!/usr/bin/env python3
"""Evaluate hackme_web board-game AI strength with reproducible probes.

The script intentionally does not use external chess/go/othello/gomoku
engines. It combines:

* live server smoke checks for the actual game API surface;
* service-level fixed-position probes with explicit expected moves;
* deterministic AI-vs-random sparring with both colors.

It writes a JSON artifact for later report writing. The goal is not to certify
absolute human rating, but to expose the practical tactical floor and the
largest mismatches between UI difficulty names and actual engine behavior.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import random
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import chess


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes import games as game_routes  # noqa: E402
from services.games import board_ai as board_ai_service  # noqa: E402
from services.games import board_arena  # noqa: E402
from services.games import chess_dl, chess_engine, chess_nnue, chess_pv  # noqa: E402
from services.games.chess import FEN_KEY, game_status, initial_board as chess_initial_board  # noqa: E402
from services.games.chess import legal_moves as chess_legal_moves  # noqa: E402
from services.games.chess import validate_move as chess_validate_move  # noqa: E402


BOARD_DIFFICULTIES = ("easy", "normal", "hard")
CHESS_DIFFICULTIES = (
    "normal",
    "hard",
    "experiment",
    "experiment 3:dl",
    "experiment 4:pv",
    "experiment 5:nnue",
)
CHESS_LABELS = {
    "normal": "普通",
    "hard": "困難",
    "experiment": "實驗",
    "experiment 3:dl": "實驗 3：DL 語義平衡",
    "experiment 4:pv": "實驗 4：Policy/Value + MCTS",
    "experiment 5:nnue": "實驗 5：NNUE + AlphaBeta/PVS",
}
GAME_LABELS = {
    "reversi": "黑白棋",
    "go": "圍棋",
    "gomoku": "五子棋",
    "chess": "西洋棋",
}
BOARD_LABELS = {"easy": "簡單", "normal": "普通", "hard": "困難"}
METRICS = (
    "normal_move",
    "short_tactics",
    "long_strategy",
    "trap_response",
    "trap_setting",
    "opening",
    "avoid_blunder",
    "endgame",
)
METRIC_LABELS = {
    "normal_move": "正常走棋",
    "short_tactics": "短期戰術",
    "long_strategy": "長期策略",
    "trap_response": "陷阱應對",
    "trap_setting": "設置陷阱",
    "opening": "佈局",
    "avoid_blunder": "避免送子",
    "endgame": "終局",
}


@dataclass(frozen=True)
class FixedCase:
    game_key: str
    case_id: str
    turn: str
    board: Any
    categories: tuple[str, ...]
    description: str
    correct_direction: str
    expected_moves: tuple[Any, ...] = ()
    avoid_moves: tuple[Any, ...] = ()
    accepted: Callable[[Any], bool] | None = None
    max_points: float = 1.0


@dataclass
class ScoreBucket:
    available: float = 0.0
    earned: float = 0.0

    def add(self, earned: float, available: float = 1.0) -> None:
        self.earned += float(earned)
        self.available += float(available)

    def score_0_5(self) -> float:
        if self.available <= 0:
            return 0.0
        return round(max(0.0, min(5.0, 5.0 * self.earned / self.available)), 2)


class LiveClient:
    def __init__(self, base_url: str, *, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.context = ssl._create_unverified_context()
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies),
            urllib.request.HTTPSHandler(context=self.context),
        )
        self.csrf_token = ""

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.csrf_token:
            headers["X-CSRF-Token"] = self.csrf_token
        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw or "{}")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {"ok": False, "raw": raw}
            payload["http_status"] = exc.code
            return payload

    def refresh_csrf(self) -> str:
        payload = self.request("GET", "/api/csrf-token")
        self.csrf_token = str(payload.get("csrf_token") or "")
        return self.csrf_token

    def login(self, username: str, password: str) -> dict[str, Any]:
        self.refresh_csrf()
        payload = self.request("POST", "/api/login", {"username": username, "password": password})
        self.refresh_csrf()
        return payload


def board_size(game_key: str) -> int:
    return board_ai_service.BOARD_AI_SIZES[game_key]


def empty_board(game_key: str) -> list[str]:
    return [""] * (board_size(game_key) ** 2)


def index(game_key: str, x: int, y: int) -> int:
    return y * board_size(game_key) + x


def idx_to_xy(game_key: str, idx: int) -> tuple[int, int]:
    size = board_size(game_key)
    return int(idx) % size, int(idx) // size


def move_label(game_key: str, move: Any) -> str:
    if game_key == "chess":
        return str(move)
    if move is None:
        return "-"
    x, y = idx_to_xy(game_key, int(move))
    return f"{int(move)} ({x},{y})"


def state_from_fen(fen: str) -> dict[str, str]:
    board = chess.Board(fen)
    state = {chess.square_name(square): piece.symbol() for square, piece in board.piece_map().items()}
    state[FEN_KEY] = board.fen()
    return state


def state_from_chess_board(board: chess.Board) -> dict[str, str]:
    state = {chess.square_name(square): piece.symbol() for square, piece in board.piece_map().items()}
    state[FEN_KEY] = board.fen()
    return state


def chess_move_uci(move: dict[str, Any] | None) -> str:
    if not move:
        return ""
    return f"{move.get('from')}{move.get('to')}{move.get('promotion') or ''}"


def material_score(board: chess.Board, color: chess.Color) -> int:
    values = {
        chess.PAWN: 100,
        chess.KNIGHT: 320,
        chess.BISHOP: 330,
        chess.ROOK: 500,
        chess.QUEEN: 900,
        chess.KING: 0,
    }
    score = 0
    for piece in board.piece_map().values():
        value = values.get(piece.piece_type, 0)
        score += value if piece.color == color else -value
    return score


def chess_prevents_opponent_mate_in_one(fen: str, side: str, actual: Any) -> bool:
    try:
        board = chess.Board(str(fen))
        board.turn = chess.WHITE if str(side).lower() == "white" else chess.BLACK
        move = chess.Move.from_uci(str(actual or "").strip().lower())
    except Exception:
        return False
    if move not in board.legal_moves:
        return False
    board.push(move)
    if board.is_checkmate():
        return True
    for reply in board.legal_moves:
        board.push(reply)
        allows_mate = board.is_checkmate()
        board.pop()
        if allows_mate:
            return False
    return True


def fixed_cases() -> list[FixedCase]:
    cases: list[FixedCase] = []

    # Reversi.
    b = tuple(board_arena.initial_board("reversi"))
    cases.append(FixedCase(
        "reversi",
        "opening_legal",
        "black",
        b,
        ("normal_move", "opening"),
        "標準初始局面，黑方必須選合法翻子點。",
        "任一合法開局點都可接受。",
        accepted=lambda actual, board=b: int(actual) in set(board_ai_service.reversi_legal_moves(tuple(board), "black")),
    ))
    b = empty_board("reversi")
    b[1] = "white"
    b[2] = "black"
    b = tuple(b)
    cases.append(FixedCase(
        "reversi",
        "take_available_corner",
        "black",
        b,
        ("short_tactics", "trap_response", "avoid_blunder", "endgame"),
        "角落 0 可直接取得，黑方應優先拿角。",
        "下 0 角，取得不可翻轉的角落資源。",
        expected_moves=(0,),
    ))
    b = empty_board("reversi")
    b[18] = "white"
    b[27] = "black"
    b[20] = "white"
    b[21] = "black"
    b = tuple(b)
    cases.append(FixedCase(
        "reversi",
        "avoid_empty_corner_x_square",
        "black",
        b,
        ("trap_response", "avoid_blunder"),
        "左上角空，X 格 9 與其他安全點同時可下。",
        "避免無補償踩 X 格，選 13 或 19 類安全點。",
        avoid_moves=(9,),
    ))
    b = empty_board("reversi")
    b[2] = "white"
    b[3] = "black"
    b[20] = "white"
    b[21] = "black"
    b = tuple(b)
    cases.append(FixedCase(
        "reversi",
        "avoid_empty_corner_c_square",
        "black",
        b,
        ("trap_response", "avoid_blunder", "long_strategy"),
        "左上角空，C 格 1 與安全點 19 同時可下。",
        "除非有清楚補償，應避免 C 格送角風險。",
        avoid_moves=(1,),
    ))

    # Go, 9x9 simplified rules.
    b = tuple(empty_board("go"))
    cases.append(FixedCase(
        "go",
        "opening_near_center",
        "black",
        b,
        ("normal_move", "opening", "long_strategy"),
        "9x9 空盤開局。",
        "中心或近中心點可接受，避免邊角隨機落子。",
        accepted=lambda actual: idx_to_xy("go", int(actual)) in {(4, 4), (3, 3), (5, 5), (3, 4), (4, 3), (4, 5), (5, 4)},
    ))
    b = empty_board("go")
    s = board_size("go")
    b[4 * s + 4] = "white"
    b[4 * s + 3] = "black"
    b[4 * s + 5] = "black"
    b[3 * s + 4] = "black"
    b = tuple(b)
    cases.append(FixedCase(
        "go",
        "capture_single_stone",
        "black",
        b,
        ("short_tactics", "trap_response", "avoid_blunder"),
        "白子在中心只剩一氣。",
        "黑方應下 49 提掉白子。",
        expected_moves=(49,),
    ))
    b = empty_board("go")
    b[index("go", 4, 4)] = "black"
    b[index("go", 3, 4)] = "white"
    b[index("go", 5, 4)] = "white"
    b[index("go", 4, 3)] = "white"
    b = tuple(b)
    cases.append(FixedCase(
        "go",
        "save_own_atari",
        "black",
        b,
        ("short_tactics", "avoid_blunder"),
        "黑中心子只剩最後一氣。",
        "黑方應補 49 救子，或至少不要無視被提。",
        expected_moves=(49,),
    ))

    # Gomoku.
    b = tuple(empty_board("gomoku"))
    cases.append(FixedCase(
        "gomoku",
        "opening_center",
        "black",
        b,
        ("normal_move", "opening"),
        "15x15 空盤第一手。",
        "自由五子棋通常應落天元或近中心；此處要求天元。",
        expected_moves=(index("gomoku", 7, 7),),
    ))
    b = empty_board("gomoku")
    for x in range(5, 9):
        b[index("gomoku", x, 7)] = "black"
    b = tuple(b)
    cases.append(FixedCase(
        "gomoku",
        "win_open_four",
        "black",
        b,
        ("short_tactics", "trap_setting", "endgame"),
        "黑方已有橫向活四。",
        "下 4,7 或 9,7 立即成五。",
        expected_moves=(index("gomoku", 4, 7), index("gomoku", 9, 7)),
    ))
    b = empty_board("gomoku")
    for x in range(5, 9):
        b[index("gomoku", x, 7)] = "white"
    b = tuple(b)
    cases.append(FixedCase(
        "gomoku",
        "block_open_four",
        "black",
        b,
        ("short_tactics", "trap_response", "avoid_blunder"),
        "白方已有橫向活四。",
        "黑方必須擋 4,7 或 9,7。",
        expected_moves=(index("gomoku", 4, 7), index("gomoku", 9, 7)),
    ))
    b = empty_board("gomoku")
    for offset in range(4):
        b[index("gomoku", 5 + offset, 6)] = "black"
        b[index("gomoku", 5 + offset, 8)] = "white"
    b = tuple(b)
    cases.append(FixedCase(
        "gomoku",
        "defense_priority_over_nonwinning_attack",
        "black",
        b,
        ("trap_response", "avoid_blunder"),
        "黑白各有一條活四，黑方輪到時可自己先成五。",
        "有立即勝時應先勝，不需要防守。",
        expected_moves=(index("gomoku", 4, 6), index("gomoku", 9, 6)),
    ))

    # Chess. Expected moves are UCI strings.
    cases.append(FixedCase(
        "chess",
        "opening_principle_start",
        "white",
        chess.STARTING_FEN,
        ("normal_move", "opening", "long_strategy"),
        "標準初始局面白方開局。",
        "接受常見開局首著：e4、d4、c4、Nf3。",
        expected_moves=("e2e4", "d2d4", "c2c4", "g1f3"),
    ))
    cases.append(FixedCase(
        "chess",
        "fools_mate_mate_in_one",
        "black",
        "rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq g3 0 2",
        ("short_tactics", "trap_setting", "endgame"),
        "白方 f3/g4 後，黑方有 Qh4#。",
        "必須下 d8h4 立即將死。",
        expected_moves=("d8h4",),
    ))
    cases.append(FixedCase(
        "chess",
        "capture_hanging_queen",
        "white",
        "k7/8/8/8/8/8/4R2q/4K3 w - - 0 1",
        ("short_tactics", "avoid_blunder"),
        "黑后在 h2 可被白車直接吃掉，局面合法。",
        "白方應走 e2h2 贏后。",
        expected_moves=("e2h2",),
    ))
    cases.append(FixedCase(
        "chess",
        "promotion_to_queen",
        "white",
        "4k3/6P1/8/8/8/8/8/4K3 w - - 0 1",
        ("endgame", "short_tactics"),
        "白兵 g7 可升變。",
        "應走 g7g8q 或等價升后路線。",
        expected_moves=("g7g8q",),
    ))
    fen = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
    cases.append(FixedCase(
        "chess",
        "defend_scholar_mate_threat",
        "black",
        fen,
        ("trap_response", "short_tactics", "avoid_blunder", "opening"),
        "白后 h5、白象 c4 對 f7 形成一手殺威脅。",
        "黑方必須走完後不允許 Qxf7#。",
        accepted=lambda actual, fen=fen: chess_prevents_opponent_mate_in_one(fen, "black", actual),
    ))
    fen = "6k1/5ppp/3b4/8/7q/8/5PPP/6K1 w - - 0 1"
    cases.append(FixedCase(
        "chess",
        "avoid_self_opened_mate_line",
        "white",
        fen,
        ("trap_response", "avoid_blunder", "short_tactics"),
        "白方若隨手推 f 兵會打開 Qe1# 對角線。",
        "白方走完後不能讓黑方有一手將死。",
        accepted=lambda actual, fen=fen: chess_prevents_opponent_mate_in_one(fen, "white", actual),
    ))
    return cases


def load_external_replay_cases(paths: list[str], *, limit: int) -> list[FixedCase]:
    """Build low-weight chess probes from PGN-import replay JSONL rows.

    Exact agreement with a human PGN move is weaker evidence than a tactical
    fixed puzzle, so these cases deliberately carry a fractional max_points.
    They are still useful for opening plausibility and broad style sanity.
    """
    cases: list[FixedCase] = []
    remaining = max(0, int(limit or 0))
    if remaining <= 0:
        return cases
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if not path.exists():
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if remaining <= 0:
                return cases
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue
            history = record.get("move_history") or []
            if not isinstance(history, list):
                continue
            labels = record.get("pgn_labels") or {}
            replay_id = str(record.get("replay_id") or f"{path.name}:{line_no}")[:12]
            for move_index, entry in enumerate(history, start=1):
                if remaining <= 0:
                    return cases
                if not isinstance(entry, dict):
                    continue
                fen = str(entry.get("fen_before") or "")
                uci = str(entry.get("uci") or "")
                side = str(entry.get("by") or "").strip().lower()
                if not fen or not uci or side not in {"white", "black"}:
                    continue
                phase_categories = ("opening", "long_strategy") if move_index <= 12 else ("long_strategy",)
                tactical_categories: list[str] = []
                if entry.get("captured") or entry.get("check_after") or entry.get("promotion"):
                    tactical_categories.append("short_tactics")
                if entry.get("promotion"):
                    tactical_categories.append("endgame")
                categories = tuple(dict.fromkeys(("normal_move", *phase_categories, *tactical_categories)))
                event = str(labels.get("event") or "PGN template")
                cases.append(FixedCase(
                    "chess",
                    f"pgn_template_{replay_id}_{move_index:03d}",
                    side,
                    fen,
                    categories,
                    f"PGN 範本第 {move_index} 手：{event}。",
                    "低權重一致性探針：若 AI 下同一 PGN 著法則加分；不同著不直接等同錯棋。",
                    expected_moves=(uci,),
                    max_points=0.35,
                ))
                remaining -= 1
    return cases


def choose_fixed_move(case: FixedCase, difficulty: str) -> tuple[Any, dict[str, Any], bool, str]:
    if case.game_key == "chess":
        state = state_from_fen(str(case.board))
        raw = game_routes.choose_computer_move(state, case.turn, difficulty)
        uci = chess_move_uci(raw)
        valid = True
        validation_error = ""
        try:
            chess_validate_move(state, case.turn, str(raw.get("from") or ""), str(raw.get("to") or ""), raw.get("promotion"))
        except Exception as exc:
            valid = False
            validation_error = f"{type(exc).__name__}: {exc}"
        raw = dict(raw or {})
        raw["uci"] = uci
        raw["valid_by_route_validator"] = valid
        if validation_error:
            raw["validation_error"] = validation_error
        return uci, raw, valid, validation_error

    raw = board_ai_service.choose_board_game_ai_move(case.game_key, list(case.board), case.turn, difficulty)
    move = None
    if isinstance(raw.get("move"), dict):
        move = raw["move"].get("index")
    return move, raw, True, ""


def case_passed(case: FixedCase, actual: Any, valid: bool) -> bool:
    if not valid:
        return False
    if case.accepted is not None:
        try:
            return bool(case.accepted(actual))
        except Exception:
            return False
    if case.expected_moves:
        return actual in set(case.expected_moves)
    if case.avoid_moves:
        return actual not in set(case.avoid_moves)
    return True


def run_fixed_suite(extra_cases: list[FixedCase] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in [*fixed_cases(), *(extra_cases or [])]:
        difficulties = CHESS_DIFFICULTIES if case.game_key == "chess" else BOARD_DIFFICULTIES
        for difficulty in difficulties:
            started = time.perf_counter()
            actual, raw, valid, validation_error = choose_fixed_move(case, difficulty)
            elapsed = time.perf_counter() - started
            passed = case_passed(case, actual, valid)
            rows.append({
                "game_key": case.game_key,
                "game_label": GAME_LABELS[case.game_key],
                "difficulty": difficulty,
                "difficulty_label": CHESS_LABELS.get(difficulty) or BOARD_LABELS.get(difficulty) or difficulty,
                "case_id": case.case_id,
                "categories": list(case.categories),
                "description": case.description,
                "correct_direction": case.correct_direction,
                "expected_moves": list(case.expected_moves),
                "avoid_moves": list(case.avoid_moves),
                "max_points": float(case.max_points),
                "actual_move": actual,
                "actual_move_label": move_label(case.game_key, actual),
                "raw_decision": raw,
                "passed": bool(passed),
                "valid": bool(valid),
                "validation_error": validation_error,
                "elapsed_ms": round(elapsed * 1000.0, 3),
            })
    return rows


def run_live_api_smoke(base_url: str, username: str, password: str) -> dict[str, Any]:
    client = LiveClient(base_url)
    out: dict[str, Any] = {"base_url": base_url, "ok": False, "steps": []}
    try:
        version = client.request("GET", "/api/version")
        out["steps"].append({"name": "version", "payload": version})
        login = client.login(username, password)
        out["steps"].append({"name": "login", "payload": login})
        catalog = client.request("GET", "/api/games/catalog")
        out["steps"].append({"name": "catalog", "payload": {
            "ok": catalog.get("ok"),
            "games": [
                {
                    "key": item.get("key"),
                    "supports_computer": item.get("supports_computer"),
                    "computer_difficulties": item.get("computer_difficulties", []),
                }
                for item in catalog.get("games", [])
            ],
        }})
        board_smoke = []
        for game_key in ("reversi", "go", "gomoku"):
            board = list(board_arena.initial_board(game_key))
            if game_key == "go":
                board = empty_board("go")
            for difficulty in BOARD_DIFFICULTIES:
                started = time.perf_counter()
                client.refresh_csrf()
                decision = client.request("POST", f"/api/games/{game_key}/ai-move", {
                    "board": board,
                    "turn": "black",
                    "difficulty": difficulty,
                })
                board_smoke.append({
                    "game_key": game_key,
                    "difficulty": difficulty,
                    "ok": bool(decision.get("ok")),
                    "action": decision.get("action"),
                    "move": (decision.get("move") or {}).get("index") if isinstance(decision.get("move"), dict) else None,
                    "reason": decision.get("reason"),
                    "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
                    "http_status": decision.get("http_status", 200),
                    "msg": decision.get("msg", ""),
                })
        out["steps"].append({"name": "board_ai_smoke", "payload": board_smoke})
        chess_smoke = []
        for difficulty in CHESS_DIFFICULTIES:
            for side in ("white", "black"):
                client.refresh_csrf()
                created = client.request("POST", "/api/games/chess/practice", {"side": side, "difficulty": difficulty})
                chess_smoke.append({
                    "difficulty": difficulty,
                    "human_side": side,
                    "ok": bool(created.get("ok")),
                    "match_id": created.get("match_id"),
                    "http_status": created.get("http_status", 200),
                    "msg": created.get("msg", ""),
                })
        out["steps"].append({"name": "chess_practice_smoke", "payload": chess_smoke})
        out["ok"] = all(
            bool(step.get("payload", {}).get("ok", True))
            for step in out["steps"]
            if isinstance(step.get("payload"), dict)
        ) and all(row.get("ok") for row in board_smoke) and all(row.get("ok") for row in chess_smoke)
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def run_board_sparring(
    games_per_side: int,
    seed: int,
    max_plies: dict[str, int],
    checkpoint: Callable[[list[dict[str, Any]], str], None] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for game_key in ("reversi", "go", "gomoku"):
        for difficulty in BOARD_DIFFICULTIES:
            for ai_color in ("black", "white"):
                for game_no in range(1, games_per_side + 1):
                    progress(
                        "board sparring start "
                        f"game={game_key} difficulty={difficulty} ai_color={ai_color} "
                        f"trial={game_no}/{games_per_side} max_plies={max_plies[game_key]}"
                    )
                    match_seed = stable_seed(seed, "board", game_key, difficulty, ai_color, game_no)
                    black = difficulty if ai_color == "black" else "random"
                    white = difficulty if ai_color == "white" else "random"
                    started = time.perf_counter()
                    match = board_arena.play_board_ai_match(
                        game_key,
                        black,
                        white,
                        seed=match_seed,
                        max_plies=max_plies[game_key],
                        include_history=True,
                    )
                    elapsed = time.perf_counter() - started
                    ai_won = match.get("winner_engine") == difficulty
                    draw = not match.get("winner_engine")
                    rows.append({
                        "game_key": game_key,
                        "game_label": GAME_LABELS[game_key],
                        "difficulty": difficulty,
                        "difficulty_label": BOARD_LABELS[difficulty],
                        "trial": game_no,
                        "ai_color": ai_color,
                        "opponent": "random",
                        "result": "draw" if draw else ("ai_win" if ai_won else "ai_loss"),
                        "reason": match.get("reason"),
                        "plies": match.get("plies"),
                        "black_score": match.get("black_score"),
                        "white_score": match.get("white_score"),
                        "winner_engine": match.get("winner_engine"),
                        "illegal_moves": match.get("illegal_moves", []),
                        "elapsed_ms": round(elapsed * 1000.0, 3),
                    })
                    progress(
                        "board sparring done "
                        f"game={game_key} difficulty={difficulty} ai_color={ai_color} "
                        f"trial={game_no}/{games_per_side} result={rows[-1]['result']} "
                        f"reason={rows[-1]['reason']} plies={rows[-1]['plies']} "
                        f"elapsed_ms={rows[-1]['elapsed_ms']}"
                    )
                    if checkpoint:
                        checkpoint(rows, f"board:{game_key}:{difficulty}:{ai_color}:{game_no}")
    return rows


def choose_random_chess_move(board: chess.Board, rng: random.Random) -> chess.Move | None:
    moves = list(board.legal_moves)
    if not moves:
        return None
    captures = [move for move in moves if board.is_capture(move)]
    checks = [move for move in moves if board.gives_check(move)]
    pool = checks or captures or moves
    return rng.choice(pool)


def _history_for_route(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in history:
        uci = str(entry.get("uci") or "").strip().lower()
        if len(uci) < 4:
            continue
        rows.append({
            "from": uci[:2],
            "to": uci[2:4],
            "promotion": uci[4:] or None,
        })
    return rows


def ai_chess_move(board: chess.Board, difficulty: str, move_history: list[dict[str, Any]] | None = None) -> tuple[chess.Move | None, dict[str, Any]]:
    side = "white" if board.turn == chess.WHITE else "black"
    random.seed(stable_seed("chess-ai-global", board.fen(), difficulty))
    raw = game_routes.choose_computer_move(
        state_from_chess_board(board),
        side,
        difficulty,
        move_history=_history_for_route(move_history or []),
    )
    uci = chess_move_uci(raw)
    info = dict(raw or {})
    info["uci"] = uci
    try:
        move = chess.Move.from_uci(uci)
    except Exception as exc:
        info["invalid"] = f"bad-uci:{type(exc).__name__}: {exc}"
        return None, info
    if move not in board.legal_moves:
        info["invalid"] = "not-in-python-chess-legal-moves"
        return None, info
    try:
        chess_validate_move(state_from_chess_board(board), side, str(raw.get("from") or ""), str(raw.get("to") or ""), raw.get("promotion"))
    except Exception as exc:
        info["invalid"] = f"route-validator:{type(exc).__name__}: {exc}"
        return None, info
    return move, info


def play_chess_ai_vs_random(difficulty: str, ai_color_name: str, seed: int, max_plies: int) -> dict[str, Any]:
    rng = random.Random(seed)
    ai_color = chess.WHITE if ai_color_name == "white" else chess.BLACK
    board = chess.Board()
    history: list[dict[str, Any]] = []
    invalid_moves: list[dict[str, Any]] = []
    started = time.perf_counter()
    for ply in range(1, max_plies + 1):
        if board.is_game_over(claim_draw=True):
            break
        if board.turn == ai_color:
            before_fen = board.fen()
            move, info = ai_chess_move(board, difficulty, history)
            if move is None:
                invalid_moves.append({"ply": ply, "fen": before_fen, "decision": info})
                break
            actor = "ai"
            decision = info
        else:
            move = choose_random_chess_move(board, rng)
            if move is None:
                break
            actor = "random"
            decision = {"uci": move.uci(), "reason": "random-biased-check-capture"}
        board.push(move)
        history.append({"ply": ply, "actor": actor, "uci": move.uci(), "fen_after": board.fen(), "decision": decision})

    outcome = board.outcome(claim_draw=True)
    result = "draw"
    winner = None
    reason = "max_plies"
    if invalid_moves:
        result = "ai_loss"
        winner = "random"
        reason = "invalid_ai_move"
    elif outcome:
        reason = str(outcome.termination.name).lower()
        if outcome.winner is None:
            result = "draw"
        elif outcome.winner == ai_color:
            result = "ai_win"
            winner = "ai"
        else:
            result = "ai_loss"
            winner = "random"
    else:
        material = material_score(board, ai_color)
        if material > 150:
            result = "ai_win"
            winner = "ai"
        elif material < -150:
            result = "ai_loss"
            winner = "random"
        else:
            result = "draw"
        reason = "material_at_ply_cap"
    return {
        "game_key": "chess",
        "game_label": GAME_LABELS["chess"],
        "difficulty": difficulty,
        "difficulty_label": CHESS_LABELS[difficulty],
        "ai_color": ai_color_name,
        "opponent": "random-check-capture-biased",
        "result": result,
        "winner": winner,
        "reason": reason,
        "plies": len(history),
        "final_fen": board.fen(),
        "ai_material_cp": material_score(board, ai_color),
        "invalid_moves": invalid_moves,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "moves": history,
    }


def run_chess_sparring(
    games_per_side: int,
    seed: int,
    max_plies: int,
    checkpoint: Callable[[list[dict[str, Any]], str], None] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for difficulty in CHESS_DIFFICULTIES:
        for ai_color in ("white", "black"):
            for game_no in range(1, games_per_side + 1):
                progress(
                    "chess sparring start "
                    f"difficulty={difficulty} ai_color={ai_color} "
                    f"trial={game_no}/{games_per_side} max_plies={max_plies}"
                )
                match_seed = stable_seed(seed, "chess", difficulty, ai_color, game_no)
                row = play_chess_ai_vs_random(difficulty, ai_color, match_seed, max_plies)
                row["trial"] = game_no
                rows.append(row)
                progress(
                    "chess sparring done "
                    f"difficulty={difficulty} ai_color={ai_color} "
                    f"trial={game_no}/{games_per_side} result={row['result']} "
                    f"reason={row['reason']} plies={row['plies']} elapsed_ms={row['elapsed_ms']}"
                )
                if checkpoint:
                    checkpoint(rows, f"chess:{difficulty}:{ai_color}:{game_no}")
    return rows


def aggregate_sparring(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = f"{row['game_key']}::{row['difficulty']}"
        bucket = summary.setdefault(key, {
            "game_key": row["game_key"],
            "game_label": row["game_label"],
            "difficulty": row["difficulty"],
            "difficulty_label": row["difficulty_label"],
            "games": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "score": 0.0,
            "illegal_or_invalid": 0,
            "avg_plies": 0.0,
            "_plies_total": 0,
        })
        bucket["games"] += 1
        result = row.get("result")
        if result == "ai_win":
            bucket["wins"] += 1
            bucket["score"] += 1.0
        elif result == "draw":
            bucket["draws"] += 1
            bucket["score"] += 0.5
        else:
            bucket["losses"] += 1
        bucket["_plies_total"] += int(row.get("plies") or 0)
        if row["game_key"] == "chess":
            bucket["illegal_or_invalid"] += len(row.get("invalid_moves") or [])
        else:
            bucket["illegal_or_invalid"] += len(row.get("illegal_moves") or [])
    for bucket in summary.values():
        games = max(1, int(bucket["games"]))
        bucket["score_rate"] = round(float(bucket["score"]) / games, 4)
        bucket["avg_plies"] = round(float(bucket.pop("_plies_total")) / games, 2)
    return summary


def aggregate_fixed(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = f"{row['game_key']}::{row['difficulty']}"
        bucket = summary.setdefault(key, {
            "game_key": row["game_key"],
            "game_label": row["game_label"],
            "difficulty": row["difficulty"],
            "difficulty_label": row["difficulty_label"],
            "cases": 0,
            "passed": 0,
            "valid_failures": 0,
            "by_metric": {metric: {"cases": 0, "passed": 0} for metric in METRICS},
        })
        weight = max(0.0, float(row.get("max_points") or 1.0))
        bucket["cases"] += weight
        if row.get("passed"):
            bucket["passed"] += weight
        if not row.get("valid", True):
            bucket["valid_failures"] += 1
        for metric in row.get("categories") or []:
            cell = bucket["by_metric"].setdefault(metric, {"cases": 0, "passed": 0})
            cell["cases"] += weight
            if row.get("passed"):
                cell["passed"] += weight
    for bucket in summary.values():
        bucket["pass_rate"] = round(bucket["passed"] / max(1, bucket["cases"]), 4)
        for cell in bucket["by_metric"].values():
            cell["pass_rate"] = round(cell["passed"] / max(1, cell["cases"]), 4) if cell["cases"] else None
    return summary


def score_rows(fixed_summary: dict[str, dict[str, Any]], sparring_summary: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    keys = sorted(set(fixed_summary) | set(sparring_summary))
    for key in keys:
        fixed = fixed_summary.get(key) or {}
        sparring = sparring_summary.get(key) or {}
        game_key = fixed.get("game_key") or sparring.get("game_key")
        difficulty = fixed.get("difficulty") or sparring.get("difficulty")
        buckets = {metric: ScoreBucket() for metric in METRICS}
        by_metric = fixed.get("by_metric") or {}
        for metric in METRICS:
            cell = by_metric.get(metric) or {}
            if cell.get("cases"):
                buckets[metric].add(cell.get("passed", 0), cell.get("cases", 0))
        score_rate = float(sparring.get("score_rate") or 0.0)
        illegal = int(sparring.get("illegal_or_invalid") or 0) + int(fixed.get("valid_failures") or 0)
        if sparring:
            buckets["normal_move"].add(1.0 if illegal == 0 else 0.0)
            buckets["long_strategy"].add(score_rate)
            buckets["avoid_blunder"].add(1.0 if illegal == 0 else 0.0)
            buckets["endgame"].add(0.5 + min(0.5, score_rate / 2.0))
        metric_scores = {metric: buckets[metric].score_0_5() for metric in METRICS}
        total = round(sum(metric_scores.values()), 2)
        rows.append({
            "game_key": game_key,
            "game_label": GAME_LABELS.get(game_key, game_key),
            "difficulty": difficulty,
            "difficulty_label": CHESS_LABELS.get(str(difficulty)) or BOARD_LABELS.get(str(difficulty)) or difficulty,
            "scores": metric_scores,
            "total_score": total,
            "fixed_cases": fixed.get("cases", 0),
            "fixed_passed": fixed.get("passed", 0),
            "fixed_pass_rate": fixed.get("pass_rate", 0.0),
            "sparring_games": sparring.get("games", 0),
            "sparring_score_rate": sparring.get("score_rate", 0.0),
            "sparring_record": {
                "wins": sparring.get("wins", 0),
                "draws": sparring.get("draws", 0),
                "losses": sparring.get("losses", 0),
            },
            "illegal_or_invalid": illegal,
            "approx_strength": approximate_strength(game_key, difficulty, total, fixed.get("pass_rate", 0.0), score_rate),
            "training_use": training_use(game_key, difficulty, total),
            "confidence": confidence_label(int(fixed.get("cases", 0)), int(sparring.get("games", 0))),
            "main_strengths": main_strengths(game_key, difficulty, metric_scores, fixed.get("pass_rate", 0.0), score_rate),
            "main_weaknesses": main_weaknesses(game_key, difficulty, metric_scores, fixed.get("pass_rate", 0.0), illegal),
        })
    return rows


def approximate_strength(game_key: str, difficulty: str, total: float, fixed_pass: float, score_rate: float) -> str:
    if game_key == "reversi":
        if total >= 32 and fixed_pass >= 0.8:
            return "中級業餘；未達強業餘/引擎級"
        if total >= 24:
            return "初級到中級"
        return "新手到初級"
    if game_key == "go":
        if total >= 30:
            return "約 15-10 級；非段位"
        if total >= 22:
            return "約 25-15 級"
        return "30-20 級入門"
    if game_key == "gomoku":
        if total >= 34:
            return "中級級位；接近 5-1 級但缺 VCF/VCT"
        if total >= 26:
            return "初級到中級"
        return "入門到初級"
    if game_key == "chess":
        if difficulty == "experiment 5:nnue" and total >= 39.5 and fixed_pass >= 1.0 and score_rate >= 1.0:
            return "約 Elo 1500-1800；非高階引擎"
        if difficulty == "experiment 5:nnue" and total >= 30:
            return "約 Elo 1200-1500"
        if total >= 32:
            return "約 Elo 1200-1500"
        if total >= 25:
            return "約 Elo 800-1200"
        if total >= 18:
            return "約 Elo 600-1000"
        return "低於 Elo 800 或不穩定"
    return "未換算"


def training_use(game_key: str, difficulty: str, total: float) -> str:
    if total >= 34:
        return "適合初中級實戰與基本複盤；不適合作為高階引擎替代"
    if total >= 26:
        return "適合新手到初級練習基本規則與一手戰術"
    if total >= 18:
        return "只適合入門熟悉規則，需搭配固定題訓練"
    return "不建議作為棋力訓練對手，只能做 UI/規則 smoke"


def confidence_label(fixed_cases_count: int, sparring_games_count: int) -> str:
    if fixed_cases_count >= 4 and sparring_games_count >= 6:
        return "中"
    if fixed_cases_count >= 2 and sparring_games_count >= 4:
        return "中低"
    return "低"


def main_strengths(game_key: str, difficulty: str, scores: dict[str, float], fixed_pass: float, score_rate: float) -> list[str]:
    strengths = []
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    for metric, value in ordered[:3]:
        if value >= 3.5:
            strengths.append(f"{METRIC_LABELS[metric]} {value}/5")
    if score_rate >= 0.75:
        strengths.append("對隨機基線勝率高")
    if fixed_pass >= 0.75:
        strengths.append("固定題通過率高")
    return strengths[:3] or ["能產生合法走法"]


def main_weaknesses(game_key: str, difficulty: str, scores: dict[str, float], fixed_pass: float, illegal: int) -> list[str]:
    weaknesses = []
    if illegal:
        weaknesses.append(f"出現 {illegal} 次非法/無法驗證走法")
    ordered = sorted(scores.items(), key=lambda item: (item[1], item[0]))
    for metric, value in ordered[:3]:
        if value < 3.0:
            weaknesses.append(f"{METRIC_LABELS[metric]} {value}/5")
    if fixed_pass < 0.6:
        weaknesses.append("固定題通過率偏低")
    return weaknesses[:3] or ["未見重大固定題失誤，但樣本仍有限"]


def tech_details() -> dict[str, Any]:
    return {
        "board_ai": {
            "reversi": {
                "implementation": "hand-written Reversi legal move + alpha-beta search",
                "depth_by_difficulty": {"easy": 1, "normal": 2, "hard": 4},
                "eval_terms": ["disc_diff", "mobility", "corners", "edges", "x_square_penalty"],
            },
            "go": {
                "implementation": "9x9 simplified go rules, no ko tracking, heuristic + shallow random rollouts",
                "easy": "capture/liberty/center heuristic",
                "normal": {"candidate_limit": 14, "rollouts": 2, "rollout_depth": 10},
                "hard": {"candidate_limit": 22, "rollouts": 4, "rollout_depth": 16},
                "scoring": "simple stone + surrounded-empty area estimate, no komi",
            },
            "gomoku": {
                "implementation": "candidate-neighborhood pattern evaluator + alpha-beta",
                "depth_by_difficulty": {"easy": 1, "normal": 1, "hard": 2},
                "candidate_radius": {"easy": 1, "normal": 2, "hard": 2},
                "special_rules": ["immediate win", "block opponent five"],
            },
        },
        "chess": {
            "normal": "static opening book first, then material/check heuristic",
            "hard": "static opening book first, then one-ply opponent reply penalty",
            "experiment": {
                "implementation": "alpha-beta search with SQLite learning bias",
                "fast_profile": chess_engine._SEARCH_PROFILES.get("fast"),
            },
            "experiment 3:dl": {
                "implementation": "JSON neural/policy style evaluator plus search fallback",
                "difficulty": chess_dl.EXPERIMENT_DL_DIFFICULTY,
                "profiles": getattr(chess_dl, "_SEARCH_PROFILES", {}),
            },
            "experiment 4:pv": {
                "implementation": "policy/value model, MCTS option, guarded overlay when enabled",
                "difficulty": chess_pv.EXPERIMENT_PV_DIFFICULTY,
                "profiles": getattr(chess_pv, "_SEARCH_PROFILES", {}),
                "mcts_simulations": getattr(chess_pv, "_MCTS_SIMULATIONS", {}),
            },
            "experiment 5:nnue": {
                "implementation": "NNUE-like sparse evaluator + alpha-beta/PVS style search",
                "difficulty": chess_nnue.EXPERIMENT_NNUE_DIFFICULTY,
                "profiles": getattr(chess_nnue, "_SEARCH_PROFILES", {}),
            },
            "opening_book": "route layer consults chess_opening_book for every non-easy difficulty; UI does not expose chess easy",
        },
    }


def stable_seed(*parts: Any) -> int:
    payload = "|".join(str(part) for part in parts)
    value = 0
    for idx, char in enumerate(payload):
        value = (value + (idx + 1) * ord(char)) % (2**31 - 1)
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate hackme_web game AI difficulty strength.")
    parser.add_argument("--base-url", default="", help="Live test server base URL, e.g. https://127.0.0.1:50974.")
    parser.add_argument("--username", default="test")
    parser.add_argument("--password", default="TestGameQa123!")
    parser.add_argument("--seed", type=int, default=20260513)
    parser.add_argument("--games-per-side", type=int, default=3)
    parser.add_argument("--reversi-max-plies", type=int, default=64)
    parser.add_argument("--go-max-plies", type=int, default=24)
    parser.add_argument("--gomoku-max-plies", type=int, default=80)
    parser.add_argument("--chess-max-plies", type=int, default=80)
    parser.add_argument("--output", default="", help="JSON artifact path. Default: docs/games/YYYY-MM-DD_game_ai_strength_eval.json.")
    parser.add_argument("--skip-live", action="store_true", help="Skip live API smoke checks.")
    parser.add_argument("--external-replay-jsonl", action="append", default=[], help="Replay JSONL from chess_pgn_to_replay.py to use as low-weight PGN template probes.")
    parser.add_argument("--external-case-limit", type=int, default=24)
    return parser.parse_args()


def build_artifact(
    *,
    args: argparse.Namespace,
    generated_at: str,
    external_cases: list[FixedCase],
    fixed: list[dict[str, Any]],
    sparring: list[dict[str, Any]],
    live: dict[str, Any] | None,
    stage: str,
    complete: bool,
) -> dict[str, Any]:
    fixed_summary = aggregate_fixed(fixed) if fixed else {}
    sparring_summary = aggregate_sparring(sparring) if sparring else {}
    scores = score_rows(fixed_summary, sparring_summary) if (fixed_summary or sparring_summary) else []
    return {
        "generated_at": generated_at,
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "seed": int(args.seed),
        "stage": stage,
        "complete": bool(complete),
        "method": {
            "games_per_side_vs_random": max(1, int(args.games_per_side)),
            "no_external_engines": True,
            "self_play_caps": {
                "reversi": int(args.reversi_max_plies),
                "go": int(args.go_max_plies),
                "gomoku": int(args.gomoku_max_plies),
                "chess": int(args.chess_max_plies),
            },
            "live_base_url": args.base_url,
            "external_replay_jsonl": list(args.external_replay_jsonl),
            "external_case_limit": int(args.external_case_limit),
            "external_cases_loaded": len(external_cases),
        },
        "technical_details": tech_details(),
        "live_api": live,
        "fixed_results": fixed,
        "sparring_results": sparring,
        "fixed_summary": fixed_summary,
        "sparring_summary": sparring_summary,
        "score_rows": scores,
    }


def write_artifact(path: Path, artifact: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    out_path = Path(args.output) if args.output else ROOT / "docs" / "games" / "2026-05-13_game_ai_strength_eval.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    random.seed(int(args.seed))

    external_cases = load_external_replay_cases(args.external_replay_jsonl, limit=int(args.external_case_limit))
    progress(f"fixed position suite external_cases={len(external_cases)}")
    fixed = run_fixed_suite(extra_cases=external_cases)
    board_sparring: list[dict[str, Any]] = []
    chess_sparring: list[dict[str, Any]] = []
    live = None

    def checkpoint(current_rows: list[dict[str, Any]], stage: str) -> None:
        nonlocal board_sparring, chess_sparring, live
        if stage.startswith("board:"):
            board_sparring = list(current_rows)
        elif stage.startswith("chess:"):
            chess_sparring = list(current_rows)
        artifact = build_artifact(
            args=args,
            generated_at=generated_at,
            external_cases=external_cases,
            fixed=fixed,
            sparring=board_sparring + chess_sparring,
            live=live,
            stage=stage,
            complete=False,
        )
        write_artifact(out_path, artifact)
        progress(f"checkpoint wrote {out_path} stage={stage}")

    checkpoint([], "fixed-suite-complete")
    progress("board sparring suite")
    board_sparring = run_board_sparring(
        max(1, int(args.games_per_side)),
        int(args.seed),
        {
            "reversi": max(1, int(args.reversi_max_plies)),
            "go": max(1, int(args.go_max_plies)),
            "gomoku": max(1, int(args.gomoku_max_plies)),
        },
        checkpoint=checkpoint,
    )
    progress("chess sparring suite")
    chess_sparring = run_chess_sparring(
        max(1, int(args.games_per_side)),
        int(args.seed),
        max(1, int(args.chess_max_plies)),
        checkpoint=checkpoint,
    )
    sparring = board_sparring + chess_sparring
    if args.base_url and not args.skip_live:
        progress("live API smoke")
        live = run_live_api_smoke(args.base_url, args.username, args.password)

    artifact = build_artifact(
        args=args,
        generated_at=generated_at,
        external_cases=external_cases,
        fixed=fixed,
        sparring=sparring,
        live=live,
        stage="complete",
        complete=True,
    )
    write_artifact(out_path, artifact)
    progress(f"wrote {out_path}")
    print(out_path)
    return 0


def progress(message: str) -> None:
    sys.stderr.write(f"[game-ai-strength-eval] {message}\n")
    sys.stderr.flush()


if __name__ == "__main__":
    raise SystemExit(main())
