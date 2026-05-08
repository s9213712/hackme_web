import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_chess_self_play_train_script_generates_runtime_reports(tmp_path):
    runtime_dir = tmp_path / "runtime"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["HACKME_RUNTIME_DIR"] = str(runtime_dir)
    env["HTML_LEARNING_CHESS_ENGINE_DB_PATH"] = str(runtime_dir / "database" / "chess_experiment.db")
    env["HTML_LEARNING_CHESS_ENGINE_NN_MODEL_PATH"] = str(runtime_dir / "games" / "models" / "chess_experiment_2_nn.json")
    env["HTML_LEARNING_CHESS_ENGINE_DL_MODEL_PATH"] = str(runtime_dir / "games" / "models" / "chess_experiment_3_dl.json")
    env["HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH"] = str(runtime_dir / "games" / "models" / "chess_experiment_4_pv.json")
    report_dir = runtime_dir / "reports" / "games"

    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_self_play_train.py"),
            "--exp1-games",
            "1",
            "--exp2-games",
            "1",
            "--exp3-games",
            "1",
            "--exp4-games",
            "1",
            "--hard-exp1-games",
            "1",
            "--hard-exp2-games",
            "1",
            "--hard-exp3-games",
            "1",
            "--hard-exp4-games",
            "1",
            "--cross-games",
            "1",
            "--cross-exp1-exp3-games",
            "1",
            "--cross-exp2-exp3-games",
            "1",
            "--cross-exp1-exp4-games",
            "1",
            "--cross-exp2-exp4-games",
            "1",
            "--cross-exp3-exp4-games",
            "1",
            "--teacher-depth",
            "1",
            "--max-plies",
            "4",
            "--smoke-games-per-pair",
            "0",
            "--benchmark-rounds",
            "0",
            "--student-exploration-rate",
            "1.0",
            "--seed",
            "11",
            "--report-dir",
            str(report_dir),
        ],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(proc.stdout)
    assert payload["games_played"] == 14
    assert payload["requested_games"]["hard_vs_exp1"] == 1
    assert payload["requested_games"]["hard_vs_exp2"] == 1
    assert payload["requested_games"]["hard_vs_exp3"] == 1
    assert payload["requested_games"]["hard_vs_exp4"] == 1
    assert payload["smoke_evaluation"]["games_played"] == 0
    assert payload["benchmark"]["games_played"] == 0
    assert payload["benchmark"]["rounds"] == 0
    assert payload["experiment_4_pv_model_path"].endswith("chess_experiment_4_pv.json")
    assert Path(payload["reports"]["json_report"]).exists()
    assert Path(payload["reports"]["md_report"]).exists()
    assert str(report_dir) in payload["reports"]["json_report"]
