#!/usr/bin/env python3
"""Harvest sparring artefacts into canonical replay JSONL — W6 commit 1.

Input  : a sparring run directory containing
         games.jsonl  +  moves.jsonl  (+  summary.json, optional).
         Typical path: ``~/chess_results/exp4_vs_exp5_smoke_<ts>/``.

Output : ``~/chess_results/sparring_replay_<ts>/`` with
         sparring_objective_replay.jsonl  (training-eligible samples)
         sparring_candidates.jsonl        (every game + filter outcome)
         sparring_rejected.jsonl          (dropped games + reason)
         summary.json + SUMMARY.md

Filter (all required for acceptance):
  * ``objective_counted == True``            — we have an oracle to judge.
  * ``objective_hit == True``                — engine matched the oracle.
  * ``forced_fixture_win == False``          — exclude mate-in-1 etc.
  * game outcome did not end on illegal move.
  * first ply ``legal == True``.

A diagnostic note: ``objective_hit`` is judged on **ply 0** (the move
right after the seed FEN). We harvest exactly that ply, with the engine
that played it. We do NOT collect later plies — without an oracle they
are no better than raw engine-vs-engine moves, which
[[feedback-pvp-replay-discipline]] forbids.

Sample shape mirrors PvP replay (W1/W3) so chess_seed_train's external
replay validator accepts it unchanged. ``trusted_source`` is the
already-whitelisted ``sparring_objective_hit`` slot (see W4 commit
``41e1a60`` and the W4.2 contract in
``services/games/external_replay_safety.py``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_OUTPUT_ROOT = Path.home() / "chess_results"
DEFAULT_SAMPLE_WEIGHT = 0.10
SAMPLE_WEIGHT_CAP = 0.15  # mirror pvp_filtered cap; sparring is similarly low-trust


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _timestamp_dirname() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _index_first_plies(moves_rows: list[dict]) -> dict[str, dict]:
    """Map seed_id → first-ply (ply=0) record from moves.jsonl."""
    out: dict[str, dict] = {}
    for row in moves_rows:
        if int(row.get("ply", -1)) != 0:
            continue
        seed_id = str(row.get("seed_id") or "")
        if seed_id and seed_id not in out:
            out[seed_id] = row
    return out


def classify_game(game: dict, *, first_ply: dict | None) -> tuple[str, str]:
    """Return ``(outcome, reason)`` for one game row.

    outcome ∈ {"accept", "reject"}; reason is empty on accept.
    """
    if not bool(game.get("objective_counted")):
        return ("reject", "no_oracle")
    if bool(game.get("forced_fixture_win")):
        return ("reject", "forced_fixture")
    outcome = str(game.get("outcome") or "")
    if outcome.startswith("illegal_"):
        return ("reject", f"illegal_outcome:{outcome}")
    if not bool(game.get("objective_hit")):
        return ("reject", "objective_miss")
    if first_ply is None:
        return ("reject", "missing_first_ply_record")
    if not bool(first_ply.get("legal")):
        return ("reject", "first_ply_illegal")
    if not first_ply.get("move") or not first_ply.get("fen_before"):
        return ("reject", "first_ply_incomplete")
    return ("accept", "")


def build_sample(game: dict, first_ply: dict, *, sample_weight: float) -> dict:
    """Compose the canonical replay row for one accepted game."""
    seed_id = str(game.get("seed_id") or "")
    return {
        "fen": str(first_ply.get("fen_before") or ""),
        "move_uci": str(first_ply.get("move") or ""),
        "side": str(first_ply.get("side") or ""),
        "target": 1.0,
        "weight": float(sample_weight),
        "source": "sparring_objective_hit",
        "source_id": f"sparring:{seed_id}:ply:0",
        "trusted_source": "sparring_objective_hit",
        "label_quality": "review",
        "training_eligible": True,
        "result_backed": True,
        "teacher_audit_status": "not_run",
        "seed_id": seed_id,
        "cluster_tag": str(game.get("cluster_tag") or ""),
        "objective_type": str(game.get("objective_type") or ""),
        "expected_rule_subtype": game.get("expected_rule_subtype"),
        "engine_id": str(first_ply.get("engine_id") or ""),
        "match_mode": "sparring",
    }


def _run_dir_hash(run_dir: Path) -> str:
    payload = json.dumps({"run_dir": str(run_dir)}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def run_export(
    *,
    run_dir: Path,
    output_root: Path,
    sample_weight: float,
    limit: int = 0,
) -> dict:
    if sample_weight > SAMPLE_WEIGHT_CAP:
        raise SystemExit(
            f"error: --sample-weight {sample_weight} exceeds policy cap "
            f"{SAMPLE_WEIGHT_CAP} (sparring is review-tier, not clean)."
        )
    games_path = run_dir / "games.jsonl"
    moves_path = run_dir / "moves.jsonl"
    if not games_path.exists():
        raise SystemExit(f"error: games.jsonl missing under {run_dir}")
    if not moves_path.exists():
        raise SystemExit(f"error: moves.jsonl missing under {run_dir}")

    games = _read_jsonl(games_path)
    moves = _read_jsonl(moves_path)
    first_ply_by_seed = _index_first_plies(moves)

    output_root.mkdir(parents=True, exist_ok=True)
    out_dir = output_root / f"sparring_replay_{_timestamp_dirname()}"
    out_dir.mkdir(parents=True, exist_ok=False)

    candidates_path = out_dir / "sparring_candidates.jsonl"
    eligible_path = out_dir / "sparring_objective_replay.jsonl"
    rejected_path = out_dir / "sparring_rejected.jsonl"

    counts: dict = {
        "games_total": 0,
        "games_accepted": 0,
        "games_rejected": 0,
        "samples_emitted": 0,
        "reject_reasons": {},
        "by_objective_type": {},
        "by_cluster_tag": {},
    }
    if limit > 0:
        games = games[:limit]

    with (
        candidates_path.open("w", encoding="utf-8") as fh_c,
        eligible_path.open("w", encoding="utf-8") as fh_e,
        rejected_path.open("w", encoding="utf-8") as fh_r,
    ):
        for game in games:
            counts["games_total"] += 1
            seed_id = str(game.get("seed_id") or "")
            first_ply = first_ply_by_seed.get(seed_id)
            outcome, reason = classify_game(game, first_ply=first_ply)

            otype = str(game.get("objective_type") or "(none)")
            counts["by_objective_type"].setdefault(otype, {"accepted": 0, "rejected": 0})
            ctag = str(game.get("cluster_tag") or "(none)")
            counts["by_cluster_tag"].setdefault(ctag, {"accepted": 0, "rejected": 0})

            candidate_row = {
                "seed_id": seed_id,
                "cluster_tag": ctag,
                "objective_type": otype,
                "objective_counted": bool(game.get("objective_counted")),
                "objective_hit": bool(game.get("objective_hit")),
                "forced_fixture_win": bool(game.get("forced_fixture_win")),
                "outcome": str(game.get("outcome") or ""),
                "expected_rule_subtype": game.get("expected_rule_subtype"),
                "first_ply_legal": bool(first_ply.get("legal")) if first_ply else False,
                "first_ply_move": str(first_ply.get("move") or "") if first_ply else "",
                "first_ply_engine": str(first_ply.get("engine_id") or "") if first_ply else "",
                "filter_outcome": outcome,
                "filter_reason": reason,
                "training_eligible": False,
            }

            if outcome == "reject":
                counts["games_rejected"] += 1
                counts["reject_reasons"][reason] = counts["reject_reasons"].get(reason, 0) + 1
                counts["by_objective_type"][otype]["rejected"] += 1
                counts["by_cluster_tag"][ctag]["rejected"] += 1
                fh_c.write(json.dumps(candidate_row, sort_keys=True) + "\n")
                fh_r.write(
                    json.dumps(
                        {
                            "seed_id": seed_id,
                            "rejection_reason": reason,
                            "cluster_tag": ctag,
                            "objective_type": otype,
                            "outcome": str(game.get("outcome") or ""),
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
                continue

            sample = build_sample(game, first_ply, sample_weight=sample_weight)
            counts["games_accepted"] += 1
            counts["samples_emitted"] += 1
            counts["by_objective_type"][otype]["accepted"] += 1
            counts["by_cluster_tag"][ctag]["accepted"] += 1
            candidate_row["training_eligible"] = True
            candidate_row["sample_weight"] = float(sample_weight)
            fh_c.write(json.dumps(candidate_row, sort_keys=True) + "\n")
            fh_e.write(json.dumps(sample, sort_keys=True) + "\n")

    summary = {
        "timestamp": _now_iso(),
        "run_dir": str(run_dir),
        "run_dir_hash": _run_dir_hash(run_dir),
        "output_dir": str(out_dir),
        "filter_config": {
            "sample_weight": sample_weight,
            "sample_weight_cap": SAMPLE_WEIGHT_CAP,
            "trusted_source": "sparring_objective_hit",
            "label_quality": "review",
            "ply_scope": "first_ply_only",
        },
        "counts": counts,
        "policy": {
            "diagnostic_only": True,
            "auto_train_hook": False,
            "production_runtime_mutation": False,
            "raw_engine_moves_collected": False,
            "forced_fixture_collected": False,
        },
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )

    lines: list[str] = [
        "# Sparring → replay export (W6 commit 1, diagnostic only)",
        "",
        f"- timestamp: {summary['timestamp']}",
        f"- run_dir: {run_dir}",
        f"- output_dir: {out_dir}",
        "",
        "## Filter config",
        f"- sample_weight: {sample_weight} (cap {SAMPLE_WEIGHT_CAP})",
        "- trusted_source: sparring_objective_hit",
        "- label_quality: review",
        "- ply_scope: first_ply_only (only the ply where objective_hit was judged)",
        "",
        "## Counts",
        f"- games_total: {counts['games_total']}",
        f"- games_accepted: {counts['games_accepted']}",
        f"- games_rejected: {counts['games_rejected']}",
        f"- samples_emitted: {counts['samples_emitted']}",
        "",
        "### reject_reasons",
    ]
    if counts["reject_reasons"]:
        for k in sorted(counts["reject_reasons"]):
            lines.append(f"- {k}: {counts['reject_reasons'][k]}")
    else:
        lines.append("- (none)")
    lines.extend([
        "",
        "### by_objective_type",
    ])
    for otype in sorted(counts["by_objective_type"]):
        slot = counts["by_objective_type"][otype]
        lines.append(f"- {otype}: accepted={slot['accepted']} rejected={slot['rejected']}")
    lines.extend([
        "",
        "## Policy (hard-coded)",
        "- diagnostic_only = True",
        "- auto_train_hook = False",
        "- production_runtime_mutation = False",
        "- raw_engine_moves_collected = False (only oracle-confirmed first plies)",
        "- forced_fixture_collected = False",
        "",
        "Feed `sparring_objective_replay.jsonl` to `chess_seed_train.py` via",
        "`--include-replay-jsonl PATH` for warm-up (downsampled per source cap).",
        "Operator can also pipe it through `chess_replay_operator.py dry-run` to",
        "validate normalize before any staging warm-up.",
    ])
    (out_dir / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    return summary


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Harvest sparring run dir → canonical replay JSONL "
        "(only objective_hit=true first plies, sparring_objective_hit trusted source)."
    )
    p.add_argument("--run-dir", required=True, help="Sparring output dir (with games.jsonl + moves.jsonl).")
    p.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    p.add_argument("--sample-weight", type=float, default=DEFAULT_SAMPLE_WEIGHT,
                   help=f"Default {DEFAULT_SAMPLE_WEIGHT}; capped at {SAMPLE_WEIGHT_CAP}.")
    p.add_argument("--limit", type=int, default=0, help="If >0, process at most this many games.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    if not run_dir.exists():
        raise SystemExit(f"error: --run-dir does not exist: {run_dir}")

    print("=== chess_sparring_to_replay (W6 commit 1, diagnostic only) ===")
    print(f"run_dir: {run_dir}")
    print(f"output_root: {output_root}")
    print(f"sample_weight: {args.sample_weight} (cap {SAMPLE_WEIGHT_CAP})")

    summary = run_export(
        run_dir=run_dir,
        output_root=output_root,
        sample_weight=float(args.sample_weight),
        limit=int(args.limit),
    )

    counts = summary["counts"]
    print()
    print(f"games_total          : {counts['games_total']}")
    print(f"games_accepted       : {counts['games_accepted']}")
    print(f"games_rejected       : {counts['games_rejected']}")
    print(f"samples_emitted      : {counts['samples_emitted']}")
    print(f"\nartifacts: {summary['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
