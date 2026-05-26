import sqlite3
import threading
from datetime import datetime

from services.core.sqlite_safe import table_columns as safe_table_columns

_MEMBER_LEVEL_SCHEMA_LOCK = threading.Lock()
_MEMBER_LEVEL_SCHEMA_READY_PATHS = set()
_MEMBER_LEVEL_USER_COLUMNS_READY_PATHS = set()

MEMBER_LEVEL_ORDER = ("newbie", "normal", "trusted", "vip", "restricted", "suspended")
SANCTION_STATUSES = {"none", "restricted", "suspended"}

DEFAULT_MEMBER_LEVEL_RULES = {
    "newbie": {
        "can_post": False,
        "can_comment": True,
        "can_send_dm": False,
        "can_upload_attachment": False,
        "can_report": True,
        "daily_post_limit": 2,
        "daily_dm_limit": 0,
        "post_rate_limit_per_hour": 2,
        "comment_rate_limit_per_hour": 10,
        "dm_rate_limit_per_day": 0,
        "upload_rate_limit_per_day": 0,
        "max_attachment_size_mb": 0,
        "attachment_quota_mb": 0,
        "requires_moderation": True,
        "report_weight": 1,
        "min_account_age_days": 1,
        "min_approved_content_count": 1,
        "min_points": 0,
        "min_trust_score": 0,
        "min_reputation": 0,
        "max_violation_score": 0,
        "downgrade_violation_threshold": 3,
        "session_idle_timeout_minutes": 10,
        "require_admin_approval": False,
        "require_root_approval": False,
    },
    "normal": {
        "can_post": True,
        "can_comment": True,
        "can_send_dm": True,
        "can_upload_attachment": True,
        "can_report": True,
        "daily_post_limit": 10,
        "daily_dm_limit": 20,
        "post_rate_limit_per_hour": 10,
        "comment_rate_limit_per_hour": 40,
        "dm_rate_limit_per_day": 20,
        "upload_rate_limit_per_day": 5,
        "max_attachment_size_mb": 5,
        "attachment_quota_mb": 100,
        "requires_moderation": False,
        "report_weight": 1,
        "min_account_age_days": 14,
        "min_approved_content_count": 5,
        "min_points": 10,
        "min_trust_score": 20,
        "min_reputation": 10,
        "max_violation_score": 0,
        "downgrade_violation_threshold": 5,
        "session_idle_timeout_minutes": 10,
        "require_admin_approval": False,
        "require_root_approval": False,
    },
    "trusted": {
        "can_post": True,
        "can_comment": True,
        "can_send_dm": True,
        "can_upload_attachment": True,
        "can_report": True,
        "daily_post_limit": 30,
        "daily_dm_limit": 80,
        "post_rate_limit_per_hour": 30,
        "comment_rate_limit_per_hour": 120,
        "dm_rate_limit_per_day": 80,
        "upload_rate_limit_per_day": 20,
        "max_attachment_size_mb": 10,
        "attachment_quota_mb": 200,
        "requires_moderation": False,
        "report_weight": 2,
        "min_account_age_days": 14,
        "min_approved_content_count": 5,
        "min_points": 100,
        "min_trust_score": 20,
        "min_reputation": 10,
        "max_violation_score": 0,
        "downgrade_violation_threshold": 8,
        "session_idle_timeout_minutes": 10,
        "require_admin_approval": False,
        "require_root_approval": False,
    },
    "vip": {
        "can_post": True,
        "can_comment": True,
        "can_send_dm": True,
        "can_upload_attachment": True,
        "can_report": True,
        "daily_post_limit": 100,
        "daily_dm_limit": 200,
        "post_rate_limit_per_hour": 100,
        "comment_rate_limit_per_hour": 300,
        "dm_rate_limit_per_day": 200,
        "upload_rate_limit_per_day": 80,
        "max_attachment_size_mb": 50,
        "attachment_quota_mb": 2048,
        "requires_moderation": False,
        "report_weight": 3,
        "min_account_age_days": 60,
        "min_approved_content_count": 50,
        "min_points": 500,
        "min_trust_score": 150,
        "min_reputation": 1000,
        "max_violation_score": 0,
        "downgrade_violation_threshold": 10,
        "session_idle_timeout_minutes": 10,
        "require_admin_approval": True,
        "require_root_approval": False,
    },
    "restricted": {
        "can_post": False,
        "can_comment": False,
        "can_send_dm": False,
        "can_upload_attachment": False,
        "can_report": True,
        "daily_post_limit": 0,
        "daily_dm_limit": 0,
        "post_rate_limit_per_hour": 0,
        "comment_rate_limit_per_hour": 0,
        "dm_rate_limit_per_day": 0,
        "upload_rate_limit_per_day": 0,
        "max_attachment_size_mb": 0,
        "attachment_quota_mb": 0,
        "requires_moderation": True,
        "report_weight": 1,
        "min_account_age_days": 0,
        "min_approved_content_count": 0,
        "min_points": 0,
        "min_trust_score": 0,
        "min_reputation": 0,
        "max_violation_score": 0,
        "downgrade_violation_threshold": 0,
        "session_idle_timeout_minutes": 10,
        "require_admin_approval": True,
        "require_root_approval": False,
    },
    "suspended": {
        "can_post": False,
        "can_comment": False,
        "can_send_dm": False,
        "can_upload_attachment": False,
        "can_report": False,
        "daily_post_limit": 0,
        "daily_dm_limit": 0,
        "post_rate_limit_per_hour": 0,
        "comment_rate_limit_per_hour": 0,
        "dm_rate_limit_per_day": 0,
        "upload_rate_limit_per_day": 0,
        "max_attachment_size_mb": 0,
        "attachment_quota_mb": 0,
        "requires_moderation": True,
        "report_weight": 0,
        "min_account_age_days": 0,
        "min_approved_content_count": 0,
        "min_points": 0,
        "min_trust_score": 0,
        "min_reputation": 0,
        "max_violation_score": 0,
        "downgrade_violation_threshold": 0,
        "session_idle_timeout_minutes": 10,
        "require_admin_approval": True,
        "require_root_approval": True,
    },
}

