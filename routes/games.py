import json
import random
from datetime import datetime, timedelta, timezone

from flask import request

from services.chess_game import (
    board_rows,
    game_status,
    initial_board,
    legal_moves,
    opponent,
    validate_move,
)
from services.points_chain import DISPLAY_CURRENCY

GAME_KEY = "chess"
SOLO_GAME_KEYS = {"sudoku", "minesweeper"}
WEEKLY_REWARDS = (300, 200, 100)
COMPUTER_DIFFICULTIES = {"easy", "normal", "hard"}
MINESWEEPER_DIFFICULTIES = {"easy", "normal", "hard"}
PIECE_VALUES = {
    "p": 100,
    "n": 320,
    "b": 330,
    "r": 500,
    "q": 900,
    "k": 20000,
}


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def current_week_key(now=None):
    now = now or datetime.now(timezone.utc)
    year, week, _weekday = now.isocalendar()
    return f"{int(year)}-W{int(week):02d}"


def completed_week_start(week_key):
    year_part, week_part = str(week_key).split("-W", 1)
    return datetime.fromisocalendar(int(year_part), int(week_part), 1).replace(tzinfo=timezone.utc)


def default_board_json():
    return json.dumps(initial_board(), ensure_ascii=False, sort_keys=True)


def normalize_computer_difficulty(value):
    difficulty = str(value or "easy").strip().lower()
    return difficulty if difficulty in COMPUTER_DIFFICULTIES else None


def move_material_value(move):
    captured = str(move.get("captured") or "").lower()
    promotion = str(move.get("promotion") or "").lower()
    score = PIECE_VALUES.get(captured, 0)
    if promotion:
        score += max(0, PIECE_VALUES.get(promotion, 0) - PIECE_VALUES["p"])
    return score


def choose_computer_move(board, side, difficulty="easy"):
    moves = legal_moves(board, side)
    if not moves:
        return None
    difficulty = normalize_computer_difficulty(difficulty) or "easy"
    if difficulty == "easy":
        return random.choice(moves)

    scored = []
    for move in moves:
        try:
            applied = validate_move(board, side, move["from"], move["to"], move.get("promotion"))
        except ValueError:
            continue
        next_board = applied["board"]
        status = game_status(next_board, opponent(side))
        score = move_material_value(move)
        if status["status"] == "finished" and status.get("winner_color") == side:
            score += 100000
        elif status.get("reason") == "check":
            score += 60

        if difficulty == "hard" and status["status"] == "active":
            reply_scores = []
            for reply in legal_moves(next_board, opponent(side)):
                try:
                    reply_applied = validate_move(next_board, opponent(side), reply["from"], reply["to"], reply.get("promotion"))
                except ValueError:
                    continue
                reply_score = move_material_value(reply)
                reply_status = game_status(reply_applied["board"], side)
                if reply_status["status"] == "finished" and reply_status.get("winner_color") == opponent(side):
                    reply_score += 100000
                reply_scores.append(reply_score)
            if reply_scores:
                score -= max(reply_scores)
        scored.append((score, move))

    if not scored:
        return random.choice(moves)
    best_score = max(score for score, _move in scored)
    best_moves = [move for score, move in scored if score == best_score]
    return random.choice(best_moves)


def load_board(row):
    try:
        data = json.loads(row["board_json"] or "{}")
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def load_history(row):
    try:
        data = json.loads(row["move_history_json"] or "[]")
    except Exception:
        data = []
    return data if isinstance(data, list) else []


def game_schema_sql():
    return """
    CREATE TABLE IF NOT EXISTS game_matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_key TEXT NOT NULL,
        mode TEXT NOT NULL DEFAULT 'pvp',
        status TEXT NOT NULL DEFAULT 'active',
        white_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        black_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        human_side TEXT NOT NULL DEFAULT 'white',
        computer_difficulty TEXT NOT NULL DEFAULT 'easy',
        current_turn TEXT NOT NULL DEFAULT 'white',
        board_json TEXT NOT NULL,
        move_history_json TEXT NOT NULL DEFAULT '[]',
        winner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        result_reason TEXT,
        leaderboard_week TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        finished_at TEXT,
        CHECK (game_key IN ('chess')),
        CHECK (mode IN ('pvp', 'computer')),
        CHECK (status IN ('active', 'finished', 'cancelled')),
        CHECK (current_turn IN ('white', 'black')),
        CHECK (human_side IN ('white', 'black')),
        CHECK (computer_difficulty IN ('easy', 'normal', 'hard'))
    );
    CREATE TABLE IF NOT EXISTS game_invites (
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
    CREATE TABLE IF NOT EXISTS game_leaderboard_rewards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_key TEXT NOT NULL,
        week_key TEXT NOT NULL,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        rank INTEGER NOT NULL,
        score INTEGER NOT NULL,
        reward_points INTEGER NOT NULL,
        ledger_uuid TEXT,
        awarded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL,
        UNIQUE(game_key, week_key, user_id)
    );
    CREATE TABLE IF NOT EXISTS game_solo_scores (
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
    CREATE INDEX IF NOT EXISTS idx_game_matches_players ON game_matches(game_key, status, white_user_id, black_user_id);
    CREATE INDEX IF NOT EXISTS idx_game_matches_finished ON game_matches(game_key, mode, finished_at);
    CREATE INDEX IF NOT EXISTS idx_game_invites_user_status ON game_invites(game_key, opponent_user_id, status);
    CREATE INDEX IF NOT EXISTS idx_game_rewards_week ON game_leaderboard_rewards(game_key, week_key);
    CREATE INDEX IF NOT EXISTS idx_game_solo_scores_rank ON game_solo_scores(game_key, week_key, difficulty, elapsed_ms);
    """


