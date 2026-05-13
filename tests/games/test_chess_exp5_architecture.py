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
    experiment_nnue_model_template,
    train_experiment_nnue_from_replay_samples,
)


def _opponent_mate_in_one_after(fen, move_uci):
    board = chess.Board(fen)
    move = chess.Move.from_uci(move_uci)
    assert move in board.legal_moves
    board.push(move)
    mate_replies = []
    for reply in board.legal_moves:
        board.push(reply)
        if board.is_checkmate():
            mate_replies.append(reply.uci())
        board.pop()
    return mate_replies


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
    assert called == {"board": board, "side": "black", "search_profile": "balanced"}

    history = [{"from": "g1", "to": "f3", "promotion": None}]
    assert choose_computer_move(board, "black", EXPERIMENT_NNUE_DIFFICULTY, move_history=history) == sentinel
    assert called["board"] is not board
    assert called == {
        "board": {**board, "__move_history__": history},
        "side": "black",
        "search_profile": "balanced",
    }


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
    assert "experiment 4:pv" in chess_pipeline.PIPELINE_RETRAIN_ENGINES
    assert "experiment 4:pv" not in chess_pipeline.PIPELINE_DEFAULT_PROMOTE_ENGINES
    default_args = chess_pipeline._pipeline_command_args(min_usable_replays=3)
    assert default_args[default_args.index("--promote-engines") + 1] == "experiment 3:dl,experiment 5:nnue"
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