BOOL_FIELDS = {
    "can_post",
    "can_comment",
    "can_send_dm",
    "can_upload_attachment",
    "can_report",
    "requires_moderation",
    "require_admin_approval",
    "require_root_approval",
}
INT_FIELDS = {
    "daily_post_limit",
    "daily_dm_limit",
    "post_rate_limit_per_hour",
    "comment_rate_limit_per_hour",
    "dm_rate_limit_per_day",
    "upload_rate_limit_per_day",
    "max_attachment_size_mb",
    "attachment_quota_mb",
    "report_weight",
    "min_account_age_days",
    "min_approved_content_count",
    "min_points",
    "min_trust_score",
    "min_reputation",
    "max_violation_score",
    "downgrade_violation_threshold",
    "session_idle_timeout_minutes",
}


def _now():
    return datetime.now().isoformat()


def _table_cols(conn, table):
    return safe_table_columns(conn, table)


def ensure_member_level_user_columns(conn):
    db_path = _connection_path(conn)
    if db_path and db_path in _MEMBER_LEVEL_USER_COLUMNS_READY_PATHS:
        return
    with _MEMBER_LEVEL_SCHEMA_LOCK:
        if db_path and db_path in _MEMBER_LEVEL_USER_COLUMNS_READY_PATHS:
            return
        _ensure_member_level_user_columns_uncached(conn)
        if db_path:
            _MEMBER_LEVEL_USER_COLUMNS_READY_PATHS.add(db_path)


def _ensure_member_level_user_columns_uncached(conn):
    cols = _table_cols(conn, "users")
    additions = (
        ("member_level", "TEXT NOT NULL DEFAULT 'normal'"),
        ("base_level", "TEXT NOT NULL DEFAULT 'normal'"),
        ("effective_level", "TEXT NOT NULL DEFAULT 'normal'"),
        ("trust_score", "INTEGER NOT NULL DEFAULT 0"),
        ("reputation", "INTEGER NOT NULL DEFAULT 0"),
        ("violation_count", "INTEGER NOT NULL DEFAULT 0"),
        ("violation_score", "INTEGER NOT NULL DEFAULT 0"),
        ("sanction_status", "TEXT NOT NULL DEFAULT 'none'"),
        ("sanction_until", "TEXT"),
        ("level_updated_at", "TEXT"),
        ("level_updated_by", "TEXT"),
        ("level_update_reason", "TEXT"),
    )
    for name, ddl in additions:
        if name not in cols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")
    conn.execute(
        """
        UPDATE users
        SET base_level=COALESCE(NULLIF(base_level, ''), NULLIF(member_level, ''), 'normal')
        WHERE base_level IS NULL OR base_level=''
        """
    )
    conn.execute(
        """
        UPDATE users
        SET effective_level=COALESCE(NULLIF(effective_level, ''), NULLIF(base_level, ''), 'normal')
        WHERE effective_level IS NULL OR effective_level=''
        """
    )
    conn.execute("UPDATE users SET sanction_status='none' WHERE sanction_status IS NULL OR sanction_status=''")
    conn.execute("UPDATE users SET violation_score=COALESCE(violation_count, 0) WHERE violation_score IS NULL")


