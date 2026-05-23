import json
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch
from pathlib import Path

import chess
from flask import Flask, jsonify

from routes.games import (
    EXP1_SEARCH_DIFFICULTY,
    SCORE_RANKED_SOLO_GAMES,
    SOLO_GAME_KEYS,
    choose_computer_move,
    ensure_game_schema,
    game_schema_sql,
    register_games_routes,
)
from services.games import chess_pipeline as chess_pipeline_service
from services.games import chess_pv as chess_pv_service
from services.games.chess_dl import (
    EXPERIMENT_DL_DIFFICULTY,
    bundled_chess_dl_model_path,
    choose_experiment_dl_move,
    explain_experiment_dl_decision,
    rank_experiment_dl_policy_moves,
    record_experiment_dl_learning,
    train_experiment_dl_from_replay_samples,
)
from services.games.chess_engine import bundled_chess_engine_db_path, ChessExperimentStore, choose_experiment_move, ensure_chess_engine_schema, record_experiment_learning
from services.games.chess_nn import EXPERIMENT_NN_DIFFICULTY, bundled_chess_nn_model_path, record_experiment_nn_learning
from services.games.chess_pv import (
    EXPERIMENT_PV_DIFFICULTY,
    bundled_chess_pv_model_path,
    choose_experiment_pv_move,
    explain_experiment_pv_decision,
    rank_experiment_pv_policy_moves,
    record_experiment_pv_learning,
    train_experiment_pv_from_replay_samples,
)
from services.games.chess_replay_buffer import (
    classify_replay_record,
    replay_buffer_summary,
)
from services.games.chess_model_registry import ensure_runtime_model_from_bundle
from services.games.chess_pv import experiment_pv_model_template
from services.games.chess import game_status, initial_board, legal_moves, validate_move
from services.games.chess_search import ZobristHasher, search_best_move
from services.users.friends import ensure_social_schema


def _build_app(db_path, actor_box, points_service=None, chess_engine_store=None):
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
        "chess_engine_store": chess_engine_store,
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
    ensure_social_schema(conn)
    conn.execute(
        """
        INSERT INTO user_friends (user_id, friend_user_id, status, requested_by, created_at, updated_at)
        VALUES (2, 3, 'accepted', 2, '2026-01-01T00:00:00', '2026-01-01T00:00:00')
        """
    )
    conn.commit()
    conn.close()


def _build_chess_engine_store(tmp_path):
    return ChessExperimentStore(tmp_path / "runtime" / "games" / "models" / "chess_experiment.db")


class FakePointsService:
    def __init__(self):
        self.calls = []
        self.wallet_balance = 0
        self.by_idempotency = {}

    def rc1_facade(self):
        return self

    def grant_reward(self, **kwargs):
        return self.record_transaction(**kwargs)

    def record_transaction(self, **kwargs):
        key = kwargs.get("idempotency_key") or f"call:{len(self.calls)}"
        if key in self.by_idempotency:
            return self.by_idempotency[key]
        self.calls.append(kwargs)
        self.wallet_balance += int(kwargs.get("amount") or 0)
        result = {
            "ok": True,
            "created": True,
            "ledger": {"ledger_uuid": f"ledger-{len(self.calls)}"},
            "wallet": {
                "points_balance": self.wallet_balance,
                "points_frozen": 0,
                "total_points_earned": self.wallet_balance,
                "total_points_spent": 0,
                "wallet_status": "active",
            },
        }
        self.by_idempotency[key] = result
        return result


def _history_from_uci_sequence(sequence):
    board = chess.Board()
    history = []
    for uci in sequence:
        move = chess.Move.from_uci(uci)
        piece = board.piece_at(move.from_square)
        captured = board.piece_at(move.to_square)
        if board.is_en_passant(move):
            capture_square = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
            captured = board.piece_at(capture_square)
        board.push(move)
        history.append({
            "by": "white" if not board.turn else "black",
            "from": chess.square_name(move.from_square),
            "to": chess.square_name(move.to_square),
            "piece": piece.symbol() if piece else "",
            "captured": captured.symbol() if captured else None,
            "promotion": chess.piece_symbol(move.promotion) if move.promotion else None,
            "at": "2026-05-08T00:00:00Z",
        })
    return history, {
        square_name: piece.symbol()
        for square_name, piece in ((chess.square_name(square), piece) for square, piece in board.piece_map().items())
    } | {"__fen__": board.fen()}, ("white" if board.turn == chess.WHITE else "black")


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
    ensure_social_schema(conn)
    conn.execute(
        """
        INSERT INTO user_friends (user_id, friend_user_id, status, requested_by, created_at, updated_at)
        VALUES (2, 3, 'accepted', 2, '2026-01-01T00:00:00', '2026-01-01T00:00:00')
        """
    )
    conn.commit()
    conn.close()


def test_game_matches_difficulty_enum_in_sync_across_bootstrap_and_runtime():
    """bootstrap.schema.sql and routes.games.game_schema_sql() must keep the
    computer_difficulty CHECK list aligned. Otherwise fresh installs and the
    runtime ensure-schema migration end up with different enum sets."""
    bootstrap_sql = (Path(__file__).resolve().parents[2] / "bootstrap.schema.sql").read_text(encoding="utf-8")
    runtime_sql = game_schema_sql()
    for value in (
        "'experiment 0:minimax2ply'",
        "'experiment 1:search'",
        "'experiment 2:nn'",
        "'experiment 4:pv'",
        "'experiment 5:nnue'",
        "'experiment 6:neuralnet'",
        "'stockfish'",
        "computer_config_json",
    ):
        assert value in bootstrap_sql, f"{value} missing from bootstrap.schema.sql"
        assert value in runtime_sql, f"{value} missing from routes.games.game_schema_sql()"


def test_game_catalog_includes_solo_games(tmp_path):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    app = _build_app(db_path, actor_box)
    client = app.test_client()

    with patch("routes.games.stockfish_available", return_value=False):
        response = client.get("/api/games/catalog")
    assert response.status_code == 200
    games = response.get_json()["games"]
    by_key = {game["key"]: game for game in games}
    assert {
        "chess",
        "sudoku",
        "minesweeper",
        "1a2b",
        "tetris",
        "real_tetris",
        "space_shooter",
        "fps_arena",
        "open_world",
        "racing",
        "bullet_hell",
        "stickman_shooter",
        "snake",
        "game_2048",
        "brick_breaker",
        "reversi",
        "go",
        "gomoku",
        "chinese_chess",
    } <= set(by_key)
    assert [item["key"] for item in by_key["chess"]["computer_difficulties"]] == [
        "experiment 0:minimax2ply",
        "experiment 1:search",
        "experiment 2:nn",
        "experiment 3:dl",
        "experiment 4:pv",
        "experiment 5:nnue",
        "experiment 6:neuralnet",
    ]
    assert by_key["sudoku"]["supports_invites"] is False
    assert by_key["minesweeper"]["supports_computer"] is False
    assert by_key["chinese_chess"]["title"] == "中國象棋"
    assert by_key["chinese_chess"]["supports_invites"] is False
    assert [item["key"] for item in by_key["chinese_chess"]["computer_difficulties"]] == [
        "easy",
        "normal",
        "hard",
    ]
    assert by_key["1a2b"]["supports_invites"] is False
    assert by_key["tetris"]["supports_invites"] is False


def test_game_catalog_adds_stockfish_only_when_local_binary_available(tmp_path):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    app = _build_app(db_path, actor_box)
    client = app.test_client()

    with patch("routes.games.stockfish_available", return_value=False):
        payload = client.get("/api/games/catalog").get_json()
    chess_game = next(game for game in payload["games"] if game["key"] == "chess")
    assert "stockfish" not in [item["key"] for item in chess_game["computer_difficulties"]]

    with patch("routes.games.stockfish_available", return_value=True):
        payload = client.get("/api/games/catalog").get_json()
    chess_game = next(game for game in payload["games"] if game["key"] == "chess")
    stockfish_rows = [item for item in chess_game["computer_difficulties"] if item["key"] == "stockfish"]
    assert stockfish_rows == [{"key": "stockfish", "label": "Stockfish（本機）", "local_only": True}]
    by_key = {game["key"]: game for game in payload["games"]}
    assert by_key["real_tetris"]["title"] == "真實版俄羅斯方塊"
    assert by_key["space_shooter"]["supports_computer"] is False
    assert by_key["fps_arena"]["supports_invites"] is True
    assert [item["key"] for item in by_key["fps_arena"]["multiplayer_modes"]] == ["coop", "pvp"]
    assert by_key["open_world"]["title"] == "都市開放世界"
    assert by_key["open_world"]["supports_computer"] is False
    assert by_key["racing"]["title"] == "街頭賽車"
    assert by_key["racing"]["supports_invites"] is False
    assert by_key["racing"]["supports_computer"] is False
    assert by_key["bullet_hell"]["title"] == "彈幕遊戲"
    assert by_key["stickman_shooter"]["title"] == "火柴人橫向射擊"
    assert by_key["stickman_shooter"]["supports_invites"] is True
    assert [item["key"] for item in by_key["stickman_shooter"]["multiplayer_modes"]] == ["coop"]
    assert by_key["snake"]["supports_invites"] is False
    assert by_key["game_2048"]["supports_computer"] is False
    assert by_key["brick_breaker"]["title"] == "打磚塊"
    assert by_key["reversi"]["title"] == "黑白棋"
    assert by_key["go"]["title"] == "圍棋"
    assert [item["key"] for item in by_key["go"]["computer_difficulties"]] == [
        "easy",
        "normal",
        "hard",
        "katago",
    ]
    assert by_key["gomoku"]["title"] == "五子棋"


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
    assert [row["username"] for row in payload["users"]] == ["bob"]
    assert payload["users"][0]["is_friend"] is True

    invite = client.post("/api/games/chess/invites", json={"opponent_username": "bob"})
    assert invite.status_code == 200
    assert invite.get_json()["ok"] is True

    blocked = client.post("/api/games/chess/invites", json={"opponent_username": "root"})
    assert blocked.status_code == 403
    assert "好友" in blocked.get_json()["msg"]


