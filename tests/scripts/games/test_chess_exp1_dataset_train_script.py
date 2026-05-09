import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_chess_exp1_dataset_train_script_updates_memory_db(tmp_path):
    runtime_dir = tmp_path / "runtime"
    db_path = runtime_dir / "games" / "models" / "chess_experiment.db"
    rows = tmp_path / "exp1_rows.jsonl"
    rows.write_text(
        json.dumps(
            {
                "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                "move_uci": "e2e4",
                "side": "white",
                "target": 1.0,
                "weight": 1.0,
                "source": "unit",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["HACKME_RUNTIME_DIR"] = str(runtime_dir)
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp1_dataset_train.py"),
            "--input-jsonl",
            str(rows),
            "--db-path",
            str(db_path),
        ],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["engine"] == "experiment"
    assert payload["accepted_samples"] == 1
    assert payload["rejected_samples"] == 0
    assert Path(payload["db_path"]).exists()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT move_uci, sample_count, win_count, score_total FROM game_chess_engine_memory"
    ).fetchone()
    conn.close()
    assert row["move_uci"] == "e2e4"
    assert row["sample_count"] == 1
    assert row["win_count"] == 1
    assert row["score_total"] > 0
