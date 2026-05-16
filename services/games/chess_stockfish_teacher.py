"""External Stockfish teacher adapter for chess training pipelines.

This module is intentionally a thin UCI client. It does not bundle Stockfish,
copy Stockfish assets, or make Stockfish a runtime dependency. Callers pass a
local binary path through CLI args or ``STOCKFISH_PATH``.
"""

from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import threading

import chess

from services.games.chess import to_chess_board


STOCKFISH_DIFFICULTY = "stockfish"
DEFAULT_RUNTIME_DEPTH = 10
DEFAULT_RUNTIME_MOVETIME_MS = 0


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 1024) -> int:
    try:
        value = int(str(os.environ.get(name, "")).strip())
    except (TypeError, ValueError):
        value = int(default)
    return max(int(minimum), min(int(maximum), value))


def _env_float(name: str, default: float, *, minimum: float = 0.1, maximum: float = 30.0) -> float:
    try:
        value = float(str(os.environ.get(name, "")).strip())
    except (TypeError, ValueError):
        value = float(default)
    return max(float(minimum), min(float(maximum), value))


_STOCKFISH_CONCURRENCY = _env_int(
    "HTML_LEARNING_CHESS_STOCKFISH_CONCURRENCY",
    1,
    minimum=1,
    maximum=8,
)
_STOCKFISH_QUEUE_TIMEOUT_SECONDS = _env_float(
    "HTML_LEARNING_CHESS_STOCKFISH_QUEUE_TIMEOUT_SECONDS",
    2.0,
    minimum=0.1,
    maximum=30.0,
)
_STOCKFISH_HASH_MB = _env_int(
    "HTML_LEARNING_CHESS_STOCKFISH_HASH_MB",
    16,
    minimum=1,
    maximum=256,
)
_STOCKFISH_SEMAPHORE = threading.BoundedSemaphore(_STOCKFISH_CONCURRENCY)


def _safe_non_negative_int(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return int(default)
    return parsed if parsed >= 0 else int(default)


def resolve_stockfish_path(path_text: str = "") -> str:
    explicit = str(path_text or "").strip()
    if explicit:
        return str(Path(explicit).expanduser().resolve())
    app_path = str(os.environ.get("HTML_LEARNING_CHESS_STOCKFISH_PATH", "")).strip()
    if app_path:
        return str(Path(app_path).expanduser().resolve())
    env_path = str(os.environ.get("STOCKFISH_PATH", "")).strip()
    if env_path:
        return str(Path(env_path).expanduser().resolve())
    found = shutil.which("stockfish")
    if found:
        return str(Path(found).resolve())
    local_reference = Path.home() / "reference_repos" / "Stockfish" / "src" / "stockfish"
    if local_reference.exists():
        return str(local_reference.resolve())
    return ""


def stockfish_available(path_text: str = "") -> bool:
    path = resolve_stockfish_path(path_text)
    return bool(path and Path(path).exists() and os.access(path, os.X_OK))


def stockfish_reference(stockfish_path: str) -> str:
    path = Path(stockfish_path)
    try:
        repo = path.resolve().parents[1]
        if (repo / ".git").exists():
            proc = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                text=True,
                capture_output=True,
                check=False,
            )
            if proc.returncode == 0:
                return proc.stdout.strip()
    except Exception:
        pass
    return path.name


def analysis_limit(*, depth: int, movetime_ms: int) -> dict[str, int]:
    limit: dict[str, int] = {}
    if int(depth or 0) > 0:
        limit["depth"] = int(depth)
    if int(movetime_ms or 0) > 0:
        limit["movetime"] = int(movetime_ms)
    if not limit:
        limit["depth"] = 8
    return limit


def _send(proc: subprocess.Popen, text: str) -> None:
    if proc.stdin is None:
        raise RuntimeError("stockfish stdin closed")
    proc.stdin.write(text.rstrip("\n") + "\n")
    proc.stdin.flush()


def _read_until(proc: subprocess.Popen, predicate) -> list[str]:
    if proc.stdout is None:
        raise RuntimeError("stockfish stdout closed")
    lines: list[str] = []
    while True:
        line = proc.stdout.readline()
        if line == "":
            raise RuntimeError("stockfish exited before expected UCI response")
        line = line.rstrip("\n")
        lines.append(line)
        if predicate(line):
            return lines


def parse_uci_info(lines: list[str], *, board: chess.Board) -> list[dict]:
    latest: dict[int, dict] = {}
    for line in lines:
        if not line.startswith("info "):
            continue
        tokens = line.split()
        multipv = 1
        if "multipv" in tokens:
            try:
                multipv = int(tokens[tokens.index("multipv") + 1])
            except Exception:
                multipv = 1
        row = dict(latest.get(multipv) or {"rank": multipv})
        for key in ("depth", "seldepth", "nodes"):
            if key in tokens:
                try:
                    row[key] = int(tokens[tokens.index(key) + 1])
                except Exception:
                    pass
        if "score" in tokens:
            idx = tokens.index("score")
            if idx + 2 < len(tokens):
                kind = tokens[idx + 1]
                try:
                    raw_score = int(tokens[idx + 2])
                except Exception:
                    raw_score = 0
                if kind == "mate":
                    row["teacher_eval_cp"] = 100000 - abs(raw_score) if raw_score > 0 else -100000 + abs(raw_score)
                    row["mate"] = raw_score
                else:
                    row["teacher_eval_cp"] = raw_score
        if "pv" in tokens:
            pv = tokens[tokens.index("pv") + 1 :]
            if pv:
                row["move"] = pv[0]
                row["pv"] = pv[:8]
        latest[multipv] = row

    rows: list[dict] = []
    for _rank, row in sorted(latest.items()):
        uci = str(row.get("move") or "").strip().lower()
        if not uci:
            continue
        try:
            move = chess.Move.from_uci(uci)
        except Exception:
            continue
        if move not in board.legal_moves:
            continue
        row["move"] = move.uci()
        row.setdefault("rank", len(rows) + 1)
        row.setdefault("teacher_eval_cp", 0)
        row.setdefault("depth", 0)
        row.setdefault("seldepth", 0)
        row.setdefault("nodes", 0)
        row.setdefault("pv", [move.uci()])
        rows.append(row)
    return rows