def ensure_game_schema(conn):
    conn.executescript(game_schema_sql())
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(game_matches)").fetchall()}
    if "white_deleted_at" not in cols:
        conn.execute("ALTER TABLE game_matches ADD COLUMN white_deleted_at TEXT")
    if "black_deleted_at" not in cols:
        conn.execute("ALTER TABLE game_matches ADD COLUMN black_deleted_at TEXT")
    if "human_side" not in cols:
        conn.execute("ALTER TABLE game_matches ADD COLUMN human_side TEXT NOT NULL DEFAULT 'white'")
    if "computer_difficulty" not in cols:
        conn.execute("ALTER TABLE game_matches ADD COLUMN computer_difficulty TEXT NOT NULL DEFAULT 'easy'")


def serialize_match(row, actor_id=None):
    board = load_board(row)
    history = load_history(row)
    side = None
    human_side = row["human_side"] if "human_side" in row.keys() else "white"
    computer_difficulty = row["computer_difficulty"] if "computer_difficulty" in row.keys() else "easy"
    if actor_id:
        if row["mode"] == "computer" and int(row["white_user_id"]) == int(actor_id):
            side = human_side
        elif int(row["white_user_id"]) == int(actor_id):
            side = "white"
        elif row["black_user_id"] and int(row["black_user_id"]) == int(actor_id):
            side = "black"
    white_username = row["white_username"]
    black_username = row["black_username"] or ("電腦" if row["mode"] == "computer" else "-")
    if row["mode"] == "computer" and human_side == "black":
        white_username = "電腦"
        black_username = row["white_username"]
    return {
        "id": row["id"],
        "game_key": row["game_key"],
        "mode": row["mode"],
        "status": row["status"],
        "white_user_id": row["white_user_id"],
        "white_username": white_username,
        "black_user_id": row["black_user_id"],
        "black_username": black_username,
        "human_side": human_side,
        "computer_difficulty": computer_difficulty,
        "current_turn": row["current_turn"],
        "board": board,
        "board_rows": board_rows(board),
        "move_history": history,
        "winner_user_id": row["winner_user_id"],
        "winner_username": row["winner_username"],
        "result_reason": row["result_reason"] or "",
        "my_side": side,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "finished_at": row["finished_at"],
        "legal_moves": legal_moves(board, row["current_turn"]) if row["status"] == "active" else [],
    }


def match_select_sql(where):
    return f"""
        SELECT m.*,
               wu.username AS white_username,
               bu.username AS black_username,
               win.username AS winner_username
        FROM game_matches m
        JOIN users wu ON wu.id=m.white_user_id
        LEFT JOIN users bu ON bu.id=m.black_user_id
        LEFT JOIN users win ON win.id=m.winner_user_id
        WHERE {where}
    """


