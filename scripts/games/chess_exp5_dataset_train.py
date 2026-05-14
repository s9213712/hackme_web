#!/usr/bin/env python3
"""Train experiment 5:nnue from replay-derived position/move datasets.

Accepted JSONL row format:

    {"fen":"...", "move_uci":"e2e4", "side":"white", "target":1.0, "weight":1.0}

This is the exp5-specific minimal trainer. The immutable base model is embedded
in source code; this script writes only an NNUE-like experience delta JSON and
replay file. Strength validation and promotion gates remain separate pending
design because exp5 is not compatible with exp3/exp4 semantic replay
assumptions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess_nnue import (  # noqa: E402
    default_chess_nnue_model_path,
    default_chess_nnue_replay_path,
    rank_experiment_nnue_policy_moves,
    train_experiment_nnue_from_replay_samples,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train exp5 NNUE-like evaluator from replay-derived datasets.")
    parser.add_argument("--input-jsonl", action="append", default=[], help="JSONL rows containing fen+move samples.")
    parser.add_argument("--model-path", default="")
    parser.add_argument("--replay-path", default="")
    parser.add_argument("--replace-replay", action="store_true")
    parser.add_argument("--max-samples", type=int, default=0, help="Optional cap after all rows are expanded.")
    parser.add_argument(
        "--epochs",
        type=int,
        default=1,
        help="Repeat the replay training loop this many times. Multi-epoch helps weights accumulate enough to flip top-1 decisions on sparse teacher targets.",
    )
    parser.add_argument(
        "--auto-hard-negative-topk",
        type=int,
        default=0,
        help="Before training, query the current model for each sample's top-K candidate moves (excluding teacher) and inject them as hard_negatives so the trainer actively penalises the rows the candidate currently prefers.",
    )
    parser.add_argument(
        "--hard-negative-source-model-path",
        default="",
        help="Optional alternate model used for computing auto hard-negatives (default: same as --model-path).",
    )
    parser.add_argument(
        "--multi-good-margin-cp",
        type=float,
        default=30.0,
        help="When auto-injecting hard-negatives, any candidate move whose policy score is within this many centipawns of the teacher move is treated as a multi-good equivalent and excluded.",
    )
    parser.add_argument(
        "--hard-negative-audit-path",
        default="",
        help="Optional path to write per-sample hard-negative audit JSONL (teacher_move, teacher_top3, injected, excluded_multi_good).",
    )
    parser.add_argument(
        "--label-quality-weight-clean",
        type=float,
        default=1.0,
        help="Per-sample weight multiplier applied when the distill row carries label_quality=clean. Default 1.0 (no change).",
    )
    parser.add_argument(
        "--label-quality-weight-review",
        type=float,
        default=0.4,
        help="Per-sample weight multiplier applied when label_quality=review (default 0.4 — exp3-style soft-trust).",
    )
    parser.add_argument(
        "--label-quality-weight-questionable",
        type=float,
        default=0.0,
        help=(
            "Per-sample weight multiplier for label_quality=questionable rows. Default 0.0 → these rows are "
            "skipped from the positive update path (they may still serve as hard-negative SOURCES for other rows)."
        ),
    )
    parser.add_argument(
        "--exclude-teacher-top5-from-hn",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Also exclude teacher_top5 (in addition to teacher_top3) when auto-injecting hard-negatives. On by default; pass --no-exclude-teacher-top5-from-hn to disable.",
    )
    parser.add_argument(
        "--soft-teacher-topk",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Train teacher_top3/top5 alternatives as fractional positive targets instead of treating every non-top1 move as wrong.",
    )
    parser.add_argument(
        "--soft-teacher-top3-weight",
        type=float,
        default=0.45,
        help="Fractional target strength for teacher_top3 alternatives. Default 0.45.",
    )
    parser.add_argument(
        "--soft-teacher-top5-weight",
        type=float,
        default=0.22,
        help="Fractional target strength for teacher_top5 alternatives outside top3. Default 0.22.",
    )
    parser.add_argument(
        "--pairwise-hard-negative",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Apply a pairwise margin update when current model scores a hard-negative too close to the teacher move.",
    )
    parser.add_argument(
        "--pairwise-margin-cp",
        type=float,
        default=180.0,
        help="Target raw-score margin between teacher move and hard-negative before pairwise updates stop firing.",
    )
    return parser.parse_args()


def _progress(message: str) -> None:
    print(f"[chess-exp5-train] {message}", file=sys.stderr, flush=True)


def _iter_jsonl(path: Path):
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_no}: row must be an object")
        yield payload


def main() -> int:
    args = parse_args()
    input_paths = [Path(item).expanduser().resolve() for item in args.input_jsonl]
    model_path = Path(args.model_path).expanduser().resolve() if args.model_path else default_chess_nnue_model_path()
    replay_path = Path(args.replay_path).expanduser().resolve() if args.replay_path else default_chess_nnue_replay_path()
    _progress(f"target experience model: {model_path}")
    _progress(f"target replay: {replay_path}")
    _progress(f"input files: {len(input_paths)}")
    samples: list[dict] = []
    for input_path in input_paths:
        _progress(f"phase read input: {input_path}")
        before = len(samples)
        samples.extend(_iter_jsonl(input_path))
        _progress(f"phase result read input: {len(samples) - before} rows")
    if args.max_samples and int(args.max_samples) > 0:
        samples = samples[: int(args.max_samples)]
        _progress(f"phase cap samples: {len(samples)} rows")
    auto_hn_topk = max(0, int(args.auto_hard_negative_topk or 0))
    multi_good_margin = max(0.0, float(args.multi_good_margin_cp or 0.0))
    weight_clean = float(args.label_quality_weight_clean)
    weight_review = float(args.label_quality_weight_review)
    weight_questionable = float(args.label_quality_weight_questionable)
    exclude_top5 = bool(args.exclude_teacher_top5_from_hn)

    # Apply label_quality multipliers up-front so the trainer sees the
    # weight-adjusted samples. Rows whose label_quality multiplier is 0 are
    # dropped from the positive-update path entirely.
    #
    # `effective_update_mass_*` measures the actual centipawn-scale weight
    # update that each tier contributes per epoch, accounting for both:
    #   (a) `repeat = max(1, round(weight))` in chess_nnue._train loop, and
    #   (b) `delta = sign * clip(target,-1,1) * clip(weight, 0.1, 8.0) * LR`
    # so reviewers can see whether `--label-quality-weight-review=0.4` actually
    # results in 40% of clean's update strength or is hidden by the rounding.
    _LR = 18.0  # mirrors chess_nnue._LEARNING_RATE
    epochs_effective = max(1, int(args.epochs or 1))
    label_quality_summary = {
        "applied": False,
        "weight_clean": weight_clean,
        "weight_review": weight_review,
        "weight_questionable": weight_questionable,
        "epochs": epochs_effective,
        "rows_clean": 0,
        "rows_review": 0,
        "rows_questionable": 0,
        "rows_unlabeled": 0,
        "rows_dropped_questionable_weight_zero": 0,
        "rows_after_weighting": 0,
        "positive_updates_by_label_quality": {"clean": 0, "review": 0, "questionable": 0, "unlabeled": 0},
        "effective_update_mass_by_label_quality": {"clean": 0.0, "review": 0.0, "questionable": 0.0, "unlabeled": 0.0},
        "review_weight_not_effective": False,
        "_LEARNING_RATE_mirror": _LR,
    }
    weighted_samples: list[dict] = []
    for sample in samples:
        lq = str(sample.get("label_quality") or "").strip().lower()
        original_weight = float(sample.get("weight") or 1.0)
        if lq == "clean":
            label_quality_summary["rows_clean"] += 1
            multiplier = weight_clean
        elif lq == "review":
            label_quality_summary["rows_review"] += 1
            multiplier = weight_review
        elif lq == "questionable":
            label_quality_summary["rows_questionable"] += 1
            multiplier = weight_questionable
        else:
            label_quality_summary["rows_unlabeled"] += 1
            multiplier = 1.0
        if multiplier <= 0.0:
            label_quality_summary["rows_dropped_questionable_weight_zero"] += 1
            label_quality_summary["applied"] = True
            continue
        if lq in {"clean", "review", "questionable"}:
            sample = dict(sample)
            sample["weight"] = original_weight * multiplier
            sample["weight_multiplier_label_quality"] = multiplier
            sample["weight_before_label_quality"] = original_weight
            label_quality_summary["applied"] = True
        # Track expected update count + delta-mass per tier so it's auditable
        # whether the review weight actually translates to smaller updates.
        final_weight = float(sample.get("weight") or 1.0)
        w_for_repeat = max(0.1, min(8.0, final_weight))
        repeat = max(1, int(round(w_for_repeat)))
        delta_per_update = w_for_repeat * _LR
        tier_key = lq if lq in {"clean", "review", "questionable"} else "unlabeled"
        label_quality_summary["positive_updates_by_label_quality"][tier_key] += repeat * epochs_effective
        label_quality_summary["effective_update_mass_by_label_quality"][tier_key] += (
            repeat * delta_per_update * epochs_effective
        )
        weighted_samples.append(sample)
    label_quality_summary["rows_after_weighting"] = len(weighted_samples)
    # Detect the "review weight is hidden by rounding" failure mode the user
    # warned about. If review rows ended up with the SAME effective mass per
    # row as clean rows, the multiplier didn't actually bite.
    rows_clean = label_quality_summary["rows_clean"]
    rows_review = label_quality_summary["rows_review"]
    if rows_clean > 0 and rows_review > 0:
        mass_per_clean = label_quality_summary["effective_update_mass_by_label_quality"]["clean"] / rows_clean
        mass_per_review = label_quality_summary["effective_update_mass_by_label_quality"]["review"] / rows_review
        label_quality_summary["mass_per_row_clean"] = round(mass_per_clean, 4)
        label_quality_summary["mass_per_row_review"] = round(mass_per_review, 4)
        label_quality_summary["mass_per_row_review_to_clean_ratio"] = round(mass_per_review / max(mass_per_clean, 1e-9), 4)
        if mass_per_clean > 0 and mass_per_review / mass_per_clean >= 0.95:
            label_quality_summary["review_weight_not_effective"] = True
    if label_quality_summary["applied"]:
        _progress(
            "phase label-quality weighting applied: "
            f"clean={label_quality_summary['rows_clean']} "
            f"review={label_quality_summary['rows_review']} "
            f"questionable={label_quality_summary['rows_questionable']} "
            f"dropped={label_quality_summary['rows_dropped_questionable_weight_zero']} "
            f"after={label_quality_summary['rows_after_weighting']}"
        )
    samples = weighted_samples

    hn_audit_rows: list[dict] = []
    hn_audit_summary = {
        "auto_hard_negative_topk": auto_hn_topk,
        "multi_good_margin_cp": multi_good_margin,
        "multi_good_margin_units": "raw_policy_score (centipawn-scaled but blended with move-order bonus)",
        "raw_policy_score_scale": "centipawn-ish",
        "hard_negative_injected_count": 0,
        "hard_negative_preexisting_count": 0,
        "hard_negative_overlap_with_teacher_top3_count": 0,
        "hard_negative_excluded_as_multi_good_count": 0,
        "hard_negative_excluded_as_teacher_top3_count": 0,
        "hard_negative_excluded_as_teacher_top5_count": 0,
        "exclude_teacher_top5_from_hn": exclude_top5,
        "samples_with_injection": 0,
        "samples_total": 0,
        "samples_missing_teacher_top3_count": 0,
        "samples_missing_teacher_top5_count": 0,
        "candidate_score_far_above_teacher_count": 0,
        "candidate_score_far_above_teacher_threshold_cp": 250.0,
        "hard_negative_source_model_path": "",
    }
    if auto_hn_topk > 0 and samples:
        hn_source = (
            Path(args.hard_negative_source_model_path).expanduser().resolve()
            if args.hard_negative_source_model_path
            else model_path
        )
        hn_audit_summary["hard_negative_source_model_path"] = str(hn_source)
        _progress(f"phase auto hard-negatives: top{auto_hn_topk} from {hn_source} multi_good_margin={multi_good_margin}cp")
        far_above_threshold = float(hn_audit_summary["candidate_score_far_above_teacher_threshold_cp"])
        for sample in samples:
            hn_audit_summary["samples_total"] += 1
            fen = str(sample.get("fen") or "").strip()
            side = str(sample.get("side") or "").strip().lower()
            teacher_move = str(sample.get("move_uci") or "").strip().lower()
            raw_top3 = sample.get("teacher_top3") or sample.get("teacher_top_moves") or []
            teacher_top3 = {str(item).strip().lower() for item in raw_top3 if str(item).strip()}
            had_teacher_top3 = bool(raw_top3)
            if not had_teacher_top3:
                hn_audit_summary["samples_missing_teacher_top3_count"] += 1
            raw_top5 = sample.get("teacher_top5") or []
            teacher_top5 = {str(item).strip().lower() for item in raw_top5 if str(item).strip()}
            had_teacher_top5 = bool(raw_top5)
            if exclude_top5 and not had_teacher_top5:
                hn_audit_summary["samples_missing_teacher_top5_count"] += 1
            if teacher_move:
                teacher_top3.add(teacher_move)
                teacher_top5.add(teacher_move)
            existing_before = [str(item).strip().lower() for item in (sample.get("hard_negatives") or []) if str(item).strip()]
            audit_row = {
                "fen": fen,
                "side": side,
                "teacher_move": teacher_move,
                "teacher_top3": sorted(teacher_top3),
                "teacher_top5": sorted(teacher_top5) if had_teacher_top5 else [],
                "preexisting_hard_negatives": list(existing_before),
                "injected_hard_negatives": [],
                "excluded_as_multi_good": [],
                "excluded_as_teacher_top3": [],
                "excluded_as_teacher_top5": [],
                "teacher_policy_score": None,
            }
            if not fen or side not in {"white", "black"} or not teacher_move:
                hn_audit_rows.append(audit_row)
                continue
            rows = rank_experiment_nnue_policy_moves(
                {"__fen__": fen},
                side,
                model_path=hn_source,
                search_profile=str(sample.get("search_profile") or "fast"),
            )
            teacher_score: float | None = None
            for row in rows:
                if str(row.get("move") or "").strip().lower() == teacher_move:
                    teacher_score = float(row.get("raw_policy_score") or 0.0)
                    break
            audit_row["teacher_policy_score"] = teacher_score
            audit_row["had_teacher_top3"] = had_teacher_top3
            top1_score = float(rows[0].get("raw_policy_score") or 0.0) if rows else None
            if teacher_score is not None and top1_score is not None:
                if (top1_score - teacher_score) >= far_above_threshold:
                    audit_row["candidate_far_above_teacher"] = True
                    hn_audit_summary["candidate_score_far_above_teacher_count"] += 1
            existing = list(existing_before)
            existing_set = set(existing)
            newly_added: list[str] = []
            for row in rows:
                move = str(row.get("move") or "").strip().lower()
                if not move or move == teacher_move or move in existing_set:
                    continue
                if move in teacher_top3:
                    audit_row["excluded_as_teacher_top3"].append(move)
                    hn_audit_summary["hard_negative_excluded_as_teacher_top3_count"] += 1
                    hn_audit_summary["hard_negative_overlap_with_teacher_top3_count"] += 1
                    continue
                if exclude_top5 and had_teacher_top5 and move in teacher_top5:
                    audit_row["excluded_as_teacher_top5"].append(move)
                    hn_audit_summary["hard_negative_excluded_as_teacher_top5_count"] += 1
                    continue
                if teacher_score is not None and multi_good_margin > 0.0:
                    candidate_score = float(row.get("raw_policy_score") or 0.0)
                    if abs(candidate_score - teacher_score) <= multi_good_margin:
                        audit_row["excluded_as_multi_good"].append(move)
                        hn_audit_summary["hard_negative_excluded_as_multi_good_count"] += 1
                        continue
                existing.append(move)
                existing_set.add(move)
                newly_added.append(move)
                if len(newly_added) >= auto_hn_topk:
                    break
            sample["hard_negatives"] = existing
            audit_row["injected_hard_negatives"] = newly_added
            hn_audit_summary["hard_negative_injected_count"] += len(newly_added)
            hn_audit_summary["hard_negative_preexisting_count"] += len(existing_before)
            if newly_added:
                hn_audit_summary["samples_with_injection"] += 1
            hn_audit_rows.append(audit_row)
        _progress(
            "phase auto hard-negatives summary: "
            f"injected={hn_audit_summary['hard_negative_injected_count']} "
            f"preexisting={hn_audit_summary['hard_negative_preexisting_count']} "
            f"excluded_top3={hn_audit_summary['hard_negative_excluded_as_teacher_top3_count']} "
            f"excluded_multi_good={hn_audit_summary['hard_negative_excluded_as_multi_good_count']}"
        )
    if args.hard_negative_audit_path:
        audit_path = Path(args.hard_negative_audit_path).expanduser().resolve()
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("w", encoding="utf-8") as handle:
            for row in hn_audit_rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        hn_audit_summary["hard_negative_audit_path"] = str(audit_path)
    result = train_experiment_nnue_from_replay_samples(
        samples,
        model_path=model_path,
        replay_path=replay_path,
        replace_replay=bool(args.replace_replay),
        epochs=max(1, int(args.epochs or 1)),
        soft_teacher_topk=bool(args.soft_teacher_topk),
        soft_teacher_top3_weight=float(args.soft_teacher_top3_weight),
        soft_teacher_top5_weight=float(args.soft_teacher_top5_weight),
        pairwise_hard_negative=bool(args.pairwise_hard_negative),
        pairwise_margin_cp=float(args.pairwise_margin_cp),
    )
    result["input_rows"] = len(samples)
    result["auto_hard_negative_topk"] = auto_hn_topk
    result["epochs_requested"] = max(1, int(args.epochs or 1))
    result["hard_negative_audit_summary"] = hn_audit_summary
    result["label_quality_weighting"] = label_quality_summary
    result["strength_validation_supported"] = False
    result["promotion_gate_supported"] = False
    result["next_design_required"] = "exp5-specific deterministic strength evaluator and promotion gate"
    _progress(f"phase result train: ok artifact={model_path} replay={replay_path}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _progress(f"FAIL: {exc}")
        _progress("failure hint: check input JSONL schema and target model/replay path permissions")
        raise
