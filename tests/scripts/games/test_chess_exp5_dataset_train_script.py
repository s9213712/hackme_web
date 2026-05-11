import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _write_exp5_rows(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1",
                "move_uci": "e7e5",
                "side": "black",
                "target": 1.0,
                "weight": 1.0,
                "source": "unit",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def test_chess_exp5_dataset_train_script_builds_model_and_replay(tmp_path):
    runtime_dir = tmp_path / "runtime"
    model_path = runtime_dir / "games" / "models" / "chess_experiment_5_nnue.json"
    replay_path = runtime_dir / "games" / "models" / "chess_experiment_5_nnue_replay.jsonl"
    rows = tmp_path / "exp5_rows.jsonl"
    _write_exp5_rows(rows)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["HACKME_RUNTIME_DIR"] = str(runtime_dir)
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp5_dataset_train.py"),
            "--input-jsonl",
            str(rows),
            "--model-path",
            str(model_path),
            "--replay-path",
            str(replay_path),
            "--replace-replay",
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
    assert payload["training_applied"] is True
    assert payload["accepted_samples"] == 1
    assert payload["rejected_samples"] == 0
    assert payload["sample_format"] == "exp5_nnue_position_move_v1"
    assert payload["promotion_gate_supported"] is False
    assert Path(payload["model_path"]).exists()
    assert Path(payload["replay_path"]).exists()
    assert json.loads(model_path.read_text(encoding="utf-8"))["sample_count"] >= 1


def test_chess_exp5_retrain_pipeline_reports_pending_strength_gate(tmp_path):
    runtime_dir = tmp_path / "runtime"
    model_path = runtime_dir / "games" / "models" / "candidate_exp5.json"
    replay_path = runtime_dir / "games" / "models" / "candidate_exp5_replay.jsonl"
    rows = tmp_path / "exp5_rows.jsonl"
    _write_exp5_rows(rows)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["HACKME_RUNTIME_DIR"] = str(runtime_dir)
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp5_retrain_pipeline.py"),
            "--input-jsonl",
            str(rows),
            "--candidate-model-path",
            str(model_path),
            "--candidate-replay-path",
            str(replay_path),
            "--replace-replay",
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
    assert payload["trainer_result"]["accepted_samples"] == 1
    assert payload["strength_validation_supported"] is False
    assert payload["promotion_gate_supported"] is False
    assert "exp5-only" in payload["boundary"]
    assert Path(payload["reports"]["json_report"]).exists()
    assert Path(payload["reports"]["md_report"]).exists()
