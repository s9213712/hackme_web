import json
import hashlib
import sqlite3
from pathlib import Path

import chess

from routes import games as games_routes
from routes.games import choose_computer_move, ensure_game_schema
from services.games import chess_pipeline
from services.games import self_play_training
from services.games.chess_nnue import (
    EXPERIMENT_NNUE_DIFFICULTY,
    EXP5_EXPERIENCE_DELTA_FORMAT,
    EXP5_PRODUCTION_SEARCH_PROFILE,
    EXP5_STATIC_BASE_MODEL_SHA256,
    _avoid_claimable_repetition_filter,
    _avoid_enabling_opponent_repetition_when_ahead_filter,
    _avoid_non_progress_shuffle_when_ahead_filter,
    _avoid_shuffle_with_advanced_pawn_push_filter,
    _avoid_unanswered_immediate_promotion_filter,
    _endgame_progress_filter,
    _forced_single_reply_mate_net_move,
    _opening_king_walk_filter,
    _opening_moved_king_home_filter,
    _opening_trap_priority_move,
    _pawn_structure_score,
    _piece_activity_score,
    _resolve_search_profile,
    _special_rule_fusion_filter,
    _avoid_reversible_cycle_when_ahead_filter,
    _static_exchange_eval,
    choose_experiment_nnue_move,
    exp5_model_artifact_policy,
    experiment_nnue_model_template,
    train_experiment_nnue_from_replay_samples,
)


