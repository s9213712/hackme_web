import sqlite3
from unittest.mock import patch

from flask import Flask, jsonify

from routes.games import choose_computer_move, ensure_game_schema, register_games_routes
from services.games.chess import game_status, initial_board, legal_moves, validate_move


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


def _seed_legacy_user_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL DEFAULT 'user',
            status TEXT NOT NULL DEFAULT 'active'
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


def test_game_catalog_includes_solo_games(tmp_path):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    app = _build_app(db_path, actor_box)
    client = app.test_client()

    response = client.get("/api/games/catalog")
    assert response.status_code == 200
    games = response.get_json()["games"]
    by_key = {game["key"]: game for game in games}
    assert {"chess", "sudoku", "minesweeper", "1a2b", "tetris", "space_shooter"} <= set(by_key)
    assert by_key["sudoku"]["supports_invites"] is False
    assert by_key["minesweeper"]["supports_computer"] is False
    assert by_key["1a2b"]["supports_invites"] is False
    assert by_key["tetris"]["supports_invites"] is False
    assert by_key["space_shooter"]["supports_computer"] is False


def test_games_users_and_invites_work_with_legacy_users_table_without_deleted_at(tmp_path):
    db_path = tmp_path / "games.db"
    _seed_legacy_user_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    app = _build_app(db_path, actor_box)
    client = app.test_client()

    users = client.get("/api/games/users")
    assert users.status_code == 200
    payload = users.get_json()
    assert payload["ok"] is True
    assert [row["username"] for row in payload["users"]] == ["bob", "root"]

    invite = client.post("/api/games/chess/invites", json={"opponent_username": "bob"})
    assert invite.status_code == 200
    assert invite.get_json()["ok"] is True


