#!/usr/bin/env python3
"""Private 100-scenario expanded validation for chess exp5.

The question set is intentionally sensitive: it contains FENs, source moves,
and downloaded-game segments.  Keep it outside the repo, under
``~/hackme_web_private/runtime/private`` by default.  Public docs outputs from
this script are aggregate/redacted by default and must not expose FENs, moves,
Stockfish PVs, or source game identifiers.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time
from typing import Any, Iterable

import chess


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess import FEN_KEY  # noqa: E402
from services.games.chess_nnue import choose_experiment_nnue_move  # noqa: E402
from services.games import chess_stockfish_teacher as stockfish_teacher  # noqa: E402


PROFILE_V24 = "fixed_depth_fianchetto_tail_castle_guard"
PRIVATE_ROOT = Path(os.environ.get("HACKME_WEB_PRIVATE_ROOT", str(ROOT.parent / "hackme_web_private/runtime/private"))).expanduser()
DEFAULT_PRIVATE_ROOT = PRIVATE_ROOT / "games/exp5/v24_expanded_100"
LEGACY_SECTIONS = ("tail10", "tail20", "human_probe_trap", "complete_game")
PERCENT_TAIL_SECTIONS = ("tail10pct", "tail25pct", "tail50pct", "complete_game")


@dataclass(frozen=True)
class SourcePosition:
    fen: str
    move_uci: str
    side: str
    ply: int
    san: str
    motifs: tuple[str, ...]


@dataclass(frozen=True)
class SourceGame:
    source_index: int
    replay_id: str
    rating_estimate: int
    result: str
    move_count: int
    labels: dict[str, Any]
    positions: tuple[SourcePosition, ...]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _progress(message: str) -> None:
    print(f"[exp5-expanded-validation] {message}", file=sys.stderr, flush=True)


def _read_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            yield line_no, payload


def _short_hash(payload: Any, *, length: int = 16) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:length]


def _side_from_fen(fen: str) -> str:
    board = chess.Board(fen)
    return "white" if board.turn == chess.WHITE else "black"


def _board_state(board: chess.Board) -> dict[str, str]:
    state = {chess.square_name(square): piece.symbol() for square, piece in board.piece_map().items()}
    state[FEN_KEY] = board.fen()
    return state


def _move_from_decision(move: dict[str, Any] | None) -> str:
    if not move:
        return ""
    return f"{move.get('from') or ''}{move.get('to') or ''}{move.get('promotion') or ''}".strip().lower()


def _entry_uci(entry: dict[str, Any]) -> str:
    direct = str(entry.get("uci") or "").strip().lower()
    if direct:
        return direct
    return f"{entry.get('from') or ''}{entry.get('to') or ''}{entry.get('promotion') or ''}".strip().lower()


def _motifs(board: chess.Board, move: chess.Move, entry: dict[str, Any], ply: int) -> tuple[str, ...]:
    motifs: set[str] = set()
    piece = board.piece_at(move.from_square)
    if ply <= 20:
        motifs.add("opening")
    if board.is_capture(move):
        motifs.add("capture")
    if board.gives_check(move) or bool(entry.get("check_after")):
        motifs.add("check")
    if board.is_castling(move) or bool(entry.get("castle")):
        motifs.add("castling")
    if board.is_en_passant(move) or bool(entry.get("en_passant")):
        motifs.add("en_passant")
    if move.promotion:
        motifs.add("promotion")
    if piece and piece.piece_type == chess.QUEEN and ply <= 14:
        motifs.add("early_queen_human_probe")
    if board.is_attacked_by(not board.turn, move.to_square) and piece and piece.piece_type in {
        chess.QUEEN,
        chess.ROOK,
        chess.BISHOP,
        chess.KNIGHT,
    }:
        motifs.add("tactical_exposure")
    if len(board.piece_map()) <= 10 or not board.queens:
        motifs.add("endgame")
    if not motifs:
        motifs.add("quiet")
    return tuple(sorted(motifs))


def _parse_source_games(paths: list[Path]) -> list[SourceGame]:
    games: list[SourceGame] = []
    for path in paths:
        for _line_no, row in _read_jsonl(path):
            history = row.get("move_history")
            if not isinstance(history, list) or not history:
                continue
            positions: list[SourcePosition] = []
            for ply_index, entry in enumerate(history, start=1):
                if not isinstance(entry, dict):
                    continue
                fen = str(entry.get("fen_before") or "").strip()
                move_uci = _entry_uci(entry)
                side = str(entry.get("by") or "").strip().lower()
                if side not in {"white", "black"} and fen:
                    try:
                        side = _side_from_fen(fen)
                    except Exception:
                        side = ""
                if not fen or len(move_uci) < 4 or side not in {"white", "black"}:
                    continue
                try:
                    board = chess.Board(fen)
                    move = chess.Move.from_uci(move_uci)
                except Exception:
                    continue
                if move not in board.legal_moves:
                    continue
                positions.append(
                    SourcePosition(
                        fen=board.fen(),
                        move_uci=move.uci(),
                        side=side,
                        ply=int(entry.get("ply") or ply_index),
                        san=str(entry.get("san") or ""),
                        motifs=_motifs(board, move, entry, int(entry.get("ply") or ply_index)),
                    )
                )
            if not positions:
                continue
            labels = dict(row.get("pgn_labels") or {})
            games.append(
                SourceGame(
                    source_index=len(games) + 1,
                    replay_id=str(row.get("replay_id") or row.get("match_id") or _short_hash(row)),
                    rating_estimate=int(row.get("rating_estimate") or labels.get("avg_elo") or 0),
                    result=str(row.get("result") or ""),
                    move_count=len(positions),
                    labels=labels,
                    positions=tuple(positions),
                )
            )
    return games


def _analyse_topk(
    engine: stockfish_teacher.UciStockfish,
    board: chess.Board,
    *,
    limit: dict[str, int],
    multipv: int,
) -> list[dict[str, Any]]:
    rows = engine.analyse(board, limit=limit, multipv=max(1, int(multipv)))
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rank, row in enumerate(rows, start=1):
        move_uci = str(row.get("move") or "").strip().lower()
        if not move_uci or move_uci in seen:
            continue
        try:
            move = chess.Move.from_uci(move_uci)
        except Exception:
            continue
        if move not in board.legal_moves:
            continue
        seen.add(move_uci)
        out.append(
            {
                "rank": int(row.get("rank") or rank),
                "move": move.uci(),
                "teacher_eval_cp": int(row.get("teacher_eval_cp") or 0),
                "depth": int(row.get("depth") or 0),
                "nodes": int(row.get("nodes") or 0),
            }
        )
    out.sort(key=lambda item: int(item.get("rank") or 999))
    return out


def _analyse_root_move(
    engine: stockfish_teacher.UciStockfish,
    board: chess.Board,
    move: chess.Move,
    *,
    limit: dict[str, int],
) -> dict[str, Any]:
    rows = engine.analyse(board, limit=limit, multipv=1, root_moves=[move])
    row = dict(rows[0]) if rows else {}
    return {
        "move": move.uci(),
        "teacher_eval_cp": int(row.get("teacher_eval_cp") or 0),
        "depth": int(row.get("depth") or 0),
        "nodes": int(row.get("nodes") or 0),
    }


def _audit_move(
    engine: stockfish_teacher.UciStockfish,
    fen: str,
    move_uci: str,
    *,
    limit: dict[str, int],
    multipv: int,
    accept_topk: int,
    clean_cp_loss: int,
    review_cp_loss: int,
) -> dict[str, Any]:
    try:
        board = chess.Board(fen)
        move = chess.Move.from_uci(move_uci)
    except Exception:
        return {"legal": False, "status": "rejected", "rank": None, "cp_loss": None, "reason": "invalid"}
    if move not in board.legal_moves:
        return {"legal": False, "status": "rejected", "rank": None, "cp_loss": None, "reason": "illegal"}
    topk = _analyse_topk(engine, board, limit=limit, multipv=multipv)
    if not topk:
        return {"legal": True, "status": "rejected", "rank": None, "cp_loss": None, "reason": "teacher_no_pv"}
    best_eval = int(topk[0].get("teacher_eval_cp") or 0)
    top_moves = [str(row.get("move") or "") for row in topk]
    rank = top_moves.index(move.uci()) + 1 if move.uci() in top_moves else None
    if rank is not None:
        chosen_eval = int(topk[rank - 1].get("teacher_eval_cp") or 0)
    else:
        chosen_eval = int(_analyse_root_move(engine, board, move, limit=limit).get("teacher_eval_cp") or 0)
    cp_loss = max(0, best_eval - chosen_eval)
    if rank is not None and rank <= max(1, int(accept_topk)):
        status = "clean"
        reason = "teacher_topk"
    elif cp_loss <= int(clean_cp_loss):
        status = "clean"
        reason = "cp_loss_clean"
    elif cp_loss <= int(review_cp_loss):
        status = "review"
        reason = "cp_loss_review"
    else:
        status = "rejected"
        reason = "cp_loss_rejected"
    return {
        "legal": True,
        "status": status,
        "rank": rank,
        "cp_loss": cp_loss,
        "chosen_eval_cp": chosen_eval,
        "best_eval_cp": best_eval,
        "reason": reason,
        "teacher_depth": int(topk[0].get("depth") or 0),
        "teacher_nodes": int(topk[0].get("nodes") or 0),
    }


def _segment_quality(statuses: list[dict[str, Any]], *, min_clean_rate: float, max_rejected: int) -> bool:
    if not statuses:
        return False
    rejected = sum(1 for row in statuses if row.get("status") == "rejected")
    clean = sum(1 for row in statuses if row.get("status") == "clean")
    review = sum(1 for row in statuses if row.get("status") == "review")
    return rejected <= max_rejected and (clean + review) == len(statuses) and clean / max(1, len(statuses)) >= min_clean_rate


def _quality_summary(statuses: list[dict[str, Any]]) -> dict[str, Any]:
    cp_losses = [int(row["cp_loss"]) for row in statuses if isinstance(row.get("cp_loss"), int)]
    return {
        "positions": len(statuses),
        "clean": sum(1 for row in statuses if row.get("status") == "clean"),
        "review": sum(1 for row in statuses if row.get("status") == "review"),
        "rejected": sum(1 for row in statuses if row.get("status") == "rejected"),
        "avg_cp_loss": round(sum(cp_losses) / max(1, len(cp_losses)), 3),
        "max_cp_loss": max(cp_losses or [None]),
    }


def _question_from_positions(
    *,
    section: str,
    ordinal: int,
    game: SourceGame,
    positions: list[SourcePosition],
    source_statuses: list[dict[str, Any]],
) -> dict[str, Any]:
    public_key = _short_hash(
        {
            "section": section,
            "ordinal": ordinal,
            "replay": game.replay_id,
            "plies": [pos.ply for pos in positions],
        },
        length=12,
    )
    return {
        "question_id": f"{section}_{ordinal:03d}_{public_key}",
        "section": section,
        "source": "downloaded_pgn_blockfish_audited",
        "source_game_hash": _short_hash(game.replay_id, length=16),
        "rating_estimate": game.rating_estimate,
        "move_count": game.move_count,
        "positions": [
            {
                "fen": pos.fen,
                "side": pos.side,
                "source_move": pos.move_uci,
                "source_san": pos.san,
                "ply": pos.ply,
                "motifs": list(pos.motifs),
            }
            for pos in positions
        ],
        "source_quality": _quality_summary(source_statuses),
    }


def _pick_tail_questions(
    *,
    section: str,
    tail_len: int,
    games: list[SourceGame],
    used: set[tuple[str, str]],
    engine: stockfish_teacher.UciStockfish,
    limit: dict[str, int],
    args: argparse.Namespace,
    target: int,
) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for game in games:
        if len(questions) >= target:
            break
        if len(game.positions) < tail_len + 8:
            continue
        key = (section, game.replay_id)
        if key in used:
            continue
        segment = list(game.positions[-tail_len:])
        statuses = [
            _audit_move(
                engine,
                pos.fen,
                pos.move_uci,
                limit=limit,
                multipv=int(args.multipv),
                accept_topk=int(args.accept_topk),
                clean_cp_loss=int(args.clean_cp_loss),
                review_cp_loss=int(args.review_cp_loss),
            )
            for pos in segment
        ]
        if not _segment_quality(statuses, min_clean_rate=float(args.min_segment_clean_rate), max_rejected=0):
            continue
        used.add(key)
        questions.append(
            _question_from_positions(
                section=section,
                ordinal=len(questions) + 1,
                game=game,
                positions=segment,
                source_statuses=statuses,
            )
        )
        _progress(f"accepted {section}: {len(questions)}/{target}")
    return questions


def _pick_tail_percent_questions(
    *,
    percent: int,
    games: list[SourceGame],
    used: set[tuple[str, str]],
    engine: stockfish_teacher.UciStockfish,
    limit: dict[str, int],
    args: argparse.Namespace,
    target: int,
) -> list[dict[str, Any]]:
    section = f"tail{int(percent)}pct"
    questions: list[dict[str, Any]] = []
    for game in games:
        if len(questions) >= target:
            break
        if len(game.positions) < int(args.min_complete_plies):
            continue
        key = (section, game.replay_id)
        if key in used:
            continue
        tail_len = max(1, int(round(len(game.positions) * (int(percent) / 100.0))))
        if len(game.positions) < tail_len + 8:
            continue
        segment = list(game.positions[-tail_len:])
        statuses = [
            _audit_move(
                engine,
                pos.fen,
                pos.move_uci,
                limit=limit,
                multipv=int(args.multipv),
                accept_topk=int(args.accept_topk),
                clean_cp_loss=int(args.clean_cp_loss),
                review_cp_loss=int(args.review_cp_loss),
            )
            for pos in segment
        ]
        if not _segment_quality(statuses, min_clean_rate=float(args.min_segment_clean_rate), max_rejected=0):
            continue
        used.add(key)
        questions.append(
            _question_from_positions(
                section=section,
                ordinal=len(questions) + 1,
                game=game,
                positions=segment,
                source_statuses=statuses,
            )
        )
        _progress(f"accepted {section}: {len(questions)}/{target}")
    return questions


def _pick_human_probe_trap_questions(
    *,
    games: list[SourceGame],
    used_positions: set[str],
    engine: stockfish_teacher.UciStockfish,
    limit: dict[str, int],
    args: argparse.Namespace,
    target: int,
) -> list[dict[str, Any]]:
    motif_priority = {
        "promotion": 0,
        "en_passant": 1,
        "check": 2,
        "capture": 3,
        "castling": 4,
        "early_queen_human_probe": 5,
        "tactical_exposure": 6,
        "opening": 7,
    }
    candidates: list[tuple[int, SourceGame, SourcePosition]] = []
    for game in games:
        for pos in game.positions:
            motifs = set(pos.motifs)
            if not motifs.intersection(motif_priority):
                continue
            priority = min(motif_priority[motif] for motif in motifs.intersection(motif_priority))
            candidates.append((priority, game, pos))
    candidates.sort(key=lambda item: (item[0], -item[1].rating_estimate, item[2].ply))

    questions: list[dict[str, Any]] = []
    motif_counts: Counter[str] = Counter()
    for _priority, game, pos in candidates:
        if len(questions) >= target:
            break
        pos_key = _short_hash({"fen": pos.fen, "side": pos.side}, length=18)
        if pos_key in used_positions:
            continue
        status = _audit_move(
            engine,
            pos.fen,
            pos.move_uci,
            limit=limit,
            multipv=int(args.multipv),
            accept_topk=int(args.accept_topk),
            clean_cp_loss=int(args.clean_cp_loss),
            review_cp_loss=int(args.review_cp_loss),
        )
        if status.get("status") != "clean":
            continue
        used_positions.add(pos_key)
        for motif in pos.motifs:
            motif_counts[motif] += 1
        questions.append(
            _question_from_positions(
                section="human_probe_trap",
                ordinal=len(questions) + 1,
                game=game,
                positions=[pos],
                source_statuses=[status],
            )
        )
        _progress(f"accepted human_probe_trap: {len(questions)}/{target}")
    return questions


def _pick_complete_game_questions(
    *,
    games: list[SourceGame],
    used: set[tuple[str, str]],
    engine: stockfish_teacher.UciStockfish,
    limit: dict[str, int],
    args: argparse.Namespace,
    target: int,
) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    sample_cap = max(8, int(args.complete_source_audit_positions or 24))
    for game in games:
        if len(questions) >= target:
            break
        if len(game.positions) < int(args.min_complete_plies):
            continue
        key = ("complete_game", game.replay_id)
        if key in used:
            continue
        step = max(1, len(game.positions) // sample_cap)
        sampled = list(game.positions[::step])[:sample_cap]
        if game.positions[-1] not in sampled:
            sampled.append(game.positions[-1])
        statuses = [
            _audit_move(
                engine,
                pos.fen,
                pos.move_uci,
                limit=limit,
                multipv=int(args.multipv),
                accept_topk=int(args.accept_topk),
                clean_cp_loss=int(args.clean_cp_loss),
                review_cp_loss=int(args.review_cp_loss),
            )
            for pos in sampled
        ]
        if not _segment_quality(statuses, min_clean_rate=float(args.min_complete_clean_rate), max_rejected=int(args.max_complete_source_rejected)):
            continue
        positions = list(game.positions)
        if int(args.complete_max_positions or 0) > 0:
            positions = positions[: int(args.complete_max_positions)]
        used.add(key)
        questions.append(
            _question_from_positions(
                section="complete_game",
                ordinal=len(questions) + 1,
                game=game,
                positions=positions,
                source_statuses=statuses,
            )
        )
        _progress(f"accepted complete_game: {len(questions)}/{target}")
    return questions


def build_question_set(args: argparse.Namespace) -> int:
    input_paths = [Path(item).expanduser().resolve() for item in args.input_replay_jsonl]
    games = _parse_source_games(input_paths)
    if not games:
        raise SystemExit("no source games found")
    rng = random.Random(int(args.seed))
    rng.shuffle(games)
    games.sort(key=lambda game: (-game.rating_estimate, rng.random()))
    _progress(f"source games parsed: {len(games)}")

    stockfish_path = stockfish_teacher.resolve_stockfish_path(str(args.stockfish_path or ""))
    if not stockfish_path or not Path(stockfish_path).exists():
        raise SystemExit("Stockfish binary not found; pass --stockfish-path or set STOCKFISH_PATH")
    limit = stockfish_teacher.analysis_limit(depth=int(args.depth or 0), movetime_ms=int(args.movetime_ms or 0))
    target = int(args.target_per_section)
    if str(args.section_plan) == "legacy":
        expected_sections = LEGACY_SECTIONS
    else:
        expected_sections = tuple(f"tail{int(percent)}pct" for percent in args.tail_percent) + ("complete_game",)
    used_game_sections: set[tuple[str, str]] = set()
    used_positions: set[str] = set()
    all_questions: list[dict[str, Any]] = []

    with stockfish_teacher.UciStockfish(stockfish_path) as engine:
        if str(args.section_plan) == "legacy":
            all_questions.extend(
                _pick_tail_questions(
                    section="tail10",
                    tail_len=10,
                    games=games,
                    used=used_game_sections,
                    engine=engine,
                    limit=limit,
                    args=args,
                    target=target,
                )
            )
            all_questions.extend(
                _pick_tail_questions(
                    section="tail20",
                    tail_len=20,
                    games=games,
                    used=used_game_sections,
                    engine=engine,
                    limit=limit,
                    args=args,
                    target=target,
                )
            )
            all_questions.extend(
                _pick_human_probe_trap_questions(
                    games=games,
                    used_positions=used_positions,
                    engine=engine,
                    limit=limit,
                    args=args,
                    target=target,
                )
            )
        else:
            for percent in args.tail_percent:
                all_questions.extend(
                    _pick_tail_percent_questions(
                        percent=int(percent),
                        games=games,
                        used=used_game_sections,
                        engine=engine,
                        limit=limit,
                        args=args,
                        target=target,
                    )
                )
        all_questions.extend(
            _pick_complete_game_questions(
                games=games,
                used=used_game_sections,
                engine=engine,
                limit=limit,
                args=args,
                target=target,
            )
        )

    by_section = Counter(str(question.get("section")) for question in all_questions)
    complete = all(by_section.get(section, 0) >= target for section in expected_sections)
    question_set = {
        "created_at": _now(),
        "script": "scripts/games/chess_exp5_expanded_validation.py",
        "kind": "private_exp5_expanded_100_question_set",
        "leak_policy": "private runtime only; do not commit; do not copy FEN/move/teacher details into docs",
        "source_replay_jsonl": [str(path) for path in input_paths],
        "teacher": {
            "backend": "stockfish_uci",
            "alias": "blockfish_teacher",
            "path": stockfish_path,
            "reference": stockfish_teacher.stockfish_reference(stockfish_path),
            "limit": limit,
            "multipv": int(args.multipv),
        },
        "target_per_section": target,
        "section_plan": str(args.section_plan),
        "sections": list(expected_sections),
        "complete": complete,
        "counts_by_section": dict(by_section),
        "source_games_parsed": len(games),
        "questions": all_questions,
    }
    output_path = Path(args.output_question_set).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(question_set, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    redacted = _redacted_question_set_summary(question_set)
    if args.output_summary_json:
        summary_path = Path(args.output_summary_json).expanduser().resolve()
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(redacted, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(redacted, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if complete else 3


def _redacted_question_set_summary(question_set: dict[str, Any]) -> dict[str, Any]:
    questions = list(question_set.get("questions") or [])
    by_section: dict[str, dict[str, Any]] = {}
    sections = _ordered_sections(questions, question_set.get("sections") or [])
    for section in sections:
        items = [question for question in questions if question.get("section") == section]
        positions = [pos for question in items for pos in (question.get("positions") or []) if isinstance(pos, dict)]
        source_quality = [question.get("source_quality") or {} for question in items]
        by_section[section] = {
            "questions": len(items),
            "positions": len(positions),
            "avg_positions_per_question": round(len(positions) / max(1, len(items)), 3),
            "source_clean": sum(int(row.get("clean") or 0) for row in source_quality),
            "source_review": sum(int(row.get("review") or 0) for row in source_quality),
            "source_rejected": sum(int(row.get("rejected") or 0) for row in source_quality),
            "motifs": dict(Counter(motif for pos in positions for motif in (pos.get("motifs") or []))),
        }
    return {
        "created_at": question_set.get("created_at"),
        "script": question_set.get("script"),
        "kind": "redacted_exp5_expanded_100_question_set_summary",
        "complete": bool(question_set.get("complete")),
        "target_per_section": int(question_set.get("target_per_section") or 0),
        "section_plan": str(question_set.get("section_plan") or "legacy"),
        "sections": sections,
        "total_questions": len(questions),
        "counts_by_section": dict(Counter(str(question.get("section")) for question in questions)),
        "source_games_parsed": int(question_set.get("source_games_parsed") or 0),
        "teacher": {
            "backend": ((question_set.get("teacher") or {}).get("backend") or "stockfish_uci"),
            "alias": ((question_set.get("teacher") or {}).get("alias") or "blockfish_teacher"),
            "reference": ((question_set.get("teacher") or {}).get("reference") or ""),
            "limit": ((question_set.get("teacher") or {}).get("limit") or {}),
            "multipv": int(((question_set.get("teacher") or {}).get("multipv") or 0)),
        },
        "by_section": by_section,
        "leak_policy": "redacted: no FEN, moves, PV, source game ids, or per-position answers",
    }


def _evaluate_question(
    question: dict[str, Any],
    *,
    profile: str,
    engine: stockfish_teacher.UciStockfish,
    limit: dict[str, int],
    args: argparse.Namespace,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    detail_rows: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    rank_counts: Counter[str] = Counter()
    cp_losses: list[int] = []
    elapsed_total = 0.0
    positions = [pos for pos in (question.get("positions") or []) if isinstance(pos, dict)]
    for index, pos in enumerate(positions, start=1):
        fen = str(pos.get("fen") or "")
        try:
            board = chess.Board(fen)
        except Exception:
            status_counts["rejected"] += 1
            continue
        side = "white" if board.turn == chess.WHITE else "black"
        started = time.perf_counter()
        decision = choose_experiment_nnue_move(_board_state(board), side, search_profile=profile)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        elapsed_total += elapsed_ms
        chosen_uci = _move_from_decision(decision)
        audit = _audit_move(
            engine,
            board.fen(),
            chosen_uci,
            limit=limit,
            multipv=int(args.multipv),
            accept_topk=int(args.accept_topk),
            clean_cp_loss=int(args.clean_cp_loss),
            review_cp_loss=int(args.review_cp_loss),
        )
        status = str(audit.get("status") or "rejected")
        status_counts[status] += 1
        rank = audit.get("rank")
        if isinstance(rank, int):
            if rank <= 1:
                rank_counts["top1"] += 1
            if rank <= 3:
                rank_counts["top3"] += 1
            if rank <= 5:
                rank_counts["top5"] += 1
        if isinstance(audit.get("cp_loss"), int):
            cp_losses.append(int(audit["cp_loss"]))
        detail_rows.append(
            {
                "question_id": question.get("question_id"),
                "section": question.get("section"),
                "position_index": index,
                "fen": board.fen(),
                "side": side,
                "chosen_move": chosen_uci,
                "source_move": str(pos.get("source_move") or ""),
                "status": status,
                "teacher_rank": rank,
                "cp_loss": audit.get("cp_loss"),
                "chosen_eval_cp": audit.get("chosen_eval_cp"),
                "teacher_best_eval_cp": audit.get("best_eval_cp"),
                "elapsed_ms": round(elapsed_ms, 3),
                "motifs": list(pos.get("motifs") or []),
            }
        )
    total = len(positions)
    summary = {
        "question_index": 0,
        "section": str(question.get("section") or "unknown"),
        "positions": total,
        "clean": status_counts.get("clean", 0),
        "review": status_counts.get("review", 0),
        "rejected": status_counts.get("rejected", 0),
        "clean_rate": round(status_counts.get("clean", 0) / max(1, total), 4),
        "review_or_better_rate": round((status_counts.get("clean", 0) + status_counts.get("review", 0)) / max(1, total), 4),
        "top1": rank_counts.get("top1", 0),
        "top3": rank_counts.get("top3", 0),
        "top5": rank_counts.get("top5", 0),
        "top1_rate": round(rank_counts.get("top1", 0) / max(1, total), 4),
        "top3_rate": round(rank_counts.get("top3", 0) / max(1, total), 4),
        "top5_rate": round(rank_counts.get("top5", 0) / max(1, total), 4),
        "avg_cp_loss": round(sum(cp_losses) / max(1, len(cp_losses)), 3),
        "max_cp_loss": max(cp_losses or [None]),
        "avg_elapsed_ms": round(elapsed_total / max(1, total), 3),
    }
    return summary, detail_rows


def _aggregate_evaluation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_positions = sum(int(row.get("positions") or 0) for row in rows)
    total_clean = sum(int(row.get("clean") or 0) for row in rows)
    total_review = sum(int(row.get("review") or 0) for row in rows)
    total_rejected = sum(int(row.get("rejected") or 0) for row in rows)
    total_top1 = sum(int(row.get("top1") or 0) for row in rows)
    total_top3 = sum(int(row.get("top3") or 0) for row in rows)
    total_top5 = sum(int(row.get("top5") or 0) for row in rows)
    by_section: dict[str, dict[str, Any]] = {}
    for section in _ordered_sections(rows, []):
        items = [row for row in rows if row.get("section") == section]
        positions = sum(int(row.get("positions") or 0) for row in items)
        clean = sum(int(row.get("clean") or 0) for row in items)
        review = sum(int(row.get("review") or 0) for row in items)
        rejected = sum(int(row.get("rejected") or 0) for row in items)
        top1 = sum(int(row.get("top1") or 0) for row in items)
        top3 = sum(int(row.get("top3") or 0) for row in items)
        top5 = sum(int(row.get("top5") or 0) for row in items)
        weighted_cp = sum(float(row.get("avg_cp_loss") or 0.0) * int(row.get("positions") or 0) for row in items)
        weighted_elapsed = sum(float(row.get("avg_elapsed_ms") or 0.0) * int(row.get("positions") or 0) for row in items)
        by_section[section] = {
            "questions": len(items),
            "positions": positions,
            "clean": clean,
            "review": review,
            "rejected": rejected,
            "clean_rate": round(clean / max(1, positions), 4),
            "review_or_better_rate": round((clean + review) / max(1, positions), 4),
            "top1_rate": round(top1 / max(1, positions), 4),
            "top3_rate": round(top3 / max(1, positions), 4),
            "top5_rate": round(top5 / max(1, positions), 4),
            "avg_cp_loss": round(weighted_cp / max(1, positions), 3),
            "avg_elapsed_ms": round(weighted_elapsed / max(1, positions), 3),
        }
    return {
        "questions": len(rows),
        "positions": total_positions,
        "clean": total_clean,
        "review": total_review,
        "rejected": total_rejected,
        "clean_rate": round(total_clean / max(1, total_positions), 4),
        "review_or_better_rate": round((total_clean + total_review) / max(1, total_positions), 4),
        "top1_rate": round(total_top1 / max(1, total_positions), 4),
        "top3_rate": round(total_top3 / max(1, total_positions), 4),
        "top5_rate": round(total_top5 / max(1, total_positions), 4),
        "by_section": by_section,
    }


def evaluate_question_set(args: argparse.Namespace) -> int:
    question_path = Path(args.question_set).expanduser().resolve()
    payload = json.loads(question_path.read_text(encoding="utf-8"))
    questions = [question for question in (payload.get("questions") or []) if isinstance(question, dict)]
    if not questions:
        raise SystemExit("question set contains no questions")
    requested_sections = {str(item or "").strip() for item in (args.section or []) if str(item or "").strip()}
    if requested_sections:
        questions = [question for question in questions if str(question.get("section") or "") in requested_sections]
        if not questions:
            raise SystemExit(f"question set contains no questions for sections: {sorted(requested_sections)}")
    if int(args.questions or 0) > 0:
        questions = questions[: int(args.questions)]
    stockfish_path = stockfish_teacher.resolve_stockfish_path(str(args.stockfish_path or ""))
    if not stockfish_path or not Path(stockfish_path).exists():
        raise SystemExit("Stockfish binary not found; pass --stockfish-path or set STOCKFISH_PATH")
    limit = stockfish_teacher.analysis_limit(depth=int(args.depth or 0), movetime_ms=int(args.movetime_ms or 0))
    profile = str(args.profile or PROFILE_V24)
    summaries: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    with stockfish_teacher.UciStockfish(stockfish_path) as engine:
        for index, question in enumerate(questions, start=1):
            if index == 1 or index % 10 == 0 or index == len(questions):
                _progress(f"evaluating question {index}/{len(questions)}")
            summary, details = _evaluate_question(
                question,
                profile=profile,
                engine=engine,
                limit=limit,
                args=args,
            )
            summary["question_index"] = index
            summaries.append(summary)
            detail_rows.extend(details)

    aggregate = _aggregate_evaluation(summaries)
    report = {
        "created_at": _now(),
        "script": "scripts/games/chess_exp5_expanded_validation.py",
        "kind": "redacted_exp5_expanded_100_evaluation",
        "profile": profile,
        "question_set": "redacted",
        "section_plan": str(payload.get("section_plan") or "legacy"),
        "sections": list(payload.get("sections") or _ordered_sections(questions, [])),
        "question_count": len(questions),
        "teacher": {
            "backend": "stockfish_uci",
            "alias": "blockfish_teacher",
            "reference": stockfish_teacher.stockfish_reference(stockfish_path),
            "limit": limit,
            "multipv": int(args.multipv),
            "accept_topk": int(args.accept_topk),
            "clean_cp_loss": int(args.clean_cp_loss),
            "review_cp_loss": int(args.review_cp_loss),
        },
        "summary": aggregate,
        "per_question_redacted": summaries,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "leak_policy": "redacted: no FEN, moves, PV, source game ids, or teacher answers",
    }
    output_json = Path(args.output_json).expanduser().resolve()
    output_jsonl = Path(args.output_jsonl).expanduser().resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with output_jsonl.open("w", encoding="utf-8") as handle:
        for row in summaries:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    if args.private_detail_jsonl:
        detail_path = Path(args.private_detail_jsonl).expanduser().resolve()
        detail_path.parent.mkdir(parents=True, exist_ok=True)
        with detail_path.open("w", encoding="utf-8") as handle:
            for row in detail_rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        report["private_detail_jsonl"] = str(detail_path)
        output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output_json": str(output_json), "output_jsonl": str(output_jsonl), "summary": aggregate}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _add_common_teacher_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--stockfish-path", default="", help="External local Stockfish-compatible UCI binary.")
    parser.add_argument("--depth", type=int, default=6, help="Teacher depth.")
    parser.add_argument("--movetime-ms", type=int, default=0)
    parser.add_argument("--multipv", type=int, default=5)
    parser.add_argument("--accept-topk", type=int, default=3)
    parser.add_argument("--clean-cp-loss", type=int, default=60)
    parser.add_argument("--review-cp-loss", type=int, default=160)


def _ordered_sections(rows: list[dict[str, Any]], preferred: list[Any]) -> list[str]:
    out: list[str] = []
    for item in preferred:
        section = str(item or "").strip()
        if section and section not in out:
            out.append(section)
    for row in rows:
        section = str(row.get("section") or "").strip()
        if section and section not in out:
            out.append(section)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build/evaluate private exp5 expanded 100-scenario validation.")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="Build private question set from downloaded PGN replay rows.")
    build.add_argument("--input-replay-jsonl", action="append", required=True)
    build.add_argument("--output-question-set", default=str(DEFAULT_PRIVATE_ROOT / "v24_expanded_100_questions.json"))
    build.add_argument("--output-summary-json", default=str(ROOT / "docs/games/evidence/exp5/v24_expanded_100_question_set_summary.json"))
    build.add_argument("--target-per-section", type=int, default=25)
    build.add_argument("--section-plan", choices=["percent_tail", "legacy"], default="percent_tail")
    build.add_argument("--tail-percent", type=int, action="append", default=[], help="Tail percentage sections for --section-plan percent_tail. Defaults to 10,25,50.")
    build.add_argument("--seed", type=int, default=20260514)
    build.add_argument("--min-segment-clean-rate", type=float, default=0.75)
    build.add_argument("--min-complete-clean-rate", type=float, default=0.72)
    build.add_argument("--max-complete-source-rejected", type=int, default=1)
    build.add_argument("--complete-source-audit-positions", type=int, default=24)
    build.add_argument("--complete-max-positions", type=int, default=0, help="0 means keep all positions in complete-game questions.")
    build.add_argument("--min-complete-plies", type=int, default=40)
    _add_common_teacher_args(build)

    evaluate = sub.add_parser("evaluate", help="Evaluate exp5 against a private question set.")
    evaluate.add_argument("--question-set", default=str(DEFAULT_PRIVATE_ROOT / "v24_expanded_100_questions.json"))
    evaluate.add_argument("--profile", default=PROFILE_V24)
    evaluate.add_argument("--section", action="append", default=[], help="Evaluate only matching question sections. May be repeated.")
    evaluate.add_argument("--questions", type=int, default=0)
    evaluate.add_argument("--output-json", default=str(ROOT / "docs/games/evidence/exp5/v24_expanded_100_evaluation.json"))
    evaluate.add_argument("--output-jsonl", default=str(ROOT / "docs/games/evidence/exp5/v24_expanded_100_evaluation.jsonl"))
    evaluate.add_argument("--private-detail-jsonl", default=str(DEFAULT_PRIVATE_ROOT / "v24_expanded_100_eval_detail.jsonl"))
    _add_common_teacher_args(evaluate)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if getattr(args, "section_plan", "") == "percent_tail" and not getattr(args, "tail_percent", None):
        args.tail_percent = [10, 25, 50]
    if args.command == "build":
        return build_question_set(args)
    if args.command == "evaluate":
        return evaluate_question_set(args)
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