def test_multiplayer_rooms_invite_accept_and_sync_events(tmp_path):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    app = _build_app(db_path, actor_box)
    client = app.test_client()

    created = client.post(
        "/api/games/stickman_shooter/multiplayer/invites",
        json={"opponent_username": "bob", "mode": "coop"},
    )
    assert created.status_code == 200
    created_payload = created.get_json()
    assert created_payload["ok"] is True
    invite_id = created_payload["invite_id"]
    room_id = created_payload["room"]["id"]
    assert created_payload["room"]["mode"] == "coop"

    lobby = client.get("/api/games/stickman_shooter/multiplayer")
    assert lobby.status_code == 200
    assert lobby.get_json()["rooms"][0]["id"] == room_id

    actor_box["actor"] = {"id": 3, "username": "bob", "role": "user"}
    pending = client.get("/api/games/multiplayer/invites/pending")
    assert pending.status_code == 200
    pending_payload = pending.get_json()
    assert pending_payload["invites"][0]["id"] == invite_id
    assert pending_payload["invites"][0]["room"]["id"] == room_id
    assert pending_payload["invites"][0]["room"]["room_code"]

    accepted = client.post(f"/api/games/multiplayer/invites/{invite_id}/accept", json={})
    assert accepted.status_code == 200
    accepted_payload = accepted.get_json()
    assert accepted_payload["room"]["guest_user_id"] == 3

    bob_sync = client.post(
        f"/api/games/multiplayer/rooms/{room_id}/state",
        json={
            "state": {"x": 120, "y": 272, "hp": 5, "status": "active"},
            "events": [
                {
                    "type": "friendly_fire",
                    "target_user_id": 2,
                    "payload": {"damage": 1, "x": 120, "y": 272},
                }
            ],
        },
    )
    assert bob_sync.status_code == 200

    actor_box["actor"] = {"id": 2, "username": "alice", "role": "user"}
    alice_sync = client.post(
        f"/api/games/multiplayer/rooms/{room_id}/state",
        json={"state": {"x": 80, "y": 272, "hp": 5, "status": "active"}, "after_event_id": 0},
    )
    assert alice_sync.status_code == 200
    payload = alice_sync.get_json()
    assert {row["user_id"] for row in payload["players"]} == {2, 3}
    assert payload["events"][0]["event_type"] == "friendly_fire"
    assert payload["events"][0]["target_user_id"] == 2


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
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='game_daily_challenge_rewards'").fetchone()
    finally:
        conn.close()


