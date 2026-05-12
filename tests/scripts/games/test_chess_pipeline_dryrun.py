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

import scripts.games.chess_pipeline_dryrun  # noqa: F401  (monkeypatch target)

from scripts.games.chess_pipeline_dryrun import (
    SEED_TRAIN,
    _expand_game_level_to_per_ply,
    _latest_subdir,
    build_suggested_staging_command,
    run_aggregate_stage,
    run_pgn_input_stage,
    run_pgn_teacher_audit_stage,
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


# ---- W7: PGN input stage ----------------------------------------------


def _write_game_level_jsonl(path: Path, games: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(g) for g in games) + "\n", encoding="utf-8"
    )


def _history_entry(uci: str, *, side: str) -> dict:
    promo = uci[4] if len(uci) == 5 else None
    return {
        "by": side,
        "from": uci[:2],
        "to": uci[2:4],
        "piece": "P",
        "captured": None,
        "promotion": promo,
        "at": "2026-05-12T00:00:00Z",
    }


def _build_white_winning_game() -> dict:
    """A short Ruy Lopez-ish stub ending in white win."""
    seq = ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4", "g8f6"]
    history = []
    for i, uci in enumerate(seq):
        history.append(_history_entry(uci, side="white" if i % 2 == 0 else "black"))
    return {
        "match_id": 1,
        "replay_id": "pgn_test_white_win",
        "winner_color": "white",
        "move_history": history,
        "move_count": len(history),
        "source": "imported_dataset",
    }


def test_expand_game_level_emits_winner_side_only(tmp_path):
    game = _build_white_winning_game()
    src = tmp_path / "game_level.jsonl"
    _write_game_level_jsonl(src, [game])
    out = tmp_path / "per_ply.jsonl"
    games, samples = _expand_game_level_to_per_ply(src, out)
    assert games == 1
    assert samples == 4  # 8 plies, 4 white moves
    rows = [
        json.loads(line)
        for line in out.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert all(r["side"] == "white" for r in rows)
    assert all(r["target"] == 1.0 for r in rows)
    assert all(r["trusted_source"] == "imported_dataset" for r in rows)
    # W8 commit 2: raw PGN-derived rows are diagnostic only; only the
    # W8 audit stage may flip these to training-safe clean status.
    assert all(r["label_quality"] == "review" for r in rows)
    assert all(r["training_eligible"] is False for r in rows)
    assert all(r["teacher_audit_status"] == "not_run" for r in rows)
    assert all(r["source_id"].startswith("pgn:pgn_test_white_win:ply:") for r in rows)


def test_expand_game_level_skips_draws_and_invalid(tmp_path):
    drawn = {
        "match_id": 2,
        "replay_id": "drawn",
        "winner_color": None,
        "move_history": [_history_entry("e2e4", side="white")],
        "move_count": 1,
    }
    missing_history = {
        "match_id": 3,
        "replay_id": "no_hist",
        "winner_color": "white",
        "move_history": "not-a-list",
    }
    src = tmp_path / "game_level.jsonl"
    _write_game_level_jsonl(src, [drawn, missing_history])
    out = tmp_path / "per_ply.jsonl"
    games, samples = _expand_game_level_to_per_ply(src, out)
    assert games == 2
    assert samples == 0
    assert out.read_text(encoding="utf-8") == ""


def test_expand_game_level_breaks_on_illegal_move(tmp_path):
    bad = {
        "match_id": 4,
        "replay_id": "bad",
        "winner_color": "white",
        "move_history": [
            _history_entry("e2e4", side="white"),
            _history_entry("e7e5", side="black"),
            # Illegal: knight from e2 cannot go to e9.
            {"by": "white", "from": "e2", "to": "e9", "piece": "N"},
        ],
        "move_count": 3,
    }
    src = tmp_path / "game_level.jsonl"
    _write_game_level_jsonl(src, [bad])
    out = tmp_path / "per_ply.jsonl"
    games, samples = _expand_game_level_to_per_ply(src, out)
    assert games == 1
    # Only the first (legal white) move should have been emitted before break.
    assert samples == 1


def test_pgn_input_stage_skipped_with_no_inputs(tmp_path):
    result = run_pgn_input_stage(
        pgn_paths=[],
        prepared_jsonls=[],
        output_root=tmp_path / "00_pgn_input",
        log_dir=tmp_path / "logs",
    )
    assert result["status"] == "skipped"
    # Reason mentions all three input flags so the operator knows
    # they need to supply at least one.
    assert "--pgn-path" in result["reason"]
    assert "--pgn-source-url" in result["reason"]


def test_pgn_input_stage_url_flow_records_network_policy(tmp_path, monkeypatch):
    """W9: when --pgn-source-url is provided, the orchestrator forwards
    --source-url to chess_pgn_to_replay and stamps
    raw_internet_download=True so the aggregator's
    any_network_pgn_download invariant flips True downstream.
    Subprocess is monkeypatched — no real network is hit in the test."""
    captured_cmds: list[list[str]] = []

    valid_game_level = {
        "match_id": 1,
        "replay_id": "url_test",
        "winner_color": "white",
        "move_history": [
            {"by": "white", "from": "e2", "to": "e4", "piece": "P", "promotion": None},
            {"by": "black", "from": "e7", "to": "e5", "piece": "p", "promotion": None},
        ],
        "move_count": 2,
        "source": "imported_dataset",
    }

    def fake_run(cmd, env=None, stdout=None, stderr=None, text=None, **kwargs):
        captured_cmds.append(list(cmd))
        # Write a single-game game-level JSONL to the --output-jsonl path so
        # _expand_game_level_to_per_ply has something to read.
        out_idx = cmd.index("--output-jsonl") + 1
        out_path = Path(cmd[out_idx])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(valid_game_level) + "\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(
        "scripts.games.chess_pipeline_dryrun.subprocess.run", fake_run
    )

    result = run_pgn_input_stage(
        pgn_paths=[],
        prepared_jsonls=[],
        output_root=tmp_path / "00_pgn_input",
        log_dir=tmp_path / "logs",
        pgn_source_urls=["https://example.com/test.pgn"],
        pgn_download_dir=str(tmp_path / "cache"),
        pgn_refresh_downloads=True,
    )
    assert result["status"] == "ok"
    assert len(captured_cmds) == 1
    cmd = captured_cmds[0]
    assert "--source-url" in cmd
    assert "https://example.com/test.pgn" in cmd
    assert "--download-dir" in cmd
    assert "--refresh-downloads" in cmd

    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["policy"]["raw_internet_download"] is True
    assert summary["policy"]["audit_gate_required"] is True
    assert summary["counts"]["source_urls_processed"] == 1
    assert summary["counts"]["games_imported"] == 1
    # Winner-side moves only: white played 1 move in the 2-ply fixture.
    assert summary["counts"]["per_ply_samples_emitted"] == 1


