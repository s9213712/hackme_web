#!/usr/bin/env python3
"""Summarize Exp5 draw outcomes without exposing positions or moves."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import chess


PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
}


def _load_games(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        games: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    games.append(json.loads(line))
        return games
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("games"), list):
        return payload["games"]
    if isinstance(payload, list):
        return payload
    raise ValueError(f"Unsupported game payload: {path}")


def _ai_color(game: dict[str, Any]) -> chess.Color | None:
    codex_color = str(game.get("codex_color", "")).lower()
    if codex_color == "white":
        return chess.BLACK
    if codex_color == "black":
        return chess.WHITE
    return None


def _material_cp(board: chess.Board, color: chess.Color) -> int:
    total = 0
    for piece_type, value in PIECE_VALUES.items():
        total += len(board.pieces(piece_type, color)) * value
        total -= len(board.pieces(piece_type, not color)) * value
    return total


def _bucket(value: int, limits: list[tuple[int, str]], fallback: str) -> str:
    for upper, name in limits:
        if value <= upper:
            return name
    return fallback


def _position_key_from_fen(fen: str) -> str:
    return " ".join(fen.split(" ")[:4])


def _summarize_game(game: dict[str, Any]) -> dict[str, Any]:
    ai = _ai_color(game)
    board = chess.Board(game["final_fen"])
    material = _material_cp(board, ai) if ai is not None else 0
    moves = list(game.get("moves") or [])
    ai_tail = [m for m in moves[-24:] if m.get("actor") == "ai"]
    tail_captures = sum(1 for m in ai_tail if m.get("decision", {}).get("captured"))
    tail_pawn_or_capture = sum(
        1
        for m in ai_tail
        if m.get("decision", {}).get("captured")
        or str(m.get("decision", {}).get("piece", "")).lower() == "p"
    )
    repeated_positions = Counter(
        _position_key_from_fen(str(m.get("fen_after", "")))
        for m in moves
        if m.get("fen_after")
    )
    max_repetition = max(repeated_positions.values() or [0])
    piece_count = sum(len(board.pieces(piece_type, chess.WHITE)) + len(board.pieces(piece_type, chess.BLACK)) for piece_type in PIECE_VALUES)
    return {
        "ai_material_cp": material,
        "ai_material_bucket": _bucket(
            material,
            [
                (-900, "ai_down_major_or_more"),
                (-300, "ai_down_minor_or_exchange"),
                (299, "near_equal"),
                (899, "ai_up_minor_or_exchange"),
            ],
            "ai_up_major_or_more",
        ),
        "piece_count_bucket": _bucket(
            piece_count,
            [(8, "low_piece_count"), (16, "medium_piece_count"), (24, "high_piece_count")],
            "very_high_piece_count",
        ),
        "plies_bucket": _bucket(
            int(game.get("plies") or 0),
            [(60, "short"), (100, "medium"), (160, "long")],
            "very_long",
        ),
        "halfmove_clock_bucket": _bucket(
            board.halfmove_clock,
            [(10, "fresh"), (30, "moderate"), (60, "high")],
            "very_high",
        ),
        "max_repetition": max_repetition,
        "tail_ai_moves": len(ai_tail),
        "tail_captures": tail_captures,
        "tail_pawn_or_capture": tail_pawn_or_capture,
        "reason": str(game.get("reason", "unknown")),
    }


def summarize(path: Path) -> dict[str, Any]:
    games = _load_games(path)
    draws = [game for game in games if game.get("result") == "draw"]
    draw_summaries = [_summarize_game(game) for game in draws if game.get("final_fen")]
    counts = {
        "games": len(games),
        "draws": len(draws),
        "draw_reasons": Counter(item["reason"] for item in draw_summaries),
        "ai_material_buckets": Counter(item["ai_material_bucket"] for item in draw_summaries),
        "piece_count_buckets": Counter(item["piece_count_bucket"] for item in draw_summaries),
        "plies_buckets": Counter(item["plies_bucket"] for item in draw_summaries),
        "halfmove_clock_buckets": Counter(item["halfmove_clock_bucket"] for item in draw_summaries),
        "max_repetition_buckets": Counter(str(item["max_repetition"]) for item in draw_summaries),
    }
    tail_ai_moves = sum(item["tail_ai_moves"] for item in draw_summaries)
    return {
        "source": str(path),
        "counts": {key: dict(value) if isinstance(value, Counter) else value for key, value in counts.items()},
        "averages": {
            "tail_capture_rate": round(sum(item["tail_captures"] for item in draw_summaries) / tail_ai_moves, 4)
            if tail_ai_moves
            else 0.0,
            "tail_pawn_or_capture_rate": round(
                sum(item["tail_pawn_or_capture"] for item in draw_summaries) / tail_ai_moves, 4
            )
            if tail_ai_moves
            else 0.0,
            "ai_material_cp": round(sum(item["ai_material_cp"] for item in draw_summaries) / len(draw_summaries), 2)
            if draw_summaries
            else 0.0,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()

    payload = summarize(args.input)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
