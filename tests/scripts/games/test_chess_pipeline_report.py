"""Tests for scripts/games/chess_pipeline_report.py (W6 commit 2).

Covers stage detection, normalisation, invariants, markdown rendering, and
a subprocess --help smoke. The aggregator is pure — these tests should
fail loud if any stage shape silently drifts.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.games.chess_pipeline_report import (
    STAGE_PGN_TEACHER_AUDIT,
    STAGE_PGN_TO_REPLAY,
    STAGE_PVP_EXPORT,
    STAGE_SEED_TRAIN_DRY_RUN,
    STAGE_SPARRING_RUN,
    STAGE_SPARRING_TO_REPLAY,
    STAGE_UNKNOWN,
    build_pipeline_summary,
    compute_invariants,
    detect_stage,
    load_payloads,
    normalize_stage,
    render_markdown,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "games" / "chess_pipeline_report.py"


# ---- detect_stage ------------------------------------------------------


def test_detect_pvp_export_by_matches_accepted_pvp_filtered():
    payload = {"counts": {"matches_total": 6, "matches_accepted_pvp_filtered": 1}}
    assert detect_stage(payload) == STAGE_PVP_EXPORT


def test_detect_sparring_run_by_objective_summary_meta_wdl():
    payload = {"objective_summary": {}, "meta": {}, "wdl": {}}
    assert detect_stage(payload) == STAGE_SPARRING_RUN


def test_detect_sparring_run_accepts_raw_outcome_alias():
    """W4.1b renamed 'wdl' to 'raw_outcome' (commit b4affc8); aggregator
    must recognise either to stay robust against pre/post-rename runs."""
    payload = {"objective_summary": {}, "meta": {}, "raw_outcome": {}}
    assert detect_stage(payload) == STAGE_SPARRING_RUN


def test_detect_seed_train_dry_run_by_external_replay_and_dry_run():
    payload = {"external_replay": {}, "dry_run": True}
    assert detect_stage(payload) == STAGE_SEED_TRAIN_DRY_RUN


def test_detect_sparring_to_replay_by_games_accepted_and_samples_emitted():
    payload = {"counts": {"games_accepted": 1, "samples_emitted": 1, "games_total": 12}}
    assert detect_stage(payload) == STAGE_SPARRING_TO_REPLAY


def test_detect_pgn_to_replay_by_self_stamped_stage_field():
    payload = {"stage": "pgn_to_replay", "counts": {"per_ply_samples_emitted": 16}}
    assert detect_stage(payload) == STAGE_PGN_TO_REPLAY


def test_detect_ignores_unrecognised_stage_field_and_falls_through():
    payload = {"stage": "totally_made_up", "counts": {"matches_accepted_pvp_filtered": 1}}
    assert detect_stage(payload) == STAGE_PVP_EXPORT


def test_normalize_pgn_to_replay_extracts_metrics():
    payload = {
        "stage": "pgn_to_replay",
        "timestamp": "2026-05-12T12:00:00+00:00",
        "output_dir": "/x",
        "input_pgn_paths": ["/x/games.pgn"],
        "output_jsonls": ["/x/per_ply.jsonl"],
        "counts": {
            "pgn_paths_processed": 1,
            "prepared_jsonls_attached": 0,
            "games_imported": 2,
            "per_ply_samples_emitted": 16,
        },
        "policy": {
            "diagnostic_only": True,
            "production_runtime_mutation": False,
            "raw_internet_download": False,
        },
    }
    out = normalize_stage(payload)
    assert out["stage"] == STAGE_PGN_TO_REPLAY
    assert out["diagnostic_only"] is True
    assert out["model_mutation_in_this_stage"] is False
    m = out["key_metrics"]
    assert m["pgn_paths_processed"] == 1
    assert m["games_imported"] == 2
    assert m["per_ply_samples_emitted"] == 16
    assert m["raw_internet_download"] is False
    assert m["output_jsonls"] == ["/x/per_ply.jsonl"]


def test_detect_unknown_for_empty_payload():
    assert detect_stage({}) == STAGE_UNKNOWN


def test_detect_unknown_for_non_dict():
    assert detect_stage(None) == STAGE_UNKNOWN
    assert detect_stage("string") == STAGE_UNKNOWN


# ---- normalize_stage ---------------------------------------------------


def test_normalize_pvp_export_extracts_metrics():
    payload = {
        "timestamp": "2026-05-12T09:17:40+00:00",
        "output_dir": "/x",
        "counts": {
            "matches_total": 6,
            "matches_accepted_pvp_filtered": 1,
            "matches_accepted_human_beat_engine": 1,
            "matches_rejected": 4,
            "samples_pvp_filtered": 12,
            "samples_human_beat_engine": 12,
            "reject_reasons": {"no_player_quality:black": 1},
        },
        "quality_signal": {"union_size": 2},
        "policy": {"diagnostic_only": True, "production_runtime_mutation": False},
    }
    out = normalize_stage(payload, source_path="/x/summary.json")
    assert out["stage"] == STAGE_PVP_EXPORT
    assert out["source_path"] == "/x/summary.json"
    assert out["diagnostic_only"] is True
    assert out["production_runtime_mutation"] is False
    assert out["model_mutation_in_this_stage"] is False
    m = out["key_metrics"]
    assert m["matches_total"] == 6
    assert m["matches_accepted_pvp_filtered"] == 1
    assert m["matches_accepted_human_beat_engine"] == 1
    assert m["samples_pvp_filtered"] == 12
    assert m["quality_union_size"] == 2
    assert m["reject_reasons"]["no_player_quality:black"] == 1


def test_normalize_seed_train_dry_run_marks_no_mutation():
    payload = {
        "dry_run": True,
        "external_replay": {
            "load_stats": {"files_read": 1, "rows_total": 24, "rows_kept": 24},
            "cap_stats": {"total_kept": 24},
            "normalize_validation": {"exp4_ok": 24, "exp4_failed": 0, "exp5_ok": 24, "exp5_failed": 0},
            "train_result": {"skipped_reason": "dry_run", "trained_exp4": False, "trained_exp5": False},
            "skip_exp4": False,
            "skip_exp5": False,
        },
        "dry_run_artifact": "/tmp/dr.json",
    }
    out = normalize_stage(payload)
    assert out["stage"] == STAGE_SEED_TRAIN_DRY_RUN
    assert out["diagnostic_only"] is True
    assert out["model_mutation_in_this_stage"] is False
    m = out["key_metrics"]
    assert m["dry_run"] is True
    assert m["rows_kept"] == 24
    assert m["total_kept_after_caps"] == 24
    assert m["exp4_failed"] == 0
    assert m["exp5_failed"] == 0
    assert m["train_skipped_reason"] == "dry_run"
    assert m["dry_run_artifact"] == "/tmp/dr.json"


def test_normalize_seed_train_non_dry_run_flags_mutation():
    payload = {
        "dry_run": False,
        "external_replay": {
            "load_stats": {"rows_kept": 10},
            "cap_stats": {"total_kept": 10},
            "normalize_validation": {"exp4_ok": 10, "exp4_failed": 0, "exp5_ok": 10, "exp5_failed": 0},
            "train_result": {"skipped_reason": "", "trained_exp4": True, "trained_exp5": False},
        },
        "dry_run_artifact": "",
    }
    out = normalize_stage(payload)
    assert out["diagnostic_only"] is False
    assert out["model_mutation_in_this_stage"] is True
    assert any("non-dry-run training executed" in n for n in out["notes"])


def test_normalize_sparring_run_uses_meta_and_objective_summary():
    payload = {
        "meta": {
            "exp4_model_path": "/x/pv.json",
            "exp5_model_path": "/y/nnue.json",
            "mode": "smoke",
            "seeds_played": ["fair_1a"],
            "diagnostic_only": True,
            "timestamp": "2026-05-12T03:57:25+00:00",
            "output_dir": "/o",
        },
        "wdl": {"exp4_win": 0, "exp5_win": 0, "draw": 12, "games_total": 12},
        "raw_outcome": {},
        "strength_counted_outcome": {"games_counted": 4},
        "objective_summary": {"games_counted_total": 12, "games_hit_total": 1},
        "illegal_count": 0,
        "suspicious_count": 0,
    }
    out = normalize_stage(payload)
    assert out["stage"] == STAGE_SPARRING_RUN
    assert out["diagnostic_only"] is True
    assert out["production_runtime_mutation"] is False
    m = out["key_metrics"]
    assert m["exp4_model_path"] == "/x/pv.json"
    assert m["seeds_played"] == ["fair_1a"]
    assert m["objective_summary"]["games_hit_total"] == 1


def test_normalize_sparring_to_replay_extracts_counts():
    payload = {
        "counts": {
            "games_total": 12,
            "games_accepted": 1,
            "games_rejected": 11,
            "samples_emitted": 1,
            "reject_reasons": {"objective_miss": 11},
        },
        "policy": {"diagnostic_only": True},
        "run_dir": "/run",
    }
    out = normalize_stage(payload)
    assert out["stage"] == STAGE_SPARRING_TO_REPLAY
    m = out["key_metrics"]
    assert m["games_accepted"] == 1
    assert m["samples_emitted"] == 1
    assert m["reject_reasons"]["objective_miss"] == 11
    assert m["run_dir"] == "/run"


def test_normalize_unknown_records_note():
    out = normalize_stage({"random": "junk"})
    assert out["stage"] == STAGE_UNKNOWN
    assert any("not recognised" in n for n in out["notes"])


# ---- invariants --------------------------------------------------------


def test_compute_invariants_aggregate_flags():
    stages = [
        {"stage": "a", "diagnostic_only": True, "production_runtime_mutation": False, "model_mutation_in_this_stage": False},
        {"stage": "b", "diagnostic_only": True, "production_runtime_mutation": False, "model_mutation_in_this_stage": True},
    ]
    inv = compute_invariants(stages)
    assert inv["all_stages_diagnostic_only"] is True
    assert inv["any_production_runtime_mutation"] is False
    assert inv["any_model_mutation"] is True
    assert inv["stage_count"] == 2
    assert inv["stages_seen"] == ["a", "b"]


def test_compute_invariants_detects_dirty_stage():
    stages = [{"stage": "x", "diagnostic_only": False, "production_runtime_mutation": True, "model_mutation_in_this_stage": True}]
    inv = compute_invariants(stages)
    assert inv["all_stages_diagnostic_only"] is False
    assert inv["any_production_runtime_mutation"] is True


def test_detect_pgn_teacher_audit_by_self_stamped_stage_field():
    payload = {"stage": "pgn_teacher_audit", "counts": {"accepted_rows": 2}}
    assert detect_stage(payload) == STAGE_PGN_TEACHER_AUDIT


def test_detect_stockfish_teacher_audit_as_pgn_teacher_audit():
    payload = {"stage": "stockfish_teacher_audit", "counts": {"teacher_train_rows": 2}}
    assert detect_stage(payload) == STAGE_PGN_TEACHER_AUDIT


def test_normalize_pgn_teacher_audit_extracts_metrics():
    payload = {
        "stage": "pgn_teacher_audit",
        "audit_profile": "strict",
        "top_k": 3,
        "weight_cap": 0.5,
        "exp4_teacher_used": True,
        "exp5_teacher_used": True,
        "counts": {
            "input_rows": 12,
            "accepted_rows": 2,
            "review_rows": 10,
            "rejected_rows": 0,
            "duplicates_dropped": 0,
            "by_reason_review": {"teacher_no_top_k_agreement": 10},
            "by_reason_rejected": {},
        },
        "accepted_jsonl": "/x/accepted_replay.jsonl",
        "policy": {
            "diagnostic_only": True,
            "production_runtime_mutation": False,
            "raw_internet_download": False,
            "audited_trusted_source": "imported_dataset_teacher_audited",
        },
    }
    out = normalize_stage(payload)
    assert out["stage"] == STAGE_PGN_TEACHER_AUDIT
    assert out["diagnostic_only"] is True
    assert out["model_mutation_in_this_stage"] is False
    m = out["key_metrics"]
    assert m["audit_profile"] == "strict"
    assert m["accepted_rows"] == 2
    assert m["review_rows"] == 10
    assert m["rejected_rows"] == 0
    assert m["exp4_teacher_used"] is True
    assert m["exp5_teacher_used"] is True
    assert m["accepted_jsonl"] == "/x/accepted_replay.jsonl"
    assert m["audited_trusted_source"] == "imported_dataset_teacher_audited"


def test_normalize_stockfish_teacher_audit_extracts_metrics():
    payload = {
        "stage": "stockfish_teacher_audit",
        "depth": 8,
        "movetime_ms": 0,
        "multipv": 5,
        "teacher_train_jsonl": "/x/stockfish_teacher_train_rows.jsonl",
        "stockfish_reference": "abc123",
        "counts": {
            "selected_positions": 20,
            "teacher_rows": 20,
            "teacher_train_rows": 12,
            "teacher_eval_rows": 3,
            "played_clean_rows": 7,
            "review_rows": 5,
            "rejected_rows": 3,
            "hard_negative_source_moves": 2,
            "by_category": {"opening": 8, "tactic": 4},
            "by_played_status": {"clean": 7, "review": 5},
        },
    }

    out = normalize_stage(payload)

    assert out["stage"] == STAGE_PGN_TEACHER_AUDIT
    assert out["diagnostic_only"] is True
    m = out["key_metrics"]
    assert m["audit_backend"] == "stockfish"
    assert m["depth"] == 8
    assert m["top_k"] == 5
    assert m["input_rows"] == 20
    assert m["accepted_rows"] == 12
    assert m["eval_rows"] == 3
    assert m["played_clean_rows"] == 7
    assert m["hard_negative_source_moves"] == 2
    assert m["accepted_jsonl"] == "/x/stockfish_teacher_train_rows.jsonl"
    assert m["audited_trusted_source"] == "stockfish_teacher_audited"
    assert m["stockfish_reference"] == "abc123"


def test_compute_invariants_flags_unaudited_imported_dataset_in_seed_train():
    """The W8 default flow feeds only imported_dataset_teacher_audited into
    seed_train; the only way the raw 'imported_dataset' source shows up in
    a seed_train stage's source_breakdown_raw is via
    --include-unaudited-pgn-in-dryrun-diagnostic. Flag it for review."""
    stages = [
        {
            "stage": STAGE_SEED_TRAIN_DRY_RUN,
            "diagnostic_only": True,
            "model_mutation_in_this_stage": False,
            "production_runtime_mutation": False,
            "key_metrics": {
                "source_breakdown_raw": {"imported_dataset": 5, "pvp_filtered": 1},
            },
        }
    ]
    inv = compute_invariants(stages)
    assert inv["unaudited_imported_dataset_used_for_seed_train"] is True


def test_compute_invariants_default_safe_flow_is_clean():
    """Audited-only stream MUST NOT trigger the unaudited invariant."""
    stages = [
        {
            "stage": STAGE_SEED_TRAIN_DRY_RUN,
            "diagnostic_only": True,
            "model_mutation_in_this_stage": False,
            "production_runtime_mutation": False,
            "key_metrics": {
                "source_breakdown_raw": {
                    "imported_dataset_teacher_audited": 2,
                    "pvp_filtered": 1,
                },
            },
        }
    ]
    inv = compute_invariants(stages)
    assert inv["unaudited_imported_dataset_used_for_seed_train"] is False


def test_compute_invariants_no_seed_train_means_no_unaudited():
    inv = compute_invariants([{"stage": STAGE_PGN_TO_REPLAY, "diagnostic_only": True, "model_mutation_in_this_stage": False, "production_runtime_mutation": False, "key_metrics": {}}])
    assert inv["unaudited_imported_dataset_used_for_seed_train"] is False


def test_compute_invariants_flags_network_pgn_download_when_url_used():
    """W9: a pgn_to_replay stage with raw_internet_download=True
    flips the any_network_pgn_download invariant. Audit gate is
    separate (still required); the invariant is just for visibility."""
    stages = [
        {
            "stage": STAGE_PGN_TO_REPLAY,
            "diagnostic_only": True,
            "model_mutation_in_this_stage": False,
            "production_runtime_mutation": False,
            "key_metrics": {
                "source_urls_processed": 1,
                "raw_internet_download": True,
            },
        }
    ]
    inv = compute_invariants(stages)
    assert inv["any_network_pgn_download"] is True


def test_compute_invariants_no_url_means_no_network():
    stages = [
        {
            "stage": STAGE_PGN_TO_REPLAY,
            "diagnostic_only": True,
            "model_mutation_in_this_stage": False,
            "production_runtime_mutation": False,
            "key_metrics": {
                "source_urls_processed": 0,
                "raw_internet_download": False,
            },
        }
    ]
    inv = compute_invariants(stages)
    assert inv["any_network_pgn_download"] is False


# ---- build / render ----------------------------------------------------


def test_build_pipeline_summary_carries_next_step_and_policy():
    stages = [{"stage": "pvp_export", "diagnostic_only": True, "production_runtime_mutation": False, "model_mutation_in_this_stage": False, "key_metrics": {}, "notes": [], "source_path": "", "timestamp": "", "output_dir": ""}]
    summary = build_pipeline_summary(stages, next_step_command="echo hi")
    assert summary["next_step_command"] == "echo hi"
    assert summary["policy"]["aggregator_writes_no_models"] is True
    assert summary["policy"]["aggregator_executes_no_stage"] is True
    assert summary["invariants"]["stage_count"] == 1


def test_render_markdown_includes_invariants_and_next_step():
    stages = [{"stage": "pvp_export", "diagnostic_only": True, "production_runtime_mutation": False, "model_mutation_in_this_stage": False, "key_metrics": {"matches_total": 6}, "notes": [], "source_path": "/x", "timestamp": "2026", "output_dir": "/o"}]
    summary = build_pipeline_summary(stages, next_step_command="python3 staging.py")
    md = render_markdown(summary)
    assert "Cross-stage invariants" in md
    assert "all_stages_diagnostic_only" in md
    assert "matches_total: 6" in md
    assert "python3 staging.py" in md
    assert md.endswith("\n")


# ---- load_payloads + end-to-end ---------------------------------------


def test_load_payloads_skips_missing(tmp_path, capsys):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"a": 1}))
    missing = tmp_path / "missing.json"
    out = load_payloads([str(good), str(missing)])
    assert len(out) == 1
    captured = capsys.readouterr()
    assert "summary not found" in captured.err


def test_end_to_end_writes_both_artifacts(tmp_path):
    pvp_summary = tmp_path / "pvp.json"
    pvp_summary.write_text(json.dumps({
        "counts": {"matches_total": 6, "matches_accepted_pvp_filtered": 1, "matches_accepted_human_beat_engine": 1, "matches_rejected": 4, "samples_pvp_filtered": 12, "samples_human_beat_engine": 12, "reject_reasons": {"no_player_quality:black": 1}},
        "quality_signal": {"union_size": 2},
        "policy": {"diagnostic_only": True, "production_runtime_mutation": False},
        "timestamp": "2026-05-12T09:00:00+00:00",
        "output_dir": "/pvp",
    }))
    dry_run = tmp_path / "dr.json"
    artifact = tmp_path / "dr_artifact.json"
    artifact.write_text("{}")
    dry_run.write_text(json.dumps({
        "dry_run": True,
        "external_replay": {
            "load_stats": {"rows_kept": 24},
            "cap_stats": {"total_kept": 24},
            "normalize_validation": {"exp4_ok": 24, "exp4_failed": 0, "exp5_ok": 24, "exp5_failed": 0},
            "train_result": {"skipped_reason": "dry_run", "trained_exp4": False, "trained_exp5": False},
            "skip_exp4": False, "skip_exp5": True,
        },
        "dry_run_artifact": str(artifact),
    }))
    sparring_replay = tmp_path / "sp_replay.json"
    sparring_replay.write_text(json.dumps({
        "counts": {"games_total": 12, "games_accepted": 1, "games_rejected": 11, "samples_emitted": 1, "reject_reasons": {"objective_miss": 11}},
        "policy": {"diagnostic_only": True},
        "run_dir": "/sp",
    }))
    out_dir = tmp_path / "out"
    env = dict(os.environ)
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--summary-path", str(pvp_summary),
            "--summary-path", str(dry_run),
            "--summary-path", str(sparring_replay),
            "--output-dir", str(out_dir),
            "--next-step-command", "python3 scripts/games/chess_seed_train.py --preset warmup10 ...",
        ],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert result.returncode == 0, result.stderr

    pipeline_summary = json.loads((out_dir / "pipeline_summary.json").read_text(encoding="utf-8"))
    assert pipeline_summary["invariants"]["all_stages_diagnostic_only"] is True
    assert pipeline_summary["invariants"]["any_model_mutation"] is False
    stages_seen = pipeline_summary["invariants"]["stages_seen"]
    assert "pvp_export" in stages_seen
    assert "seed_train_dry_run" in stages_seen
    assert "sparring_to_replay" in stages_seen

    md = (out_dir / "PIPELINE_SUMMARY.md").read_text(encoding="utf-8")
    assert "pipeline aggregated report" in md.lower()
    assert "matches_total: 6" in md
    assert "samples_emitted: 1" in md


# ---- subprocess smoke -------------------------------------------------


def test_script_help_subprocess():
    env = dict(os.environ)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert result.returncode == 0
    assert "--summary-path" in result.stdout
    assert "--output-dir" in result.stdout
