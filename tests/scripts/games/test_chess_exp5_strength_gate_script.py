import json
import os
import subprocess
import sys
from pathlib import Path

import chess

from scripts.games.chess_exp5_production_readiness import (
    _normalize_case,
    _soft_label_near_equivalent_audit,
)
from services.games.chess_nnue import experiment_nnue_model_template, save_experiment_nnue_experience_delta


ROOT = Path(__file__).resolve().parents[3]


def test_exp5_audited_multigood_moves_are_explicit_not_broad_endgame_credit():
    quiet = _normalize_case({
        "id": "exp5_09_bench_d400404a65f3",
        "fen": "8/8/6k1/8/8/5K1P/8/8 w - - 0 1",
        "side": "white",
        "category": "quiet_positional",
        "teacher_move": "g3f2",
        "expected_uci_any": ["g3f2"],
    })
    assert "h2h4" in quiet["expected_uci_any"]
    assert quiet["audited_multi_good_uci_any"] == ["h2h4"]

    endgame = _normalize_case({
        "id": "exp5_10_teacher_012",
        "fen": "8/5p2/2r3p1/3pk2p/8/1P1K1R1P/5PP1/8 b - - 15 58",
        "side": "black",
        "category": "endgame",
        "teacher_move": "e5d6",
        "expected_uci_any": ["e5d6"],
    })
    assert "c6a6" in endgame["expected_uci_any"]
    assert endgame["audited_multi_good_uci_any"] == ["c6a6"]

    unaudited_endgame = _normalize_case({
        "id": "not_a_pinned_audit_case",
        "fen": "8/5p2/2r3p1/3pk2p/8/1P1K1R1P/5PP1/8 b - - 15 58",
        "side": "black",
        "category": "endgame",
        "teacher_move": "e5d6",
        "expected_uci_any": ["e5d6"],
    })
    audit = _soft_label_near_equivalent_audit(unaudited_endgame, chess.Board(unaudited_endgame["fen"]), "c6a6")
    assert audit["applied"] is False
    assert audit["accepted"] is False


def test_chess_exp5_strength_gate_reports_standard_policy(tmp_path):
    model_path = tmp_path / "candidate_exp5.json"
    output_dir = tmp_path / "reports"
    save_experiment_nnue_experience_delta(model_path, experiment_nnue_model_template())

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp5_strength_gate.py"),
            "--candidate-model-path",
            str(model_path),
            "--baseline-model-path",
            str(model_path),
            "--output-dir",
            str(output_dir),
            "--search-profile",
            "fast",
            "--min-case-pass-rate",
            "0.0",
        ],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["engine"] == "experiment 5:nnue"
    assert payload["promotion_gate_supported"] is True
    assert payload["standard_policy"]["same_as_exp3_exp4"] is False
    assert payload["standard_policy"]["common_safety_floor_shared"] is True
    assert payload["standard_policy"]["exp5_specific_deterministic_gate_required"] is True
    assert payload["baseline_score"] == payload["candidate_score"]
    assert payload["score_delta"] == 0.0
    assert payload["pass"] is False
    assert "candidate_score_not_above_baseline" in payload["reasons"]
    assert payload["promotion_gate"]["passed"] is False
    assert payload["promotion_gate"]["blocked_by_strength_gate"] is True
    assert payload["promotion_gate"]["candidate_can_be_staged"] is False
    assert payload["legal_rate"] == 1.0
    assert payload["safety_guard"]["illegal_rate_zero"] is True
    assert payload["cases_total"] >= 1
    assert Path(payload["reports"]["json_report"]).exists()
    assert Path(payload["reports"]["md_report"]).exists()
