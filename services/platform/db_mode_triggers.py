"""Server Mode v2 — DB-level mode triggers.

Phase 3 of SERVER_MODE_V2_IMPLEMENTATION_PLAN.md — the *last* line of
defense against chain pollution. Phases 7 (service guard) and 2
(routing service) catch most bugs at the application layer; this
trigger catches anything that slipped through (e.g. a future ORM
migration that opens its own connection and writes raw SQL).

Two pieces, called from different sites:

1. `register_app_mode_function(conn, mode_reader=...)` — call this on
   EVERY new SQLite connection (e.g. inside `get_db()`). Registers
   the `app_mode()` user function so the trigger below has something
   to evaluate. Without this call, a connection that opens a write
   transaction on `points_chain_blocks` will fail with "no such
   function: app_mode" — the failure is loud, not silent, which is
   the point.

2. `install_mode_triggers_schema(conn)` — call this once at schema
   setup (e.g. inside `ensure_points_economy_schema`). Creates the
   BEFORE INSERT trigger on `points_chain_blocks` that aborts the
   write when `app_mode()` is not in the allow-set.

Bootstrap window: when a fresh DB has no `server_modes` row yet (or
the row hasn't been chosen), the mode reader returns "bootstrap" and
the trigger lets the write through. This is necessary so the
chain's genesis path doesn't fight itself on first run. `dev_ready`
is also allowed so isolated pre-live stress tests can package blocks
before the runtime is cleared for launch.
"""

from __future__ import annotations

from typing import Callable, Optional

import sqlite3


# Mode names that the chain-block trigger allows.
_CHAIN_INSERT_ALLOWED_MODES = ("production", "dev_ready", "bootstrap")


def register_app_mode_function(
    conn: sqlite3.Connection,
    *,
    mode_reader: Optional[Callable[[], Optional[str]]] = None,
) -> None:
    """Register `app_mode()` user function on this connection.

    `mode_reader` is the authoritative source — typically the same
    `get_runtime_server_mode` callable that gets injected into the
    auth + chain services. If omitted (e.g. in tests), we read
    `current_mode` from the `server_modes` row directly via this
    very connection.

    Returns nothing; the side-effect is the registration on `conn`.
    """

    def _read_mode():
        # IMPORTANT: do NOT strip / lower-case the value here. We rely on
        # strict equality in the trigger: leading/trailing whitespace or
        # case differences from a malformed source should be treated as
        # non-production and fail the write closed.
        #
        # `None` (mode_reader missing or raised) means "no opinion" —
        # fall back to reading from the DB.
        # An empty string "" from the reader is a deliberate signal,
        # not a missing value: a malformed mode string should NOT be
        # silently rewritten to "bootstrap"; we preserve it so the
        # trigger fails closed.
        if mode_reader is not None:
            try:
                value = mode_reader()
            except Exception:
                value = None
            if value is not None:
                return str(value)
        try:
            row = conn.execute(
                "SELECT current_mode FROM server_modes WHERE id=1"
            ).fetchone()
        except sqlite3.Error:
            return "bootstrap"
        if not row:
            return "bootstrap"
        try:
            value = row["current_mode"]
        except (IndexError, TypeError, KeyError):
            value = row[0] if row else None
        if value is None:
            return "bootstrap"
        return str(value)

    # narg=0 (no arguments). deterministic=False so SQLite re-evaluates
    # per call — we need the live mode value, never a query-cached one.
    conn.create_function("app_mode", 0, _read_mode)


def install_mode_triggers_schema(conn: sqlite3.Connection) -> None:
    """Create the BEFORE INSERT trigger on points_chain_blocks.

    Idempotent. Safe to call every time a connection is opened, but
    typically called from the schema-init path
    (ensure_points_economy_schema).

    The trigger body is part of the runtime contract, so we rebuild it
    instead of using CREATE TRIGGER IF NOT EXISTS. That lets existing
    databases pick up allow-set changes such as dev_ready block sealing.
    """
    conn.execute("DROP TRIGGER IF EXISTS phase3_forbid_nonprod_chain_block_insert")
    conn.execute(
        """
        CREATE TRIGGER phase3_forbid_nonprod_chain_block_insert
        BEFORE INSERT ON points_chain_blocks
        WHEN app_mode() NOT IN ('production', 'dev_ready', 'bootstrap')
        BEGIN
            SELECT RAISE(ABORT, 'phase3: chain block write forbidden outside production/dev_ready/bootstrap mode');
        END;
        """
    )


def install_all(
    conn: sqlite3.Connection,
    *,
    mode_reader: Optional[Callable[[], Optional[str]]] = None,
) -> None:
    """Convenience: register the user function + ensure the trigger
    exists. Useful for tests that build their own throwaway
    connections.
    """
    register_app_mode_function(conn, mode_reader=mode_reader)
    install_mode_triggers_schema(conn)


__all__ = [
    "register_app_mode_function",
    "install_mode_triggers_schema",
    "install_all",
]
