import sqlite3

import pytest

from services.core.sqlite_hardening import connect_sqlite, connect_sqlite_readonly, sqlite_busy_timeout_ms


def test_sqlite_busy_timeout_default_fails_fast_for_web_requests(monkeypatch):
    monkeypatch.delenv("HACKME_SQLITE_BUSY_TIMEOUT_MS", raising=False)

    assert sqlite_busy_timeout_ms() == 3000


def test_hardened_sqlite_applies_runtime_pragmas(tmp_path):
    db_path = tmp_path / "hardening.db"
    conn = connect_sqlite(db_path)
    try:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO sample (value) VALUES ('ok')")
        conn.commit()
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000
        assert conn.execute("PRAGMA temp_store").fetchone()[0] in {1, 2}
        assert conn.execute("PRAGMA cache_size").fetchone()[0] < 0
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()


def test_readonly_sqlite_connection_allows_reads_and_blocks_writes(tmp_path):
    db_path = tmp_path / "readonly.db"
    conn = connect_sqlite(db_path)
    try:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO sample (value) VALUES ('ok')")
        conn.commit()
    finally:
        conn.close()

    ro = connect_sqlite_readonly(db_path)
    try:
        assert ro.execute("SELECT value FROM sample WHERE id=1").fetchone()["value"] == "ok"
        assert ro.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("INSERT INTO sample (value) VALUES ('no')")
            ro.commit()
    finally:
        ro.close()


def test_hardened_sqlite_retries_schema_changed_transient(tmp_path, monkeypatch):
    db_path = tmp_path / "schema_changed_retry.db"
    monkeypatch.setenv("HACKME_SQLITE_LOCK_RETRY_ATTEMPTS", "3")
    conn = connect_sqlite(db_path)
    calls = {"count": 0}

    def flaky_operation():
        calls["count"] += 1
        if calls["count"] == 1:
            raise sqlite3.OperationalError("database schema has changed")
        return "ok"

    try:
        assert conn._with_locked_retry(flaky_operation) == "ok"
        assert calls["count"] == 2
    finally:
        conn.close()