def test_exp5_opening_overlay_uses_exact_position_book_prior(tmp_path):
    model_path = tmp_path / "exp5_overlay.json"
    payload = experiment_nnue_model_template()
    payload["opening_overlay"] = {
        "enabled": True,
        "version": "exp5_opening_overlay_v1",
        "mode": "exact_position_book_prior",
        "max_fullmove": 12,
        "positions": {
            "ce30807049a23e2f3a9eb122e950cb3530814ac9ce92c77c89d7adbb6c8bd3c4": {
                "id": "start",
                "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                "side": "white",
                "label_quality": "clean",
                "moves": [
                    {"uci": "e2e4", "weight": 100},
                    {"uci": "d2d4", "weight": 99},
                ],
            }
        },
    }
    model_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    chosen = choose_experiment_nnue_move(
        {"__fen__": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"},
        "white",
        model_path=model_path,
        search_profile="fixed_depth_strong",
    )

    assert f"{chosen['from']}{chosen['to']}{chosen.get('promotion') or ''}" == "e2e4"


def test_exp5_opening_overlay_can_override_broad_early_castle_heuristic(tmp_path):
    model_path = tmp_path / "exp5_overlay.json"
    fen = "r1bqkbnr/1ppp1ppp/p1n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 4"
    payload = experiment_nnue_model_template()
    payload["opening_overlay"] = {
        "enabled": True,
        "version": "exp5_opening_overlay_v1",
        "mode": "exact_position_book_prior",
        "max_fullmove": 12,
        "positions": {
            "b9b6917204d4136fc655581831afd0601c9816446c1bb15e5dae0ee594417950": {
                "id": "ruy_after_a6",
                "fen": fen,
                "side": "white",
                "label_quality": "clean",
                "moves": [
                    {"uci": "b5a4", "weight": 100},
                    {"uci": "b5c6", "weight": 99},
                ],
            }
        },
    }
    model_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    chosen = choose_experiment_nnue_move(
        {"__fen__": fen},
        "white",
        model_path=model_path,
        search_profile="fixed_depth_strong",
    )

    assert f"{chosen['from']}{chosen['to']}{chosen.get('promotion') or ''}" == "b5a4"


def test_exp5_offbook_opening_prefers_development_over_flank_pawn(tmp_path):
    model_path = tmp_path / "exp5.json"
    fen = "rnbqkbnr/pppppppp/8/8/8/7N/PPPPPPPP/RNBQKB1R b KQkq - 1 1"

    chosen = choose_experiment_nnue_move(
        {"__fen__": fen},
        "black",
        model_path=model_path,
        search_profile="fixed_depth_fast",
    )

    chosen_uci = f"{chosen['from']}{chosen['to']}{chosen.get('promotion') or ''}"
    assert chosen_uci not in {"a7a5", "a7a6", "h7h5", "h7h6"}
    board = chess.Board(fen)
    move = chess.Move.from_uci(chosen_uci)
    assert move in board.legal_moves


def test_exp5_replay_prior_follows_downloaded_template_line():
    chosen = choose_experiment_nnue_move(
        {"__fen__": chess.STARTING_FEN},
        "white",
        search_profile="fixed_depth_fast",
    )

    assert f"{chosen['from']}{chosen['to']}{chosen.get('promotion') or ''}" == "d2d4"


def test_exp5_opening_guard_blocks_low_value_rook_excursion(tmp_path):
    model_path = tmp_path / "exp5.json"
    fen = "rnbqkbnr/3pppBp/8/1N6/2p2P2/P6N/P1PPP1PP/R2QKB1R b KQkq - 0 7"

    chosen = choose_experiment_nnue_move(
        {"__fen__": fen},
        "black",
        model_path=model_path,
        search_profile="fixed_depth_fast",
    )

    assert f"{chosen['from']}{chosen['to']}{chosen.get('promotion') or ''}" != "a8a3"


def test_exp5_tactical_safety_blocks_direct_rook_hang(tmp_path):
    model_path = tmp_path / "exp5.json"
    fen = "1nbqkbnB/3ppp1p/8/1N6/2p2P2/r6N/P1PPP1PP/R2QKB1R b KQk - 0 8"

    chosen = choose_experiment_nnue_move(
        {"__fen__": fen},
        "black",
        model_path=model_path,
        search_profile="fixed_depth_fast",
    )

    assert f"{chosen['from']}{chosen['to']}{chosen.get('promotion') or ''}" != "a3h3"


def test_exp5_prioritizes_safe_minor_piece_recapture(tmp_path):
    model_path = tmp_path / "exp5.json"
    fen = "r2k1b1r/p1p1ppp1/p6p/3p4/5P2/2N5/PP1B2PP/2Rb1RK1 w - - 0 12"

    chosen = choose_experiment_nnue_move(
        {"__fen__": fen},
        "white",
        model_path=model_path,
        search_profile="fixed_depth_fast",
    )

    assert f"{chosen['from']}{chosen['to']}{chosen.get('promotion') or ''}" in {"c1d1", "c3d1", "f1d1"}


def test_exp5_captures_dangerous_advanced_pawn(tmp_path):
    model_path = tmp_path / "exp5.json"
    fen = "8/8/8/8/8/8/R1p5/4K2k w - - 0 1"

    chosen = choose_experiment_nnue_move(
        {"__fen__": fen},
        "white",
        model_path=model_path,
        search_profile="fixed_depth_fast",
    )

    assert f"{chosen['from']}{chosen['to']}{chosen.get('promotion') or ''}" == "a2c2"


def test_exp5_blocks_scholar_mate_threat(tmp_path):
    model_path = tmp_path / "exp5.json"
    fen = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"

    chosen = choose_experiment_nnue_move(
        {"__fen__": fen},
        "black",
        model_path=model_path,
        search_profile="fixed_depth_fast",
    )

    chosen_uci = f"{chosen['from']}{chosen['to']}{chosen.get('promotion') or ''}"
    assert "h5f7" not in _opponent_mate_in_one_after(fen, chosen_uci)


def test_exp5_avoids_self_opened_mate_in_one(tmp_path):
    model_path = tmp_path / "exp5.json"
    fen = "6k1/5ppp/3b4/8/7q/8/5PPP/6K1 w - - 0 1"

    chosen = choose_experiment_nnue_move(
        {"__fen__": fen},
        "white",
        model_path=model_path,
        search_profile="fixed_depth_fast",
    )

    chosen_uci = f"{chosen['from']}{chosen['to']}{chosen.get('promotion') or ''}"
    assert chosen_uci != "f2f3"
    assert not _opponent_mate_in_one_after(fen, chosen_uci)


def test_exp5_history_aware_filter_keeps_claimable_draw_when_not_clearly_ahead(tmp_path):
    model_path = tmp_path / "exp5.json"
    history_uci = [
        "g1h3", "g8f6", "b1c3", "b8c6", "f2f4", "d7d5", "c3d5", "c8h3",
        "d5f6", "e7f6", "g2h3", "f8d6", "f1g2", "e8g8", "g2c6", "b7c6",
        "e1g1", "c6c5", "f4f5", "c5c4", "e2e4", "c4c3", "d2c3", "a7a6",
        "d1d6", "c7d6", "c1f4", "g7g5", "f5g6", "a8a7", "g6h7", "g8h7",
        "c3c4", "a7a8", "h3h4", "a8a7", "h4h5", "a7a8", "h5h6", "a8a7",
        "h2h4", "a7a8", "h4h5", "a8a7", "c2c3", "a7a8", "b2b4", "a8a7",
        "a2a4", "a7a8", "f1e1", "a8a7", "e1f1", "a7a8", "f1e1",
    ]
    history = [{"from": uci[:2], "to": uci[2:4], "promotion": uci[4:] or None} for uci in history_uci]
    fen = "r2q1r2/5p1k/p2p1p1P/7P/PPP1PB2/2P5/8/R3R1K1 b - - 6 28"

    chosen = choose_experiment_nnue_move(
        {"__fen__": fen, "__move_history__": history},
        "black",
        model_path=model_path,
        search_profile="balanced",
    )

    chosen_uci = f"{chosen['from']}{chosen['to']}{chosen.get('promotion') or ''}"
    board = chess.Board()
    for move_uci in history_uci:
        board.push(chess.Move.from_uci(move_uci))
    assert board.fen() == fen
    board.push(chess.Move.from_uci(chosen_uci))
    assert board.can_claim_threefold_repetition()
