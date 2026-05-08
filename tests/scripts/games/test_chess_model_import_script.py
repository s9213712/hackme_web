import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from services.games.chess_dl import experiment_dl_model_template
from services.games.chess_nn import experiment_nn_model_template
from services.games.chess_pv import experiment_pv_model_template


ROOT = Path(__file__).resolve().parents[3]


def test_chess_model_import_script_installs_exp2_json_into_runtime(tmp_path):
    runtime_dir = tmp_path / "runtime"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["HACKME_RUNTIME_DIR"] = str(runtime_dir)
    input_path = tmp_path / "exp2.json"
    payload = experiment_nn_model_template()
    payload["sample_count"] = 321
    input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_model_import.py"),
            "--engine",
            "exp2",
            "--input",
            str(input_path),
        ],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    result = json.loads(proc.stdout)
    assert result["ok"] is True
    assert result["engine"] == "experiment 2:nn"
    output_path = runtime_dir / "games" / "models" / "chess_experiment_2_nn.json"
    assert result["output_path"] == str(output_path)
    installed = json.loads(output_path.read_text(encoding="utf-8"))
    assert installed["sample_count"] == 321
    assert installed["hidden_size"] == 16


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("numpy") is None,
    reason="numpy not installed",
)
def test_chess_model_import_script_validates_exp3_npz(tmp_path):
    import numpy as np

    runtime_dir = tmp_path / "runtime"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["HACKME_RUNTIME_DIR"] = str(runtime_dir)
    input_path = tmp_path / "exp3.npz"
    payload = experiment_dl_model_template()
    np.savez(
        input_path,
        w1=np.array(payload["w1"], dtype=float),
        b1=np.array(payload["b1"], dtype=float),
        w2=np.array(payload["w2"], dtype=float),
        b2=np.array(payload["b2"], dtype=float),
        w3=np.array(payload["w3"], dtype=float),
        b3=np.array(payload["b3"], dtype=float),
        sample_count=np.array(654, dtype=int),
        replay_size=np.array(77, dtype=int),
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_model_import.py"),
            "--engine",
            "exp3",
            "--input",
            str(input_path),
            "--validate-only",
        ],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    result = json.loads(proc.stdout)
    assert result["ok"] is True
    assert result["engine"] == "experiment 3:dl"
    assert result["validate_only"] is True
    assert result["sample_count"] == 654
    assert result["replay_size"] == 77
    assert not (runtime_dir / "games" / "models" / "chess_experiment_3_dl.json").exists()


def test_chess_model_import_script_installs_exp4_json_into_runtime(tmp_path):
    runtime_dir = tmp_path / "runtime"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["HACKME_RUNTIME_DIR"] = str(runtime_dir)
    input_path = tmp_path / "exp4.json"
    payload = experiment_pv_model_template()
    payload["sample_count"] = 88
    input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_model_import.py"),
            "--engine",
            "exp4",
            "--input",
            str(input_path),
        ],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    result = json.loads(proc.stdout)
    assert result["ok"] is True
    assert result["engine"] == "experiment 4:pv"
    output_path = runtime_dir / "games" / "models" / "chess_experiment_4_pv.json"
    assert result["output_path"] == str(output_path)
    installed = json.loads(output_path.read_text(encoding="utf-8"))
    assert installed["sample_count"] == 88
    assert installed["shared_hidden_size"] == 96
