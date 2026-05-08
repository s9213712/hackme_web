import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_chess_replay_prepare_script_emits_train_and_eval_sets(tmp_path):
    runtime_dir = tmp_path / "runtime"
    reports_dir = runtime_dir / "reports" / "games"
    reports_dir.mkdir(parents=True, exist_ok=True)
    trusted_path = reports_dir / "chess_replays.jsonl"
    quarantine_path = reports_dir / "chess_replays_quarantine.jsonl"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["HACKME_RUNTIME_DIR"] = str(runtime_dir)
    env["HTML_LEARNING_CHESS_REPLAY_BUFFER_PATH"] = str(trusted_path)
    env["HTML_LEARNING_CHESS_REPLAY_QUARANTINE_PATH"] = str(quarantine_path)

    trusted_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "replay_id": "trusted-1",
                        "source": "user_games",
                        "confidence_score": 0.8,
                        "adjudicated_or_natural": "natural",
                        "opening_seed": "standard_start",
                        "move_count": 8,
                        "winner_color": "white",
                        "move_history": [
                            {"by": "white", "from": "e2", "to": "e4"},
                            {"by": "black", "from": "e7", "to": "e5"},
                            {"by": "white", "from": "g1", "to": "f3"},
                            {"by": "black", "from": "b8", "to": "c6"},
                            {"by": "white", "from": "f1", "to": "c4"},
                            {"by": "black", "from": "g8", "to": "f6"},
                            {"by": "white", "from": "d2", "to": "d3"},
                            {"by": "black", "from": "f8", "to": "c5"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "replay_id": "trusted-2",
                        "source": "user_games",
                        "confidence_score": 0.7,
                        "adjudicated_or_natural": "natural",
                        "opening_seed": "standard_start",
                        "move_count": 8,
                        "winner_color": None,
                        "move_history": [
                            {"by": "white", "from": "d2", "to": "d4"},
                            {"by": "black", "from": "d7", "to": "d5"},
                            {"by": "white", "from": "c1", "to": "f4"},
                            {"by": "black", "from": "g8", "to": "f6"},
                            {"by": "white", "from": "e2", "to": "e3"},
                            {"by": "black", "from": "c8", "to": "f5"},
                            {"by": "white", "from": "f1", "to": "d3"},
                            {"by": "black", "from": "e7", "to": "e6"},
                        ],
                    },
                    ensure_ascii=False,
                ),
            ]
        ) + "\n",
        encoding="utf-8",
    )
    quarantine_path.write_text(
        json.dumps(
            {
                "replay_id": "quarantine-1",
                "source": "user_games",
                "confidence_score": 0.3,
                "adjudicated_or_natural": "natural",
                "opening_seed": "standard_start",
                "move_count": 8,
                "winner_color": "black",
                "move_history": [
                    {"by": "white", "from": "c2", "to": "c4"},
                    {"by": "black", "from": "e7", "to": "e5"},
                    {"by": "white", "from": "b1", "to": "c3"},
                    {"by": "black", "from": "g8", "to": "f6"},
                    {"by": "white", "from": "g2", "to": "g3"},
                    {"by": "black", "from": "d7", "to": "d5"},
                    {"by": "white", "from": "f1", "to": "g2"},
                    {"by": "black", "from": "f8", "to": "b4"},
                ],
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_replay_prepare.py"),
            "--replace-output",
            "--include-quarantine",
        ],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["trusted_replays_seen"] == 2
    assert payload["quarantine_replays_seen"] == 1
    assert payload["accepted_train_samples"] >= 1
    assert payload["accepted_eval_samples"] >= 1
    assert Path(payload["train_path"]).exists()
    assert Path(payload["eval_path"]).exists()
    assert Path(payload["reports"]["json_report"]).exists()
    assert Path(payload["reports"]["md_report"]).exists()
