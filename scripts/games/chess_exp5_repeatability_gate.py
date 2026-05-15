#!/usr/bin/env python3
"""Run exp5 repeatability and robust promotion-tier checks."""

from __future__ import annotations

import argparse
import chess
import hashlib
import json
import os
import random
import statistics
import subprocess
import sys
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess_nnue import EXPERIMENT_NNUE_DIFFICULTY


def _progress(message: str) -> None:
    print(f"[chess-exp5-repeatability] {message}", file=sys.stderr, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run exp5_03 repeatability scenario.")
    parser.add_argument("--baseline-model-path", required=True)
    parser.add_argument("--distill-jsonl", required=True)
    parser.add_argument("--train-rows-jsonl", required=True)
    parser.add_argument("--strength-cases-jsonl", required=True)
    parser.add_argument("--heldout-source-jsonl", default="")
    parser.add_argument("--benchmark-report-path", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--run-count", type=int, default=3)
    parser.add_argument("--seeds", default="0,1,2")
    parser.add_argument("--heldout-count", type=int, default=24)
    parser.add_argument("--smoke-count", type=int, default=4)
    parser.add_argument("--search-profile", default="strong")
    parser.add_argument("--min-case-pass-rate", type=float, default=0.70)
    parser.add_argument("--min-benchmark-score-rate", type=float, default=0.45)
    parser.add_argument("--min-benchmark-games", type=int, default=2)
    parser.add_argument("--require-smoke", action="store_true")
    parser.add_argument("--max-regression-rate", type=float, default=0.10)
    parser.add_argument("--runtime-root", default="")
    parser.add_argument(
        "--epochs",
        type=int,
        default=1,
        help="Forwarded to chess_exp5_dataset_train.py: number of training passes (exp5_04 learning capacity).",
    )
    parser.add_argument(
        "--auto-hard-negative-topk",
        type=int,
        default=0,
        help="Forwarded to chess_exp5_dataset_train.py: inject the candidate's currently-preferred K moves as hard-negatives (exp5_04 learning capacity).",
    )
    parser.add_argument(
        "--multi-good-margin-cp",
        type=float,
        default=30.0,
        help="Forwarded to chess_exp5_dataset_train.py: cp window around teacher policy score within which a candidate move is treated as multi-good equivalent and excluded from hard-negatives.",
    )
    parser.add_argument(
        "--label-quality-weight-clean",
        type=float,
        default=1.0,
        help="Forwarded to chess_exp5_dataset_train.py: per-sample weight multiplier for label_quality=clean rows.",
    )
    parser.add_argument(
        "--label-quality-weight-review",
        type=float,
        default=0.4,
        help="Forwarded to chess_exp5_dataset_train.py: per-sample weight multiplier for label_quality=review rows.",
    )
    parser.add_argument(
        "--label-quality-weight-questionable",
        type=float,
        default=0.0,
        help="Forwarded to chess_exp5_dataset_train.py: per-sample weight multiplier for label_quality=questionable rows (0.0 = drop).",
    )
    return parser.parse_args()


def _iter_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_no}: row must be an object")
        rows.append(payload)
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_rows(path: Path) -> str:
    digest = hashlib.sha256()
    for row in _iter_jsonl(path):
        digest.update(json.dumps(row, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


def _row_signature(row: dict) -> str:
    fen = str(row.get("fen") or "")
    side = str(row.get("side") or ("white" if " w " in fen else "black")).strip().lower()
    try:
        board = chess.Board(fen)
        material = "".join(str(piece) for piece in board.piece_map().values())
        normalized_fen = board.board_fen()
        side_to_move = "w" if board.turn else "b"
        text = f"{normalized_fen}|{side_to_move}|{side}|{''.join(sorted(material))}"
    except Exception:
        text = f"{fen}|{side}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _flip_fen_turn(row: dict) -> dict:
    row = dict(row)
    fen = str(row.get("fen") or "")
    parts = fen.split()
    if len(parts) < 2:
        return row
    if parts[1] == "w":
        parts[1] = "b"
    elif parts[1] == "b":
        parts[1] = "w"
    row["fen"] = " ".join(parts)
    side = str(row.get("side") or "white").strip().lower()
    if side == "white":
        row["side"] = "black"
    elif side == "black":
        row["side"] = "white"
    return row


def _run_json(cmd: list[str], *, env: dict[str, str], cwd: Path) -> dict:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=None,
    )
    if proc.stderr:
        sys.stderr.write(proc.stderr)
        sys.stderr.flush()
    if proc.returncode != 0:
        raise RuntimeError(
            "command failed\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stdout: {proc.stdout}\n"
            f"stderr: {proc.stderr}"
        )
    try:
        return json.loads(proc.stdout)
    except Exception as exc:
        raise RuntimeError(f"command did not output JSON\nstdout={proc.stdout}\nstderr={proc.stderr}") from exc


def _parse_seeds(raw: str, run_count: int) -> list[int]:
    seeds: list[int] = []
    for item in str(raw).split(","):
        item = item.strip()
        if item:
            seeds.append(int(item))
    if len(seeds) < run_count:
        while len(seeds) < run_count:
            seeds.append(len(seeds))
    return seeds[:run_count]


def _select_heldout_rows(source_rows: list[dict], train_rows: list[dict], target_count: int) -> list[dict]:
    if target_count <= 0:
        return []

    banned = {_row_signature(row) for row in train_rows}
    pool = [dict(row) for row in source_rows if _row_signature(row) not in banned and str(row.get("fen") or "").strip()]
    if pool:
        _progress(f"heldout selector: source={len(source_rows)} pool_non_overlap={len(pool)} train={len(train_rows)} target={target_count}")
    else:
        _progress(
            f"heldout selector: source={len(source_rows)} pool_non_overlap=0 train={len(train_rows)} target={target_count} (attempting fallback synthesis)"
        )

    buckets: dict[str, list[dict]] = {}
    for row in pool:
        category = str(row.get("category") or "other").strip().lower()
        buckets.setdefault(category, []).append(row)

    category_order = [
        "opening",
        "tactic",
        "endgame",
        "blunder_avoid",
        "teacher_hard",
        "baseline_teacher_disagreement",
        "quiet_positional",
    ]
    picked: list[dict] = []
    used: set[str] = set()

    for category in category_order:
        for row in buckets.get(category, []):
            signature = _row_signature(row)
            if signature in used:
                continue
            picked.append(row)
            used.add(signature)
            if len(picked) >= target_count:
                return picked[:target_count]

    for row in pool:
        signature = _row_signature(row)
        if signature in used:
            continue
        picked.append(row)
        used.add(signature)
        if len(picked) >= target_count:
            return picked[:target_count]

    # Fallback #1: source rows are all overlapped with train set (likely same file); try side-flip variants.
    for row in source_rows:
        if len(picked) >= target_count:
            break
        signature = _row_signature(row)
        if signature not in banned and signature not in used:
            picked.append(dict(row))
            used.add(signature)
            continue

        alt = _flip_fen_turn(row)
        alt_signature = _row_signature(alt)
        if alt_signature not in banned and alt_signature not in used:
            alt.setdefault("id", f"{row.get('id', 'exp5_03_heldout')}_flip_{len(picked):03d}")
            picked.append(alt)
            used.add(alt_signature)

    if len(picked) >= target_count:
        return picked[:target_count]

    # Fallback #2: if still short, fallback to smoke-like synthetic rows.
    for row in _make_smoke_rows(source_rows, target_count - len(picked)):
        signature = _row_signature(row)
        if signature in used or signature in banned:
            continue
        picked.append(row)
        used.add(signature)

    return picked[:target_count]


def _make_smoke_rows(strength_rows: list[dict], count: int) -> list[dict]:
    count = max(0, int(count))
    selected: list[dict] = []
    used: set[str] = set()
    for row in strength_rows:
        if len(selected) >= count:
            break
        case = dict(row)
        base_id = str(case.get("id") or f"smoke_{len(selected):03d}")
        case["id"] = f"{base_id}_smoke"
        case["category"] = "smoke"
        selected.append(case)
        used.add(_row_signature(case))

    if len(selected) < count:
        fallback = [
            {
                "id": "smoke_fallback_000",
                "fen": "8/8/8/8/8/8/7k/4K3 w - - 0 1",
                "side": "white",
                "category": "smoke",
                "label_quality": "review",
            },
            {
                "id": "smoke_fallback_001",
                "fen": "8/8/8/8/8/8/5k2/4K2R b - - 0 1",
                "side": "black",
                "category": "smoke",
                "label_quality": "review",
            },
            {
                "id": "smoke_fallback_002",
                "fen": "8/8/8/8/8/4K3/8/7k b - - 0 1",
                "side": "black",
                "category": "smoke",
                "label_quality": "review",
            },
            {
                "id": "smoke_fallback_003",
                "fen": "8/8/8/8/8/4K3/7k/4R3 b - - 0 1",
                "side": "black",
                "category": "smoke",
                "label_quality": "review",
            },
        ]
        for row in fallback:
            if len(selected) >= count:
                break
            signature = _row_signature(row)
            if signature in used:
                continue
            selected.append(row)
            used.add(signature)

    return selected[:count]


def _collect_case_summary(case_results: list[dict]) -> dict:
    decision_counts: dict[str, int] = {}
    clean_deltas: list[float] = []
    review_deltas: list[float] = []
    net = 0

    for row in case_results:
        decision_category = str(row.get("decision_category") or "unknown")
        decision_counts[decision_category] = int(decision_counts.get(decision_category, 0)) + 1
        delta = float(row.get("score_delta") or 0.0)
        net += 1 if delta > 0 else (-1 if delta < 0 else 0)

        label_quality = str(row.get("label_quality") or "clean")
        if label_quality == "review":
            review_deltas.append(delta)
        else:
            clean_deltas.append(delta)

    clean_case_score_delta = round(sum(clean_deltas) / max(1, len(clean_deltas)), 6)
    review_case_score_delta = round(sum(review_deltas) / max(1, len(review_deltas)), 6)
    clean_rows = [row for row in case_results if str(row.get("label_quality") or "clean") != "review"]
    clean_only_strength_score = round(sum(1 for row in clean_rows if bool(row.get("pass"))) / max(1, len(clean_rows)), 6)

    return {
        "case_category_counts": decision_counts,
        "net_improvement_count": net,
        "clean_net_improvement_count": sum(
            1 for row in case_results if float(row.get("score_delta") or 0.0) > 0 and str(row.get("label_quality") or "clean") != "review"
        ),
        "heldout_net_improvement_count": net,
        "clean_case_score_delta": clean_case_score_delta,
        "review_case_score_delta": review_case_score_delta,
        "clean_only_strength_score": clean_only_strength_score,
        "smoke_case_count": len([row for row in case_results if str(row.get("category") or "") == "smoke"]),
    }


def _collect_regression_budget(case_results: list[dict], max_rate: float) -> dict:
    regressed = [row for row in case_results if str(row.get("decision_category") or "") == "candidate_regressed"]
    total = max(1, len(case_results))
    rate = round(len(regressed) / total, 6)
    return {
        "candidate_regressed_count": len(regressed),
        "candidate_regressed_rate": rate,
        "max_allowed_regression_rate": float(max_rate),
        "passes_regression_budget": rate <= float(max_rate),
        "regressed_cases": [
            {
                "case_id": str(item.get("id") or ""),
                "category": str(item.get("category") or ""),
                "baseline_move": str(item.get("baseline", {}).get("chosen_move") or ""),
                "candidate_move": str(item.get("candidate", {}).get("chosen_move") or ""),
                "teacher_move": str(item.get("teacher_move") or ""),
                "baseline_score": float(item.get("baseline_score") or 0.0),
                "candidate_score": float(item.get("candidate_score") or 0.0),
                "regression_reason": "candidate_regressed",
            }
            for item in regressed
        ],
    }


def _collect_train_learning(gate_payload: dict) -> dict:
    train = gate_payload.get("train_rows_learning") or {}
    rows = []
    for row in (train.get("rows") or []):
        baseline_margin = float(row.get("baseline_teacher_margin") or 0.0)
        candidate_margin = float(row.get("candidate_teacher_margin") or 0.0)
        rows.append(
            {
                **row,
                "fen": str(row.get("fen") or ""),
                "teacher_margin_before": baseline_margin,
                "teacher_margin_after": candidate_margin,
                "margin_delta": round(candidate_margin - baseline_margin, 8),
                "candidate_matches_teacher": bool(row.get("candidate_teacher_agreement")),
            }
        )
    if rows:
        train = dict(train)
        train["rows"] = rows
        train["retrain_not_loaded"] = False
        train["update_too_weak"] = float(train.get("train_agreement_delta") or 0.0) <= 0.0
        train["PVS_decision_not_sensitive_to_weights"] = float(train.get("margin_delta") or 0.0) <= 0.0
        train["teacher_target_not_aligned_with_gate_score"] = False
        train["train_improved_but_metric_mismatch"] = bool(
            float(train.get("train_agreement_delta") or 0.0) > 0.0 and float(gate_payload.get("score_delta") or 0.0) <= 0.0
        )
    else:
        train = dict(train)
        train.setdefault("rows", [])
        train.setdefault("retrain_not_loaded", True)
        train.setdefault("update_too_weak", True)
        train.setdefault("train_improved_but_metric_mismatch", False)
        train.setdefault("PVS_decision_not_sensitive_to_weights", True)
        train.setdefault("teacher_target_not_aligned_with_gate_score", True)

    return train


def _collect_repeatability(values: list[float]) -> dict:
    if not values:
        return {"mean": 0.0, "min": 0.0, "max": 0.0, "std": 0.0}
    return {
        "mean": round(statistics.fmean(values), 6),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
        "std": round(statistics.pstdev(values), 6) if len(values) > 1 else 0.0,
    }


def _determine_tier(runs: list[dict], *, require_smoke: bool, max_regression_rate: float) -> dict:
    """Tier the candidate across N seeds.

    exp5_07 plumbing:
      - stage_candidate: all seeds report `candidate_can_be_staged=True` (per
        the strength gate's stage_reasons). pass_count of seeds where the
        deterministic stage-level evidence holds.
      - shadow_candidate: stage_candidate + repeatability_pass + safety
        (no benchmark needed at stage level; benchmark becomes a shadow/
        production blocker per strength gate's shadow_reasons).
      - production_promote: shadow_candidate + no production_reasons.
    """
    run_count = len(runs)

    # Per-seed stage-level pass (from the inner strength gate's
    # `candidate_can_be_staged`, not the legacy `gate_pass` which couples in
    # benchmark missing).
    stage_pass_count = sum(1 for row in runs if bool(row.get("candidate_can_be_staged")))
    shadow_pass_count = sum(1 for row in runs if bool(row.get("candidate_can_be_shadowed")))
    production_pass_count = sum(1 for row in runs if bool(row.get("candidate_can_be_production_promoted")))
    legacy_pass_count = sum(1 for row in runs if bool(row.get("gate_pass")))

    stage_reasons: list[str] = []
    shadow_reasons: list[str] = []
    production_reasons: list[str] = []

    if stage_pass_count == 0:
        stage_reasons.append("all_runs_failed_stage")
    if stage_pass_count < run_count:
        stage_reasons.append("not_all_runs_passed_stage")

    deltas = [float(row.get("score_delta") or 0.0) for row in runs]
    repeat_stats = _collect_repeatability(deltas)
    if run_count >= 2 and repeat_stats["std"] > 0.05:
        shadow_reasons.append("repeatability_unstable")

    if any(float(row.get("regression", {}).get("candidate_regressed_rate") or 0.0) > float(max_regression_rate) for row in runs):
        stage_reasons.append("regression_budget_exceeded")

    if any(bool((row.get("leakage") or {}).get("held_out_in_training")) for row in runs):
        stage_reasons.append("heldout_in_training")

    if require_smoke and any(row.get("smoke_case_count", 0) == 0 for row in runs):
        production_reasons.append("smoke_cases_missing")
    if require_smoke and any(bool(row.get("smoke_audit_failed")) for row in runs):
        stage_reasons.append("smoke_case_failed")

    # Aggregate shadow / production reasons reported by each inner gate.
    for row in runs:
        for r in row.get("shadow_reasons") or []:
            if r not in shadow_reasons:
                shadow_reasons.append(r)
        for r in row.get("production_reasons") or []:
            if r not in production_reasons:
                production_reasons.append(r)

    stage_candidate = (not stage_reasons) and stage_pass_count == run_count and run_count > 0
    shadow_candidate = stage_candidate and not shadow_reasons and shadow_pass_count == run_count
    production_promote = (
        shadow_candidate
        and not production_reasons
        and production_pass_count == run_count
        and all(not bool((row.get("train_learning") or {}).get("update_too_weak")) for row in runs)
    )

    return {
        "blocked": bool(stage_reasons),
        "stage_candidate": stage_candidate,
        "shadow_candidate": shadow_candidate,
        "production_promote": production_promote,
        "stage_reasons": stage_reasons,
        "shadow_reasons": shadow_reasons,
        "production_reasons": production_reasons,
        "stage_pass_count": stage_pass_count,
        "shadow_pass_count": shadow_pass_count,
        "production_pass_count": production_pass_count,
        "pass_count": legacy_pass_count,
        "run_count": run_count,
        "repeatability_delta": {
            **repeat_stats,
            "pass_count": legacy_pass_count,
            "run_count": run_count,
        },
    }


def _write_report(output_root: Path, payload: dict) -> dict:
    stamp = payload["finished_at"].replace(":", "").replace("-", "").replace("T", "_").replace("Z", "")
    json_path = output_root / f"chess_exp5_repeatability_{stamp}.json"
    md_path = output_root / f"chess_exp5_repeatability_{stamp}.md"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# chess_exp5_repeatability",
        "",
        f"- engine: `{payload['engine']}`",
        f"- baseline model: `{payload['baseline_model_path']}`",
        f"- run_count: `{payload['run_count']}`",
        f"- pass_count: `{payload['tier']['pass_count']}`",
        f"- stage_candidate: `{payload['tier']['stage_candidate']}`",
        f"- shadow_candidate: `{payload['tier']['shadow_candidate']}`",
        f"- production_promote: `{payload['tier']['production_promote']}`",
        f"- stage_reasons: `{', '.join(payload['tier']['stage_reasons'])}`",
        f"- repeatability mean/std: `{payload['tier']['repeatability_delta']['mean']}` / `{payload['tier']['repeatability_delta']['std']}`",
        "",
        "## Runs",
    ]
    for row in payload["runs"]:
        lines.append(
            f"- run={row['run_index']} seed={row['seed']} baseline={row['baseline_hash'][:12]} candidate={row['candidate_hash'][:12]} score_delta={row['score_delta']} pass={row['gate_pass']}"
        )
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def main() -> int:
    args = parse_args()
    baseline_path = Path(args.baseline_model_path).expanduser().resolve()
    distill_path = Path(args.distill_jsonl).expanduser().resolve()
    train_rows_path = Path(args.train_rows_jsonl).expanduser().resolve()
    strength_case_path = Path(args.strength_cases_jsonl).expanduser().resolve()
    heldout_source = Path(args.heldout_source_jsonl).expanduser().resolve() if args.heldout_source_jsonl else strength_case_path
    benchmark_path = Path(args.benchmark_report_path).expanduser().resolve() if args.benchmark_report_path else None
    output_root = Path(args.output_dir).expanduser().resolve()

    if not distill_path.exists():
        raise FileNotFoundError(f"distill jsonl missing: {distill_path}")

    train_rows = _iter_jsonl(train_rows_path)
    strength_cases = _iter_jsonl(strength_case_path)
    heldout_source_rows = _iter_jsonl(heldout_source) if heldout_source.exists() else strength_cases

    heldout_rows = _select_heldout_rows(heldout_source_rows, train_rows, int(args.heldout_count))
    smoke_rows = _make_smoke_rows(strength_cases, int(args.smoke_count))

    heldout_path = output_root / "heldout_rows_exp5_03.jsonl"
    smoke_path = output_root / "smoke_rows_exp5_03.jsonl"
    _write_jsonl(heldout_path, heldout_rows)
    _write_jsonl(smoke_path, smoke_rows)
    _progress(f"heldout rows: {len(heldout_rows)}")
    _progress(f"smoke rows: {len(smoke_rows)}")

    run_count = max(1, int(args.run_count))
    seeds = _parse_seeds(args.seeds, run_count)

    runtime_root = Path(args.runtime_root).expanduser().resolve() if args.runtime_root else output_root / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)

    runs: list[dict] = []
    for run_index, seed in enumerate(seeds, start=1):
        run_dir = output_root / f"run_{run_index}_seed_{seed}"
        candidate_model = run_dir / "candidate" / "chess_experiment_5_nnue_experience.json"
        candidate_replay = run_dir / "candidate" / "chess_experiment_5_nnue_experience_replay.jsonl"
        run_dir.mkdir(parents=True, exist_ok=True)
        candidate_model.parent.mkdir(parents=True, exist_ok=True)

        if baseline_path.exists():
            shutil.copyfile(baseline_path, candidate_model)

        distill_rows = _iter_jsonl(distill_path)
        random.Random(seed).shuffle(distill_rows)
        shuffled_distill = run_dir / "distill_shuffled.jsonl"
        _write_jsonl(shuffled_distill, distill_rows)

        train_cmd = [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp5_dataset_train.py"),
            "--model-path",
            str(candidate_model),
            "--replay-path",
            str(candidate_replay),
            "--input-jsonl",
            str(shuffled_distill),
            "--replace-replay",
        ]
        if int(args.epochs or 1) > 1:
            train_cmd.extend(["--epochs", str(int(args.epochs))])
        if int(args.auto_hard_negative_topk or 0) > 0:
            audit_path = run_dir / "hard_negative_audit.jsonl"
            train_cmd.extend([
                "--auto-hard-negative-topk",
                str(int(args.auto_hard_negative_topk)),
                "--hard-negative-source-model-path",
                str(baseline_path),
                "--hard-negative-audit-path",
                str(audit_path),
                "--multi-good-margin-cp",
                str(float(args.multi_good_margin_cp)),
            ])
        train_cmd.extend([
            "--label-quality-weight-clean",
            str(float(args.label_quality_weight_clean)),
            "--label-quality-weight-review",
            str(float(args.label_quality_weight_review)),
            "--label-quality-weight-questionable",
            str(float(args.label_quality_weight_questionable)),
        ])
        retrain_payload = _run_json(train_cmd, env=env, cwd=ROOT)

        strength_for_run = run_dir / "strength_cases_exp5_03.jsonl"
        _write_jsonl(strength_for_run, strength_cases + smoke_rows)

        gate_cmd = [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp5_strength_gate.py"),
            "--candidate-model-path",
            str(candidate_model),
            "--baseline-model-path",
            str(baseline_path),
            "--train-rows-jsonl",
            str(train_rows_path),
            "--held-out-rows-jsonl",
            str(heldout_path),
            "--strength-cases-jsonl",
            str(strength_for_run),
            "--output-dir",
            str(runtime_root),
            "--search-profile",
            str(args.search_profile),
            "--min-case-pass-rate",
            str(args.min_case_pass_rate),
            "--min-benchmark-score-rate",
            str(args.min_benchmark_score_rate),
            "--min-benchmark-games",
            str(args.min_benchmark_games),
        ]
        if benchmark_path and benchmark_path.exists():
            gate_cmd.extend(["--benchmark-report-path", str(benchmark_path)])

        gate_payload = _run_json(gate_cmd, env=env, cwd=ROOT)

        case_summary = _collect_case_summary(gate_payload.get("case_results") or [])
        regression = _collect_regression_budget(gate_payload.get("case_results") or [], args.max_regression_rate)
        train_learning = _collect_train_learning(gate_payload)
        leakage = gate_payload.get("leakage_guard") or {}
        smoke_audit = gate_payload.get("smoke_audit") or []
        smoke_audit_failed = False
        if gate_payload.get("smoke_audit") is not None:
            smoke_audit_failed = any(item.get("failure_reason") == "candidate_fail" for item in smoke_audit)

        run_payload = {
            "run_index": run_index,
            "seed": seed,
            "run_dir": str(run_dir),
            "baseline_model_path": str(baseline_path),
            "candidate_model_path": str(candidate_model),
            "baseline_hash": _sha256_file(baseline_path),
            "candidate_hash": _sha256_file(candidate_model),
            "distill_hash": _sha256_rows(shuffled_distill),
            "retrain_seconds": round(float(retrain_payload.get("retrain_seconds") or 0.0), 6),
            "train_rows_count": len(train_rows),
            "heldout_rows_count": len(heldout_rows),
            "smoke_case_count": len(smoke_rows),
            "gate_pass": bool(gate_payload.get("pass")),
            "candidate_can_be_staged": bool((gate_payload.get("promotion_gate") or {}).get("candidate_can_be_staged") or False),
            "candidate_can_be_shadowed": bool((gate_payload.get("promotion_gate") or {}).get("candidate_can_be_shadowed") or False),
            "candidate_can_be_production_promoted": bool((gate_payload.get("promotion_gate") or {}).get("candidate_can_be_production_promoted") or False),
            "candidate_can_be_promoted": bool((gate_payload.get("promotion_gate") or {}).get("candidate_can_be_promoted") or False),
            "stage_reasons": list((gate_payload.get("promotion_gate") or {}).get("stage_reasons") or []),
            "shadow_reasons": list((gate_payload.get("promotion_gate") or {}).get("shadow_reasons") or []),
            "production_reasons": list((gate_payload.get("promotion_gate") or {}).get("production_reasons") or []),
            "baseline_score": float(gate_payload.get("baseline_score") or 0.0),
            "candidate_score": float(gate_payload.get("candidate_score") or 0.0),
            "score_delta": float(gate_payload.get("score_delta") or 0.0),
            "case_pass_rate": float(gate_payload.get("case_pass_rate") or 0.0),
            "legal_rate": float(gate_payload.get("legal_rate") or 0.0),
            "suspicious_rate": float(gate_payload.get("suspicious_rate") or 0.0),
            "tactic_score": float(gate_payload.get("tactic_score") or 0.0),
            "endgame_score": float(gate_payload.get("endgame_score") or 0.0),
            "smoke_score": float(gate_payload.get("smoke_score") or 0.0),
            "case_summary": case_summary,
            "regression": regression,
            "train_learning": train_learning,
            "leakage": leakage,
            "smoke_audit": smoke_audit,
            "smoke_audit_failed": smoke_audit_failed,
            "train_payload": retrain_payload,
            "training_config": {
                "epochs": int(args.epochs or 1),
                "auto_hard_negative_topk": int(args.auto_hard_negative_topk or 0),
                "multi_good_margin_cp": float(args.multi_good_margin_cp or 0.0),
                "label_quality_weight_clean": float(args.label_quality_weight_clean),
                "label_quality_weight_review": float(args.label_quality_weight_review),
                "label_quality_weight_questionable": float(args.label_quality_weight_questionable),
                "positive_updates": int(retrain_payload.get("positive_updates") or 0),
                "hard_negative_updates": int(retrain_payload.get("hard_negative_updates") or 0),
                "epochs_actual": int(retrain_payload.get("epochs") or 1),
                "search_profile": str(args.search_profile),
            },
            "label_quality_weighting": retrain_payload.get("label_quality_weighting") or {},
            "hard_negative_audit_summary": retrain_payload.get("hard_negative_audit_summary") or {},
            "gate_payload_path": str(output_root / "run_{:d}_seed_{:d}".format(run_index, seed) / "gate_summary.jsonl"),
        }
        _progress(
            f"run {run_index}: pass={run_payload['gate_pass']} baseline={run_payload['baseline_score']} candidate={run_payload['candidate_score']} delta={run_payload['score_delta']}"
        )
        run_payload["gate_payload"] = {
            "pass": gate_payload.get("pass"),
            "reasons": gate_payload.get("reasons") or [],
        }
        runs.append(run_payload)

    tier = _determine_tier(runs, require_smoke=bool(args.require_smoke), max_regression_rate=float(args.max_regression_rate))
    baseline_scores = [row["baseline_score"] for row in runs]
    candidate_scores = [row["candidate_score"] for row in runs]
    score_deltas = [row["score_delta"] for row in runs]

    payload = {
        "ok": True,
        "engine": EXPERIMENT_NNUE_DIFFICULTY,
        "finished_at": datetime.utcnow().isoformat() + "Z",
        "baseline_model_path": str(baseline_path),
        "run_count": len(runs),
        "distill_hash": _sha256_rows(distill_path),
        "distill_config_hash": hashlib.sha256(
            json.dumps(
                {
                    "baseline_model_path": str(baseline_path),
                    "train_rows_path": str(train_rows_path),
                    "strength_cases_path": str(strength_case_path),
                    "heldout_rows": len(heldout_rows),
                    "smoke_cases": len(smoke_rows),
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest(),
        "heldout_path": str(heldout_path),
        "smoke_path": str(smoke_path),
        "heldout_count": len(heldout_rows),
        "smoke_case_count": len(smoke_rows),
        "repeatability": {
            "baseline_scores": baseline_scores,
            "candidate_scores": candidate_scores,
            "score_delta": score_deltas,
            "retrain_seconds": [row["retrain_seconds"] for row in runs],
            "mean_delta": _collect_repeatability(score_deltas)["mean"],
            "min_delta": _collect_repeatability(score_deltas)["min"],
            "max_delta": _collect_repeatability(score_deltas)["max"],
            "std_delta": _collect_repeatability(score_deltas)["std"],
            "pass_count": tier["pass_count"],
            "run_count": tier["run_count"],
        },
        "tier": tier,
        "results_root": str(output_root),
        "runs": runs,
    }
    payload["reports"] = _write_report(output_root, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _progress(f"FAIL: {exc}")
        raise