def test_pgn_input_stage_path_flow_raw_internet_download_false(tmp_path, monkeypatch):
    """--pgn-path alone must not flip raw_internet_download."""
    def fake_run(cmd, env=None, stdout=None, stderr=None, text=None, **kwargs):
        out_idx = cmd.index("--output-jsonl") + 1
        out_path = Path(cmd[out_idx])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(
        "scripts.games.chess_pipeline_dryrun.subprocess.run", fake_run
    )

    fake_pgn = tmp_path / "fixture.pgn"
    fake_pgn.write_text("[Result \"1-0\"]\n\n1. e4 e5 1-0\n", encoding="utf-8")
    result = run_pgn_input_stage(
        pgn_paths=[str(fake_pgn)],
        prepared_jsonls=[],
        output_root=tmp_path / "00_pgn_input",
        log_dir=tmp_path / "logs",
    )
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["policy"]["raw_internet_download"] is False
    assert summary["counts"]["source_urls_processed"] == 0


def test_pgn_input_stage_pass_through_prepared_jsonl(tmp_path):
    prepared = tmp_path / "pre.jsonl"
    prepared.write_text(
        json.dumps({"fen": "x", "move_uci": "e2e4", "side": "white"}) + "\n",
        encoding="utf-8",
    )
    result = run_pgn_input_stage(
        pgn_paths=[],
        prepared_jsonls=[str(prepared)],
        output_root=tmp_path / "00_pgn_input",
        log_dir=tmp_path / "logs",
    )
    assert result["status"] == "ok"
    assert str(prepared) in result["output_jsonls"]
    summary = json.loads(
        (Path(result["summary_path"])).read_text(encoding="utf-8")
    )
    assert summary["stage"] == "pgn_to_replay"
    assert summary["counts"]["prepared_jsonls_attached"] == 1
    assert summary["counts"]["pgn_paths_processed"] == 0
    assert summary["policy"]["raw_internet_download"] is False


def test_pgn_teacher_audit_stage_skips_without_raw_jsonls(tmp_path):
    result = run_pgn_teacher_audit_stage(
        raw_jsonls=[],
        output_dir=tmp_path / "00b_pgn_teacher_audit",
        log_dir=tmp_path / "logs",
        exp4_model_path="",
        exp5_model_path="",
        audit_profile="strict",
        top_k=3,
    )
    assert result["status"] == "skipped"
    assert "no raw pgn jsonls" in result["reason"]


def test_pgn_teacher_audit_stage_skips_when_inputs_missing_on_disk(tmp_path):
    result = run_pgn_teacher_audit_stage(
        raw_jsonls=[str(tmp_path / "absent.jsonl")],
        output_dir=tmp_path / "00b_pgn_teacher_audit",
        log_dir=tmp_path / "logs",
        exp4_model_path="",
        exp5_model_path="",
        audit_profile="strict",
        top_k=3,
    )
    assert result["status"] == "skipped"
    assert "missing on disk" in result["reason"]


def test_pgn_input_stage_ignores_missing_prepared(tmp_path):
    result = run_pgn_input_stage(
        pgn_paths=[],
        prepared_jsonls=[str(tmp_path / "does_not_exist.jsonl")],
        output_root=tmp_path / "00_pgn_input",
        log_dir=tmp_path / "logs",
    )
    assert result["status"] == "ok"
    assert result["output_jsonls"] == []
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["counts"]["prepared_jsonls_attached"] == 0


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
