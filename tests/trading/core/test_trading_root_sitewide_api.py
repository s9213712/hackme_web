import sqlite3

from flask import Flask, jsonify

from routes.trading import register_trading_routes
from services.points_chain import PointsLedgerService, ensure_points_economy_schema
from services.trading.trading_engine import TradingEngineService, ensure_trading_schema


def _db(tmp_path):
    path = tmp_path / "root_sitewide_api.db"

    def get_db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    conn = get_db()
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, role TEXT NOT NULL DEFAULT 'user', status TEXT NOT NULL DEFAULT 'active')"
    )
    conn.execute(
        "INSERT INTO users (username, role, status) VALUES "
        "('alice', 'user', 'active'), "
        "('root', 'super_admin', 'active'), "
        "('admin', 'manager', 'active')"
    )
    ensure_points_economy_schema(conn)
    ensure_trading_schema(conn)
    conn.commit()
    conn.close()
    return get_db


def _app(tmp_path, actor):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    trading = TradingEngineService(get_db=get_db, points_service=points, live_price_provider=lambda symbol: 100)

    app = Flask(__name__)
    app.testing = True

    def passthrough(fn):
        return fn

    def json_resp(payload, status=None):
        response = jsonify(payload)
        return (response, status) if status else response

    register_trading_routes(app, {
        "trading_service": trading,
        "get_current_user_ctx": lambda: actor,
        "json_resp": json_resp,
        "require_csrf": passthrough,
        "require_csrf_safe": passthrough,
        "audit": lambda *args, **kwargs: None,
        "check_user_rate_limit": lambda *args, **kwargs: (False, {}),
    })
    return app, points, trading, get_db


