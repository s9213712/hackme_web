import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_chess_seed_train_script_produces_runtime_seed_models(tmp_path):
    runtime_dir = tmp_path / "runtime"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["HACKME_RUNTIME_DIR"] = str(runtime_dir)
    env["HTML_LEARNING_CHESS_ENGINE_NN_MODEL_PATH"] = str(runtime_dir / "games" / "models" / "chess_experiment_2_nn.json")
    env["HTML_LEARNING_CHESS_ENGINE_DL_MODEL_PATH"] = str(runtime_dir / "games" / "models" / "chess_experiment_3_dl.json")
    env["HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH"] = str(runtime_dir / "games" / "models" / "chess_experiment_4_pv.json")

    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_seed_train.py"),
            "--preset",
            "micro",
            "--dl-search-depth",
            "1",
            "--dl-quiescence-depth",
            "1",
            "--pv-search-depth",
            "1",
            "--pv-quiescence-depth",
            "1",
        ],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["preset"] == "micro"
    assert payload["games_played"] >= 1
    assert payload["models"]["exp3"]["exists"] is True
    assert payload["models"]["exp4"]["exists"] is True
    assert payload["models"]["exp3"]["sample_count"] >= 1
    assert payload["models"]["exp4"]["sample_count"] >= 1
    assert Path(payload["reports"]["json_report"]).exists()
    assert Path(payload["reports"]["md_report"]).exists()
