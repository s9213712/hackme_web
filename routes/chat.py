import hashlib
import json
import re
import secrets
import sqlite3
from datetime import datetime, timedelta
from flask import Response, request

from services.storage.cloud_drive import attach_existing_file, can_download_file, can_remove_context_attachment, ensure_cloud_drive_attachment_schema
from services.system.notifications import create_notification, create_notification_if_enabled, ensure_notifications_schema
from services.security.permissions import require_member_action
from services.core.sqlite_safe import table_columns as safe_table_columns
from services.users.friends import (
    assert_can_target_user,
    block_user,
    create_friend_request,
    list_friend_state,
    remove_friend,
    review_friend_request,
    unblock_user,
)

CHAT_RECALL_WINDOW_SECONDS = 5 * 60
CHAT_STICKERS = {
    "smile": {"label": "微笑", "glyph": "🙂"},
    "thanks": {"label": "感謝", "glyph": "🥹"},
    "ok": {"label": "了解", "glyph": "😙"},
    "wow": {"label": "驚訝", "glyph": "😃"},
    "cheer": {"label": "加油", "glyph": "😚"},
    "sad": {"label": "難過", "glyph": "🥲"},
}
CHAT_HTML_TAG_RE = re.compile(r"<\s*/?\s*[A-Za-z][^>]*>")


def actor_value(actor, key, default=None):
    if not actor:
        return default
    try:
        return actor[key]
    except Exception:
        return actor.get(key, default) if hasattr(actor, "get") else default


def actor_role(actor):
    if not actor:
        return "guest"
    return "super_admin" if actor_value(actor, "username") == "root" else (actor_value(actor, "role") or "user")


def truthy_payload(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "y"}
    return False


def sanitize_chat_content(value):
    """Store chat as plain text so saved messages cannot become stored HTML."""
    if value is None:
        return ""
    text = str(value).replace("\x00", "").strip()
    return CHAT_HTML_TAG_RE.sub("", text).strip()


def _audit_safe(value, *, max_len=200):
    """Escape user-controlled fields before inserting into audit `detail`
    key=value strings.

    Audit log readers split events on newlines; a chat room name like
    `legitimate\\nROOT_LOGIN_FORGED ip=... success=True` would otherwise
    forge a fake audit row. This helper:

      - replaces ``\\r`` / ``\\n`` / ``\\x00`` with their literal escape
        sequences so log readers see one logical line
      - replaces ``,`` and ``=`` (the audit kv separators) with similar
        escapes so callers cannot inject extra k=v pairs
      - caps length so a single forged-name attack cannot fill audit
        storage

    See issue #179.
    """
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace("\r", "\\r")
    text = text.replace("\n", "\\n")
    text = text.replace("\x00", "\\x00")
    text = text.replace(",", "\\,")
    text = text.replace("=", "\\=")
    if len(text) > max_len:
        text = text[:max_len] + "...(truncated)"
    return text


def _table_columns(conn, table):
    try:
        return safe_table_columns(conn, table)
    except Exception:
        return set()


def ensure_chat_feature_schema(conn):
    room_cols = _table_columns(conn, "chat_rooms")
    room_additions = (
        ("join_password_hash", "TEXT"),
        ("join_password_required", "INTEGER NOT NULL DEFAULT 0"),
        ("allow_anonymous", "INTEGER NOT NULL DEFAULT 0"),
    )
    for name, ddl in room_additions:
        if name not in room_cols:
            conn.execute(f"ALTER TABLE chat_rooms ADD COLUMN {name} {ddl}")
    member_cols = _table_columns(conn, "chat_room_members")
    if "anonymous_enabled" not in member_cols:
        conn.execute("ALTER TABLE chat_room_members ADD COLUMN anonymous_enabled INTEGER NOT NULL DEFAULT 0")
    cols = _table_columns(conn, "chat_messages")
    additions = (
        ("message_type", "TEXT NOT NULL DEFAULT 'text'"),
        ("sticker_key", "TEXT"),
        ("is_revoked", "INTEGER NOT NULL DEFAULT 0"),
        ("revoked_at", "TEXT"),
        ("revoked_by", "INTEGER"),
        ("edited_at", "TEXT"),
        ("edited_by", "INTEGER"),
        ("edit_count", "INTEGER NOT NULL DEFAULT 0"),
        ("original_content", "TEXT"),
    )
    for name, ddl in additions:
        if name not in cols:
            conn.execute(f"ALTER TABLE chat_messages ADD COLUMN {name} {ddl}")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_message_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
            room_id INTEGER NOT NULL REFERENCES chat_rooms(id) ON DELETE CASCADE,
            reporter_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            reported_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            reason TEXT NOT NULL,
            content_snapshot TEXT,
            message_created_at TEXT,
            message_edited_at TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            reviewed_by TEXT,
            reviewed_at TEXT,
            review_note TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(message_id, reporter_user_id)
        )
        """
    )
    report_cols = _table_columns(conn, "chat_message_reports")
    report_additions = (
        ("content_snapshot", "TEXT"),
        ("message_created_at", "TEXT"),
        ("message_edited_at", "TEXT"),
    )
    for name, ddl in report_additions:
        if name not in report_cols:
            conn.execute(f"ALTER TABLE chat_message_reports ADD COLUMN {name} {ddl}")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_friends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            friend_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'pending',
            requested_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, friend_user_id),
            CHECK (user_id <> friend_user_id),
            CHECK (status IN ('pending', 'accepted', 'rejected', 'blocked'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_friends_user_status ON user_friends(user_id, status)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_room_invites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL REFERENCES chat_rooms(id) ON DELETE CASCADE,
            inviter_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            invitee_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(room_id, invitee_user_id),
            CHECK (status IN ('pending', 'accepted', 'rejected'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_room_invites_invitee ON chat_room_invites(invitee_user_id, status)")


def hash_chat_room_password(password):
    raw = str(password or "")
    if not raw:
        return None
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt.encode("ascii"), 120_000)
    return f"pbkdf2_sha256$120000${salt}${digest.hex()}"


def verify_chat_room_password(stored, password):
    if not stored:
        return True
    try:
        algo, rounds, salt, digest = str(stored).split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"), salt.encode("ascii"), int(rounds))
        return secrets.compare_digest(candidate.hex(), digest)
    except Exception:
        return False


def normalize_username_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = value.replace("\n", ",").split(",")
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = [value]
    names = []
    seen = set()
    for item in raw_items:
        name = str(item or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
        if len(names) >= 20:
            break
    return names


def parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def can_delete_chat_message(actor, message_row, role_rank):
    if not actor or not message_row:
        return False
    if actor["username"] == "root":
        return True
    if message_row["sender_id"] == actor["id"]:
        return True
    if message_row["owner_user_id"] == actor["id"]:
        return True

    actor_rank = role_rank(actor_role(actor))
    if actor_rank >= role_rank("super_admin"):
        return True
    if actor_rank < role_rank("manager"):
        return False

    target_role = "super_admin" if message_row["sender_username"] == "root" else (message_row["sender_role"] or "user")
    return role_rank(target_role) < actor_rank


def can_recall_chat_message(actor, message_row):
    if not actor or not message_row:
        return False
    if message_row["sender_id"] != actor["id"]:
        return False
    created = parse_iso_datetime(message_row["created_at"])
    if not created:
        return False
    return datetime.now() - created <= timedelta(seconds=CHAT_RECALL_WINDOW_SECONDS)


def can_edit_chat_message(actor, message_row):
    if not can_recall_chat_message(actor, message_row):
        return False
    if message_row["is_revoked"]:
        return False
    if "is_blocked" in message_row.keys() and message_row["is_blocked"]:
        return False
    if "message_type" in message_row.keys() and (message_row["message_type"] or "text") != "text":
        return False
    return True


def chat_message_has_pending_report(conn, message_id):
    row = conn.execute(
        "SELECT 1 FROM chat_message_reports WHERE message_id=? AND status='pending' LIMIT 1",
        (message_id,),
    ).fetchone()
    return bool(row)


def chat_message_pending_report_ids(conn, message_ids):
    ids = [int(message_id) for message_id in message_ids if message_id]
    if not ids:
        return set()
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT DISTINCT message_id FROM chat_message_reports WHERE status='pending' AND message_id IN ({placeholders})",
        tuple(ids),
    ).fetchall()
    return {int(row["message_id"]) for row in rows}


def chat_message_mutation_lock_message(conn, message_id):
    if chat_message_has_pending_report(conn, message_id):
        return "此訊息已有待審核檢舉，審核完成前不能編輯或收回"
    return ""


def can_delete_chat_room(actor, room_row, role_rank):
    if not actor or not room_row:
        return False
    if actor_value(actor, "username") == "root":
        return True
    if room_row["owner_user_id"] == actor_value(actor, "id"):
        return True
    actor_rank = role_rank(actor_role(actor))
    if actor_rank < role_rank("manager"):
        return False
    owner_role = "super_admin" if room_row["owner_username"] == "root" else (room_row["owner_role"] or "user")
    return role_rank(owner_role) < actor_rank


def normalize_attachment_file_ids(value, *, limit=8):
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else [value]
    file_ids = []
    seen = set()
    for item in raw_items:
        file_id = str(item or "").strip()
        if not file_id or file_id in seen:
            continue
        seen.add(file_id)
        file_ids.append(file_id)
        if len(file_ids) >= limit:
            break
    return file_ids


def chat_message_attachment_map(conn, actor, message_ids):
    ids = [int(mid) for mid in message_ids if mid]
    if not ids:
        return {}
    if not _table_columns(conn, "uploaded_files"):
        return {}
    ensure_cloud_drive_attachment_schema(conn)
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT r.id AS ref_id, r.context_id AS message_id, r.file_id, r.owner_user_id, r.attached_by,
               r.context_type, r.context_id,
               f.original_filename_plain_for_public, f.mime_type_plain_for_public,
               f.size_bytes, f.scan_status, f.risk_level, f.privacy_mode, f.deleted_at
        FROM cloud_file_refs r
        JOIN uploaded_files f ON f.id=r.file_id
        WHERE r.context_type='chat_message' AND r.context_id IN ({placeholders})
        ORDER BY r.created_at ASC
        """,
        tuple(str(mid) for mid in ids),
    ).fetchall()
    by_message = {}
    for row in rows:
        if row["deleted_at"]:
            continue
        allowed, reason, _ = can_download_file(conn, actor=actor, file_id=row["file_id"])
        item = dict(row)
        item["can_download"] = bool(allowed)
        item["download_reason"] = reason
        item["can_remove"] = can_remove_context_attachment(actor, row)
        item.pop("owner_user_id", None)
        item.pop("attached_by", None)
        by_message.setdefault(int(row["message_id"]), []).append(item)
    return by_message


