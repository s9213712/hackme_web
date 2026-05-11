import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_chess_exp5_strength_gate_reports_standard_policy(tmp_path):
    model_path = tmp_path / "candidate_exp5.json"
    output_dir = tmp_path / "reports"
    shutil.copyfile(ROOT / "services" / "games" / "models" / "chess_experiment_5_nnue.json", model_path)

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
