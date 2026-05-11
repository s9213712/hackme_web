import json
import sqlite3

from routes import games as games_routes
from routes.games import choose_computer_move, ensure_game_schema
from services.games import self_play_training
from services.games.chess_nnue import EXPERIMENT_NNUE_DIFFICULTY


def test_exp5_difficulty_is_schema_supported():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user'
        )
        """
    )
    conn.execute("INSERT INTO users (id, username) VALUES (1, 'alice')")
    ensure_game_schema(conn)

    conn.execute(
        """
        INSERT INTO game_matches (
            game_key, mode, status, white_user_id, black_user_id, human_side,
            computer_difficulty, current_turn, board_json, move_history_json,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "chess",
            "computer",
            "active",
            1,
            None,
            "white",
            EXPERIMENT_NNUE_DIFFICULTY,
            "white",
            json.dumps({}),
            "[]",
            "2026-05-11T00:00:00Z",
            "2026-05-11T00:00:00Z",
        ),
    )

    row = conn.execute("SELECT computer_difficulty FROM game_matches").fetchone()
    assert row["computer_difficulty"] == EXPERIMENT_NNUE_DIFFICULTY


def test_exp5_computer_move_dispatches_to_nnue_engine(monkeypatch):
    sentinel = {"from": "e7", "to": "e5", "piece": "p"}
    called = {}

    def fake_choose_nnue_move(board, side, *, search_profile="balanced"):
        called["board"] = board
        called["side"] = side
        called["search_profile"] = search_profile
        return sentinel

    monkeypatch.setattr(games_routes, "choose_experiment_nnue_move", fake_choose_nnue_move)

    board = {"__fen__": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1"}
    assert choose_computer_move(board, "black", EXPERIMENT_NNUE_DIFFICULTY) == sentinel
    assert called == {"board": board, "side": "black", "search_profile": "fast"}


def test_exp5_is_benchmark_engine_and_uses_nnue_model_path(monkeypatch, tmp_path):
    sentinel = {"from": "e7", "to": "e5", "piece": "p"}
    called = {}

    def fake_choose_nnue_move(board, side, *, model_path=None, search_profile="balanced"):
        called["board"] = board
        called["side"] = side
        called["model_path"] = model_path
        called["search_profile"] = search_profile
        return sentinel

    model_path = tmp_path / "exp5.json"
    monkeypatch.setattr(self_play_training, "choose_experiment_nnue_move", fake_choose_nnue_move)

    board = {"__fen__": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1"}
    assert EXPERIMENT_NNUE_DIFFICULTY in self_play_training.BENCHMARK_ENGINES
    assert self_play_training._engine_move_for_benchmark(
        EXPERIMENT_NNUE_DIFFICULTY,
        board,
        "black",
        store=self_play_training.ChessExperimentStore(tmp_path / "exp1.db"),
        nn_model_path=tmp_path / "exp2.json",
        dl_model_path=tmp_path / "exp3.json",
        pv_model_path=tmp_path / "exp4.json",
        nnue_model_path=model_path,
        teacher_depth=1,
    ) == sentinel
    assert called == {
        "board": board,
        "side": "black",
        "model_path": model_path,
        "search_profile": "strong",
    }
