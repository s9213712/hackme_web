import sqlite3

import pytest

from services.governance.sanction_notices import record_admin_sanction_notice, restore_admin_sanction_context
from services.governance.violations import get_latest_violation


def _db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_admin_sanction_notice_creates_notification_and_restore_context(tmp_path):
    conn = _db(tmp_path / "sanction.db")
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL,
            member_level TEXT NOT NULL,
            base_level TEXT NOT NULL,
            effective_level TEXT NOT NULL,
            sanction_status TEXT NOT NULL DEFAULT 'none',
            sanction_until TEXT,
            level_update_reason TEXT,
            updated_at TEXT
        );
        INSERT INTO users (
            id, username, role, status, member_level, base_level, effective_level, sanction_status
        ) VALUES
          (1, 'root', 'super_admin', 'active', 'normal', 'normal', 'normal', 'none'),
          (2, 'test', 'user', 'active', 'trusted', 'trusted', 'trusted', 'none');
        """
    )
    actor = conn.execute("SELECT * FROM users WHERE id=1").fetchone()
    target = conn.execute("SELECT * FROM users WHERE id=2").fetchone()
    previous = dict(target)

    conn.execute(
        "UPDATE users SET effective_level='restricted', sanction_status='restricted' WHERE id=2"
    )
    record_admin_sanction_notice(
        conn,
        actor=actor,
        target=target,
        previous=previous,
        violation_id=7,
        action_label="處分狀態 none -> restricted",
        reason="測試處分通知",
    )
    conn.commit()

    dm_table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='direct_messages'").fetchone()
    assert dm_table is None
    note = conn.execute("SELECT user_id, type, title, body, link FROM notifications").fetchone()
    assert note["user_id"] == 2
    assert note["type"] == "member_governance"
    assert note["title"] == "會員權益變更通知"
    assert note["link"] == "/appeals"
    assert "你可以到「申覆」分頁提出申覆" in note["body"]
    context = conn.execute("SELECT points_ledger_uuid FROM admin_sanction_appeal_contexts WHERE violation_id=7").fetchone()
    assert context["points_ledger_uuid"] is None

    restored = restore_admin_sanction_context(conn, user_id=2, violation_id=7)
    assert restored is True
    user = conn.execute(
        "SELECT status, role, member_level, base_level, effective_level, sanction_status, sanction_until FROM users WHERE id=2"
    ).fetchone()
    assert dict(user) == {
        "status": "active",
        "role": "user",
        "member_level": "trusted",
        "base_level": "trusted",
        "effective_level": "trusted",
        "sanction_status": "none",
        "sanction_until": None,
    }


def test_admin_sanction_notice_without_violation_id_uses_negative_governance_id(tmp_path):
    conn = _db(tmp_path / "sanction-negative.db")
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL,
            member_level TEXT NOT NULL,
            base_level TEXT NOT NULL,
            effective_level TEXT NOT NULL,
            sanction_status TEXT NOT NULL DEFAULT 'none',
            sanction_until TEXT,
            level_update_reason TEXT,
            updated_at TEXT
        );
        INSERT INTO users (
            id, username, role, status, member_level, base_level, effective_level, sanction_status
        ) VALUES
          (1, 'root', 'super_admin', 'active', 'normal', 'normal', 'normal', 'none'),
          (2, 'test', 'user', 'active', 'trusted', 'trusted', 'trusted', 'none');
        """
    )
    actor = conn.execute("SELECT * FROM users WHERE id=1").fetchone()
    target = conn.execute("SELECT * FROM users WHERE id=2").fetchone()
    previous = dict(target)

    first = record_admin_sanction_notice(
        conn,
        actor=actor,
        target=target,
        previous=previous,
        action_label="角色 user -> manager",
        reason="治理通知一",
    )
    second = record_admin_sanction_notice(
        conn,
        actor=actor,
        target=target,
        previous=previous,
        action_label="角色 manager -> user",
        reason="治理通知二",
    )
    conn.commit()

    assert first["violation_id"] == -1
    assert second["violation_id"] == -2
    rows = conn.execute(
        "SELECT violation_id, action_label, reason FROM admin_sanction_appeal_contexts ORDER BY violation_id DESC"
    ).fetchall()
    assert [row["violation_id"] for row in rows] == [-1, -2]


