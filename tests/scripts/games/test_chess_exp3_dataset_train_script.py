import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_chess_exp3_dataset_train_script_accepts_plain_and_teacher_distill_rows(tmp_path):
    runtime_dir = tmp_path / "runtime"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["HACKME_RUNTIME_DIR"] = str(runtime_dir)
    env["HTML_LEARNING_CHESS_ENGINE_DL_MODEL_PATH"] = str(runtime_dir / "models" / "chess_experiment_3_dl.json")
    env["HTML_LEARNING_CHESS_ENGINE_DL_REPLAY_PATH"] = str(runtime_dir / "models" / "chess_experiment_3_dl_replay.jsonl")

    plain_rows = tmp_path / "plain.jsonl"
    plain_rows.write_text(
        json.dumps({
            "fen": "6k1/5Q2/6K1/8/8/8/8/8 w - - 0 1",
            "move_uci": "f7g7",
            "side": "white",
            "target": 1.0,
            "weight": 1.1,
            "source": "unit",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    teacher_rows = tmp_path / "teacher.jsonl"
    teacher_rows.write_text(
        json.dumps({
            "fen": "6k1/5Q2/6K1/8/8/8/8/8 w - - 0 1",
            "side": "white",
            "source": "teacher_unit",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp3_dataset_train.py"),
            "--input-jsonl",
            str(plain_rows),
            "--teacher-distill-jsonl",
            str(teacher_rows),
            "--teacher-depth",
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
    assert payload["accepted_samples"] >= 2
    assert payload["input_rows"] >= 2
    assert Path(payload["model_path"]).exists()
    assert Path(payload["replay_path"]).exists()
