#!/usr/bin/env python3
"""Add self-play outcome anchors to exp5 distill rows.

This implements item 5 from the exp3 example1 analysis: give each per-FEN
distill row a secondary supervision signal that is NOT purely the
depth-3 static teacher's choice. Concretely:

For each distill row (fen + side), play K self-play games from that
position using the supplied NNUE model (default: the bundled exp5
baseline) until termination or a max-ply cap. Aggregate the per-game
outcomes (white-win / draw / black-win) and produce, for each row:

- `self_play_games_played`           (number of games actually played)
- `self_play_wld_from_side`          {"win": int, "draw": int, "loss": int} from `side`'s POV
- `self_play_outcome_win_rate`       (win / games_played)
- `self_play_outcome_loss_rate`
- `self_play_outcome_draw_rate`
- `self_play_outcome_anchor`         "win" | "loss" | "draw" | "inconclusive"
- `self_play_outcome_anchor_target`  +1 / -1 / 0 / null (training target signal)
- `self_play_outcome_confidence`     win_rate or loss_rate, whichever is the
                                     majority class (in [0, 1])

The anchor is `inconclusive` when no class reaches the `--majority-threshold`
(default 0.7) — this is per the example1 recommendation that rows where
self-play diverges should NOT be used as positive samples.

The script does NOT mutate the trainer; it enriches the distill JSONL
in-place (with --output-jsonl). The downstream dataset trainer can then
choose to (a) weight rows by `self_play_outcome_confidence`, or (b) drop
rows where the anchor disagrees with the teacher's choice, etc.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import random
import sys

import chess


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess_nnue import (  # noqa: E402
    choose_experiment_nnue_move,
    default_chess_nnue_model_path,
)


def _progress(msg: str) -> None:
    print(f"[chess-exp5-self-play-anchor] {msg}", file=sys.stderr, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add self-play outcome anchors to exp5 distill rows.")
    parser.add_argument("--input-jsonl", required=True, help="Distill JSONL to enrich.")
    parser.add_argument("--output-jsonl", required=True, help="Enriched distill JSONL output.")
    parser.add_argument("--audit-jsonl", default="", help="Optional per-row anchor audit JSONL.")
    parser.add_argument("--model-path", default="", help="NNUE model used for self-play (default: bundled exp5 baseline).")
    parser.add_argument("--games-per-row", type=int, default=2, help="Number of self-play games per distill row.")
    parser.add_argument("--max-plies", type=int, default=80, help="Per-game maximum ply count.")
    parser.add_argument("--search-profile", default="fixed_depth_fast", help="Search profile for self-play (cheap fixed-depth so K games are affordable).")
    parser.add_argument("--majority-threshold", type=float, default=0.7, help="Fraction of games a single class must reach to call the anchor non-inconclusive.")
    parser.add_argument("--seed", type=int, default=20260511, help="Base RNG seed for tie-breaks (not currently used; engine is deterministic).")
    parser.add_argument("--max-samples", type=int, default=0, help="Optional cap.")
    return parser.parse_args()


def _iter_jsonl(path: Path):
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception as exc:
            raise ValueError(f"{path}:{line_no}: {exc}") from exc
        if isinstance(payload, dict):
            yield payload


def _play_one_self_play(start_fen: str, model_path: Path, *, max_plies: int, search_profile: str) -> tuple[str, int, list[str]]:
    """Return (outcome, plies_played, move_list) where outcome ∈ {white,black,draw,timeout}."""
    try:
        board = chess.Board(start_fen)
    except Exception:
        return ("invalid_fen", 0, [])
    moves: list[str] = []
    for ply in range(max_plies):
        if board.is_game_over():
            break
        side = "white" if board.turn == chess.WHITE else "black"
        try:
            mv = choose_experiment_nnue_move({"__fen__": board.fen()}, side, model_path=model_path, search_profile=search_profile)
        except Exception:
            return ("engine_error", len(moves), moves)
        if not mv:
            break
        uci = f"{mv.get('from')}{mv.get('to')}{mv.get('promotion') or ''}".lower()
        try:
            move = board.parse_uci(uci)
        except Exception:
            return ("invalid_engine_move", len(moves), moves)
        if move not in board.legal_moves:
            return ("illegal_engine_move", len(moves), moves)
        board.push(move)
        moves.append(uci)
    if board.is_checkmate():
        # whoever's turn it is to move is mated -> opposite side won
        winner = "black" if board.turn == chess.WHITE else "white"
        return (winner, len(moves), moves)
    if board.is_stalemate() or board.is_insufficient_material() or board.can_claim_fifty_moves() or board.can_claim_threefold_repetition():
        return ("draw", len(moves), moves)
    return ("timeout", len(moves), moves)


def _enrich(row: dict, *, model_path: Path, games_per_row: int, max_plies: int, search_profile: str, majority_threshold: float) -> dict:
    side = str(row.get("side") or "white").strip().lower()
    fen = str(row.get("fen") or "").strip()
    if not fen or side not in {"white", "black"}:
        return dict(row, self_play_outcome_anchor="invalid_row", self_play_outcome_anchor_target=None)
    wins = losses = draws = others = 0
    game_outcomes: list[dict] = []
    games_played = 0
    # The engine is deterministic, so playing N games from the same FEN
    # under the same profile yields the same result N times. We still loop
    # for plumbing parity and to allow future stochasticity.
    for game_idx in range(max(1, int(games_per_row))):
        outcome, plies, moves = _play_one_self_play(fen, model_path, max_plies=max_plies, search_profile=search_profile)
        game_outcomes.append({"game_idx": game_idx, "outcome": outcome, "plies": plies, "first_8_moves": moves[:8]})
        games_played += 1
        if outcome == side:
            wins += 1
        elif outcome == ("black" if side == "white" else "white"):
            losses += 1
        elif outcome == "draw":
            draws += 1
        else:
            others += 1
    total = max(1, wins + losses + draws)  # exclude `others` from rate denom
    win_rate = round(wins / total, 4)
    loss_rate = round(losses / total, 4)
    draw_rate = round(draws / total, 4)

    anchor = "inconclusive"
    target = None
    confidence = 0.0
    if win_rate >= majority_threshold:
        anchor, target, confidence = "win", 1.0, win_rate
    elif loss_rate >= majority_threshold:
        anchor, target, confidence = "loss", -1.0, loss_rate
    elif draw_rate >= majority_threshold:
        anchor, target, confidence = "draw", 0.0, draw_rate

    out = dict(row)
    out["self_play_games_played"] = games_played
    out["self_play_wld_from_side"] = {"win": wins, "loss": losses, "draw": draws, "other": others}
    out["self_play_outcome_win_rate"] = win_rate
    out["self_play_outcome_loss_rate"] = loss_rate
    out["self_play_outcome_draw_rate"] = draw_rate
    out["self_play_outcome_anchor"] = anchor
    out["self_play_outcome_anchor_target"] = target
    out["self_play_outcome_confidence"] = round(confidence, 4)
    out["self_play_game_outcomes"] = game_outcomes
    return out


def main() -> int:
    args = parse_args()
    input_path = Path(args.input_jsonl).expanduser().resolve()
    output_path = Path(args.output_jsonl).expanduser().resolve()
    model_path = Path(args.model_path).expanduser().resolve() if args.model_path else default_chess_nnue_model_path()
    audit_path = Path(args.audit_jsonl).expanduser().resolve() if args.audit_jsonl else None
    _progress(f"input: {input_path}")
    _progress(f"output: {output_path}")
    _progress(f"model: {model_path}")
    _progress(f"games_per_row={args.games_per_row} max_plies={args.max_plies} search_profile={args.search_profile} majority_threshold={args.majority_threshold}")

    rows = list(_iter_jsonl(input_path))
    if args.max_samples and args.max_samples > 0:
        rows = rows[: int(args.max_samples)]
    summary = {
        "ok": True,
        "finished_at": datetime.utcnow().isoformat() + "Z",
        "input_path": str(input_path),
        "output_path": str(output_path),
        "model_path": str(model_path),
        "games_per_row": int(args.games_per_row),
        "max_plies": int(args.max_plies),
        "search_profile": str(args.search_profile),
        "majority_threshold": float(args.majority_threshold),
        "rows_in": len(rows),
        "rows_enriched": 0,
        "anchor_counts": {"win": 0, "loss": 0, "draw": 0, "inconclusive": 0, "invalid_row": 0},
    }

    audit_rows: list[dict] = []
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as out:
        for idx, row in enumerate(rows):
            enriched = _enrich(
                row,
                model_path=model_path,
                games_per_row=int(args.games_per_row),
                max_plies=int(args.max_plies),
                search_profile=str(args.search_profile),
                majority_threshold=float(args.majority_threshold),
            )
            out.write(json.dumps(enriched, ensure_ascii=False, sort_keys=True) + "\n")
            summary["rows_enriched"] += 1
            anc = str(enriched.get("self_play_outcome_anchor") or "invalid_row")
            summary["anchor_counts"][anc] = int(summary["anchor_counts"].get(anc, 0)) + 1
            if audit_path is not None:
                audit_rows.append({
                    "fen": enriched.get("fen"),
                    "side": enriched.get("side"),
                    "self_play_outcome_anchor": enriched.get("self_play_outcome_anchor"),
                    "self_play_outcome_anchor_target": enriched.get("self_play_outcome_anchor_target"),
                    "self_play_outcome_win_rate": enriched.get("self_play_outcome_win_rate"),
                    "self_play_outcome_loss_rate": enriched.get("self_play_outcome_loss_rate"),
                    "self_play_outcome_draw_rate": enriched.get("self_play_outcome_draw_rate"),
                    "self_play_outcome_confidence": enriched.get("self_play_outcome_confidence"),
                    "self_play_games_played": enriched.get("self_play_games_played"),
                })
            if (idx + 1) % 20 == 0:
                _progress(f"phase progress: {idx+1} / {len(rows)} enriched")
    if audit_path is not None:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("w", encoding="utf-8") as h:
            for r in audit_rows:
                h.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
        summary["audit_jsonl"] = str(audit_path)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _progress(f"FAIL: {exc}")
        raise
