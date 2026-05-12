import json
import sqlite3

import chess

from routes import games as games_routes
from routes.games import choose_computer_move, ensure_game_schema
from services.games import chess_pipeline
from services.games import self_play_training
from services.games.chess_nnue import (
    EXPERIMENT_NNUE_DIFFICULTY,
    choose_experiment_nnue_move,
    train_experiment_nnue_from_replay_samples,
)


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


def test_exp5_is_supported_pipeline_autorun_target():
    assert EXPERIMENT_NNUE_DIFFICULTY in chess_pipeline.PIPELINE_RETRAIN_ENGINES
    args = chess_pipeline._pipeline_command_args(
        min_usable_replays=3,
        target_engines=[EXPERIMENT_NNUE_DIFFICULTY],
    )
    assert args[args.index("--promote-engines") + 1] == EXPERIMENT_NNUE_DIFFICULTY
    assert "--skip-exp3" in args
    assert "--skip-exp4" in args
    assert "--skip-exp5" not in args


def test_exp5_rule_priority_handles_core_special_moves(tmp_path):
    model_path = tmp_path / "exp5.json"
    cases = [
        ("k7/4P3/2K5/8/8/8/8/8 w - - 0 1", "white", "e7e8q"),
        ("7k/8/8/3pP3/8/8/8/4K3 w - d6 0 1", "white", "e5d6"),
        ("4k3/8/8/8/8/8/4r3/4K3 w - - 0 1", "white", "e1e2"),
        ("4k3/8/8/8/8/8/8/4K2R w K - 0 1", "white", "e1g1"),
        ("r3k3/8/8/8/8/8/8/4K3 b q - 0 1", "black", "e8c8"),
        ("3K4/1PQ2p2/k7/4b3/4Q3/3R4/8/1Q6 w - - 0 1", "white", "b7b8n"),
    ]
    for fen, side, expected in cases:
        move = choose_experiment_nnue_move(
            {"__fen__": fen},
            side,
            model_path=model_path,
            search_profile="fixed_depth_fast",
        )
        chosen = f"{move['from']}{move['to']}{move.get('promotion') or ''}"
        assert chosen == expected


def test_exp5_avoids_stalemate_when_legal_alternative_exists(tmp_path):
    model_path = tmp_path / "exp5.json"
    fen = "4Q3/8/8/4k3/8/4K3/8/8 w - - 0 1"
    move = choose_experiment_nnue_move(
        {"__fen__": fen},
        "white",
        model_path=model_path,
        search_profile="fixed_depth_fast",
    )
    chosen = chess.Move.from_uci(f"{move['from']}{move['to']}{move.get('promotion') or ''}")
    board = chess.Board(fen)
    assert chosen in board.legal_moves
    board.push(chosen)
    assert not board.is_stalemate()


def test_exp5_training_positive_black_sample_increases_black_piece_weight(tmp_path):
    model_path = tmp_path / "exp5.json"
    replay_path = tmp_path / "exp5_replay.jsonl"

    result = train_experiment_nnue_from_replay_samples(
        [
            {
                "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1",
                "side": "black",
                "move_uci": "e7e5",
                "target": 1.0,
                "weight": 4.0,
            }
        ],
        model_path=model_path,
        replay_path=replay_path,
        replace_replay=True,
        epochs=1,
    )

    payload = json.loads(model_path.read_text(encoding="utf-8"))
    assert result["accepted_samples"] == 1
    assert payload["piece_square_weights"]["b:p:e5"] > 0
