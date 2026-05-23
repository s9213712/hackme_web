"""Phase 3 of SERVER_MODE_V2_IMPLEMENTATION_PLAN.md — DB-level mode triggers.

Locks the contract that ANY direct SQL INSERT into points_chain_blocks
outside production/dev_ready/bootstrap is aborted by the trigger, even
if the service-layer guard (Phase 7) is bypassed. This is the final
defense line; Phases 7 and 2 catch most bugs first, but if some path
opens its own connection and writes raw SQL, the trigger still refuses.

The trigger is connection-aware via the `app_mode()` user function
registered on every new connection. Bootstrap window (no `server_modes`
row yet) is permitted so the chain's genesis path doesn't fight itself
on first run.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from services.platform.db_mode_triggers import (
    install_all,
    install_mode_triggers_schema,
    register_app_mode_function,
)
from services.points_chain import ensure_points_economy_schema


def _fresh_db(*, with_users=True):
    path = Path(tempfile.mkdtemp()) / "phase3.sqlite"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    if with_users:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT)")
    return conn


def _connection_in_mode(mode):
    """Build a fresh connection with app_mode() returning the given string."""
    conn = _fresh_db()
    register_app_mode_function(conn, mode_reader=lambda: mode)
    ensure_points_economy_schema(conn)
    return conn


def _insert_chain_block(conn, *, block_number=1):
    # block_hash has a UNIQUE constraint — derive from block_number so
    # repeated test inserts never collide.
    conn.execute(
        """
        INSERT INTO points_chain_blocks (
            block_number, previous_block_hash, merkle_root, block_hash,
            ledger_count, first_ledger_id, last_ledger_id, sealed_by,
            sealed_by_node, sealed_at, seal_status, anchor_status, created_at
        ) VALUES (?, NULL, ?, ?, 0, 0, 0, NULL, 'node', '2026-05-05', 'sealed', 'local_only', '2026-05-05')
        """,
        (block_number, f"merkle_{block_number}", f"hash_{block_number}"),
    )


# ── trigger fires in disallowed runtime modes ────────────────────────


@pytest.mark.parametrize("mode", ["internal_test", "test", "maintenance", "incident_lockdown", "superweak"])
def test_trigger_blocks_chain_block_insert_in_disallowed_modes(mode):
    conn = _connection_in_mode(mode)
    with pytest.raises(sqlite3.IntegrityError) as exc:
        _insert_chain_block(conn)
    assert "phase3" in str(exc.value).lower() or "production/dev_ready" in str(exc.value).lower()


# ── production + dev_ready + bootstrap allowed ───────────────────────


def test_trigger_allows_chain_block_insert_in_production():
    conn = _connection_in_mode("production")
    _insert_chain_block(conn)
    conn.commit()
    row = conn.execute("SELECT block_number FROM points_chain_blocks").fetchone()
    assert row["block_number"] == 1


def test_trigger_allows_chain_block_insert_in_dev_ready():
    conn = _connection_in_mode("dev_ready")
    _insert_chain_block(conn)
    conn.commit()
    row = conn.execute("SELECT block_number FROM points_chain_blocks").fetchone()
    assert row["block_number"] == 1


def test_trigger_schema_upgrade_replaces_existing_trigger():
    conn = _connection_in_mode("dev_ready")
    conn.execute("DROP TRIGGER IF EXISTS phase3_forbid_nonprod_chain_block_insert")
    conn.execute(
        """
        CREATE TRIGGER phase3_forbid_nonprod_chain_block_insert
        BEFORE INSERT ON points_chain_blocks
        WHEN app_mode() NOT IN ('production', 'bootstrap')
        BEGIN
            SELECT RAISE(ABORT, 'phase3: chain block write forbidden in non-production mode');
        END;
        """
    )

    install_mode_triggers_schema(conn)

    _insert_chain_block(conn)
    conn.commit()
    row = conn.execute("SELECT block_number FROM points_chain_blocks").fetchone()
    assert row["block_number"] == 1


def test_trigger_allows_chain_block_insert_during_bootstrap():
    """When `server_modes` table is missing / empty, mode reader
    returns 'bootstrap' and the trigger lets the write through —
    this is required for first-run genesis."""
    conn = _fresh_db()
    register_app_mode_function(conn)  # no mode_reader -> reads from DB; no server_modes row -> 'bootstrap'
    ensure_points_economy_schema(conn)
    _insert_chain_block(conn)
    conn.commit()


# ── trigger persists across connections ──────────────────────────────


def test_trigger_persists_across_new_connections(tmp_path):
    """Trigger lives in the schema; only the user function is per-conn."""
    path = tmp_path / "p.db"
    conn1 = sqlite3.connect(str(path))
    register_app_mode_function(conn1, mode_reader=lambda: "production")
    ensure_points_economy_schema(conn1)  # installs schema + trigger
    conn1.commit()
    conn1.close()

    # Reopen — the trigger schema is still there, but user function
    # must be re-registered per connection.
    conn2 = sqlite3.connect(str(path))
    register_app_mode_function(conn2, mode_reader=lambda: "internal_test")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_chain_block(conn2)


def test_unregistered_app_mode_raises_on_chain_insert(tmp_path):
    """A connection that opens points_chain_blocks WITHOUT registering
    app_mode() will fail — that's the hard-fail behavior we want for
    any code path that bypasses get_db()."""
    path = tmp_path / "p.db"
    conn1 = sqlite3.connect(str(path))
    register_app_mode_function(conn1, mode_reader=lambda: "production")
    ensure_points_economy_schema(conn1)
    conn1.commit()
    conn1.close()

    conn2 = sqlite3.connect(str(path))
    # Note: NOT calling register_app_mode_function. The trigger will try
    # to invoke app_mode() and fail with OperationalError or
    # IntegrityError depending on SQLite version. Either way the write
    # is refused — we don't get a successful insert.
    with pytest.raises((sqlite3.OperationalError, sqlite3.IntegrityError)):
        _insert_chain_block(conn2)
        conn2.commit()


# ── strict equality ───────────────────────────────────────────────────


@pytest.mark.parametrize("spoof", ["Production", "PROD", "production ", " production", ""])
def test_trigger_strict_mode_equality(spoof):
    """Anything that's not exactly 'production', 'dev_ready', or 'bootstrap' is
    treated as non-production by the trigger."""
    conn = _connection_in_mode(spoof)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_chain_block(conn)


# ── bootstrap-window flip ─────────────────────────────────────────────


def test_mode_change_takes_effect_immediately():
    """Switching the mode reader's value at runtime must instantly
    flip enforcement — no caching, no stale window."""
    state = {"mode": "production"}
    conn = _fresh_db()
    register_app_mode_function(conn, mode_reader=lambda: state["mode"])
    ensure_points_economy_schema(conn)
    # Production: insert 1 succeeds.
    _insert_chain_block(conn, block_number=1)
    conn.commit()
    # Switch to internal_test: insert 2 must abort.
    state["mode"] = "internal_test"
    with pytest.raises(sqlite3.IntegrityError):
        _insert_chain_block(conn, block_number=2)
    conn.rollback()
    # Switch back to production: insert 3 succeeds.
    state["mode"] = "production"
    _insert_chain_block(conn, block_number=3)
    conn.commit()
    n = conn.execute("SELECT COUNT(*) AS c FROM points_chain_blocks").fetchone()["c"]
    assert n == 2  # blocks 1 and 3, not 2
