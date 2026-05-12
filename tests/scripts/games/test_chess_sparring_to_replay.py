"""Tests for scripts/games/chess_sparring_to_replay.py (W6 commit 1).

Covers the filter contract end-to-end:
  - accept only objective_counted=True AND objective_hit=True AND
    forced_fixture_win=False AND outcome not illegal_* AND first ply legal.
  - emit canonical replay rows with trusted_source='sparring_objective_hit',
    label_quality='review', weight defaulting to 0.10 (cap 0.15).
  - never harvest later plies (they have no oracle).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.games.chess_sparring_to_replay import (
    DEFAULT_SAMPLE_WEIGHT,
    SAMPLE_WEIGHT_CAP,
    _index_first_plies,
    _read_jsonl,
    build_sample,
    classify_game,
    run_export,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "games" / "chess_sparring_to_replay.py"


# ---- helpers / fixtures ------------------------------------------------


def _ply(seed_id: str, *, ply: int = 0, **overrides) -> dict:
    base = {
        "seed_id": seed_id,
        "ply": ply,
        "engine_id": "exp4",
        "side": "white",
        "fen_before": "8/8/8/3k4/8/8/3KP3/8 w - - 0 1",
        "move": "d2c1",
        "legal": True,
    }
    base.update(overrides)
    return base


def _game(seed_id: str, **overrides) -> dict:
    base = {
        "seed_id": seed_id,
        "cluster_tag": "endgame",
        "objective_type": "endgame_plan",
        "objective_counted": True,
        "objective_hit": True,
        "forced_fixture_win": False,
        "outcome": "draw",
        "expected_rule_subtype": None,
    }
    base.update(overrides)
    return base


# ---- classify_game -----------------------------------------------------


def test_classify_accepts_full_match():
    out, reason = classify_game(_game("s1"), first_ply=_ply("s1"))
    assert out == "accept"
    assert reason == ""


def test_classify_rejects_no_oracle():
    out, reason = classify_game(_game("s", objective_counted=False), first_ply=_ply("s"))
    assert out == "reject"
    assert reason == "no_oracle"


def test_classify_rejects_objective_miss():
    out, reason = classify_game(_game("s", objective_hit=False), first_ply=_ply("s"))
    assert out == "reject"
    assert reason == "objective_miss"


def test_classify_rejects_forced_fixture():
    out, reason = classify_game(_game("s", forced_fixture_win=True), first_ply=_ply("s"))
    assert out == "reject"
    assert reason == "forced_fixture"


def test_classify_rejects_illegal_outcome():
    out, reason = classify_game(_game("s", outcome="illegal_exp4"), first_ply=_ply("s"))
    assert out == "reject"
    assert reason.startswith("illegal_outcome:")


def test_classify_rejects_missing_first_ply():
    out, reason = classify_game(_game("s"), first_ply=None)
    assert out == "reject"
    assert reason == "missing_first_ply_record"


def test_classify_rejects_first_ply_illegal():
    out, reason = classify_game(_game("s"), first_ply=_ply("s", legal=False))
    assert out == "reject"
    assert reason == "first_ply_illegal"


def test_classify_rejects_first_ply_incomplete():
    out, reason = classify_game(_game("s"), first_ply=_ply("s", move=""))
    assert out == "reject"
    assert reason == "first_ply_incomplete"


# ---- build_sample ------------------------------------------------------


def test_build_sample_uses_canonical_trusted_source_and_default_weight():
    s = build_sample(_game("s1"), _ply("s1"), sample_weight=DEFAULT_SAMPLE_WEIGHT)
    assert s["trusted_source"] == "sparring_objective_hit"
    assert s["source"] == "sparring_objective_hit"
    assert s["label_quality"] == "review"
    assert s["target"] == 1.0
    assert s["weight"] == DEFAULT_SAMPLE_WEIGHT
    assert s["training_eligible"] is True
    assert s["source_id"] == "sparring:s1:ply:0"
    assert s["fen"] == "8/8/8/3k4/8/8/3KP3/8 w - - 0 1"
    assert s["move_uci"] == "d2c1"
    assert s["side"] == "white"
    assert s["match_mode"] == "sparring"


def test_build_sample_carries_diagnostic_metadata():
    g = _game("s1", cluster_tag="special_rule", objective_type="rule_subtype",
              expected_rule_subtype="castling_short")
    p = _ply("s1", engine_id="exp4")
    s = build_sample(g, p, sample_weight=0.12)
    assert s["cluster_tag"] == "special_rule"
    assert s["objective_type"] == "rule_subtype"
    assert s["expected_rule_subtype"] == "castling_short"
    assert s["engine_id"] == "exp4"


# ---- helpers -----------------------------------------------------------


def test_index_first_plies_picks_ply0_only(tmp_path):
    rows = [
        _ply("a", ply=0, move="e2e4"),
        _ply("a", ply=1, move="e7e5"),  # ignored
        _ply("b", ply=0, move="d2d4"),
    ]
    idx = _index_first_plies(rows)
    assert set(idx.keys()) == {"a", "b"}
    assert idx["a"]["move"] == "e2e4"
    assert idx["b"]["move"] == "d2d4"


def test_read_jsonl_skips_blank_and_malformed(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text(
        "\n".join([
            json.dumps({"a": 1}),
            "",
            "not-json",
            json.dumps({"a": 2}),
        ]),
        encoding="utf-8",
    )
    rows = _read_jsonl(p)
    assert rows == [{"a": 1}, {"a": 2}]


def test_read_jsonl_missing_file(tmp_path):
    assert _read_jsonl(tmp_path / "nope.jsonl") == []


# ---- run_export end-to-end --------------------------------------------


def _write_run_dir(tmp_path: Path, games: list[dict], moves: list[dict]) -> Path:
    run_dir = tmp_path / "exp4_vs_exp5_smoke_fixture"
    run_dir.mkdir()
    (run_dir / "games.jsonl").write_text(
        "\n".join(json.dumps(g) for g in games) + "\n", encoding="utf-8"
    )
    (run_dir / "moves.jsonl").write_text(
        "\n".join(json.dumps(m) for m in moves) + "\n", encoding="utf-8"
    )
    return run_dir


def test_run_export_accepts_hits_and_rejects_others(tmp_path):
    games = [
        _game("hit_endgame"),
        _game("miss_opening", objective_type="opening_sanity", objective_hit=False),
        _game("forced", forced_fixture_win=True),
        _game("no_oracle", objective_counted=False),
        _game("illegal_game", outcome="illegal_exp4"),
    ]
    moves = [
        _ply("hit_endgame", engine_id="exp5"),
        _ply("miss_opening", move="a7a5"),
        _ply("forced"),
        _ply("no_oracle"),
        _ply("illegal_game", legal=False),
    ]
    run_dir = _write_run_dir(tmp_path, games, moves)
    out_root = tmp_path / "out"

    summary = run_export(
        run_dir=run_dir, output_root=out_root, sample_weight=DEFAULT_SAMPLE_WEIGHT
    )
    counts = summary["counts"]
    assert counts["games_total"] == 5
    assert counts["games_accepted"] == 1
    assert counts["games_rejected"] == 4
    assert counts["samples_emitted"] == 1
    assert set(counts["reject_reasons"]) == {
        "objective_miss",
        "forced_fixture",
        "no_oracle",
        "illegal_outcome:illegal_exp4",
    }

    out_dir = Path(summary["output_dir"])
    eligible = [
        json.loads(line)
        for line in (out_dir / "sparring_objective_replay.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(eligible) == 1
    sample = eligible[0]
    assert sample["seed_id"] == "hit_endgame"
    assert sample["engine_id"] == "exp5"
    assert sample["trusted_source"] == "sparring_objective_hit"
    assert sample["weight"] == DEFAULT_SAMPLE_WEIGHT

    rejected = [
        json.loads(line)
        for line in (out_dir / "sparring_rejected.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {r["seed_id"] for r in rejected} == {
        "miss_opening", "forced", "no_oracle", "illegal_game"
    }


def test_run_export_caps_sample_weight(tmp_path):
    run_dir = _write_run_dir(tmp_path, [], [])
    out_root = tmp_path / "out"
    with pytest.raises(SystemExit) as exc:
        run_export(
            run_dir=run_dir,
            output_root=out_root,
            sample_weight=SAMPLE_WEIGHT_CAP + 0.05,
        )
    assert "exceeds policy cap" in str(exc.value)


def test_run_export_requires_games_and_moves_files(tmp_path):
    run_dir = tmp_path / "empty"
    run_dir.mkdir()
    with pytest.raises(SystemExit):
        run_export(run_dir=run_dir, output_root=tmp_path / "out",
                   sample_weight=DEFAULT_SAMPLE_WEIGHT)


# ---- subprocess smoke -------------------------------------------------


def test_script_help_subprocess():
    env = dict(os.environ)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert result.returncode == 0
    assert "--run-dir" in result.stdout
    assert "sparring_objective_hit" in result.stdout
