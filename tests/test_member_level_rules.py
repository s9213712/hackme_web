import sqlite3
from datetime import datetime, timedelta

from services.member_levels import (
    DEFAULT_MEMBER_LEVEL_RULES,
    apply_member_level_change,
    ensure_member_level_rules_schema,
    ensure_member_level_user_columns,
    evaluate_next_level,
    get_member_level_rule,
    refresh_user_effective_level,
    suggest_sanction,
    update_member_level_rule,
)
from services.permissions import (
    can_comment,
    can_dm,
    can_post,
    can_report,
    can_upload,
    get_rate_limit,
    require_member_action,
)


def _conn(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            status TEXT NOT NULL DEFAULT 'active',
            member_level TEXT NOT NULL DEFAULT 'normal',
            created_at TEXT NOT NULL,
            updated_at TEXT,
            trust_score INTEGER NOT NULL DEFAULT 0,
            points INTEGER NOT NULL DEFAULT 0,
            reputation INTEGER NOT NULL DEFAULT 0,
            violation_count INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    ensure_member_level_user_columns(conn)
    ensure_member_level_rules_schema(conn)
    conn.commit()
    return conn


def _insert_user(conn, user_id, username, level, **overrides):
    created_at = overrides.pop("created_at", (datetime.now() - timedelta(days=30)).isoformat())
    values = {
        "id": user_id,
        "username": username,
        "status": "active",
        "role": "user",
        "member_level": level,
        "base_level": level,
        "effective_level": level,
        "created_at": created_at,
        "trust_score": 0,
        "points": 0,
        "reputation": 0,
        "violation_score": 0,
        "sanction_status": "none",
        "sanction_until": None,
    }
    values.update(overrides)
    conn.execute(
        "INSERT INTO users "
        "(id, username, role, status, member_level, base_level, effective_level, created_at, trust_score, points, reputation, "
        "violation_score, sanction_status, sanction_until) "
        "VALUES (:id, :username, :role, :status, :member_level, :base_level, :effective_level, :created_at, :trust_score, "
        ":points, :reputation, :violation_score, :sanction_status, :sanction_until)",
        values,
    )
    conn.commit()
    return conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def test_member_level_rules_schema_seeds_defaults(tmp_path):
    conn = _conn(tmp_path / "levels.db")
    try:
        rows = conn.execute("SELECT level FROM member_level_rules ORDER BY level").fetchall()
        levels = {row["level"] for row in rows}
        assert levels == set(DEFAULT_MEMBER_LEVEL_RULES)
        normal = get_member_level_rule(conn, "normal")
        assert normal["can_post"] is True
        assert normal["can_report"] is True
        assert normal["post_rate_limit_per_hour"] == DEFAULT_MEMBER_LEVEL_RULES["normal"]["post_rate_limit_per_hour"]
    finally:
        conn.close()


def test_update_member_level_rule_validates_and_serializes(tmp_path):
    conn = _conn(tmp_path / "levels.db")
    try:
        rule, err = update_member_level_rule(
            conn,
            "normal",
            {"can_post": False, "daily_post_limit": 3, "max_attachment_size_mb": 8, "report_weight": 4, "session_idle_timeout_minutes": 7},
        )
        assert err is None
        assert rule["can_post"] is False
        assert rule["daily_post_limit"] == 3
        assert rule["max_attachment_size_mb"] == 8
        assert rule["report_weight"] == 4
        assert rule["session_idle_timeout_minutes"] == 7

        rule, err = update_member_level_rule(conn, "normal", {"daily_dm_limit": -1})
        assert rule is None
        assert err == "daily_dm_limit 不可小於 0"
    finally:
        conn.close()


def test_newbie_permissions_are_limited(tmp_path):
    conn = _conn(tmp_path / "levels.db")
    try:
        user = _insert_user(conn, 1, "newbie", "newbie")
        assert can_post(user, conn) is False
        assert can_comment(user, conn) is True
        assert can_dm(user, conn=conn) is False
        assert can_upload(user, conn) is False
        assert can_report(user, conn) is True
    finally:
        conn.close()


def test_normal_user_can_interact(tmp_path):
    conn = _conn(tmp_path / "levels.db")
    try:
        user = _insert_user(conn, 2, "normal", "normal")
        assert can_post(user, conn) is True
        assert can_comment(user, conn) is True
        assert can_dm(user, conn=conn) is True
        assert can_upload(user, conn) is True
    finally:
        conn.close()


def test_trusted_attachment_and_rate_limit(tmp_path):
    conn = _conn(tmp_path / "levels.db")
    try:
        user = _insert_user(conn, 3, "trusted", "trusted")
        assert can_upload(user, conn) is True
        assert get_rate_limit(user, "community_thread_create", conn) == DEFAULT_MEMBER_LEVEL_RULES["trusted"]["post_rate_limit_per_hour"]
        assert get_member_level_rule(conn, "trusted")["max_attachment_size_mb"] == 10
    finally:
        conn.close()


def test_vip_extra_quota(tmp_path):
    conn = _conn(tmp_path / "levels.db")
    try:
        user = _insert_user(conn, 4, "vip", "vip")
        rule = get_member_level_rule(conn, "vip")
        assert can_upload(user, conn) is True
        assert rule["attachment_quota_mb"] > get_member_level_rule(conn, "trusted")["attachment_quota_mb"]
        assert get_rate_limit(user, "chat_dm_create", conn) == rule["dm_rate_limit_per_day"]
    finally:
        conn.close()


def test_restricted_can_only_read(tmp_path):
    conn = _conn(tmp_path / "levels.db")
    try:
        user = _insert_user(conn, 5, "restricted", "restricted")
        assert can_post(user, conn) is False
        assert can_comment(user, conn) is False
        assert can_dm(user, conn=conn) is False
        assert can_upload(user, conn) is False
        assert require_member_action(user, "community_reply", conn=conn) == (False, "會員等級受限，僅可閱讀不可互動", 403)
    finally:
        conn.close()


def test_manager_role_bypasses_member_interaction_limits(tmp_path):
    conn = _conn(tmp_path / "levels.db")
    try:
        manager = _insert_user(conn, 12, "admin", "restricted", role="manager")
        root = _insert_user(conn, 13, "root", "suspended", role="super_admin")
        assert can_post(manager, conn) is True
        assert can_comment(manager, conn) is True
        assert can_upload(manager, conn) is True
        assert can_report(manager, conn) is True
        assert get_rate_limit(manager, "community_thread_create", conn) is None
        assert can_post(root, conn) is True
        assert can_upload(root, conn) is True
        assert require_member_action(manager, "community_reply", conn=conn) == (True, "", 200)
        assert require_member_action(root, "community_thread_create", conn=conn) == (True, "", 200)
    finally:
        conn.close()


def test_suspended_can_only_login_notifications_and_appeal_surfaces(tmp_path):
    conn = _conn(tmp_path / "levels.db")
    try:
        user = _insert_user(conn, 6, "suspended", "suspended")
        assert can_post(user, conn) is False
        assert can_comment(user, conn) is False
        assert can_report(user, conn) is False
        assert require_member_action(user, "community_reaction", conn=conn) == (False, "會員等級已停權，僅可登入、查看通知與申訴", 403)
    finally:
        conn.close()


def test_vip_restricted_sanction_overrides_effective_level_and_preserves_base(tmp_path):
    conn = _conn(tmp_path / "levels.db")
    try:
        _insert_user(conn, 7, "vipuser", "vip")
        user, err = apply_member_level_change(
            conn,
            7,
            actor="admin",
            source="admin",
            sanction_status="restricted",
            reason="manual sanction",
        )
        assert err is None
        assert user["base_level"] == "vip"
        assert user["effective_level"] == "restricted"
        assert can_post(user, conn) is False
    finally:
        conn.close()


def test_expired_sanction_restores_base_level(tmp_path):
    conn = _conn(tmp_path / "levels.db")
    try:
        expired = (datetime.now() - timedelta(minutes=1)).isoformat()
        _insert_user(conn, 8, "expired", "vip", effective_level="restricted", sanction_status="restricted", sanction_until=expired)
        user = refresh_user_effective_level(conn, 8, actor="system", source="system", reason="sanction expired")
        assert user["base_level"] == "vip"
        assert user["effective_level"] == "vip"
        assert user["sanction_status"] == "none"
        restored = conn.execute("SELECT effective_level, sanction_status FROM users WHERE id=8").fetchone()
        assert restored["effective_level"] == "vip"
        assert restored["sanction_status"] == "none"
    finally:
        conn.close()


def test_every_level_change_writes_audit_log(tmp_path):
    conn = _conn(tmp_path / "levels.db")
    try:
        _insert_user(conn, 9, "auditme", "normal")
        user, err = apply_member_level_change(
            conn,
            9,
            actor="root",
            source="root",
            base_level="trusted",
            reason="manual promotion",
        )
        assert err is None
        row = conn.execute("SELECT * FROM member_level_audit WHERE target_user='auditme'").fetchone()
        assert row["actor"] == "root"
        assert row["old_base_level"] == "normal"
        assert row["new_base_level"] == "trusted"
        assert row["old_effective_level"] == "normal"
        assert row["new_effective_level"] == "trusted"
        assert row["reason"] == "manual promotion"
        assert row["source"] == "root"
    finally:
        conn.close()


def test_quota_reduction_level_change_warns_user_with_dm_and_notification(tmp_path):
    conn = _conn(tmp_path / "levels.db")
    try:
        _insert_user(conn, 1, "root", "vip", role="super_admin")
        _insert_user(conn, 9, "quotauser", "vip")
        conn.execute(
            """
            CREATE TABLE uploaded_files (
                id TEXT PRIMARY KEY,
                owner_user_id INTEGER NOT NULL,
                storage_path TEXT NOT NULL,
                privacy_mode TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                scan_status TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                deleted_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO uploaded_files (
                id, owner_user_id, storage_path, privacy_mode, risk_level, scan_status,
                size_bytes, created_at
            ) VALUES ('f1', 9, 'users/9/f1/a.bin', 'private_scannable', 'low', 'clean', ?, ?)
            """,
            (150 * 1024 * 1024, datetime.now().isoformat()),
        )

        user, err = apply_member_level_change(
            conn,
            9,
            actor="root",
            source="root",
            base_level="normal",
            reason="quota downgrade",
        )

        assert err is None
        assert user["effective_level"] == "normal"
        notice = conn.execute("SELECT * FROM storage_quota_reduction_notices WHERE user_id=9").fetchone()
        assert notice["status"] == "pending"
        assert notice["new_quota_bytes"] == 100 * 1024 * 1024
        assert "24 小時" in notice["notice_message"]
        notification = conn.execute("SELECT * FROM notifications WHERE user_id=9 AND type='storage_quota_reduced'").fetchone()
        assert notification is not None
        dm = conn.execute("SELECT * FROM direct_messages WHERE recipient_user_id=9").fetchone()
        assert dm is not None
        assert "完成備份" in dm["body"]
    finally:
        conn.close()


def test_upgrade_and_sanction_suggestion_use_configured_rules(tmp_path):
    conn = _conn(tmp_path / "levels.db")
    try:
        old = (datetime.now() - timedelta(days=15)).isoformat()
        user = _insert_user(conn, 10, "candidate", "normal", created_at=old, trust_score=30, reputation=20)
        conn.execute(
            "CREATE TABLE forum_threads (id INTEGER PRIMARY KEY, author_user_id INTEGER, status TEXT)"
        )
        for idx in range(5):
            conn.execute("INSERT INTO forum_threads (id, author_user_id, status) VALUES (?, 10, 'approved')", (idx + 1,))
        result, err = evaluate_next_level(conn, user)
        assert err is None
        assert result == {"target_level": "trusted", "requires_approval": False}

        rule, err = update_member_level_rule(conn, "normal", {"downgrade_violation_threshold": 2})
        assert err is None
        violator = _insert_user(conn, 11, "violator", "normal", violation_score=2)
        assert suggest_sanction(conn, violator) == "restricted"
    finally:
        conn.close()