class UciStockfish:
    """Minimal blocking UCI client for Stockfish teacher analysis."""

    def __init__(self, path: str) -> None:
        self.path = resolve_stockfish_path(path)
        if not self.path or not Path(self.path).exists():
            raise FileNotFoundError("Stockfish binary not found")
        self.proc = subprocess.Popen(
            [self.path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        _send(self.proc, "uci")
        _read_until(self.proc, lambda line: line.strip() == "uciok")
        self.setoption("Threads", "1")
        self.setoption("Hash", str(_STOCKFISH_HASH_MB))
        self.setoption("UCI_ShowWDL", "true")
        self.setoption("UCI_AnalyseMode", "true")
        self.isready()

    def __enter__(self) -> "UciStockfish":
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.quit()

    def setoption(self, name: str, value: str) -> None:
        _send(self.proc, f"setoption name {name} value {value}")

    def button_option(self, name: str) -> None:
        _send(self.proc, f"setoption name {name}")

    def isready(self) -> None:
        _send(self.proc, "isready")
        _read_until(self.proc, lambda line: line.strip() == "readyok")

    def quit(self) -> None:
        if self.proc.poll() is not None:
            return
        try:
            _send(self.proc, "quit")
            self.proc.wait(timeout=3)
        except Exception:
            self.proc.kill()
            self.proc.wait(timeout=3)

    def analyse(
        self,
        board: chess.Board,
        *,
        limit: dict[str, int],
        multipv: int = 1,
        root_moves: list[chess.Move] | None = None,
    ) -> list[dict]:
        multipv = max(1, int(multipv or 1))
        self.setoption("MultiPV", str(multipv))
        self.button_option("Clear Hash")
        self.isready()
        _send(self.proc, f"position fen {board.fen()}")
        parts = ["go"]
        if int(limit.get("depth") or 0) > 0:
            parts.extend(["depth", str(int(limit["depth"]))])
        if int(limit.get("movetime") or 0) > 0:
            parts.extend(["movetime", str(int(limit["movetime"]))])
        if root_moves:
            # `searchmoves` consumes all remaining tokens, so keep it last.
            parts.append("searchmoves")
            parts.extend(move.uci() for move in root_moves)
        _send(self.proc, " ".join(parts))
        lines = _read_until(self.proc, lambda line: line.startswith("bestmove"))
        return parse_uci_info(lines, board=board)


def stockfish_top_k(
    board: chess.Board,
    *,
    stockfish_path: str,
    k: int = 5,
    depth: int = 8,
    movetime_ms: int = 0,
) -> list[dict]:
    with UciStockfish(stockfish_path) as engine:
        return engine.analyse(
            board,
            limit=analysis_limit(depth=depth, movetime_ms=movetime_ms),
            multipv=max(1, int(k or 1)),
        )


def _move_dict(board: chess.Board, move: chess.Move) -> dict:
    piece = board.piece_at(move.from_square)
    captured = board.piece_at(move.to_square)
    if board.is_en_passant(move):
        capture_square = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
        captured = board.piece_at(capture_square)
    return {
        "from": chess.square_name(move.from_square),
        "to": chess.square_name(move.to_square),
        "piece": piece.symbol() if piece else "",
        "captured": captured.symbol() if captured else None,
        "promotion": chess.piece_symbol(move.promotion) if move.promotion else None,
        "castle": bool(board.is_castling(move)),
        "en_passant": bool(board.is_en_passant(move)),
        "engine": STOCKFISH_DIFFICULTY,
    }


def choose_stockfish_move(
    board_state,
    side: str,
    *,
    stockfish_path: str = "",
    depth: int | None = None,
    movetime_ms: int | None = None,
) -> dict | None:
    path = resolve_stockfish_path(stockfish_path)
    if not path or not Path(path).exists() or not os.access(path, os.X_OK):
        return None
    board = to_chess_board(board_state, side)
    board.turn = chess.WHITE if str(side).strip().lower() == "white" else chess.BLACK
    if board.is_game_over():
        return None
    default_depth = _safe_non_negative_int(depth, DEFAULT_RUNTIME_DEPTH)
    default_movetime = _safe_non_negative_int(movetime_ms, DEFAULT_RUNTIME_MOVETIME_MS)
    runtime_depth = _safe_non_negative_int(
        os.environ.get("HTML_LEARNING_CHESS_STOCKFISH_DEPTH", ""),
        default_depth,
    )
    runtime_movetime = _safe_non_negative_int(
        os.environ.get("HTML_LEARNING_CHESS_STOCKFISH_MOVETIME_MS", ""),
        default_movetime,
    )
    acquired = _STOCKFISH_SEMAPHORE.acquire(timeout=_STOCKFISH_QUEUE_TIMEOUT_SECONDS)
    if not acquired:
        return None
    try:
        rows = stockfish_top_k(
            board,
            stockfish_path=path,
            k=1,
            depth=runtime_depth,
            movetime_ms=runtime_movetime,
        )
    finally:
        _STOCKFISH_SEMAPHORE.release()
    if not rows:
        return None
    try:
        move = chess.Move.from_uci(str(rows[0].get("move") or ""))
    except Exception:
        return None
    if move not in board.legal_moves:
        return None
    return _move_dict(board, move)
