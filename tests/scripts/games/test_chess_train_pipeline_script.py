import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_chess_train_pipeline_runs_prepare_seed_benchmark_and_stage(tmp_path):
    runtime_dir = tmp_path / "runtime"
    replay_path = runtime_dir / "reports" / "games" / "chess_replays.jsonl"
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    replay_path.write_text(
        json.dumps(
            {
                "source": "user_games",
                "engine_name": "experiment 4:pv",
                "engine_version": "experiment 4:pv",
                "white_engine": "experiment 4:pv",
                "black_engine": "user",
                "opening_seed": "standard_start",
                "result": "white",
                "winner_color": "white",
                "adjudicated_or_natural": "natural",
                "move_count": 9,
                "timestamp": "2026-05-08T12:27:08.354707Z",
                "rating_estimate": None,
                "suspicious_flag": False,
                "duplicate_flag": False,
                "resign_abuse_flag": False,
                "confidence_score": 0.3,
                "collection_tier": "trusted",
                "quarantine_reasons": [],
                "replay_id": "pipeline-test-replay",
                "move_history": [
                    {"by": "white", "from": "b1", "to": "c3"},
                    {"by": "black", "from": "g8", "to": "f6"},
                    {"by": "white", "from": "c3", "to": "b5"},
                    {"by": "black", "from": "e7", "to": "e6"},
                    {"by": "white", "from": "a1", "to": "b1"},
                    {"by": "black", "from": "f8", "to": "e7"},
                    {"by": "white", "from": "a2", "to": "a3"},
                    {"by": "black", "from": "e8", "to": "g8"},
                    {"by": "white", "from": "a3", "to": "a4"},
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["HACKME_RUNTIME_DIR"] = str(runtime_dir)
    env["HTML_LEARNING_CHESS_RETRAIN_MIN_REPLAYS"] = "1"

    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_train_pipeline.py"),
            "--preset",
            "micro",
            "--min-usable-replays",
            "1",
            "--skip-promote",
            "--promote-engines",
            "experiment 3:dl",
        ],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["prepare"]["accepted_train_samples"] >= 1
    assert payload["prepare"]["accepted_eval_samples"] >= 1
    assert payload["seed_train"]["games_played"] >= 1
    assert Path(payload["benchmark"]["reports"]["json_report"]).exists()
    assert payload["promotion_results"][0]["engine"] == "experiment 3:dl"
    assert payload["promotion_results"][0]["staged"] is True
    assert Path(payload["reports"]["json_report"]).exists()
    assert Path(payload["reports"]["md_report"]).exists()
