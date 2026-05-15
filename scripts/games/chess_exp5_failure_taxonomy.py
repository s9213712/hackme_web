#!/usr/bin/env python3
"""Redacted failure taxonomy for private exp5 validation detail rows."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import chess


PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize private exp5 validation failures without leaking positions or moves.")
    parser.add_argument("--input-jsonl", required=True, help="Private detail JSONL from chess_exp5_expanded_validation.py evaluate.")
    parser.add_argument("--output-json", required=True, help="Redacted aggregate taxonomy JSON.")
    parser.add_argument("--report-md", default="", help="Optional redacted markdown report.")
    parser.add_argument("--focus-status", action="append", default=["rejected"], help="Status to classify. Repeatable.")
    return parser.parse_args()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _piece_value(piece: chess.Piece | None) -> int:
    if piece is None:
        return 0
    return PIECE_VALUES.get(piece.piece_type, 0)


def _material_margin(board: chess.Board, color: chess.Color) -> int:
    score = 0
    for square, piece in board.piece_map().items():
        value = _piece_value(piece)
        score += value if piece.color == color else -value
    return score


def _is_passed_pawn(board: chess.Board, square: chess.Square, color: chess.Color) -> bool:
    file_idx = chess.square_file(square)
    rank_idx = chess.square_rank(square)
    enemy = not color
    files = [file for file in (file_idx - 1, file_idx, file_idx + 1) if 0 <= file <= 7]
    ranks = range(rank_idx + 1, 8) if color == chess.WHITE else range(rank_idx - 1, -1, -1)
    for file in files:
        for rank in ranks:
            piece = board.piece_at(chess.square(file, rank))
            if piece and piece.color == enemy and piece.piece_type == chess.PAWN:
                return False
    return True


def _has_advanced_passed_pawn(board: chess.Board, color: chess.Color) -> bool:
    for square in board.pieces(chess.PAWN, color):
        rank = chess.square_rank(square)
        if not _is_passed_pawn(board, square, color):
            continue
        if color == chess.WHITE and rank >= 4:
            return True
        if color == chess.BLACK and rank <= 3:
            return True
    return False


def _promotion_distance(square: chess.Square, color: chess.Color) -> int:
    rank = chess.square_rank(square)
    return 7 - rank if color == chess.WHITE else rank


def _near_promotion(board: chess.Board, color: chess.Color) -> bool:
    return any(_promotion_distance(square, color) <= 2 for square in board.pieces(chess.PAWN, color))


def _king_distance_to_pawns(board: chess.Board, color: chess.Color) -> int | None:
    king = board.king(color)
    if king is None:
        return None
    enemy_pawns = list(board.pieces(chess.PAWN, not color))
    own_pawns = list(board.pieces(chess.PAWN, color))
    targets = enemy_pawns + own_pawns
    if not targets:
        return None
    return min(chess.square_distance(king, square) for square in targets)


def _move_hanging_penalty(board: chess.Board, move: chess.Move) -> int:
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type == chess.KING:
        return 0
    after = board.copy(stack=False)
    after.push(move)
    moved_piece = after.piece_at(move.to_square)
    if moved_piece is None:
        return 0
    attacked = after.is_attacked_by(not piece.color, move.to_square)
    defended = after.is_attacked_by(piece.color, move.to_square)
    if attacked and not defended:
        return _piece_value(moved_piece)
    return 0


def _king_zone_pressure(board: chess.Board, color: chess.Color) -> int:
    king = board.king(color)
    if king is None:
        return 0
    pressure = 0
    for square in chess.SquareSet(chess.BB_KING_ATTACKS[king] | chess.BB_SQUARES[king]):
        pressure += 1 if board.is_attacked_by(not color, square) else 0
    return pressure


def _open_file_near_king(board: chess.Board, color: chess.Color) -> bool:
    king = board.king(color)
    if king is None:
        return False
    king_file = chess.square_file(king)
    for file in (king_file - 1, king_file, king_file + 1):
        if not 0 <= file <= 7:
            continue
        has_pawn = any(board.piece_at(chess.square(file, rank)) and board.piece_at(chess.square(file, rank)).piece_type == chess.PAWN for rank in range(8))
        if not has_pawn:
            return True
    return False


def _classify(row: dict[str, Any]) -> list[str]:
    motifs = set(str(item) for item in (row.get("motifs") or []))
    labels: list[str] = []
    try:
        board = chess.Board(str(row.get("fen") or ""))
        chosen = chess.Move.from_uci(str(row.get("chosen_move") or ""))
    except Exception:
        return ["invalid_or_unparseable"]
    color = board.turn
    piece_count = len(board.piece_map())
    material = _material_margin(board, color)
    moved_piece = board.piece_at(chosen.from_square)

    if piece_count <= 10 or "endgame" in motifs:
        labels.append("endgame_conversion")
    if _has_advanced_passed_pawn(board, color) or _near_promotion(board, color) or "promotion" in motifs:
        labels.append("passed_pawn_or_promotion_race")
    king_distance = _king_distance_to_pawns(board, color)
    if piece_count <= 12 and king_distance is not None and king_distance >= 4:
        labels.append("king_distance_or_activity")
    if _move_hanging_penalty(board, chosen) >= PIECE_VALUES[chess.BISHOP]:
        labels.append("hanging_material_after_move")
    if "tactical_exposure" in motifs or "check" in motifs:
        labels.append("tactical_exposure")
    if _king_zone_pressure(board, color) >= 4 or _open_file_near_king(board, color):
        labels.append("king_safety_open_file")
    if moved_piece and moved_piece.piece_type == chess.PAWN and "capture" not in motifs:
        labels.append("pawn_structure_or_pawn_push")
    if not {"capture", "check", "promotion", "en_passant", "castling"}.intersection(motifs):
        labels.append("quiet_positional_ordering")
    rank = row.get("teacher_rank")
    if isinstance(rank, int) and rank <= 5:
        labels.append("top5_present_rerank_issue")
    elif row.get("status") == "rejected":
        labels.append("candidate_generation_or_search_miss")
    if material > 300 and "endgame_conversion" in labels:
        labels.append("winning_conversion")
    if not labels:
        labels.append("other")
    return sorted(set(labels))


def _row_phase(row: dict[str, Any]) -> str:
    try:
        board = chess.Board(str(row.get("fen") or ""))
    except Exception:
        return "unknown"
    pieces = len(board.piece_map())
    if pieces <= 10:
        return "endgame"
    if pieces <= 20:
        return "late_middlegame"
    if board.ply() <= 20:
        return "opening"
    return "middlegame"


def _summarize(rows: list[dict[str, Any]], focus_statuses: set[str]) -> dict[str, Any]:
    by_section: dict[str, dict[str, Any]] = {}
    sections = sorted({str(row.get("section") or "unknown") for row in rows})
    for section in sections:
        section_rows = [row for row in rows if str(row.get("section") or "unknown") == section]
        focus_rows = [row for row in section_rows if str(row.get("status") or "") in focus_statuses]
        taxonomy: Counter[str] = Counter()
        actionability: Counter[str] = Counter()
        phase: Counter[str] = Counter()
        motifs: Counter[str] = Counter()
        cp_losses = [int(row["cp_loss"]) for row in focus_rows if isinstance(row.get("cp_loss"), int)]
        for row in focus_rows:
            labels = _classify(row)
            taxonomy.update(labels)
            phase[_row_phase(row)] += 1
            motifs.update(str(item) for item in (row.get("motifs") or []))
            rank = row.get("teacher_rank")
            status = str(row.get("status") or "")
            if isinstance(rank, int) and rank <= 5:
                actionability["top5_present_rerank_issue"] += 1
            elif status == "review":
                actionability["review_not_clean_lower_priority"] += 1
            else:
                actionability["candidate_generation_or_search_miss"] += 1
        by_section[section] = {
            "positions": len(section_rows),
            "focus_rows": len(focus_rows),
            "focus_rate": round(len(focus_rows) / max(1, len(section_rows)), 4),
            "avg_focus_cp_loss": round(sum(cp_losses) / max(1, len(cp_losses)), 3),
            "max_focus_cp_loss": max(cp_losses or [None]),
            "taxonomy": dict(taxonomy.most_common()),
            "actionability": dict(actionability.most_common()),
            "phase": dict(phase.most_common()),
            "motifs": dict(motifs.most_common()),
        }
    total_focus = sum(1 for row in rows if str(row.get("status") or "") in focus_statuses)
    return {
        "positions": len(rows),
        "focus_statuses": sorted(focus_statuses),
        "focus_rows": total_focus,
        "focus_rate": round(total_focus / max(1, len(rows)), 4),
        "by_section": by_section,
        "leak_policy": "redacted: no FEN, moves, PV, source game ids, chosen/source moves, or per-position answers",
    }


def _write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Exp5 Failure Taxonomy",
        "",
        f"- Generated: `{summary.get('created_at')}`",
        f"- Input: `{summary.get('input')}`",
        f"- Focus statuses: `{', '.join(summary.get('summary', {}).get('focus_statuses', []))}`",
        f"- Positions: `{summary.get('summary', {}).get('positions')}`",
        f"- Focus rows: `{summary.get('summary', {}).get('focus_rows')}`",
        f"- Focus rate: `{summary.get('summary', {}).get('focus_rate')}`",
        "",
        "公開報告只含 aggregate taxonomy，不含 FEN、走法、PV、source/chosen move 或逐題答案。",
        "",
        "## By Section",
        "",
        "| Section | Positions | Focus rows | Focus rate | Top taxonomy | Actionability |",
        "|---|---:|---:|---:|---|---|",
    ]
    for section, row in (summary.get("summary", {}).get("by_section") or {}).items():
        top_tax = ", ".join(f"{k}:{v}" for k, v in list((row.get("taxonomy") or {}).items())[:4])
        top_action = ", ".join(f"{k}:{v}" for k, v in list((row.get("actionability") or {}).items())[:3])
        lines.append(
            f"| `{section}` | {row.get('positions')} | {row.get('focus_rows')} | {row.get('focus_rate')} | {top_tax} | {top_action} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    input_path = Path(args.input_jsonl).expanduser().resolve()
    rows = _read_jsonl(input_path)
    focus_statuses = {str(item) for item in (args.focus_status or []) if str(item)}
    output = {
        "created_at": _now(),
        "script": "scripts/games/chess_exp5_failure_taxonomy.py",
        "input": "redacted_private_detail_jsonl",
        "summary": _summarize(rows, focus_statuses),
    }
    output_path = Path(args.output_json).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.report_md:
        _write_report(Path(args.report_md).expanduser().resolve(), output)
    print(json.dumps({"output_json": str(output_path), "summary": output["summary"]}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
