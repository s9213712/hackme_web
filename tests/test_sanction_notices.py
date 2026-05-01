import sqlite3

from services.sanction_notices import record_admin_sanction_notice, restore_admin_sanction_context


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
