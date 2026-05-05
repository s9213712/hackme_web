"""Phase 4 of SERVER_MODE_V2_IMPLEMENTATION_PLAN.md — shadow tables migration.

The internal_test sandbox needs separate schemas for orders / positions /
ledger so Phase 5 (trading dual-engine) has a place to route to. These
tests assert:

1. Fresh DB → all three test_shadow_* tables exist with the expected
   structural fields (no schema regression).
2. Production tables (trading_orders, trading_spot_positions,
   points_ledger) are unaffected by the shadow migration.
3. Tester-scoped indexes exist so future Phase 5 queries by
   tester_user_id stay fast.
4. Inserting into a shadow table works — basic write smoke.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from services.snapshots import ensure_snapshot_schema
from services.points_chain import ensure_points_economy_schema
from services.trading_engine import ensure_trading_schema


def _fresh_db():
    db_path = Path(tempfile.mkdtemp()) / "phase4.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    # Real apps run all three; we replicate that order.
    ensure_snapshot_schema(conn)
    ensure_points_economy_schema(conn)
    # ensure_trading_engine_schema requires users + markets tables. The
    # snapshot schema doesn't create users by default — so we stub them
    # before driving the trading schema.
    conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT)")
    ensure_trading_schema(conn)
    return conn


def _columns(conn, table):
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def test_shadow_orders_exists_with_expected_columns():
    conn = _fresh_db()
    cols = _columns(conn, "test_shadow_orders")
    expected = {
        "id", "order_uuid", "tester_user_id", "user_id", "market_symbol", "side",
        "order_type", "funding_mode", "execution_mode", "quantity_units", "limit_price_points",
        "execution_price_points", "status", "frozen_points", "fee_points",
        "trial_frozen_points", "chain_frozen_points", "filled_quantity_units", "reason", "token_id", "created_at",
        "updated_at",
    }
    assert expected.issubset(set(cols)), f"missing columns: {expected - set(cols)}"


def test_shadow_positions_exists_with_expected_columns():
    conn = _fresh_db()
    cols = _columns(conn, "test_shadow_positions")
    expected = {
        "user_id", "tester_user_id", "market_symbol", "quantity_units",
        "locked_quantity_units", "avg_cost_points", "token_id", "updated_at",
    }
    assert expected.issubset(set(cols)), f"missing columns: {expected - set(cols)}"


def test_shadow_margin_positions_exists_with_expected_columns():
    conn = _fresh_db()
    cols = _columns(conn, "test_shadow_margin_positions")
    expected = {
        "id", "position_uuid", "tester_user_id", "user_id", "market_symbol", "position_type",
        "quantity_units", "entry_price_points", "principal_points", "collateral_points",
        "open_fee_points", "close_fee_points", "exit_price_points", "realized_pnl_points",
        "interest_percent_daily", "interest_points", "interest_paid_points",
        "interest_accrued_hours", "interest_carry_micropoints", "interest_interval_hours",
        "interest_minimum_hours", "borrowed_asset_symbol", "status", "opened_at", "closed_at",
        "updated_at", "collateral_trial_points", "collateral_chain_points",
        "open_fee_trial_points", "open_fee_chain_points",
    }
    assert expected.issubset(set(cols)), f"missing columns: {expected - set(cols)}"


def test_shadow_ledger_exists_with_expected_columns():
    conn = _fresh_db()
    cols = _columns(conn, "test_shadow_ledger")
    expected = {
        "id", "ledger_uuid", "tester_user_id", "user_id", "public_account_id", "currency_type", "direction",
        "amount", "balance_before", "balance_after", "action_type",
        "reference_type", "reference_id", "idempotency_key", "reason", "token_id", "created_at",
        "public_metadata_json", "private_metadata_json", "metadata_hash",
        "previous_ledger_hash", "ledger_hash", "status",
    }
    assert expected.issubset(set(cols)), f"missing columns: {expected - set(cols)}"


def test_shadow_wallets_exists_with_points_only_columns():
    conn = _fresh_db()
    cols = _columns(conn, "test_shadow_wallets")
    expected = {
        "id", "tester_user_id", "user_id", "balance_points", "frozen_points",
        "total_points_earned", "total_points_spent", "wallet_status",
        "risk_level", "token_id", "created_at", "updated_at",
    }
    assert expected.issubset(set(cols)), f"missing columns: {expected - set(cols)}"


def test_shadow_indexes_exist():
    conn = _fresh_db()
    indexes = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    for required in (
        "idx_shadow_orders_tester",
        "idx_shadow_orders_market_status",
        "idx_shadow_positions_tester",
        "idx_shadow_margin_positions_tester_status",
        "idx_shadow_ledger_tester",
        "idx_shadow_ledger_action",
    ):
        assert required in indexes, f"missing index {required}"


def test_production_tables_unchanged_by_shadow_migration():
    """Phase 4 must not touch the production-side schemas."""
    conn = _fresh_db()
    prod_tables = {
        "trading_orders": {"order_uuid", "user_id", "market_symbol", "side", "order_type"},
        "trading_spot_positions": {"user_id", "market_symbol", "quantity_units"},
        "points_ledger": {"ledger_uuid", "user_id", "direction", "amount"},
    }
    for table, expected_cols in prod_tables.items():
        cols = set(_columns(conn, table))
        assert cols, f"production table {table} missing"
        assert expected_cols.issubset(cols), f"{table} schema regressed: {expected_cols - cols}"


def test_shadow_orders_basic_insert():
    conn = _fresh_db()
    conn.execute(
        """
        INSERT INTO test_shadow_orders (
            order_uuid, tester_user_id, market_symbol, side, order_type,
            quantity_units, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("u-1", 7, "BTC/POINTS", "buy", "market", 100, "open", "2026-05-05T00:00:00", "2026-05-05T00:00:00"),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM test_shadow_orders WHERE order_uuid='u-1'").fetchone()
    assert row is not None
    assert row["tester_user_id"] == 7
    assert row["status"] == "open"


def test_shadow_orders_check_constraints():
    """side / order_type / status enforcement must be active on shadow tables too."""
    conn = _fresh_db()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO test_shadow_orders (
                order_uuid, tester_user_id, market_symbol, side, order_type,
                quantity_units, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("u-bad-side", 1, "BTC/POINTS", "long", "market", 1, "open", "x", "x"),
        )


def test_shadow_positions_primary_key_composite():
    conn = _fresh_db()
    now = "2026-05-05T00:00:00"
    conn.execute(
        "INSERT INTO test_shadow_positions (tester_user_id, market_symbol, quantity_units, updated_at) VALUES (?, ?, ?, ?)",
        (1, "BTC/POINTS", 5, now),
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO test_shadow_positions (tester_user_id, market_symbol, quantity_units, updated_at) VALUES (?, ?, ?, ?)",
            (1, "BTC/POINTS", 99, now),
        )


def test_shadow_ledger_basic_insert():
    conn = _fresh_db()
    conn.execute(
        """
        INSERT INTO test_shadow_ledger (
            ledger_uuid, tester_user_id, currency_type, direction, amount,
            balance_before, balance_after, action_type, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("led-1", 3, "soft", "credit", 100, 0, 100, "shadow_topup", "2026-05-05T00:00:00"),
    )
    conn.commit()
    row = conn.execute("SELECT amount, balance_after FROM test_shadow_ledger WHERE ledger_uuid='led-1'").fetchone()
    assert row["amount"] == 100
    assert row["balance_after"] == 100
