import sqlite3

from flask import Flask, jsonify

from routes.games import ensure_game_schema, register_games_routes
from services.chess_game import game_status, initial_board, legal_moves, validate_move


def _build_app(db_path, actor_box, points_service=None):
    app = Flask(__name__)
    app.testing = True

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def passthrough(fn):
        return fn

    register_games_routes(app, {
        "get_current_user_ctx": lambda: actor_box["actor"],
        "get_db": get_db,
        "json_resp": lambda payload: jsonify(payload),
        "require_csrf": passthrough,
        "require_csrf_safe": passthrough,
        "points_service": points_service,
        "audit": lambda *args, **kwargs: None,
    })
    return app


def _seed_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL DEFAULT 'user',
            status TEXT NOT NULL DEFAULT 'active',
            deleted_at TEXT
        );
        INSERT INTO users (id, username, role, status) VALUES
          (1, 'root', 'super_admin', 'active'),
          (2, 'alice', 'user', 'active'),
          (3, 'bob', 'user', 'active');
        """
    )
    ensure_game_schema(conn)
    conn.commit()
    conn.close()


def test_chess_legal_move_validation_blocks_illegal_moves():
    board = initial_board()
    assert any(move["from"] == "e2" and move["to"] == "e4" for move in legal_moves(board, "white"))
    move = validate_move(board, "white", "e2", "e4")
    assert move["board"]["e4"] == "P"
    try:
        validate_move(board, "white", "e2", "e5")
    except ValueError as exc:
        assert "不合法" in str(exc)
    else:
        raise AssertionError("illegal chess move was accepted")


def test_chess_rules_forbid_capturing_king_and_force_check_escape():
    board = {
        "e1": "K",
        "e2": "Q",
        "e8": "k",
    }
    assert not any(move["from"] == "e2" and move["to"] == "e8" for move in legal_moves(board, "white"))
    try:
        validate_move(board, "white", "e2", "e8")
    except ValueError as exc:
        assert "王不能被吃" in str(exc)
    else:
        raise AssertionError("king capture was accepted")

    checked_board = {
        "e1": "K",
        "e8": "r",
        "a8": "k",
        "a2": "R",
    }
    assert game_status(checked_board, "white")["reason"] == "check"
    assert not any(move["from"] == "a2" and move["to"] == "a3" for move in legal_moves(checked_board, "white"))
    try:
        validate_move(checked_board, "white", "a2", "a3")
    except ValueError as exc:
        assert "不合法" in str(exc)
    else:
        raise AssertionError("move that ignores check was accepted")


def test_chess_checkmate_and_missing_king_finish_game():
    board = initial_board()
    for color, from_square, to_square in (
        ("white", "f2", "f3"),
        ("black", "e7", "e5"),
        ("white", "g2", "g4"),
        ("black", "d8", "h4"),
    ):
        board = validate_move(board, color, from_square, to_square)["board"]
    assert game_status(board, "white") == {"status": "finished", "winner_color": "black", "reason": "checkmate"}

    missing_white_king = {"a8": "k", "a1": "R"}
    assert game_status(missing_white_king, "white") == {"status": "finished", "winner_color": "black", "reason": "king_missing"}


def test_chess_practice_match_accepts_player_move_and_computer_reply(tmp_path):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    app = _build_app(db_path, actor_box)
    client = app.test_client()

    created = client.post("/api/games/chess/practice", json={})
    assert created.status_code == 200
    match_id = created.get_json()["match_id"]

    moved = client.post(f"/api/games/chess/matches/{match_id}/move", json={"from": "e2", "to": "e4"})
    assert moved.status_code == 200
    data = moved.get_json()
    assert data["ok"] is True
    assert data["match"]["board"]["e4"] == "P"
    assert data["match"]["current_turn"] == "white"
    assert len(data["match"]["move_history"]) == 2
    assert data["match"]["move_history"][1]["computer"] is True


def test_chess_invite_accept_creates_pvp_match_and_leaderboard(tmp_path):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    app = _build_app(db_path, actor_box)
    client = app.test_client()

    invite = client.post("/api/games/chess/invites", json={"opponent_username": "bob"})
    assert invite.status_code == 200
    invite_id = invite.get_json()["invite_id"]

    actor_box["actor"] = {"id": 3, "username": "bob", "role": "user"}
    accepted = client.post(f"/api/games/chess/invites/{invite_id}/accept", json={})
    assert accepted.status_code == 200
    match_id = accepted.get_json()["match_id"]

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        UPDATE game_matches
        SET status='finished', winner_user_id=2, leaderboard_week='2026-W18', finished_at='2026-04-29T00:00:00+00:00'
        WHERE id=?
        """,
        (match_id,),
    )
    conn.commit()
    conn.close()

    actor_box["actor"] = {"id": 2, "username": "alice", "role": "user"}
    leaderboard = client.get("/api/games/chess/leaderboard?week=2026-W18")
    assert leaderboard.status_code == 200
    rows = leaderboard.get_json()["leaderboard"]
    assert rows[0]["username"] == "alice"
    assert rows[0]["score"] == 3
    assert rows[1]["username"] == "bob"
    assert rows[1]["score"] == 0