def test_game_schema_rebuild_keeps_game_invites_fk_pointing_to_game_matches(tmp_path):
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
          (2, 'alice', 'user', 'active'),
          (3, 'bob', 'user', 'active');
        CREATE TABLE game_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_key TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'pvp',
            status TEXT NOT NULL DEFAULT 'active',
            white_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            black_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            current_turn TEXT NOT NULL DEFAULT 'white',
            board_json TEXT NOT NULL,
            move_history_json TEXT NOT NULL DEFAULT '[]',
            winner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            result_reason TEXT,
            leaderboard_week TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            finished_at TEXT,
            white_deleted_at TEXT,
            black_deleted_at TEXT,
            CHECK (game_key IN ('chess')),
            CHECK (mode IN ('pvp', 'computer')),
            CHECK (status IN ('active', 'finished', 'cancelled')),
            CHECK (current_turn IN ('white', 'black'))
        );
        CREATE TABLE game_invites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_key TEXT NOT NULL,
            inviter_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            opponent_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'pending',
            match_id INTEGER REFERENCES game_matches(id) ON DELETE SET NULL,
            message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT,
            CHECK (game_key IN ('chess')),
            CHECK (status IN ('pending', 'accepted', 'rejected', 'cancelled', 'expired'))
        );
        """
    )
    ensure_game_schema(conn)
    conn.commit()

    invite_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='game_invites'"
    ).fetchone()["sql"]
    assert "game_matches_old" not in str(invite_sql or "")
    conn.execute(
        """
        INSERT INTO game_invites (
            game_key, inviter_user_id, opponent_user_id, status, message, created_at, updated_at, expires_at
        ) VALUES ('chess', 2, 3, 'pending', '', '2026-05-08T00:00:00+00:00', '2026-05-08T00:00:00+00:00', '2026-05-15T00:00:00+00:00')
        """
    )
    conn.commit()
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

    fps = client.post(
        "/api/games/fps_arena/solo-scores",
        json={"score": 3200, "raw_elapsed_ms": 60000, "penalty_seconds": 0, "elapsed_ms": 60000, "difficulty": "aim", "puzzle_id": "fps-arena-aim"},
    )
    assert fps.status_code == 200
    fps_board = client.get("/api/games/fps_arena/solo-leaderboard?difficulty=aim")
    assert fps_board.status_code == 200
    fps_payload = fps_board.get_json()
    assert fps_payload["rank_mode"] == "score_desc"
    assert fps_payload["difficulty"] == "aim"
    assert fps_payload["leaderboard"][0]["score"] == 3200

    bad = client.post(
        "/api/games/space_shooter/solo-scores",
        json={"score": 0, "raw_elapsed_ms": 1000, "penalty_seconds": 0, "elapsed_ms": 1000, "puzzle_id": "space-shooter-standard"},
    )
    assert bad.status_code == 400


def test_daily_challenge_completion_awards_points_once_per_game_day(tmp_path):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    points = FakePointsService()
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    app = _build_app(db_path, actor_box, points_service=points)
    client = app.test_client()
    payload = {
        "score": 1500,
        "raw_elapsed_ms": 90000,
        "penalty_seconds": 0,
        "elapsed_ms": 90000,
        "difficulty": "daily-rush",
        "puzzle_id": "tetris-daily-2026-05-13",
    }

    first = client.post("/api/games/tetris/solo-scores", json=payload)
    assert first.status_code == 200
    first_reward = first.get_json()["daily_reward"]
    assert first_reward["awarded"] is True
    assert first_reward["reward_points"] == 25
    assert first_reward["wallet"]["points_balance"] == 25

    second = client.post("/api/games/tetris/solo-scores", json={**payload, "score": 1800})
    assert second.status_code == 200
    second_reward = second.get_json()["daily_reward"]
    assert second_reward["awarded"] is False
    assert second_reward["already_claimed"] is True
    assert len(points.calls) == 1
    assert points.calls[0]["action_type"] == "game_daily_challenge_reward"
    assert points.calls[0]["idempotency_key"] == "game_daily_reward:tetris:tetris-daily-2026-05-13:2"

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM game_daily_challenge_rewards").fetchone()
        assert row[0] == 1
    finally:
        conn.close()


def test_solo_score_route_accepts_all_registered_solo_game_keys(tmp_path):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    app = _build_app(db_path, actor_box)
    client = app.test_client()

    for game_key in sorted(SOLO_GAME_KEYS):
        payload = {
            "raw_elapsed_ms": 1000,
            "penalty_seconds": 0,
            "elapsed_ms": 1000,
            "puzzle_id": f"{game_key}-smoke",
        }
        if game_key == "minesweeper":
            payload["difficulty"] = "easy"
        if game_key == "1a2b":
            payload["guess_count"] = 3
        if game_key in SCORE_RANKED_SOLO_GAMES:
            payload["score"] = 100
        if game_key == "fps_arena":
            payload["difficulty"] = "aim"
        response = client.post(f"/api/games/{game_key}/solo-scores", json=payload)
        assert response.status_code == 200, (game_key, response.get_data(as_text=True))


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
    castle_options = [move for move in legal_moves(board, "white") if move["from"] == "e1" and move["castle"]]
    assert any(move["to"] == "g1" for move in castle_options)
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
    ep_options = [move for move in legal_moves(board, "white") if move["en_passant"]]
    assert any(move["from"] == "e5" and move["to"] == "d6" for move in ep_options)
    en_passant = validate_move(board, "white", "e5", "d6")
    assert en_passant["en_passant"] is True
    assert en_passant["captured"] == "p"
    assert "d5" not in en_passant["board"]
    assert en_passant["board"]["d6"] == "P"

    promotion_board = {"e1": "K", "a8": "k", "e7": "P"}
    promotion_options = [move for move in legal_moves(promotion_board, "white") if move["from"] == "e7" and move["to"] == "e8"]
    assert {move["promotion"] for move in promotion_options} == {"q", "r", "b", "n"}
    promoted = validate_move(promotion_board, "white", "e7", "e8")
    assert promoted["promotion"] == "q"
    assert promoted["board"]["e8"] == "Q"
    promoted_knight = validate_move(promotion_board, "white", "e7", "e8", "n")
    assert promoted_knight["promotion"] == "n"
    assert promoted_knight["board"]["e8"] == "N"


def test_chess_match_payload_exposes_claimable_draw_and_claim_endpoint(tmp_path):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    app = _build_app(db_path, actor_box)
    client = app.test_client()

    history, board, current_turn = _history_from_uci_sequence(
        ["g1f3", "g8f6", "f3g1", "f6g8", "g1f3", "g8f6", "f3g1"]
    )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    now = "2026-05-08T00:00:00Z"
    try:
        cur = conn.execute(
            """
            INSERT INTO game_matches (
                game_key, mode, status, white_user_id, black_user_id, human_side, current_turn,
                board_json, move_history_json, created_at, updated_at
            ) VALUES ('chess', 'pvp', 'active', 2, 3, 'white', ?, ?, ?, ?, ?)
            """,
            (current_turn, json.dumps(board, ensure_ascii=False, sort_keys=True), json.dumps(history, ensure_ascii=False), now, now),
        )
        match_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    detail = client.get(f"/api/games/chess/matches/{match_id}")
    assert detail.status_code == 200
    match = detail.get_json()["match"]
    assert match["can_claim_draw"] is True
    assert "threefold_repetition" in match["draw_claim_reasons"]

    actor_box["actor"] = {"id": 2, "username": "alice", "role": "user"}
    denied = client.post(f"/api/games/chess/matches/{match_id}/claim-draw", json={})
    assert denied.status_code == 409

    actor_box["actor"] = {"id": 3, "username": "bob", "role": "user"}
    claimed = client.post(f"/api/games/chess/matches/{match_id}/claim-draw", json={})
    assert claimed.status_code == 200
    payload = claimed.get_json()
    assert payload["ok"] is True
    assert payload["match"]["status"] == "finished"
    assert payload["match"]["result_reason"] == "threefold_repetition"


def test_chess_draw_offer_accept_reject_and_move_clears_offer(tmp_path):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    app = _build_app(db_path, actor_box)
    client = app.test_client()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    now = "2026-05-08T00:00:00Z"
    try:
        cur = conn.execute(
            """
            INSERT INTO game_matches (
                game_key, mode, status, white_user_id, black_user_id, human_side, current_turn,
                board_json, move_history_json, created_at, updated_at
            ) VALUES ('chess', 'pvp', 'active', 2, 3, 'white', 'white', ?, '[]', ?, ?)
            """,
            (json.dumps(initial_board(), ensure_ascii=False, sort_keys=True), now, now),
        )
        first_match_id = cur.lastrowid
        cur = conn.execute(
            """
            INSERT INTO game_matches (
                game_key, mode, status, white_user_id, black_user_id, human_side, current_turn,
                board_json, move_history_json, created_at, updated_at
            ) VALUES ('chess', 'pvp', 'active', 2, 3, 'white', 'white', ?, '[]', ?, ?)
            """,
            (json.dumps(initial_board(), ensure_ascii=False, sort_keys=True), now, now),
        )
        second_match_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    offered = client.post(f"/api/games/chess/matches/{first_match_id}/offer-draw", json={})
    assert offered.status_code == 200
    payload = offered.get_json()
    assert payload["match"]["draw_offer_pending"] is True
    assert payload["match"]["draw_offer_by_user_id"] == 2
    assert payload["match"]["can_offer_draw"] is False

    actor_box["actor"] = {"id": 3, "username": "bob", "role": "user"}
    detail = client.get(f"/api/games/chess/matches/{first_match_id}")
    assert detail.status_code == 200
    match = detail.get_json()["match"]
    assert match["can_accept_draw_offer"] is True
    assert match["can_reject_draw_offer"] is True

    rejected = client.post(f"/api/games/chess/matches/{first_match_id}/respond-draw", json={"action": "reject"})
    assert rejected.status_code == 200
    payload = rejected.get_json()
    assert payload["match"]["status"] == "active"
    assert payload["match"]["draw_offer_pending"] is False

    actor_box["actor"] = {"id": 2, "username": "alice", "role": "user"}
    offered_again = client.post(f"/api/games/chess/matches/{second_match_id}/offer-draw", json={})
    assert offered_again.status_code == 200

    actor_box["actor"] = {"id": 3, "username": "bob", "role": "user"}
    accepted = client.post(f"/api/games/chess/matches/{second_match_id}/respond-draw", json={"action": "accept"})
    assert accepted.status_code == 200
    payload = accepted.get_json()
    assert payload["match"]["status"] == "finished"
    assert payload["match"]["result_reason"] == "agreed_draw"

    actor_box["actor"] = {"id": 2, "username": "alice", "role": "user"}
    offered_third = client.post(f"/api/games/chess/matches/{first_match_id}/offer-draw", json={})
    assert offered_third.status_code == 200
    moved = client.post(f"/api/games/chess/matches/{first_match_id}/move", json={"from": "e2", "to": "e4"})
    assert moved.status_code == 200
    payload = moved.get_json()
    assert payload["match"]["draw_offer_pending"] is False


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
    app = _build_app(db_path, actor_box, chess_engine_store=_build_chess_engine_store(tmp_path))
    client = app.test_client()

    rejected = client.post("/api/games/chess/practice", json={"difficulty": "impossible"})
    assert rejected.status_code == 400
    assert "難度" in rejected.get_json()["msg"]

    created = client.post("/api/games/chess/practice", json={"difficulty": "hard"})
    assert created.status_code == 200
    match_id = created.get_json()["match_id"]
    match = client.get(f"/api/games/chess/matches/{match_id}").get_json()["match"]
    assert match["computer_difficulty"] == "experiment 0:minimax2ply"

    experiment = client.post("/api/games/chess/practice", json={"difficulty": "experiment"})
    assert experiment.status_code == 200
    experiment_id = experiment.get_json()["match_id"]
    experiment_match = client.get(f"/api/games/chess/matches/{experiment_id}").get_json()["match"]
    assert experiment_match["computer_difficulty"] == "experiment 1:search"

    experiment_nn = client.post("/api/games/chess/practice", json={"difficulty": "experiment 2:nn"})
    assert experiment_nn.status_code == 200
    experiment_nn_id = experiment_nn.get_json()["match_id"]
    experiment_nn_match = client.get(f"/api/games/chess/matches/{experiment_nn_id}").get_json()["match"]
    assert experiment_nn_match["computer_difficulty"] == "experiment 2:nn"

    experiment_dl = client.post("/api/games/chess/practice", json={"difficulty": "experiment 3:dl"})
    assert experiment_dl.status_code == 200
    experiment_dl_id = experiment_dl.get_json()["match_id"]
    experiment_dl_match = client.get(f"/api/games/chess/matches/{experiment_dl_id}").get_json()["match"]
    assert experiment_dl_match["computer_difficulty"] == "experiment 3:dl"

    experiment_pv = client.post("/api/games/chess/practice", json={"difficulty": "experiment 4:pv"})
    assert experiment_pv.status_code == 200
    experiment_pv_id = experiment_pv.get_json()["match_id"]
    experiment_pv_match = client.get(f"/api/games/chess/matches/{experiment_pv_id}").get_json()["match"]
    assert experiment_pv_match["computer_difficulty"] == "experiment 4:pv"

    experiment_nnue = client.post("/api/games/chess/practice", json={"difficulty": "experiment 5:nnue"})
    assert experiment_nnue.status_code == 200
    experiment_nnue_id = experiment_nnue.get_json()["match_id"]
    experiment_nnue_match = client.get(f"/api/games/chess/matches/{experiment_nnue_id}").get_json()["match"]
    assert experiment_nnue_match["computer_difficulty"] == "experiment 5:nnue"

    with patch("routes.games.EXP6_DEFAULT_SEARCH_PROFILE", "fast"):
        experiment_exp6 = client.post("/api/games/chess/practice", json={"difficulty": "experiment 6:neuralnet"})
        assert experiment_exp6.status_code == 200
        experiment_exp6_id = experiment_exp6.get_json()["match_id"]
        experiment_exp6_match = client.get(f"/api/games/chess/matches/{experiment_exp6_id}").get_json()["match"]
        assert experiment_exp6_match["computer_difficulty"] == "experiment 6:neuralnet"
        experiment_exp6_move = client.post(f"/api/games/chess/matches/{experiment_exp6_id}/move", json={"from": "e2", "to": "e4"})
        assert experiment_exp6_move.status_code == 200
        exp6_history = experiment_exp6_move.get_json()["match"]["move_history"]
        assert exp6_history[-1]["computer"] is True
        assert exp6_history[-1]["piece"]

        experiment_exp6_black = client.post("/api/games/chess/practice", json={"difficulty": "experiment 6:neuralnet", "side": "black"})
        assert experiment_exp6_black.status_code == 200
        exp6_black_id = experiment_exp6_black.get_json()["match_id"]
        exp6_black_match = client.get(f"/api/games/chess/matches/{exp6_black_id}").get_json()["match"]
        assert exp6_black_match["move_history"][0]["computer"] is True
        assert exp6_black_match["move_history"][0]["piece"]

    with patch("routes.games.stockfish_available", return_value=False):
        stockfish_unavailable = client.post("/api/games/chess/practice", json={"difficulty": "stockfish"})
    assert stockfish_unavailable.status_code == 400
    assert "難度" in stockfish_unavailable.get_json()["msg"]

    with patch("routes.games.stockfish_available", return_value=True):
        stockfish_match = client.post("/api/games/chess/practice", json={"difficulty": "stockfish", "stockfish_depth": 14})
    assert stockfish_match.status_code == 200
    stockfish_id = stockfish_match.get_json()["match_id"]
    stockfish_detail = client.get(f"/api/games/chess/matches/{stockfish_id}").get_json()["match"]
    assert stockfish_detail["computer_difficulty"] == "stockfish"
    assert stockfish_detail["stockfish_depth"] == 14
    assert stockfish_detail["computer_config"]["stockfish_depth"] == 14

    with patch("routes.games.stockfish_available", return_value=True):
        capped_match = client.post("/api/games/chess/practice", json={"difficulty": "stockfish", "stockfish_depth": 999})
    assert capped_match.status_code == 200
    capped_id = capped_match.get_json()["match_id"]
    capped_detail = client.get(f"/api/games/chess/matches/{capped_id}").get_json()["match"]
    assert capped_detail["stockfish_depth"] == 20


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


def test_chess_stockfish_difficulty_passes_configured_depth():
    board = {
        "e1": "K",
        "e8": "k",
        "d1": "Q",
        "d8": "q",
    }
    sentinel = {"from": "d8", "to": "d1", "piece": "q"}
    with patch("routes.games.stockfish_available", return_value=True), patch(
        "routes.games.choose_stockfish_move", return_value=sentinel
    ) as choose:
        move = choose_computer_move(board, "black", "stockfish", computer_config={"stockfish_depth": 12})
    assert move == sentinel
    assert choose.call_args.kwargs["depth"] == 12


def test_experiment_learning_store_uses_separate_runtime_db(tmp_path):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    store = _build_chess_engine_store(tmp_path)
    row = {
        "id": 7,
        "mode": "computer",
        "computer_difficulty": "experiment",
        "human_side": "black",
        "move_history_json": '[{"by":"white","from":"e2","to":"e4","piece":"P"}]',
    }
    updated = record_experiment_learning(row, winner_color="white", store=store)
    assert updated == 1
    assert store.db_path.exists()

    conn = sqlite3.connect(db_path)
    try:
        learning_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='game_chess_engine_memory'"
        ).fetchone()
        assert learning_table is None
    finally:
        conn.close()

    learning_conn = sqlite3.connect(store.db_path)
    learning_conn.row_factory = sqlite3.Row
    try:
        memory = learning_conn.execute(
            "SELECT move_uci, sample_count, win_count, score_total FROM game_chess_engine_memory"
        ).fetchone()
        assert memory["move_uci"] == "e2e4"
        assert memory["sample_count"] == 1
        assert memory["win_count"] == 1
        assert memory["score_total"] > 0
    finally:
        learning_conn.close()


def test_experiment_move_reads_learning_bias_from_store(tmp_path):
    store = _build_chess_engine_store(tmp_path)
    with store.connect() as conn:
        conn.execute(
            """
            INSERT INTO game_chess_engine_memory (
                position_key, side, move_uci, sample_count, win_count, draw_count, loss_count, score_total, updated_at
            ) VALUES (?, 'white', 'e2e4', 20, 20, 0, 0, 160, '2026-05-07T00:00:00+00:00')
            """,
            ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -",),
        )
        conn.commit()
    move = choose_experiment_move(initial_board(), "white", store=store)
    assert move["from"] == "e2"
    assert move["to"] == "e4"


def test_experiment_resign_collects_replay_without_online_learning(tmp_path, monkeypatch):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    store = _build_chess_engine_store(tmp_path)
    replay_path = tmp_path / "runtime" / "reports" / "games" / "chess_replays.jsonl"
    rejected_path = tmp_path / "runtime" / "reports" / "games" / "chess_replays_rejected.jsonl"
    monkeypatch.setenv("HTML_LEARNING_CHESS_REPLAY_BUFFER_PATH", str(replay_path))
    monkeypatch.setenv("HTML_LEARNING_CHESS_REPLAY_REJECTED_PATH", str(rejected_path))
    app = _build_app(db_path, actor_box, chess_engine_store=store)
    client = app.test_client()

    created = client.post("/api/games/chess/practice", json={"difficulty": "experiment", "side": "black"})
    assert created.status_code == 200
    match_id = created.get_json()["match_id"]

    resigned = client.post(f"/api/games/chess/matches/{match_id}/resign", json={})
    assert resigned.status_code == 200

    learning_conn = sqlite3.connect(store.db_path)
    learning_conn.row_factory = sqlite3.Row
    try:
        rows = learning_conn.execute(
            "SELECT COUNT(*) AS c FROM game_chess_engine_memory"
        ).fetchone()
        assert rows["c"] == 0
    finally:
        learning_conn.close()
    lines = rejected_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    replay = json.loads(lines[0])
    assert replay["source"] == "user_games"
    assert replay["engine_name"] == EXP1_SEARCH_DIFFICULTY
    assert replay["confidence_score"] <= 0.42
    assert replay["move_count"] == 1
    assert replay["collection_tier"] == "rejected"
    assert "too_short" in replay["quarantine_reasons"]


def test_resign_finished_match_returns_conflict(tmp_path):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    app = _build_app(db_path, actor_box, chess_engine_store=_build_chess_engine_store(tmp_path))
    client = app.test_client()

    created = client.post("/api/games/chess/practice", json={"difficulty": "normal", "side": "black"})
    assert created.status_code == 200
    match_id = created.get_json()["match_id"]

    first = client.post(f"/api/games/chess/matches/{match_id}/resign", json={})
    assert first.status_code == 200

    second = client.post(f"/api/games/chess/matches/{match_id}/resign", json={})
    assert second.status_code == 409
    assert second.get_json()["msg"] == "這局已經結束"


def test_experiment_nn_learning_writes_separate_runtime_model(tmp_path, monkeypatch):
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_2_nn.json"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_NN_MODEL_PATH", str(model_path))
    row = {
        "id": 8,
        "mode": "computer",
        "computer_difficulty": EXPERIMENT_NN_DIFFICULTY,
        "human_side": "black",
        "move_history_json": '[{"by":"white","from":"e2","to":"e4","piece":"P"}]',
    }
    updated = record_experiment_nn_learning(row, winner_color="white")
    assert updated == 1
    assert model_path.exists()
    model = json.loads(model_path.read_text(encoding="utf-8"))
    assert model["sample_count"] >= 1
    assert model["version"] >= 1


def test_experiment_nn_legacy_match_resign_collects_replay_without_mutating_model(tmp_path, monkeypatch):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_2_nn.json"
    replay_path = tmp_path / "runtime" / "reports" / "games" / "chess_replays.jsonl"
    rejected_path = tmp_path / "runtime" / "reports" / "games" / "chess_replays_rejected.jsonl"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_NN_MODEL_PATH", str(model_path))
    monkeypatch.setenv("HTML_LEARNING_CHESS_REPLAY_BUFFER_PATH", str(replay_path))
    monkeypatch.setenv("HTML_LEARNING_CHESS_REPLAY_REJECTED_PATH", str(rejected_path))
    app = _build_app(db_path, actor_box, chess_engine_store=_build_chess_engine_store(tmp_path))
    client = app.test_client()

    conn = sqlite3.connect(db_path)
    try:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        cur = conn.execute(
            """
            INSERT INTO game_matches (
                game_key, mode, status, white_user_id, black_user_id, human_side, computer_difficulty, current_turn,
                board_json, move_history_json, created_at, updated_at
            ) VALUES ('chess', 'computer', 'active', 2, NULL, 'black', 'experiment 2:nn', 'black', ?, ?, ?, ?)
            """,
            (
                json.dumps(initial_board(), ensure_ascii=False, sort_keys=True),
                json.dumps(
                    [
                        {
                            "by": "white",
                            "from": "e2",
                            "to": "e4",
                            "piece": "P",
                            "computer": True,
                            "at": now,
                        }
                    ],
                    ensure_ascii=False,
                ),
                now,
                now,
            ),
        )
        conn.commit()
        match_id = cur.lastrowid
    finally:
        conn.close()
    model_before = model_path.read_text(encoding="utf-8") if model_path.exists() else None

    resigned = client.post(f"/api/games/chess/matches/{match_id}/resign", json={})
    assert resigned.status_code == 200
    if model_before is None:
        assert not model_path.exists()
    else:
        assert model_path.read_text(encoding="utf-8") == model_before
    replay = json.loads(rejected_path.read_text(encoding="utf-8").strip())
    assert replay["engine_name"] == "experiment 2:nn"
    assert replay["collection_tier"] == "rejected"


def test_experiment_dl_learning_writes_runtime_model_and_replay(tmp_path, monkeypatch):
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_3_dl.json"
    replay_path = tmp_path / "runtime" / "models" / "chess_experiment_3_dl_replay.jsonl"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_DL_MODEL_PATH", str(model_path))
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_DL_REPLAY_PATH", str(replay_path))
    row = {
        "id": 9,
        "mode": "computer",
        "computer_difficulty": EXPERIMENT_DL_DIFFICULTY,
        "human_side": "black",
        "move_history_json": '[{"by":"white","from":"e2","to":"e4","piece":"P"}]',
    }
    updated = record_experiment_dl_learning(row, winner_color="white")
    assert updated == 1
    assert model_path.exists()
    assert replay_path.exists()
    model = json.loads(model_path.read_text(encoding="utf-8"))
    assert model["sample_count"] >= 1
    assert model["replay_size"] >= 1


def test_experiment_dl_resign_collects_replay_without_mutating_model(tmp_path, monkeypatch):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_3_dl.json"
    replay_path = tmp_path / "runtime" / "models" / "chess_experiment_3_dl_replay.jsonl"
    user_replay_path = tmp_path / "runtime" / "reports" / "games" / "chess_replays.jsonl"
    rejected_path = tmp_path / "runtime" / "reports" / "games" / "chess_replays_rejected.jsonl"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_DL_MODEL_PATH", str(model_path))
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_DL_REPLAY_PATH", str(replay_path))
    monkeypatch.setenv("HTML_LEARNING_CHESS_REPLAY_BUFFER_PATH", str(user_replay_path))
    monkeypatch.setenv("HTML_LEARNING_CHESS_REPLAY_REJECTED_PATH", str(rejected_path))
    app = _build_app(db_path, actor_box, chess_engine_store=_build_chess_engine_store(tmp_path))
    client = app.test_client()

    created = client.post("/api/games/chess/practice", json={"difficulty": "experiment 3:dl", "side": "black"})
    assert created.status_code == 200
    match_id = created.get_json()["match_id"]
    model_before = model_path.read_text(encoding="utf-8") if model_path.exists() else None
    dl_replay_before = replay_path.read_text(encoding="utf-8") if replay_path.exists() else None

    resigned = client.post(f"/api/games/chess/matches/{match_id}/resign", json={})
    assert resigned.status_code == 200
    if model_before is None:
        assert not model_path.exists()
    else:
        assert model_path.read_text(encoding="utf-8") == model_before
    if dl_replay_before is None:
        assert not replay_path.exists()
    else:
        assert replay_path.read_text(encoding="utf-8") == dl_replay_before
    replay = json.loads(rejected_path.read_text(encoding="utf-8").strip())
    assert replay["engine_name"] == "experiment 3:dl"
    assert replay["collection_tier"] == "rejected"


def test_experiment_dl_move_finds_mate_in_one(tmp_path, monkeypatch):
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_3_dl.json"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_DL_MODEL_PATH", str(model_path))
    board = {"__fen__": "6k1/5Q2/6K1/8/8/8/8/8 w - - 0 1"}

    move = choose_experiment_dl_move(board, "white", model_path=model_path)

    assert move is not None
    chosen_uci = f"{move['from']}{move['to']}{move.get('promotion') or ''}"
    board_obj = chess.Board(board["__fen__"])
    board_obj.push(chess.Move.from_uci(chosen_uci))
    assert board_obj.is_checkmate()


def test_experiment_dl_move_returns_legal_move_on_fresh_model(tmp_path, monkeypatch):
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_3_dl.json"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_DL_MODEL_PATH", str(model_path))
    board = initial_board()

    move = choose_experiment_dl_move(board, "white", model_path=model_path)

    assert move is not None
    applied = validate_move(board, "white", move["from"], move["to"], move.get("promotion"))
    assert isinstance(applied["board"], dict)


def test_experiment_dl_contrastive_replay_can_make_expected_raw_policy_top1(tmp_path, monkeypatch):
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_3_dl.json"
    replay_path = tmp_path / "runtime" / "models" / "chess_experiment_3_dl_replay.jsonl"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_DL_MODEL_PATH", str(model_path))
    fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"

    before = rank_experiment_dl_policy_moves({"__fen__": fen}, "black", model_path=model_path)
    result = train_experiment_dl_from_replay_samples(
        [{"fen": fen, "side": "black", "move_uci": "f7f5", "target": 1.0, "weight": 1.0}],
        model_path=model_path,
        replay_path=replay_path,
        replace_replay=True,
    )
    after = rank_experiment_dl_policy_moves({"__fen__": fen}, "black", model_path=model_path)

    assert before[0]["move"] != "f7f5"
    assert after[0]["move"] == "f7f5"
    assert result["training_objective"] == "contrastive_policy_ranking_with_flank_context_auxiliary_semantic_adapters_budget_scheduler"
    assert result["auxiliary_objectives"]["flank_context_classification_loss"] is True
    assert result["auxiliary_objectives"]["semantic_specific_adapter_loss"] is True
    assert result["auxiliary_objectives"]["retention_aware_update_scheduler"] is True
    assert result["contrastive_negative_updates"] > 0
    assert result["semantic_head_update_count"]
    assert result["semantic_loss_budget_scheduler"] is True
    assert result["loss_budget_by_semantic"]
    assert result["update_schedule_trace"]
    assert result["policy_probe"]["raw_policy_top1_changed_to_expected"] is True


def test_experiment_dl_decision_explain_reports_raw_policy_and_final_scores(tmp_path, monkeypatch):
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_3_dl.json"
    replay_path = tmp_path / "runtime" / "models" / "chess_experiment_3_dl_replay.jsonl"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_DL_MODEL_PATH", str(model_path))
    fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    train_experiment_dl_from_replay_samples(
        [{"fen": fen, "side": "black", "move_uci": "f7f5", "target": 1.0, "weight": 1.0}],
        model_path=model_path,
        replay_path=replay_path,
        replace_replay=True,
    )

    move = choose_experiment_dl_move({"__fen__": fen}, "black", model_path=model_path, search_profile="fast")
    explanation = explain_experiment_dl_decision(
        {"__fen__": fen},
        "black",
        model_path=model_path,
        search_profile="fast",
        watched_moves=["f7f5", "e7e5"],
    )

    assert f"{move['from']}{move['to']}" == "f7f5"
    assert explanation["chosen_move"] == "f7f5"
    assert explanation["chosen_reason"] in {"high_confidence_policy_override", "search_best_move", "opening_sanity_fallback"}
    override = explanation["policy_override"]
    assert "margin" in override
    assert "thresholds" in override
    assert "reason" in override
    watched = {row["move"]: row for row in explanation["watched_moves"]}
    assert {"f7f5", "e7e5"} <= set(watched)
    assert "raw_policy_score" in watched["f7f5"]
    assert "static_eval_score" in watched["f7f5"]
    assert "search_score" in watched["f7f5"]
    assert "fused_score" in watched["f7f5"]
    assert "override_applied" in watched["f7f5"]
    assert "override_reason" in watched["f7f5"]
    assert "final_combined_score" in watched["f7f5"]
    assert explanation["style_profile"]["style_profile"] == "balanced"
    assert explanation["style_profile"]["applied"] is False
    assert watched["f7f5"]["base_score"] == watched["f7f5"]["fused_score"]
    assert watched["f7f5"]["style_bonus"] == 0


def test_experiment_dl_style_profile_reports_bounded_candidates(tmp_path, monkeypatch):
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_3_dl.json"
    replay_path = tmp_path / "runtime" / "models" / "chess_experiment_3_dl_replay.jsonl"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_DL_MODEL_PATH", str(model_path))
    fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    train_experiment_dl_from_replay_samples(
        [{"fen": fen, "side": "black", "move_uci": "f7f5", "target": 1.0, "weight": 1.0}],
        model_path=model_path,
        replay_path=replay_path,
        replace_replay=True,
    )

    explanation = explain_experiment_dl_decision(
        {"__fen__": fen},
        "black",
        model_path=model_path,
        search_profile="fast",
        watched_moves=["f7f5", "e7e5", "d7d5"],
        style_profile="attacking",
    )

    style = explanation["style_profile"]
    assert style["style_profile"] == "attacking"
    assert "candidate_moves" in style
    assert "rejected_style_moves" in style
    assert explanation["chosen_breakdown"]["style_profile"] == "attacking"
    assert "base_score" in explanation["chosen_breakdown"]
    assert "style_bonus" in explanation["chosen_breakdown"]
    assert "final_combined_score" in explanation["chosen_breakdown"]
    selected = next(
        (row for row in style["candidate_moves"] if row["move"] == explanation["chosen_move"]),
        None,
    )
    if selected is not None:
        assert selected["cp_delta_vs_best"] >= -100
    for rejected in style["rejected_style_moves"]:
        assert rejected["cp_delta_vs_best"] < -100
        assert rejected["rejection_reason"]


def test_experiment_dl_style_profile_does_not_override_forced_mate(tmp_path, monkeypatch):
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_3_dl.json"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_DL_MODEL_PATH", str(model_path))
    board = {"__fen__": "6k1/5Q2/6K1/8/8/8/8/8 w - - 0 1"}

    balanced = explain_experiment_dl_decision(board, "white", model_path=model_path, style_profile="balanced")
    attacking = explain_experiment_dl_decision(board, "white", model_path=model_path, style_profile="attacking")
    defensive = explain_experiment_dl_decision(board, "white", model_path=model_path, style_profile="defensive")

    assert balanced["chosen_reason"] == "forced_mate"
    assert attacking["chosen_reason"] == "forced_mate"
    assert defensive["chosen_reason"] == "forced_mate"
    assert attacking["chosen_move"] == balanced["chosen_move"] == defensive["chosen_move"]


def test_experiment_pv_learning_writes_runtime_model(tmp_path, monkeypatch):
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_4_pv.json"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH", str(model_path))
    row = {
        "id": 10,
        "mode": "computer",
        "computer_difficulty": EXPERIMENT_PV_DIFFICULTY,
        "human_side": "black",
        "move_history_json": '[{"by":"white","from":"e2","to":"e4","piece":"P"}]',
    }
    updated = record_experiment_pv_learning(row, winner_color="white")
    assert updated == 1
    assert model_path.exists()
    model = json.loads(model_path.read_text(encoding="utf-8"))
    assert model["sample_count"] >= 1
    assert model["version"] >= 1


def test_experiment_pv_contrastive_replay_can_make_expected_raw_policy_top1(tmp_path, monkeypatch):
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_4_pv.json"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH", str(model_path))
    fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"

    before = rank_experiment_pv_policy_moves({"__fen__": fen}, "black", model_path=model_path)
    result = train_experiment_pv_from_replay_samples(
        [{"fen": fen, "side": "black", "move_uci": "e7e5", "target": 1.0, "weight": 1.0}],
        model_path=model_path,
    )
    after = rank_experiment_pv_policy_moves({"__fen__": fen}, "black", model_path=model_path)

    assert before[0]["move"] != "e7e5"
    assert after[0]["move"] == "e7e5"
    assert result["training_objective"] == "contrastive_policy_ranking"
    assert result["contrastive_negative_updates"] > 0
    assert result["policy_probe"]["raw_policy_top1_changed_to_expected"] is True


def test_experiment_pv_decision_explain_reports_policy_override_scores(tmp_path, monkeypatch):
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_4_pv.json"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH", str(model_path))
    fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    train_experiment_pv_from_replay_samples(
        [{"fen": fen, "side": "black", "move_uci": "e7e5", "target": 1.0, "weight": 1.0}],
        model_path=model_path,
    )

    move = choose_experiment_pv_move({"__fen__": fen}, "black", model_path=model_path, search_profile="fast")
    explanation = explain_experiment_pv_decision(
        {"__fen__": fen},
        "black",
        model_path=model_path,
        search_profile="fast",
        watched_moves=["e7e5", "a7a5"],
    )

    assert f"{move['from']}{move['to']}" == "e7e5"
    assert explanation["chosen_move"] == "e7e5"
    assert explanation["chosen_reason"] == "high_confidence_policy_override"
    assert explanation["policy_override"]["used"] is True
    assert explanation["policy_override"]["margin"] >= explanation["policy_override"]["thresholds"]["min_margin"]
    assert explanation["policy_override"]["reason"] == "adaptive_policy_score_and_margin_met_threshold"
    watched = {row["move"]: row for row in explanation["watched_moves"]}
    assert {"e7e5", "a7a5"} <= set(watched)
    assert "raw_policy_score" in watched["e7e5"]
    assert "static_eval_score" in watched["e7e5"]
    assert "search_score" in watched["e7e5"]
    assert "fused_score" in watched["e7e5"]
    assert "override_applied" in watched["e7e5"]
    assert "override_reason" in watched["e7e5"]
    assert "final_combined_score" in watched["e7e5"]


def test_experiment_pv_rule_aware_fusion_adopts_learned_special_moves(tmp_path, monkeypatch):
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_4_pv.json"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH", str(model_path))
    cases = [
        {
            "fen": "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2N2N2/PPPP1PPP/R1BQK2R w KQkq - 4 5",
            "side": "white",
            "move_uci": "e1g1",
            "rule_type": "castling_short",
        },
        {
            "fen": "rnbqkbnr/pppp1ppp/8/3Pp3/8/8/PPP1PPPP/RNBQKBNR w KQkq e6 0 3",
            "side": "white",
            "move_uci": "d5e6",
            "rule_type": "en_passant",
        },
    ]

    result = train_experiment_pv_from_replay_samples(
        [
            {
                **case,
                "target": 1.0,
                "weight": 3.0,
                "hard_negatives": ["d2d4", "e2e4", "c2c4"],
            }
            for case in cases
        ],
        model_path=model_path,
    )

    assert result["rule_feature_rows_consumed"] == 2
    assert result["rule_feature_breakdown"]["castling_short"] > 0
    assert result["rule_feature_breakdown"]["en_passant"] > 0
    for case in cases:
        move = choose_experiment_pv_move(
            {"__fen__": case["fen"]},
            case["side"],
            model_path=model_path,
            search_profile="fast",
        )
        assert f"{move['from']}{move['to']}{move.get('promotion') or ''}" == case["move_uci"]
        explanation = explain_experiment_pv_decision(
            {"__fen__": case["fen"]},
            case["side"],
            model_path=model_path,
            search_profile="fast",
            watched_moves=[case["move_uci"], "d2d4", "e2e4"],
        )
        assert explanation["chosen_move"] == case["move_uci"]
        assert explanation["chosen_reason"] == "rule_aware_final_fusion_bonus"
        rule_fusion = explanation["rule_aware_fusion"]
        assert rule_fusion["used"] is True
        assert rule_fusion["move"] == case["move_uci"]
        candidate = rule_fusion["candidate"]
        assert candidate["guard_passed"] is True
        assert candidate["raw_policy_rank"] <= 3
        watched = {row["move"]: row for row in explanation["watched_moves"]}
        assert watched[case["move_uci"]]["rule_bonus_after"] > 0
        assert watched[case["move_uci"]]["rule_bonus_guard_passed"] is True


def test_experiment_pv_rule_aware_fusion_locks_policy_override(tmp_path, monkeypatch):
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_4_pv.json"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH", str(model_path))
    fen = "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2N2N2/PPPP1PPP/R1BQK2R w KQkq - 4 5"
    train_experiment_pv_from_replay_samples(
        [
            {
                "fen": fen,
                "side": "white",
                "move_uci": "e1g1",
                "rule_type": "castling_short",
                "target": 1.0,
                "weight": 3.0,
                "hard_negatives": ["d2d4", "e2e4", "c2c4"],
            }
        ],
        model_path=model_path,
    )

    def forbidden_policy_override(*args, **kwargs):
        raise AssertionError("policy override must not run after rule-aware fusion locks a final move")

    monkeypatch.setattr(chess_pv_service, "_policy_override_move", forbidden_policy_override)
    move = choose_experiment_pv_move({"__fen__": fen}, "white", model_path=model_path, search_profile="fast")
    assert f"{move['from']}{move['to']}{move.get('promotion') or ''}" == "e1g1"

    monkeypatch.setattr(
        chess_pv_service,
        "_policy_override_info",
        lambda *args, **kwargs: {
            "used": True,
            "move": "d2d4",
            "raw_policy_score": 1.0,
            "runner_up_move": "e1g1",
            "runner_up_raw_policy_score": 0.99,
            "margin": 0.01,
            "reason": "test_override_should_be_locked",
            "thresholds": {},
        },
    )
    explanation = explain_experiment_pv_decision(
        {"__fen__": fen},
        "white",
        model_path=model_path,
        search_profile="fast",
        watched_moves=["e1g1", "d2d4"],
    )
    assert explanation["chosen_move"] == "e1g1"
    assert explanation["chosen_reason"] == "rule_aware_final_fusion_bonus"
    assert explanation["policy_override"]["used"] is False
    assert explanation["policy_override"]["would_have_used"] is True
    assert explanation["policy_override"]["would_have_move"] == "d2d4"
    assert explanation["policy_override"]["rejected_reason"] == "rule_aware_fusion_locked_final_move"


def test_experiment_pv_rule_aware_fusion_requires_rank_and_search_guard(tmp_path, monkeypatch):
    fen = "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2N2N2/PPPP1PPP/R1BQK2R w KQkq - 4 5"
    board = chess.Board(fen)
    baseline_info = chess_pv_service._rule_aware_final_fusion_info(
        experiment_pv_model_template(),
        board,
        "white",
        chess.Move.from_uci("d2d4"),
    )
    assert baseline_info["used"] is False
    candidate = next(row for row in baseline_info["candidates"] if row["move"] == "e1g1")
    assert candidate["raw_policy_rank"] > 3
    assert candidate["rule_bonus_after"] == 0
    assert candidate["rejection_reason"] == "raw_policy_rank_below_threshold"

    model_path = tmp_path / "runtime" / "models" / "chess_experiment_4_pv.json"
    train_experiment_pv_from_replay_samples(
        [
            {
                "fen": fen,
                "side": "white",
                "move_uci": "e1g1",
                "rule_type": "castling_short",
                "target": 1.0,
                "weight": 3.0,
                "hard_negatives": ["d2d4", "e2e4", "c2c4"],
            }
        ],
        model_path=model_path,
    )
    model = chess_pv_service._load_model(model_path)
    monkeypatch.setattr(
        chess_pv_service,
        "_override_search_guard",
        lambda *args, **kwargs: {
            "rejected": True,
            "reason": "test_decisive_search_disagreement",
            "search_best_move": "d2d4",
            "chosen_search_score": 250,
            "override_search_score": 0,
            "disagreement_cp": 250,
        },
    )
    rejected_info = chess_pv_service._rule_aware_final_fusion_info(
        model,
        board,
        "white",
        chess.Move.from_uci("d2d4"),
    )
    assert rejected_info["used"] is False
    rejected_candidate = next(row for row in rejected_info["candidates"] if row["move"] == "e1g1")
    assert rejected_candidate["guard_passed"] is False
    assert rejected_candidate["rule_bonus_after"] == 0
    assert rejected_candidate["rejection_reason"] == "search_guard:test_decisive_search_disagreement"


def test_experiment_pv_rule_aware_fusion_preserves_special_rule_subtype(tmp_path, monkeypatch):
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_4_pv.json"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH", str(model_path))
    cases = [
        {
            "fen": "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2N2N2/PPPP1PPP/R1BQK2R w KQkq - 4 5",
            "side": "white",
            "move_uci": "e1g1",
            "rule_type": "castling_short",
            "hard_negatives": ["d2d4", "e2e4", "c2c4"],
            "watch": ["e1g1", "d2d4", "e2e4"],
        },
        {
            "fen": "5k2/4P3/5K2/8/8/8/8/8 w - - 0 1",
            "side": "white",
            "move_uci": "e7e8n",
            "rule_type": "promotion_knight_mate",
            "hard_negatives": ["e7e8r", "e7e8q", "e7e8b"],
            "watch": ["e7e8n", "e7e8r", "e7e8q", "e7e8b"],
        },
        {
            "fen": "8/4P3/8/8/8/8/8/4K2k w - - 0 1",
            "side": "white",
            "move_uci": "e7e8q",
            "rule_type": "promotion_queen",
            "hard_negatives": ["e7e8r", "e7e8n", "e7e8b"],
            "watch": ["e7e8q", "e7e8r", "e7e8n", "e7e8b"],
        },
    ]
    train_experiment_pv_from_replay_samples(
        [
            {
                "fen": case["fen"],
                "side": case["side"],
                "move_uci": case["move_uci"],
                "rule_type": case["rule_type"],
                "target": 1.0,
                "weight": 3.0,
                "hard_negatives": case["hard_negatives"],
            }
            for case in cases
        ],
        model_path=model_path,
    )

    for case in cases:
        move = choose_experiment_pv_move(
            {"__fen__": case["fen"]},
            case["side"],
            model_path=model_path,
            search_profile="fixed_depth_fast",
        )
        chosen = f"{move['from']}{move['to']}{move.get('promotion') or ''}"
        explanation = explain_experiment_pv_decision(
            {"__fen__": case["fen"]},
            case["side"],
            model_path=model_path,
            search_profile="fixed_depth_fast",
            watched_moves=case["watch"],
        )
        assert chosen == case["move_uci"]
        assert explanation["chosen_move"] == case["move_uci"]
        assert explanation["chosen_reason"] in {"rule_aware_final_fusion_bonus", "opening_sanity_fallback", "search_best_move"}
        candidate = explanation["rule_aware_fusion"]["candidate"]
        if explanation["chosen_reason"] == "rule_aware_final_fusion_bonus":
            assert candidate["move"] == case["move_uci"]
            assert candidate["rule_family"] in {"castling", "promotion"}
            assert candidate["raw_policy_rank"] == 1


def test_experiment_pv_choose_and_explain_special_rule_consistency(tmp_path, monkeypatch):
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_4_pv.json"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH", str(model_path))
    cases = [
        {
            "fen": "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2N2N2/PPPP1PPP/R1BQK2R w KQkq - 4 5",
            "side": "white",
            "move_uci": "e1g1",
            "rule_type": "castling_short",
            "hard_negatives": ["d2d4", "e2e4", "c2c4"],
        },
        {
            "fen": "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2N2N2/PPPP1PPP/R1BQK2R b kq - 4 5",
            "side": "black",
            "move_uci": "e8g8",
            "rule_type": "castling_short",
            "hard_negatives": ["d7d5", "e7e5", "c7c5"],
        },
        {
            "fen": "rnbqkbnr/pppp1ppp/8/3Pp3/8/8/PPP1PPPP/RNBQKBNR w KQkq e6 0 3",
            "side": "white",
            "move_uci": "d5e6",
            "rule_type": "en_passant",
            "hard_negatives": ["e2e4"],
        },
        {
            "fen": "8/4P3/8/8/8/8/8/4K2k w - - 0 1",
            "side": "white",
            "move_uci": "e7e8q",
            "rule_type": "promotion_queen",
            "hard_negatives": ["e7e8r", "e7e8n", "e7e8b"],
        },
    ]
    train_experiment_pv_from_replay_samples(
        [
            {
                "fen": case["fen"],
                "side": case["side"],
                "move_uci": case["move_uci"],
                "rule_type": case["rule_type"],
                "target": 1.0,
                "weight": 3.0,
                "hard_negatives": case["hard_negatives"],
            }
            for case in cases
        ],
        model_path=model_path,
    )

    for case in cases:
        move = choose_experiment_pv_move(
            {"__fen__": case["fen"]},
            case["side"],
            model_path=model_path,
            search_profile="fixed_depth_fast",
        )
        chosen = f"{move['from']}{move['to']}{move.get('promotion') or ''}"
        explanation = explain_experiment_pv_decision(
            {"__fen__": case["fen"]},
            case["side"],
            model_path=model_path,
            search_profile="fixed_depth_fast",
            watched_moves=[case["move_uci"]],
        )
        assert chosen == explanation["chosen_move"] == case["move_uci"]


def test_experiment_pv_mcts_decision_explain_reports_root_stats(tmp_path, monkeypatch):
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_4_pv.json"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH", str(model_path))
    fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    train_experiment_pv_from_replay_samples(
        [{"fen": fen, "side": "black", "move_uci": "e7e5", "target": 1.0, "weight": 1.0}],
        model_path=model_path,
    )

    explanation = explain_experiment_pv_decision(
        {"__fen__": fen},
        "black",
        model_path=model_path,
        search_profile="fast",
        watched_moves=["e7e5", "a7a5"],
        decision_mode="mcts",
    )

    assert explanation["decision_mode"] == "mcts"
    assert explanation["mcts"]["simulations"] > 0
    assert explanation["mcts"]["stats"]
    watched = {row["move"]: row for row in explanation["watched_moves"]}
    assert "mcts_prior" in watched["e7e5"]
    assert "mcts_visit_count" in watched["e7e5"]
    assert "mcts_q_value" in watched["e7e5"]


def test_experiment_pv_resign_collects_replay_without_mutating_model(tmp_path, monkeypatch):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_4_pv.json"
    replay_path = tmp_path / "runtime" / "reports" / "games" / "chess_replays.jsonl"
    rejected_path = tmp_path / "runtime" / "reports" / "games" / "chess_replays_rejected.jsonl"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH", str(model_path))
    monkeypatch.setenv("HTML_LEARNING_CHESS_REPLAY_BUFFER_PATH", str(replay_path))
    monkeypatch.setenv("HTML_LEARNING_CHESS_REPLAY_REJECTED_PATH", str(rejected_path))
    app = _build_app(db_path, actor_box, chess_engine_store=_build_chess_engine_store(tmp_path))
    client = app.test_client()

    created = client.post("/api/games/chess/practice", json={"difficulty": "experiment 4:pv", "side": "black"})
    assert created.status_code == 200
    match_id = created.get_json()["match_id"]
    model_before = model_path.read_text(encoding="utf-8") if model_path.exists() else None

    resigned = client.post(f"/api/games/chess/matches/{match_id}/resign", json={})
    assert resigned.status_code == 200
    if model_before is None:
        assert not model_path.exists()
    else:
        assert model_path.read_text(encoding="utf-8") == model_before
    replay = json.loads(rejected_path.read_text(encoding="utf-8").strip())
    assert replay["engine_name"] == "experiment 4:pv"
    assert replay["collection_tier"] == "rejected"


def test_user_game_with_varied_moves_can_enter_trusted_replay_buffer(tmp_path, monkeypatch):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user"}}
    trusted_path = tmp_path / "runtime" / "reports" / "games" / "chess_replays.jsonl"
    quarantine_path = tmp_path / "runtime" / "reports" / "games" / "chess_replays_quarantine.jsonl"
    rejected_path = tmp_path / "runtime" / "reports" / "games" / "chess_replays_rejected.jsonl"
    monkeypatch.setenv("HTML_LEARNING_CHESS_REPLAY_BUFFER_PATH", str(trusted_path))
    monkeypatch.setenv("HTML_LEARNING_CHESS_REPLAY_QUARANTINE_PATH", str(quarantine_path))
    monkeypatch.setenv("HTML_LEARNING_CHESS_REPLAY_REJECTED_PATH", str(rejected_path))
    app = _build_app(db_path, actor_box, chess_engine_store=_build_chess_engine_store(tmp_path))
    client = app.test_client()

    created = client.post("/api/games/chess/practice", json={"difficulty": "experiment 4:pv", "side": "black"})
    assert created.status_code == 200
    match_id = created.get_json()["match_id"]
    match = client.get(f"/api/games/chess/matches/{match_id}").get_json()["match"]
    preferred_ucis = ["g8f6", "e7e6", "f8e7", "e8g8"]
    for preferred in preferred_ucis:
        options = legal_moves(match["board"], match["current_turn"])
        move = next((cand for cand in options if f"{cand['from']}{cand['to']}{cand.get('promotion') or ''}" == preferred), options[0])
        moved = client.post(
            f"/api/games/chess/matches/{match_id}/move",
            json={"from": move["from"], "to": move["to"], "promotion": move.get("promotion")},
        )
        assert moved.status_code == 200
        match = moved.get_json()["match"]

    resigned = client.post(f"/api/games/chess/matches/{match_id}/resign", json={})
    assert resigned.status_code == 200

    assert trusted_path.exists()
    record = json.loads(trusted_path.read_text(encoding="utf-8").strip())
    assert record["engine_name"] == "experiment 4:pv"
    assert record["collection_tier"] == "trusted"
    assert record["suspicious_flag"] is False
    assert record["quarantine_reasons"] == []
    assert not quarantine_path.exists()
    assert not rejected_path.exists()


def test_replay_classification_quarantines_duplicate_and_short_user_games(tmp_path):
    base_record = {
        "source": "user_games",
        "move_count": 5,
        "suspicious_flag": False,
        "resign_abuse_flag": False,
        "duplicate_signature": "sig-1",
    }
    duplicate = classify_replay_record(dict(base_record), existing_signatures={"sig-1"})
    assert duplicate["collection_tier"] == "quarantine"
    assert duplicate["duplicate_flag"] is True
    assert "duplicate" in duplicate["quarantine_reasons"]
    assert "low_move_count" in duplicate["quarantine_reasons"]

    trusted = classify_replay_record(
        {
            "source": "teacher_guidance",
            "move_count": 18,
            "suspicious_flag": False,
            "resign_abuse_flag": False,
            "duplicate_signature": "sig-2",
        },
        existing_signatures=set(),
    )
    assert trusted["collection_tier"] == "trusted"
    assert trusted["duplicate_flag"] is False


def test_replay_buffer_summary_tracks_trusted_quarantine_and_rejected(tmp_path):
    trusted_path = tmp_path / "runtime" / "reports" / "games" / "chess_replays.jsonl"
    quarantine_path = tmp_path / "runtime" / "reports" / "games" / "chess_replays_quarantine.jsonl"
    rejected_path = tmp_path / "runtime" / "reports" / "games" / "chess_replays_rejected.jsonl"
    trusted_path.parent.mkdir(parents=True, exist_ok=True)
    trusted_path.write_text(
        json.dumps({"source": "user_games", "timestamp": "2026-05-08T00:00:00Z", "duplicate_flag": False, "resign_abuse_flag": False, "suspicious_flag": False, "quarantine_reasons": []}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    quarantine_path.write_text(
        json.dumps({"source": "user_games", "timestamp": "2026-05-08T00:00:01Z", "duplicate_flag": True, "resign_abuse_flag": True, "suspicious_flag": True, "quarantine_reasons": ["duplicate", "early_resign"]}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    rejected_path.write_text(
        json.dumps({"source": "user_games", "timestamp": "2026-05-08T00:00:02Z", "duplicate_flag": False, "resign_abuse_flag": False, "suspicious_flag": True, "quarantine_reasons": ["empty_history"]}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    summary = replay_buffer_summary(path=trusted_path, quarantine_path=quarantine_path, rejected_path=rejected_path)

    assert summary["total_replays"] == 3
    assert summary["usable_replays"] == 1
    assert summary["trusted_replays"] == 1
    assert summary["quarantine_replays"] == 1
    assert summary["rejected_replays"] == 1
    assert summary["duplicate_count"] == 1
    assert summary["resign_abuse_count"] == 1
    assert summary["quarantine_reasons"]["duplicate"] == 1
    assert summary["quarantine_reasons"]["empty_history"] == 1


def test_experiment_pv_move_finds_mate_in_one(tmp_path, monkeypatch):
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_4_pv.json"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH", str(model_path))
    board = {"__fen__": "6k1/5Q2/6K1/8/8/8/8/8 w - - 0 1"}

    move = choose_experiment_pv_move(board, "white", model_path=model_path)

    assert move is not None
    chosen_uci = f"{move['from']}{move['to']}{move.get('promotion') or ''}"
    board_obj = chess.Board(board["__fen__"])
    board_obj.push(chess.Move.from_uci(chosen_uci))
    assert board_obj.is_checkmate()


def test_experiment_pv_move_returns_legal_move_on_fresh_model(tmp_path, monkeypatch):
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_4_pv.json"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH", str(model_path))
    board = initial_board()

    move = choose_experiment_pv_move(board, "white", model_path=model_path)

    assert move is not None
    applied = validate_move(board, "white", move["from"], move["to"], move.get("promotion"))
    assert isinstance(applied["board"], dict)


def test_experiment_pv_avoids_early_rook_shuffle_after_edge_pawn(tmp_path, monkeypatch):
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_4_pv.json"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH", str(model_path))
    board = chess.Board()
    for uci in ("a2a4", "g8f6"):
        board.push(chess.Move.from_uci(uci))

    move = choose_experiment_pv_move({"__fen__": board.fen()}, "white", model_path=model_path)

    assert move is not None
    assert move["from"] != "a1"
    applied = validate_move({"__fen__": board.fen()}, "white", move["from"], move["to"], move.get("promotion"))
    assert isinstance(applied["board"], dict)


def test_experiment_pv_avoids_repeating_rook_wander_in_opening(tmp_path, monkeypatch):
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_4_pv.json"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH", str(model_path))
    board = chess.Board()
    for uci in ("a2a4", "g8f6", "a1a3", "e7e5"):
        board.push(chess.Move.from_uci(uci))

    move = choose_experiment_pv_move({"__fen__": board.fen()}, "white", model_path=model_path)

    assert move is not None
    assert move["from"] != "a3"
    applied = validate_move({"__fen__": board.fen()}, "white", move["from"], move["to"], move.get("promotion"))
    assert isinstance(applied["board"], dict)


def test_experiment_move_avoids_early_rook_shuffle_after_edge_pawn(tmp_path):
    board = chess.Board()
    for uci in ("a2a4", "g8f6"):
        board.push(chess.Move.from_uci(uci))

    move = choose_experiment_move({"__fen__": board.fen()}, "white", store=ChessExperimentStore(tmp_path / "exp1.db"))

    assert move is not None
    assert move["from"] != "a1"
    applied = validate_move({"__fen__": board.fen()}, "white", move["from"], move["to"], move.get("promotion"))
    assert isinstance(applied["board"], dict)


def test_search_best_move_restores_root_board_on_exception():
    board = chess.Board()
    original_fen = board.fen()

    def exploding_eval(_board):
        raise RuntimeError("boom")

    try:
        search_best_move(
            board,
            max_depth=2,
            evaluate=exploding_eval,
            move_order_fn=lambda current_board, move, _ply: 1 if current_board.is_capture(move) else 0,
            hasher=ZobristHasher(seed=20260518),
            time_budget_ms=250,
        )
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("search_best_move should propagate the injected failure")

    assert board.fen() == original_fen


def test_experiment_move_stays_legal_on_timeout_prone_position(tmp_path):
    fen = "rnbqkbn1/pp2ppp1/2pp3B/8/P2PP2p/8/RPP2PPP/1N1QKBNR w Kq - 0 6"

    move = choose_experiment_move({"__fen__": fen}, "white", store=ChessExperimentStore(tmp_path / "exp1.db"), search_profile="fast")

    assert move is not None
    applied = validate_move({"__fen__": fen}, "white", move["from"], move["to"], move.get("promotion"))
    assert isinstance(applied["board"], dict)


def test_experiment_dl_move_avoids_early_rook_shuffle_after_edge_pawn(tmp_path, monkeypatch):
    model_path = tmp_path / "runtime" / "models" / "chess_experiment_3_dl.json"
    monkeypatch.setenv("HTML_LEARNING_CHESS_ENGINE_DL_MODEL_PATH", str(model_path))
    board = chess.Board()
    for uci in ("a2a4", "g8f6"):
        board.push(chess.Move.from_uci(uci))

    move = choose_experiment_dl_move({"__fen__": board.fen()}, "white", model_path=model_path)

    assert move is not None
    assert move["from"] != "a1"
    applied = validate_move({"__fen__": board.fen()}, "white", move["from"], move["to"], move.get("promotion"))
    assert isinstance(applied["board"], dict)


def test_root_chess_engine_dashboard_reports_warm_start_and_replay_summary(tmp_path, monkeypatch):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    replay_path = tmp_path / "runtime" / "reports" / "games" / "chess_replays.jsonl"
    monkeypatch.setenv("HACKME_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("HTML_LEARNING_CHESS_REPLAY_BUFFER_PATH", str(replay_path))
    app = _build_app(db_path, actor_box, chess_engine_store=_build_chess_engine_store(tmp_path))
    client = app.test_client()

    response = client.get("/api/root/games/chess/engines/dashboard")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["warm_start"]["ok"] is True
    assert any(row["engine"] == "experiment 4:pv" for row in payload["production_models"])
    assert any(row["engine"] == "experiment 5:nnue" for row in payload["production_models"])
    assert payload["replay_buffer"]["total_replays"] == 0
    assert payload["pipeline"]["train_path"].endswith("train.jsonl")
    assert "chess_replay_prepare.py" in payload["pipeline"]["commands"]["prepare"]
    assert "chess_seed_train.py" in payload["pipeline"]["commands"]["seed_train"]
    assert "chess_train_pipeline.py" in payload["pipeline"]["commands"]["full_pipeline"]
    assert payload["pipeline_recommendation"]["ready"] is False
    assert "no usable replays yet" in payload["pipeline_recommendation"]["blocked_reasons"]
    assert payload["pipeline_autorun"]["exists"] is False
    assert Path(payload["promotion"]["path"]).name == "chess_promotion_status.json"
    runtime_models = tmp_path / "runtime" / "games" / "models"
    assert (runtime_models / bundled_chess_engine_db_path().name).exists()
    assert (runtime_models / bundled_chess_nn_model_path().name).exists()
    assert (runtime_models / bundled_chess_dl_model_path().name).exists()
    assert (runtime_models / bundled_chess_pv_model_path().name).exists()
    artifacts = {row["engine"]: row for row in payload["warm_start"]["artifacts"]}
    assert artifacts["experiment"]["source"] in {"bundled_seed", "runtime_existing", "schema_fallback"}
    assert artifacts["experiment 2:nn"]["source"] in {"bundled_seed", "runtime_existing", "template_fallback"}


def test_root_chess_warm_start_does_not_overwrite_existing_exp1_runtime_db(tmp_path, monkeypatch):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    runtime_dir = tmp_path / "runtime"
    runtime_exp1 = runtime_dir / "games" / "models" / bundled_chess_engine_db_path().name
    runtime_exp1.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(runtime_exp1)
    conn.row_factory = sqlite3.Row
    ensure_chess_engine_schema(conn)
    conn.execute(
        """
        INSERT INTO game_chess_engine_memory (
            position_key, side, move_uci, sample_count, win_count, draw_count, loss_count, score_total, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("test-position", "white", "a2a3", 1, 1, 0, 0, 1, "2026-05-08T00:00:00Z"),
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("HACKME_RUNTIME_DIR", str(runtime_dir))
    app = _build_app(db_path, actor_box, chess_engine_store=ChessExperimentStore(runtime_exp1))
    client = app.test_client()

    response = client.get("/api/root/games/chess/engines/dashboard")
    assert response.status_code == 200
    payload = response.get_json()
    artifacts = {row["engine"]: row for row in payload["warm_start"]["artifacts"]}
    assert artifacts["experiment"]["source"] == "runtime_existing"

    conn = sqlite3.connect(runtime_exp1)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT move_uci, sample_count FROM game_chess_engine_memory WHERE position_key=?",
            ("test-position",),
        ).fetchone()
        assert row["move_uci"] == "a2a3"
        assert row["sample_count"] == 1
    finally:
        conn.close()


