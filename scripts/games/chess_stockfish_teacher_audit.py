#!/usr/bin/env python3
"""Audit chess replay positions with Stockfish and emit teacher rows.

The script intentionally treats Stockfish as an external dependency. It never
bundles or copies the Stockfish binary/NNUE file; callers must pass
``--stockfish-path`` or set ``STOCKFISH_PATH``.

Inputs accepted:

* game-level replay rows from ``chess_pgn_to_replay.py`` with ``move_history``;
* Codex play-eval rows with ``moves``;
* per-position rows with ``fen`` + ``move_uci``.

Outputs:

* Stockfish top-1/top-K teacher rows for exp3/exp4/exp5 training;
* clean played-move rows for conservative replay filtering;
* review/rejected/detail ledgers plus a summary JSON.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Iterable

import chess


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games import chess_stockfish_teacher as stockfish_teacher  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Use Stockfish MultiPV as a chess replay teacher/auditor.")
    parser.add_argument("--input-jsonl", action="append", default=[], help="Replay or per-position JSONL input.")
    parser.add_argument("--output-dir", required=True, help="Directory for teacher rows, audit ledgers, and summary.")
    parser.add_argument(
        "--stockfish-path",
        default="",
        help="External Stockfish-compatible UCI binary. Defaults to $STOCKFISH_PATH or PATH lookup.",
    )
    parser.add_argument("--depth", type=int, default=8, help="Stockfish analysis depth. Set <=0 to rely on movetime only.")
    parser.add_argument("--movetime-ms", type=int, default=0, help="Optional per-position movetime in ms.")
    parser.add_argument("--multipv", type=int, default=5, help="Number of principal variations to request.")
    parser.add_argument("--max-positions", type=int, default=0, help="Maximum positions to analyze after sampling.")
    parser.add_argument("--max-games", type=int, default=0, help="Maximum game-level rows to scan.")
    parser.add_argument("--sample-every", type=int, default=1, help="Analyze every Nth extracted position.")
    parser.add_argument("--skip-opening-plies", type=int, default=0, help="Skip the first N plies before auditing.")
    parser.add_argument("--max-ply", type=int, default=0, help="Ignore positions after this ply number.")
    parser.add_argument("--accept-topk", type=int, default=3, help="Played move is clean if it appears within this Stockfish rank.")
    parser.add_argument("--clean-cp-loss", type=int, default=60, help="Played move is clean if cp loss is at most this value.")
    parser.add_argument("--review-cp-loss", type=int, default=160, help="Played move is review if cp loss is at most this value.")
    parser.add_argument("--hard-negative-cp-loss", type=int, default=220, help="Played move becomes a hard negative at/above this cp loss.")
    parser.add_argument("--teacher-weight", type=float, default=1.4, help="Weight for emitted Stockfish top-1 teacher rows.")
    parser.add_argument("--played-clean-weight", type=float, default=0.6, help="Weight for clean played-move rows.")
    parser.add_argument("--eval-mod", type=int, default=10, help="Deterministic split: bucket 0 => eval, others => train. 0 disables split.")
    parser.add_argument("--replace-output", action="store_true", help="Replace output directory files instead of appending.")
    parser.add_argument("--report-md", default="", help="Optional markdown report path.")
    return parser.parse_args()


@dataclass(frozen=True)
class PositionRow:
    fen: str
    move_uci: str
    side: str
    source_id: str
    source_path: str
    replay_id: str
    ply: int
    game_index: int
    source_kind: str
    actor: str
    pgn_headers: dict


def _progress(message: str) -> None:
    print(f"[chess-stockfish-teacher] {message}", file=sys.stderr, flush=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _resolve_stockfish_path(path_text: str) -> str:
    explicit = str(path_text or "").strip()
    if explicit:
        return str(Path(explicit).expanduser().resolve())
    env_path = str(os.environ.get("STOCKFISH_PATH", "")).strip()
    if env_path:
        return str(Path(env_path).expanduser().resolve())
    found = shutil.which("stockfish")
    return str(Path(found).resolve()) if found else ""


def _read_jsonl(path: Path) -> Iterable[tuple[int, dict]]:
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_no}: row must be an object")
        yield line_no, payload


def _row_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _side_from_fen(fen: str) -> str:
    try:
        board = chess.Board(fen)
    except Exception:
        return "white" if " w " in fen else "black"
    return "white" if board.turn == chess.WHITE else "black"


def _entry_uci(entry: dict) -> str:
    direct = str(entry.get("uci") or "").strip().lower()
    if direct:
        return direct
    return f"{entry.get('from') or ''}{entry.get('to') or ''}{entry.get('promotion') or ''}".strip().lower()


def _extract_game_history_row(
    *,
    row: dict,
    source_path: str,
    line_no: int,
    game_index: int,
    history_key: str,
) -> list[PositionRow]:
    history = row.get(history_key) or []
    if not isinstance(history, list):
        return []
    replay_id = str(row.get("replay_id") or row.get("match_id") or row.get("game_key") or _row_hash(row)[:16])
    headers = dict(row.get("pgn_headers") or {})
    out: list[PositionRow] = []
    board: chess.Board | None = None
    opening_seed = str(row.get("opening_seed") or "").strip()
    if opening_seed and opening_seed != "standard_start":
        try:
            board = chess.Board(opening_seed)
        except Exception:
            board = None
    if board is None:
        board = chess.Board()
    for index, entry in enumerate(history, start=1):
        if not isinstance(entry, dict):
            continue
        fen = str(entry.get("fen_before") or "").strip()
        move_uci = _entry_uci(entry)
        if not move_uci:
            continue
        if not fen:
            fen = board.fen()
        side = str(entry.get("by") or entry.get("side") or "").strip().lower()
        if side not in {"white", "black"}:
            side = _side_from_fen(fen)
        source_id = f"{Path(source_path).name}:{line_no}:{history_key}:{index}"
        out.append(
            PositionRow(
                fen=fen,
                move_uci=move_uci,
                side=side,
                source_id=source_id,
                source_path=source_path,
                replay_id=replay_id,
                ply=int(entry.get("ply") or index),
                game_index=game_index,
                source_kind=f"game_{history_key}",
                actor=str(entry.get("actor") or entry.get("by") or ""),
                pgn_headers=headers,
            )
        )
        try:
            move = chess.Move.from_uci(move_uci)
            if move in board.legal_moves:
                board.push(move)
            elif fen:
                board = chess.Board(fen)
                if move in board.legal_moves:
                    board.push(move)
        except Exception:
            continue
    return out


def _extract_position_rows(path: Path, *, max_games: int) -> list[PositionRow]:
    rows: list[PositionRow] = []
    game_rows_seen = 0
    for line_no, payload in _read_jsonl(path):
        if "move_history" in payload:
            game_rows_seen += 1
            if max_games and game_rows_seen > max_games:
                continue
            rows.extend(
                _extract_game_history_row(
                    row=payload,
                    source_path=str(path),
                    line_no=line_no,
                    game_index=game_rows_seen,
                    history_key="move_history",
                )
            )
            continue
        if "moves" in payload:
            game_rows_seen += 1
            if max_games and game_rows_seen > max_games:
                continue
            rows.extend(
                _extract_game_history_row(
                    row=payload,
                    source_path=str(path),
                    line_no=line_no,
                    game_index=game_rows_seen,
                    history_key="moves",
                )
            )
            continue
        fen = str(payload.get("fen") or payload.get("board_fen") or "").strip()
        move_uci = str(payload.get("move_uci") or payload.get("uci") or payload.get("move") or "").strip().lower()
        if not fen or not move_uci:
            continue
        side = str(payload.get("side") or "").strip().lower()
        if side not in {"white", "black"}:
            side = _side_from_fen(fen)
        rows.append(
            PositionRow(
                fen=fen,
                move_uci=move_uci,
                side=side,
                source_id=str(payload.get("source_id") or f"{path.name}:{line_no}"),
                source_path=str(path),
                replay_id=str(payload.get("replay_id") or payload.get("source_game_id") or ""),
                ply=int(payload.get("source_move_index") or payload.get("ply") or line_no),
                game_index=0,
                source_kind="position_row",
                actor=str(payload.get("actor") or payload.get("side") or ""),
                pgn_headers=dict(payload.get("pgn_headers") or {}),
            )
        )
    return rows


def _position_id(fen: str, side: str, ply: int) -> str:
    try:
        board = chess.Board(fen)
        ep = chess.square_name(board.ep_square) if board.ep_square is not None else "-"
        normalized = "|".join(
            [
                board.board_fen(),
                "w" if board.turn else "b",
                board.castling_xfen() or "-",
                ep,
                str(side),
                str(int(ply)),
            ]
        )
    except Exception:
        normalized = f"{fen}|{side}|{ply}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _split_bucket(position_id: str, eval_mod: int) -> int:
    if int(eval_mod or 0) <= 0:
        return -1
    return int(position_id[:8], 16) % int(eval_mod)


def _analysis_limit(*, depth: int, movetime_ms: int) -> dict[str, int]:
    kwargs: dict[str, int] = {}
    if int(depth or 0) > 0:
        kwargs["depth"] = int(depth)
    if int(movetime_ms or 0) > 0:
        kwargs["movetime"] = int(movetime_ms)
    if not kwargs:
        kwargs["depth"] = 8
    return kwargs


class UciStockfish:
    """Small blocking UCI client.

    python-chess' SimpleEngine can hang against some bleeding-edge Stockfish dev
    binaries in this environment. The direct UCI protocol remains stable and is
    simple enough for the fixed teacher/audit workflow we need here.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.proc = subprocess.Popen(
            [path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._send("uci")
        self._read_until(lambda line: line.strip() == "uciok")
        self.setoption("UCI_ShowWDL", "true")
        self.isready()

    def __enter__(self) -> "UciStockfish":
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.quit()

    def _send(self, text: str) -> None:
        if self.proc.stdin is None:
            raise RuntimeError("stockfish stdin closed")
        self.proc.stdin.write(text.rstrip("\n") + "\n")
        self.proc.stdin.flush()

    def _read_until(self, predicate) -> list[str]:
        if self.proc.stdout is None:
            raise RuntimeError("stockfish stdout closed")
        lines: list[str] = []
        while True:
            line = self.proc.stdout.readline()
            if line == "":
                raise RuntimeError("stockfish exited before expected UCI response")
            line = line.rstrip("\n")
            lines.append(line)
            if predicate(line):
                return lines

    def setoption(self, name: str, value: str) -> None:
        self._send(f"setoption name {name} value {value}")

    def isready(self) -> None:
        self._send("isready")
        self._read_until(lambda line: line.strip() == "readyok")

    def quit(self) -> None:
        if self.proc.poll() is not None:
            return
        try:
            self._send("quit")
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
        self._send(f"position fen {board.fen()}")
        parts = ["go"]
        if int(limit.get("depth") or 0) > 0:
            parts.extend(["depth", str(int(limit["depth"]))])
        if int(limit.get("movetime") or 0) > 0:
            parts.extend(["movetime", str(int(limit["movetime"]))])
        if root_moves:
            # Stockfish parses all tokens after `searchmoves` as candidate
            # moves, so keep this clause at the end of the command.
            parts.append("searchmoves")
            parts.extend(move.uci() for move in root_moves)
        self._send(" ".join(parts))
        lines = self._read_until(lambda line: line.startswith("bestmove"))
        return _parse_uci_info(lines)


def _parse_uci_info(lines: list[str]) -> list[dict]:
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
                score_type = tokens[idx + 1]
                try:
                    raw_score = int(tokens[idx + 2])
                except Exception:
                    raw_score = 0
                if score_type == "mate":
                    row["teacher_eval_cp"] = 100000 - abs(raw_score) if raw_score > 0 else -100000 + abs(raw_score)
                    row["mate"] = raw_score
                else:
                    row["teacher_eval_cp"] = raw_score
        if "pv" in tokens:
            pv = tokens[tokens.index("pv") + 1 :]
            row["pv"] = pv[:8]
            if pv:
                row["move"] = pv[0]
        latest[multipv] = row
    rows = [row for _rank, row in sorted(latest.items()) if row.get("move")]
    for index, row in enumerate(rows, start=1):
        row.setdefault("rank", index)
        row.setdefault("teacher_eval_cp", 0)
        row.setdefault("depth", 0)
        row.setdefault("seldepth", 0)
        row.setdefault("nodes", 0)
        row.setdefault("pv", [row["move"]])
    return rows


def _analyse_topk(
    engine: UciStockfish,
    board: chess.Board,
    *,
    limit: dict[str, int],
    multipv: int,
) -> list[dict]:
    infos = engine.analyse(board, limit=limit, multipv=max(1, int(multipv)))
    rows: list[dict] = []
    seen: set[str] = set()
    for rank, info in enumerate(infos, start=1):
        pv = [chess.Move.from_uci(item) for item in (info.get("pv") or []) if str(item)]
        if not pv:
            continue
        move = pv[0]
        if move not in board.legal_moves:
            continue
        uci = move.uci()
        if uci in seen:
            continue
        seen.add(uci)
        rows.append(
            {
                "rank": rank,
                "move": uci,
                "teacher_eval_cp": int(info.get("teacher_eval_cp") or 0),
                "depth": int(info.get("depth") or 0),
                "seldepth": int(info.get("seldepth") or 0),
                "nodes": int(info.get("nodes") or 0),
                "pv": [mv.uci() for mv in pv[:8]],
            }
        )
    rows.sort(key=lambda item: int(item["rank"]))
    return rows


def _analyse_root_move(
    engine: UciStockfish,
    board: chess.Board,
    move: chess.Move,
    *,
    limit: dict[str, int],
) -> dict:
    infos = engine.analyse(board, limit=limit, multipv=1, root_moves=[move])
    info = infos[0] if infos else {}
    pv = [chess.Move.from_uci(item) for item in (info.get("pv") or []) if str(item)]
    return {
        "move": move.uci(),
        "teacher_eval_cp": int(info.get("teacher_eval_cp") or 0),
        "depth": int(info.get("depth") or 0),
        "seldepth": int(info.get("seldepth") or 0),
        "nodes": int(info.get("nodes") or 0),
        "pv": [mv.uci() for mv in pv[:8]],
    }


def _category(board: chess.Board, move: chess.Move, ply: int) -> str:
    if board.is_castling(move):
        return "special_rule"
    if board.is_en_passant(move) or move.promotion:
        return "special_rule"
    if ply <= 20:
        return "opening"
    piece_count = len(board.piece_map())
    if piece_count <= 10 or not board.queens:
        return "endgame"
    if board.is_capture(move) or board.gives_check(move):
        return "tactical"
    return "quiet_positional"


def _teacher_weights(topk: list[dict]) -> dict[str, float]:
    if not topk:
        return {}
    best = int(topk[0].get("teacher_eval_cp") or 0)
    weights: dict[str, float] = {}
    for row in topk:
        move = str(row.get("move") or "")
        if not move:
            continue
        loss = max(0, best - int(row.get("teacher_eval_cp") or 0))
        if int(row.get("rank") or 0) == 1:
            weight = 1.0
        elif loss <= 25:
            weight = 0.85
        elif loss <= 60:
            weight = 0.65
        elif loss <= 120:
            weight = 0.35
        else:
            weight = 0.15
        weights[move] = round(weight, 4)
    return weights


def _write_jsonl(path: Path, rows: list[dict], *, replace: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if replace else "a"
    with path.open(mode, encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_md_report(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    counts = summary.get("counts") or {}
    lines = [
        "# Stockfish Teacher Audit",
        "",
        f"- Generated: `{summary.get('generated_at')}`",
        f"- Stockfish binary: `{summary.get('stockfish_path')}`",
        f"- Stockfish commit/reference: `{summary.get('stockfish_reference')}`",
        f"- Depth: `{summary.get('depth')}`, movetime_ms: `{summary.get('movetime_ms')}`, MultiPV: `{summary.get('multipv')}`",
        f"- Positions analyzed: `{counts.get('analyzed_positions')}`",
        f"- Teacher rows: `{counts.get('teacher_rows')}`",
        f"- Played clean rows: `{counts.get('played_clean_rows')}`",
        f"- Review rows: `{counts.get('review_rows')}`",
        f"- Rejected rows: `{counts.get('rejected_rows')}`",
        "",
        "## Outputs",
        "",
    ]
    for key in (
        "teacher_train_jsonl",
        "teacher_eval_jsonl",
        "teacher_all_jsonl",
        "played_clean_jsonl",
        "review_jsonl",
        "rejected_jsonl",
        "audit_detail_jsonl",
        "summary_json",
    ):
        if summary.get(key):
            lines.append(f"- `{key}`: `{summary[key]}`")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "Clean played rows mean the source move agreed with Stockfish top-K or had small centipawn loss.",
            "Teacher rows always train Stockfish's selected top move and keep the source move only as audit context or a hard negative.",
            "The Stockfish binary is external and must not be committed unless GPLv3 distribution obligations are intentionally accepted.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _stockfish_reference(stockfish_path: str) -> str:
    path = Path(stockfish_path)
    try:
        repo = path.resolve().parents[1]
        head = (repo / ".git").exists()
        if head:
            import subprocess

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


def run(args: argparse.Namespace) -> dict:
    input_paths = [Path(item).expanduser().resolve() for item in args.input_jsonl]
    if not input_paths:
        raise SystemExit("error: at least one --input-jsonl is required")
    engine_path = stockfish_teacher.resolve_stockfish_path(str(args.stockfish_path or ""))
    if not engine_path or not Path(engine_path).exists():
        raise SystemExit("error: Stockfish binary not found; pass --stockfish-path or set STOCKFISH_PATH")
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    teacher_all_path = output_dir / "stockfish_teacher_rows.jsonl"
    teacher_train_path = output_dir / "stockfish_teacher_train_rows.jsonl"
    teacher_eval_path = output_dir / "stockfish_teacher_eval_rows.jsonl"
    played_clean_path = output_dir / "stockfish_played_clean_rows.jsonl"
    review_path = output_dir / "stockfish_review_rows.jsonl"
    rejected_path = output_dir / "stockfish_rejected_rows.jsonl"
    detail_path = output_dir / "stockfish_audit_detail.jsonl"
    summary_path = output_dir / "summary.json"
    if args.replace_output:
        for path in (
            teacher_all_path,
            teacher_train_path,
            teacher_eval_path,
            played_clean_path,
            review_path,
            rejected_path,
            detail_path,
            summary_path,
        ):
            if path.exists():
                path.unlink()

    _progress(f"stockfish: {engine_path}")
    _progress(f"inputs: {len(input_paths)} output_dir={output_dir}")
    source_positions: list[PositionRow] = []
    for input_path in input_paths:
        _progress(f"phase extract positions: {input_path}")
        before = len(source_positions)
        source_positions.extend(_extract_position_rows(input_path, max_games=max(0, int(args.max_games or 0))))
        _progress(f"phase result extract: {len(source_positions) - before} positions")

    sample_every = max(1, int(args.sample_every or 1))
    skip_opening_plies = max(0, int(args.skip_opening_plies or 0))
    max_ply = max(0, int(args.max_ply or 0))
    filtered: list[PositionRow] = []
    for index, row in enumerate(source_positions, start=1):
        if row.ply <= skip_opening_plies:
            continue
        if max_ply and row.ply > max_ply:
            continue
        if ((index - 1) % sample_every) != 0:
            continue
        filtered.append(row)
        if int(args.max_positions or 0) > 0 and len(filtered) >= int(args.max_positions):
            break
    _progress(f"phase sampling result: extracted={len(source_positions)} selected={len(filtered)}")

    limit = stockfish_teacher.analysis_limit(depth=int(args.depth or 0), movetime_ms=int(args.movetime_ms or 0))
    counts = {
        "input_paths": len(input_paths),
        "extracted_positions": len(source_positions),
        "selected_positions": len(filtered),
        "analyzed_positions": 0,
        "teacher_rows": 0,
        "teacher_train_rows": 0,
        "teacher_eval_rows": 0,
        "played_clean_rows": 0,
        "review_rows": 0,
        "rejected_rows": 0,
        "invalid_rows": 0,
        "hard_negative_source_moves": 0,
        "by_category": {},
        "by_played_status": {},
    }
    teacher_all: list[dict] = []
    teacher_train: list[dict] = []
    teacher_eval: list[dict] = []
    played_clean: list[dict] = []
    review: list[dict] = []
    rejected: list[dict] = []
    detail_rows: list[dict] = []

    with stockfish_teacher.UciStockfish(engine_path) as engine:
        for index, item in enumerate(filtered, start=1):
            if index == 1 or index % 25 == 0 or index == len(filtered):
                _progress(f"phase stockfish analyse: {index}/{len(filtered)}")
            try:
                board = chess.Board(item.fen)
                target_turn = chess.WHITE if item.side == "white" else chess.BLACK
                if board.turn != target_turn:
                    board.turn = target_turn
                played_move = chess.Move.from_uci(item.move_uci)
            except Exception as exc:
                counts["invalid_rows"] += 1
                rejected.append(
                    {
                        "source_id": item.source_id,
                        "fen": item.fen,
                        "move_uci": item.move_uci,
                        "audit_status": "rejected",
                        "audit_reasons": [f"invalid_position_or_uci:{exc.__class__.__name__}"],
                    }
                )
                continue
            if played_move not in board.legal_moves:
                counts["invalid_rows"] += 1
                rejected.append(
                    {
                        "source_id": item.source_id,
                        "fen": board.fen(),
                        "move_uci": item.move_uci,
                        "side": item.side,
                        "audit_status": "rejected",
                        "audit_reasons": ["illegal_source_move"],
                    }
                )
                continue

            topk = _analyse_topk(engine, board, limit=limit, multipv=max(1, int(args.multipv or 1)))
            if not topk:
                counts["rejected_rows"] += 1
                rejected.append(
                    {
                        "source_id": item.source_id,
                        "fen": board.fen(),
                        "move_uci": item.move_uci,
                        "side": item.side,
                        "audit_status": "rejected",
                        "audit_reasons": ["stockfish_no_pv"],
                    }
                )
                continue

            counts["analyzed_positions"] += 1
            best = topk[0]
            top_moves = [str(row["move"]) for row in topk]
            played_rank = top_moves.index(played_move.uci()) + 1 if played_move.uci() in top_moves else 0
            if played_rank:
                played_eval = int(topk[played_rank - 1].get("teacher_eval_cp") or 0)
                played_analysis = dict(topk[played_rank - 1])
            else:
                played_analysis = _analyse_root_move(engine, board, played_move, limit=limit)
                played_eval = int(played_analysis.get("teacher_eval_cp") or 0)
            best_eval = int(best.get("teacher_eval_cp") or 0)
            cp_loss = max(0, best_eval - played_eval)
            position_id = _position_id(board.fen(), item.side, item.ply)
            bucket = _split_bucket(position_id, int(args.eval_mod or 0))
            category = _category(board, chess.Move.from_uci(str(best["move"])), item.ply)
            counts["by_category"][category] = counts["by_category"].get(category, 0) + 1

            clean_by_rank = bool(played_rank and played_rank <= max(1, int(args.accept_topk or 1)))
            clean_by_cp = cp_loss <= int(args.clean_cp_loss)
            review_by_cp = cp_loss <= int(args.review_cp_loss)
            if clean_by_rank or clean_by_cp:
                played_status = "clean"
                reasons = ["legal_move"]
                if clean_by_rank:
                    reasons.append("stockfish_topk_agreement")
                if clean_by_cp:
                    reasons.append("cp_loss_clean")
            elif review_by_cp:
                played_status = "review"
                reasons = ["legal_move", "cp_loss_review"]
            else:
                played_status = "rejected"
                reasons = ["legal_move", "cp_loss_too_high"]
            counts["by_played_status"][played_status] = counts["by_played_status"].get(played_status, 0) + 1

            hard_negatives: list[str] = []
            if cp_loss >= int(args.hard_negative_cp_loss) and played_move.uci() != str(best["move"]):
                hard_negatives.append(played_move.uci())
                counts["hard_negative_source_moves"] += 1
            teacher_top3 = top_moves[:3]
            teacher_top5 = top_moves[:5]
            teacher_row = {
                "fen": board.fen(),
                "move_uci": str(best["move"]),
                "side": item.side,
                "target": 1.0,
                "weight": float(args.teacher_weight),
                "source": "stockfish_teacher_audited",
                "trusted_source": "stockfish_teacher_audited",
                "teacher_backend": "stockfish",
                "teacher_backend_used": "stockfish",
                "teacher_top_k_method": "stockfish_multipv",
                "teacher_depth": int(args.depth or 0),
                "teacher_movetime_ms": int(args.movetime_ms or 0),
                "teacher_multipv": int(args.multipv or 1),
                "teacher_best_eval_cp": best_eval,
                "teacher_top3": teacher_top3,
                "teacher_top5": teacher_top5,
                "teacher_top_weights": _teacher_weights(topk),
                "hard_negatives": hard_negatives,
                "label_quality": "clean",
                "training_eligible": True,
                "category": category,
                "source_category": "teacher_guidance",
                "position_id": position_id,
                "dataset_split_bucket": bucket,
                "dataset_split": "eval" if bucket == 0 else "train",
                "source_replay_id": item.replay_id,
                "source_id": item.source_id,
                "source_path": item.source_path,
                "source_ply": item.ply,
                "source_played_move": played_move.uci(),
                "source_played_rank": played_rank,
                "source_played_eval_cp": played_eval,
                "source_cp_loss": cp_loss,
                "source_played_status": played_status,
            }
            teacher_all.append(teacher_row)
            if bucket == 0:
                teacher_eval.append(teacher_row)
            else:
                teacher_train.append(teacher_row)

            detail = {
                "source_id": item.source_id,
                "source_path": item.source_path,
                "source_replay_id": item.replay_id,
                "source_ply": item.ply,
                "fen": board.fen(),
                "side": item.side,
                "played_move": played_move.uci(),
                "played_status": played_status,
                "played_reasons": reasons,
                "played_rank": played_rank,
                "played_eval_cp": played_eval,
                "best_move": str(best["move"]),
                "best_eval_cp": best_eval,
                "cp_loss": cp_loss,
                "category": category,
                "teacher_topk": topk,
                "played_analysis": played_analysis,
                "dataset_split_bucket": bucket,
            }
            detail_rows.append(detail)
            if played_status == "clean":
                played_row = dict(teacher_row)
                played_row.update(
                    {
                        "move_uci": played_move.uci(),
                        "target": 1.0,
                        "weight": float(args.played_clean_weight),
                        "source": "stockfish_played_move_clean",
                        "trusted_source": "stockfish_played_move_clean",
                        "teacher_best_move": str(best["move"]),
                        "teacher_best_eval_cp": best_eval,
                        "label_quality_reason": ",".join(reasons),
                    }
                )
                played_clean.append(played_row)
            elif played_status == "review":
                review.append(detail)
            else:
                rejected.append(detail)

    counts["teacher_rows"] = len(teacher_all)
    counts["teacher_train_rows"] = len(teacher_train)
    counts["teacher_eval_rows"] = len(teacher_eval)
    counts["played_clean_rows"] = len(played_clean)
    counts["review_rows"] = len(review)
    counts["rejected_rows"] = len(rejected)

    _write_jsonl(teacher_all_path, teacher_all, replace=bool(args.replace_output))
    _write_jsonl(teacher_train_path, teacher_train, replace=bool(args.replace_output))
    _write_jsonl(teacher_eval_path, teacher_eval, replace=bool(args.replace_output))
    _write_jsonl(played_clean_path, played_clean, replace=bool(args.replace_output))
    _write_jsonl(review_path, review, replace=bool(args.replace_output))
    _write_jsonl(rejected_path, rejected, replace=bool(args.replace_output))
    _write_jsonl(detail_path, detail_rows, replace=bool(args.replace_output))

    summary = {
        "stage": "stockfish_teacher_audit",
        "generated_at": _now(),
        "stockfish_path": engine_path,
        "stockfish_reference": stockfish_teacher.stockfish_reference(engine_path),
        "stockfish_license_policy": {
            "binary_bundled_in_repo": False,
            "expected_use": "external_local_teacher",
            "distribution_note": "If Stockfish binary/NNUE is bundled or redistributed, preserve GPLv3 copyright/license/source obligations.",
        },
        "input_jsonls": [str(path) for path in input_paths],
        "output_dir": str(output_dir),
        "depth": int(args.depth or 0),
        "movetime_ms": int(args.movetime_ms or 0),
        "multipv": int(args.multipv or 1),
        "accept_topk": int(args.accept_topk),
        "clean_cp_loss": int(args.clean_cp_loss),
        "review_cp_loss": int(args.review_cp_loss),
        "hard_negative_cp_loss": int(args.hard_negative_cp_loss),
        "eval_mod": int(args.eval_mod or 0),
        "counts": counts,
        "teacher_all_jsonl": str(teacher_all_path),
        "teacher_train_jsonl": str(teacher_train_path),
        "teacher_eval_jsonl": str(teacher_eval_path),
        "played_clean_jsonl": str(played_clean_path),
        "review_jsonl": str(review_path),
        "rejected_jsonl": str(rejected_path),
        "audit_detail_jsonl": str(detail_path),
        "summary_json": str(summary_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.report_md:
        _write_md_report(Path(args.report_md).expanduser().resolve(), summary)
        summary["report_md"] = str(Path(args.report_md).expanduser().resolve())
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _progress(
        "phase result: "
        f"teacher={counts['teacher_rows']} train={counts['teacher_train_rows']} eval={counts['teacher_eval_rows']} "
        f"played_clean={counts['played_clean_rows']} review={counts['review_rows']} rejected={counts['rejected_rows']}"
    )
    return summary


def main() -> int:
    args = parse_args()
    summary = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
