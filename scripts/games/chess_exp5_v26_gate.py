#!/usr/bin/env python3
"""Redacted V26 acceptance gate for Exp5 percent-tail validation.

This script compares aggregate validation summaries only. It intentionally
does not read or emit FENs, moves, teacher PVs, source game identifiers, or
per-position answers.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PRIMARY_SECTIONS = ("complete_game", "tail50pct", "tail25pct")
DEFAULT_REDUCTION = 0.10


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return data


def _summary(data: dict[str, Any]) -> dict[str, Any]:
    summary = data.get("summary")
    if not isinstance(summary, dict):
        raise SystemExit("evaluation JSON is missing object field: summary")
    by_section = summary.get("by_section")
    if not isinstance(by_section, dict):
        raise SystemExit("evaluation JSON is missing object field: summary.by_section")
    return summary


def _profile(data: dict[str, Any]) -> str:
    return str(data.get("profile") or "unknown")


def _section(summary: dict[str, Any], name: str) -> dict[str, Any]:
    by_section = summary.get("by_section")
    if not isinstance(by_section, dict):
        return {}
    item = by_section.get(name)
    return item if isinstance(item, dict) else {}


def _count(section: dict[str, Any], key: str) -> int:
    try:
        return int(section.get(key) or 0)
    except Exception:
        return 0


def _rate(section: dict[str, Any], key: str) -> float:
    try:
        return round(float(section.get(key) or 0.0), 6)
    except Exception:
        return 0.0


def _max_rejected_threshold(baseline_count: int, reduction: float) -> int:
    return int(float(baseline_count) * max(0.0, min(1.0, 1.0 - reduction)))


def _section_gate(
    *,
    section_name: str,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    reduction: float,
) -> dict[str, Any]:
    baseline_rejected = _count(baseline, "rejected")
    candidate_rejected = _count(candidate, "rejected")
    threshold = _max_rejected_threshold(baseline_rejected, reduction)
    return {
        "section": section_name,
        "baseline_rejected": baseline_rejected,
        "candidate_rejected": candidate_rejected,
        "delta_rejected": candidate_rejected - baseline_rejected,
        "required_max_rejected": threshold,
        "passed": candidate_rejected <= threshold,
        "baseline_clean_rate": _rate(baseline, "clean_rate"),
        "candidate_clean_rate": _rate(candidate, "clean_rate"),
        "baseline_review_or_better_rate": _rate(baseline, "review_or_better_rate"),
        "candidate_review_or_better_rate": _rate(candidate, "review_or_better_rate"),
        "baseline_top5_rate": _rate(baseline, "top5_rate"),
        "candidate_top5_rate": _rate(candidate, "top5_rate"),
        "baseline_avg_elapsed_ms": _rate(baseline, "avg_elapsed_ms"),
        "candidate_avg_elapsed_ms": _rate(candidate, "avg_elapsed_ms"),
    }


def _taxonomy_search_miss(taxonomy_path: Path | None) -> dict[str, int]:
    if taxonomy_path is None:
        return {}
    data = _load_json(taxonomy_path)
    summary = data.get("summary")
    if not isinstance(summary, dict):
        return {}
    by_section = summary.get("by_section")
    if not isinstance(by_section, dict):
        return {}
    result: dict[str, int] = {}
    for section_name, section in by_section.items():
        if not isinstance(section, dict):
            continue
        actionability = section.get("actionability")
        if not isinstance(actionability, dict):
            continue
        try:
            result[str(section_name)] = int(actionability.get("candidate_generation_or_search_miss") or 0)
        except Exception:
            result[str(section_name)] = 0
    return result


def _write_markdown(path: Path, gate: dict[str, Any]) -> None:
    lines = [
        "# Exp5 V26 Gate",
        "",
        "This report is redacted: it contains no FENs, moves, teacher PVs, source game identifiers, or per-position answers.",
        "",
        f"- Baseline: `{gate['baseline']['profile']}`",
        f"- Candidate: `{gate['candidate']['profile']}`",
        f"- Primary objective: `{gate['primary_objective']}`",
        f"- Accepted: `{gate['accepted']}`",
        "",
        "## Rejected Gates",
        "",
        "| Section | Baseline rejected | Candidate rejected | Delta | Required max | Passed |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in gate["section_gates"]:
        lines.append(
            "| {section} | {baseline_rejected} | {candidate_rejected} | {delta_rejected} | {required_max_rejected} | {passed} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "## Secondary Metrics",
            "",
            f"- Total rejected baseline/candidate: `{gate['baseline']['summary']['rejected']}` / `{gate['candidate']['summary']['rejected']}`",
            f"- Clean rate baseline/candidate: `{gate['baseline']['summary']['clean_rate']}` / `{gate['candidate']['summary']['clean_rate']}`",
            f"- Review+ rate baseline/candidate: `{gate['baseline']['summary']['review_or_better_rate']}` / `{gate['candidate']['summary']['review_or_better_rate']}`",
            f"- Top5 rate baseline/candidate: `{gate['baseline']['summary']['top5_rate']}` / `{gate['candidate']['summary']['top5_rate']}`",
            "",
            "## Anti-Leakage",
            "",
        ]
    )
    for key, value in gate["anti_leakage"].items():
        lines.append(f"- `{key}`: `{value}`")
    if gate.get("candidate_search_miss_delta"):
        lines.extend(["", "## Candidate/Search Miss", ""])
        for section, row in sorted(gate["candidate_search_miss_delta"].items()):
            lines.append(
                f"- `{section}`: baseline `{row['baseline']}`, candidate `{row['candidate']}`, delta `{row['delta']}`"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_gate(args: argparse.Namespace) -> dict[str, Any]:
    baseline_data = _load_json(Path(args.baseline_eval_json))
    candidate_data = _load_json(Path(args.candidate_eval_json))
    baseline_summary = _summary(baseline_data)
    candidate_summary = _summary(candidate_data)
    reduction = float(args.rejected_reduction)

    section_gates = [
        _section_gate(
            section_name=section_name,
            baseline=_section(baseline_summary, section_name),
            candidate=_section(candidate_summary, section_name),
            reduction=reduction,
        )
        for section_name in PRIMARY_SECTIONS
    ]

    baseline_search_miss = _taxonomy_search_miss(Path(args.baseline_taxonomy_json)) if args.baseline_taxonomy_json else {}
    candidate_search_miss = _taxonomy_search_miss(Path(args.candidate_taxonomy_json)) if args.candidate_taxonomy_json else {}
    search_miss_delta: dict[str, dict[str, int]] = {}
    for section_name in sorted(set(baseline_search_miss) | set(candidate_search_miss)):
        baseline_count = baseline_search_miss.get(section_name, 0)
        candidate_count = candidate_search_miss.get(section_name, 0)
        search_miss_delta[section_name] = {
            "baseline": baseline_count,
            "candidate": candidate_count,
            "delta": candidate_count - baseline_count,
        }

    candidate_search_miss_passed = True
    for section_name in PRIMARY_SECTIONS:
        if section_name in search_miss_delta and search_miss_delta[section_name]["delta"] > 0:
            candidate_search_miss_passed = False

    gate = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": "scripts/games/chess_exp5_v26_gate.py",
        "kind": "redacted_exp5_v26_gate",
        "baseline": {
            "path": str(args.baseline_eval_json),
            "profile": _profile(baseline_data),
            "summary": {
                "positions": int(baseline_summary.get("positions") or 0),
                "clean_rate": _rate(baseline_summary, "clean_rate"),
                "review_or_better_rate": _rate(baseline_summary, "review_or_better_rate"),
                "top5_rate": _rate(baseline_summary, "top5_rate"),
                "rejected": int(baseline_summary.get("rejected") or 0),
            },
        },
        "candidate": {
            "path": str(args.candidate_eval_json),
            "profile": _profile(candidate_data),
            "summary": {
                "positions": int(candidate_summary.get("positions") or 0),
                "clean_rate": _rate(candidate_summary, "clean_rate"),
                "review_or_better_rate": _rate(candidate_summary, "review_or_better_rate"),
                "top5_rate": _rate(candidate_summary, "top5_rate"),
                "rejected": int(candidate_summary.get("rejected") or 0),
            },
        },
        "primary_objective": "weak_slice_rejected_reduction",
        "thresholds": {
            "rejected_reduction": reduction,
            "complete_game_rejected_max": _max_rejected_threshold(_count(_section(baseline_summary, "complete_game"), "rejected"), reduction),
            "tail50pct_rejected_max": _max_rejected_threshold(_count(_section(baseline_summary, "tail50pct"), "rejected"), reduction),
            "tail25pct_rejected_max": _max_rejected_threshold(_count(_section(baseline_summary, "tail25pct"), "rejected"), reduction),
            "gauntlet_losses_max": int(args.gauntlet_losses_max),
            "human_trap_clean_min": float(args.human_trap_clean_min),
        },
        "section_gates": section_gates,
        "candidate_search_miss_delta": search_miss_delta,
        "candidate_search_miss_passed": candidate_search_miss_passed,
        "gauntlet": {
            "status": "not_checked_by_this_script",
            "losses_max": int(args.gauntlet_losses_max),
        },
        "human_trap_guardrail": {
            "status": "not_in_percent_tail_validation_set",
            "clean_min": float(args.human_trap_clean_min),
        },
        "anti_leakage": {
            "no_fen": True,
            "no_moves": True,
            "no_teacher_pv": True,
            "no_source_game_ids": True,
            "no_exact_memory_or_position_lookup": True,
            "public_outputs_are_aggregate_only": True,
        },
    }
    gate["accepted"] = bool(
        all(row["passed"] for row in section_gates)
        and candidate_search_miss_passed
    )
    return gate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-eval-json", required=True)
    parser.add_argument("--candidate-eval-json", required=True)
    parser.add_argument("--baseline-taxonomy-json")
    parser.add_argument("--candidate-taxonomy-json")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--report-md")
    parser.add_argument("--rejected-reduction", type=float, default=DEFAULT_REDUCTION)
    parser.add_argument("--human-trap-clean-min", type=float, default=0.96)
    parser.add_argument("--gauntlet-losses-max", type=int, default=0)
    args = parser.parse_args()

    gate = build_gate(args)
    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.report_md:
        _write_markdown(Path(args.report_md), gate)
    print(json.dumps({"accepted": gate["accepted"], "candidate": gate["candidate"]["profile"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
