import sqlite3
from types import SimpleNamespace

import pytest
from flask import Flask, jsonify

from routes.games import register_games_routes

import services.games.board_ai as board_ai
from services.games.board_ai import (
    BOARD_AI_SIZES,
    choose_board_game_ai_move,
    go_apply_move,
    go_life_death_network,
    gomoku_has_five,
    reversi_apply_move,
)


def _build_app(db_path):
    app = Flask(__name__)
    app.testing = True

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def passthrough(fn):
        return fn

    register_games_routes(app, {
        "get_current_user_ctx": lambda: {"id": 2, "username": "alice", "role": "user"},
        "get_db": get_db,
        "json_resp": lambda payload: jsonify(payload),
        "require_csrf": passthrough,
        "require_csrf_safe": passthrough,
        "audit": lambda *args, **kwargs: None,
    })
    return app


def _empty(game_key):
    return [""] * (BOARD_AI_SIZES[game_key] ** 2)


def test_go_uses_standard_19_line_board():
    assert BOARD_AI_SIZES["go"] == 19


def test_reversi_ai_selects_legal_flipping_move():
    size = BOARD_AI_SIZES["reversi"]
    board = _empty("reversi")
    board[3 * size + 3] = "white"
    board[4 * size + 4] = "white"
    board[3 * size + 4] = "black"
    board[4 * size + 3] = "black"

    decision = choose_board_game_ai_move("reversi", board, "white", "normal")

    assert decision["action"] == "move"
    next_board = reversi_apply_move(tuple(board), decision["move"]["index"], "white")
    assert next_board is not None
    assert next_board.count("white") > tuple(board).count("white")


def test_gomoku_ai_finishes_immediate_five():
    size = BOARD_AI_SIZES["gomoku"]
    board = _empty("gomoku")
    for x in range(4):
        board[7 * size + x + 5] = "black"

    decision = choose_board_game_ai_move("gomoku", board, "black", "hard")

    assert decision["action"] == "move"
    next_board = list(board)
    next_board[decision["move"]["index"]] = "black"
    assert gomoku_has_five(tuple(next_board), decision["move"]["index"], "black")


def test_gomoku_ai_blocks_opponent_open_four():
    size = BOARD_AI_SIZES["gomoku"]
    board = _empty("gomoku")
    for x in range(4):
        board[7 * size + x + 5] = "white"

    decision = choose_board_game_ai_move("gomoku", board, "black", "normal")

    assert decision["action"] == "move"
    assert decision["move"]["index"] in {7 * size + 4, 7 * size + 9}


def test_gomoku_hard_creates_open_four_threat_space():
    size = BOARD_AI_SIZES["gomoku"]
    board = _empty("gomoku")
    for x in (5, 6, 8):
        board[7 * size + x] = "black"

    decision = choose_board_game_ai_move("gomoku", board, "black", "hard")

    assert decision["action"] == "move"
    assert decision["reason"] == "threat-space"
    assert decision["move"]["index"] == 7 * size + 7


def test_gomoku_hard_blocks_opponent_open_four_builder():
    size = BOARD_AI_SIZES["gomoku"]
    board = _empty("gomoku")
    for x in (5, 6, 8):
        board[7 * size + x] = "white"
    board[3 * size + 3] = "black"

    decision = choose_board_game_ai_move("gomoku", board, "black", "hard")

    assert decision["action"] == "move"
    assert decision["reason"] == "threat-block"
    assert decision["move"]["index"] == 7 * size + 7


def test_reversi_hard_prioritizes_available_corner():
    size = BOARD_AI_SIZES["reversi"]
    board = _empty("reversi")
    board[1] = "white"
    board[2] = "black"
    board[3 * size + 3] = "white"
    board[4 * size + 4] = "white"
    board[3 * size + 4] = "black"
    board[4 * size + 3] = "black"

    decision = choose_board_game_ai_move("reversi", board, "black", "hard")

    assert decision["action"] == "move"
    assert decision["move"]["index"] == 0


def test_reversi_hard_uses_exact_endgame_solver():
    size = BOARD_AI_SIZES["reversi"]
    board = ["black"] * (size * size)
    board[0] = ""
    board[1] = "white"
    board[2] = "black"

    decision = choose_board_game_ai_move("reversi", board, "black", "hard")

    assert decision["action"] == "move"
    assert decision["reason"] == "exact-endgame-alpha-beta"
    assert decision["move"]["index"] == 0


def test_go_ai_prioritizes_capture():
    size = BOARD_AI_SIZES["go"]
    board = _empty("go")
    board[4 * size + 4] = "white"
    board[4 * size + 3] = "black"
    board[4 * size + 5] = "black"
    board[3 * size + 4] = "black"

    decision = choose_board_game_ai_move("go", board, "black", "normal")

    assert decision["action"] == "move"
    assert decision["move"]["index"] == 5 * size + 4
    next_board, captured = go_apply_move(tuple(board), decision["move"]["index"], "black")
    assert captured == 1
    assert next_board[4 * size + 4] == ""


def test_go_life_death_network_rates_two_eye_shape_as_alive():
    size = BOARD_AI_SIZES["go"]
    alive = _empty("go")
    weak = _empty("go")
    for x, y in (
        (3, 3), (4, 3), (5, 3), (6, 3), (7, 3),
        (3, 4), (5, 4), (7, 4),
        (3, 5), (4, 5), (5, 5), (6, 5), (7, 5),
    ):
        alive[y * size + x] = "black"
    weak[10 * size + 10] = "black"
    for x, y in ((9, 10), (11, 10), (10, 9)):
        weak[y * size + x] = "white"

    assert go_life_death_network(alive, "black") > go_life_death_network(weak, "black") + 600