def serialize_invite(row):
    return {
        "id": row["id"],
        "game_key": row["game_key"],
        "status": row["status"],
        "inviter_user_id": row["inviter_user_id"],
        "inviter_username": row["inviter_username"],
        "opponent_user_id": row["opponent_user_id"],
        "opponent_username": row["opponent_username"],
        "match_id": row["match_id"],
        "message": row["message"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "expires_at": row["expires_at"],
    }


def finish_match(conn, row, status_info, now):
    winner_color = status_info.get("winner_color")
    winner_user_id = None
    human_side = row["human_side"] if "human_side" in row.keys() else "white"
    if row["mode"] == "computer":
        if winner_color == human_side:
            winner_user_id = row["white_user_id"]
    elif winner_color == "white":
        winner_user_id = row["white_user_id"]
    elif winner_color == "black":
        winner_user_id = row["black_user_id"]
    week = current_week_key(datetime.fromisoformat(now.replace("Z", "+00:00")))
    conn.execute(
        """
        UPDATE game_matches
        SET status='finished', winner_user_id=?, result_reason=?, leaderboard_week=?, finished_at=?, updated_at=?
        WHERE id=?
        """,
        (winner_user_id, status_info.get("reason") or "draw", week, now, now, row["id"]),
    )


def register_games_routes(app, deps):
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_db = deps["get_db"]
    json_resp = deps["json_resp"]
    require_csrf = deps["require_csrf"]
    require_csrf_safe = deps["require_csrf_safe"]
    points_service = deps.get("points_service")
    audit = deps.get("audit", lambda *args, **kwargs: None)
    get_client_ip = deps.get("get_client_ip", lambda: "")
    get_ua = deps.get("get_ua", lambda: "")

    def actor_or_401():
        actor = get_current_user_ctx()
        if not actor:
            return None, json_resp({"ok": False, "msg": "未登入"}), 401
        return actor, None, None

    def parse_json_body():
        try:
            data = request.get_json(force=True)
        except Exception:
            return None, json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        if not isinstance(data, dict):
            return None, json_resp({"ok": False, "msg": "Invalid request"}), 400
        return data, None, None

    def user_row(conn, user_id):
        return conn.execute("SELECT id, username, role, status FROM users WHERE id=?", (int(user_id),)).fetchone()

    def match_row(conn, match_id):
        return conn.execute(match_select_sql("m.id=?"), (int(match_id),)).fetchone()

    def actor_can_play(actor, row):
        return int(row["white_user_id"]) == int(actor["id"]) or (row["black_user_id"] and int(row["black_user_id"]) == int(actor["id"]))

    def actor_color(actor, row):
        if row["mode"] == "computer" and int(row["white_user_id"]) == int(actor["id"]):
            return row["human_side"] if "human_side" in row.keys() else "white"
        if int(row["white_user_id"]) == int(actor["id"]):
            return "white"
        if row["black_user_id"] and int(row["black_user_id"]) == int(actor["id"]):
            return "black"
        return None

    def actor_delete_column(actor, row):
        if int(row["white_user_id"]) == int(actor["id"]):
            return "white_deleted_at"
        if row["black_user_id"] and int(row["black_user_id"]) == int(actor["id"]):
            return "black_deleted_at"
        return None

    def award_weekly_rewards(week, actor=None):
        conn = get_db()
        try:
            ensure_game_schema(conn)
            rows = leaderboard_rows(conn, week)[:3]
        finally:
            conn.close()
        awarded = []
        for index, row in enumerate(rows):
            reward_points = WEEKLY_REWARDS[index]
            ledger_uuid = None
            if points_service:
                result = points_service.record_transaction(
                    user_id=row["user_id"],
                    currency_type=DISPLAY_CURRENCY,
                    direction="credit",
                    amount=reward_points,
                    action_type="game_weekly_leaderboard_reward",
                    reference_type="game_weekly_leaderboard",
                    reference_id=f"{GAME_KEY}:{week}:{index + 1}",
                    idempotency_key=f"game_weekly_reward:{GAME_KEY}:{week}:{row['user_id']}",
                    reason=f"西洋棋週排行榜第 {index + 1} 名獎勵",
                    public_metadata={"game_key": GAME_KEY, "week": week, "rank": index + 1, "score": row["score"]},
                    actor=actor,
                )
                ledger_uuid = result["ledger"]["ledger_uuid"]
            conn = get_db()
            try:
                ensure_game_schema(conn)
                now = utc_now()
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO game_leaderboard_rewards (
                        game_key, week_key, user_id, rank, score, reward_points, ledger_uuid, awarded_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        GAME_KEY,
                        week,
                        row["user_id"],
                        index + 1,
                        row["score"],
                        reward_points,
                        ledger_uuid,
                        int(actor["id"]) if actor and actor.get("id") else None,
                        now,
                    ),
                )
                conn.commit()
                inserted = cur.rowcount > 0
            finally:
                conn.close()
            if inserted:
                awarded.append({"user_id": row["user_id"], "username": row["username"], "rank": index + 1, "reward_points": reward_points})
        return awarded

    @app.route("/api/games/catalog", methods=["GET"])
    @require_csrf_safe
    def games_catalog():
        actor, err, status = actor_or_401()
        if err:
            return err, status
        return json_resp({
            "ok": True,
            "games": [{
                "key": GAME_KEY,
                "title": "西洋棋",
                "status": "available",
                "supports_invites": True,
                "supports_computer": True,
                "computer_difficulties": [
                    {"key": "easy", "label": "簡單"},
                    {"key": "normal", "label": "普通"},
                    {"key": "hard", "label": "困難"},
                ],
            }, {
                "key": "sudoku",
                "title": "數獨",
                "status": "available",
                "supports_invites": False,
                "supports_computer": False,
            }, {
                "key": "minesweeper",
                "title": "踩地雷",
                "status": "available",
                "supports_invites": False,
                "supports_computer": False,
            }],
        })

    @app.route("/api/games/users", methods=["GET"])
    @require_csrf_safe
    def games_users():
        actor, err, status = actor_or_401()
        if err:
            return err, status
        conn = get_db()
        try:
            ensure_game_schema(conn)
            rows = conn.execute(
                """
                SELECT id, username, role
                FROM users
                WHERE id<>? AND COALESCE(deleted_at, '')='' AND COALESCE(status, 'active')='active'
                ORDER BY username COLLATE NOCASE
                LIMIT 200
                """,
                (int(actor["id"]),),
            ).fetchall()
            return json_resp({"ok": True, "users": [dict(row) for row in rows]})
        finally:
            conn.close()

    @app.route("/api/games/chess/invites", methods=["GET"])
    @require_csrf_safe
    def chess_invites():
        actor, err, status = actor_or_401()
        if err:
            return err, status
        conn = get_db()
        try:
            ensure_game_schema(conn)
            sql = """
                SELECT i.*, inviter.username AS inviter_username, opponent.username AS opponent_username
                FROM game_invites i
                JOIN users inviter ON inviter.id=i.inviter_user_id
                JOIN users opponent ON opponent.id=i.opponent_user_id
                WHERE i.game_key=? AND (i.inviter_user_id=? OR i.opponent_user_id=?)
                ORDER BY i.id DESC
                LIMIT 80
            """
            rows = conn.execute(sql, (GAME_KEY, int(actor["id"]), int(actor["id"]))).fetchall()
            return json_resp({"ok": True, "invites": [serialize_invite(row) for row in rows]})
        finally:
            conn.close()

    @app.route("/api/games/chess/invites", methods=["POST"])
    @require_csrf
    def create_chess_invite():
        actor, err, status = actor_or_401()
        if err:
            return err, status
        data, err, status = parse_json_body()
        if err:
            return err, status
        username = str(data.get("opponent_username") or data.get("username") or "").strip()
        if not username:
            return json_resp({"ok": False, "msg": "請選擇要邀請的玩家"}), 400
        conn = get_db()
        try:
            ensure_game_schema(conn)
            opponent_row = conn.execute(
                "SELECT id, username FROM users WHERE username=? AND COALESCE(status, 'active')='active' AND COALESCE(deleted_at, '')=''",
                (username,),
            ).fetchone()
            if not opponent_row:
                return json_resp({"ok": False, "msg": "找不到可邀請的玩家"}), 404
            if int(opponent_row["id"]) == int(actor["id"]):
                return json_resp({"ok": False, "msg": "不能邀請自己"}), 400
            pending = conn.execute(
                """
                SELECT id FROM game_invites
                WHERE game_key=? AND status='pending' AND inviter_user_id=? AND opponent_user_id=?
                """,
                (GAME_KEY, int(actor["id"]), int(opponent_row["id"])),
            ).fetchone()
            if pending:
                return json_resp({"ok": False, "msg": "已經有等待中的邀請"}), 409
            now = utc_now()
            expires = (datetime.now(timezone.utc) + timedelta(days=7)).replace(microsecond=0).isoformat()
            cur = conn.execute(
                """
                INSERT INTO game_invites (game_key, inviter_user_id, opponent_user_id, status, message, created_at, updated_at, expires_at)
                VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)
                """,
                (GAME_KEY, int(actor["id"]), int(opponent_row["id"]), str(data.get("message") or "")[:160], now, now, expires),
            )
            conn.commit()
            audit("GAME_INVITE_CREATED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"invite_id={cur.lastrowid}")
            return json_resp({"ok": True, "invite_id": cur.lastrowid})
        finally:
            conn.close()

    @app.route("/api/games/chess/invites/<int:invite_id>/<action>", methods=["POST"])
    @require_csrf
    def review_chess_invite(invite_id, action):
        actor, err, status = actor_or_401()
        if err:
            return err, status
        if action not in {"accept", "reject", "cancel"}:
            return json_resp({"ok": False, "msg": "不支援的邀請操作"}), 400
        conn = get_db()
        try:
            ensure_game_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            invite = conn.execute("SELECT * FROM game_invites WHERE id=? AND game_key=?", (invite_id, GAME_KEY)).fetchone()
            if not invite:
                conn.rollback()
                return json_resp({"ok": False, "msg": "找不到邀請"}), 404
            if invite["status"] != "pending":
                conn.rollback()
                return json_resp({"ok": False, "msg": "邀請已處理"}), 409
            actor_id = int(actor["id"])
            if action == "cancel" and actor_id != int(invite["inviter_user_id"]):
                conn.rollback()
                return json_resp({"ok": False, "msg": "只有邀請者能取消邀請"}), 403
            if action in {"accept", "reject"} and actor_id != int(invite["opponent_user_id"]):
                conn.rollback()
                return json_resp({"ok": False, "msg": "只有受邀者能回覆邀請"}), 403
            now = utc_now()
            match_id = None
            new_status = {"accept": "accepted", "reject": "rejected", "cancel": "cancelled"}[action]
            if action == "accept":
                inviter_is_white = random.choice([True, False])
                white_user_id = int(invite["inviter_user_id"]) if inviter_is_white else int(invite["opponent_user_id"])
                black_user_id = int(invite["opponent_user_id"]) if inviter_is_white else int(invite["inviter_user_id"])
                cur = conn.execute(
                    """
                    INSERT INTO game_matches (
                        game_key, mode, status, white_user_id, black_user_id, human_side, current_turn,
                        board_json, move_history_json, created_at, updated_at
                    ) VALUES (?, 'pvp', 'active', ?, ?, 'white', 'white', ?, '[]', ?, ?)
                    """,
                    (GAME_KEY, white_user_id, black_user_id, default_board_json(), now, now),
                )
                match_id = cur.lastrowid
            conn.execute(
                "UPDATE game_invites SET status=?, match_id=?, updated_at=? WHERE id=?",
                (new_status, match_id, now, invite_id),
            )
            conn.commit()
            return json_resp({"ok": True, "match_id": match_id})
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @app.route("/api/games/chess/practice", methods=["POST"])
    @require_csrf
    def create_chess_practice():
        actor, err, status = actor_or_401()
        if err:
            return err, status
        data, err, status = parse_json_body()
        if err:
            return err, status
        human_side = str(data.get("side") or data.get("human_side") or "white").strip().lower()
        if human_side not in {"white", "black"}:
            return json_resp({"ok": False, "msg": "請選擇白方或黑方"}), 400
        difficulty = normalize_computer_difficulty(data.get("difficulty") or data.get("computer_difficulty"))
        if difficulty is None:
            return json_resp({"ok": False, "msg": "請選擇有效的電腦難度"}), 400
        conn = get_db()
        try:
            ensure_game_schema(conn)
            now = utc_now()
            board = initial_board()
            history = []
            current_turn = "white"
            if human_side == "black":
                opening_moves = legal_moves(board, "white")
                if opening_moves:
                    computer_move = choose_computer_move(board, "white", difficulty)
                    applied = validate_move(board, "white", computer_move["from"], computer_move["to"], computer_move.get("promotion"))
                    board = applied["board"]
                    history.append({
                        "by": "white",
                        "from": computer_move["from"],
                        "to": computer_move["to"],
                        "piece": computer_move["piece"],
                        "captured": applied.get("captured"),
                        "computer": True,
                        "at": now,
                    })
                    current_turn = "black"
            cur = conn.execute(
                """
                INSERT INTO game_matches (
                    game_key, mode, status, white_user_id, black_user_id, human_side, computer_difficulty, current_turn,
                    board_json, move_history_json, created_at, updated_at
                ) VALUES (?, 'computer', 'active', ?, NULL, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    GAME_KEY,
                    int(actor["id"]),
                    human_side,
                    difficulty,
                    current_turn,
                    json.dumps(board, ensure_ascii=False, sort_keys=True),
                    json.dumps(history, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            conn.commit()
            return json_resp({"ok": True, "match_id": cur.lastrowid})
        finally:
            conn.close()

    @app.route("/api/games/chess/matches", methods=["GET"])
    @require_csrf_safe
    def chess_matches():
        actor, err, status = actor_or_401()
        if err:
            return err, status
        conn = get_db()
        try:
            ensure_game_schema(conn)
            rows = conn.execute(
                match_select_sql(
                    """
                    m.game_key=?
                    AND (
                        (m.white_user_id=? AND m.white_deleted_at IS NULL)
                        OR (m.black_user_id=? AND m.black_deleted_at IS NULL)
                    )
                    ORDER BY CASE WHEN m.status='active' THEN 0 ELSE 1 END, m.id DESC
                    LIMIT 80
                    """
                ),
                (GAME_KEY, int(actor["id"]), int(actor["id"])),
            ).fetchall()
            return json_resp({"ok": True, "matches": [serialize_match(row, actor["id"]) for row in rows]})
        finally:
            conn.close()

    @app.route("/api/games/chess/matches/<int:match_id>", methods=["GET"])
    @require_csrf_safe
    def chess_match_detail(match_id):
        actor, err, status = actor_or_401()
        if err:
            return err, status
        conn = get_db()
        try:
            ensure_game_schema(conn)
            row = match_row(conn, match_id)
            if not row:
                return json_resp({"ok": False, "msg": "找不到棋局"}), 404
            if not actor_can_play(actor, row):
                return json_resp({"ok": False, "msg": "不是這局的玩家"}), 403
            return json_resp({"ok": True, "match": serialize_match(row, actor["id"])})
        finally:
            conn.close()

    @app.route("/api/games/chess/matches/<int:match_id>", methods=["DELETE"])
    @require_csrf
    def chess_match_delete(match_id):
        actor, err, status = actor_or_401()
        if err:
            return err, status
        conn = get_db()
        try:
            ensure_game_schema(conn)
            row = match_row(conn, match_id)
            if not row:
                return json_resp({"ok": False, "msg": "找不到棋局"}), 404
            side = actor_color(actor, row)
            column = actor_delete_column(actor, row)
            if not side or not column:
                return json_resp({"ok": False, "msg": "不是這局的玩家"}), 403
            if row["status"] == "active":
                return json_resp({"ok": False, "msg": "進行中的棋局不能刪除，請先認輸或完成棋局"}), 409
            now = utc_now()
            conn.execute(f"UPDATE game_matches SET {column}=?, updated_at=? WHERE id=?", (now, now, match_id))
            conn.commit()
            audit(
                "GAME_MATCH_DELETED",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"match_id={match_id}, side={side}, status={row['status']}",
            )
            return json_resp({"ok": True, "msg": "棋局已從你的列表移除"})
        finally:
            conn.close()

    @app.route("/api/games/chess/matches/<int:match_id>/move", methods=["POST"])
    @require_csrf
    def chess_match_move(match_id):
        actor, err, status = actor_or_401()
        if err:
            return err, status
        data, err, status = parse_json_body()
        if err:
            return err, status
        from_square = str(data.get("from") or "").strip().lower()
        to_square = str(data.get("to") or "").strip().lower()
        conn = get_db()
        try:
            ensure_game_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            row = match_row(conn, match_id)
            if not row:
                conn.rollback()
                return json_resp({"ok": False, "msg": "找不到棋局"}), 404
            if row["status"] != "active":
                conn.rollback()
                return json_resp({"ok": False, "msg": "棋局已結束"}), 409
            side = actor_color(actor, row)
            if not side:
                conn.rollback()
                return json_resp({"ok": False, "msg": "不是這局的玩家"}), 403
            if side != row["current_turn"]:
                conn.rollback()
                return json_resp({"ok": False, "msg": "還沒輪到你"}), 409
            board = load_board(row)
            try:
                move = validate_move(board, side, from_square, to_square, data.get("promotion"))
            except ValueError as exc:
                conn.rollback()
                return json_resp({"ok": False, "msg": str(exc)}), 400
            history = load_history(row)
            now = utc_now()
            history.append({
                "by": side,
                "from": from_square,
                "to": to_square,
                "piece": move["piece"],
                "captured": move.get("captured"),
                "at": now,
            })
            board = move["board"]
            next_turn = opponent(side)
            status_info = game_status(board, next_turn)
            human_side = row["human_side"] if "human_side" in row.keys() else "white"
            computer_difficulty = row["computer_difficulty"] if "computer_difficulty" in row.keys() else "easy"
            if row["mode"] == "computer" and status_info["status"] == "active" and next_turn != human_side:
                computer_side = next_turn
                computer_move = choose_computer_move(board, computer_side, computer_difficulty)
                if computer_move:
                    computer_applied = validate_move(board, computer_side, computer_move["from"], computer_move["to"], computer_move.get("promotion"))
                    board = computer_applied["board"]
                    history.append({
                        "by": computer_side,
                        "from": computer_move["from"],
                        "to": computer_move["to"],
                        "piece": computer_move["piece"],
                        "captured": computer_applied.get("captured"),
                        "computer": True,
                        "at": utc_now(),
                    })
                    next_turn = human_side
                    status_info = game_status(board, next_turn)
            conn.execute(
                """
                UPDATE game_matches
                SET board_json=?, move_history_json=?, current_turn=?, updated_at=?
                WHERE id=?
                """,
                (json.dumps(board, ensure_ascii=False, sort_keys=True), json.dumps(history, ensure_ascii=False), next_turn, now, match_id),
            )
            if status_info["status"] == "finished":
                refreshed = conn.execute("SELECT * FROM game_matches WHERE id=?", (match_id,)).fetchone()
                finish_match(conn, refreshed, status_info, utc_now())
            conn.commit()
            refreshed = match_row(conn, match_id)
            return json_resp({"ok": True, "match": serialize_match(refreshed, actor["id"])})
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @app.route("/api/games/chess/matches/<int:match_id>/resign", methods=["POST"])
    @require_csrf
    def chess_match_resign(match_id):
        actor, err, status = actor_or_401()
        if err:
            return err, status
        conn = get_db()
        try:
            ensure_game_schema(conn)
            row = match_row(conn, match_id)
            if not row:
                return json_resp({"ok": False, "msg": "找不到棋局"}), 404
            side = actor_color(actor, row)
            if not side:
                return json_resp({"ok": False, "msg": "不是這局的玩家"}), 403
            winner = row["black_user_id"] if side == "white" else row["white_user_id"]
            if row["mode"] == "computer":
                winner = None
            now = utc_now()
            conn.execute(
                """
                UPDATE game_matches
                SET status='finished', winner_user_id=?, result_reason='resign', leaderboard_week=?, finished_at=?, updated_at=?
                WHERE id=? AND status='active'
                """,
                (winner, current_week_key(), now, now, match_id),
            )
            conn.commit()
            refreshed = match_row(conn, match_id)
            return json_resp({"ok": True, "match": serialize_match(refreshed, actor["id"])})
        finally:
            conn.close()

    @app.route("/api/games/chess/leaderboard", methods=["GET"])
    @require_csrf_safe
    def chess_leaderboard():
        actor, err, status = actor_or_401()
        if err:
            return err, status
        week = str(request.args.get("week") or current_week_key()).strip()
        now = datetime.now(timezone.utc)
        auto_awarded = []
        if not request.args.get("week") and now.weekday() >= 5:
            auto_awarded = award_weekly_rewards(week, actor=None)
        conn = get_db()
        try:
            ensure_game_schema(conn)
            rows = leaderboard_rows(conn, week)
            rewards = conn.execute(
                """
                SELECT r.*, u.username
                FROM game_leaderboard_rewards r
                JOIN users u ON u.id=r.user_id
                WHERE r.game_key=? AND r.week_key=?
                ORDER BY r.rank ASC
                """,
                (GAME_KEY, week),
            ).fetchall()
            return json_resp({
                "ok": True,
                "week": week,
                "reward_points": list(WEEKLY_REWARDS),
                "leaderboard": rows,
                "rewards": [dict(row) for row in rewards],
                "auto_awarded": auto_awarded,
            })
        finally:
            conn.close()

    @app.route("/api/games/<game_key>/solo-leaderboard", methods=["GET"])
    @require_csrf_safe
    def solo_game_leaderboard(game_key):
        actor, err, status = actor_or_401()
        if err:
            return err, status
        game_key = str(game_key or "").strip().lower()
        if game_key not in SOLO_GAME_KEYS:
            return json_resp({"ok": False, "msg": "不支援的單人遊戲"}), 404
        week = str(request.args.get("week") or current_week_key()).strip()
        difficulty = str(request.args.get("difficulty") or ("easy" if game_key == "minesweeper" else "standard")).strip().lower()
        if game_key == "minesweeper" and difficulty not in MINESWEEPER_DIFFICULTIES:
            return json_resp({"ok": False, "msg": "不支援的難度"}), 400
        if game_key == "sudoku":
            difficulty = "standard"
        conn = get_db()
        try:
            ensure_game_schema(conn)
            return json_resp({
                "ok": True,
                "game_key": game_key,
                "week": week,
                "difficulty": difficulty,
                "rank_mode": "time_asc",
                "leaderboard": solo_leaderboard_rows(conn, game_key, week, difficulty),
            })
        finally:
            conn.close()

    @app.route("/api/games/<game_key>/solo-scores", methods=["POST"])
    @require_csrf
    def submit_solo_game_score(game_key):
        actor, err, status = actor_or_401()
        if err:
            return err, status
        game_key = str(game_key or "").strip().lower()
        if game_key not in SOLO_GAME_KEYS:
            return json_resp({"ok": False, "msg": "不支援的單人遊戲"}), 404
        data, err, status = parse_json_body()
        if err:
            return err, status
        try:
            raw_elapsed_ms = int(data.get("raw_elapsed_ms") or data.get("elapsed_ms") or 0)
            penalty_seconds = int(data.get("penalty_seconds") or 0)
            elapsed_ms = int(data.get("elapsed_ms") or 0)
        except Exception:
            return json_resp({"ok": False, "msg": "成績格式錯誤"}), 400
        if raw_elapsed_ms <= 0 or elapsed_ms <= 0 or penalty_seconds < 0:
            return json_resp({"ok": False, "msg": "成績時間不可小於等於 0"}), 400
        if elapsed_ms < raw_elapsed_ms or elapsed_ms != raw_elapsed_ms + penalty_seconds * 1000:
            return json_resp({"ok": False, "msg": "成績時間與加時不一致"}), 400
        if elapsed_ms > 24 * 60 * 60 * 1000 or penalty_seconds > 3600:
            return json_resp({"ok": False, "msg": "成績時間超出合理範圍"}), 400
        difficulty = str(data.get("difficulty") or ("easy" if game_key == "minesweeper" else "standard")).strip().lower()
        if game_key == "minesweeper" and difficulty not in MINESWEEPER_DIFFICULTIES:
            return json_resp({"ok": False, "msg": "不支援的難度"}), 400
        if game_key == "sudoku":
            difficulty = "standard"
        puzzle_id = str(data.get("puzzle_id") or "")[:64]
        week = current_week_key()
        now = utc_now()
        conn = get_db()
        try:
            ensure_game_schema(conn)
            cur = conn.execute(
                """
                INSERT INTO game_solo_scores (
                    game_key, user_id, week_key, difficulty, puzzle_id,
                    raw_elapsed_ms, penalty_seconds, elapsed_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (game_key, int(actor["id"]), week, difficulty, puzzle_id, raw_elapsed_ms, penalty_seconds, elapsed_ms, now),
            )
            conn.commit()
            audit(
                "GAME_SOLO_SCORE_SUBMITTED",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"game_key={game_key},score_id={cur.lastrowid},elapsed_ms={elapsed_ms},penalty_seconds={penalty_seconds}",
            )
            return json_resp({
                "ok": True,
                "score_id": cur.lastrowid,
                "week": week,
                "leaderboard": solo_leaderboard_rows(conn, game_key, week, difficulty),
            })
        finally:
            conn.close()

    @app.route("/api/root/games/chess/weekly-rewards/award", methods=["POST"])
    @require_csrf
    def award_chess_weekly_rewards():
        actor, err, status = actor_or_401()
        if err:
            return err, status
        if actor.get("username") != "root":
            return json_resp({"ok": False, "msg": "只有 root 可執行此操作"}), 403
        data, err, status = parse_json_body()
        if err:
            return err, status
        week = str(data.get("week") or current_week_key()).strip()
        awarded = award_weekly_rewards(week, actor=actor)
        audit("GAME_WEEKLY_REWARDS_AWARDED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"week={week}")
        return json_resp({"ok": True, "week": week, "awarded": awarded})


def leaderboard_rows(conn, week):
    rows = conn.execute(
        """
        SELECT u.id AS user_id,
               u.username AS username,
               SUM(CASE
                    WHEN m.winner_user_id=u.id THEN 3
                    WHEN m.winner_user_id IS NULL THEN 1
                    ELSE 0
               END) AS score,
               SUM(CASE WHEN m.winner_user_id=u.id THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN m.winner_user_id IS NULL THEN 1 ELSE 0 END) AS draws,
               SUM(CASE WHEN m.winner_user_id IS NOT NULL AND m.winner_user_id<>u.id THEN 1 ELSE 0 END) AS losses,
               COUNT(*) AS games
        FROM game_matches m
        JOIN users u ON u.id IN (m.white_user_id, m.black_user_id)
        WHERE m.game_key=? AND m.mode='pvp' AND m.status='finished' AND m.leaderboard_week=?
        GROUP BY u.id, u.username
        ORDER BY score DESC, wins DESC, games ASC, u.username COLLATE NOCASE ASC
        LIMIT 50
        """,
        (GAME_KEY, week),
    ).fetchall()
    return [{**dict(row), "rank": index + 1} for index, row in enumerate(rows)]


def solo_leaderboard_rows(conn, game_key, week, difficulty):
    rows = conn.execute(
        """
        SELECT best.user_id,
               u.username,
               best.elapsed_ms,
               best.raw_elapsed_ms,
               best.penalty_seconds,
               attempts.attempts,
               best.created_at AS latest_at
        FROM game_solo_scores s
        JOIN game_solo_scores best ON best.id=(
            SELECT s2.id
            FROM game_solo_scores s2
            WHERE s2.game_key=s.game_key
              AND s2.week_key=s.week_key
              AND s2.difficulty=s.difficulty
              AND s2.user_id=s.user_id
            ORDER BY s2.elapsed_ms ASC, s2.created_at ASC, s2.id ASC
            LIMIT 1
        )
        JOIN (
            SELECT user_id, COUNT(*) AS attempts
            FROM game_solo_scores
            WHERE game_key=? AND week_key=? AND difficulty=?
            GROUP BY user_id
        ) attempts ON attempts.user_id=best.user_id
        JOIN users u ON u.id=best.user_id
        WHERE s.game_key=? AND s.week_key=? AND s.difficulty=?
        GROUP BY best.id, best.user_id, u.username, best.elapsed_ms, best.raw_elapsed_ms, best.penalty_seconds, attempts.attempts, best.created_at
        ORDER BY best.elapsed_ms ASC, attempts.attempts ASC, u.username COLLATE NOCASE ASC
        LIMIT 50
        """,
        (game_key, week, difficulty, game_key, week, difficulty),
    ).fetchall()
    return [{**dict(row), "rank": index + 1} for index, row in enumerate(rows)]
