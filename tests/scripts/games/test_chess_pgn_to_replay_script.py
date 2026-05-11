import json
import os
import subprocess
import sys
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[3]


def _run_import(tmp_path, pgn_text, *extra_args):
    input_path = tmp_path / "games.pgn"
    output_path = tmp_path / "replays.jsonl"
    input_path.write_text(pgn_text, encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_pgn_to_replay.py"),
            "--input-pgn",
            str(input_path),
            "--output-jsonl",
            str(output_path),
            "--replace-output",
            *extra_args,
        ],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    summary = json.loads(proc.stdout)
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return summary, rows


def test_chess_pgn_to_replay_preserves_special_rule_moves(tmp_path):
    pgn = """
[Event "Castling sample"]
[Site "local"]
[Date "2026.05.11"]
[Round "1"]
[White "White"]
[Black "Black"]
[Result "1/2-1/2"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 Nf6 4. O-O Be7 5. Re1 O-O 1/2-1/2

[Event "Promotion sample"]
[Site "local"]
[Date "2026.05.11"]
[Round "2"]
[White "White"]
[Black "Black"]
[Result "1-0"]
[SetUp "1"]
[FEN "k7/4P3/8/8/8/8/8/4K3 w - - 0 1"]

1. e8=Q# 1-0
""".strip()
    summary, rows = _run_import(tmp_path, pgn, "--min-ply", "1")

    assert summary["ok"] is True
    assert summary["written_records"] == 2
    assert summary["special_rule_counts"]["castling"] == 1
    assert summary["special_rule_counts"]["promotion"] == 1
    assert any(move.get("castle") for move in rows[0]["move_history"])
    assert rows[1]["move_history"][0]["promotion"] == "q"
    assert rows[1]["opening_seed"].startswith("k7/4P3")
    assert rows[1]["winner_color"] == "white"
    assert rows[1]["collection_tier"] == "trusted"
    assert rows[1]["source"] == "imported_dataset"
    assert "contains_promotion" in rows[1]["training_tags"]


def test_chess_pgn_to_replay_can_filter_and_sample_deterministically(tmp_path):
    pgn = """
[Event "Low rated"]
[Site "local"]
[White "A"]
[Black "B"]
[WhiteElo "900"]
[BlackElo "900"]
[Result "1-0"]

1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0

[Event "Master one"]
[Site "local"]
[White "C"]
[Black "D"]
[WhiteElo "2300"]
[BlackElo "2310"]
[Result "1-0"]

1. d4 d5 2. c4 e6 3. Nc3 Nf6 4. Bg5 Be7 1-0

[Event "Master two"]
[Site "local"]
[White "E"]
[Black "F"]
[WhiteElo "2400"]
[BlackElo "2410"]
[Result "0-1"]

1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 0-1
""".strip()
    summary_a, rows_a = _run_import(
        tmp_path,
        pgn,
        "--min-elo",
        "2200",
        "--sample-size",
        "1",
        "--seed",
        "7",
    )
    summary_b, rows_b = _run_import(
        tmp_path,
        pgn,
        "--min-elo",
        "2200",
        "--sample-size",
        "1",
        "--seed",
        "7",
    )

    assert summary_a["eligible_games"] == 2
    assert summary_a["written_records"] == 1
    assert rows_a[0]["replay_id"] == rows_b[0]["replay_id"]
    assert rows_a[0]["rating_estimate"] >= 2200
    assert rows_a[0]["pgn_labels"]["rating_band"] == "master"


def test_chess_pgn_to_replay_reads_zip_archives(tmp_path):
    archive_path = tmp_path / "games.zip"
    output_path = tmp_path / "replays.jsonl"
    pgn = """
[Event "Zip sample"]
[Site "local"]
[White "A"]
[Black "B"]
[Result "1-0"]

1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0
""".strip()
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("inside.pgn", pgn)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_pgn_to_replay.py"),
            "--input-pgn",
            str(archive_path),
            "--output-jsonl",
            str(output_path),
            "--replace-output",
            "--min-ply",
            "1",
        ],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    summary = json.loads(proc.stdout)
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert summary["written_records"] == 1
    assert rows[0]["pgn_labels"]["event"] == "Zip sample"
