ROLE_RANK = {
    "user": 0,
    "moderator": 1,
    "content_admin": 2,
    "security_admin": 2,
    "manager": 3,
    "admin": 3,
    "super_admin": 4,
    "root": 4,
}

ROLE_LABEL = {
    "root": "Root",
    "super_admin": "最高管理者",
    "admin": "管理者",
    "manager": "管理者",
    "security_admin": "安全管理者",
    "content_admin": "內容管理者",
    "moderator": "版主",
    "user": "一般用戶",
}

MEMBER_LEVELS = {"newbie", "normal", "trusted", "vip", "restricted", "suspended"}
ACCOUNT_STATUSES = {"active", "inactive", "pending", "rejected", "limited", "muted", "suspended", "deleted"}

PHASE1_USER_COLUMNS = (
    ("role", "TEXT NOT NULL DEFAULT 'user'"),
    ("email", "TEXT"),
    ("member_level", "TEXT NOT NULL DEFAULT 'normal'"),
    ("base_level", "TEXT NOT NULL DEFAULT 'normal'"),
    ("effective_level", "TEXT NOT NULL DEFAULT 'normal'"),
    ("nickname", "TEXT"),
    ("real_name", "TEXT"),
    ("birthdate", "TEXT"),
    ("id_number", "TEXT"),
    ("phone", "TEXT"),
    ("blocked_until", "TEXT"),
    ("violation_count", "INTEGER NOT NULL DEFAULT 0"),
    ("chat_violation_warned", "INTEGER NOT NULL DEFAULT 0"),
    ("trust_score", "INTEGER NOT NULL DEFAULT 0"),
    ("points", "INTEGER NOT NULL DEFAULT 0"),
    ("reputation", "INTEGER NOT NULL DEFAULT 0"),
    ("violation_score", "INTEGER NOT NULL DEFAULT 0"),
    ("sanction_status", "TEXT NOT NULL DEFAULT 'none'"),
    ("sanction_until", "TEXT"),
    ("level_updated_at", "TEXT"),
    ("level_updated_by", "TEXT"),
    ("level_update_reason", "TEXT"),
    ("email_verified", "INTEGER NOT NULL DEFAULT 0"),
    ("two_factor_enabled", "INTEGER NOT NULL DEFAULT 0"),
    ("failed_login_count", "INTEGER NOT NULL DEFAULT 0"),
    ("locked_until", "TEXT"),
    ("password_strength_score", "INTEGER NOT NULL DEFAULT 0"),
    ("last_login_at", "TEXT"),
    ("password_changed_at", "TEXT"),
    ("must_change_password", "INTEGER NOT NULL DEFAULT 0"),
    ("is_default_password", "INTEGER NOT NULL DEFAULT 0"),
    ("avatar_file_id", "TEXT"),
    ("avatar_crop_json", "TEXT"),
    ("updated_at", "TEXT"),
    ("deleted_at", "TEXT"),
)


def role_rank(role):
    return ROLE_RANK.get(role or "user", 0)


def is_admin_role(role):
    return role_rank(role) >= role_rank("manager")


def ensure_user_identity_columns(conn):
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    for name, ddl in PHASE1_USER_COLUMNS:
        if name not in cols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")
    conn.execute("UPDATE users SET role='user' WHERE role IS NULL OR role=''")
    conn.execute("UPDATE users SET member_level='normal' WHERE member_level IS NULL OR member_level=''")
    conn.execute("UPDATE users SET base_level=member_level WHERE base_level IS NULL OR base_level=''")
    conn.execute("UPDATE users SET effective_level=base_level WHERE effective_level IS NULL OR effective_level=''")
    conn.execute("UPDATE users SET sanction_status='none' WHERE sanction_status IS NULL OR sanction_status=''")
    conn.execute("UPDATE users SET status='active' WHERE status IS NULL OR status=''")