def test_go_hard_life_death_network_saves_group_in_atari():
    size = BOARD_AI_SIZES["go"]
    board = _empty("go")
    board[4 * size + 4] = "black"
    board[5 * size + 4] = "black"
    for x, y in ((3, 4), (5, 4), (4, 3), (3, 5), (5, 5)):
        board[y * size + x] = "white"

    decision = choose_board_game_ai_move("go", board, "black", "hard")

    assert decision["action"] == "move"
    assert decision["reason"] == "life-death-network"
    assert decision["move"]["index"] == 6 * size + 4


def test_go_hard_life_death_network_attacks_two_liberty_group():
    size = BOARD_AI_SIZES["go"]
    board = _empty("go")
    board[10 * size + 10] = "white"
    board[9 * size + 10] = "black"
    board[10 * size + 9] = "black"

    decision = choose_board_game_ai_move("go", board, "black", "hard")

    assert decision["action"] == "move"
    assert decision["reason"] == "life-death-network"
    assert decision["move"]["index"] in {10 * size + 11, 11 * size + 10}


def test_go_katago_difficulty_uses_analysis_engine(monkeypatch):
    size = BOARD_AI_SIZES["go"]
    board = _empty("go")
    board[3 * size + 3] = "black"
    monkeypatch.setenv("HACKME_KATAGO_COMMAND", "katago analysis -config cfg -model model")

    def fake_run(command, *, input, text, capture_output, timeout, check):
        query = board_ai.json.loads(input)
        assert command == ["katago", "analysis", "-config", "cfg", "-model", "model"]
        assert text is True
        assert capture_output is True
        assert check is False
        assert query["rules"] == "chinese"
        assert query["boardXSize"] == 19
        assert query["komi"] == 6.5
        assert query["analyzeTurns"] == ["W"]
        assert ["B", "D16"] in query["initialStones"]
        return SimpleNamespace(
            returncode=0,
            stdout=board_ai.json.dumps({"id": query["id"], "moveInfos": [{"move": "K10", "winrate": 0.72, "scoreLead": 3.5}]}) + "\n",
            stderr="",
        )

    monkeypatch.setattr(board_ai.subprocess, "run", fake_run)

    decision = choose_board_game_ai_move("go", board, "white", "katago")

    assert decision["action"] == "move"
    assert decision["reason"] == "katago-neural-network"
    assert decision["difficulty"] == "katago"
    assert decision["move"] == {"index": 9 * size + 9, "x": 9, "y": 9}


def test_katago_command_auto_detects_runtime_install(monkeypatch, tmp_path):
    home = tmp_path / "katago"
    home.mkdir()
    binary = home / "katago"
    config = home / "analysis.cfg"
    model = home / "kata1-test.bin.gz"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    config.write_text("numSearchThreads = 2\n", encoding="utf-8")
    model.write_bytes(b"model")

    for key in (
        "HACKME_KATAGO_COMMAND",
        "KATAGO_COMMAND",
        "HACKME_KATAGO_BIN",
        "KATAGO_BIN",
        "HACKME_KATAGO_CONFIG",
        "KATAGO_CONFIG",
        "HACKME_KATAGO_MODEL",
        "KATAGO_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HACKME_KATAGO_HOME", str(home))

    assert board_ai._katago_command() == [
        str(binary),
        "analysis",
        "-config",
        str(config),
        "-model",
        str(model),
    ]


def test_katago_unavailable_points_to_setup_script(monkeypatch, tmp_path):
    for key in (
        "HACKME_KATAGO_COMMAND",
        "KATAGO_COMMAND",
        "HACKME_KATAGO_BIN",
        "KATAGO_BIN",
        "HACKME_KATAGO_CONFIG",
        "KATAGO_CONFIG",
        "HACKME_KATAGO_MODEL",
        "KATAGO_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HACKME_KATAGO_HOME", str(tmp_path / "missing"))
    monkeypatch.setattr(board_ai.shutil, "which", lambda _name: None)

    with pytest.raises(board_ai.KataGoUnavailable) as exc_info:
        board_ai._katago_command()

    assert "scripts/games/setup_katago.py" in str(exc_info.value)


def test_katago_difficulty_is_go_only():
    with pytest.raises(ValueError):
        choose_board_game_ai_move("gomoku", _empty("gomoku"), "black", "katago")


def test_board_ai_does_not_accept_chess_key():
    with pytest.raises(ValueError):
        choose_board_game_ai_move("chess", _empty("reversi"), "black")


def test_board_ai_route_is_scoped_to_non_chess_games(tmp_path):
    app = _build_app(tmp_path / "games.db")
    client = app.test_client()
    board = _empty("gomoku")

    response = client.post("/api/games/gomoku/ai-move", json={
        "board": board,
        "turn": "black",
        "difficulty": "normal",
    })
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["game_key"] == "gomoku"
    assert payload["action"] == "move"

    invalid_difficulty = client.post("/api/games/gomoku/ai-move", json={
        "board": board,
        "turn": "black",
        "difficulty": "katago",
    })
    assert invalid_difficulty.status_code == 400

    chess_response = client.post("/api/games/chess/ai-move", json={
        "board": board,
        "turn": "black",
    })
    assert chess_response.status_code == 404
