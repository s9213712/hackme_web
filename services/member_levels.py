from datetime import datetime

DEFAULT_MEMBER_LEVEL_RULES = {
    "newbie": {
        "can_post": False,
        "can_comment": True,
        "can_send_dm": False,
        "can_upload_attachment": False,
        "daily_post_limit": 2,
        "daily_dm_limit": 0,
        "max_attachment_size_mb": 0,
        "requires_moderation": True,
        "min_points": 0,
        "min_trust_score": 0,
    },
    "normal": {
        "can_post": True,
        "can_comment": True,
        "can_send_dm": True,
        "can_upload_attachment": False,
        "daily_post_limit": 10,
        "daily_dm_limit": 20,
        "max_attachment_size_mb": 0,
        "requires_moderation": False,
        "min_points": 10,
        "min_trust_score": 5,
    },
    "trusted": {
        "can_post": True,
        "can_comment": True,
        "can_send_dm": True,
        "can_upload_attachment": True,
        "daily_post_limit": 30,
        "daily_dm_limit": 80,
        "max_attachment_size_mb": 10,
        "requires_moderation": False,
        "min_points": 100,
        "min_trust_score": 50,
    },
    "vip": {
        "can_post": True,
        "can_comment": True,
        "can_send_dm": True,
        "can_upload_attachment": True,
        "daily_post_limit": 100,
        "daily_dm_limit": 200,
        "max_attachment_size_mb": 50,
        "requires_moderation": False,
        "min_points": 500,
        "min_trust_score": 150,
    },
    "restricted": {
        "can_post": False,
        "can_comment": False,
        "can_send_dm": False,
        "can_upload_attachment": False,
        "daily_post_limit": 0,
        "daily_dm_limit": 0,
        "max_attachment_size_mb": 0,
        "requires_moderation": True,
        "min_points": 0,
        "min_trust_score": 0,
    },
    "suspended": {
        "can_post": False,
        "can_comment": False,
        "can_send_dm": False,
        "can_upload_attachment": False,
        "daily_post_limit": 0,
        "daily_dm_limit": 0,
        "max_attachment_size_mb": 0,
        "requires_moderation": True,
        "min_points": 0,
        "min_trust_score": 0,
    },
}


def ensure_member_level_rules_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS member_level_rules (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            level                  TEXT NOT NULL UNIQUE,
            can_post               INTEGER NOT NULL DEFAULT 1,
            can_comment            INTEGER NOT NULL DEFAULT 1,
            can_send_dm            INTEGER NOT NULL DEFAULT 1,
            can_upload_attachment  INTEGER NOT NULL DEFAULT 0,
            daily_post_limit       INTEGER NOT NULL DEFAULT 10,
            daily_dm_limit         INTEGER NOT NULL DEFAULT 20,
            max_attachment_size_mb INTEGER NOT NULL DEFAULT 0,
            requires_moderation    INTEGER NOT NULL DEFAULT 0,
            min_points             INTEGER NOT NULL DEFAULT 0,
            min_trust_score        INTEGER NOT NULL DEFAULT 0,
            created_at             TEXT NOT NULL,
            updated_at             TEXT NOT NULL
        )
        """
    )
    now = datetime.now().isoformat()
    for level, rule in DEFAULT_MEMBER_LEVEL_RULES.items():
        conn.execute(
            "INSERT OR IGNORE INTO member_level_rules "
            "(level, can_post, can_comment, can_send_dm, can_upload_attachment, daily_post_limit, daily_dm_limit, "
            "max_attachment_size_mb, requires_moderation, min_points, min_trust_score, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                level,
                int(rule["can_post"]),
                int(rule["can_comment"]),
                int(rule["can_send_dm"]),
                int(rule["can_upload_attachment"]),
                rule["daily_post_limit"],
                rule["daily_dm_limit"],
                rule["max_attachment_size_mb"],
                int(rule["requires_moderation"]),
                rule["min_points"],
                rule["min_trust_score"],
                now,
                now,
            ),
        )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_member_level_rules_level ON member_level_rules(level)")


def serialize_member_level_rule(row):
    if not row:
        return None
    data = dict(row)
    for key in ("can_post", "can_comment", "can_send_dm", "can_upload_attachment", "requires_moderation"):
        data[key] = bool(data.get(key))
    return data


def get_member_level_rule(conn, level):
    ensure_member_level_rules_schema(conn)
    row = conn.execute("SELECT * FROM member_level_rules WHERE level=?", (level or "normal",)).fetchone()
    if row:
        return serialize_member_level_rule(row)
    return dict(DEFAULT_MEMBER_LEVEL_RULES.get(level or "normal", DEFAULT_MEMBER_LEVEL_RULES["normal"]))


def update_member_level_rule(conn, level, data):
    ensure_member_level_rules_schema(conn)
    if level not in DEFAULT_MEMBER_LEVEL_RULES:
        return None, "會員等級錯誤"
    if not isinstance(data, dict):
        return None, "Invalid request"
    bool_fields = {"can_post", "can_comment", "can_send_dm", "can_upload_attachment", "requires_moderation"}
    int_fields = {"daily_post_limit", "daily_dm_limit", "max_attachment_size_mb", "min_points", "min_trust_score"}
    updates = []
    params = []
    for key in bool_fields:
        if key in data:
            updates.append(f"{key}=?")
            params.append(1 if bool(data[key]) else 0)
    for key in int_fields:
        if key in data:
            try:
                value = int(data[key])
            except Exception:
                return None, f"{key} 格式錯誤"
            if value < 0:
                return None, f"{key} 不可小於 0"
            updates.append(f"{key}=?")
            params.append(value)
    if not updates:
        return None, "未提供可更新欄位"
    updates.append("updated_at=?")
    params.append(datetime.now().isoformat())
    params.append(level)
    conn.execute(f"UPDATE member_level_rules SET {', '.join(updates)} WHERE level=?", tuple(params))
    row = conn.execute("SELECT * FROM member_level_rules WHERE level=?", (level,)).fetchone()
    return serialize_member_level_rule(row), None
