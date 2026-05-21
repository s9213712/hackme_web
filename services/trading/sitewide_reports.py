"""Snapshot builders for root trading dashboards.

These helpers are intentionally read-only and are meant to be called by the
background engine. Root HTTP routes should read the latest stored snapshot
instead of recomputing all users, positions, bots, and pool rows inline.
"""

from __future__ import annotations

from services.core.sqlite_safe import table_columns
from services.trading.accounting.core import units_to_quantity


def build_sitewide_pools_payload(service):
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        reserve = dict(service._reserve(conn))
        funding_pool = service._funding_pool_payload(conn)
        fee_summary = dict(conn.execute(
            """
            SELECT
                COUNT(*) AS fill_count,
                COALESCE(SUM(fee_points), 0) AS total_fee_points,
                COALESCE(SUM(reserve_delta_points), 0) AS reserve_delta_points,
                MAX(created_at) AS latest_fill_at
            FROM trading_fills
            """
        ).fetchone())
        lending_summary = dict(conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN event_type IN ('margin_principal_lent', 'margin_collateral_withdraw_principal_lent') THEN ABS(delta_points) ELSE 0 END), 0) AS lent_out_points,
                COALESCE(SUM(CASE WHEN event_type='margin_principal_repaid' THEN delta_points ELSE 0 END), 0) AS repaid_points,
                COALESCE(SUM(CASE WHEN event_type='margin_interest_retained' THEN delta_points ELSE 0 END), 0) AS interest_retained_points,
                COALESCE(SUM(CASE WHEN event_type IN ('fee_retained', 'margin_fee_retained') THEN delta_points ELSE 0 END), 0) AS fee_retained_points,
                COALESCE(SUM(CASE WHEN event_type='margin_profit_paid' THEN ABS(delta_points) ELSE 0 END), 0) AS profit_paid_points,
                COUNT(*) AS reserve_event_count,
                MAX(created_at) AS latest_reserve_event_at
            FROM trading_reserve_pool_events
            """
        ).fetchone())
        open_margin = dict(conn.execute(
            """
            SELECT
                COUNT(*) AS open_margin_positions,
                COALESCE(SUM(principal_points), 0) AS open_principal_points,
                COALESCE(SUM(collateral_points), 0) AS open_collateral_points,
                COALESCE(SUM(interest_points - interest_paid_points), 0) AS open_interest_due_points,
                COALESCE(SUM(interest_carry_micropoints), 0) AS interest_carry_micropoints
            FROM trading_margin_positions
            WHERE status='open'
            """
        ).fetchone()) if table_columns(conn, "trading_margin_positions") else {
            "open_margin_positions": 0,
            "open_principal_points": 0,
            "open_collateral_points": 0,
            "open_interest_due_points": 0,
            "interest_carry_micropoints": 0,
        }
        reserve_events = [
            dict(row)
            for row in conn.execute(
                """
                SELECT e.*, actor.username AS actor_username, source.username AS source_username
                FROM trading_reserve_pool_events e
                LEFT JOIN users actor ON actor.id=e.actor_user_id
                LEFT JOIN users source ON source.id=e.source_user_id
                ORDER BY e.id DESC
                LIMIT 30
                """
            ).fetchall()
        ]
        return {
            "ok": True,
            "pools": {
                "reserve_pool": reserve,
                "funding_pool": funding_pool,
                "fee_summary": fee_summary,
                "lending_summary": lending_summary,
                "open_margin_summary": open_margin,
                "reserve_events": reserve_events,
                "read_only": True,
                "snapshot_backed": True,
            },
        }
    finally:
        conn.close()


def build_sitewide_user_positions_payload(service):
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        spot_summary = dict(conn.execute(
            """
            SELECT COUNT(*) AS position_count
            FROM trading_spot_positions p
            JOIN users u ON u.id=p.user_id
            WHERE COALESCE(LOWER(u.username), '') != 'root'
              AND (p.quantity_units > 0 OR p.locked_quantity_units > 0)
            """
        ).fetchone())
        spot_positions = [
            {
                **dict(row),
                "quantity": units_to_quantity(row["quantity_units"]),
                "locked_quantity": units_to_quantity(row["locked_quantity_units"]),
            }
            for row in conn.execute(
                """
                SELECT p.*, u.username
                FROM trading_spot_positions p
                JOIN users u ON u.id=p.user_id
                WHERE COALESCE(LOWER(u.username), '') != 'root'
                  AND (p.quantity_units > 0 OR p.locked_quantity_units > 0)
                ORDER BY p.updated_at DESC, p.user_id ASC, p.market_symbol ASC
                LIMIT 200
                """
            ).fetchall()
        ]
        has_margin = bool(table_columns(conn, "trading_margin_positions"))
        margin_summary = dict(conn.execute(
            """
            SELECT COUNT(*) AS position_count
            FROM trading_margin_positions p
            JOIN users u ON u.id=p.user_id
            WHERE COALESCE(LOWER(u.username), '') != 'root'
              AND p.status='open'
            """
        ).fetchone()) if has_margin else {"position_count": 0}
        margin_positions = [
            {
                **dict(row),
                "quantity": units_to_quantity(row["quantity_units"]),
                "interest_due_points": max(0, int(row["interest_points"] or 0) - int(row["interest_paid_points"] or 0)),
            }
            for row in conn.execute(
                """
                SELECT p.*, u.username
                FROM trading_margin_positions p
                JOIN users u ON u.id=p.user_id
                WHERE COALESCE(LOWER(u.username), '') != 'root'
                  AND p.status='open'
                ORDER BY p.updated_at DESC, p.user_id ASC
                LIMIT 200
                """
            ).fetchall()
        ] if has_margin else []
        order_summary = dict(conn.execute(
            """
            SELECT
                COUNT(*) AS open_orders,
                COALESCE(SUM(frozen_points + trial_frozen_points + chain_frozen_points), 0) AS frozen_order_points,
                COALESCE(SUM(quantity_units - filled_quantity_units), 0) AS remaining_quantity_units
            FROM trading_orders o
            JOIN users u ON u.id=o.user_id
            WHERE COALESCE(LOWER(u.username), '') != 'root'
              AND o.status IN ('open', 'partially_filled')
            """
        ).fetchone())
        bot_summary = dict(conn.execute(
            """
            SELECT
                COUNT(*) AS bot_count,
                COALESCE(SUM(CASE WHEN b.enabled=1 THEN 1 ELSE 0 END), 0) AS enabled_bot_count
            FROM trading_bots b
            JOIN users u ON u.id=b.user_id
            WHERE COALESCE(LOWER(u.username), '') != 'root'
            """
        ).fetchone()) if table_columns(conn, "trading_bots") else {"bot_count": 0, "enabled_bot_count": 0}
        grid_bot_summary = dict(conn.execute(
            """
            SELECT
                COUNT(*) AS grid_bot_count,
                COALESCE(SUM(CASE WHEN gb.enabled=1 THEN 1 ELSE 0 END), 0) AS enabled_grid_bot_count
            FROM trading_grid_bots gb
            JOIN users u ON u.id=gb.user_id
            WHERE COALESCE(LOWER(u.username), '') != 'root'
            """
        ).fetchone()) if table_columns(conn, "trading_grid_bots") else {"grid_bot_count": 0, "enabled_grid_bot_count": 0}
        bots = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    b.bot_uuid,
                    b.user_id,
                    u.username,
                    b.bot_type,
                    b.name,
                    b.market_symbol,
                    b.side,
                    b.order_type,
                    b.quantity_text,
                    b.limit_price_points,
                    b.trigger_type,
                    b.trigger_price_points,
                    b.enabled,
                    b.run_count,
                    b.max_runs,
                    b.cooldown_seconds,
                    b.interval_hours,
                    b.budget_points,
                    b.stop_loss_percent,
                    b.take_profit_percent,
                    b.last_run_at,
                    b.last_error,
                    b.updated_at
                FROM trading_bots b
                JOIN users u ON u.id=b.user_id
                WHERE COALESCE(LOWER(u.username), '') != 'root'
                ORDER BY b.enabled DESC, b.updated_at DESC, b.id DESC
                LIMIT 200
                """
            ).fetchall()
        ] if table_columns(conn, "trading_bots") else []
        grid_bots = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    gb.bot_uuid,
                    gb.user_id,
                    u.username,
                    'grid' AS bot_type,
                    gb.name,
                    gb.market_symbol,
                    gb.enabled,
                    gb.total_profit_points,
                    gb.total_trades,
                    gb.initial_price_points,
                    gb.lower_price_points,
                    gb.upper_price_points,
                    gb.grid_count,
                    gb.order_amount_points,
                    gb.stop_loss_percent,
                    gb.take_profit_percent,
                    gb.last_scan_at,
                    gb.last_error,
                    gb.updated_at,
                    COALESCE(SUM(CASE WHEN go.status='open' THEN 1 ELSE 0 END), 0) AS open_grid_orders,
                    COALESCE(SUM(CASE WHEN go.status='filled' THEN 1 ELSE 0 END), 0) AS filled_grid_orders
                FROM trading_grid_bots gb
                JOIN users u ON u.id=gb.user_id
                LEFT JOIN trading_grid_orders go ON go.grid_bot_id=gb.id
                WHERE COALESCE(LOWER(u.username), '') != 'root'
                GROUP BY gb.id
                ORDER BY gb.enabled DESC, gb.updated_at DESC, gb.id DESC
                LIMIT 200
                """
            ).fetchall()
        ] if table_columns(conn, "trading_grid_bots") else []
        return {
            "ok": True,
            "positions": {
                "summary": {
                    "spot_position_count": int(spot_summary["position_count"] or 0),
                    "margin_position_count": int(margin_summary["position_count"] or 0),
                    "open_order_count": int(order_summary["open_orders"] or 0),
                    "frozen_order_points": int(order_summary["frozen_order_points"] or 0),
                    "remaining_order_quantity": units_to_quantity(order_summary["remaining_quantity_units"]),
                    "bot_count": int(bot_summary["bot_count"] or 0),
                    "enabled_bot_count": int(bot_summary["enabled_bot_count"] or 0),
                    "grid_bot_count": int(grid_bot_summary["grid_bot_count"] or 0),
                    "enabled_grid_bot_count": int(grid_bot_summary["enabled_grid_bot_count"] or 0),
                    "total_bot_count": int(bot_summary["bot_count"] or 0) + int(grid_bot_summary["grid_bot_count"] or 0),
                    "total_enabled_bot_count": int(bot_summary["enabled_bot_count"] or 0) + int(grid_bot_summary["enabled_grid_bot_count"] or 0),
                    "root_simulated_excluded": True,
                },
                "spot_positions": spot_positions,
                "margin_positions": margin_positions,
                "bots": bots,
                "grid_bots": grid_bots,
                "order_summary": order_summary,
                "read_only": True,
                "snapshot_backed": True,
            },
        }
    finally:
        conn.close()


def build_root_report_payload(service):
    return {"ok": True, "report": service.root_report()}


def build_sitewide_snapshot_payloads(service):
    return {
        "root_report": build_root_report_payload(service),
        "sitewide_pools": build_sitewide_pools_payload(service),
        "sitewide_user_positions": build_sitewide_user_positions_payload(service),
    }
