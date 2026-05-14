#!/usr/bin/env python3
"""Aggregate per-stage summaries into one pipeline report (W6 commit 2).

Reads a list of ``summary.json`` files (or dry-run payload JSON files) from
the individual stages of the replay/training pipeline and emits a single
``pipeline_summary.json`` + ``PIPELINE_SUMMARY.md`` that answers:

  * Which stages ran?
  * What artefacts did each stage produce?
  * Was any stage non-dry-run? Did any stage mutate the production runtime
    model?
  * What is the next-step staging command (if dry-run validation passed)?

The aggregator never executes any pipeline stage. It is a pure reader: feed
it the summary files; get back a unified view. No model writes, no DB
writes, no subprocess of pipeline tools.

Detection is heuristic by structural fingerprint, so adding a new stage
type later is a matter of adding one more recogniser.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.games.external_replay_safety import serialize_json_payload  # noqa: E402


STAGE_PVP_EXPORT = "pvp_export"
STAGE_SPARRING_RUN = "sparring_run"
STAGE_SEED_TRAIN_DRY_RUN = "seed_train_dry_run"
STAGE_SPARRING_TO_REPLAY = "sparring_to_replay"
STAGE_PGN_TO_REPLAY = "pgn_to_replay"
STAGE_PGN_TEACHER_AUDIT = "pgn_teacher_audit"
STAGE_UNKNOWN = "unknown"

_KNOWN_STAGES = {
    STAGE_PVP_EXPORT,
    STAGE_SPARRING_RUN,
    STAGE_SEED_TRAIN_DRY_RUN,
    STAGE_SPARRING_TO_REPLAY,
    STAGE_PGN_TO_REPLAY,
    STAGE_PGN_TEACHER_AUDIT,
}

# Trusted-source name reserved for raw PGN-derived rows that have NOT
# passed the W8 teacher audit. Seeing this name inside a seed_train
# dry-run stage's load_stats means an unaudited row reached training,
# which the aggregator surfaces as a dedicated invariant.
_UNAUDITED_IMPORTED_DATASET = "imported_dataset"


def detect_stage(payload: dict) -> str:
    """Return a stage identifier for a raw summary/payload dict."""
    if not isinstance(payload, dict):
        return STAGE_UNKNOWN
    # Self-stamped 'stage' field wins over structural fingerprinting
    # (W7+ convention; older stages don't set this so the fingerprint
    # path below is still authoritative for them).
    explicit = payload.get("stage")
    if isinstance(explicit, str) and explicit in _KNOWN_STAGES:
        return explicit
    # seed_train dry-run payload
    if "external_replay" in payload and "dry_run" in payload:
        return STAGE_SEED_TRAIN_DRY_RUN
    # sparring runner summary (from chess_exp4_vs_exp5_sparring).
    # Field name evolved: legacy "wdl" was renamed to "raw_outcome" in W4.1b
    # (commit b4affc8). Accept either so the aggregator works against both
    # pre- and post-rename run dirs without flagging them as unknown.
    if "objective_summary" in payload and "meta" in payload and (
        "wdl" in payload or "raw_outcome" in payload
    ):
        return STAGE_SPARRING_RUN
    counts = payload.get("counts") if isinstance(payload, dict) else None
    if isinstance(counts, dict):
        if "matches_accepted_pvp_filtered" in counts:
            return STAGE_PVP_EXPORT
        if "games_accepted" in counts and "samples_emitted" in counts:
            return STAGE_SPARRING_TO_REPLAY
    return STAGE_UNKNOWN


def _safe_get(d: dict, *path, default=None):
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def normalize_stage(payload: dict, *, source_path: str = "") -> dict:
    """Reduce one raw summary/payload to the aggregator's view.

    Returns a dict shaped like:
      {
        "stage": <type>,
        "source_path": <path>,
        "timestamp": ...,
        "output_dir": ...,
        "diagnostic_only": bool,
        "production_runtime_mutation": bool,
        "model_mutation_in_this_stage": bool,
        "key_metrics": {...stage-specific...},
        "notes": [optional warnings],
      }
    """
    stage = detect_stage(payload)
    base = {
        "stage": stage,
        "source_path": source_path,
        "timestamp": payload.get("timestamp", "") if isinstance(payload, dict) else "",
        "output_dir": payload.get("output_dir", "") if isinstance(payload, dict) else "",
        "diagnostic_only": True,
        "production_runtime_mutation": False,
        "model_mutation_in_this_stage": False,
        "key_metrics": {},
        "notes": [],
    }

    if stage == STAGE_PVP_EXPORT:
        counts = dict(payload.get("counts") or {})
        policy = dict(payload.get("policy") or {})
        base["diagnostic_only"] = bool(policy.get("diagnostic_only", True))
        base["production_runtime_mutation"] = bool(policy.get("production_runtime_mutation"))
        base["key_metrics"] = {
            "matches_total": counts.get("matches_total", 0),
            "matches_accepted_pvp_filtered": counts.get("matches_accepted_pvp_filtered", 0),
            "matches_accepted_human_beat_engine": counts.get("matches_accepted_human_beat_engine", 0),
            "matches_rejected": counts.get("matches_rejected", 0),
            "samples_pvp_filtered": counts.get("samples_pvp_filtered", 0),
            "samples_human_beat_engine": counts.get("samples_human_beat_engine", 0),
            "reject_reasons": dict(counts.get("reject_reasons") or {}),
            "quality_union_size": _safe_get(payload, "quality_signal", "union_size", default=0),
        }
        return base

    if stage == STAGE_SPARRING_RUN:
        meta = dict(payload.get("meta") or {})
        wdl = dict(payload.get("wdl") or payload.get("raw_outcome") or {})
        obj = dict(payload.get("objective_summary") or {})
        base["output_dir"] = meta.get("output_dir", "") or base["output_dir"]
        base["timestamp"] = meta.get("timestamp", "") or base["timestamp"]
        # Sparring is read-only on production model — only writes its own
        # artifacts, not bundled / runtime defaults.
        base["diagnostic_only"] = bool(meta.get("diagnostic_only", True))
        base["production_runtime_mutation"] = False
        base["key_metrics"] = {
            "exp4_model_path": meta.get("exp4_model_path", ""),
            "exp5_model_path": meta.get("exp5_model_path", ""),
            "mode": meta.get("mode", ""),
            "seeds_played": list(meta.get("seeds_played") or []),
            "wdl": wdl,
            "strength_counted_outcome": dict(payload.get("strength_counted_outcome") or {}),
            "objective_summary": obj,
            "illegal_count": payload.get("illegal_count", 0),
            "suspicious_count": payload.get("suspicious_count", 0),
        }
        return base

    if stage == STAGE_SEED_TRAIN_DRY_RUN:
        er = dict(payload.get("external_replay") or {})
        load_stats = dict(er.get("load_stats") or {})
        cap_stats = dict(er.get("cap_stats") or {})
        nv = dict(er.get("normalize_validation") or {})
        train = dict(er.get("train_result") or {})
        is_dry_run = bool(payload.get("dry_run"))
        # The model_mutation_in_this_stage flag is True iff training actually
        # ran — i.e. NOT dry-run AND trained_exp4 or trained_exp5.
        trained_any = bool(train.get("trained_exp4")) or bool(train.get("trained_exp5"))
        base["diagnostic_only"] = is_dry_run
        base["model_mutation_in_this_stage"] = (not is_dry_run) and trained_any
        # Whether the explicit model paths were defaults is captured by the
        # safety contract before main(); if the aggregator sees a non-dry-run
        # that trained anything, flag it for operator review.
        if base["model_mutation_in_this_stage"]:
            base["notes"].append(
                "non-dry-run training executed; verify model paths are staging, "
                "not bundled / runtime defaults"
            )
        artifact = str(payload.get("dry_run_artifact") or "")
        source_breakdown = dict(load_stats.get("source_breakdown_raw") or {})
        base["key_metrics"] = {
            "dry_run": is_dry_run,
            "skip_exp4": bool(er.get("skip_exp4")),
            "skip_exp5": bool(er.get("skip_exp5")),
            "files_read": load_stats.get("files_read", 0),
            "rows_total": load_stats.get("rows_total", 0),
            "rows_kept": load_stats.get("rows_kept", 0),
            "total_kept_after_caps": cap_stats.get("total_kept", 0),
            "exp4_ok": nv.get("exp4_ok", 0),
            "exp4_failed": nv.get("exp4_failed", 0),
            "exp5_ok": nv.get("exp5_ok", 0),
            "exp5_failed": nv.get("exp5_failed", 0),
            "train_skipped_reason": train.get("skipped_reason", ""),
            "trained_exp4": bool(train.get("trained_exp4")),
            "trained_exp5": bool(train.get("trained_exp5")),
            "dry_run_artifact": artifact,
            "source_breakdown_raw": source_breakdown,
        }
        return base

    if stage == STAGE_PGN_TEACHER_AUDIT:
        counts = dict(payload.get("counts") or {})
        policy = dict(payload.get("policy") or {})
        base["diagnostic_only"] = bool(policy.get("diagnostic_only", True))
        base["key_metrics"] = {
            "audit_profile": payload.get("audit_profile", ""),
            "top_k": payload.get("top_k", 0),
            "weight_cap": payload.get("weight_cap", 0),
            "exp4_teacher_used": bool(payload.get("exp4_teacher_used")),
            "exp5_teacher_used": bool(payload.get("exp5_teacher_used")),
            "input_rows": counts.get("input_rows", 0),
            "accepted_rows": counts.get("accepted_rows", 0),
            "review_rows": counts.get("review_rows", 0),
            "rejected_rows": counts.get("rejected_rows", 0),
            "duplicates_dropped": counts.get("duplicates_dropped", 0),
            "by_reason_review": dict(counts.get("by_reason_review") or {}),
            "by_reason_rejected": dict(counts.get("by_reason_rejected") or {}),
            "accepted_jsonl": payload.get("accepted_jsonl", ""),
            "audited_trusted_source": policy.get("audited_trusted_source", ""),
        }
        return base

    if stage == STAGE_SPARRING_TO_REPLAY:
        counts = dict(payload.get("counts") or {})
        policy = dict(payload.get("policy") or {})
        base["diagnostic_only"] = bool(policy.get("diagnostic_only", True))
        base["key_metrics"] = {
            "games_total": counts.get("games_total", 0),
            "games_accepted": counts.get("games_accepted", 0),
            "games_rejected": counts.get("games_rejected", 0),
            "samples_emitted": counts.get("samples_emitted", 0),
            "reject_reasons": dict(counts.get("reject_reasons") or {}),
            "run_dir": payload.get("run_dir", ""),
        }
        return base

    if stage == STAGE_PGN_TO_REPLAY:
        counts = dict(payload.get("counts") or {})
        policy = dict(payload.get("policy") or {})
        base["diagnostic_only"] = bool(policy.get("diagnostic_only", True))
        base["key_metrics"] = {
            "pgn_paths_processed": counts.get("pgn_paths_processed", 0),
            "source_urls_processed": counts.get("source_urls_processed", 0),
            "prepared_jsonls_attached": counts.get("prepared_jsonls_attached", 0),
            "games_imported": counts.get("games_imported", 0),
            "per_ply_samples_emitted": counts.get("per_ply_samples_emitted", 0),
            "output_jsonls": list(payload.get("output_jsonls") or []),
            "input_pgn_paths": list(payload.get("input_pgn_paths") or []),
            "input_source_urls": list(payload.get("input_source_urls") or []),
            "download_dir": payload.get("download_dir", ""),
            "raw_internet_download": bool(policy.get("raw_internet_download")),
            "audit_gate_required": bool(policy.get("audit_gate_required", True)),
        }
        return base

    base["notes"].append("stage type not recognised by aggregator")
    return base


def compute_invariants(stages: list[dict]) -> dict:
    """Cross-stage invariants the operator should be able to assert at-a-glance."""
    # W8: surface whether any seed_train stage loaded the unaudited
    # ``imported_dataset`` trusted-source name. That bucket only exists
    # if W8 commit 2's --include-unaudited-pgn-in-dryrun-diagnostic
    # override was used, so the invariant flips True for diagnostic
    # runs and stays False for the safe default flow.
    unaudited_used = False
    for s in stages:
        if s.get("stage") != STAGE_SEED_TRAIN_DRY_RUN:
            continue
        breakdown = (s.get("key_metrics") or {}).get("source_breakdown_raw") or {}
        if isinstance(breakdown, dict) and int(breakdown.get(_UNAUDITED_IMPORTED_DATASET, 0) or 0) > 0:
            unaudited_used = True
            break
    # W9: surface whether any pgn_to_replay stage downloaded from the
    # network. Even when True the audit gate (stage 00b) still runs;
    # the invariant exists so a reviewer can see at-a-glance that
    # network content reached the pipeline and decide whether the
    # provenance is acceptable.
    network_pgn_download = any(
        s.get("stage") == STAGE_PGN_TO_REPLAY
        and (s.get("key_metrics") or {}).get("raw_internet_download")
        for s in stages
    )
    return {
        "all_stages_diagnostic_only": all(s.get("diagnostic_only", True) for s in stages),
        "any_production_runtime_mutation": any(
            s.get("production_runtime_mutation") for s in stages
        ),
        "any_model_mutation": any(s.get("model_mutation_in_this_stage") for s in stages),
        "unaudited_imported_dataset_used_for_seed_train": unaudited_used,
        "any_network_pgn_download": network_pgn_download,
        "stage_count": len(stages),
        "stages_seen": sorted({s["stage"] for s in stages}),
    }


def build_pipeline_summary(
    stages: list[dict],
    *,
    next_step_command: str = "",
) -> dict:
    invariants = compute_invariants(stages)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stages": stages,
        "invariants": invariants,
        "next_step_command": next_step_command,
        "policy": {
            "aggregator_writes_no_models": True,
            "aggregator_writes_no_db": True,
            "aggregator_executes_no_stage": True,
        },
    }


def render_markdown(summary: dict) -> str:
    inv = summary.get("invariants") or {}
    lines: list[str] = [
        "# Chess pipeline aggregated report",
        "",
        f"- generated_at: {summary['generated_at']}",
        f"- stage_count: {inv.get('stage_count', 0)}",
        f"- stages_seen: {', '.join(inv.get('stages_seen') or ['(none)'])}",
        "",
        "## Cross-stage invariants",
        f"- all_stages_diagnostic_only: {inv.get('all_stages_diagnostic_only')}",
        f"- any_production_runtime_mutation: {inv.get('any_production_runtime_mutation')}",
        f"- any_model_mutation: {inv.get('any_model_mutation')}",
        "",
        "## Per-stage detail",
    ]
    for idx, st in enumerate(summary.get("stages") or [], start=1):
        lines.append("")
        lines.append(f"### {idx}. {st.get('stage')}")
        lines.append(f"- source_path: {st.get('source_path') or '(inline payload)'}")
        if st.get("timestamp"):
            lines.append(f"- timestamp: {st['timestamp']}")
        if st.get("output_dir"):
            lines.append(f"- output_dir: {st['output_dir']}")
        lines.append(f"- diagnostic_only: {st.get('diagnostic_only')}")
        lines.append(
            f"- model_mutation_in_this_stage: {st.get('model_mutation_in_this_stage')}"
        )
        for k, v in (st.get("key_metrics") or {}).items():
            if isinstance(v, (dict, list)):
                v = json.dumps(v, sort_keys=True, ensure_ascii=False)
            lines.append(f"  - {k}: {v}")
        for note in st.get("notes") or []:
            lines.append(f"- note: {note}")
    if summary.get("next_step_command"):
        lines.extend([
            "",
            "## Suggested next step (NOT executed)",
            "```",
            summary["next_step_command"],
            "```",
        ])
    lines.extend([
        "",
        "## Aggregator policy",
        "- aggregator_writes_no_models = True",
        "- aggregator_writes_no_db = True",
        "- aggregator_executes_no_stage = True",
        "",
    ])
    return "\n".join(lines) + "\n"


def load_payloads(paths: list[str | Path]) -> list[tuple[str, dict]]:
    """Read each path as JSON. Skip missing files with a stderr warning."""
    out: list[tuple[str, dict]] = []
    for raw in paths:
        p = Path(raw).expanduser().resolve()
        if not p.exists():
            print(f"[WARN] summary not found: {p}", file=sys.stderr)
            continue
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[WARN] failed to parse {p}: {exc!r}", file=sys.stderr)
            continue
        out.append((str(p), payload))
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Aggregate per-stage summaries into one pipeline report."
    )
    p.add_argument(
        "--summary-path",
        action="append",
        default=[],
        help="Path to a stage's summary.json or dry-run JSON. Repeatable.",
    )
    p.add_argument(
        "--output-dir",
        required=True,
        help="Directory to write pipeline_summary.json + PIPELINE_SUMMARY.md.",
    )
    p.add_argument(
        "--next-step-command",
        default="",
        help="Optional command string to include verbatim as the suggested next step.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.summary_path:
        raise SystemExit("error: at least one --summary-path is required")
    payloads = load_payloads(args.summary_path)
    if not payloads:
        raise SystemExit("error: no readable summaries to aggregate")
    stages = [normalize_stage(p, source_path=path) for path, p in payloads]
    summary = build_pipeline_summary(stages, next_step_command=args.next_step_command)

    out_dir = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "pipeline_summary.json").write_text(
        serialize_json_payload(summary), encoding="utf-8"
    )
    (out_dir / "PIPELINE_SUMMARY.md").write_text(render_markdown(summary), encoding="utf-8")
    print(f"wrote: {out_dir / 'pipeline_summary.json'}")
    print(f"wrote: {out_dir / 'PIPELINE_SUMMARY.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