def test_game_schema_migrates_existing_solo_scores_without_guess_count(tmp_path):
    db_path = tmp_path / "games.db"
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
          (2, 'alice', 'user', 'active');
        CREATE TABLE game_solo_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_key TEXT NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            week_key TEXT NOT NULL,
            difficulty TEXT NOT NULL DEFAULT 'standard',
            puzzle_id TEXT,
            raw_elapsed_ms INTEGER NOT NULL,
            penalty_seconds INTEGER NOT NULL DEFAULT 0,
            elapsed_ms INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            CHECK (game_key IN ('sudoku', 'minesweeper')),
            CHECK (elapsed_ms > 0),
            CHECK (raw_elapsed_ms > 0),
            CHECK (penalty_seconds >= 0)
        );
        INSERT INTO game_solo_scores (
            game_key, user_id, week_key, difficulty, puzzle_id,
            raw_elapsed_ms, penalty_seconds, elapsed_ms, created_at
        ) VALUES ('sudoku', 2, '2026-W18', 'standard', 'legacy', 50000, 0, 50000, '2026-05-01T00:00:00+00:00');
        """
    )
    conn.commit()
    conn.close()

    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    app = _build_app(db_path, actor_box)
    client = app.test_client()

    response = client.get("/api/games/users")
    assert response.status_code == 200
    assert response.get_json()["ok"] is True

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(game_solo_scores)").fetchall()}
        assert "guess_count" in cols
        assert "score" in cols
        migrated = conn.execute("SELECT game_key, guess_count, score FROM game_solo_scores WHERE puzzle_id='legacy'").fetchone()
        assert migrated["game_key"] == "sudoku"
        assert migrated["guess_count"] == 0
        assert migrated["score"] == 0
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_game_solo_scores_guesses_rank'").fetchone()
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_game_solo_scores_score_rank'").fetchone()
    finally:
        conn.close()


def test_solo_games_use_elapsed_time_leaderboard(tmp_path):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    app = _build_app(db_path, actor_box)
    client = app.test_client()

    first = client.post(
        "/api/games/sudoku/solo-scores",
        json={"raw_elapsed_ms": 50000, "penalty_seconds": 10, "elapsed_ms": 60000, "puzzle_id": "p1"},
    )
    assert first.status_code == 200
    second = client.post(
        "/api/games/sudoku/solo-scores",
        json={"raw_elapsed_ms": 45000, "penalty_seconds": 0, "elapsed_ms": 45000, "puzzle_id": "p1"},
    )
    assert second.status_code == 200

    board = client.get("/api/games/sudoku/solo-leaderboard")
    assert board.status_code == 200
    payload = board.get_json()
    assert payload["rank_mode"] == "time_asc"
    assert payload["leaderboard"][0]["username"] == "alice"
    assert payload["leaderboard"][0]["elapsed_ms"] == 45000
    assert payload["leaderboard"][0]["attempts"] == 2

    bad = client.post(
        "/api/games/minesweeper/solo-scores",
        json={"raw_elapsed_ms": 10000, "penalty_seconds": 10, "elapsed_ms": 10000, "difficulty": "easy"},
    )
    assert bad.status_code == 400

    onea2b = client.post(
        "/api/games/1a2b/solo-scores",
        json={"raw_elapsed_ms": 30000, "penalty_seconds": 0, "elapsed_ms": 30000, "puzzle_id": "1a2b-4digits", "guess_count": 3},
    )
    assert onea2b.status_code == 200
    better_guesses = client.post(
        "/api/games/1a2b/solo-scores",
        json={"raw_elapsed_ms": 60000, "penalty_seconds": 0, "elapsed_ms": 60000, "puzzle_id": "1a2b-4digits", "guess_count": 2},
    )
    assert better_guesses.status_code == 200
    too_slow = client.post(
        "/api/games/1a2b/solo-scores",
        json={"raw_elapsed_ms": 301000, "penalty_seconds": 0, "elapsed_ms": 301000, "puzzle_id": "1a2b-4digits", "guess_count": 1},
    )
    assert too_slow.status_code == 200
    assert too_slow.get_json()["ranked"] is False
    actor_box["actor"] = {"id": 3, "username": "bob", "role": "user"}
    fewest_guesses = client.post(
        "/api/games/1a2b/solo-scores",
        json={"raw_elapsed_ms": 100000, "penalty_seconds": 0, "elapsed_ms": 100000, "puzzle_id": "1a2b-4digits", "guess_count": 1},
    )
    assert fewest_guesses.status_code == 200
    onea2b_board = client.get("/api/games/1a2b/solo-leaderboard")
    assert onea2b_board.status_code == 200
    onea2b_payload = onea2b_board.get_json()
    assert onea2b_payload["rank_mode"] == "guesses_then_time"
    assert [row["username"] for row in onea2b_payload["leaderboard"][:2]] == ["bob", "alice"]
    assert onea2b_payload["leaderboard"][0]["guess_count"] == 1
    assert onea2b_payload["leaderboard"][1]["guess_count"] == 2
    assert onea2b_payload["leaderboard"][1]["elapsed_ms"] == 60000


def test_score_ranked_solo_games_use_high_score_leaderboard(tmp_path):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    app = _build_app(db_path, actor_box)
    client = app.test_client()

    low = client.post(
        "/api/games/tetris/solo-scores",
        json={"score": 1200, "raw_elapsed_ms": 90000, "penalty_seconds": 0, "elapsed_ms": 90000, "puzzle_id": "tetris-standard"},
    )
    assert low.status_code == 200
    high = client.post(
        "/api/games/tetris/solo-scores",
        json={"score": 2200, "raw_elapsed_ms": 110000, "penalty_seconds": 0, "elapsed_ms": 110000, "puzzle_id": "tetris-standard"},
    )
    assert high.status_code == 200
    actor_box["actor"] = {"id": 3, "username": "bob", "role": "user"}
    bob = client.post(
        "/api/games/tetris/solo-scores",
        json={"score": 1800, "raw_elapsed_ms": 70000, "penalty_seconds": 0, "elapsed_ms": 70000, "puzzle_id": "tetris-standard"},
    )
    assert bob.status_code == 200

    board = client.get("/api/games/tetris/solo-leaderboard")
    assert board.status_code == 200
    payload = board.get_json()
    assert payload["rank_mode"] == "score_desc"
    assert [row["username"] for row in payload["leaderboard"][:2]] == ["alice", "bob"]
    assert payload["leaderboard"][0]["score"] == 2200
    assert payload["leaderboard"][0]["attempts"] == 2

    bad = client.post(
        "/api/games/space_shooter/solo-scores",
        json={"score": 0, "raw_elapsed_ms": 1000, "penalty_seconds": 0, "elapsed_ms": 1000, "puzzle_id": "space-shooter-standard"},
    )
    assert bad.status_code == 400


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


def test_chess_engine_supports_castling_en_passant_and_promotion():
    board = initial_board()
    for color, from_square, to_square in (
        ("white", "e2", "e4"),
        ("black", "e7", "e5"),
        ("white", "g1", "f3"),
        ("black", "b8", "c6"),
        ("white", "f1", "c4"),
        ("black", "g8", "f6"),
    ):
        board = validate_move(board, color, from_square, to_square)["board"]
    castle = validate_move(board, "white", "e1", "g1")
    assert castle["castle"] is True
    assert castle["board"]["g1"] == "K"
    assert castle["board"]["f1"] == "R"

    board = initial_board()
    for color, from_square, to_square in (
        ("white", "e2", "e4"),
        ("black", "h7", "h5"),
        ("white", "e4", "e5"),
        ("black", "d7", "d5"),
    ):
        board = validate_move(board, color, from_square, to_square)["board"]
    en_passant = validate_move(board, "white", "e5", "d6")
    assert en_passant["en_passant"] is True
    assert en_passant["captured"] == "p"
    assert "d5" not in en_passant["board"]
    assert en_passant["board"]["d6"] == "P"

    promotion_board = {"e1": "K", "a8": "k", "e7": "P"}
    promoted = validate_move(promotion_board, "white", "e7", "e8")
    assert promoted["promotion"] == "q"
    assert promoted["board"]["e8"] == "Q"


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


def test_chess_practice_can_choose_black_and_computer_moves_first(tmp_path):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    app = _build_app(db_path, actor_box)
    client = app.test_client()

    with patch("routes.games.random.choice", side_effect=lambda seq: seq[0]):
        created = client.post("/api/games/chess/practice", json={"side": "black"})
    assert created.status_code == 200
    match_id = created.get_json()["match_id"]

    detail = client.get(f"/api/games/chess/matches/{match_id}")
    assert detail.status_code == 200
    match = detail.get_json()["match"]
    assert match["my_side"] == "black"
    assert match["human_side"] == "black"
    assert match["white_username"] == "電腦"
    assert match["black_username"] == "alice"
    assert match["current_turn"] == "black"
    assert len(match["move_history"]) == 1
    assert match["move_history"][0]["computer"] is True
    assert match["move_history"][0]["by"] == "white"


def test_chess_practice_difficulty_is_persisted_and_rejects_invalid_value(tmp_path):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    app = _build_app(db_path, actor_box)
    client = app.test_client()

    rejected = client.post("/api/games/chess/practice", json={"difficulty": "impossible"})
    assert rejected.status_code == 400
    assert "難度" in rejected.get_json()["msg"]

    created = client.post("/api/games/chess/practice", json={"difficulty": "hard"})
    assert created.status_code == 200
    match_id = created.get_json()["match_id"]
    match = client.get(f"/api/games/chess/matches/{match_id}").get_json()["match"]
    assert match["computer_difficulty"] == "hard"


def test_chess_computer_normal_difficulty_prefers_high_value_capture():
    board = {
        "e1": "K",
        "e8": "k",
        "d8": "q",
        "d1": "Q",
        "h2": "P",
    }
    move = choose_computer_move(board, "black", "normal")
    assert move["from"] == "d8"
    assert move["to"] == "d1"
    assert move["captured"] == "Q"


def test_chess_pvp_checkmate_finishes_match(tmp_path):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    app = _build_app(db_path, actor_box)
    client = app.test_client()

    invite = client.post("/api/games/chess/invites", json={"opponent_username": "bob"})
    assert invite.status_code == 200
    invite_id = invite.get_json()["invite_id"]

    actor_box["actor"] = {"id": 3, "username": "bob", "role": "user"}
    with patch("routes.games.random.choice", return_value=True):
        accepted = client.post(f"/api/games/chess/invites/{invite_id}/accept", json={})
    assert accepted.status_code == 200
    match_id = accepted.get_json()["match_id"]

    moves = [
        ({"id": 2, "username": "alice", "role": "user"}, "f2", "f3"),
        ({"id": 3, "username": "bob", "role": "user"}, "e7", "e5"),
        ({"id": 2, "username": "alice", "role": "user"}, "g2", "g4"),
        ({"id": 3, "username": "bob", "role": "user"}, "d8", "h4"),
    ]
    final = None
    for actor, from_square, to_square in moves:
        actor_box["actor"] = actor
        final = client.post(f"/api/games/chess/matches/{match_id}/move", json={"from": from_square, "to": to_square})
        assert final.status_code == 200

    match = final.get_json()["match"]
    assert match["status"] == "finished"
    assert match["result_reason"] == "checkmate"
    assert match["winner_username"] == "bob"
    assert match["legal_moves"] == []


def test_chess_pvp_accept_randomizes_sides(tmp_path):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    app = _build_app(db_path, actor_box)
    client = app.test_client()

    invite = client.post("/api/games/chess/invites", json={"opponent_username": "bob"})
    assert invite.status_code == 200
    invite_id = invite.get_json()["invite_id"]

    actor_box["actor"] = {"id": 3, "username": "bob", "role": "user"}
    with patch("routes.games.random.choice", return_value=False):
        accepted = client.post(f"/api/games/chess/invites/{invite_id}/accept", json={})
    assert accepted.status_code == 200
    match_id = accepted.get_json()["match_id"]

    bob_match = client.get(f"/api/games/chess/matches/{match_id}").get_json()["match"]
    assert bob_match["my_side"] == "white"
    assert bob_match["white_username"] == "bob"
    assert bob_match["black_username"] == "alice"

    actor_box["actor"] = {"id": 2, "username": "alice", "role": "user"}
    alice_match = client.get(f"/api/games/chess/matches/{match_id}").get_json()["match"]
    assert alice_match["my_side"] == "black"


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


def test_finished_match_can_be_deleted_from_own_list_without_removing_leaderboard(tmp_path):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    app = _build_app(db_path, actor_box)
    client = app.test_client()

    invite = client.post("/api/games/chess/invites", json={"opponent_username": "bob"})
    invite_id = invite.get_json()["invite_id"]
    actor_box["actor"] = {"id": 3, "username": "bob", "role": "user"}
    accepted = client.post(f"/api/games/chess/invites/{invite_id}/accept", json={})
    match_id = accepted.get_json()["match_id"]

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        UPDATE game_matches
        SET status='finished', winner_user_id=2, leaderboard_week='2026-W18',
            result_reason='checkmate', finished_at='2026-04-29T00:00:00+00:00'
        WHERE id=?
        """,
        (match_id,),
    )
    conn.commit()
    conn.close()

    actor_box["actor"] = {"id": 2, "username": "alice", "role": "user"}
    deleted = client.delete(f"/api/games/chess/matches/{match_id}")
    assert deleted.status_code == 200
    assert deleted.get_json()["ok"] is True

    alice_matches = client.get("/api/games/chess/matches")
    assert alice_matches.status_code == 200
    assert alice_matches.get_json()["matches"] == []

    leaderboard = client.get("/api/games/chess/leaderboard?week=2026-W18")
    assert leaderboard.status_code == 200
    assert leaderboard.get_json()["leaderboard"][0]["username"] == "alice"

    actor_box["actor"] = {"id": 3, "username": "bob", "role": "user"}
    bob_matches = client.get("/api/games/chess/matches")
    assert [row["id"] for row in bob_matches.get_json()["matches"]] == [match_id]


def test_active_match_cannot_be_deleted(tmp_path):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    app = _build_app(db_path, actor_box)
    client = app.test_client()

    created = client.post("/api/games/chess/practice", json={})
    match_id = created.get_json()["match_id"]

    deleted = client.delete(f"/api/games/chess/matches/{match_id}")
    assert deleted.status_code == 409
    assert "進行中" in deleted.get_json()["msg"]