def _write_pipeline_ready_replay(runtime_dir: Path) -> None:
    replay_path = runtime_dir / "reports" / "games" / "chess_replays.jsonl"
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    replay_path.write_text(
        json.dumps(
            {
                "source": "user_games",
                "engine_name": "experiment 4:pv",
                "engine_version": "experiment 4:pv",
                "white_engine": "experiment 4:pv",
                "black_engine": "user",
                "opening_seed": "standard_start",
                "result": "white",
                "winner_color": "white",
                "adjudicated_or_natural": "natural",
                "move_count": 18,
                "timestamp": "2026-05-09T12:27:08.354707Z",
                "rating_estimate": None,
                "suspicious_flag": False,
                "duplicate_flag": False,
                "resign_abuse_flag": False,
                "confidence_score": 0.42,
                "collection_tier": "trusted",
                "quarantine_reasons": [],
                "replay_id": "autorun-test-replay",
                "move_history": [
                    {"by": "white", "from": "e2", "to": "e4"},
                    {"by": "black", "from": "e7", "to": "e5"},
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def test_pipeline_autorun_disabled_by_default_preserves_replay_summary(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_pipeline_ready_replay(runtime_dir)
    monkeypatch.setenv("HACKME_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("HTML_LEARNING_CHESS_RETRAIN_MIN_REPLAYS", "1")
    monkeypatch.delenv("HTML_LEARNING_CHESS_AUTORETRAIN_ENABLED", raising=False)
    monkeypatch.delenv("HTML_LEARNING_CHESS_PIPELINE_AUTORUN_ENABLED", raising=False)

    def _unexpected_popen(*args, **kwargs):
        raise AssertionError("auto-retrain must remain disabled by default")

    monkeypatch.setattr(chess_pipeline_service.subprocess, "Popen", _unexpected_popen)

    result = chess_pipeline_service.maybe_launch_chess_train_pipeline(trigger="test_suite", actor_username="root")

    assert result["ok"] is True
    assert result["launched"] is False
    assert result["reason"] == chess_pipeline_service.AUTO_RETRAIN_DISABLED_REASON
    assert result["recommendation"]["ready"] is True
    assert result["recommendation"]["usable_replays"] == 1
    assert result["recommendation"]["auto_retrain_enabled"] is False
    assert result["status"]["auto_retrain_enabled"] is False
    assert result["status"]["disabled_reason"] == chess_pipeline_service.AUTO_RETRAIN_DISABLED_REASON


def test_pipeline_autorun_starts_when_replay_threshold_is_met(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_pipeline_ready_replay(runtime_dir)
    monkeypatch.setenv("HACKME_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("HTML_LEARNING_CHESS_RETRAIN_MIN_REPLAYS", "1")
    monkeypatch.setenv("HTML_LEARNING_CHESS_AUTORETRAIN_ENABLED", "1")
    monkeypatch.setenv("HTML_LEARNING_CHESS_AUTORUN_SKIP_BENCHMARK", "1")
    monkeypatch.setenv("HTML_LEARNING_CHESS_AUTORUN_SKIP_PROMOTE", "1")

    popen_calls = []

    class _FakeProc:
        pid = 424242

        def wait(self):
            return 0

    class _ImmediateThread:
        def __init__(self, *, target=None, name=None, daemon=None):
            self._target = target

        def start(self):
            if self._target is not None:
                self._target()

    def _fake_popen(command, **kwargs):
        popen_calls.append({"command": list(command), **kwargs})
        return _FakeProc()

    monkeypatch.setattr(chess_pipeline_service.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(chess_pipeline_service.threading, "Thread", _ImmediateThread)

    result = chess_pipeline_service.maybe_launch_chess_train_pipeline(trigger="test_suite", actor_username="root")

    assert result["ok"] is True
    assert result["launched"] is True
    assert popen_calls
    assert "--include-quarantine" in popen_calls[0]["command"]
    assert "--min-usable-replays" in popen_calls[0]["command"]
    assert "--skip-benchmark" in popen_calls[0]["command"]
    assert "--skip-promote" in popen_calls[0]["command"]

    status = chess_pipeline_service.latest_pipeline_autorun_status()
    assert status["exists"] is True
    assert status["status"] == "passed"
    assert status["returncode"] == 0
    assert "--skip-benchmark" in status["recommendation"]["recommended_command"]
    assert "--skip-promote" in status["recommendation"]["recommended_command"]


def test_chess_pipeline_targeted_autorun_command_only_trains_requested_engine():
    try:
        chess_pipeline_service._pipeline_command_args(min_usable_replays=10, target_engines=["experiment 2:nn"])
    except ValueError as exc:
        assert "unknown chess pipeline target engine" in str(exc)
    else:
        raise AssertionError("exp2 should be removed from retrain pipeline targets")

    exp3_args = chess_pipeline_service._pipeline_command_args(min_usable_replays=10, target_engines=["experiment 3:dl"])
    assert "--include-exp2" not in exp3_args
    assert "--skip-exp1-refine" in exp3_args
    assert "--skip-exp3" not in exp3_args
    assert "--skip-exp4" in exp3_args
    assert exp3_args[exp3_args.index("--promote-engines") + 1] == "experiment 3:dl"


def test_root_chess_promotion_stage_and_promote(tmp_path, monkeypatch):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    runtime_dir = tmp_path / "runtime"
    benchmark_report = runtime_dir / "reports" / "games" / "fake_benchmark.json"
    benchmark_report.parent.mkdir(parents=True, exist_ok=True)
    benchmark_report.write_text(
        json.dumps(
            {
                "smoke_evaluation": {"pass": True, "games_played": 8, "suspicious_matches": []},
                "benchmark": {
                    "standings": [
                        {
                            "engine": "experiment 4:pv",
                            "score_rate": 0.62,
                            "win_rate": 0.41,
                            "games": 12,
                            "draws": 3,
                        }
                    ],
                    "suspicious_matches": [],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    candidate_source = tmp_path / "candidate_exp4.json"
    candidate_source.write_text(json.dumps(experiment_pv_model_template(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("HACKME_RUNTIME_DIR", str(runtime_dir))
    app = _build_app(db_path, actor_box, chess_engine_store=_build_chess_engine_store(tmp_path))
    client = app.test_client()

    staged = client.post(
        "/api/root/games/chess/promotion/stage",
        json={
            "engine": "experiment 4:pv",
            "source_path": str(candidate_source),
            "benchmark_report_path": str(benchmark_report),
        },
    )
    assert staged.status_code == 200
    staged_payload = staged.get_json()
    assert staged_payload["ok"] is True

    promoted = client.post(
        "/api/root/games/chess/promotion/promote",
        json={
            "engine": "experiment 4:pv",
            "benchmark_report_path": str(benchmark_report),
        },
    )
    assert promoted.status_code == 200
    promoted_payload = promoted.get_json()
    assert promoted_payload["ok"] is True
    production_path = Path(promoted_payload["production_path"])
    assert production_path.exists()
    assert production_path.read_text(encoding="utf-8") == candidate_source.read_text(encoding="utf-8")

    status_response = client.get("/api/root/games/chess/promotion/status")
    assert status_response.status_code == 200
    status_payload = status_response.get_json()["promotion"]["status"]
    assert status_payload["last_promotion_result"]["engine"] == "experiment 4:pv"
    assert status_payload["candidate"] is None


def test_chess_warm_start_does_not_overwrite_existing_runtime_model(tmp_path):
    bundled = tmp_path / "services" / "games" / "models" / "seed.json"
    runtime = tmp_path / "runtime" / "games" / "models" / "model.json"
    bundled.parent.mkdir(parents=True)
    runtime.parent.mkdir(parents=True)
    bundled.write_text('{"source":"bundle"}\n', encoding="utf-8")
    runtime.write_text('{"source":"runtime_retrained"}\n', encoding="utf-8")

    result = ensure_runtime_model_from_bundle(runtime, bundled)

    assert result["ok"] is True
    assert result["source"] == "runtime_existing"
    assert result["copied"] is False
    assert runtime.read_text(encoding="utf-8") == '{"source":"runtime_retrained"}\n'
    assert bundled.read_text(encoding="utf-8") == '{"source":"bundle"}\n'


def test_root_chess_promotion_gate_blocks_weak_candidate(tmp_path, monkeypatch):
    db_path = tmp_path / "games.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    runtime_dir = tmp_path / "runtime"
    benchmark_report = runtime_dir / "reports" / "games" / "weak_benchmark.json"
    benchmark_report.parent.mkdir(parents=True, exist_ok=True)
    benchmark_report.write_text(
        json.dumps(
            {
                "smoke_evaluation": {"pass": False, "games_played": 4, "suspicious_matches": [{}]},
                "benchmark": {
                    "standings": [
                        {
                            "engine": "experiment 4:pv",
                            "score_rate": 0.2,
                            "win_rate": 0.1,
                            "games": 4,
                            "draws": 4,
                        }
                    ],
                    "suspicious_matches": [{}],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    candidate_source = tmp_path / "candidate_exp4_bad.json"
    candidate_source.write_text(json.dumps(experiment_pv_model_template(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("HACKME_RUNTIME_DIR", str(runtime_dir))
    app = _build_app(db_path, actor_box, chess_engine_store=_build_chess_engine_store(tmp_path))
    client = app.test_client()

    staged = client.post(
        "/api/root/games/chess/promotion/stage",
        json={
            "engine": "experiment 4:pv",
            "source_path": str(candidate_source),
            "benchmark_report_path": str(benchmark_report),
        },
    )
    assert staged.status_code == 200

    promoted = client.post(
        "/api/root/games/chess/promotion/promote",
        json={
            "engine": "experiment 4:pv",
            "benchmark_report_path": str(benchmark_report),
        },
    )
    assert promoted.status_code == 400
    assert "promotion gate failed" in promoted.get_json()["msg"]


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
