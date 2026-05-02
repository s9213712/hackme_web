import hashlib
import json
import re
import secrets
import sqlite3
from datetime import datetime, timedelta
from flask import Response, request

from services.cloud_drive import attach_existing_file, can_download_file, ensure_cloud_drive_attachment_schema
from services.notifications import create_notification, create_notification_if_enabled, ensure_notifications_schema
from services.permissions import require_member_action
from services.sqlite_safe import table_columns as safe_table_columns

CHAT_RECALL_WINDOW_SECONDS = 5 * 60
CHAT_BACKUP_FORMAT = "hackme_web.chat.backup"
CHAT_BACKUP_VERSION = 1
CHAT_BACKUP_MAX_MESSAGES = 5000
CHAT_BACKUP_MAX_BYTES = 2 * 1024 * 1024
CHAT_STICKERS = {
    "smile": {"label": "微笑", "glyph": ":)"},
    "thanks": {"label": "感謝", "glyph": "THX"},
    "ok": {"label": "了解", "glyph": "OK"},
    "wow": {"label": "驚訝", "glyph": "WOW"},
    "cheer": {"label": "加油", "glyph": "GO"},
    "sad": {"label": "難過", "glyph": ":("},
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


def sanitize_chat_content(value):
    """Store chat as plain text so saved messages cannot become stored HTML."""
    if value is None:
        return ""
    text = str(value).replace("\x00", "").strip()
    return CHAT_HTML_TAG_RE.sub("", text).strip()


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
    )
    for name, ddl in room_additions:
        if name not in room_cols:
            conn.execute(f"ALTER TABLE chat_rooms ADD COLUMN {name} {ddl}")
    cols = _table_columns(conn, "chat_messages")
    additions = (
        ("message_type", "TEXT NOT NULL DEFAULT 'text'"),
        ("sticker_key", "TEXT"),
        ("is_revoked", "INTEGER NOT NULL DEFAULT 0"),
        ("revoked_at", "TEXT"),
        ("revoked_by", "INTEGER"),
    )
    for name, ddl in additions:
        if name not in cols:
            conn.execute(f"ALTER TABLE chat_messages ADD COLUMN {name} {ddl}")
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
        SELECT r.id AS ref_id, r.context_id AS message_id, r.file_id, r.context_type, r.context_id,
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
                            "member_count": r["member_count"],
                            "created_at": r["created_at"]
                        } for r in rows
                    ]
                })
            finally:
                conn.close()

        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        name = normalize_text(data.get("name"))
        target_user = normalize_text(data.get("target_user"))
        invite_usernames = normalize_username_list(data.get("invite_usernames"))
        join_password = str(data.get("join_password") or "")
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
            elif not name:
                return json_resp({"ok":False,"msg":"聊天室名稱不可為空"}), 400

            if not is_private_room and len(name) > 48:
                return json_resp({"ok":False,"msg":"聊天室名稱最多 48 字元"}), 400
            if target_user == actor["username"]:
                return json_resp({"ok":False,"msg":"不能指定自己為對象"}), 400

            password_hash = None if is_private_room else hash_chat_room_password(join_password)
            cur = conn.execute(
                "INSERT INTO chat_rooms (name, owner_user_id, is_private, join_password_hash, join_password_required, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (name, urow_id, 1 if is_private_room else 0, password_hash, 1 if password_hash else 0, datetime.now().isoformat())
            )
            room_id = cur.lastrowid
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT OR IGNORE INTO chat_room_members (room_id, user_id, joined_at) VALUES (?, ?, ?)",
                (room_id, urow_id, now)
            )
            if target_row:
                conn.execute(
                    "INSERT OR IGNORE INTO chat_room_members (room_id, user_id, joined_at) VALUES (?, ?, ?)",
                    (room_id, target_row["id"], now)
                )
            added_usernames = []
            if invite_usernames and not is_private_room:
                user_status_filter = "AND status='active'" if "status" in _table_columns(conn, "users") else ""
                for username in invite_usernames:
                    user_row = conn.execute(
                        f"SELECT id, username FROM users WHERE username=? {user_status_filter}",
                        (username,),
                    ).fetchone()
                    if not user_row:
                        continue
                    conn.execute(
                        "INSERT OR IGNORE INTO chat_room_members (room_id, user_id, joined_at) VALUES (?, ?, ?)",
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
            conn.commit()
            detail = f"room_id={room_id}, name={name}, is_private={is_private_room}, invited={','.join(added_usernames)}"
            if target_row:
                detail += f", target={target_row['username']}"
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
                "join_password_required": bool(join_password and not is_private_room)
            }
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
                return json_resp({"ok":True,"msg":"已加入聊天室","room":{"id":room["id"],"name":room["name"]}})
            if room["is_private"]:
                return json_resp({"ok":False,"msg":"這是私人聊天室，無法直接加入"}), 403
            pending_invite = conn.execute(
                "SELECT id FROM chat_room_invites WHERE room_id=? AND invitee_user_id=? AND status='pending'",
                (room_id, actor_id),
            ).fetchone()
            password = ""
            if room["join_password_required"]:
                try:
                    data = request.get_json(silent=True) or {}
                except Exception:
                    data = {}
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
            conn.execute(
                "INSERT OR IGNORE INTO chat_room_members (room_id, user_id, joined_at) VALUES (?, ?, ?)",
                (room_id, actor_id, datetime.now().isoformat())
            )
            if pending_invite:
                conn.execute(
                    "UPDATE chat_room_invites SET status='accepted', updated_at=? WHERE id=?",
                    (datetime.now().isoformat(), pending_invite["id"]),
                )
            conn.commit()
            audit("CHAT_ROOM_JOIN", get_client_ip(), user=actor["username"], detail=f"room_id={room_id}")
            return json_resp({"ok":True,"msg":"已加入聊天室","room":{"id":room["id"],"name":room["name"]}})
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
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
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
            for username in usernames:
                user_row = conn.execute(
                    f"SELECT id, username FROM users WHERE username=? {user_status_filter}",
                    (username,),
                ).fetchone()
                if not user_row:
                    missing.append(username)
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
            audit("CHAT_ROOM_INVITE", get_client_ip(), user=actor["username"], detail=f"room_id={room_id},invited={','.join(invited)},missing={','.join(missing)}")
            return json_resp({"ok":True,"msg":"聊天室邀請已送出","invited":invited,"missing":missing})
        finally:
            conn.close()

    @app.route("/api/chat/rooms/<int:room_id>/backup", methods=["GET"], strict_slashes=False)
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
                "u.username AS owner_username FROM chat_rooms r LEFT JOIN users u ON u.id=r.owner_user_id WHERE r.id=?",
                (room_id,),
            ).fetchone()
            if not room or not room["is_active"]:
                return json_resp({"ok":False,"msg":"找不到聊天室"}), 404
            member = conn.execute("SELECT 1 FROM chat_room_members WHERE room_id=? AND user_id=?", (room_id, actor["id"])).fetchone()
            if actor["username"] != "root" and not member:
                return json_resp({"ok":False,"msg":"你不在此聊天室"}), 403
            rows = conn.execute(
                "SELECT m.id, m.sender_id, u.username AS sender, m.content, m.message_type, m.sticker_key, "
                "m.is_revoked, m.revoked_at, m.created_at "
                "FROM chat_messages m LEFT JOIN users u ON u.id=m.sender_id "
                "WHERE m.room_id=? AND m.is_blocked=0 ORDER BY m.id ASC",
                (room_id,),
            ).fetchall()
            payload = {
                "ok": True,
                "format": CHAT_BACKUP_FORMAT,
                "version": CHAT_BACKUP_VERSION,
                "exported_at": datetime.now().isoformat(),
                "exported_by": actor["username"],
                "truncated": False,
                "room": {
                    "id": room["id"],
                    "name": room["name"],
                    "owner_username": room["owner_username"] or "未知",
                    "is_private": bool(room["is_private"]),
                    "created_at": room["created_at"],
                },
                "messages": [
                    {
                        "id": row["id"],
                        "sender": row["sender"] or "系統",
                        "content": "（訊息已收回）" if row["is_revoked"] else row["content"],
                        "message_type": "text" if row["is_revoked"] else (row["message_type"] or "text"),
                        "sticker_key": None if row["is_revoked"] else row["sticker_key"],
                        "is_revoked": bool(row["is_revoked"]),
                        "revoked_at": row["revoked_at"],
                        "created_at": row["created_at"],
                    }
                    for row in rows
                ],
            }
            audit("CHAT_ROOM_EXPORTED", get_client_ip(), user=actor["username"], detail=f"room_id={room_id},messages={len(rows)}")
            body = json.dumps(payload, ensure_ascii=False, indent=2)
            filename = f"chat_room_{room_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            return Response(body, mimetype="application/json; charset=utf-8", headers={"Content-Disposition": f"attachment; filename={filename}"})
        finally:
            conn.close()

    @app.route("/api/chat/rooms/restore", methods=["POST"], strict_slashes=False)
    @require_csrf
    def restore_chat_room():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        upload = request.files.get("backup_file") if request.files else None
        if not upload:
            return json_resp({"ok":False,"msg":"請上傳聊天室備份檔"}), 400
        try:
            raw = upload.read()
            if len(raw) > CHAT_BACKUP_MAX_BYTES:
                return json_resp({"ok":False,"msg":"聊天室備份檔過大"}), 400
            backup = json.loads(raw.decode("utf-8"))
        except Exception:
            return json_resp({"ok":False,"msg":"聊天室備份檔格式錯誤"}), 400
        if not isinstance(backup, dict) or backup.get("format") != CHAT_BACKUP_FORMAT:
            return json_resp({"ok":False,"msg":"不是本專案聊天室備份檔"}), 400
        if int(backup.get("version") or 0) != CHAT_BACKUP_VERSION:
            return json_resp({"ok":False,"msg":"聊天室備份版本不支援"}), 400
        messages = backup.get("messages")
        if not isinstance(messages, list):
            return json_resp({"ok":False,"msg":"聊天室備份缺少 messages"}), 400
        if len(messages) > CHAT_BACKUP_MAX_MESSAGES:
            return json_resp({"ok":False,"msg":f"聊天室備份訊息過多，最多 {CHAT_BACKUP_MAX_MESSAGES} 則"}), 400
        restored = []
        for item in messages:
            if not isinstance(item, dict):
                return json_resp({"ok":False,"msg":"聊天室備份包含無效訊息"}), 400
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            if len(content) > CHAT_MESSAGE_MAX_LEN:
                return json_resp({"ok":False,"msg":f"訊息過長，最多 {CHAT_MESSAGE_MAX_LEN} 字"}), 400
            is_bad, bad_reason = detect_chat_violation(content)
            if is_bad:
                return json_resp({"ok":False,"msg":f"備份含敏感詞，已拒絕還原：{bad_reason}"}), 403
            restored.append(content)
        room_meta = backup.get("room") if isinstance(backup.get("room"), dict) else {}
        original_name = str(room_meta.get("name") or "聊天室備份").strip()
        requested_name = str(request.form.get("room_name") or "").strip() if request.form else ""
        room_name = (requested_name or f"還原 - {original_name}")[:48].strip() or "還原聊天室"
        conn = get_db()
        try:
            ensure_chat_feature_schema(conn)
            ok, msg, status = require_member_action(actor, "chat_send", conn=conn)
            if not ok:
                return json_resp({"ok":False,"msg":msg}), status
            now = datetime.now().isoformat()
            conn.commit()
            conn.execute("BEGIN")
            cur = conn.execute(
                "INSERT INTO chat_rooms (name, owner_user_id, is_private, created_at) VALUES (?, ?, 1, ?)",
                (room_name, actor["id"], now),
            )
            new_room_id = cur.lastrowid
            conn.execute(
                "INSERT OR IGNORE INTO chat_room_members (room_id, user_id, joined_at) VALUES (?, ?, ?)",
                (new_room_id, actor["id"], now),
            )
            for content in restored:
                restored_content = f"[聊天室備份還原] {actor['username']}：{content}"
                conn.execute(
                    "INSERT INTO chat_messages (room_id, sender_id, content, message_type, sticker_key, created_at) VALUES (?, ?, ?, 'text', NULL, ?)",
                    (new_room_id, actor["id"], restored_content[:CHAT_MESSAGE_MAX_LEN], now),
                )
            conn.commit()
            audit("CHAT_ROOM_RESTORED", get_client_ip(), user=actor["username"], detail=f"new_room_id={new_room_id},messages={len(restored)},source_room={original_name[:80]}")
            return json_resp({
                "ok": True,
                "msg": "聊天室備份已還原為新聊天室",
                "room": {"id": new_room_id, "name": room_name, "owner_user_id": actor["id"], "owner_username": actor["username"], "is_private": 1},
                "restored_messages": len(restored),
            })
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            audit("CHAT_ROOM_RESTORE_FAILED", get_client_ip(), user=actor["username"], success=False, detail=str(exc))
            return json_resp({"ok":False,"msg":"聊天室備份還原失敗"}), 500
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
                    "SELECT m.id, m.sender_id, u.username, m.content, m.created_at, "
                    "m.message_type, m.sticker_key, m.is_revoked, m.revoked_at "
                    "FROM chat_messages m "
                    "LEFT JOIN users u ON u.id = m.sender_id "
                    "WHERE m.room_id = ? AND m.is_blocked = 0 "
                    "ORDER BY m.id DESC LIMIT ?",
                    (room_id, limit)
                ).fetchall()
                attachment_map = chat_message_attachment_map(conn, actor, [r["id"] for r in rows])
                messages = [
                    {
                        "id": r["id"],
                        "sender_id": r["sender_id"],
                        "sender": r["username"] or "系統",
                        "content": "（訊息已收回）" if r["is_revoked"] else r["content"],
                        "created_at": r["created_at"],
                        "message_type": "text" if r["is_revoked"] else (r["message_type"] or "text"),
                        "sticker_key": None if r["is_revoked"] else r["sticker_key"],
                        "sticker": None if r["is_revoked"] else CHAT_STICKERS.get(r["sticker_key"] or ""),
                        "is_revoked": bool(r["is_revoked"]),
                        "revoked_at": r["revoked_at"],
                        "can_recall": can_recall_chat_message(actor, r) and not r["is_revoked"],
                        "attachments": [] if r["is_revoked"] else attachment_map.get(int(r["id"]), []),
                    } for r in reversed(rows)
                ]
                return json_resp({
                    "ok": True,
                    "room": {
                        "id": room["id"],
                        "name": room["name"],
                        "is_private": room["is_private"],
                        "join_password_required": bool(room["join_password_required"]),
                        "member_count": room["member_count"],
                    },
                    "messages": messages
                })

            try:
                data = request.get_json(force=True)
            except Exception:
                return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
            if not isinstance(data, dict):
                return json_resp({"ok":False,"msg":"Invalid request"}), 400
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
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        reason = normalize_text(data.get("reason")) or "使用者檢舉"
        if len(reason) > 200:
            return json_resp({"ok":False,"msg":"檢舉原因請控制在 200 字以內"}), 400

        conn = get_db()
        try:
            ensure_chat_feature_schema(conn)
            msg = conn.execute(
                "SELECT m.id, m.room_id, m.sender_id, m.content, u.username AS sender_username "
                "FROM chat_messages m LEFT JOIN users u ON u.id=m.sender_id WHERE m.id=?",
                (message_id,)
            ).fetchone()
            if not msg:
                return json_resp({"ok":False,"msg":"找不到訊息"}), 404
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
                    "(message_id, room_id, reporter_user_id, reported_user_id, reason, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (message_id, msg["room_id"], actor["id"], msg["sender_id"], reason, datetime.now().isoformat())
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return json_resp({"ok":False,"msg":"你已檢舉過這則訊息"}), 409
            audit("CHAT_MESSAGE_REPORTED", get_client_ip(), user=actor["username"],
                  detail=f"message_id={message_id},reported={msg['sender_username']},reason={reason}")
            return json_resp({"ok":True,"msg":"檢舉已送出，等待超級管理員審核"})
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
            rows = conn.execute(
                """
                SELECT f.id, f.user_id, f.friend_user_id, f.status, f.requested_by, f.created_at, f.updated_at,
                       u1.username AS user_username, u2.username AS friend_username, req.username AS requested_by_username
                FROM user_friends f
                JOIN users u1 ON u1.id=f.user_id
                JOIN users u2 ON u2.id=f.friend_user_id
                LEFT JOIN users req ON req.id=f.requested_by
                WHERE f.user_id=? OR f.friend_user_id=?
                ORDER BY f.updated_at DESC, f.id DESC
                """,
                (actor["id"], actor["id"]),
            ).fetchall()
            friends = []
            incoming = []
            outgoing = []
            for row in rows:
                other_id = row["friend_user_id"] if row["user_id"] == actor["id"] else row["user_id"]
                other_username = row["friend_username"] if row["user_id"] == actor["id"] else row["user_username"]
                item = {
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "friend_user_id": row["friend_user_id"],
                    "other_user_id": other_id,
                    "other_username": other_username,
                    "status": row["status"],
                    "requested_by": row["requested_by"],
                    "requested_by_username": row["requested_by_username"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                if row["status"] == "accepted":
                    friends.append(item)
                elif row["status"] == "pending" and row["requested_by"] == actor["id"]:
                    outgoing.append(item)
                elif row["status"] == "pending":
                    incoming.append(item)
            return json_resp({"ok":True,"friends":friends,"incoming":incoming,"outgoing":outgoing})
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
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        username = normalize_text(data.get("username"))
        if not username:
            return json_resp({"ok":False,"msg":"請輸入好友帳號"}), 400
        if username == actor["username"]:
            return json_resp({"ok":False,"msg":"不能加自己為好友"}), 400
        conn = get_db()
        try:
            ensure_chat_feature_schema(conn)
            user_cols = _table_columns(conn, "users")
            status_filter = "AND status='active'" if "status" in user_cols else ""
            target = conn.execute(f"SELECT id, username FROM users WHERE username=? {status_filter}", (username,)).fetchone()
            if not target:
                return json_resp({"ok":False,"msg":"找不到指定帳號"}), 404
            user_a, user_b = sorted([int(actor["id"]), int(target["id"])])
            existing = conn.execute(
                "SELECT * FROM user_friends WHERE user_id=? AND friend_user_id=?",
                (user_a, user_b),
            ).fetchone()
            now = datetime.now().isoformat()
            if existing:
                if existing["status"] == "accepted":
                    return json_resp({"ok":True,"msg":"已經是好友"})
                if existing["status"] == "pending":
                    return json_resp({"ok":True,"msg":"好友邀請已存在"})
                conn.execute(
                    "UPDATE user_friends SET status='pending', requested_by=?, updated_at=? WHERE id=?",
                    (actor["id"], now, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO user_friends (user_id, friend_user_id, status, requested_by, created_at, updated_at) VALUES (?, ?, 'pending', ?, ?, ?)",
                    (user_a, user_b, actor["id"], now, now),
                )
            conn.commit()
            audit("CHAT_FRIEND_REQUESTED", get_client_ip(), user=actor["username"], detail=f"target={target['username']}")
            return json_resp({"ok":True,"msg":"好友邀請已送出"})
        finally:
            conn.close()

    @app.route("/api/chat/friends/requests/<int:request_id>/<decision>", methods=["POST"], strict_slashes=False)
    @require_csrf
    def chat_friend_review(request_id, decision):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        if decision not in {"accept", "reject"}:
            return json_resp({"ok":False,"msg":"不支援的操作"}), 400
        conn = get_db()
        try:
            ensure_chat_feature_schema(conn)
            row = conn.execute("SELECT * FROM user_friends WHERE id=?", (request_id,)).fetchone()
            if not row:
                return json_resp({"ok":False,"msg":"找不到好友邀請"}), 404
            if row["status"] != "pending":
                return json_resp({"ok":False,"msg":"好友邀請已處理"}), 409
            if row["requested_by"] == actor["id"] or actor["id"] not in {row["user_id"], row["friend_user_id"]}:
                return json_resp({"ok":False,"msg":"你不能處理這筆好友邀請"}), 403
            status = "accepted" if decision == "accept" else "rejected"
            conn.execute("UPDATE user_friends SET status=?, updated_at=? WHERE id=?", (status, datetime.now().isoformat(), request_id))
            conn.commit()
            audit("CHAT_FRIEND_REVIEWED", get_client_ip(), user=actor["username"], detail=f"request_id={request_id},decision={decision}")
            return json_resp({"ok":True,"msg":"已加入好友" if decision == "accept" else "已拒絕好友邀請"})
        finally:
            conn.close()

    @app.route("/api/chat/friends/<int:friend_user_id>", methods=["DELETE"], strict_slashes=False)
    @require_csrf
    def chat_friend_delete(friend_user_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        user_a, user_b = sorted([int(actor["id"]), int(friend_user_id)])
        conn = get_db()
        try:
            ensure_chat_feature_schema(conn)
            cur = conn.execute(
                "DELETE FROM user_friends WHERE user_id=? AND friend_user_id=? AND status='accepted'",
                (user_a, user_b),
            )
            conn.commit()
            if cur.rowcount < 1:
                return json_resp({"ok":False,"msg":"找不到好友關係"}), 404
            audit("CHAT_FRIEND_REMOVED", get_client_ip(), user=actor["username"], detail=f"friend_user_id={friend_user_id}")
            return json_resp({"ok":True,"msg":"已解除好友"})
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

        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT u.username, la.ip_address, la.user_agent, la.success, la.attempted_at "
                "FROM login_attempts la LEFT JOIN users u ON u.id=la.user_id "
                "ORDER BY la.attempted_at DESC LIMIT 200"
            ).fetchall()
        finally:
            conn.close()

        entries = []
        for r in rows:
            entries.append({
                "user":      r["username"] or "(未知)",
                "ip":        r["ip_address"],
                "ua":        r["user_agent"],
                "success":   bool(r["success"]),
                "time":      r["attempted_at"],
            })
        return json_resp({"ok":True,"entries":entries})