def test_admin_sanction_notice_non_appealable_only_creates_plain_notification(tmp_path):
    conn = _db(tmp_path / "sanction-non-appealable.db")
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL,
            member_level TEXT NOT NULL,
            base_level TEXT NOT NULL,
            effective_level TEXT NOT NULL,
            sanction_status TEXT NOT NULL DEFAULT 'none',
            sanction_until TEXT,
            level_update_reason TEXT,
            updated_at TEXT
        );
        INSERT INTO users (
            id, username, role, status, member_level, base_level, effective_level, sanction_status
        ) VALUES
          (1, 'root', 'super_admin', 'active', 'normal', 'normal', 'normal', 'none'),
          (2, 'test', 'user', 'active', 'trusted', 'trusted', 'trusted', 'none');
        """
    )
    actor = conn.execute("SELECT * FROM users WHERE id=1").fetchone()
    target = conn.execute("SELECT * FROM users WHERE id=2").fetchone()

    result = record_admin_sanction_notice(
        conn,
        actor=actor,
        target=target,
        previous=dict(target),
        action_label="角色 user -> manager",
        reason="升級通知",
        appealable=False,
    )
    conn.commit()

    assert result["violation_id"] is None
    note = conn.execute("SELECT type, link, body FROM notifications").fetchone()
    assert note["type"] == "member_governance"
    assert note["link"] is None
    assert "你可以到「申覆」分頁提出申覆" not in note["body"]
    context_count = conn.execute("SELECT COUNT(*) FROM admin_sanction_appeal_contexts").fetchone()[0]
    assert context_count == 0


def test_admin_sanction_notice_contexts_are_immutable_against_delete(tmp_path):
    conn = _db(tmp_path / "sanction-immutable.db")
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL,
            member_level TEXT NOT NULL,
            base_level TEXT NOT NULL,
            effective_level TEXT NOT NULL,
            sanction_status TEXT NOT NULL DEFAULT 'none',
            sanction_until TEXT,
            level_update_reason TEXT,
            updated_at TEXT
        );
        INSERT INTO users (
            id, username, role, status, member_level, base_level, effective_level, sanction_status
        ) VALUES
          (1, 'root', 'super_admin', 'active', 'normal', 'normal', 'normal', 'none'),
          (2, 'test', 'user', 'active', 'trusted', 'trusted', 'trusted', 'none');
        """
    )
    actor = conn.execute("SELECT * FROM users WHERE id=1").fetchone()
    target = conn.execute("SELECT * FROM users WHERE id=2").fetchone()
    record_admin_sanction_notice(
        conn,
        actor=actor,
        target=target,
        previous=dict(target),
        violation_id=17,
        action_label="角色 user -> manager",
        reason="不可刪除治理脈絡",
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("DELETE FROM admin_sanction_appeal_contexts WHERE violation_id=17")


def test_get_latest_violation_returns_real_violation_even_if_context_table_exists(tmp_path):
    conn = _db(tmp_path / "latest-violation.db")
    conn.executescript(
        """
        CREATE TABLE secure_violations (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            points INTEGER NOT NULL,
            reason TEXT NOT NULL,
            triggered_by TEXT NOT NULL,
            actor_username TEXT NOT NULL,
            created_at TEXT NOT NULL,
            prev_hash TEXT,
            entry_hash TEXT
        );
        CREATE TABLE admin_sanction_appeal_contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            violation_id INTEGER NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            pre_status TEXT,
            pre_role TEXT,
            pre_base_level TEXT,
            pre_member_level TEXT,
            pre_effective_level TEXT,
            pre_sanction_status TEXT,
            pre_sanction_until TEXT,
            action_label TEXT NOT NULL,
            reason TEXT NOT NULL,
            actor_username TEXT NOT NULL,
            points_ledger_uuid TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO secure_violations (id, user_id, username, points, reason, triggered_by, actor_username, created_at, prev_hash, entry_hash) "
        "VALUES (9, 2, 'test', 3, '真實違規', 'manager', 'admin', '2026-05-03T12:00:00', 'p', 'h')"
    )
    conn.execute(
        "INSERT INTO secure_violations (id, user_id, username, points, reason, triggered_by, actor_username, created_at, prev_hash, entry_hash) "
        "VALUES (10, 2, 'test', 0, '會員權益變更：角色 user -> manager；原因：治理通知', 'super_admin', 'root', '2026-05-03T12:10:00', 'h', 'i')"
    )
    conn.execute(
        "INSERT INTO admin_sanction_appeal_contexts (violation_id, user_id, action_label, reason, actor_username, created_at) "
        "VALUES (-1, 2, '角色變更', '不列入違規', 'root', '2026-05-03T12:05:00')"
    )
    conn.execute(
        "INSERT INTO admin_sanction_appeal_contexts (violation_id, user_id, action_label, reason, actor_username, created_at) "
        "VALUES (10, 2, '角色變更', '舊資料治理通知', 'root', '2026-05-03T12:10:00')"
    )

    row = get_latest_violation(conn, 2)

    assert row["id"] == 9
    assert row["reason"] == "真實違規"
