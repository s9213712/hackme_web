#!/usr/bin/env python3
"""Targeted regression check for the experiment 5:nnue chess fix."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import chess


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.games.game_ai_codex_play_eval as codex_eval  # noqa: E402
from scripts.games.game_ai_strength_eval import run_fixed_suite  # noqa: E402
from services.games.chess_nnue import choose_experiment_nnue_move  # noqa: E402
from services.games.chess import FEN_KEY  # noqa: E402


EXP5 = "experiment 5:nnue"
BASELINE = ROOT / "docs" / "games" / "2026-05-13_game_ai_codex_play_eval.json"


def uci(move: dict | None) -> str:
    if not move:
        return ""
    return f"{move.get('from')}{move.get('to')}{move.get('promotion') or ''}"


def exp5_summary(rows: list[dict]) -> dict:
    exp5_rows = [row for row in rows if row.get("game_key") == "chess" and row.get("difficulty") == EXP5]
    return {
        "games": len(exp5_rows),
        "codex_wins": sum(1 for row in exp5_rows if row.get("result") == "codex_win"),
        "draws": sum(1 for row in exp5_rows if row.get("result") == "draw"),
        "ai_wins": sum(1 for row in exp5_rows if row.get("result") == "ai_win"),
        "reasons": sorted({str(row.get("reason") or "") for row in exp5_rows}),
        "avg_plies": round(sum(int(row.get("plies") or 0) for row in exp5_rows) / max(1, len(exp5_rows)), 2),
        "first_ai_san_sequences": [
            [move.get("san") for move in row.get("moves", []) if move.get("actor") == "ai"][:8]
            for row in exp5_rows
        ],
    }


def load_baseline(path: Path) -> dict:
    if not path.exists():
        return {"available": False, "path": str(path)}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "available": True,
        "path": str(path),
        "summary": exp5_summary(data.get("games") or []),
    }


def _profile_override_ai(profile: str):
    def choose_ai_chess_move(board: chess.Board, _difficulty: str, move_history: list[dict] | None = None) -> tuple[chess.Move | None, dict]:
        side = "white" if board.turn == chess.WHITE else "black"
        state = {chess.square_name(square): piece.symbol() for square, piece in board.piece_map().items()}
        state[FEN_KEY] = board.fen()
        if move_history is not None:
            state["__move_history__"] = [
                {
                    "from": str(item.get("uci") or "")[:2],
                    "to": str(item.get("uci") or "")[2:4],
                    "promotion": str(item.get("uci") or "")[4:] or None,
                }
                for item in move_history
                if len(str(item.get("uci") or "")) >= 4
            ]
        raw = choose_experiment_nnue_move(state, side, search_profile=profile)
        chosen = uci(raw)
        if not chosen:
            return None, {"uci": "", "profile": profile}
        return chess.Move.from_uci(chosen), {"uci": chosen, "profile": profile}

    return choose_ai_chess_move


def run_complete_games(seed: int, profile_override: str | None) -> list[dict]:
    original = codex_eval.choose_ai_chess_move
    if profile_override:
        codex_eval.choose_ai_chess_move = _profile_override_ai(profile_override)
    rows = []
    try:
        for game_no in range(1, 6):
            rows.append(codex_eval.play_chess_codex_game(
                EXP5,
                codex_color_name="white" if game_no % 2 == 1 else "black",
                seed=codex_eval.stable_seed(seed, "chess", EXP5, game_no),
                max_plies=None,
            ))
        return rows
    finally:
        codex_eval.choose_ai_chess_move = original


def run_spot_checks() -> list[dict]:
    cases = [
        {
            "id": "after_1_Nh3_black_should_develop",
            "fen": "rnbqkbnr/pppppppp/8/8/8/7N/PPPPPPPP/RNBQKB1R b KQkq - 1 1",
            "side": "black",
            "forbidden": ["a7a5", "a7a6", "h7h5", "h7h6"],
        },
        {
            "id": "block_low_value_rook_excursion",
            "fen": "rnbqkbnr/3pppBp/8/1N6/2p2P2/P6N/P1PPP1PP/R2QKB1R b KQkq - 0 7",
            "side": "black",
            "forbidden": ["a8a3"],
        },
        {
            "id": "block_direct_rook_hang",
            "fen": "1nbqkbnB/3ppp1p/8/1N6/2p2P2/r6N/P1PPP1PP/R2QKB1R b KQk - 0 8",
            "side": "black",
            "forbidden": ["a3h3"],
        },
    ]
    out = []
    for case in cases:
        move = choose_experiment_nnue_move({"__fen__": case["fen"]}, case["side"], search_profile="fixed_depth_fast")
        chosen = uci(move)
        out.append({
            **case,
            "chosen": chosen,
            "passed": bool(chosen) and chosen not in set(case["forbidden"]),
        })
    return out


def run_exp5_fixed_probes() -> dict:
    rows = [row for row in run_fixed_suite() if row["game_key"] == "chess" and row["difficulty"] == EXP5]
    return {
        "cases": len(rows),
        "passed": sum(1 for row in rows if row.get("passed")),
        "rows": [
            {
                "case_id": row["case_id"],
                "passed": bool(row.get("passed")),
                "actual_move": row.get("actual_move_label"),
                "correct_direction": row.get("correct_direction"),
            }
            for row in rows
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run targeted exp5 fix regression.")
    parser.add_argument("--seed", type=int, default=20260513)
    parser.add_argument("--baseline", default=str(BASELINE))
    parser.add_argument("--search-profile-override", choices=["fast", "balanced", "strong"], default="")
    parser.add_argument("--output", default=str(ROOT / "docs" / "games" / "2026-05-13_exp5_fix_regression.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profile_override = str(args.search_profile_override or "").strip() or None
    games = run_complete_games(int(args.seed), profile_override)
    artifact = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "engine": EXP5,
        "seed": int(args.seed),
        "search_profile_override": profile_override,
        "baseline": load_baseline(Path(args.baseline)),
        "current": {
            "summary": exp5_summary(games),
            "games": games,
        },
        "spot_checks": run_spot_checks(),
        "fixed_probes": run_exp5_fixed_probes(),
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
