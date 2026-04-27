import sqlite3

from services import security_events


def _get_db_factory(db_path):
    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return get_db


def test_record_security_event_normalizes_event_types(tmp_path):
    db_path = tmp_path / "events.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE security_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            target_user TEXT,
            detail TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

    original_state = dict(security_events._STATE)
    original_cleanup_at = security_events._LAST_EVENT_CLEANUP_AT
    try:
        security_events._LAST_EVENT_CLEANUP_AT = 10**12
        security_events.configure_security_events_service(
            get_db=_get_db_factory(str(db_path)),
            get_system_settings=lambda: {},
            audit=lambda *args, **kwargs: None,
            is_ip_blocking_enabled=lambda: False,
        )

        security_events.record_security_event(
            "feature_disabled",
            "127.0.0.1",
            target_user="alice",
            detail="feature_chat_enabled",
        )
        security_events.record_security_event("unknown_event", "127.0.0.1")
    finally:
        security_events._STATE.clear()
        security_events._STATE.update(original_state)
        security_events._LAST_EVENT_CLEANUP_AT = original_cleanup_at

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT event_type, ip_address, target_user, detail FROM security_events ORDER BY id"
    ).fetchall()
    conn.close()

    assert rows[0] == ("feature_disabled", "127.0.0.1", "alice", "feature_chat_enabled")
    assert rows[1][0] == "permission_denied"


def test_rate_limit_block_records_security_event(tmp_path):
    db_path = tmp_path / "rate-limit.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE security_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            target_user TEXT,
            detail TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

    original_state = dict(security_events._STATE)
    original_cleanup_at = security_events._LAST_EVENT_CLEANUP_AT
    original_buckets = dict(security_events._RATE_LIMIT_BUCKETS)
    try:
        security_events._LAST_EVENT_CLEANUP_AT = 10**12
        security_events._RATE_LIMIT_BUCKETS.clear()
        security_events.configure_security_events_service(
            get_db=_get_db_factory(str(db_path)),
            get_system_settings=lambda: {},
            audit=lambda *args, **kwargs: None,
            is_ip_blocking_enabled=lambda: False,
        )

        assert security_events.is_rate_limited("10.0.0.9", max_req=1, window_sec=60)[0] is False
        assert security_events.is_rate_limited("10.0.0.9", max_req=1, window_sec=60)[0] is True
    finally:
        security_events._STATE.clear()
        security_events._STATE.update(original_state)
        security_events._LAST_EVENT_CLEANUP_AT = original_cleanup_at
        security_events._RATE_LIMIT_BUCKETS.clear()
        security_events._RATE_LIMIT_BUCKETS.update(original_buckets)

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT event_type, ip_address, detail FROM security_events ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()

    assert row[0] == "rate_limit"
    assert row[1] == "10.0.0.9"
    assert "limit=1" in row[2]