def ensure_member_level_rules_schema(conn):
    db_path = _connection_path(conn)
    if db_path and db_path in _MEMBER_LEVEL_SCHEMA_READY_PATHS:
        return
    with _MEMBER_LEVEL_SCHEMA_LOCK:
        if db_path and db_path in _MEMBER_LEVEL_SCHEMA_READY_PATHS:
            return
        _ensure_member_level_rules_schema_uncached(conn)
        if db_path:
            _MEMBER_LEVEL_SCHEMA_READY_PATHS.add(db_path)


def _connection_path(conn):
    try:
        row = conn.execute("PRAGMA database_list").fetchone()
        return str(row["file"] if hasattr(row, "keys") else row[2])
    except Exception:
        return ""


def _ensure_member_level_rules_schema_uncached(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS member_level_rules (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            level                  TEXT NOT NULL UNIQUE,
            can_post               INTEGER NOT NULL DEFAULT 1,
            can_comment            INTEGER NOT NULL DEFAULT 1,
            can_send_dm            INTEGER NOT NULL DEFAULT 1,
            can_upload_attachment  INTEGER NOT NULL DEFAULT 0,
            can_report             INTEGER NOT NULL DEFAULT 1,
            daily_post_limit       INTEGER NOT NULL DEFAULT 10,
            daily_dm_limit         INTEGER NOT NULL DEFAULT 20,
            post_rate_limit_per_hour INTEGER NOT NULL DEFAULT 10,
            comment_rate_limit_per_hour INTEGER NOT NULL DEFAULT 40,
            dm_rate_limit_per_day  INTEGER NOT NULL DEFAULT 20,
            upload_rate_limit_per_day INTEGER NOT NULL DEFAULT 0,
            max_attachment_size_mb INTEGER NOT NULL DEFAULT 0,
            attachment_quota_mb    INTEGER NOT NULL DEFAULT 0,
            requires_moderation    INTEGER NOT NULL DEFAULT 0,
            report_weight          INTEGER NOT NULL DEFAULT 1,
            min_account_age_days   INTEGER NOT NULL DEFAULT 0,
            min_approved_content_count INTEGER NOT NULL DEFAULT 0,
            min_points             INTEGER NOT NULL DEFAULT 0,
            min_trust_score        INTEGER NOT NULL DEFAULT 0,
            min_reputation         INTEGER NOT NULL DEFAULT 0,
            max_violation_score    INTEGER NOT NULL DEFAULT 0,
            downgrade_violation_threshold INTEGER NOT NULL DEFAULT 0,
            session_idle_timeout_minutes INTEGER NOT NULL DEFAULT 3,
            require_admin_approval INTEGER NOT NULL DEFAULT 0,
            require_root_approval  INTEGER NOT NULL DEFAULT 0,
            created_at             TEXT NOT NULL,
            updated_at             TEXT NOT NULL
        )
        """
    )
    cols = _table_cols(conn, "member_level_rules")
    added_columns = set()
    for name in BOOL_FIELDS:
        if name not in cols:
            conn.execute(f"ALTER TABLE member_level_rules ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0")
            added_columns.add(name)
    for name in INT_FIELDS:
        if name not in cols:
            conn.execute(f"ALTER TABLE member_level_rules ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0")
            added_columns.add(name)
    now = _now()
    all_columns = ["level", *BOOL_FIELDS, *INT_FIELDS, "created_at", "updated_at"]
    insert_columns = ", ".join(all_columns)
    placeholders = ", ".join("?" for _ in all_columns)
    for level, rule in DEFAULT_MEMBER_LEVEL_RULES.items():
        values = [level]
        values.extend(1 if bool(rule[key]) else 0 for key in BOOL_FIELDS)
        values.extend(int(rule[key]) for key in INT_FIELDS)
        values.extend([now, now])
        conn.execute(
            f"INSERT OR IGNORE INTO member_level_rules ({insert_columns}) VALUES ({placeholders})",
            tuple(values),
        )
        updates = []
        params = []
        for key in BOOL_FIELDS:
            updates.append(f"{key}=COALESCE({key}, ?)")
            params.append(1 if bool(rule[key]) else 0)
        for key in INT_FIELDS:
            updates.append(f"{key}=COALESCE({key}, ?)")
            params.append(int(rule[key]))
        params.append(level)
        conn.execute(f"UPDATE member_level_rules SET {', '.join(updates)} WHERE level=?", tuple(params))
        if added_columns:
            set_defaults = []
            default_params = []
            for key in added_columns:
                set_defaults.append(f"{key}=?")
                default_params.append(1 if key in BOOL_FIELDS and bool(rule[key]) else int(rule[key]))
            default_params.append(level)
            conn.execute(f"UPDATE member_level_rules SET {', '.join(set_defaults)} WHERE level=?", tuple(default_params))
    conn.execute("CREATE INDEX IF NOT EXISTS idx_member_level_rules_level ON member_level_rules(level)")
    ensure_member_level_audit_schema(conn)


def ensure_member_level_audit_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS member_level_audit (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            actor               TEXT NOT NULL,
            target_user         TEXT NOT NULL,
            old_base_level      TEXT,
            new_base_level      TEXT,
            old_effective_level TEXT,
            new_effective_level TEXT,
            reason              TEXT NOT NULL,
            source              TEXT NOT NULL,
            created_at          TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_member_level_audit_target ON member_level_audit(target_user, created_at)")


def serialize_member_level_rule(row):
    if not row:
        return None
    data = dict(row)
    for key in BOOL_FIELDS:
        data[key] = bool(data.get(key))
    for key in INT_FIELDS:
        data[key] = int(data.get(key) or 0)
    return data


def get_member_level_rule(conn, level):
    ensure_member_level_rules_schema(conn)
    normalized = level if level in DEFAULT_MEMBER_LEVEL_RULES else "normal"
    row = conn.execute("SELECT * FROM member_level_rules WHERE level=?", (normalized,)).fetchone()
    if row:
        return serialize_member_level_rule(row)
    return dict(DEFAULT_MEMBER_LEVEL_RULES[normalized])


def get_member_level_rule_readonly(conn, level):
    normalized = level if level in DEFAULT_MEMBER_LEVEL_RULES else "normal"
    try:
        row = conn.execute("SELECT * FROM member_level_rules WHERE level=?", (normalized,)).fetchone()
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        if "no such table" not in message and "no such column" not in message:
            raise
        row = None
    if not row:
        return dict(DEFAULT_MEMBER_LEVEL_RULES[normalized])

    data = dict(row)
    rule = dict(DEFAULT_MEMBER_LEVEL_RULES[normalized])
    for key in BOOL_FIELDS:
        if key in data:
            rule[key] = bool(data.get(key))
    for key in INT_FIELDS:
        if key in data:
            rule[key] = int(data.get(key) or 0)
    for key, value in data.items():
        if key not in rule:
            rule[key] = value
    return rule


def get_user_level_fields(user):
    data = dict(user or {})
    base_level = data.get("base_level") or data.get("member_level") or "normal"
    effective_level = data.get("effective_level") or base_level
    return base_level, effective_level


def compute_effective_level(user, now=None):
    data = dict(user or {})
    base_level = data.get("base_level") or data.get("member_level") or "normal"
    sanction_status = data.get("sanction_status") or "none"
    sanction_until = data.get("sanction_until")
    now_dt = now or datetime.now()
    if sanction_status in {"restricted", "suspended"}:
        if not sanction_until:
            return sanction_status
        try:
            if now_dt < datetime.fromisoformat(sanction_until):
                return sanction_status
        except Exception:
            return sanction_status
    return base_level if base_level in DEFAULT_MEMBER_LEVEL_RULES else "normal"


def record_member_level_audit(conn, *, actor, target_user, old_base_level, new_base_level, old_effective_level, new_effective_level, reason, source):
    ensure_member_level_audit_schema(conn)
    conn.execute(
        "INSERT INTO member_level_audit "
        "(actor, target_user, old_base_level, new_base_level, old_effective_level, new_effective_level, reason, source, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            actor or "system",
            target_user or "-",
            old_base_level,
            new_base_level,
            old_effective_level,
            new_effective_level,
            (reason or "-")[:1000],
            source or "system",
            _now(),
        ),
    )


def _actor_notice_row(conn, actor_username):
    username = str(actor_username or "").strip()
    if not username:
        return None
    try:
        return conn.execute(
            "SELECT id, username, role FROM users WHERE username=? LIMIT 1",
            (username,),
        ).fetchone()
    except Exception:
        return None


def refresh_user_effective_level(conn, user_id, *, actor="system", source="system", reason="refresh effective level"):
    ensure_member_level_user_columns(conn)
    row = conn.execute(
        "SELECT id, username, role, member_level, base_level, effective_level, sanction_status, sanction_until FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    if not row:
        return None
    data = dict(row)
    old_base = data.get("base_level") or data.get("member_level") or "normal"
    old_effective = data.get("effective_level") or old_base
    new_effective = compute_effective_level(data)
    updates = ["effective_level=?", "member_level=?", "level_updated_at=?"]
    params = [new_effective, new_effective, _now()]
    if data.get("sanction_status") in {"restricted", "suspended"} and new_effective == old_base:
        updates.extend(["sanction_status='none'", "sanction_until=NULL"])
        data["sanction_status"] = "none"
        data["sanction_until"] = None
    params.append(user_id)
    conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id=?", tuple(params))
    if old_effective != new_effective:
        record_member_level_audit(
            conn,
            actor=actor,
            target_user=data["username"],
            old_base_level=old_base,
            new_base_level=old_base,
            old_effective_level=old_effective,
            new_effective_level=new_effective,
            reason=reason,
            source=source,
        )
    data["effective_level"] = new_effective
    data["member_level"] = new_effective
    return data


def apply_member_level_change(
    conn,
    user_id,
    *,
    actor="system",
    source="system",
    base_level=None,
    sanction_status=None,
    sanction_until=None,
    reason,
):
    ensure_member_level_user_columns(conn)
    row = conn.execute(
        "SELECT id, username, role, member_level, base_level, effective_level, sanction_status, sanction_until FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    if not row:
        return None, "找不到帳號"
    data = dict(row)
    old_base = data.get("base_level") or data.get("member_level") or "normal"
    old_effective = data.get("effective_level") or old_base
    new_base = base_level or old_base
    new_sanction = sanction_status if sanction_status is not None else (data.get("sanction_status") or "none")
    if new_base not in DEFAULT_MEMBER_LEVEL_RULES:
        return None, "會員等級錯誤"
    if new_sanction not in SANCTION_STATUSES:
        return None, "處分狀態錯誤"
    future = {
        **data,
        "base_level": new_base,
        "sanction_status": new_sanction,
        "sanction_until": sanction_until,
    }
    new_effective = compute_effective_level(future)
    old_member_rule = get_member_level_rule(conn, old_effective)
    new_member_rule = get_member_level_rule(conn, new_effective)
    now = _now()
    conn.execute(
        "UPDATE users SET base_level=?, effective_level=?, member_level=?, sanction_status=?, sanction_until=?, "
        "level_updated_at=?, level_updated_by=?, level_update_reason=?, updated_at=? WHERE id=?",
        (new_base, new_effective, new_effective, new_sanction, sanction_until, now, actor, reason[:1000], now, user_id),
    )
    record_member_level_audit(
        conn,
        actor=actor,
        target_user=data["username"],
        old_base_level=old_base,
        new_base_level=new_base,
        old_effective_level=old_effective,
        new_effective_level=new_effective,
        reason=reason,
        source=source,
    )
    if old_effective != new_effective:
        from services.storage.quota_enforcement import maybe_create_quota_reduction_notice

        updated_user = {
            **data,
            "base_level": new_base,
            "effective_level": new_effective,
            "member_level": new_effective,
            "sanction_status": new_sanction,
            "sanction_until": sanction_until,
        }
        maybe_create_quota_reduction_notice(
            conn,
            user_before=data,
            user_after=updated_user,
            old_member_rule=old_member_rule,
            new_member_rule=new_member_rule,
            actor=_actor_notice_row(conn, actor),
            reason=reason,
        )
    return {
        **data,
        "base_level": new_base,
        "effective_level": new_effective,
        "member_level": new_effective,
        "sanction_status": new_sanction,
        "sanction_until": sanction_until,
    }, None


def update_member_level_rule(conn, level, data):
    ensure_member_level_rules_schema(conn)
    if level not in DEFAULT_MEMBER_LEVEL_RULES:
        return None, "會員等級錯誤"
    if not isinstance(data, dict):
        return None, "請求內容格式錯誤"
    updates = []
    params = []
    for key in BOOL_FIELDS:
        if key in data:
            updates.append(f"{key}=?")
            params.append(1 if bool(data[key]) else 0)
    for key in INT_FIELDS:
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
    params.append(_now())
    params.append(level)
    conn.execute(f"UPDATE member_level_rules SET {', '.join(updates)} WHERE level=?", tuple(params))
    row = conn.execute("SELECT * FROM member_level_rules WHERE level=?", (level,)).fetchone()
    return serialize_member_level_rule(row), None


def approved_content_count(conn, user_id):
    total = 0
    try:
        total += conn.execute("SELECT COUNT(*) AS c FROM forum_threads WHERE author_user_id=? AND status='approved'", (user_id,)).fetchone()["c"]
    except Exception:
        pass
    try:
        total += conn.execute("SELECT COUNT(*) AS c FROM forum_posts WHERE author_user_id=? AND is_hidden=0", (user_id,)).fetchone()["c"]
    except Exception:
        pass
    return total


def account_age_days(user):
    created_at = dict(user or {}).get("created_at")
    if not created_at:
        return 0
    try:
        return max(0, (datetime.now() - datetime.fromisoformat(created_at)).days)
    except Exception:
        return 0


def has_basic_profile(user):
    data = dict(user or {})
    return all(data.get(key) for key in ("real_name", "birthdate", "id_number", "phone"))


def evaluate_next_level(conn, user):
    data = dict(user or {})
    base_level = data.get("base_level") or data.get("member_level") or "normal"
    effective_level = data.get("effective_level") or base_level
    if effective_level in {"restricted", "suspended"} or base_level in {"restricted", "suspended"}:
        return None, "處分中不可自動升等"
    next_map = {"newbie": "normal", "normal": "trusted", "trusted": "vip"}
    target_level = next_map.get(base_level)
    if not target_level:
        return None, "目前等級不可自動升等"
    rule = get_member_level_rule(conn, target_level)
    if base_level == "newbie" and not has_basic_profile(data):
        return None, "基本資料未完成"
    if account_age_days(data) < rule["min_account_age_days"]:
        return None, "帳號年齡未達門檻"
    if approved_content_count(conn, data.get("id")) < rule["min_approved_content_count"]:
        return None, "核准內容數未達門檻"
    if int(data.get("violation_score") or data.get("violation_count") or 0) > rule["max_violation_score"]:
        return None, "近期違規分數未達升等條件"
    if int(data.get("trust_score") or 0) < rule["min_trust_score"]:
        return None, "信任分未達門檻"
    if int(data.get("reputation") or 0) < rule["min_reputation"]:
        return None, "聲望分未達門檻"
    if rule["require_admin_approval"] or rule["require_root_approval"]:
        return {"target_level": target_level, "requires_approval": True}, None
    return {"target_level": target_level, "requires_approval": False}, None


def suggest_sanction(conn, user):
    data = dict(user or {})
    level = data.get("effective_level") or data.get("base_level") or data.get("member_level") or "normal"
    rule = get_member_level_rule(conn, level)
    score = int(data.get("violation_score") or data.get("violation_count") or 0)
    threshold = int(rule.get("downgrade_violation_threshold") or 0)
    if threshold and score >= threshold:
        return "suspended" if score >= threshold * 2 else "restricted"
    return "none"
