#!/usr/bin/env python3
"""exp4 vs exp5 head-to-head diagnostic sparring (Phase 1 smoke).

Interactive runner: prompts for model paths and game mode, prints every ply
loudly (no silent failures), writes artifacts under --output-root.

DIAGNOSTIC ONLY — does not promote, does not shadow, does not touch the
production model. exp4 uses chess_pv `balanced` (time-budget, accepted variance
for smoke). exp5 uses `fixed_depth_strong` (deterministic).

Modes:
  - single   : one seed (pick interactively or via --seed-id)
  - castling : seeds 3+4 (kingside white+black)
  - tactic   : seeds 1,2,6 (mate-in-one × 2 + forced queen capture)
  - smoke    : all 6 baked-in seeds
  - custom   : interactively pick a subset
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import chess
import chess.pgn

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess_sparring_adapter import (  # noqa: E402
    compute_model_hash,
    decide_and_audit_exp4,
    decide_and_audit_exp5,
)


# ----- bundled smoke seeds (no external JSONL needed) ---------------------

SMOKE_SEEDS: list[dict] = [
    {
        "seed_id": "smoke_01_mate_in_one_white",
        "fen": "6k1/5Q2/6K1/8/8/8/8/8 w - - 0 1",
        "side_to_move": "white",
        "exp4_plays": "white",
        "cluster_tag": "tactic",
        "oracle_source": "python_chess_rule",
        "label_quality": "objective",
        "expected_move_any": ["f7e8", "f7f8"],
        "audit_rules": {"must_checkmate_in_one": True},
        "source_ref": "EXP5_STRENGTH_CASES.mate_in_one_white",
        "forced_fixture_win": True,
        "strength_counted": False,
        "color_mirror_group": "mate_in_one_kqk",
    },
    {
        "seed_id": "smoke_02_mate_in_one_black",
        "fen": "8/8/8/8/8/6k1/5q2/6K1 b - - 0 1",
        "side_to_move": "black",
        "exp4_plays": "black",
        "cluster_tag": "tactic",
        "oracle_source": "python_chess_rule",
        "label_quality": "objective",
        "expected_move_any": ["f2e1", "f2f1"],
        "audit_rules": {"must_checkmate_in_one": True},
        "source_ref": "EXP5_STRENGTH_CASES.mate_in_one_black",
        "forced_fixture_win": True,
        "strength_counted": False,
        "color_mirror_group": "mate_in_one_kqk",
    },
    {
        "seed_id": "smoke_03_castle_kingside_white",
        "fen": "r3k2r/pppq1ppp/2n2n2/2bpp3/2BPP3/2N2N2/PPPQ1PPP/R3K2R w KQkq - 0 1",
        "side_to_move": "white",
        "exp4_plays": "white",
        "cluster_tag": "special_rule",
        "oracle_source": "python_chess_rule",
        "label_quality": "objective",
        "expected_move_any": ["e1g1"],
        "audit_rules": {"expected_castle": True},
        "source_ref": "SPECIAL_RULE_CASES.castle_kingside_white",
        "forced_fixture_win": False,
        "strength_counted": True,
        "color_mirror_group": "castle_kingside_symmetric",
    },
    {
        "seed_id": "smoke_04_castle_kingside_black",
        "fen": "r3k2r/pppq1ppp/2n2n2/2bpp3/2BPP3/2N2N2/PPPQ1PPP/R3K2R b KQkq - 1 1",
        "side_to_move": "black",
        "exp4_plays": "black",
        "cluster_tag": "special_rule",
        "oracle_source": "python_chess_rule",
        "label_quality": "objective",
        "expected_move_any": ["e8g8"],
        "audit_rules": {"expected_castle": True},
        "source_ref": "SPECIAL_RULE_CASES.castle_kingside_black",
        "forced_fixture_win": False,
        "strength_counted": True,
        "color_mirror_group": "castle_kingside_symmetric",
    },
    {
        "seed_id": "smoke_05_promotion_to_queen_white",
        "fen": "k7/4P3/2K5/8/8/8/8/8 w - - 0 1",
        "side_to_move": "white",
        "exp4_plays": "white",
        "cluster_tag": "endgame",
        "oracle_source": "python_chess_rule",
        "label_quality": "objective",
        "expected_move_any": ["e7e8q"],
        "audit_rules": {"must_promote": True, "expected_promotion": "q"},
        "source_ref": "SPECIAL_RULE_CASES.promotion_to_queen_white",
        "forced_fixture_win": False,
        "strength_counted": True,
        "color_mirror_group": "promotion_to_queen_white_only",
    },
    {
        "seed_id": "smoke_06_forced_queen_capture_black",
        "fen": "4k3/4Q3/8/8/8/8/8/4K3 b - - 0 1",
        "side_to_move": "black",
        "exp4_plays": "black",
        "cluster_tag": "tactic",
        "oracle_source": "python_chess_rule",
        "label_quality": "objective",
        "expected_move_any": ["e8e7"],
        "audit_rules": {"requires_capture": True, "min_material_gain": 800},
        "source_ref": "EXP5_STRENGTH_CASES.forced_queen_capture",
        "forced_fixture_win": True,
        "strength_counted": False,
        "color_mirror_group": "forced_queen_capture_black_only",
    },
]

MODE_PRESETS = {
    "single": [0],  # default; overridden by --seed-id / interactive picker
    "castling": [2, 3],
    "tactic": [0, 1, 5],
    "smoke": [0, 1, 2, 3, 4, 5],
}

EXP4_KNOWN_CANDIDATES: list[tuple[str, str]] = [
    (
        "bundled_production",
        "/home/s92137/hackme_web/services/games/models/chess_experiment_4_pv.json",
    ),
    (
        "exp4_14_checkpoint_10",
        "/home/s92137/chess_results/exp4_14_balanced_curriculum/exp4/checkpoints/10/exp4_quick_candidate_model.json",
    ),
    (
        "exp4_14_final_model_checkpoint_20",
        "/home/s92137/chess_results/exp4_14_balanced_curriculum/exp4/checkpoints/20/exp4_quick_candidate_model.json",
    ),
]

EXP5_KNOWN_CANDIDATES: list[tuple[str, str]] = [
    (
        "bundled_production",
        "/home/s92137/hackme_web/services/games/models/chess_experiment_5_nnue.json",
    ),
    (
        "exp5_08_stage_candidate",
        "/home/s92137/chess_results/exp5_08_stage_candidate/chess_experiment_5_nnue_stage_candidate.json",
    ),
]


# ----- I/O helpers --------------------------------------------------------


def _say(msg: str) -> None:
    """Loud stdout, line-flushed."""
    print(msg, flush=True)


def _warn(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr, flush=True)


def _err(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr, flush=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _timestamp_dirname() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _other_side(side: str) -> str:
    return "black" if side == "white" else "white"


# ----- interactive prompts -----------------------------------------------


def _prompt(message: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    try:
        raw = input(f"{message}{suffix}> ").strip()
    except EOFError:
        raw = ""
    if not raw and default is not None:
        return default
    return raw


def _select_model(label: str, candidates: list[tuple[str, str]]) -> Path:
    _say("")
    _say(f"=== select {label} model ===")
    existing = []
    for name, path_str in candidates:
        path = Path(path_str)
        if path.exists():
            try:
                size_kb = path.stat().st_size // 1024
            except Exception:
                size_kb = -1
            existing.append((name, path, size_kb))
    for idx, (name, path, size_kb) in enumerate(existing, start=1):
        _say(f"  [{idx}] {name}  ({size_kb} KB)  {path}")
    next_idx = len(existing) + 1
    _say(f"  [{next_idx}] (other) — paste a path")
    choice = _prompt(f"choose 1..{next_idx}", default="1")
    try:
        idx = int(choice)
    except ValueError:
        idx = 1
    if 1 <= idx <= len(existing):
        return existing[idx - 1][1]
    raw = _prompt(f"paste {label} model JSON path")
    path = Path(raw).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"path does not exist: {path}")
    return path


def _select_mode_and_seeds() -> tuple[str, list[int]]:
    _say("")
    _say("=== select game mode ===")
    _say("  [1] single   — one seed (you'll pick which)")
    _say("  [2] castling — 2 games (kingside white + black)")
    _say("  [3] tactic   — 3 games (mate_in_one ×2 + forced queen capture)")
    _say("  [4] smoke    — all 6 baked-in seeds")
    _say("  [5] custom   — pick a subset by number")
    choice = _prompt("choose 1..5", default="1")
    mode_map = {"1": "single", "2": "castling", "3": "tactic", "4": "smoke", "5": "custom"}
    mode = mode_map.get(choice, "single")
    if mode in ("castling", "tactic", "smoke"):
        return mode, list(MODE_PRESETS[mode])
    if mode == "single":
        _say("")
        for idx, seed in enumerate(SMOKE_SEEDS, start=1):
            _say(f"  [{idx}] {seed['seed_id']}  (cluster={seed['cluster_tag']}, exp4={seed['exp4_plays']})")
        pick = _prompt(f"choose seed 1..{len(SMOKE_SEEDS)}", default="1")
        try:
            i = max(1, min(len(SMOKE_SEEDS), int(pick)))
        except ValueError:
            i = 1
        return "single", [i - 1]
    _say("")
    for idx, seed in enumerate(SMOKE_SEEDS, start=1):
        _say(f"  [{idx}] {seed['seed_id']}")
    raw = _prompt("enter seed numbers comma-separated (e.g. 1,3,5)", default="1,2")
    indices = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            i = int(token)
            if 1 <= i <= len(SMOKE_SEEDS):
                indices.append(i - 1)
        except ValueError:
            continue
    if not indices:
        indices = [0]
    return "custom", indices


# ----- per-ply pretty print ----------------------------------------------


def _print_ply(seed_id: str, decision: dict, ply_index: int) -> None:
    engine = decision.get("engine_id", "?")
    side = decision.get("side", "?")
    move = decision.get("move") or "<empty>"
    legal = decision.get("legal")
    reason = decision.get("decision_reason") or "<unknown>"
    special = decision.get("special_rule_tag") or ""
    audit_err = decision.get("audit_error", False)
    audit_msg = decision.get("audit_error_message", "")
    _say(
        f"  [{seed_id} ply={ply_index} side={side} engine={engine}] "
        f"move={move} legal={legal} reason={reason} special={special}"
    )
    if audit_err:
        _warn(
            f"[{seed_id} ply={ply_index} engine={engine}] audit FAILED (loop continues): {audit_msg}"
        )
    flags = decision.get("audit_flags") or {}
    if flags and not audit_err:
        compact = {
            k: v
            for k, v in flags.items()
            if v is not None and v != "" and v != [] and v != {}
        }
        if compact:
            _say(f"    audit_flags: {json.dumps(compact, sort_keys=True)}")


# ----- core sparring ------------------------------------------------------


def play_one_game(
    seed: dict,
    *,
    exp4_path: Path,
    exp4_hash: str,
    exp5_path: Path,
    exp5_hash: str,
    max_plies: int,
    profile_exp4: str,
    profile_exp5: str,
    enable_audit: bool,
    audit_max_plies: int,
) -> dict:
    fen = seed["fen"]
    board = chess.Board(fen)
    exp4_color = seed["exp4_plays"]
    exp5_color = _other_side(exp4_color)

    ply_records: list[dict] = []
    illegal_count = 0
    audit_success = {"exp4": 0, "exp5": 0}
    audit_error = {"exp4": 0, "exp5": 0}
    audit_attempted = {"exp4": 0, "exp5": 0}
    final_outcome: str | None = None
    result_reason = "max_plies_hit"

    _say("")
    _say(
        f"=== START {seed['seed_id']} | cluster={seed['cluster_tag']} | "
        f"exp4={exp4_color} exp5={exp5_color} | start_fen={fen} ==="
    )

    plies_played = 0
    while plies_played < max_plies:
        if board.is_game_over(claim_draw=True):
            outcome = board.outcome(claim_draw=True)
            if outcome:
                term = outcome.termination.name.lower()
                if outcome.winner is None:
                    final_outcome = "draw"
                    result_reason = term
                else:
                    winner_side = "white" if outcome.winner else "black"
                    final_outcome = "exp4_win" if winner_side == exp4_color else "exp5_win"
                    result_reason = term
            break

        current_side = "white" if board.turn == chess.WHITE else "black"
        engine = "exp4" if current_side == exp4_color else "exp5"
        do_audit = enable_audit and (audit_max_plies <= 0 or plies_played < audit_max_plies)
        if do_audit:
            audit_attempted[engine] += 1

        current_fen = board.fen()
        try:
            if engine == "exp4":
                decision = decide_and_audit_exp4(
                    current_fen,
                    current_side,
                    model_path=exp4_path,
                    model_hash=exp4_hash,
                    search_profile=profile_exp4,
                    enable_audit=do_audit,
                )
            else:
                decision = decide_and_audit_exp5(
                    current_fen,
                    current_side,
                    model_path=exp5_path,
                    model_hash=exp5_hash,
                    search_profile=profile_exp5,
                    enable_audit=do_audit,
                )
        except Exception as exc:
            _err(
                f"[{seed['seed_id']} ply={plies_played} engine={engine}] adapter raised; aborting game"
            )
            traceback.print_exc()
            decision = {
                "engine_id": engine,
                "model_path": str(exp4_path if engine == "exp4" else exp5_path),
                "model_hash": exp4_hash if engine == "exp4" else exp5_hash,
                "fen_before": current_fen,
                "side": current_side,
                "move": "",
                "legal": False,
                "raw_policy_top1": None,
                "raw_policy_top3": [],
                "search_best_move": None,
                "search_score": None,
                "final_score": None,
                "decision_reason": f"adapter_raised:{exc!r}",
                "special_rule_tag": None,
                "audit_flags": {},
                "audit_error": True,
                "audit_error_message": f"adapter_raised:{exc!r}",
            }

        decision["ply"] = plies_played
        decision["fullmove_number"] = board.fullmove_number
        ply_records.append(decision)
        _print_ply(seed["seed_id"], decision, plies_played)

        if decision.get("audit_error"):
            audit_error[engine] += 1
        elif do_audit:
            audit_success[engine] += 1

        move_uci = decision.get("move") or ""
        if not move_uci or not decision.get("legal"):
            illegal_count += 1
            final_outcome = f"illegal_{engine}"
            result_reason = decision.get("decision_reason") or f"illegal_move_by_{engine}"
            _err(
                f"[{seed['seed_id']} ply={plies_played} engine={engine}] illegal/empty move; "
                f"aborting game (move={move_uci!r}, reason={result_reason})"
            )
            break

        try:
            mv = board.parse_uci(move_uci)
            board.push(mv)
        except Exception as exc:
            illegal_count += 1
            final_outcome = f"illegal_{engine}"
            result_reason = f"push_failed_{engine}:{exc!r}"
            _err(
                f"[{seed['seed_id']} ply={plies_played} engine={engine}] push failed: {exc!r}"
            )
            break

        plies_played += 1

    if final_outcome is None:
        final_outcome = "draw"
        result_reason = "max_plies_hit"

    game = chess.pgn.Game()
    game.setup(chess.Board(seed["fen"]))
    game.headers["Event"] = "exp4_vs_exp5_sparring_phase1_smoke"
    game.headers["Site"] = "hackme_web"
    game.headers["Date"] = datetime.now(timezone.utc).strftime("%Y.%m.%d")
    game.headers["Round"] = seed["seed_id"]
    game.headers["White"] = "exp4" if exp4_color == "white" else "exp5"
    game.headers["Black"] = "exp4" if exp4_color == "black" else "exp5"
    if final_outcome == "draw":
        game.headers["Result"] = "1/2-1/2"
    elif final_outcome.startswith("illegal"):
        game.headers["Result"] = "*"
    elif final_outcome == "exp4_win":
        game.headers["Result"] = "1-0" if exp4_color == "white" else "0-1"
    elif final_outcome == "exp5_win":
        game.headers["Result"] = "1-0" if exp5_color == "white" else "0-1"

    pgn_board = chess.Board(seed["fen"])
    node = game
    for record in ply_records:
        try:
            mv = pgn_board.parse_uci(record["move"])
            node = node.add_variation(mv)
            pgn_board.push(mv)
        except Exception:
            break

    audit_coverage = {}
    for k in ("exp4", "exp5"):
        total = audit_success[k] + audit_error[k]
        audit_coverage[k] = (audit_success[k] / total) if total else None

    _say(
        f"=== END {seed['seed_id']} | outcome={final_outcome} | reason={result_reason} | "
        f"plies={len(ply_records)} | illegal={illegal_count} | "
        f"audit_ok_exp4={audit_success['exp4']} audit_err_exp4={audit_error['exp4']} | "
        f"audit_ok_exp5={audit_success['exp5']} audit_err_exp5={audit_error['exp5']}"
    )

    first_move_match_expected = (
        ply_records[0].get("move") in (seed.get("expected_move_any") or [])
        if ply_records
        else False
    )

    return {
        "seed_id": seed["seed_id"],
        "cluster_tag": seed["cluster_tag"],
        "oracle_source": seed["oracle_source"],
        "label_quality": seed["label_quality"],
        "source_ref": seed["source_ref"],
        "forced_fixture_win": bool(seed.get("forced_fixture_win")),
        "strength_counted": bool(seed.get("strength_counted")),
        "color_mirror_group": str(seed.get("color_mirror_group") or ""),
        "start_fen": seed["fen"],
        "side_to_move": seed["side_to_move"],
        "exp4_color": exp4_color,
        "exp5_color": exp5_color,
        "outcome": final_outcome,
        "result_reason": result_reason,
        "plies": len(ply_records),
        "illegal_count": illegal_count,
        "audit_success_count": audit_success,
        "audit_error_count": audit_error,
        "audit_attempted_count": audit_attempted,
        "audit_coverage_rate": audit_coverage,
        "expected_move_any": seed.get("expected_move_any") or [],
        "first_move_match_expected": first_move_match_expected,
        "ply_records": ply_records,
        "pgn": str(game),
    }


# ----- artifact writing ---------------------------------------------------


def _suspicious_record(record: dict) -> bool:
    if not record.get("legal"):
        return True
    if record.get("audit_error"):
        return True
    return False


def write_artifacts(out_dir: Path, game_reports: list[dict], meta: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pgn_dir = out_dir / "pgn"
    pgn_dir.mkdir(exist_ok=True)

    with (out_dir / "games.jsonl").open("w", encoding="utf-8") as fh:
        for g in game_reports:
            row = {k: v for k, v in g.items() if k not in ("ply_records", "pgn")}
            fh.write(json.dumps(row, sort_keys=True) + "\n")

    with (out_dir / "moves.jsonl").open("w", encoding="utf-8") as fh:
        for g in game_reports:
            for record in g["ply_records"]:
                row = {**record, "seed_id": g["seed_id"]}
                fh.write(json.dumps(row, sort_keys=True) + "\n")

    for g in game_reports:
        (pgn_dir / f"{g['seed_id']}.pgn").write_text(g["pgn"], encoding="utf-8")

    raw_outcome = {
        "exp4_win": 0,
        "exp5_win": 0,
        "draw": 0,
        "illegal_exp4": 0,
        "illegal_exp5": 0,
        "games_total": 0,
    }
    strength_counted_outcome = {
        "exp4_win": 0,
        "exp5_win": 0,
        "draw": 0,
        "illegal_exp4": 0,
        "illegal_exp5": 0,
        "games_counted": 0,
    }
    forced_fixture_count = 0
    mirror_group_breakdown: dict[str, dict] = {}
    color_split = {"exp4_white": 0, "exp4_black": 0}
    illegal_count = 0
    suspicious_count = 0
    cluster_breakdown: dict[str, dict] = {}
    audit_success_total = {"exp4": 0, "exp5": 0}
    audit_error_total = {"exp4": 0, "exp5": 0}
    expected_match = {"hit": 0, "miss": 0, "no_label": 0}

    for g in game_reports:
        outcome = g["outcome"]
        raw_outcome[outcome] = raw_outcome.get(outcome, 0) + 1
        raw_outcome["games_total"] += 1
        if g.get("strength_counted"):
            strength_counted_outcome[outcome] = strength_counted_outcome.get(outcome, 0) + 1
            strength_counted_outcome["games_counted"] += 1
        if g.get("forced_fixture_win"):
            forced_fixture_count += 1
        group = str(g.get("color_mirror_group") or "")
        if group:
            slot_g = mirror_group_breakdown.setdefault(
                group,
                {"games": 0, "exp4_win": 0, "exp5_win": 0, "draw": 0, "illegal": 0, "members": []},
            )
            slot_g["games"] += 1
            if outcome in ("exp4_win", "exp5_win", "draw"):
                slot_g[outcome] += 1
            else:
                slot_g["illegal"] += 1
            slot_g["members"].append(
                {
                    "seed_id": g["seed_id"],
                    "exp4_color": g["exp4_color"],
                    "outcome": outcome,
                    "plies": g["plies"],
                }
            )
        color_split[f"exp4_{g['exp4_color']}"] += 1
        illegal_count += g["illegal_count"]
        for record in g["ply_records"]:
            if _suspicious_record(record):
                suspicious_count += 1
        for k in ("exp4", "exp5"):
            audit_success_total[k] += g["audit_success_count"][k]
            audit_error_total[k] += g["audit_error_count"][k]
        ct = g["cluster_tag"]
        slot = cluster_breakdown.setdefault(
            ct,
            {"games": 0, "exp4_win": 0, "exp5_win": 0, "draw": 0, "illegal": 0},
        )
        slot["games"] += 1
        if outcome in ("exp4_win", "exp5_win", "draw"):
            slot[outcome] += 1
        else:
            slot["illegal"] += 1
        if g.get("expected_move_any"):
            if g.get("first_move_match_expected"):
                expected_match["hit"] += 1
            else:
                expected_match["miss"] += 1
        else:
            expected_match["no_label"] += 1

    audit_coverage_rate = {}
    for k in ("exp4", "exp5"):
        total = audit_success_total[k] + audit_error_total[k]
        audit_coverage_rate[k] = (audit_success_total[k] / total) if total else None

    summary = {
        "meta": meta,
        "raw_outcome": raw_outcome,
        "strength_counted_outcome": strength_counted_outcome,
        "forced_fixture_count": forced_fixture_count,
        "mirror_group_breakdown": mirror_group_breakdown,
        "color_split": color_split,
        "illegal_count": illegal_count,
        "suspicious_count": suspicious_count,
        "cluster_breakdown": cluster_breakdown,
        "exp4_audit_success_count": audit_success_total["exp4"],
        "exp4_audit_error_count": audit_error_total["exp4"],
        "exp4_audit_coverage_rate": audit_coverage_rate["exp4"],
        "exp5_audit_success_count": audit_success_total["exp5"],
        "exp5_audit_error_count": audit_error_total["exp5"],
        "exp5_audit_coverage_rate": audit_coverage_rate["exp5"],
        "first_move_vs_expected": expected_match,
        "audit_enabled": meta.get("audit_enabled"),
        "audit_fail_soft": meta.get("audit_fail_soft"),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )

    gate_state = {
        "can_use_as_promotion_evidence": False,
        "can_use_as_strength_evidence": False,
        "diagnostic_only": True,
        "candidate_can_be_promoted": False,
        "production_model_unchanged": True,
        "exp4_deterministic_profile": False,
        "exp4_search_profile": meta["search_profile_exp4"],
        "exp4_time_budget_variance_accepted": True,
        "exp5_search_profile": meta["search_profile_exp5"],
        "exp5_deterministic_profile": meta["search_profile_exp5"].startswith("fixed_depth"),
        "phase": "phase_1_smoke",
    }
    (out_dir / "gate_state.json").write_text(
        json.dumps(gate_state, indent=2, sort_keys=True), encoding="utf-8"
    )

    lines = [
        "# exp4 vs exp5 sparring smoke — diagnostic only",
        "",
        f"- timestamp: {meta['timestamp']}",
        f"- mode: {meta['mode']}",
        f"- seeds_played: {', '.join(meta['seeds_played'])}",
        "",
        "## Models",
        f"- exp4_model_path: {meta['exp4_model_path']}",
        f"- exp4_model_hash (sha256): {meta['exp4_model_hash']}",
        f"- exp4_model_source: {meta['exp4_model_source']}",
        f"- exp5_model_path: {meta['exp5_model_path']}",
        f"- exp5_model_hash (sha256): {meta['exp5_model_hash']}",
        f"- exp5_model_source: {meta['exp5_model_source']}",
        "",
        "## Profiles",
        f"- exp4_search_profile: {meta['search_profile_exp4']} (time-budget; non-deterministic)",
        f"- exp5_search_profile: {meta['search_profile_exp5']}",
        "",
        "## Gate semantics",
        "- can_use_as_promotion_evidence = false",
        "- can_use_as_strength_evidence = false",
        "- diagnostic_only = true",
        "- production_model_unchanged = true",
        "",
        "## raw_outcome (all games, includes forced-fixture seeds)",
        f"- exp4_win: {raw_outcome['exp4_win']}",
        f"- exp5_win: {raw_outcome['exp5_win']}",
        f"- draw: {raw_outcome['draw']}",
        f"- illegal_exp4: {raw_outcome.get('illegal_exp4', 0)}",
        f"- illegal_exp5: {raw_outcome.get('illegal_exp5', 0)}",
        f"- games_total: {raw_outcome['games_total']}",
        "",
        "## strength_counted_outcome (forced-fixture seeds excluded)",
        f"- exp4_win: {strength_counted_outcome['exp4_win']}",
        f"- exp5_win: {strength_counted_outcome['exp5_win']}",
        f"- draw: {strength_counted_outcome['draw']}",
        f"- illegal_exp4: {strength_counted_outcome.get('illegal_exp4', 0)}",
        f"- illegal_exp5: {strength_counted_outcome.get('illegal_exp5', 0)}",
        f"- games_counted: {strength_counted_outcome['games_counted']}",
        f"- forced_fixture_count (excluded): {forced_fixture_count}",
        "",
        "## Color split (exp4 side)",
        f"- exp4_white: {color_split['exp4_white']}",
        f"- exp4_black: {color_split['exp4_black']}",
        "",
        "## Audit coverage",
        (
            f"- exp4: success={audit_success_total['exp4']} error={audit_error_total['exp4']} "
            f"rate={audit_coverage_rate['exp4']}"
        ),
        (
            f"- exp5: success={audit_success_total['exp5']} error={audit_error_total['exp5']} "
            f"rate={audit_coverage_rate['exp5']}"
        ),
        "",
        "## First-move-vs-expected (objective oracle only)",
        f"- hit: {expected_match['hit']}",
        f"- miss: {expected_match['miss']}",
        f"- no_label: {expected_match['no_label']}",
        "",
        "## Cluster breakdown",
    ]
    for ct, slot in sorted(cluster_breakdown.items()):
        lines.append(
            f"- {ct}: games={slot['games']} exp4_win={slot['exp4_win']} "
            f"exp5_win={slot['exp5_win']} draw={slot['draw']} illegal={slot['illegal']}"
        )

    if mirror_group_breakdown:
        lines.append("")
        lines.append("## Color mirror groups")
        for group, slot in sorted(mirror_group_breakdown.items()):
            lines.append(
                f"- {group}: games={slot['games']} exp4_win={slot['exp4_win']} "
                f"exp5_win={slot['exp5_win']} draw={slot['draw']} illegal={slot['illegal']}"
            )

    if suspicious_count or illegal_count:
        lines.append("")
        lines.append("## Suspicious / illegal flags")
        lines.append(f"- illegal_count: {illegal_count}")
        lines.append(f"- suspicious_count: {suspicious_count}")

    (out_dir / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ----- argparse + main ---------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="exp4 vs exp5 head-to-head diagnostic sparring (Phase 1 smoke)."
    )
    p.add_argument("--non-interactive", action="store_true", help="Skip all prompts; require CLI args.")
    p.add_argument("--exp4-model-path", default="", help="exp4 PV model JSON path.")
    p.add_argument("--exp5-model-path", default="", help="exp5 NNUE model JSON path.")
    p.add_argument(
        "--mode",
        default="",
        choices=["", "single", "castling", "tactic", "smoke", "custom"],
        help="Game mode preset.",
    )
    p.add_argument(
        "--seed-id",
        default="",
        help="For --mode single: the seed_id to play (e.g. smoke_01_mate_in_one_white).",
    )
    p.add_argument(
        "--seed-indices",
        default="",
        help="For --mode custom: comma-separated 1-based seed indices (e.g. '1,3,5').",
    )
    p.add_argument(
        "--output-root",
        default="/home/s92137/chess_results",
        help="Parent dir for the timestamped run folder.",
    )
    p.add_argument("--max-plies", type=int, default=120)
    p.add_argument("--search-profile-exp4", default="balanced")
    p.add_argument("--search-profile-exp5", default="fixed_depth_strong")
    p.add_argument("--enable-exp4-audit", action="store_true", default=True)
    p.add_argument("--disable-exp4-audit", action="store_true", default=False)
    p.add_argument("--audit-max-plies-per-game", type=int, default=0)
    p.add_argument("--master-seed", type=int, default=20260512, help="Logged for traceability.")
    return p.parse_args()


def _resolve_paths_interactive(args: argparse.Namespace) -> tuple[Path, Path, str, str]:
    if args.exp4_model_path:
        exp4_path = Path(args.exp4_model_path).expanduser().resolve()
        exp4_source = "manual_cli"
    elif args.non_interactive:
        raise SystemExit("error: --exp4-model-path required in --non-interactive mode")
    else:
        exp4_path = _select_model("exp4", EXP4_KNOWN_CANDIDATES)
        exp4_source = "interactive_select"
    if args.exp5_model_path:
        exp5_path = Path(args.exp5_model_path).expanduser().resolve()
        exp5_source = "manual_cli"
    elif args.non_interactive:
        raise SystemExit("error: --exp5-model-path required in --non-interactive mode")
    else:
        exp5_path = _select_model("exp5", EXP5_KNOWN_CANDIDATES)
        exp5_source = "interactive_select"
    if not exp4_path.exists():
        raise SystemExit(f"error: exp4 model path does not exist: {exp4_path}")
    if not exp5_path.exists():
        raise SystemExit(f"error: exp5 model path does not exist: {exp5_path}")
    return exp4_path, exp5_path, exp4_source, exp5_source


def _resolve_mode_interactive(args: argparse.Namespace) -> tuple[str, list[int]]:
    if args.mode:
        mode = args.mode
        if mode in MODE_PRESETS and mode != "single":
            return mode, list(MODE_PRESETS[mode])
        if mode == "single":
            if args.seed_id:
                for idx, seed in enumerate(SMOKE_SEEDS):
                    if seed["seed_id"] == args.seed_id:
                        return "single", [idx]
                raise SystemExit(f"error: --seed-id not found: {args.seed_id}")
            if args.non_interactive:
                return "single", [0]
            return _select_mode_and_seeds()
        if mode == "custom":
            if args.seed_indices:
                indices = []
                for token in args.seed_indices.split(","):
                    token = token.strip()
                    if not token:
                        continue
                    try:
                        i = int(token)
                        if 1 <= i <= len(SMOKE_SEEDS):
                            indices.append(i - 1)
                    except ValueError:
                        continue
                if not indices:
                    raise SystemExit("error: --seed-indices empty after parsing")
                return "custom", indices
            if args.non_interactive:
                raise SystemExit("error: --seed-indices required for --mode custom in --non-interactive")
            return _select_mode_and_seeds()
    if args.non_interactive:
        return "smoke", list(MODE_PRESETS["smoke"])
    return _select_mode_and_seeds()


def main() -> int:
    args = parse_args()

    audit_enabled = bool(args.enable_exp4_audit) and not bool(args.disable_exp4_audit)

    _say("=== exp4 vs exp5 sparring (phase 1 smoke, diagnostic only) ===")
    _say(f"timestamp: {_now_iso()}")
    _say(f"interactive: {not args.non_interactive}")
    _say(f"exp4_audit_enabled: {audit_enabled}")
    _say(f"audit_fail_soft: True (hard-coded)")

    exp4_path, exp5_path, exp4_source, exp5_source = _resolve_paths_interactive(args)
    exp4_hash = compute_model_hash(exp4_path)
    exp5_hash = compute_model_hash(exp5_path)

    mode, seed_indices = _resolve_mode_interactive(args)
    seeds = [SMOKE_SEEDS[i] for i in seed_indices]
    seeds_to_play = seeds[: max(1, len(seeds))]

    _say("")
    _say("=== confirmed configuration ===")
    _say(f"exp4_model_path : {exp4_path}")
    _say(f"exp4_model_hash : {exp4_hash}")
    _say(f"exp4_source     : {exp4_source}")
    _say(f"exp5_model_path : {exp5_path}")
    _say(f"exp5_model_hash : {exp5_hash}")
    _say(f"exp5_source     : {exp5_source}")
    _say(f"mode            : {mode}")
    _say(f"seeds_to_play   : {[s['seed_id'] for s in seeds_to_play]}")
    _say(f"max_plies       : {args.max_plies}")
    _say(f"profile_exp4    : {args.search_profile_exp4}")
    _say(f"profile_exp5    : {args.search_profile_exp5}")

    timestamp_dir = f"exp4_vs_exp5_smoke_{_timestamp_dirname()}"
    out_dir = Path(args.output_root).expanduser().resolve() / timestamp_dir

    if not args.non_interactive:
        confirm = _prompt("proceed? [Y/n]", default="Y")
        if confirm.lower() not in ("", "y", "yes"):
            _say("aborted by user")
            return 1

    meta = {
        "timestamp": _now_iso(),
        "mode": mode,
        "master_seed": args.master_seed,
        "max_plies": args.max_plies,
        "exp4_model_path": str(exp4_path),
        "exp4_model_hash": exp4_hash,
        "exp4_model_source": exp4_source,
        "exp5_model_path": str(exp5_path),
        "exp5_model_hash": exp5_hash,
        "exp5_model_source": exp5_source,
        "search_profile_exp4": args.search_profile_exp4,
        "search_profile_exp5": args.search_profile_exp5,
        "audit_enabled": audit_enabled,
        "audit_fail_soft": True,
        "audit_max_plies_per_game": args.audit_max_plies_per_game,
        "diagnostic_only": True,
        "phase": "phase_1_smoke",
        "seeds_played": [s["seed_id"] for s in seeds_to_play],
        "output_dir": str(out_dir),
    }

    game_reports: list[dict] = []
    for seed in seeds_to_play:
        report = play_one_game(
            seed,
            exp4_path=exp4_path,
            exp4_hash=exp4_hash,
            exp5_path=exp5_path,
            exp5_hash=exp5_hash,
            max_plies=args.max_plies,
            profile_exp4=args.search_profile_exp4,
            profile_exp5=args.search_profile_exp5,
            enable_audit=audit_enabled,
            audit_max_plies=args.audit_max_plies_per_game,
        )
        game_reports.append(report)

    write_artifacts(out_dir, game_reports, meta)

    _say("")
    _say("=== run complete ===")
    _say(f"artifacts: {out_dir}")
    _say(f"summary.json + games.jsonl + moves.jsonl + pgn/ + SUMMARY.md + gate_state.json")

    illegal_total = sum(g["illegal_count"] for g in game_reports)
    if illegal_total:
        _warn(f"total illegal moves across all games: {illegal_total} — inspect moves.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
