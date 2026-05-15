import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_chess_exp5_teacher_distill_script_writes_exp5_samples(tmp_path):
    input_path = tmp_path / "positions.jsonl"
    output_path = tmp_path / "distilled.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                "side": "white",
                "weight": 1.2,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp5_teacher_distill.py"),
            "--input-jsonl",
            str(input_path),
            "--output-jsonl",
            str(output_path),
            "--teacher-depth",
            "1",
            "--replace-output",
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
    assert payload["accepted_samples"] == 1
    assert payload["input_fen_count"] == 1
    assert payload["distilled_rows"] == 1
    assert payload["sample_format"] == "exp5_nnue_position_move_v1"
    assert payload["retrain_input_compatible"] is True
    assert payload["quality_audit"]["duplicate_ratio"] == 0.0
    assert payload["quality_audit"]["legal_teacher_move_rate"] == 1.0
    assert payload["quality_audit"]["suspicious_teacher_move_rate"] == 0.0
    assert payload["quality_audit"]["teacher_top1_available_rate"] == 1.0
    assert payload["quality_audit"]["teacher_score_available_rate"] == 0.0
    assert payload["quality_audit"]["label_quality_summary"]["pass"] is True

    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["sample_format"] == "exp5_nnue_position_move_v1"
    assert rows[0]["side"] == "white"
    assert len(rows[0]["move_uci"]) >= 4


def test_chess_exp5_teacher_distill_can_use_opening_book_backend(tmp_path):
    input_path = tmp_path / "positions.jsonl"
    output_path = tmp_path / "distilled_book.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                "side": "white",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp5_teacher_distill.py"),
            "--input-jsonl",
            str(input_path),
            "--output-jsonl",
            str(output_path),
            "--teacher-backend",
            "opening_book",
            "--replace-output",
        ],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["teacher_backend"] == "opening_book"
    assert payload["accepted_samples"] == 1
    row = json.loads(output_path.read_text(encoding="utf-8").strip())
    assert row["teacher_backend"] == "opening_book"
    assert row["teacher_top_k_method"] == "deterministic_opening_book"
    assert row["move_uci"] in {"e2e4", "d2d4", "c2c4", "g1f3", "b2b3"}
