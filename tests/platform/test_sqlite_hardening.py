import sqlite3

import pytest

from services.core.sqlite_hardening import connect_sqlite, connect_sqlite_readonly


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
