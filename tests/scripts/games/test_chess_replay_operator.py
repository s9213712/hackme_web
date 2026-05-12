"""Tests for scripts/games/chess_replay_operator.py (W5 operator UX).

Focuses on pure helpers (parsers, grouper, staging command builder) plus a
single subprocess smoke for ``--help``. The underlying safety contract
already has end-to-end CLI coverage in
``tests/scripts/games/test_chess_seed_train_cli_contract.py``; this file
covers the operator UX layer that wraps it.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.games.chess_replay_operator import (
    REPO_ROOT,
    SEED_TRAIN_PATH,
    detect_runtime,
    explain_rejection_reason,
    generate_staging_command,
    group_rejected_by_reason,
    parse_converter_summary,
    parse_dry_run_payload,
)


OPERATOR_SCRIPT = REPO_ROOT / "scripts" / "games" / "chess_replay_operator.py"


# ---- detect_runtime ---------------------------------------------------


def test_detect_runtime_with_no_env_returns_disabled_state(monkeypatch):
    info = detect_runtime(env={})
    assert info["db_path"] == ""
    assert info["db_exists"] is False
    assert info["has_game_matches"] is False
    assert "(none" in info["db_source"]


def test_detect_runtime_uses_runtime_dir_database_subdir(tmp_path):
    """Mirrors server.py:258: $HACKME_RUNTIME_DIR/database/database.db."""
    info = detect_runtime(env={"HACKME_RUNTIME_DIR": str(tmp_path)})
    assert info["db_path"] == str((tmp_path / "database" / "database.db").resolve())
    assert "HACKME_RUNTIME_DIR" in info["db_source"]
    assert info["db_exists"] is False  # path resolved but file absent


def test_detect_runtime_html_learning_db_dir_overrides(tmp_path):
    info = detect_runtime(
        env={
            "HACKME_RUNTIME_DIR": str(tmp_path / "rt"),
            "HTML_LEARNING_DB_DIR": str(tmp_path / "alt"),
        }
    )
    assert info["db_path"] == str((tmp_path / "alt" / "database.db").resolve())
    assert info["db_source"] == "HTML_LEARNING_DB_DIR"


def test_detect_runtime_detects_game_matches_table(tmp_path):
    db_dir = tmp_path / "database"
    db_dir.mkdir()
    db_path = db_dir / "database.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE game_matches (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    info = detect_runtime(env={"HACKME_RUNTIME_DIR": str(tmp_path)})
    assert info["db_exists"] is True
    assert info["has_game_matches"] is True


def test_detect_runtime_db_exists_but_no_game_matches(tmp_path):
    db_dir = tmp_path / "database"
    db_dir.mkdir()
    db_path = db_dir / "database.db"
    sqlite3.connect(str(db_path)).close()  # empty DB
    info = detect_runtime(env={"HACKME_RUNTIME_DIR": str(tmp_path)})
    assert info["db_exists"] is True
    assert info["has_game_matches"] is False


# ---- parse_converter_summary ------------------------------------------


def test_parse_converter_summary_extracts_key_fields(tmp_path):
    summary = {
        "timestamp": "2026-05-12T09:17:40+00:00",
        "output_dir": "/x",
        "counts": {
            "matches_total": 6,
            "matches_accepted_pvp_filtered": 1,
            "matches_accepted_human_beat_engine": 1,
            "matches_rejected": 4,
            "samples_pvp_filtered": 12,
            "samples_human_beat_engine": 12,
            "reject_reasons": {"no_player_quality:black": 1, "non_normal_end:timeout": 1},
        },
        "quality_signal": {"union_size": 2},
        "filter_config": {"hve_difficulty_whitelist": ["experiment 4:pv", "experiment 5:nnue"]},
    }
    p = tmp_path / "summary.json"
    p.write_text(json.dumps(summary))
    out = parse_converter_summary(p)
    assert out["matches_total"] == 6
    assert out["matches_accepted_pvp_filtered"] == 1
    assert out["matches_accepted_human_beat_engine"] == 1
    assert out["samples_pvp_filtered"] == 12
    assert out["reject_reasons"]["no_player_quality:black"] == 1
    assert out["quality_union_size"] == 2
    assert "experiment 4:pv" in out["hve_whitelist"]


# ---- parse_dry_run_payload --------------------------------------------


def _good_payload(artifact_path: str) -> dict:
    return {
        "dry_run": True,
        "external_replay": {
            "enabled": True,
            "load_stats": {"rows_kept": 24, "files_read": 1, "rows_total": 24},
            "cap_stats": {"total_kept": 24},
            "normalize_validation": {
                "exp4_ok": 24,
                "exp4_failed": 0,
                "exp5_ok": 24,
                "exp5_failed": 0,
            },
            "train_result": {"skipped_reason": "dry_run", "trained_exp4": False, "trained_exp5": False},
        },
        "dry_run_artifact": artifact_path,
    }


def test_parse_dry_run_payload_pass(tmp_path):
    artifact = tmp_path / "dr.json"
    artifact.write_text("{}")
    result = parse_dry_run_payload(_good_payload(str(artifact)))
    assert result["status"] == "PASS"
    assert result["rows_kept"] == 24
    assert result["total_kept"] == 24
    assert result["exp4_failed"] == 0
    assert result["exp5_failed"] == 0
    assert result["artifact_exists"] is True


def test_parse_dry_run_payload_fail_on_normalize_error(tmp_path):
    artifact = tmp_path / "dr.json"
    artifact.write_text("{}")
    payload = _good_payload(str(artifact))
    payload["external_replay"]["normalize_validation"]["exp4_failed"] = 2
    result = parse_dry_run_payload(payload)
    assert result["status"] == "FAIL"
    assert result["exp4_failed"] == 2


def test_parse_dry_run_payload_fail_on_missing_artifact(tmp_path):
    payload = _good_payload(str(tmp_path / "does_not_exist.json"))
    result = parse_dry_run_payload(payload)
    assert result["status"] == "FAIL"
    assert result["artifact_exists"] is False


def test_parse_dry_run_payload_fail_on_zero_rows(tmp_path):
    artifact = tmp_path / "dr.json"
    artifact.write_text("{}")
    payload = _good_payload(str(artifact))
    payload["external_replay"]["load_stats"]["rows_kept"] = 0
    result = parse_dry_run_payload(payload)
    assert result["status"] == "FAIL"


def test_parse_dry_run_payload_fail_when_not_dry_run(tmp_path):
    artifact = tmp_path / "dr.json"
    artifact.write_text("{}")
    payload = _good_payload(str(artifact))
    payload["dry_run"] = False
    payload["external_replay"]["train_result"]["skipped_reason"] = ""
    result = parse_dry_run_payload(payload)
    assert result["status"] == "FAIL"


# ---- group_rejected_by_reason -----------------------------------------


def test_group_rejected_by_reason_buckets_rows(tmp_path):
    p = tmp_path / "rejected.jsonl"
    p.write_text(
        "\n".join(
            [
                json.dumps({"rejection_reason": "X", "match_id": 1}),
                json.dumps({"rejection_reason": "X", "match_id": 2}),
                json.dumps({"rejection_reason": "Y", "match_id": 3}),
                "",  # blank line should be skipped
                "not-json",  # malformed should be skipped
            ]
        )
    )
    grouped = group_rejected_by_reason(p)
    assert sorted(grouped.keys()) == ["X", "Y"]
    assert len(grouped["X"]) == 2
    assert len(grouped["Y"]) == 1


def test_group_rejected_by_reason_missing_file(tmp_path):
    assert group_rejected_by_reason(tmp_path / "absent.jsonl") == {}


# ---- explain_rejection_reason -----------------------------------------


@pytest.mark.parametrize(
    "reason,expected_substring",
    [
        ("no_player_quality:white", "top-30%"),
        ("no_player_quality:black", "top-30%"),
        ("non_normal_end:timeout", "timeout"),
        ("non_target_engine:hard", "hard"),
        ("non_target_engine:experiment 2:nn", "experiment 2:nn"),
        ("too_short:8", "8 plies"),
        ("no_winner_or_drawn", "Draw"),
        ("reconstruction_error:illegal_move:ply=3:e2e4", "replay legally"),
        ("move_history_json_invalid:foo", "could not be parsed"),
    ],
)
def test_explain_rejection_reason_known_codes(reason, expected_substring):
    assert expected_substring.lower() in explain_rejection_reason(reason).lower()


def test_explain_rejection_reason_unknown_code():
    assert "no explanation registered" in explain_rejection_reason("alien_reason")


# ---- generate_staging_command -----------------------------------------


def test_generate_staging_command_includes_safe_defaults(tmp_path):
    run_dir = tmp_path / "pvp_replay_x"
    candidate_dir = tmp_path / "stage"
    cmd = generate_staging_command(run_dir=run_dir, candidate_dir=candidate_dir)
    assert "--include-replay-jsonl" in cmd
    assert "pvp_replay_training_eligible.jsonl" in cmd
    assert "--experiment-4-model-path" in cmd
    assert "chess_experiment_4_pv_candidate.json" in cmd
    assert "--skip-exp5" in cmd
    assert "--allow-default-model-paths" not in cmd
    assert str(SEED_TRAIN_PATH) in cmd
    # candidate path must live under candidate_dir, not under
    # services/games/models/ (otherwise W4.2 guard would reject).
    assert "services/games/models" not in cmd


def test_generate_staging_command_opt_in_exp5(tmp_path):
    cmd = generate_staging_command(
        run_dir=tmp_path / "r", candidate_dir=tmp_path / "s", train_exp5=True
    )
    assert "--skip-exp5" not in cmd
    assert "--experiment-5-model-path" in cmd
    assert "chess_experiment_5_nnue_candidate.json" in cmd


def test_generate_staging_command_path_resolution(tmp_path):
    """Run dir and candidate dir should resolve to absolute paths."""
    run_dir = tmp_path / "rel_run"
    candidate_dir = tmp_path / "rel_stage"
    cmd = generate_staging_command(run_dir=run_dir, candidate_dir=candidate_dir)
    # Resolved paths should contain the absolute tmp_path prefix.
    assert str(tmp_path.resolve()) in cmd


# ---- subprocess smoke -------------------------------------------------


def test_operator_help_subprocess():
    """One subprocess smoke: --help works and lists all subcommands."""
    env = dict(os.environ)
    result = subprocess.run(
        [sys.executable, str(OPERATOR_SCRIPT), "--help"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0
    for name in ("detect", "export", "dry-run", "review", "generate-staging-command", "wizard"):
        assert name in result.stdout, f"subcommand {name!r} missing from --help output"
