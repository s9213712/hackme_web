import sqlite3

import pytest
from flask import Flask, jsonify

from routes.games import register_games_routes

from services.games.board_ai import (
    BOARD_AI_SIZES,
    choose_board_game_ai_move,
    go_apply_move,
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

    chess_response = client.post("/api/games/chess/ai-move", json={
        "board": board,
        "turn": "black",
    })
    assert chess_response.status_code == 404
