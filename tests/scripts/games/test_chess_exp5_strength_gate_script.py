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
    assert payload["cases_total"] >= 1
    assert Path(payload["reports"]["json_report"]).exists()
    assert Path(payload["reports"]["md_report"]).exists()
