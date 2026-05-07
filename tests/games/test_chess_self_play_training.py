import json
from pathlib import Path

import chess

from services.games.chess_engine import ChessExperimentStore
from services.games.self_play_training import (
    TEACHER_DIFFICULTY,
    choose_teacher_move,
    run_training_session,
    write_training_report,
)


def test_teacher_engine_finds_mate_in_one():
    board = {"__fen__": "6k1/5Q2/6K1/8/8/8/8/8 w - - 0 1"}
    move = choose_teacher_move({"__fen__": "6k1/5Q2/6K1/8/8/8/8/8 w - - 0 1"}, "white", depth=2)
    board_obj = chess.Board(board["__fen__"])
    mating_moves = set()
    for legal in board_obj.legal_moves:
        board_after = board_obj.copy(stack=False)
        board_after.push(legal)
        if board_after.is_checkmate():
            mating_moves.add(legal.uci())

    assert move is not None
    chosen_uci = f"{move['from']}{move['to']}{move.get('promotion') or ''}"
    assert chosen_uci in mating_moves


def test_training_session_updates_runtime_db_and_nn_model(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    experiment_db = runtime_dir / "database" / "chess_experiment.db"
    experiment_nn = runtime_dir / "models" / "chess_experiment_2_nn.json"
    monkeypatch.setenv("HACKME_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_DB_PATH", str(experiment_db))
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_NN_MODEL_PATH", str(experiment_nn))

    summary = run_training_session(
        exp1_teacher_games=1,
        exp2_teacher_games=1,
        cross_games=1,
        teacher_depth=1,
        max_plies=12,
        student_exploration_rate=1.0,
        seed=7,
        store=ChessExperimentStore(experiment_db),
        nn_model_path=experiment_nn,
    )

    assert summary["games_played"] == 3
    assert summary["experiment_db_path"] == str(experiment_db)
    assert summary["experiment_2_nn_model_path"] == str(experiment_nn)
    assert experiment_db.exists()
    assert experiment_nn.exists()
    assert any(match["white_engine"] == TEACHER_DIFFICULTY or match["black_engine"] == TEACHER_DIFFICULTY for match in summary["matches"])

    model = json.loads(experiment_nn.read_text(encoding="utf-8"))
    assert model["sample_count"] >= 1
    reports = write_training_report(summary, report_dir=runtime_dir / "reports" / "games")
    assert Path(reports["json_report"]).exists()
    assert Path(reports["md_report"]).exists()
