"""Tests for scripts/games/chess_imported_replay_teacher_audit.py (W8 commit 1).

Focuses on the audit contract: only legal teacher-agreed rows reach the
accepted stream with ``trusted_source='imported_dataset_teacher_audited'``,
everything else lands in review/rejected and is structurally incapable of
being interpreted as training-safe by chess_seed_train's whitelist.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.games.chess_imported_replay_teacher_audit import (
    ACCEPTED_WEIGHT_CAP,
    AUDIT_PROFILES,
    AUDITED_TRUSTED_SOURCE,
    classify_row,
    run_audit,
    stamp_accepted,
)
from scripts.games.chess_seed_train import (
    DEFAULT_EXTERNAL_CAPS,
    TRUSTED_SOURCE_WHITELIST,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "games" / "chess_imported_replay_teacher_audit.py"

VALID_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"


def _row(**kw) -> dict:
    base = {
        "fen": VALID_FEN,
        "move_uci": "e7e5",
        "side": "black",
        "target": 1.0,
        "weight": 0.5,
        "source": "imported_dataset",
        "trusted_source": "imported_dataset",
        "label_quality": "review",
        "training_eligible": False,
        "teacher_audit_status": "not_run",
        "source_id": "pgn:test:ply:0",
        "winner_color": "black",
    }
    base.update(kw)
    return base


# ---- seed_train whitelist contract ------------------------------------


def test_seed_train_whitelists_audited_trusted_source():
    assert AUDITED_TRUSTED_SOURCE in TRUSTED_SOURCE_WHITELIST
    assert AUDITED_TRUSTED_SOURCE in DEFAULT_EXTERNAL_CAPS
    assert DEFAULT_EXTERNAL_CAPS[AUDITED_TRUSTED_SOURCE] > 0


def test_audit_profiles_well_known():
    assert AUDIT_PROFILES == ("strict", "very_strict", "diagnostic")


# ---- classify_row -----------------------------------------------------


def test_classify_rejects_invalid_fen():
    status, reasons, _ = classify_row(_row(fen="not-a-fen"), exp4_top=None, exp5_top=None)
    assert status == "rejected"
    assert "invalid_fen" in reasons


def test_classify_rejects_missing_fields():
    status, reasons, _ = classify_row(_row(fen=""), exp4_top=None, exp5_top=None)
    assert status == "rejected"
    assert "missing_required_field" in reasons


def test_classify_rejects_invalid_uci_format():
    status, reasons, _ = classify_row(
        _row(move_uci="nonsense"), exp4_top=None, exp5_top=None
    )
    assert status == "rejected"
    assert "invalid_uci" in reasons


def test_classify_rejects_illegal_move():
    # Well-formed UCI but a black pawn cannot move 3 squares from e7.
    status, reasons, _ = classify_row(
        _row(move_uci="e7e4"), exp4_top=None, exp5_top=None
    )
    assert status == "rejected"
    assert "illegal_move" in reasons


def test_classify_strict_accepts_when_in_either_top_k():
    status, reasons, teacher = classify_row(
        _row(),
        exp4_top=["e7e5", "c7c5"],
        exp5_top=["a7a5"],  # not match
        profile="strict",
    )
    assert status == "accepted"
    assert "teacher_top_k_agreement" in reasons
    assert teacher["exp4"]["candidate_in_top_k"] is True
    assert teacher["exp5"]["candidate_in_top_k"] is False


def test_classify_strict_reviews_when_no_top_k_agreement():
    status, reasons, _ = classify_row(
        _row(),
        exp4_top=["a7a5"],
        exp5_top=["b7b5"],
        profile="strict",
    )
    assert status == "review"
    assert "teacher_no_top_k_agreement" in reasons


def test_classify_strict_reviews_when_no_teacher_configured():
    status, reasons, _ = classify_row(
        _row(), exp4_top=None, exp5_top=None, profile="strict"
    )
    assert status == "review"
    assert "no_teacher_configured" in reasons


def test_classify_very_strict_requires_both_engines():
    accepted_status, _, _ = classify_row(
        _row(),
        exp4_top=["e7e5"],
        exp5_top=["e7e5"],
        profile="very_strict",
    )
    assert accepted_status == "accepted"

    review_status, review_reasons, _ = classify_row(
        _row(),
        exp4_top=["e7e5"],
        exp5_top=["a7a5"],
        profile="very_strict",
    )
    assert review_status == "review"
    assert "teacher_top_k_partial_agreement_only" in review_reasons

    rejected_status, rejected_reasons, _ = classify_row(
        _row(),
        exp4_top=["a7a5"],
        exp5_top=["b7b5"],
        profile="very_strict",
    )
    assert rejected_status == "rejected"
    assert "teacher_top_k_disagreement_both" in rejected_reasons


def test_classify_diagnostic_always_reviews():
    status, reasons, _ = classify_row(
        _row(),
        exp4_top=["e7e5"],
        exp5_top=["e7e5"],
        profile="diagnostic",
    )
    assert status == "review"
    assert "diagnostic_only_profile" in reasons


# ---- stamp_accepted ----------------------------------------------------


def test_stamp_accepted_pins_audited_trusted_source():
    out = stamp_accepted(_row(weight=2.0))
    assert out["trusted_source"] == AUDITED_TRUSTED_SOURCE
    assert out["source"] == AUDITED_TRUSTED_SOURCE
    assert out["label_quality"] == "clean"
    assert out["training_eligible"] is True
    assert out["teacher_audit_status"] == "passed"
    # Weight should be clamped under the cap.
    assert out["weight"] <= ACCEPTED_WEIGHT_CAP


def test_stamp_accepted_does_not_mutate_input():
    src = _row()
    _ = stamp_accepted(src)
    # source row must keep its W7 raw labelling.
    assert src["trusted_source"] == "imported_dataset"
    assert src["training_eligible"] is False


# ---- run_audit end-to-end ---------------------------------------------


def _write_input(tmp_path: Path, name: str, rows: list[dict]) -> Path:
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def test_run_audit_routes_rows_to_three_streams(tmp_path, monkeypatch):
    # Force deterministic top-K by monkeypatching the rankers.
    fake_calls = []

    def fake_pv(board_state, side, *, model_path):
        fake_calls.append(("pv", side))
        return [{"move": "e7e5"}, {"move": "c7c5"}, {"move": "g8f6"}]

    def fake_nnue(board_state, side, *, model_path, search_profile="fast"):
        fake_calls.append(("nnue", side))
        return [{"move": "a7a5"}, {"move": "b7b5"}, {"move": "c7c5"}]

    monkeypatch.setattr(
        "scripts.games.chess_imported_replay_teacher_audit.rank_experiment_pv_policy_moves",
        fake_pv,
    )
    monkeypatch.setattr(
        "scripts.games.chess_imported_replay_teacher_audit.rank_experiment_nnue_policy_moves",
        fake_nnue,
    )

    accepted_row = _row(move_uci="e7e5", source_id="A")  # in exp4 top → accepted
    review_row = _row(move_uci="d7d5", source_id="B")  # legal but no top hit → review
    rejected_row = _row(move_uci="a1a3", source_id="C")  # illegal → rejected
    bad_fen_row = _row(fen="garbage", source_id="D")  # invalid fen → rejected

    input_path = _write_input(
        tmp_path,
        "input.jsonl",
        [accepted_row, review_row, rejected_row, bad_fen_row],
    )
    summary = run_audit(
        input_jsonls=[input_path],
        output_dir=tmp_path / "out",
        exp4_model_path="/fake/exp4.json",
        exp5_model_path="/fake/exp5.json",
        profile="strict",
    )
    counts = summary["counts"]
    assert counts["input_rows"] == 4
    assert counts["accepted_rows"] == 1
    assert counts["review_rows"] == 1
    assert counts["rejected_rows"] == 2

    accepted = [
        json.loads(line)
        for line in (Path(summary["output_dir"]) / "accepted_replay.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(accepted) == 1
    assert accepted[0]["trusted_source"] == AUDITED_TRUSTED_SOURCE
    assert accepted[0]["training_eligible"] is True

    review = [
        json.loads(line)
        for line in (Path(summary["output_dir"]) / "review_replay.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert all(r["training_eligible"] is False for r in review)

    rejected = [
        json.loads(line)
        for line in (Path(summary["output_dir"]) / "rejected_replay.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert all(r["training_eligible"] is False for r in rejected)
    assert any("invalid_fen" in r.get("audit_reasons", []) for r in rejected)


def test_run_audit_dedupes_by_fen_side_move(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.games.chess_imported_replay_teacher_audit.rank_experiment_pv_policy_moves",
        lambda *a, **k: [{"move": "e7e5"}],
    )
    monkeypatch.setattr(
        "scripts.games.chess_imported_replay_teacher_audit.rank_experiment_nnue_policy_moves",
        lambda *a, **k: [{"move": "e7e5"}],
    )
    dup_a = _row(source_id="A")
    dup_b = _row(source_id="B")
    input_path = _write_input(tmp_path, "input.jsonl", [dup_a, dup_b])
    summary = run_audit(
        input_jsonls=[input_path],
        output_dir=tmp_path / "out",
        exp4_model_path="/fake/exp4.json",
        exp5_model_path="/fake/exp5.json",
        profile="strict",
    )
    counts = summary["counts"]
    assert counts["accepted_rows"] == 1
    assert counts["duplicates_dropped"] == 1
    assert counts["rejected_rows"] == 1
    assert counts["by_reason_rejected"].get("duplicate_fen_side_move") == 1


def test_run_audit_missing_file_counted_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.games.chess_imported_replay_teacher_audit.rank_experiment_pv_policy_moves",
        lambda *a, **k: [],
    )
    monkeypatch.setattr(
        "scripts.games.chess_imported_replay_teacher_audit.rank_experiment_nnue_policy_moves",
        lambda *a, **k: [],
    )
    summary = run_audit(
        input_jsonls=[tmp_path / "missing.jsonl"],
        output_dir=tmp_path / "out",
        profile="strict",
    )
    assert summary["counts"]["missing_files"] == 1
    assert summary["counts"]["input_rows"] == 0


def test_run_audit_summary_carries_policy_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.games.chess_imported_replay_teacher_audit.rank_experiment_pv_policy_moves",
        lambda *a, **k: [],
    )
    monkeypatch.setattr(
        "scripts.games.chess_imported_replay_teacher_audit.rank_experiment_nnue_policy_moves",
        lambda *a, **k: [],
    )
    input_path = _write_input(tmp_path, "input.jsonl", [_row()])
    summary = run_audit(
        input_jsonls=[input_path],
        output_dir=tmp_path / "out",
        profile="strict",
    )
    assert summary["stage"] == "pgn_teacher_audit"
    assert summary["policy"]["diagnostic_only"] is True
    assert summary["policy"]["production_runtime_mutation"] is False
    assert summary["policy"]["raw_internet_download"] is False
    assert summary["policy"]["audited_trusted_source"] == AUDITED_TRUSTED_SOURCE


def test_run_audit_invalid_profile_errors(tmp_path):
    input_path = _write_input(tmp_path, "input.jsonl", [_row()])
    with pytest.raises(SystemExit):
        run_audit(
            input_jsonls=[input_path],
            output_dir=tmp_path / "out",
            profile="totally_made_up",
        )


# ---- subprocess smoke -------------------------------------------------


def test_script_help_subprocess():
    env = dict(os.environ)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0
    assert "--input-jsonl" in result.stdout
    assert "--audit-profile" in result.stdout
    assert "imported_dataset_teacher_audited" in result.stdout
