"""Finance-domain SQLite routing helpers.

PointsChain and Trading must stay in one SQLite file because order settlement,
ledger writes, reserve accounting, and economy events rely on same-transaction
atomicity.  This helper opens that shared finance DB while exposing core
identity rows as read-only temp views for legacy SQL that joins ``users``.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

from services.core.sqlite_hardening import connect_sqlite, sqlite_busy_timeout_ms
from services.server.domain_databases import (
    DOMAIN_TABLES,
    connect_db,
    export_domains_to_database,
    list_user_tables,
    table_row_count,
)


FINANCE_DOMAINS = {"points_chain", "trading"}
FINANCE_TABLES = set().union(*(DOMAIN_TABLES[domain] for domain in FINANCE_DOMAINS))
_FINANCE_MIGRATION_LOCK = threading.Lock()
_FINANCE_MIGRATED_PATHS: set[str] = set()


def _finance_busy_timeout_ms() -> int:
    try:
        configured = int(str(os.environ.get("HACKME_FINANCE_SQLITE_BUSY_TIMEOUT_MS", "60000")).strip())
    except Exception:
        configured = 60000
    return max(sqlite_busy_timeout_ms(), configured, 1000)


def _path_key(path: str | Path) -> str:
    try:
        return str(Path(path).expanduser().resolve())
    except Exception:
        return str(path)


def _same_path(left: str | Path, right: str | Path) -> bool:
    return _path_key(left) == _path_key(right)


def _table_exists(conn: sqlite3.Connection, table: str, *, schema: str = "main") -> bool:
    try:
        row = conn.execute(
            f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (str(table),),
        ).fetchone()
        return bool(row)
    except Exception:
        return False


def _selected_row_count(conn: sqlite3.Connection, tables: set[str]) -> int:
    total = 0
    existing = set(list_user_tables(conn))
    for table in sorted(tables & existing):
        try:
            total += int(table_row_count(conn, table))
        except Exception:
            pass
    return total


def migrate_finance_tables_if_needed(
    *,
    core_db_path: str | Path,
    finance_db_path: str | Path,
) -> dict:
    """Copy legacy finance tables from main DB into finance DB once.

    The source is left untouched.  If the finance DB already has any
    PointsChain/Trading rows, migration is skipped to avoid mixing histories.
    """

    if _same_path(core_db_path, finance_db_path):
        return {"ok": True, "skipped": True, "reason": "same_database"}
    core = Path(core_db_path)
    finance = Path(finance_db_path)
    if not core.exists():
        return {"ok": True, "skipped": True, "reason": "core_missing"}
    key = _path_key(finance)
    if key in _FINANCE_MIGRATED_PATHS:
        return {"ok": True, "skipped": True, "reason": "already_checked"}
    with _FINANCE_MIGRATION_LOCK:
        if key in _FINANCE_MIGRATED_PATHS:
            return {"ok": True, "skipped": True, "reason": "already_checked"}
        source_conn = connect_db(core, read_only=True)
        try:
            source_rows = _selected_row_count(source_conn, FINANCE_TABLES)
        finally:
            source_conn.close()
        if source_rows <= 0:
            _FINANCE_MIGRATED_PATHS.add(key)
            return {"ok": True, "skipped": True, "reason": "source_empty"}
        if finance.exists():
            dest_conn = connect_db(finance, read_only=True)
            try:
                dest_rows = _selected_row_count(dest_conn, FINANCE_TABLES)
            finally:
                dest_conn.close()
            if dest_rows > 0:
                _FINANCE_MIGRATED_PATHS.add(key)
                return {"ok": True, "skipped": True, "reason": "target_not_empty", "target_rows": dest_rows}
        manifest = export_domains_to_database(core, finance, domains=FINANCE_DOMAINS, overwrite=True)
        _FINANCE_MIGRATED_PATHS.add(key)
        return {"ok": True, "skipped": False, "manifest": manifest}


def _attach_core_identity_views(conn: sqlite3.Connection, *, core_db_path: str | Path, finance_db_path: str | Path) -> None:
    if _same_path(core_db_path, finance_db_path):
        return
    core = Path(core_db_path)
    if not core.exists():
        return
    try:
        conn.execute("ATTACH DATABASE ? AS core", (str(core),))
    except sqlite3.OperationalError as exc:
        if "already in use" not in str(exc).lower():
            raise
    if _table_exists(conn, "users", schema="core"):
        conn.execute("DROP VIEW IF EXISTS temp.users")
        conn.execute("CREATE TEMP VIEW users AS SELECT * FROM core.users")


def get_finance_db(
    finance_db_path: str | Path,
    *,
    core_db_path: str | Path,
    register_app_mode=None,
) -> sqlite3.Connection:
    busy_timeout_ms = _finance_busy_timeout_ms()
    conn = connect_sqlite(
        finance_db_path,
        timeout=busy_timeout_ms / 1000.0,
        row_factory=True,
        foreign_keys=False,
        wal=True,
        busy_timeout_ms=busy_timeout_ms,
    )
    try:
        if register_app_mode is not None:
            register_app_mode(conn)
    except Exception:
        pass
    _attach_core_identity_views(conn, core_db_path=core_db_path, finance_db_path=finance_db_path)
    try:
        conn.commit()
    except Exception:
        pass
    return conn


def finance_split_enabled() -> bool:
    raw = str(os.environ.get("HTML_LEARNING_FINANCE_DB_SPLIT", "1") or "").strip().lower()
    return raw not in {"0", "false", "no", "off", "disabled"}