ROOT = Path(__file__).resolve().parents[2]


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
    assert called == {"board": board, "side": "black", "search_profile": EXP5_PRODUCTION_SEARCH_PROFILE}

    history = [{"from": "g1", "to": "f3", "promotion": None}]
    assert choose_computer_move(board, "black", EXPERIMENT_NNUE_DIFFICULTY, move_history=history) == sentinel
    assert called["board"] is not board
    assert called == {
        "board": {**board, "__move_history__": history},
        "side": "black",
        "search_profile": EXP5_PRODUCTION_SEARCH_PROFILE,
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
    assert default_args[default_args.index("--promote-engines") + 1] == "experiment 3:dl"
    assert "--skip-exp5-refine" in default_args
    args = chess_pipeline._pipeline_command_args(
        min_usable_replays=3,
        target_engines=[EXPERIMENT_NNUE_DIFFICULTY],
    )
    assert args[args.index("--promote-engines") + 1] == EXPERIMENT_NNUE_DIFFICULTY
    assert "--skip-exp3" in args
    assert "--skip-exp4" in args
    assert "--skip-exp5" not in args


def test_exp5_model_policy_separates_static_base_from_generated_artifacts():
    policy = exp5_model_artifact_policy()
    assert policy["engine"] == EXPERIMENT_NNUE_DIFFICULTY
    assert policy["main_model_role"] == "static_base_eval_parameters"
    assert policy["generated_artifact_role"] == "adapter_or_experience_table"
    assert policy["main_model_generation_default"] == "disabled"
    assert policy["source_base_module"] == "services.games.chess_exp5_base_model"
    assert policy["bundled_main_json_required"] is False
    assert policy["runtime_experience_model_name"] == "chess_experiment_5_nnue_experience.json"
    assert policy["experience_delta_format"] == EXP5_EXPERIENCE_DELTA_FORMAT
    assert policy["score_versions_may_change_without_model_checksum_change"] is True


def test_exp5_base_model_is_source_embedded_and_legacy_main_json_removed():
    payload = experiment_nnue_model_template()
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    assert hashlib.sha256(body.encode("utf-8")).hexdigest() == EXP5_STATIC_BASE_MODEL_SHA256
    assert payload["sample_count"] == 1837
    assert payload["opening_overlay"]["positions"]
    assert not (ROOT / "services/games/models/chess_experiment_5_nnue.json").exists()


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


def test_exp5_uses_deterministic_static_opening_book_when_overlay_misses(tmp_path):
    model_path = tmp_path / "exp5_no_overlay.json"
    payload = experiment_nnue_model_template()
    payload["opening_overlay"] = {"enabled": False, "positions": {}}
    model_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    move = choose_experiment_nnue_move(
        {"__fen__": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"},
        "black",
        model_path=model_path,
        search_profile="fixed_depth_deep",
    )

    assert f"{move['from']}{move['to']}{move.get('promotion') or ''}" == "c7c5"


def test_exp5_special_rule_final_fusion_promotes_close_castling_choice():
    board = chess.Board("4k3/8/8/8/8/8/8/R3K2R w KQ - 0 1")
    quiet = chess.Move.from_uci("a1a2")
    castle = chess.Move.from_uci("e1g1")
    assert quiet in board.legal_moves
    assert castle in board.legal_moves

    chosen = _special_rule_fusion_filter(
        board,
        quiet,
        score_move=lambda move: {quiet: 1000.0, castle: 900.0}.get(move, 0.0),
    )

    assert chosen == castle


def test_exp5_eval_rewards_bishop_pair_and_penalizes_doubled_isolated_pawns():
    active = chess.Board("4k3/8/8/8/8/8/8/2B1KB2 w - - 0 1")
    passive = chess.Board("4k3/8/2p5/8/8/2P5/2P5/4K3 w - - 0 1")

    assert _piece_activity_score(active) > 0
    assert _pawn_structure_score(passive) < 0


def test_exp5_v28e_low_legal_check_escape_is_current_profile():
    v27k = _resolve_search_profile("fixed_depth_fianchetto_tail_castle_guard_v27k_depth3_no_null_mate_net30_defense_book")
    v28e = _resolve_search_profile(
        "fixed_depth_fianchetto_tail_castle_guard_v28e_depth3_no_null_mate_net30_fast_king_mobility4"
    )

    assert EXP5_PRODUCTION_SEARCH_PROFILE == (
        "fixed_depth_fianchetto_tail_castle_guard_v28e_depth3_no_null_mate_net30_fast_king_mobility4"
    )
    assert not v27k.get("enable_final_low_legal_check_escape")
    assert v28e["enable_final_low_legal_check_escape"] is True
    assert v28e["final_low_legal_check_escape_enable_king_mobility4"] is True
    assert v28e["final_low_legal_check_escape_max_legal"] == 4
    assert v28e["final_low_legal_check_escape_max_depth"] == 0
    assert v28e["enable_king_zone_pressure"] is False
    assert v28e["enable_pawn_structure"] is False
    assert v28e["quiescence_depth"] == v27k["quiescence_depth"] == 2


def test_exp5_adapter_exact_memory_is_guarded_and_opt_in(monkeypatch, tmp_path):
    main_model_path = tmp_path / "main_exp5.json"
    adapter_model_path = tmp_path / "adapter_exp5.json"
    rows_path = tmp_path / "adapter_rows.jsonl"
    main_model_path.write_text(json.dumps(experiment_nnue_model_template()), encoding="utf-8")
    adapter_model_path.write_text(json.dumps(experiment_nnue_model_template()), encoding="utf-8")
    fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    rows_path.write_text(
        json.dumps(
            {
                "fen": fen,
                "side": "white",
                "move_uci": "g1f3",
                "label_quality": "clean",
                "teacher_top3": ["g1f3"],
                "source": "test_adapter_memory",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_NNUE_MODEL_PATH", str(main_model_path))
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_MODEL_PATH", str(adapter_model_path))
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_ROWS_PATH", str(rows_path))
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_MODE", "exact")

    move = choose_experiment_nnue_move(
        {"__fen__": fen},
        "white",
        search_profile="fixed_depth_fast",
    )
    chosen = f"{move['from']}{move['to']}{move.get('promotion') or ''}"
    assert chosen == "g1f3"
    assert move["adapter_decision"]["adopted"] is True
    assert move["adapter_decision"]["source"] == "exact_memory"


def test_exp5_adapter_without_exact_memory_falls_back_to_main(monkeypatch, tmp_path):
    main_model_path = tmp_path / "main_exp5.json"
    adapter_model_path = tmp_path / "adapter_exp5.json"
    rows_path = tmp_path / "adapter_rows.jsonl"
    main_model_path.write_text(json.dumps(experiment_nnue_model_template()), encoding="utf-8")
    adapter_model_path.write_text(json.dumps(experiment_nnue_model_template()), encoding="utf-8")
    rows_path.write_text(
        json.dumps(
            {
                "fen": "8/8/8/8/8/8/8/8 w - - 0 1",
                "side": "white",
                "move_uci": "a1a2",
                "label_quality": "clean",
                "source": "unmatched_test_adapter_memory",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_NNUE_MODEL_PATH", str(main_model_path))
    monkeypatch.delenv("HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_MODEL_PATH", raising=False)
    monkeypatch.delenv("HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_ROWS_PATH", raising=False)
    monkeypatch.delenv("HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_MODE", raising=False)
    monkeypatch.delenv("HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_ALLOW_GENERAL", raising=False)
    direct = choose_experiment_nnue_move(
        {"__fen__": fen},
        "white",
        search_profile="fixed_depth_fast",
    )
    direct_uci = f"{direct['from']}{direct['to']}{direct.get('promotion') or ''}"

    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_MODEL_PATH", str(adapter_model_path))
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_ROWS_PATH", str(rows_path))
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_MODE", "guarded")
    monkeypatch.delenv("HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_ALLOW_GENERAL", raising=False)

    move = choose_experiment_nnue_move(
        {"__fen__": fen},
        "white",
        search_profile="fixed_depth_fast",
    )
    chosen = f"{move['from']}{move['to']}{move.get('promotion') or ''}"
    assert chosen == direct_uci
    assert move["adapter_decision"]["adopted"] is False
    assert move["adapter_decision"]["source"] == "none"
    assert "no_exact_memory" in move["adapter_decision"]["reasons"]


def test_exp5_guarded_adapter_keeps_exact_memory_as_shadow_notes(monkeypatch, tmp_path):
    main_model_path = tmp_path / "main_exp5.json"
    adapter_model_path = tmp_path / "adapter_exp5.json"
    rows_path = tmp_path / "adapter_rows.jsonl"
    main_model_path.write_text(json.dumps(experiment_nnue_model_template()), encoding="utf-8")
    adapter_model_path.write_text(json.dumps(experiment_nnue_model_template()), encoding="utf-8")
    fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    rows_path.write_text(
        json.dumps(
            {
                "fen": fen,
                "side": "white",
                "move_uci": "g1f3",
                "label_quality": "clean",
                "baseline_teacher_rank": 1,
                "baseline_policy_gap_cp": 0,
                "source": "test_adapter_memory",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_NNUE_MODEL_PATH", str(main_model_path))
    monkeypatch.delenv("HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_MODEL_PATH", raising=False)
    direct = choose_experiment_nnue_move(
        {"__fen__": fen},
        "white",
        search_profile="fixed_depth_fast",
    )
    direct_uci = f"{direct['from']}{direct['to']}{direct.get('promotion') or ''}"

    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_MODEL_PATH", str(adapter_model_path))
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_ROWS_PATH", str(rows_path))
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_MODE", "guarded")
    monkeypatch.delenv("HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_ALLOW_EXACT", raising=False)
    monkeypatch.delenv("HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_ALLOW_GENERAL", raising=False)

    move = choose_experiment_nnue_move(
        {"__fen__": fen},
        "white",
        search_profile="fixed_depth_fast",
    )
    chosen = f"{move['from']}{move['to']}{move.get('promotion') or ''}"
    assert chosen == direct_uci
    assert move["adapter_decision"]["adopted"] is False
    assert move["adapter_decision"]["source"] == "exact_memory"
    assert "exact_memory_shadow_only" in move["adapter_decision"]["reasons"]


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


def test_exp5_static_exchange_eval_separates_safe_and_poisoned_captures():
    safe_board = chess.Board("6k1/8/8/4b3/8/8/8/4R1K1 w - - 0 1")
    safe_capture = chess.Move.from_uci("e1e5")
    assert safe_capture in safe_board.legal_moves
    assert _static_exchange_eval(safe_board, safe_capture) >= 300

    poisoned_board = chess.Board("4r1k1/8/8/4b3/8/8/8/4R1K1 w - - 0 1")
    poisoned_capture = chess.Move.from_uci("e1e5")
    assert poisoned_capture in poisoned_board.legal_moves
    assert _static_exchange_eval(poisoned_board, poisoned_capture) < 0


def test_exp5_cycle_filter_blocks_reverse_move_when_ahead():
    board = chess.Board("8/pk6/p7/P7/2p2p1p/R1N2p1p/2P2R1P/7K w - - 10 46")
    reverse_move = chess.Move.from_uci("a3a2")
    assert reverse_move in board.legal_moves
    board.move_stack.clear()
    board.move_stack.extend([chess.Move.from_uci("a2a3"), chess.Move.from_uci("b7c7")])

    chosen = _avoid_reversible_cycle_when_ahead_filter(
        board,
        reverse_move,
        side="white",
        score_move=lambda _move: 0.0,
    )

    assert chosen != reverse_move
    assert chosen in board.legal_moves


def test_exp5_filter_blocks_move_that_lets_opponent_claim_repetition_when_ahead():
    board = chess.Board()
    history_uci = [
        "c2c4", "g8f6", "g1h3", "b8c6", "b1c3", "d7d5", "c4d5", "c8h3",
        "g2h3", "c6d4", "d1a4", "b7b5", "a4d4", "e7e5", "d4e5", "f8e7",
        "e5e7", "d8e7", "c3b5", "e8g8", "b5c7", "e7c7", "f1g2", "a7a5",
        "e1g1", "a5a4", "f2f4", "a4a3", "b2a3", "f6d7", "c1b2", "a8a4",
        "b2g7", "g8g7", "f4f5", "a4a3", "f5f6", "g7g6", "g2e4", "g6h5",
        "e4h7", "a3a4", "f1f5", "h5h6", "e2e4", "h6h7", "f5h5", "h7g6",
        "h5f5", "c7b6", "d2d4", "a4a3", "f5f4", "b6d4", "f4f2", "d4a1",
        "g1g2", "a1b1", "e4e5", "a3a4", "h3h4", "d7e5", "h4h5", "g6g5",
        "h2h4", "g5g4", "h5h6", "g4h4", "h6h7", "b1h7", "d5d6", "a4a3",
        "f2f4", "h4g5", "f4d4", "a3a2", "g2g1", "a2a1", "g1g2", "a1a2",
        "g2g1",
    ]
    for move_uci in history_uci:
        move = chess.Move.from_uci(move_uci)
        assert move in board.legal_moves
        board.push(move)
    repeated_check = chess.Move.from_uci("a2a1")
    assert repeated_check in board.legal_moves
    after = board.copy(stack=True)
    after.push(repeated_check)
    assert not after.can_claim_threefold_repetition()
    assert any(
        (reply_board := after.copy(stack=True)).push(reply) is None
        and reply_board.can_claim_threefold_repetition()
        for reply in after.legal_moves
    )

    chosen = _avoid_enabling_opponent_repetition_when_ahead_filter(
        board,
        repeated_check,
        side="black",
        score_move=lambda _move: 0.0,
    )

    assert chosen != repeated_check
    assert chosen in board.legal_moves


def test_exp5_advantage_filter_accepts_lower_scored_safe_progress_over_self_repetition():
    board = chess.Board()
    history_uci = [
        "e2e4", "e7e6", "d2d4", "d7d5", "f1b5", "c7c6", "c1f4", "c6b5",
        "f4b8", "a8b8", "e4d5", "e6d5", "b1c3", "d8e7", "g1e2", "e7e2",
        "d1e2", "e8d8", "e1g1", "c8f5", "a1b1", "f5c2", "e2c2", "g8h6",
        "a2a4", "b5a4", "b1c1", "f8e7", "b2b4", "e7b4", "c3a4", "f7f5",
        "c2c7", "d8e8", "c7b8", "e8f7", "b8h8", "f5f4", "g1h1", "h6f5",
        "a4b2", "f5d4", "h8e8", "f7e8", "c1c8", "e8f7", "c8c7", "f7g8",
        "c7c8", "g8f7", "c8c7", "f7g8",
    ]
    for move_uci in history_uci:
        move = chess.Move.from_uci(move_uci)
        assert move in board.legal_moves
        board.push(move)

    repeated_check = chess.Move.from_uci("c7c8")
    progress_capture = chess.Move.from_uci("c7b7")
    assert repeated_check in board.legal_moves
    assert progress_capture in board.legal_moves
    after = board.copy(stack=True)
    after.push(repeated_check)
    assert after.can_claim_threefold_repetition()

    chosen = _avoid_claimable_repetition_filter(
        board,
        repeated_check,
        score_move=lambda move: {
            repeated_check: 2384.0,
            progress_capture: 1761.0,
        }.get(move, 0.0),
    )

    assert chosen == progress_capture


def test_exp5_advantage_filter_accepts_lower_scored_safe_progress_over_perpetual_check():
    board = chess.Board()
    history_uci = [
        "d2d4", "g8f6", "c2c4", "g7g6", "c1f4", "b8c6", "b1c3", "c6d4",
        "d1d4", "e7e5", "e1c1", "e5d4", "d1d4", "f8c5", "d4d1", "c5f2",
        "g1f3", "e8g8", "e2e4", "f6e4", "c3e4", "f2b6", "a2a3", "f7f5",
        "e4g3", "d7d5", "a3a4", "c8e6", "a4a5", "b6a5", "b2b3", "d5d4",
        "b3b4", "a5b4", "c1b1", "e6c4", "f1c4", "g8h8", "b1a2", "c7c5",
        "a2b1", "h7h6", "b1a1", "d8a5", "a1b1", "h6h5", "b1c1", "a5a3",
        "c1b1", "a3f3", "g2f3", "h5h4", "f4e5", "h8h7", "g3e2", "f5f4",
        "b1a1", "f8f5", "e5c7", "h4h3", "a1a2", "g6g5", "a2a1", "g5g4",
        "a1a2", "g4f3", "e2c1", "f3f2", "a2a1", "f2f1q", "c4f1", "b4c3",
        "a1a2", "c5c4", "a2b1", "f5b5", "b1a2", "b5b2", "a2a3", "f4f3",
        "f1h3", "f3f2", "a3a4", "f2f1q", "h3f1", "b7b5", "a4a3", "b5b4",
        "a3a4", "d4d3", "a4b5", "a7a6", "b5a5", "b4b3", "a5a4", "c3d4",
        "f1d3", "c4d3", "a4a3", "d3d2", "c1e2", "b2a2", "a3b3", "a2b2",
        "b3a3", "d4h8", "a3a4", "b2a2", "a4b3", "a2b2", "b3a3", "h8g7",
        "a3a4", "b2a2", "a4b3", "a2b2", "b3a3", "a6a5", "a3a4", "b2b4",
        "a4a3", "g7b2", "a3a2", "a5a4", "d1d2", "b2h8", "d2d7", "h7h6",
        "d7d6", "h6h7", "d6d7", "h7h6",
    ]
    for move_uci in history_uci:
        move = chess.Move.from_uci(move_uci)
        assert move in board.legal_moves
        board.push(move)

    repeated_check = chess.Move.from_uci("d7d6")
    progress_move = chess.Move.from_uci("d7e7")
    assert repeated_check in board.legal_moves
    assert progress_move in board.legal_moves
    after = board.copy(stack=True)
    after.push(repeated_check)
    assert any(
        (reply_board := after.copy(stack=True)).push(reply) is None
        and reply_board.can_claim_threefold_repetition()
        for reply in after.legal_moves
    )

    chosen = _avoid_enabling_opponent_repetition_when_ahead_filter(
        board,
        repeated_check,
        side="white",
        score_move=lambda move: {
            repeated_check: 1979.0,
            progress_move: 652.0,
        }.get(move, 0.0),
    )

    assert chosen == progress_move


def test_exp5_filter_blocks_unanswered_immediate_promotion():
    board = chess.Board("2N5/2N2R2/R7/6kp/2P5/6p1/3p2P1/7K w - - 0 47")
    quiet_blunder = chess.Move.from_uci("a6a2")
    assert quiet_blunder in board.legal_moves
    after = board.copy(stack=True)
    after.push(quiet_blunder)
    assert any(reply.promotion for reply in after.legal_moves)

    chosen = _avoid_unanswered_immediate_promotion_filter(
        board,
        quiet_blunder,
        side="white",
        score_move=lambda _move: 0.0,
    )

    assert chosen != quiet_blunder
    assert chosen in board.legal_moves
    safe_after = board.copy(stack=True)
    safe_after.push(chosen)
    assert not any(reply.promotion for reply in safe_after.legal_moves)


def test_exp5_opening_king_walk_filter_prefers_non_king_check_evasion():
    board = chess.Board("1rb1kbnr/pp2qppp/8/1p1p4/3P4/2N5/PPP2PPP/R2QK1NR w KQk - 2 8")
    bad_king_walk = chess.Move.from_uci("e1d2")
    assert bad_king_walk in board.legal_moves

    chosen = _opening_king_walk_filter(
        board,
        bad_king_walk,
        score_move=lambda move: 10_000.0 if move == bad_king_walk else 0.0,
    )

    assert chosen != bad_king_walk
    assert chosen in board.legal_moves
    assert board.piece_at(chosen.from_square).piece_type != chess.KING


def test_exp5_opening_king_walk_filter_does_not_overblock_moved_king():
    board = chess.Board("rnbq2nr/pppp1kpp/3b4/4p2Q/4P3/8/PPPP1PPP/RNB1K1NR b KQ - 1 4")
    active_king_move = chess.Move.from_uci("f7e6")
    assert active_king_move in board.legal_moves

    chosen = _opening_king_walk_filter(
        board,
        active_king_move,
        score_move=lambda _move: 0.0,
    )

    assert chosen == active_king_move


def test_exp5_opening_moved_king_filter_prefers_safe_home_retreat():
    board = chess.Board("r1b1k1nr/pppp1ppp/5q2/4p2Q/3nP3/2NB4/PPPPK1PP/R1B3NR w kq - 3 7")
    drift = chess.Move.from_uci("e2d1")
    home = chess.Move.from_uci("e2e1")
    assert drift in board.legal_moves
    assert home in board.legal_moves

    chosen = _opening_moved_king_home_filter(
        board,
        drift,
        score_move=lambda move: {drift: 1562.0, home: 1218.0}.get(move, 0.0),
    )

    assert chosen == home


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
    assert payload["artifact_role"] == "adapter_or_experience_table"
    assert payload["delta_format"] == EXP5_EXPERIENCE_DELTA_FORMAT
    assert payload["base_model_sha256"] == EXP5_STATIC_BASE_MODEL_SHA256
    assert not payload["opening_overlay"]
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


def test_exp5_opening_guard_prefers_development_over_low_value_pawn_capture(tmp_path):
    model_path = tmp_path / "exp5.json"
    fen = "rnbqkbnr/pp3ppp/2p1p3/1B1p4/3PP3/8/PPP2PPP/RNBQK1NR w KQkq - 0 4"

    chosen = choose_experiment_nnue_move(
        {"__fen__": fen},
        "white",
        model_path=model_path,
        search_profile="fixed_depth_balanced",
    )

    chosen_uci = f"{chosen['from']}{chosen['to']}{chosen.get('promotion') or ''}"
    board = chess.Board(fen)
    move = chess.Move.from_uci(chosen_uci)
    piece = board.piece_at(move.from_square)
    assert piece is not None
    assert piece.piece_type in {chess.KNIGHT, chess.BISHOP}
    assert chess.square_rank(move.from_square) == 0


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


def test_exp5_history_aware_filter_does_not_force_draw_when_slightly_ahead(tmp_path):
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
    assert not board.can_claim_threefold_repetition()


def test_exp5_conversion_check_evasion_activates_king_in_won_rook_endgame(tmp_path):
    model_path = tmp_path / "exp5.json"
    fen = "6k1/8/8/1p1PN3/1r6/8/1K1R1P1R/5B2 w - - 2 43"

    chosen = choose_experiment_nnue_move(
        {"__fen__": fen},
        "white",
        model_path=model_path,
        search_profile="balanced",
    )

    chosen_uci = f"{chosen['from']}{chosen['to']}{chosen.get('promotion') or ''}"
    assert chosen_uci == "b2c3"


def test_exp5_conversion_check_evasion_avoids_back_rank_cycle(tmp_path):
    model_path = tmp_path / "exp5.json"
    fen = "6k1/8/8/1p1PN3/r7/8/K2R1P1R/5B2 w - - 4 44"

    chosen = choose_experiment_nnue_move(
        {"__fen__": fen},
        "white",
        model_path=model_path,
        search_profile="balanced",
    )

    chosen_uci = f"{chosen['from']}{chosen['to']}{chosen.get('promotion') or ''}"
    assert chosen_uci == "a2b3"


def test_exp5_v15_pushes_passed_pawn_race_in_low_material(tmp_path):
    model_path = tmp_path / "exp5.json"
    fen = "8/3k4/4P3/8/8/8/3K4/8 w - - 0 1"

    chosen = choose_experiment_nnue_move(
        {"__fen__": fen},
        "white",
        model_path=model_path,
        search_profile="fixed_depth_fast",
    )

    assert f"{chosen['from']}{chosen['to']}{chosen.get('promotion') or ''}" == "e6e7"


def test_exp5_v15_bare_king_conversion_uses_rook_cutoff(tmp_path):
    model_path = tmp_path / "exp5.json"
    fen = "8/8/8/8/5k2/8/6K1/1R6 w - - 58 111"

    chosen = choose_experiment_nnue_move(
        {"__fen__": fen},
        "white",
        model_path=model_path,
        search_profile="fixed_depth_fast",
    )

    chosen_uci = f"{chosen['from']}{chosen['to']}{chosen.get('promotion') or ''}"
    assert chosen_uci == "b1b4"
    board = chess.Board(fen)
    board.push(chess.Move.from_uci(chosen_uci))
    assert not board.is_stalemate()


def test_exp5_v15_non_progress_shuffle_filter_replaces_recent_rook_cycle():
    board = chess.Board("8/8/2N5/5k2/8/6K1/8/R7 w - - 46 105")
    board.push(chess.Move.from_uci("a1a3"))
    board.push(chess.Move.from_uci("f5e5"))
    repeated_rook_shuffle = chess.Move.from_uci("a3a1")
    assert repeated_rook_shuffle in board.legal_moves

    chosen = _avoid_non_progress_shuffle_when_ahead_filter(
        board,
        repeated_rook_shuffle,
        side="white",
        score_move=lambda _move: 0.0,
    )

    assert chosen != repeated_rook_shuffle
    assert chosen in board.legal_moves


def test_exp5_v15_shuffle_filter_prefers_advanced_pawn_push_when_behind():
    board = chess.Board("1r1qkb1r/pp1bp1pp/7n/3P1p2/8/1pNQ4/5P1P/1R4K1 w k - 0 17")
    board.push(chess.Move.from_uci("b1b2"))
    board.push(chess.Move.from_uci("f5f4"))
    rook_shuffle = chess.Move.from_uci("b2b1")
    pawn_push = chess.Move.from_uci("d5d6")
    assert rook_shuffle in board.legal_moves
    assert pawn_push in board.legal_moves

    chosen = _avoid_shuffle_with_advanced_pawn_push_filter(
        board,
        rook_shuffle,
        side="white",
        score_move=lambda move: -1.0 if move == pawn_push else 0.0,
    )

    assert chosen == pawn_push


def test_exp5_v15_endgame_progress_filter_prefers_rook_progress_over_back_rank():
    board = chess.Board("8/8/2N5/5k2/8/R5K1/8/8 w - - 48 106")
    passive_rook = chess.Move.from_uci("a3a1")
    progress_rook = chess.Move.from_uci("a3a5")
    assert passive_rook in board.legal_moves
    assert progress_rook in board.legal_moves

    chosen = _endgame_progress_filter(
        board,
        passive_rook,
        side="white",
        score_move=lambda move: 500.0 if move == passive_rook else 0.0,
    )

    assert chosen != passive_rook
    assert chosen in board.legal_moves
    after = board.copy(stack=True)
    after.push(chosen)
    assert not after.is_stalemate()


def test_exp5_v17_opening_trap_prior_uses_code_level_experience():
    cases = [
        ("rnbqkbnr/pppp1ppp/8/4p3/2B1P3/8/PPPP1PPP/RNBQK1NR b KQkq - 1 2", "black", "f8d6"),
        ("rnbqk1nr/ppp2ppp/4p3/3P4/1b1P4/2P5/PP3PPP/RNBQKBNR b KQkq - 0 4", "black", "e6d5"),
        ("r1bq1k1r/pppp2p1/2n3Bp/2b5/2Pp1p2/5N2/PP3PPP/R1BQ1RK1 w - - 0 11", "white", "a1b1"),
    ]
    for fen, side, expected in cases:
        board = chess.Board(fen)

        chosen = _opening_trap_priority_move(board, side)

        assert chosen == chess.Move.from_uci(expected)


def test_exp5_v17_forced_single_reply_mate_net_finds_caro_kann_finish():
    board = chess.Board("7r/pp3kp1/5n1p/2b1P3/3r2bK/8/PPP2PPP/RN4NR b - - 1 15")

    chosen = _forced_single_reply_mate_net_move(board)

    assert chosen == chess.Move.from_uci("g7g5")
    board.push(chosen)
    assert list(board.legal_moves) == [chess.Move.from_uci("h4g3")]
