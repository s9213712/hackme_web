"""Tests for scripts/games/chess_pipeline_dryrun.py (W6 commit 3).

Each pipeline stage subprocess-shells out to a separate tool that has its
own test coverage. These tests focus on the orchestrator's own logic:

  * staging command builder produces the safe default invocation;
  * each stage runner short-circuits cleanly when its prerequisites are
    missing (no model paths → no sparring; no JSONLs → no dry-run; etc);
  * --help lists the public flags.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


from scripts.games.chess_pipeline_dryrun import (
    SEED_TRAIN,
    _latest_subdir,
    build_suggested_staging_command,
    run_aggregate_stage,
    run_pvp_export_stage,
    run_seed_train_dryrun_stage,
    run_sparring_stage,
    run_sparring_to_replay_stage,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "games" / "chess_pipeline_dryrun.py"


# ---- build_suggested_staging_command ----------------------------------


def test_staging_command_includes_replay_jsonls_and_skip_exp5(tmp_path):
    cmd = build_suggested_staging_command(
        include_jsonls=[
            str(tmp_path / "pvp_replay_training_eligible.jsonl"),
            str(tmp_path / "sparring_objective_replay.jsonl"),
        ],
        candidate_dir=tmp_path / "stage",
    )
    assert "--include-replay-jsonl" in cmd
    assert cmd.count("--include-replay-jsonl") == 2
    assert "--experiment-4-model-path" in cmd
    assert "chess_experiment_4_pv_candidate.json" in cmd
    assert "--skip-exp5" in cmd
    assert "--allow-default-model-paths" not in cmd
    assert str(SEED_TRAIN) in cmd
    # Candidate path under tmp_path, not inside services/games/models/.
    assert "services/games/models" not in cmd


def test_staging_command_skip_exp5_disabled(tmp_path):
    cmd = build_suggested_staging_command(
        include_jsonls=[str(tmp_path / "x.jsonl")],
        candidate_dir=tmp_path / "stage",
        skip_exp5=False,
    )
    assert "--skip-exp5" not in cmd


def test_staging_command_resolves_candidate_path(tmp_path):
    cmd = build_suggested_staging_command(
        include_jsonls=[str(tmp_path / "x.jsonl")],
        candidate_dir=tmp_path / "stage",
    )
    assert str(tmp_path) in cmd


# ---- _latest_subdir ----------------------------------------------------


def test_latest_subdir_picks_newest_match(tmp_path):
    a = tmp_path / "pvp_replay_a"
    b = tmp_path / "pvp_replay_b"
    other = tmp_path / "unrelated"
    a.mkdir()
    other.mkdir()
    # Force b to be later by sleeping a touch.
    time.sleep(0.01)
    b.mkdir()
    assert _latest_subdir(tmp_path, "pvp_replay_") == b


def test_latest_subdir_returns_none_when_no_match(tmp_path):
    assert _latest_subdir(tmp_path, "pvp_replay_") is None


# ---- stage runners — skipped paths ------------------------------------


def test_pvp_export_skips_when_no_runtime_dir(tmp_path):
    result = run_pvp_export_stage(
        runtime_dir="",
        since="",
        output_root=tmp_path / "out",
        log_dir=tmp_path / "logs",
    )
    assert result["status"] == "skipped"
    assert "no --runtime-dir" in result["reason"]


def test_sparring_skips_without_model_paths(tmp_path):
    result = run_sparring_stage(
        exp4_model_path="",
        exp5_model_path="/some/exp5.json",
        mode="smoke",
        output_root=tmp_path / "out",
        log_dir=tmp_path / "logs",
        max_plies=40,
    )
    assert result["status"] == "skipped"
    assert "exp4-model-path" in result["reason"] or "exp5-model-path" in result["reason"]


def test_sparring_to_replay_skips_without_run_dir(tmp_path):
    result = run_sparring_to_replay_stage(
        sparring_run_dir="",
        output_root=tmp_path / "out",
        log_dir=tmp_path / "logs",
    )
    assert result["status"] == "skipped"
    assert "no sparring run dir" in result["reason"]


def test_seed_train_dryrun_skips_when_no_jsonls(tmp_path):
    result = run_seed_train_dryrun_stage(
        include_jsonls=["", "/nonexistent.jsonl"],
        report_dir=tmp_path / "reports",
        log_dir=tmp_path / "logs",
    )
    assert result["status"] == "skipped"
    assert "no --include-replay-jsonl" in result["reason"]


def test_aggregate_skips_with_no_summaries(tmp_path):
    result = run_aggregate_stage(
        summary_paths=[],
        output_dir=tmp_path / "agg",
        next_step_command="echo hi",
    )
    assert result["status"] == "skipped"
    assert "no summaries collected" in result["reason"]


# ---- subprocess smoke -------------------------------------------------


def test_script_help_subprocess():
    env = dict(os.environ)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert result.returncode == 0
    for flag in (
        "--runtime-dir",
        "--exp4-model-path",
        "--exp5-model-path",
        "--sparring-mode",
        "--train-exp5-in-suggestion",
        "--output-root",
    ):
        assert flag in result.stdout, f"flag {flag} missing from --help"