def test_root_sitewide_user_positions_are_read_only_and_exclude_root(tmp_path):
    app, points, trading, get_db = _app(tmp_path, {"id": 2, "username": "root", "role": "super_admin"})
    points.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=1000,
        action_type="seed_member",
        idempotency_key="seed:member",
    )
    points.record_transaction(
        user_id=2,
        currency_type="points",
        direction="credit",
        amount=5000,
        action_type="seed_root",
        idempotency_key="seed:root",
    )
    conn = get_db()
    try:
        trading.ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO trading_spot_positions (
                user_id, market_symbol, quantity_units, locked_quantity_units,
                avg_cost_points, updated_at
            ) VALUES (1, 'BTC/POINTS', 100000000, 0, 100, '2026-01-01T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO trading_margin_positions (
                position_uuid, user_id, market_symbol, position_type, quantity_units,
                entry_price_points, principal_points, collateral_points,
                interest_points, interest_paid_points, status, opened_at, updated_at
            ) VALUES (
                'pos-alice-1', 1, 'BTC/POINTS', 'margin_long', 100000000,
                100, 900, 100, 12, 2, 'open',
                '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO trading_orders (
                order_uuid, user_id, market_symbol, side, order_type, quantity_units,
                limit_price_points, status, frozen_points, created_at, updated_at
            ) VALUES (
                'ord-alice-1', 1, 'BTC/POINTS', 'buy', 'limit', 100000000,
                100, 'open', 100, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO trading_bots (
                bot_uuid, user_id, bot_type, name, market_symbol, side, order_type,
                quantity_text, trigger_type, trigger_price_points, enabled, max_runs,
                run_count, cooldown_seconds, interval_hours, budget_points,
                created_at, updated_at
            ) VALUES (
                'bot-alice-1', 1, 'conditional', 'alice spot bot', 'BTC/POINTS',
                'buy', 'market', '0.1', 'price_below', 95, 1, 3,
                1, 60, 24, 100,
                '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO trading_grid_bots (
                bot_uuid, user_id, name, market_symbol, upper_price_points,
                lower_price_points, grid_count, order_amount_points, enabled,
                total_profit_points, total_trades, initial_price_points,
                created_at, updated_at
            ) VALUES (
                'grid-alice-1', 1, 'alice grid bot', 'BTC/POINTS', 120,
                80, 5, 100, 1,
                7, 2, 100,
                '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO trading_spot_positions (
                user_id, market_symbol, quantity_units, locked_quantity_units,
                avg_cost_points, updated_at
            ) VALUES (2, 'BTC/POINTS', 900000000, 0, 100, '2026-01-01T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO trading_spot_positions (
                user_id, market_symbol, quantity_units, locked_quantity_units,
                avg_cost_points, updated_at
            ) VALUES (3, 'ETH/POINTS', 200000000, 0, 100, '2026-01-01T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO trading_margin_positions (
                position_uuid, user_id, market_symbol, position_type, quantity_units,
                entry_price_points, principal_points, collateral_points,
                interest_points, interest_paid_points, status, opened_at, updated_at
            ) VALUES (
                'pos-admin-1', 3, 'ETH/POINTS', 'margin_long', 200000000,
                100, 900, 100, 7, 1, 'open',
                '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO trading_bots (
                bot_uuid, user_id, bot_type, name, market_symbol, side, order_type,
                quantity_text, trigger_type, trigger_price_points, enabled, max_runs,
                run_count, cooldown_seconds, interval_hours, budget_points,
                created_at, updated_at
            ) VALUES (
                'bot-admin-1', 3, 'conditional', 'admin spot bot', 'ETH/POINTS',
                'buy', 'market', '0.2', 'price_below', 95, 1, 3,
                1, 60, 24, 100,
                '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    trading.refresh_root_trading_snapshots(source_job_key="unit-test")
    response = app.test_client().get("/api/root/trading/sitewide/user-positions")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["positions"]["read_only"] is True
    assert payload["positions"]["summary"]["root_simulated_excluded"] is True
    assert "total_outstanding_points" not in payload["positions"]["summary"]
    assert "wallets" not in payload["positions"]
    assert {row["username"] for row in payload["positions"]["spot_positions"]} == {"alice", "admin"}
    assert {row["username"] for row in payload["positions"]["margin_positions"]} == {"alice", "admin"}
    assert {row["username"] for row in payload["positions"]["bots"]} == {"alice", "admin"}
    assert payload["positions"]["margin_positions"][0]["interest_due_points"] == 10
    assert payload["positions"]["summary"]["spot_position_count"] == 2
    assert payload["positions"]["summary"]["margin_position_count"] == 2
    assert payload["positions"]["summary"]["open_order_count"] == 1
    assert payload["positions"]["summary"]["bot_count"] == 2
    assert payload["positions"]["summary"]["grid_bot_count"] == 1
    assert payload["positions"]["summary"]["total_enabled_bot_count"] == 3
    assert {row["name"] for row in payload["positions"]["bots"]} == {"alice spot bot", "admin spot bot"}
    assert payload["positions"]["grid_bots"][0]["name"] == "alice grid bot"


def test_root_sitewide_pools_endpoint_is_root_only(tmp_path):
    app, _points, trading, get_db = _app(tmp_path, {"id": 2, "username": "root", "role": "super_admin"})
    conn = get_db()
    try:
        trading.ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO trading_reserve_pool_events (
                event_uuid, delta_points, balance_after, event_type, reason,
                actor_user_id, source_user_id, created_at
            ) VALUES (
                'reserve-event-1', 25, 10025, 'fee_retained', 'test fee',
                2, 1, '2026-01-01T00:00:00Z'
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    trading.refresh_root_trading_snapshots(source_job_key="unit-test")
    response = app.test_client().get("/api/root/trading/sitewide/pools")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["pools"]["read_only"] is True
    assert payload["pools"]["reserve_events"][0]["event_type"] == "fee_retained"

    non_root_dir = tmp_path / "non_root"
    non_root_dir.mkdir()
    non_root_app, _points, _trading, _get_db = _app(non_root_dir, {"id": 1, "username": "alice", "role": "user"})
    forbidden = non_root_app.test_client().get("/api/root/trading/sitewide/pools")
    assert forbidden.status_code == 403


def test_root_sitewide_endpoints_require_snapshot_instead_of_inline_recompute(tmp_path):
    app, _points, _trading, _get_db = _app(tmp_path, {"id": 2, "username": "root", "role": "super_admin"})

    response = app.test_client().get("/api/root/trading/sitewide/user-positions")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["snapshot"]["missing"] is True
    assert payload["snapshot"]["required_job_key"] == "sitewide_metrics_refresh"


def test_root_admin_report_reads_snapshot_only(tmp_path):
    app, _points, trading, _get_db = _app(tmp_path, {"id": 2, "username": "root", "role": "super_admin"})

    missing = app.test_client().get("/api/admin/trading/report")
    missing_payload = missing.get_json()

    assert missing.status_code == 200
    assert missing_payload["snapshot"]["missing"] is True
    assert missing_payload["snapshot"]["required_job_key"] == "sitewide_metrics_refresh"

    trading.refresh_root_trading_snapshots(source_job_key="unit-test", source_run_uuid="run-report-test")
    response = app.test_client().get("/api/admin/trading/report")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert "report" in payload
    assert payload["snapshot"]["snapshot_key"] == "root_report"
    assert payload["snapshot"]["source_run_uuid"] == "run-report-test"


def test_root_run_once_enqueues_background_job(tmp_path):
    app, _points, _trading, _get_db = _app(tmp_path, {"id": 2, "username": "root", "role": "super_admin"})

    response = app.test_client().post(
        "/api/root/trading/background/run-once",
        json={"job_key": "sitewide_metrics_refresh", "confirm": "RUN_TRADING_JOB_ONCE"},
    )
    payload = response.get_json()

    assert response.status_code == 202
    assert payload["ok"] is True
    assert payload["queued"] is True
    assert payload["job_key"] == "sitewide_metrics_refresh"
    assert payload["queue_uuid"]


def test_root_sitewide_refresh_rebuilds_snapshot_before_read(tmp_path):
    app, _points, trading, get_db = _app(tmp_path, {"id": 2, "username": "root", "role": "super_admin"})
    conn = get_db()
    try:
        trading.ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO trading_spot_positions (
                user_id, market_symbol, quantity_units, locked_quantity_units,
                avg_cost_points, updated_at
            ) VALUES (3, 'ETH/POINTS', 200000000, 0, 100, '2026-01-01T00:00:00Z')
            """
        )
        conn.commit()
    finally:
        conn.close()

    refresh = app.test_client().post("/api/root/trading/sitewide/refresh", json={"reason": "unit-test"})
    refresh_payload = refresh.get_json()
    response = app.test_client().get("/api/root/trading/sitewide/user-positions")
    payload = response.get_json()

    assert refresh.status_code == 200
    assert refresh_payload["ok"] is True
    assert "sitewide_user_positions" in refresh_payload["refresh"]["snapshot_keys"]
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["snapshot"]["source_job_key"] == "root_manual_sitewide_refresh"
    assert [row["username"] for row in payload["positions"]["spot_positions"]] == ["admin"]