def register_chat_routes(app, deps):
    CHAT_MESSAGE_MAX_LEN = deps["CHAT_MESSAGE_MAX_LEN"]
    OFFICIAL_CHAT_ROOM_NAME = deps["OFFICIAL_CHAT_ROOM_NAME"]
    add_violation = deps["add_violation"]
    append_chat_record = deps["append_chat_record"]
    audit = deps["audit"]
    check_user_rate_limit = deps["check_user_rate_limit"]
    db_get_user_from_token = deps["db_get_user_from_token"]
    db_get_user_role = deps["db_get_user_role"]
    detect_chat_violation = deps["detect_chat_violation"]
    ensure_user_official_room_membership = deps["ensure_user_official_room_membership"]
    get_client_ip = deps["get_client_ip"]
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_auth_db = deps.get("get_auth_db", deps["get_db"])
    get_db = deps["get_db"]
    json_resp = deps["json_resp"]
    normalize_text = deps["normalize_text"]
    parse_positive_int = deps["parse_positive_int"]
    require_csrf = deps["require_csrf"]
    require_csrf_safe = deps["require_csrf_safe"]
    role_rank = deps["role_rank"]

    def is_official_chat_room(row):
        if not row:
            return False
        try:
            return row["name"] == OFFICIAL_CHAT_ROOM_NAME
        except Exception:
            return row.get("name") == OFFICIAL_CHAT_ROOM_NAME if hasattr(row, "get") else False

    def can_view_original_chat_sender(actor):
        return actor_value(actor, "username") == "root" or role_rank(actor_role(actor)) >= role_rank("manager")

    def official_chat_sender_aliases(conn, room_id):
        rows = conn.execute(
            """
            SELECT DISTINCT u.id, u.username, u.role
            FROM users u
            WHERE u.id IN (
                SELECT user_id FROM chat_room_members WHERE room_id=?
                UNION
                SELECT sender_id FROM chat_messages WHERE room_id=? AND sender_id IS NOT NULL
            )
            ORDER BY u.id ASC
            """,
            (room_id, room_id),
        ).fetchall()
        manager_index = 0
        anonymous_index = 0
        aliases = {}
        for row in rows:
            user_id = int(row["id"])
            username = row["username"] or ""
            role = "super_admin" if username == "root" else (row["role"] or "user")
            if username == "root":
                aliases[user_id] = {"display": "root", "official": True}
            elif role_rank(role) >= role_rank("manager"):
                manager_index += 1
                aliases[user_id] = {"display": f"管理員{manager_index}", "official": True}
            else:
                anonymous_index += 1
                aliases[user_id] = {"display": f"匿名{anonymous_index}", "official": False}
        return aliases

    def anonymous_chat_sender_aliases(conn, room_id):
        rows = conn.execute(
            """
            SELECT DISTINCT u.id
            FROM chat_room_members m
            JOIN users u ON u.id=m.user_id
            WHERE m.room_id=? AND COALESCE(m.anonymous_enabled, 0)=1
            ORDER BY u.id ASC
            """,
            (room_id,),
        ).fetchall()
        aliases = {}
        for index, row in enumerate(rows, start=1):
            aliases[int(row["id"])] = {"display": f"匿名{index}", "official": False}
        return aliases

    def public_chat_sender_payload(row, *, room, actor, official_aliases=None, anonymous_aliases=None):
        data = dict(row)
        sender_id = data.get("sender_id")
        sender_id_int = int(sender_id) if sender_id is not None else None
        username = data.get("username") or data.get("sender") or "系統"
        role = "super_admin" if username == "root" else (data.get("sender_role") or "user")
        is_self = sender_id_int is not None and sender_id_int == int(actor_value(actor, "id", 0) or 0)
        is_official_room = is_official_chat_room(room)
        room_allows_anonymous = bool(room["allow_anonymous"]) if "allow_anonymous" in room.keys() else False
        member_anonymous = bool(data.get("sender_anonymous_enabled")) and room_allows_anonymous
        privileged_view = can_view_original_chat_sender(actor)
        sender_is_official = False
        sender = username
        anonymous_to_viewer = False

        if is_official_room:
            alias = (official_aliases or {}).get(sender_id_int, {"display": "匿名", "official": False})
            sender = alias["display"]
            sender_is_official = bool(alias["official"])
            anonymous_to_viewer = not privileged_view and username != sender
        elif member_anonymous:
            alias = (anonymous_aliases or {}).get(sender_id_int, {"display": "匿名", "official": False})
            sender = alias["display"]
            anonymous_to_viewer = not privileged_view and username != sender

        if anonymous_to_viewer and is_self and not privileged_view:
            sender = username

        expose_original = privileged_view or is_self or not anonymous_to_viewer
        if not expose_original and not is_self:
            public_sender_id = None
        else:
            public_sender_id = sender_id_int
        avatar_file_id = data.get("avatar_file_id") or ""
        if anonymous_to_viewer and not is_self:
            avatar_file_id = ""
        original_sender = username if privileged_view and username != sender else ""

        return {
            "sender_id": public_sender_id,
            "sender": sender,
            "sender_original": original_sender,
            "sender_role": role if privileged_view else "",
            "sender_is_official": sender_is_official,
            "sender_anonymous": bool(anonymous_to_viewer or member_anonymous or (is_official_room and username != "root")),
            "sender_avatar_file_id": avatar_file_id,
            "is_self": is_self,
        }

    @app.route("/api/chat/rooms", methods=["GET", "POST"], strict_slashes=False)
    @require_csrf_safe
    def chat_rooms():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        ip = get_client_ip()
        urow_id = actor["id"]

        if request.method == "GET":
            conn = get_db()
            try:
                ensure_chat_feature_schema(conn)
                ensure_user_official_room_membership(conn, urow_id)
                conn.commit()
                rows = conn.execute(
                    "SELECT r.id, r.name, r.owner_user_id, r.is_private, r.created_at, "
                    "COALESCE(r.join_password_required, 0) AS join_password_required, "
                    "COALESCE(r.allow_anonymous, 0) AS allow_anonymous, "
                    "COALESCE(m.anonymous_enabled, 0) AS anonymous_enabled, "
                    "(SELECT COUNT(*) FROM chat_room_members cm WHERE cm.room_id=r.id) AS member_count, "
                    "u.username AS owner_username "
                    "FROM chat_rooms r "
                    "LEFT JOIN users u ON u.id = r.owner_user_id "
                    "INNER JOIN chat_room_members m ON m.room_id = r.id "
                    "WHERE m.user_id = ? AND COALESCE(r.is_active, 1)=1 "
                    "ORDER BY r.is_private ASC, r.created_at DESC",
                    (urow_id,)
                ).fetchall()
                return json_resp({
                    "ok": True,
                    "rooms": [
                        {
                            "id": r["id"],
                            "name": r["name"],
                            "owner_user_id": r["owner_user_id"],
                            "owner_username": r["owner_username"] or "未知",
                            "is_private": r["is_private"],
                            "is_official": is_official_chat_room(r),
                            "join_password_required": bool(r["join_password_required"]),
                            "allow_anonymous": bool(r["allow_anonymous"]) and not bool(r["is_private"]),
                            "anonymous_enabled": bool(r["anonymous_enabled"]) and not bool(r["is_private"]),
                            "hide_member_count": is_official_chat_room(r),
                            "member_count": None if is_official_chat_room(r) else r["member_count"],
                            "created_at": r["created_at"]
                        } for r in rows
                    ]
                })
            finally:
                conn.close()

        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        name = normalize_text(data.get("name"))
        target_user = normalize_text(data.get("target_user"))
        invite_usernames = normalize_username_list(data.get("invite_usernames"))
        join_password = str(data.get("join_password") or "")
        allow_anonymous = truthy_payload(data.get("allow_anonymous"))
        anonymous_enabled = truthy_payload(data.get("anonymous") if "anonymous" in data else data.get("anonymous_enabled"))
        if not name and not target_user:
            return json_resp({"ok":False,"msg":"聊天室名稱不可為空"}), 400
        if len(name) > 48:
            return json_resp({"ok":False,"msg":"聊天室名稱最多 48 字元"}), 400
        if target_user == actor["username"]:
            return json_resp({"ok":False,"msg":"不能指定自己為對象"}), 400
        if actor["username"] in invite_usernames:
            invite_usernames = [item for item in invite_usernames if item != actor["username"]]
        if len(join_password) > 128:
            return json_resp({"ok":False,"msg":"聊天室密碼最多 128 字元"}), 400

        conn = get_db()
        room_id = None
        invite_username = None
        detail = None
        is_private_room = False
        try:
            conn.execute("BEGIN")
            ensure_chat_feature_schema(conn)
            target_row = None
            if target_user:
                ok, msg, status = require_member_action(actor, "chat_dm_create", conn=conn)
                if not ok:
                    return json_resp({"ok":False,"msg":msg}), status
                user_status_filter = "AND status='active'" if "status" in _table_columns(conn, "users") else ""
                target_row = conn.execute(
                    f"SELECT id, username FROM users WHERE username=? {user_status_filter}",
                    (target_user,)
                ).fetchone()
                if not target_row:
                    return json_resp({"ok":False,"msg":"找不到指定對象帳號"}), 404
                allowed, deny_msg = assert_can_target_user(conn, actor, target_row["id"], context="pm")
                if not allowed:
                    return json_resp({"ok":False,"msg":deny_msg}), 403

                # Check if a private 1on1 room already exists between these two users
                existing = conn.execute(
                    """SELECT cr.id, cr.name FROM chat_rooms cr
                       INNER JOIN chat_room_members m1 ON m1.room_id = cr.id AND m1.user_id = ?
                       INNER JOIN chat_room_members m2 ON m2.room_id = cr.id AND m2.user_id = ?
                       WHERE cr.is_private = 1 AND COALESCE(cr.is_active, 1)=1
                       LIMIT 1""",
                    (urow_id, target_row["id"])
                ).fetchone()
                if existing:
                    conn.commit()
                    return json_resp({
                        "ok": True,
                        "msg": "已找到私訊聊天室",
                        "room": {
                            "id": existing["id"],
                            "name": existing["name"],
                            "owner_user_id": urow_id,
                            "owner_username": actor["username"],
                            "target_username": target_row["username"],
                            "is_private": 1
                        }
                    })

                # Auto-generate consistent room name (alphabetically sorted)
                usernames = sorted([actor["username"], target_row["username"]])
                name = f"PM: {usernames[0]} | {usernames[1]}"
                is_private_room = True
                allow_anonymous = False
                anonymous_enabled = False
            elif not name:
                return json_resp({"ok":False,"msg":"聊天室名稱不可為空"}), 400

            if not is_private_room and len(name) > 48:
                return json_resp({"ok":False,"msg":"聊天室名稱最多 48 字元"}), 400
            if target_user == actor["username"]:
                return json_resp({"ok":False,"msg":"不能指定自己為對象"}), 400
            if not allow_anonymous:
                anonymous_enabled = False

            password_hash = None if is_private_room else hash_chat_room_password(join_password)
            cur = conn.execute(
                "INSERT INTO chat_rooms (name, owner_user_id, is_private, join_password_hash, join_password_required, allow_anonymous, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, urow_id, 1 if is_private_room else 0, password_hash, 1 if password_hash else 0, 1 if allow_anonymous and not is_private_room else 0, datetime.now().isoformat())
            )
            room_id = cur.lastrowid
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT OR IGNORE INTO chat_room_members (room_id, user_id, joined_at, anonymous_enabled) VALUES (?, ?, ?, ?)",
                (room_id, urow_id, now, 1 if anonymous_enabled and allow_anonymous and not is_private_room else 0)
            )
            if target_row:
                conn.execute(
                    "INSERT OR IGNORE INTO chat_room_members (room_id, user_id, joined_at, anonymous_enabled) VALUES (?, ?, ?, 0)",
                    (room_id, target_row["id"], now)
                )
            added_usernames = []
            forbidden_usernames = []
            if invite_usernames and not is_private_room:
                user_status_filter = "AND status='active'" if "status" in _table_columns(conn, "users") else ""
                placeholders = ",".join("?" for _ in invite_usernames)
                invite_rows = conn.execute(
                    f"SELECT id, username FROM users WHERE username IN ({placeholders}) {user_status_filter}",
                    tuple(invite_usernames),
                ).fetchall()
                invite_map = {str(row["username"]): row for row in invite_rows}
                for username in invite_usernames:
                    user_row = invite_map.get(username)
                    if not user_row:
                        continue
                    allowed, _deny_msg = assert_can_target_user(conn, actor, user_row["id"], context="private_group")
                    if not allowed:
                        forbidden_usernames.append(user_row["username"])
                        continue
                    conn.execute(
                        "INSERT OR IGNORE INTO chat_room_members (room_id, user_id, joined_at, anonymous_enabled) VALUES (?, ?, ?, 0)",
                        (room_id, user_row["id"], now),
                    )
                    added_usernames.append(user_row["username"])
                    try:
                        ensure_notifications_schema(conn)
                        create_notification(
                            conn,
                            user_id=user_row["id"],
                            type="chat_room_added",
                            title="你已加入聊天室",
                            body=f"{actor['username']} 將你加入聊天室「{name}」。",
                            link="/chat",
                        )
                    except Exception:
                        pass
            if forbidden_usernames:
                conn.rollback()
                return json_resp({
                    "ok": False,
                    "msg": "只能邀請已成為好友的使用者",
                    "forbidden": forbidden_usernames,
                }), 403
            conn.commit()
            # Escape user-controlled fields (room name, usernames) to prevent
            # log injection — see _audit_safe / issue #179.
            safe_invited = ",".join(_audit_safe(u, max_len=80) for u in added_usernames)
            safe_forbidden = ",".join(_audit_safe(u, max_len=80) for u in forbidden_usernames)
            detail = (
                f"room_id={room_id}, name={_audit_safe(name)}, "
                f"is_private={is_private_room}, invited={safe_invited}, forbidden={safe_forbidden}"
            )
            if target_row:
                detail += f", target={_audit_safe(target_row['username'], max_len=80)}"
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return json_resp({"ok":False,"msg":"建立聊天室失敗"}), 500
        finally:
            conn.close()

        if detail:
            try:
                audit("CHAT_ROOM_CREATED", ip, user=actor["username"], detail=detail)
            except Exception:
                pass
        invite_username = target_row["username"] if target_row else None
        return json_resp({
            "ok": True,
            "msg": "私人訊息聊天室已建立" if is_private_room else "聊天室已建立",
            "room": {
                "id": room_id,
                "name": name,
                "owner_user_id": urow_id,
                "owner_username": actor["username"],
                "target_username": invite_username,
                "is_private": 1 if is_private_room else 0,
                "join_password_required": bool(join_password and not is_private_room),
                "allow_anonymous": bool(allow_anonymous and not is_private_room),
                "anonymous_enabled": bool(anonymous_enabled and allow_anonymous and not is_private_room),
            },
            "forbidden": forbidden_usernames,
        })

    @app.route("/api/chat/rooms/<int:room_id>/join", methods=["POST"], strict_slashes=False)
    @require_csrf
    def chat_room_join(room_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_id = actor["id"]
        conn = get_db()
        try:
            ensure_chat_feature_schema(conn)
            room = conn.execute(
                "SELECT r.id, r.name, r.owner_user_id, r.is_private, r.join_password_hash, "
                "COALESCE(r.allow_anonymous, 0) AS allow_anonymous, "
                "COALESCE(r.join_password_required, 0) AS join_password_required, u.username AS owner_username "
                "FROM chat_rooms r LEFT JOIN users u ON u.id=r.owner_user_id WHERE r.id=? AND COALESCE(r.is_active, 1)=1",
                (room_id,)
            ).fetchone()
            if not room:
                return json_resp({"ok":False,"msg":"找不到聊天室"}), 404
            existing_member = conn.execute(
                "SELECT 1 FROM chat_room_members WHERE room_id=? AND user_id=?",
                (room_id, actor_id)
            ).fetchone()
            if existing_member:
                return json_resp({"ok":True,"msg":"已加入聊天室","room":{"id":room["id"],"name":room["name"],"allow_anonymous":bool(room["allow_anonymous"])}})
            if room["is_private"]:
                return json_resp({"ok":False,"msg":"這是私人聊天室，無法直接加入"}), 403
            try:
                data = request.get_json(silent=True) or {}
            except Exception:
                data = {}
            pending_invite = conn.execute(
                "SELECT id FROM chat_room_invites WHERE room_id=? AND invitee_user_id=? AND status='pending'",
                (room_id, actor_id),
            ).fetchone()
            password = ""
            if room["join_password_required"]:
                password = str(data.get("password") or "")
                blocked, info = check_user_rate_limit(actor_id, f"chat_join_password:{room_id}", max_req=10, window_sec=60)
                if blocked:
                    audit("CHAT_JOIN_RATE_LIMITED", get_client_ip(), user=actor["username"], detail=f"room_id={room_id},limit={info['limit']}")
                    return json_resp({"ok":False,"msg":f"聊天室密碼嘗試過於頻繁（每分鐘最多 {info['limit']} 次）"}), 429
                if not verify_chat_room_password(room["join_password_hash"], password):
                    audit("CHAT_JOIN_DENIED", get_client_ip(), user=actor["username"], detail=f"room_id={room_id},reason=bad_password")
                    return json_resp({"ok":False,"msg":"聊天室密碼錯誤"}), 403
            is_public_official = room["name"] == OFFICIAL_CHAT_ROOM_NAME and room["owner_username"] == "root"
            if not is_public_official and not pending_invite and not room["join_password_required"]:
                audit("CHAT_JOIN_DENIED", get_client_ip(), user=actor["username"], detail=f"room_id={room_id},owner={room['owner_username'] or '-'}")
                return json_resp({"ok":False,"msg":"你需要邀請或聊天室密碼才能加入"}), 403
            anonymous_enabled = truthy_payload(data.get("anonymous") if "anonymous" in data else data.get("anonymous_enabled"))
            anonymous_enabled = bool(anonymous_enabled and room["allow_anonymous"] and not room["is_private"])
            conn.execute(
                "INSERT OR IGNORE INTO chat_room_members (room_id, user_id, joined_at, anonymous_enabled) VALUES (?, ?, ?, ?)",
                (room_id, actor_id, datetime.now().isoformat(), 1 if anonymous_enabled else 0)
            )
            if pending_invite:
                conn.execute(
                    "UPDATE chat_room_invites SET status='accepted', updated_at=? WHERE id=?",
                    (datetime.now().isoformat(), pending_invite["id"]),
                )
            conn.commit()
            audit("CHAT_ROOM_JOIN", get_client_ip(), user=actor["username"], detail=f"room_id={room_id}")
            return json_resp({"ok":True,"msg":"已加入聊天室","room":{"id":room["id"],"name":room["name"],"allow_anonymous":bool(room["allow_anonymous"]),"anonymous_enabled":anonymous_enabled}})
        finally:
            conn.close()

    @app.route("/api/chat/rooms/<int:room_id>", methods=["DELETE"], strict_slashes=False)
    @require_csrf
    def delete_chat_room(room_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        conn = get_db()
        try:
            ensure_chat_feature_schema(conn)
            room = conn.execute(
                "SELECT r.id, r.name, r.owner_user_id, r.is_private, COALESCE(r.is_active, 1) AS is_active, "
                "u.username AS owner_username, u.role AS owner_role "
                "FROM chat_rooms r LEFT JOIN users u ON u.id=r.owner_user_id WHERE r.id=?",
                (room_id,),
            ).fetchone()
            if not room or not room["is_active"]:
                return json_resp({"ok":False,"msg":"找不到聊天室"}), 404
            if is_official_chat_room(room):
                return json_resp({"ok":False,"msg":"官方聊天室不可刪除"}), 403
            member = conn.execute(
                "SELECT 1 FROM chat_room_members WHERE room_id=? AND user_id=?",
                (room_id, actor["id"]),
            ).fetchone()
            if actor["username"] != "root" and not member and role_rank(actor_role(actor)) < role_rank("manager"):
                return json_resp({"ok":False,"msg":"你不在此聊天室"}), 403
            if not can_delete_chat_room(actor, room, role_rank):
                return json_resp({"ok":False,"msg":"你沒有刪除此聊天室的權限"}), 403
            conn.execute("UPDATE chat_rooms SET is_active=0 WHERE id=?", (room_id,))
            conn.commit()
            audit(
                "CHAT_ROOM_DELETED",
                get_client_ip(),
                user=actor["username"],
                detail=f"room_id={room_id},name={room['name']},owner={room['owner_username'] or '-'}",
            )
            return json_resp({"ok":True,"msg":"聊天室已刪除"})
        finally:
            conn.close()

    @app.route("/api/chat/rooms/<int:room_id>/invites", methods=["POST"], strict_slashes=False)
    @require_csrf
    def invite_chat_room_members(room_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        usernames = normalize_username_list(data.get("usernames") or data.get("username"))
        usernames = [item for item in usernames if item != actor["username"]]
        if not usernames:
            return json_resp({"ok":False,"msg":"請輸入要邀請的帳號"}), 400
        conn = get_db()
        try:
            ensure_chat_feature_schema(conn)
            room = conn.execute(
                "SELECT r.id, r.name, r.owner_user_id, r.is_private, COALESCE(r.is_active, 1) AS is_active "
                "FROM chat_rooms r WHERE r.id=?",
                (room_id,),
            ).fetchone()
            if not room or not room["is_active"]:
                return json_resp({"ok":False,"msg":"找不到聊天室"}), 404
            if room["is_private"]:
                return json_resp({"ok":False,"msg":"私人一對一聊天室不可邀請第三人"}), 403
            member = conn.execute(
                "SELECT 1 FROM chat_room_members WHERE room_id=? AND user_id=?",
                (room_id, actor["id"]),
            ).fetchone()
            if actor["username"] != "root" and room["owner_user_id"] != actor["id"] and not member:
                return json_resp({"ok":False,"msg":"你不在此聊天室"}), 403
            now = datetime.now().isoformat()
            user_status_filter = "AND status='active'" if "status" in _table_columns(conn, "users") else ""
            invited = []
            missing = []
            forbidden = []
            target_context = "official_chat" if is_official_chat_room(room) else "private_group"
            for username in usernames:
                user_row = conn.execute(
                    f"SELECT id, username FROM users WHERE username=? {user_status_filter}",
                    (username,),
                ).fetchone()
                if not user_row:
                    missing.append(username)
                    continue
                allowed, _deny_msg = assert_can_target_user(conn, actor, user_row["id"], context=target_context)
                if not allowed:
                    forbidden.append(user_row["username"])
                    continue
                if conn.execute("SELECT 1 FROM chat_room_members WHERE room_id=? AND user_id=?", (room_id, user_row["id"])).fetchone():
                    continue
                conn.execute(
                    """
                    INSERT INTO chat_room_invites (room_id, inviter_user_id, invitee_user_id, status, created_at, updated_at)
                    VALUES (?, ?, ?, 'pending', ?, ?)
                    ON CONFLICT(room_id, invitee_user_id) DO UPDATE SET
                        inviter_user_id=excluded.inviter_user_id,
                        status='pending',
                        updated_at=excluded.updated_at
                    """,
                    (room_id, actor["id"], user_row["id"], now, now),
                )
                create_notification(
                    conn,
                    user_id=user_row["id"],
                    type="chat_room_invite",
                    title="聊天室邀請",
                    body=f"{actor['username']} 邀請你加入聊天室「{room['name']}」。可在聊天室輸入 ID {room_id} 加入。",
                    link="/chat",
                )
                invited.append(user_row["username"])
            conn.commit()
            safe_invited_csv = ",".join(_audit_safe(u, max_len=80) for u in invited)
            safe_missing_csv = ",".join(_audit_safe(u, max_len=80) for u in missing)
            safe_forbidden_csv = ",".join(_audit_safe(u, max_len=80) for u in forbidden)
            audit(
                "CHAT_ROOM_INVITE", get_client_ip(),
                user=actor["username"],
                detail=f"room_id={room_id},invited={safe_invited_csv},missing={safe_missing_csv},forbidden={safe_forbidden_csv}",
            )
            if forbidden and not invited:
                return json_resp({"ok":False,"msg":"只能邀請已成為好友的使用者","invited":invited,"missing":missing,"forbidden":forbidden}), 403
            return json_resp({"ok":True,"msg":"聊天室邀請已送出","invited":invited,"missing":missing,"forbidden":forbidden})
        finally:
            conn.close()

    @app.route("/api/chat/rooms/<int:room_id>/export", methods=["GET"], strict_slashes=False)
    @require_csrf_safe
    def export_chat_room(room_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        conn = get_db()
        try:
            ensure_chat_feature_schema(conn)
            room = conn.execute(
                "SELECT r.id, r.name, r.owner_user_id, r.is_private, r.created_at, COALESCE(r.is_active, 1) AS is_active, "
                "COALESCE(r.allow_anonymous, 0) AS allow_anonymous, "
                "u.username AS owner_username FROM chat_rooms r LEFT JOIN users u ON u.id=r.owner_user_id WHERE r.id=?",
                (room_id,),
            ).fetchone()
            if not room or not room["is_active"]:
                return json_resp({"ok":False,"msg":"找不到聊天室"}), 404
            member = conn.execute("SELECT 1 FROM chat_room_members WHERE room_id=? AND user_id=?", (room_id, actor["id"])).fetchone()
            if actor["username"] != "root" and not member:
                return json_resp({"ok":False,"msg":"你不在此聊天室"}), 403
            rows = conn.execute(
                "SELECT m.id, m.sender_id, u.username, u.username AS sender, u.role AS sender_role, u.avatar_file_id, "
                "COALESCE(sm.anonymous_enabled, 0) AS sender_anonymous_enabled, "
                "m.content, m.message_type, m.sticker_key, "
                "m.is_revoked, m.revoked_at, m.edited_at, m.edit_count, m.created_at "
                "FROM chat_messages m LEFT JOIN users u ON u.id=m.sender_id "
                "LEFT JOIN chat_room_members sm ON sm.room_id=m.room_id AND sm.user_id=m.sender_id "
                "WHERE m.room_id=? AND m.is_blocked=0 ORDER BY m.id ASC",
                (room_id,),
            ).fetchall()
            official_aliases = official_chat_sender_aliases(conn, room_id) if is_official_chat_room(room) else {}
            anonymous_aliases = {} if is_official_chat_room(room) else anonymous_chat_sender_aliases(conn, room_id)
            def export_message_payload(row):
                sender_payload = public_chat_sender_payload(
                    row,
                    room=room,
                    actor=actor,
                    official_aliases=official_aliases,
                    anonymous_aliases=anonymous_aliases,
                )
                return {
                    "id": row["id"],
                    "sender": sender_payload["sender"],
                    "sender_original": sender_payload["sender_original"],
                    "content": "（訊息已收回）" if row["is_revoked"] else row["content"],
                    "message_type": "text" if row["is_revoked"] else (row["message_type"] or "text"),
                    "sticker_key": None if row["is_revoked"] else row["sticker_key"],
                    "is_revoked": bool(row["is_revoked"]),
                    "revoked_at": row["revoked_at"],
                    "edited_at": row["edited_at"],
                    "edit_count": row["edit_count"],
                    "created_at": row["created_at"],
                }
            payload = {
                "ok": True,
                "exported_at": datetime.now().isoformat(),
                "room": {
                    "id": room["id"],
                    "name": room["name"],
                    "owner_username": room["owner_username"] or "未知",
                    "is_private": bool(room["is_private"]),
                    "created_at": room["created_at"],
                },
                "messages": [export_message_payload(row) for row in rows],
            }
            audit("CHAT_ROOM_EXPORTED", get_client_ip(), user=actor["username"], detail=f"room_id={room_id},messages={len(rows)}")
            body = json.dumps(payload, ensure_ascii=False, indent=2)
            filename = f"chat_room_{room_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            return Response(body, mimetype="application/json; charset=utf-8", headers={"Content-Disposition": f"attachment; filename={filename}"})
        finally:
            conn.close()

    @app.route("/api/chat/rooms/<int:room_id>/messages", methods=["GET", "POST"], strict_slashes=False)
    @require_csrf_safe
    def chat_messages(room_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        conn = get_db()
        try:
            ensure_chat_feature_schema(conn)
            if request.method == "POST":
                ok, msg, status = require_member_action(actor, "chat_send", conn=conn)
                if not ok:
                    return json_resp({"ok":False,"msg":msg}), status
            ensure_user_official_room_membership(conn, actor["id"])
            conn.commit()
            room = conn.execute(
                "SELECT id, name, is_private, COALESCE(join_password_required, 0) AS join_password_required, "
                "COALESCE(allow_anonymous, 0) AS allow_anonymous, "
                "(SELECT COUNT(*) FROM chat_room_members cm WHERE cm.room_id=chat_rooms.id) AS member_count "
                "FROM chat_rooms WHERE id=? AND COALESCE(is_active, 1)=1",
                (room_id,),
            ).fetchone()
            if not room:
                return json_resp({"ok":False,"msg":"找不到聊天室"}), 404

            member = conn.execute(
                "SELECT 1 FROM chat_room_members WHERE room_id=? AND user_id=?",
                (room_id, actor["id"])
            ).fetchone()
            if not member:
                return json_resp({"ok":False,"msg":"你尚未加入此聊天室"}), 403

            if request.method == "GET":
                limit = parse_positive_int(request.args.get("limit", 50), default=50, min_value=1, max_value=200)
                if limit is None:
                    return json_resp({"ok":False,"msg":"limit 參數錯誤"}), 400
                rows = conn.execute(
                    "SELECT m.id, m.sender_id, cr.owner_user_id, u.username, u.username AS sender_username, u.role AS sender_role, u.avatar_file_id, "
                    "COALESCE(sm.anonymous_enabled, 0) AS sender_anonymous_enabled, "
                    "m.content, m.created_at, "
                    "m.message_type, m.sticker_key, m.is_revoked, m.revoked_at, m.edited_at, m.edit_count, m.is_blocked "
                    "FROM chat_messages m "
                    "LEFT JOIN users u ON u.id = m.sender_id "
                    "LEFT JOIN chat_room_members sm ON sm.room_id=m.room_id AND sm.user_id=m.sender_id "
                    "LEFT JOIN chat_rooms cr ON cr.id=m.room_id "
                    "WHERE m.room_id = ? AND m.is_blocked = 0 "
                    "ORDER BY m.id DESC LIMIT ?",
                    (room_id, limit)
                ).fetchall()
                attachment_map = chat_message_attachment_map(conn, actor, [r["id"] for r in rows])
                pending_report_ids = chat_message_pending_report_ids(conn, [r["id"] for r in rows])
                official_aliases = official_chat_sender_aliases(conn, room_id) if is_official_chat_room(room) else {}
                anonymous_aliases = {} if is_official_chat_room(room) else anonymous_chat_sender_aliases(conn, room_id)
                messages = []
                for r in reversed(rows):
                    mutation_locked = int(r["id"]) in pending_report_ids
                    is_self_only_actor = (
                        r["sender_id"] == actor["id"]
                        and actor["username"] != "root"
                        and role_rank(actor_role(actor)) < role_rank("manager")
                    )
                    can_recall = can_recall_chat_message(actor, r) and not r["is_revoked"] and not mutation_locked
                    can_edit = can_edit_chat_message(actor, r) and not mutation_locked
                    can_delete = (
                        can_delete_chat_message(actor, r, role_rank)
                        and not r["is_revoked"]
                        and not is_self_only_actor
                    )
                    messages.append({
                        "id": r["id"],
                        "content": "（訊息已收回）" if r["is_revoked"] else r["content"],
                        "created_at": r["created_at"],
                        "edited_at": None if r["is_revoked"] else r["edited_at"],
                        "edit_count": 0 if r["is_revoked"] else int(r["edit_count"] or 0),
                        "message_type": "text" if r["is_revoked"] else (r["message_type"] or "text"),
                        "sticker_key": None if r["is_revoked"] else r["sticker_key"],
                        "sticker": None if r["is_revoked"] else CHAT_STICKERS.get(r["sticker_key"] or ""),
                        "is_revoked": bool(r["is_revoked"]),
                        "revoked_at": r["revoked_at"],
                        "can_recall": can_recall,
                        "can_edit": can_edit,
                        "can_delete": can_delete,
                        "mutation_locked": bool(mutation_locked),
                        "attachments": [] if r["is_revoked"] else attachment_map.get(int(r["id"]), []),
                        **public_chat_sender_payload(
                            r,
                            room=room,
                            actor=actor,
                            official_aliases=official_aliases,
                            anonymous_aliases=anonymous_aliases,
                        ),
                    })
                return json_resp({
                    "ok": True,
                    "room": {
                        "id": room["id"],
                        "name": room["name"],
                        "is_private": room["is_private"],
                        "join_password_required": bool(room["join_password_required"]),
                        "allow_anonymous": bool(room["allow_anonymous"]) and not bool(room["is_private"]),
                        "hide_member_count": is_official_chat_room(room),
                        "member_count": None if is_official_chat_room(room) else room["member_count"],
                    },
                    "messages": messages
                })

            try:
                data = request.get_json(force=True)
            except Exception:
                return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
            if not isinstance(data, dict):
                return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
            message_type = str(data.get("message_type") or "text").strip().lower()
            sticker_key = str(data.get("sticker_key") or "").strip().lower()
            attachment_file_ids = normalize_attachment_file_ids(data.get("attachment_file_ids"))
            if message_type not in {"text", "sticker"}:
                return json_resp({"ok":False,"msg":"不支援的訊息類型"}), 400
            if message_type == "sticker":
                if attachment_file_ids:
                    return json_resp({"ok":False,"msg":"表情包訊息不能同時附加檔案"}), 400
                if sticker_key not in CHAT_STICKERS:
                    return json_resp({"ok":False,"msg":"不支援的表情包"}), 400
                content = f"[sticker:{sticker_key}]"
            else:
                sticker_key = None
                content = sanitize_chat_content(data.get("content"))
                if not content and attachment_file_ids:
                    content = "已分享附件"
            if not content:
                return json_resp({"ok":False,"msg":"訊息不可為空"}), 400
            if len(content) > CHAT_MESSAGE_MAX_LEN:
                return json_resp({"ok":False,"msg":f"訊息過長，最多 {CHAT_MESSAGE_MAX_LEN} 字"}), 400
            blocked, info = check_user_rate_limit(actor["id"], "chat_send", max_req=20, window_sec=60)
            if blocked:
                return json_resp({"ok":False,"msg":f"訊息發送過於頻繁（每分鐘最多 {info['limit']} 則）"}), 429
            if attachment_file_ids and not _table_columns(conn, "uploaded_files"):
                return json_resp({"ok":False,"msg":"附件系統尚未初始化，請先完成雲端硬碟上傳"}), 400
            private_member_rows = []
            if bool(room["is_private"]) and not is_official_chat_room(room):
                private_member_rows = conn.execute(
                    "SELECT user_id FROM chat_room_members WHERE room_id=? AND user_id<>?",
                    (room_id, actor["id"]),
                ).fetchall()
                target_context = "pm" if len(private_member_rows) <= 1 else "private_group"
                for member_row in private_member_rows:
                    allowed, deny_msg = assert_can_target_user(conn, actor, member_row["user_id"], context=target_context)
                    if not allowed:
                        return json_resp({"ok":False,"msg":deny_msg or "你不能向此聊天室發送訊息"}), 403

            is_bad, bad_reason = detect_chat_violation(content)
            if message_type == "text" and is_bad:
                warning_count = int(dict(actor).get("chat_violation_warned") or 0)
                if warning_count == 0:
                    conn.execute(
                        "UPDATE users SET chat_violation_warned = 1, updated_at=? WHERE id=?",
                        (datetime.now().isoformat(), actor["id"])
                    )
                    conn.commit()
                    audit("CHAT_WARNING", get_client_ip(), user=actor["username"], detail=f"room_id={room_id},reason={bad_reason}")
                    return json_resp({
                        "ok":False,
                        "warned":True,
                        "reason":bad_reason,
                        "msg":"訊息含違規內容，已警告一次，請修改後再送出"
                    }), 403

                role = "super_admin" if actor["username"] == "root" else actor["role"]
                action, msg, total = add_violation(
                    actor["id"], actor["username"], role, points=1,
                    reason=f"聊天違規：{bad_reason}", triggered_by="system", actor_username=actor["username"]
                )
                audit("CHAT_VIOLATION", get_client_ip(), user=actor["username"],
                      detail=f"room_id={room_id},reason={bad_reason},action={action},total={total}")
                return json_resp({
                    "ok":False,
                    "warned":True,
                    "reason":bad_reason,
                    "violation_count": total,
                    "msg":msg
                }), 403

            created_at = datetime.now().isoformat()
            cur = conn.execute(
                "INSERT INTO chat_messages (room_id, sender_id, content, message_type, sticker_key, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (room_id, actor["id"], content, message_type, sticker_key, created_at)
            )
            message_id = cur.lastrowid
            if attachment_file_ids:
                ensure_cloud_drive_attachment_schema(conn)
                member_rows = conn.execute("SELECT user_id FROM chat_room_members WHERE room_id=?", (room_id,)).fetchall()
                grant_user_ids = [int(row["user_id"]) for row in member_rows if int(row["user_id"]) != int(actor["id"])]
                for file_id in attachment_file_ids:
                    _, attach_msg = attach_existing_file(
                        conn,
                        actor=actor,
                        file_id=file_id,
                        context_type="chat_message",
                        context_id=str(message_id),
                        grant_user_ids=grant_user_ids,
                        can_preview=True,
                    )
                    if attach_msg:
                        conn.rollback()
                        return json_resp({"ok":False,"msg":attach_msg}), 400
            conn.commit()
            transcript_synced = append_chat_record(room_id, message_id, actor["username"], content, created_at)
            if not transcript_synced:
                audit("CHAT_TRANSCRIPT_WRITE_FAILED", get_client_ip(), user=actor["username"], detail=f"room_id={room_id},message_id={message_id}")
            notify_conn = get_db()
            try:
                notification_type = "chat_private_message" if int(room["is_private"] or 0) else "chat_group_message"
                title = "收到私訊" if notification_type == "chat_private_message" else "群聊有新訊息"
                if is_official_chat_room(room):
                    body = f"「{room['name']}」有新訊息。"
                else:
                    body = (
                        f"{actor['username']} 傳送了一則私訊。"
                        if notification_type == "chat_private_message"
                        else f"{actor['username']} 在「{room['name']}」傳送了新訊息。"
                    )
                member_rows = notify_conn.execute(
                    "SELECT user_id FROM chat_room_members WHERE room_id=? AND user_id<>?",
                    (room_id, actor["id"]),
                ).fetchall()
                for member_row in member_rows:
                    create_notification_if_enabled(
                        notify_conn,
                        user_id=member_row["user_id"],
                        type=notification_type,
                        title=title,
                        body=body,
                        link=f"/chat?room_id={room_id}",
                    )
                notify_conn.commit()
            except Exception:
                try:
                    notify_conn.rollback()
                except Exception:
                    pass
            finally:
                notify_conn.close()
            return json_resp({"ok":True,"msg":"訊息已送出","message_id":message_id,"transcript_synced":transcript_synced})
        finally:
            conn.close()

    @app.route("/api/chat/messages/<int:message_id>/report", methods=["POST"], strict_slashes=False)
    @require_csrf
    def report_chat_message(message_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        reason = normalize_text(data.get("reason")) or "使用者檢舉"
        if len(reason) > 200:
            return json_resp({"ok":False,"msg":"檢舉原因請控制在 200 字以內"}), 400

        conn = get_db()
        try:
            ensure_chat_feature_schema(conn)
            msg = conn.execute(
                "SELECT m.id, m.room_id, m.sender_id, m.content, m.is_revoked, m.created_at, m.edited_at, u.username AS sender_username "
                "FROM chat_messages m LEFT JOIN users u ON u.id=m.sender_id WHERE m.id=?",
                (message_id,)
            ).fetchone()
            if not msg:
                return json_resp({"ok":False,"msg":"找不到訊息"}), 404
            if msg["is_revoked"]:
                return json_resp({"ok":False,"msg":"訊息已收回，不能檢舉"}), 400
            if msg["sender_id"] == actor["id"]:
                return json_resp({"ok":False,"msg":"不能檢舉自己的訊息"}), 400
            member = conn.execute(
                "SELECT 1 FROM chat_room_members WHERE room_id=? AND user_id=?",
                (msg["room_id"], actor["id"])
            ).fetchone()
            if not member:
                return json_resp({"ok":False,"msg":"找不到訊息"}), 404
            try:
                conn.execute(
                    "INSERT INTO chat_message_reports "
                    "(message_id, room_id, reporter_user_id, reported_user_id, reason, content_snapshot, message_created_at, message_edited_at, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        message_id,
                        msg["room_id"],
                        actor["id"],
                        msg["sender_id"],
                        reason,
                        msg["content"],
                        msg["created_at"],
                        msg["edited_at"],
                        datetime.now().isoformat(),
                    )
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return json_resp({"ok":False,"msg":"你已檢舉過這則訊息"}), 409
            audit("CHAT_MESSAGE_REPORTED", get_client_ip(), user=actor["username"],
                  detail=f"message_id={message_id},reported={msg['sender_username']},reason={reason}")
            return json_resp({"ok":True,"msg":"檢舉已送出，等待超級管理員審核"})
        finally:
            conn.close()

    @app.route("/api/chat/messages/<int:message_id>", methods=["PUT"], strict_slashes=False)
    @require_csrf
    def edit_chat_message(message_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg":"請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"請求內容格式錯誤"}), 400
        content = sanitize_chat_content(data.get("content"))
        if not content:
            return json_resp({"ok":False,"msg":"訊息不可為空"}), 400
        if len(content) > CHAT_MESSAGE_MAX_LEN:
            return json_resp({"ok":False,"msg":f"訊息過長，最多 {CHAT_MESSAGE_MAX_LEN} 字"}), 400

        conn = get_db()
        try:
            ensure_chat_feature_schema(conn)
            ok, msg_text, status = require_member_action(actor, "chat_send", conn=conn)
            if not ok:
                return json_resp({"ok":False,"msg":msg_text}), status
            msg = conn.execute(
                "SELECT m.id, m.room_id, m.sender_id, m.content, m.message_type, m.is_blocked, m.is_revoked, "
                "m.created_at, m.edited_at, m.edit_count, m.original_content "
                "FROM chat_messages m WHERE m.id=?",
                (message_id,),
            ).fetchone()
            if not msg:
                return json_resp({"ok":False,"msg":"找不到訊息"}), 404
            member = conn.execute(
                "SELECT 1 FROM chat_room_members WHERE room_id=? AND user_id=?",
                (msg["room_id"], actor["id"]),
            ).fetchone()
            if actor["username"] != "root" and not member:
                return json_resp({"ok":False,"msg":"找不到訊息"}), 404
            if msg["sender_id"] != actor["id"]:
                return json_resp({"ok":False,"msg":"只能編輯自己的訊息"}), 403
            lock_msg = chat_message_mutation_lock_message(conn, message_id)
            if lock_msg:
                return json_resp({"ok":False,"msg":lock_msg}), 409
            if msg["is_revoked"]:
                return json_resp({"ok":False,"msg":"訊息已收回，不能編輯"}), 409
            if msg["is_blocked"]:
                return json_resp({"ok":False,"msg":"訊息已刪除，不能編輯"}), 409
            if (msg["message_type"] or "text") != "text":
                return json_resp({"ok":False,"msg":"表情包訊息不能編輯"}), 400
            if not can_edit_chat_message(actor, msg):
                return json_resp({"ok":False,"msg":"留言只能在送出後 5 分鐘內編輯"}), 403
            if content == msg["content"]:
                return json_resp({"ok":True,"msg":"訊息未變更"})
            blocked, info = check_user_rate_limit(actor["id"], "chat_edit", max_req=20, window_sec=60)
            if blocked:
                return json_resp({"ok":False,"msg":f"訊息編輯過於頻繁（每分鐘最多 {info['limit']} 次）"}), 429
            is_bad, bad_reason = detect_chat_violation(content)
            if is_bad:
                return json_resp({
                    "ok": False,
                    "warned": True,
                    "reason": bad_reason,
                    "msg": "編輯內容含違規內容，請修改後再儲存",
                }), 403
            edited_at = datetime.now().isoformat()
            original_content = msg["original_content"] or msg["content"]
            conn.execute(
                "UPDATE chat_messages "
                "SET content=?, edited_at=?, edited_by=?, edit_count=COALESCE(edit_count, 0)+1, original_content=? "
                "WHERE id=?",
                (content, edited_at, actor["id"], original_content, message_id),
            )
            conn.commit()
            audit(
                "CHAT_MESSAGE_EDITED",
                get_client_ip(),
                user=actor["username"],
                detail=f"message_id={message_id},room_id={msg['room_id']},edit_count={int(msg['edit_count'] or 0) + 1}",
            )
            return json_resp({"ok":True,"msg":"訊息已更新","edited_at":edited_at})
        finally:
            conn.close()

    @app.route("/api/chat/messages/<int:message_id>", methods=["DELETE"], strict_slashes=False)
    @require_csrf
    def delete_chat_message(message_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401

        conn = get_db()
        try:
            ensure_chat_feature_schema(conn)
            msg = conn.execute(
                "SELECT m.id, m.room_id, m.sender_id, m.is_blocked, m.is_revoked, m.created_at, u.username AS sender_username, "
                "u.role AS sender_role, r.owner_user_id "
                "FROM chat_messages m "
                "LEFT JOIN users u ON u.id=m.sender_id "
                "LEFT JOIN chat_rooms r ON r.id=m.room_id "
                "WHERE m.id=?",
                (message_id,),
            ).fetchone()
            if not msg:
                return json_resp({"ok":False,"msg":"找不到訊息"}), 404
            if msg["is_blocked"]:
                return json_resp({"ok":True,"msg":"訊息已刪除"})

            member = conn.execute(
                "SELECT 1 FROM chat_room_members WHERE room_id=? AND user_id=?",
                (msg["room_id"], actor["id"]),
            ).fetchone()
            if actor["username"] != "root" and not member and role_rank(actor_role(actor)) < role_rank("manager"):
                return json_resp({"ok":False,"msg":"你不在此聊天室"}), 403
            if not can_delete_chat_message(actor, msg, role_rank):
                return json_resp({"ok":False,"msg":"你沒有刪除此訊息的權限"}), 403

            is_self_only_recall = msg["sender_id"] == actor["id"] and actor["username"] != "root" and role_rank(actor_role(actor)) < role_rank("manager")
            if is_self_only_recall:
                if msg["is_revoked"]:
                    return json_resp({"ok":True,"msg":"訊息已收回"})
                lock_msg = chat_message_mutation_lock_message(conn, message_id)
                if lock_msg:
                    return json_resp({"ok":False,"msg":lock_msg}), 409
                if not can_recall_chat_message(actor, msg):
                    return json_resp({"ok":False,"msg":"留言只能在送出後 5 分鐘內收回"}), 403
                conn.execute(
                    "UPDATE chat_messages SET is_revoked=1, revoked_at=?, revoked_by=? WHERE id=?",
                    (datetime.now().isoformat(), actor["id"], message_id),
                )
                conn.commit()
                audit(
                    "CHAT_MESSAGE_RECALLED",
                    get_client_ip(),
                    user=actor["username"],
                    detail=f"message_id={message_id},room_id={msg['room_id']}",
                )
                return json_resp({"ok":True,"msg":"訊息已收回"})

            conn.execute(
                "UPDATE chat_messages SET is_blocked=1, blocked_reason=? WHERE id=?",
                (f"deleted_by={actor['username']}", message_id),
            )
            conn.commit()
            audit(
                "CHAT_MESSAGE_DELETED",
                get_client_ip(),
                user=actor["username"],
                detail=f"message_id={message_id},room_id={msg['room_id']},target={msg['sender_username'] or '-'}",
            )
            return json_resp({"ok":True,"msg":"訊息已刪除"})
        finally:
            conn.close()

    @app.route("/api/chat/friends", methods=["GET"], strict_slashes=False)
    @require_csrf_safe
    def chat_friends():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        conn = get_db()
        try:
            ensure_chat_feature_schema(conn)
            state = list_friend_state(conn, actor)
            return json_resp({"ok":True, **state})
        finally:
            conn.close()

    @app.route("/api/chat/friends/requests", methods=["POST"], strict_slashes=False)
    @require_csrf
    def chat_friend_request():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        username = normalize_text(data.get("username"))
        if not username:
            return json_resp({"ok":False,"msg":"請輸入好友帳號"}), 400
        conn = get_db()
        try:
            ensure_chat_feature_schema(conn)
            result, msg, status = create_friend_request(conn, actor, username=username)
            if status < 400:
                conn.commit()
                target = (result or {}).get("target") or {}
                audit("CHAT_FRIEND_REQUESTED", get_client_ip(), user=actor["username"], detail=f"target={target.get('username')}")
                return json_resp({"ok":True,"msg":msg,"request":result})
            return json_resp({"ok":False,"msg":msg}), status
        finally:
            conn.close()

    @app.route("/api/chat/friends/requests/<int:request_id>/<decision>", methods=["POST"], strict_slashes=False)
    @require_csrf
    def chat_friend_review(request_id, decision):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        conn = get_db()
        try:
            ensure_chat_feature_schema(conn)
            result, msg, status = review_friend_request(conn, actor, request_id=request_id, decision=decision)
            if status < 400:
                conn.commit()
                audit("CHAT_FRIEND_REVIEWED", get_client_ip(), user=actor["username"], detail=f"request_id={request_id},decision={decision}")
                return json_resp({"ok":True,"msg":msg,"request":result})
            return json_resp({"ok":False,"msg":msg}), status
        finally:
            conn.close()

    @app.route("/api/chat/friends/<int:friend_user_id>", methods=["DELETE"], strict_slashes=False)
    @require_csrf
    def chat_friend_delete(friend_user_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        conn = get_db()
        try:
            ensure_chat_feature_schema(conn)
            ok, msg, status = remove_friend(conn, actor, friend_user_id=friend_user_id)
            if ok:
                conn.commit()
                audit("CHAT_FRIEND_REMOVED", get_client_ip(), user=actor["username"], detail=f"friend_user_id={friend_user_id}")
                return json_resp({"ok":True,"msg":msg})
            return json_resp({"ok":False,"msg":msg}), status
        finally:
            conn.close()

    @app.route("/api/chat/friends/<int:target_user_id>/block", methods=["POST"], strict_slashes=False)
    @require_csrf
    def chat_friend_block(target_user_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        conn = get_db()
        try:
            ensure_chat_feature_schema(conn)
            result, msg, status = block_user(conn, actor, target_user_id=target_user_id)
            if status < 400:
                conn.commit()
                target = (result or {}).get("target") or {}
                audit("CHAT_FRIEND_BLOCKED", get_client_ip(), user=actor["username"], detail=f"target_user_id={target.get('id')}")
                return json_resp({"ok":True,"msg":msg,"block":result})
            return json_resp({"ok":False,"msg":msg}), status
        finally:
            conn.close()

    @app.route("/api/chat/friends/<int:target_user_id>/block", methods=["DELETE"], strict_slashes=False)
    @require_csrf
    def chat_friend_unblock(target_user_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        conn = get_db()
        try:
            ensure_chat_feature_schema(conn)
            ok, msg, status = unblock_user(conn, actor, target_user_id=target_user_id)
            if ok:
                conn.commit()
                audit("CHAT_FRIEND_UNBLOCKED", get_client_ip(), user=actor["username"], detail=f"target_user_id={target_user_id}")
                return json_resp({"ok":True,"msg":msg})
            return json_resp({"ok":False,"msg":msg}), status
        finally:
            conn.close()

    @app.route("/api/audit", methods=["GET"])
    def api_audit():
        tok = request.cookies.get("session_token")
        user = db_get_user_from_token(tok) if tok else None
        if not user: return json_resp({"ok":False,"msg":"未授權"}), 401
        if user != "root":
            audit("AUDIT_FORBIDDEN", get_client_ip(), user, detail="non-root attempted audit access")
            return json_resp({"ok":False,"msg":"只有 root 可檢視審計紀錄"}), 403

        auth_conn = get_auth_db()
        main_conn = get_db()
        try:
            rows = auth_conn.execute(
                "SELECT user_id, ip_address, user_agent, success, attempted_at "
                "FROM login_attempts ORDER BY attempted_at DESC LIMIT 200"
            ).fetchall()
            user_ids = sorted({int(r["user_id"]) for r in rows if r["user_id"] is not None})
            usernames = {}
            if user_ids:
                placeholders = ",".join("?" for _ in user_ids)
                for row in main_conn.execute(
                    f"SELECT id, username FROM users WHERE id IN ({placeholders})",
                    tuple(user_ids),
                ).fetchall():
                    usernames[int(row["id"])] = row["username"]
        finally:
            auth_conn.close()
            main_conn.close()

        entries = []
        for r in rows:
            entries.append({
                "user":      (usernames.get(int(r["user_id"])) if r["user_id"] is not None else None) or "(未知)",
                "ip":        r["ip_address"],
                "ua":        r["user_agent"],
                "success":   bool(r["success"]),
                "time":      r["attempted_at"],
            })
        return json_resp({"ok":True,"entries":entries})
