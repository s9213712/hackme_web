#!/usr/bin/env python3
"""Advanced non-saturated score for chess ``experiment 5:nnue``.

The legacy 40-point score is now saturated by exp5. This score deliberately
uses a higher ceiling and includes complete-game behavior, anti-repetition,
PGN exact-match signal, and runtime. It is not an external Elo, but it gives
future engine work room to improve without pretending that fixed probes alone
measure strength.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
EXP5 = "experiment 5:nnue"


def _load_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _score_probe_component(score_probe: dict[str, Any]) -> dict[str, Any]:
    row = (((score_probe.get("summary") or {}).get("score_row")) or {})
    fixed_rate = float(row.get("fixed_pass_rate") or 0.0)
    sparring_rate = float(row.get("sparring_score_rate") or 0.0)
    legacy_total = float(row.get("total_score") or 0.0)
    points = 10.0 * _clamp(fixed_rate) + 7.0 * _clamp(sparring_rate) + 3.0 * _clamp(legacy_total / 40.0)
    return {
        "name": "legacy_probe_stability",
        "max_points": 20.0,
        "points": round(points, 4),
        "inputs": {
            "legacy_total": legacy_total,
            "fixed_pass_rate": fixed_rate,
            "sparring_score_rate": sparring_rate,
        },
    }


def _tactical_component(tactical: dict[str, Any]) -> dict[str, Any]:
    summary = tactical.get("summary") or {}
    pass_rate = float(summary.get("pass_rate") or 0.0)
    pgn = summary.get("pgn_human_probe") or {}
    exact_rate = float(pgn.get("exact_reference_match_rate") or 0.0)
    pgn_pass = float(pgn.get("passed") or 0.0) / max(1.0, float(pgn.get("cases") or 0.0))
    # Passing non-blunder floors matters most, but exact reference agreement
    # keeps the score from saturating at "safe but not human-like".
    points = 16.0 * _clamp(pass_rate) + 6.0 * _clamp(pgn_pass) + 8.0 * _clamp(exact_rate / 0.55)
    return {
        "name": "large_tactical_suite",
        "max_points": 30.0,
        "points": round(points, 4),
        "inputs": {
            "cases": int(summary.get("cases") or 0),
            "pass_rate": pass_rate,
            "pgn_pass_rate": round(pgn_pass, 4),
            "pgn_exact_reference_match_rate": exact_rate,
            "pgn_exact_reference_target_for_full_credit": 0.55,
        },
    }


def _gauntlet_component(gauntlet: dict[str, Any]) -> dict[str, Any]:
    summary = gauntlet.get("summary") or {}
    games = max(1.0, float(summary.get("games") or 0.0))
    score_rate = float(summary.get("ai_score_rate") or 0.0)
    win_rate = float(summary.get("ai_win_rate") or (float(summary.get("ai_wins") or 0.0) / games))
    loss_rate = float(summary.get("loss_rate") or (float(summary.get("codex_wins") or 0.0) / games))
    threefold_rate = float(summary.get("threefold_rate") or 0.0)
    if not threefold_rate:
        threefold_rate = sum(1 for row in gauntlet.get("games") or [] if row.get("reason") == "threefold_repetition") / games
    complete_rate = float(summary.get("complete_game_rate") or 0.0)
    if not complete_rate:
        complete_rate = sum(1 for row in gauntlet.get("games") or [] if row.get("complete_game")) / games
    points = 18.0 * _clamp(score_rate)
    points += 14.0 * _clamp(win_rate / 0.85)
    points += 5.0 * _clamp(1.0 - loss_rate)
    points += 8.0 * _clamp(1.0 - threefold_rate)
    points += 5.0 * _clamp(complete_rate)
    return {
        "name": "complete_game_gauntlet",
        "max_points": 50.0,
        "points": round(points, 4),
        "inputs": {
            "games": int(summary.get("games") or 0),
            "ai_wins": int(summary.get("ai_wins") or 0),
            "draws": int(summary.get("draws") or 0),
            "codex_wins": int(summary.get("codex_wins") or 0),
            "ai_score_rate": score_rate,
            "ai_win_rate": round(win_rate, 4),
            "loss_rate": round(loss_rate, 4),
            "threefold_rate": round(threefold_rate, 4),
            "complete_game_rate": round(complete_rate, 4),
        },
    }


def _runtime_component(gauntlet: dict[str, Any]) -> dict[str, Any]:
    games = gauntlet.get("games") or []
    avg_elapsed = 0.0
    if games:
        avg_elapsed = sum(float(row.get("elapsed_ms") or 0.0) for row in games) / max(1, len(games))
    else:
        avg_elapsed = float(((gauntlet.get("summary") or {}).get("avg_elapsed_ms")) or 0.0)
    # Full credit below 8s/game in this Python reviewer gauntlet, decays to 0
    # at 45s/game.
    efficiency = 1.0 - _clamp((avg_elapsed - 8000.0) / 37000.0)
    return {
        "name": "runtime_efficiency",
        "max_points": 10.0,
        "points": round(10.0 * efficiency, 4),
        "inputs": {
            "avg_elapsed_ms_per_gauntlet_game": round(avg_elapsed, 3),
            "full_credit_ms": 8000,
            "zero_credit_ms": 45000,
        },
    }


def _grade(total: float) -> str:
    if total >= 90:
        return "advanced_engine_candidate"
    if total >= 78:
        return "strong_club_candidate"
    if total >= 65:
        return "club_level_candidate"
    if total >= 50:
        return "training_bot_plus"
    return "needs_core_engine_work"


def build_score(score_probe: dict[str, Any], tactical: dict[str, Any], gauntlet: dict[str, Any]) -> dict[str, Any]:
    components = [
        _score_probe_component(score_probe),
        _tactical_component(tactical),
        _gauntlet_component(gauntlet),
        _runtime_component(gauntlet),
    ]
    total = sum(float(component["points"]) for component in components)
    max_points = sum(float(component["max_points"]) for component in components)
    normalized = 100.0 * total / max(1.0, max_points)
    return {
        "engine": EXP5,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "score_name": "exp5_advanced_non_saturated_score_v1",
        "total_points": round(total, 4),
        "max_points": round(max_points, 4),
        "normalized_100": round(normalized, 4),
        "grade": _grade(normalized),
        "components": components,
        "interpretation": {
            "legacy_40_point_score": "saturated; retained only as stability gate",
            "main_current_ceiling": "complete-game gauntlet win rate, lower threefold rate, PGN exact-match signal, and runtime",
            "not_external_elo": True,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build advanced exp5 score from existing artifacts.")
    parser.add_argument("--score-probe", default=str(ROOT / "docs/games/2026-05-13_exp5_score_probe_see_extension.json"))
    parser.add_argument("--tactical-suite", default=str(ROOT / "docs/games/2026-05-13_exp5_tactical_suite_300_see_extension.json"))
    parser.add_argument("--gauntlet", default=str(ROOT / "docs/games/2026-05-13_exp5_gauntlet_see_extension.json"))
    parser.add_argument("--output", default=str(ROOT / "docs/games/2026-05-13_exp5_advanced_score.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact = build_score(
        _load_json(args.score_probe),
        _load_json(args.tactical_suite),
        _load_json(args.gauntlet),
    )
    artifact["inputs"] = {
        "score_probe": str(Path(args.score_probe)),
        "tactical_suite": str(Path(args.tactical_suite)),
        "gauntlet": str(Path(args.gauntlet)),
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
