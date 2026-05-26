"""Snapshot builders for root trading dashboards.

These helpers are intentionally read-only and are meant to be called by the
background engine. Root HTTP routes should read the latest stored snapshot
instead of recomputing all users, positions, bots, and pool rows inline.
"""

from __future__ import annotations

from services.core.sqlite_safe import table_columns
from services.trading.accounting.core import units_to_quantity


CAPITAL_FLOW_EVENT_TYPES = {
    "initial_funding",
    "official_exchange_fund_replenishment",
    "root_reserve_allocation",
    "walletized_exchange_fund_alignment",
}


PRINCIPAL_TRANSFER_EVENT_TYPES = {
    "margin_principal_lent",
    "margin_collateral_withdraw_principal_lent",
    "margin_principal_repaid",
}


RESERVE_FLOW_LABELS = {
    "initial_funding": ("capital", "初始資本"),
    "official_exchange_fund_replenishment": ("capital", "官方財庫撥補"),
    "root_reserve_allocation": ("capital", "root 交易所基金撥款"),
    "walletized_exchange_fund_alignment": ("capital", "官方熱錢包校準"),
    "spot_cfd_principal_collected": ("customer_principal", "現貨/CFD 客戶本金流入"),
    "spot_cfd_gross_payout": ("customer_payout", "現貨/CFD 客戶賣出或盈利支付"),
    "fee_retained": ("trading_fee", "現貨交易手續費"),
    "margin_fee_retained": ("trading_fee", "借貸交易手續費"),
    "margin_interest_retained": ("interest", "借貸利息收入"),
    "margin_loss_collected": ("customer_loss", "客戶虧損結算流入"),
    "margin_principal_lent": ("lending_principal", "借貸本金撥出"),
    "margin_collateral_withdraw_principal_lent": ("lending_principal", "提領保證金補借貸本金"),
    "margin_principal_repaid": ("lending_repay", "借貸本金歸還"),
    "margin_profit_paid": ("customer_payout", "客戶借貸盈利支付"),
}


def _reserve_flow_label(event_type: str) -> tuple[str, str]:
    normalized = str(event_type or "").strip()
    if normalized in RESERVE_FLOW_LABELS:
        return RESERVE_FLOW_LABELS[normalized]
    return "other", normalized.replace("_", " ").strip() or "其他基金事件"


def _build_reserve_flow_summary(conn, reserve: dict) -> dict:
    rows = conn.execute(
        """
        SELECT
            event_type,
            COUNT(*) AS event_count,
            COALESCE(SUM(CASE WHEN delta_points > 0 THEN delta_points ELSE 0 END), 0) AS inflow_points,
            COALESCE(SUM(CASE WHEN delta_points < 0 THEN ABS(delta_points) ELSE 0 END), 0) AS outflow_points,
            COALESCE(SUM(delta_points), 0) AS net_points,
            MIN(created_at) AS first_event_at,
            MAX(created_at) AS latest_event_at
        FROM trading_reserve_pool_events
        GROUP BY event_type
        ORDER BY ABS(COALESCE(SUM(delta_points), 0)) DESC, event_type ASC
        """
    ).fetchall()
    categories = []
    total_inflow = 0
    total_outflow = 0
    capital_inflow = 0
    capital_outflow = 0
    principal_inflow = 0
    principal_outflow = 0
    for row in rows:
        event_type = str(row["event_type"] or "")
        category_key, label = _reserve_flow_label(event_type)
        inflow = int(row["inflow_points"] or 0)
        outflow = int(row["outflow_points"] or 0)
        net = int(row["net_points"] or 0)
        total_inflow += inflow
        total_outflow += outflow
        if event_type in CAPITAL_FLOW_EVENT_TYPES:
            capital_inflow += inflow
            capital_outflow += outflow
            statement_role = "capital"
        elif event_type in PRINCIPAL_TRANSFER_EVENT_TYPES:
            principal_inflow += inflow
            principal_outflow += outflow
            statement_role = "principal_transfer"
        else:
            statement_role = "operating"
        categories.append({
            "event_type": event_type,
            "category_key": category_key,
            "label": label,
            "statement_role": statement_role,
            "counts_as_operating": statement_role == "operating",
            "event_count": int(row["event_count"] or 0),
            "inflow_points": inflow,
            "outflow_points": outflow,
            "net_points": net,
            "direction": "inflow" if net > 0 else "outflow" if net < 0 else "flat",
            "first_event_at": row["first_event_at"],
            "latest_event_at": row["latest_event_at"],
        })
    net_flow = total_inflow - total_outflow
    reserve_balance = int((reserve or {}).get("balance_points") or 0)
    operating_inflow = max(0, total_inflow - capital_inflow - principal_inflow)
    operating_outflow = max(0, total_outflow - capital_outflow - principal_outflow)
    operating_net = operating_inflow - operating_outflow
    realized_categories = [item for item in categories if item.get("counts_as_operating")]
    return {
        "total_inflow_points": total_inflow,
        "total_outflow_points": total_outflow,
        "net_flow_points": net_flow,
        "capital_inflow_points": capital_inflow,
        "capital_outflow_points": capital_outflow,
        "principal_inflow_points": principal_inflow,
        "principal_outflow_points": principal_outflow,
        "principal_net_points": principal_inflow - principal_outflow,
        "non_operating_inflow_points": capital_inflow + principal_inflow,
        "non_operating_outflow_points": capital_outflow + principal_outflow,
        "operating_inflow_points": operating_inflow,
        "operating_outflow_points": operating_outflow,
        "operating_net_points": operating_net,
        "current_balance_points": reserve_balance,
        "balance_matches_event_replay": reserve_balance == net_flow,
        "event_count": sum(int(item["event_count"] or 0) for item in categories),
        "category_count": len(categories),
        "realized_category_count": len(realized_categories),
        "realized_categories": realized_categories,
        "categories": categories,
    }


def build_sitewide_pools_payload(service):
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        reserve = dict(service._reserve(conn))
        funding_pool = service._funding_pool_payload(conn)
        try:
            pointschain_exchange_fund = service._exchange_fund_chain_snapshot(conn)
        except Exception as exc:
            pointschain_exchange_fund = {"error": str(exc)[:240]}
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
        fund_flow_summary = _build_reserve_flow_summary(conn, reserve)
        return {
            "ok": True,
            "pools": {
                "reserve_pool": reserve,
                "funding_pool": funding_pool,
                "pointschain_exchange_fund": pointschain_exchange_fund,
                "fee_summary": fee_summary,
                "lending_summary": lending_summary,
                "open_margin_summary": open_margin,
                "reserve_events": reserve_events,
                "fund_flow_summary": fund_flow_summary,
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
        markets = []
        for market_row in conn.execute("SELECT * FROM trading_markets").fetchall():
            market_item = service._market_payload(market_row)
            reference_context, risk_grade_context = service._stored_market_price_contexts(market_item)
            markets.append(
                service._attach_market_price_contexts(
                    market_item,
                    reference_context=reference_context,
                    risk_grade_context=risk_grade_context,
                )
            )
        market_map = {row["symbol"]: row for row in markets}
        spot_realized_map = {
            (int(row["user_id"]), row["market_symbol"]): int(row["realized_pnl_points"] or 0)
            for row in conn.execute(
                """
                SELECT user_id, market_symbol, COALESCE(SUM(net_pnl_points), 0) AS realized_pnl_points
                FROM trading_spot_realized_pnl
                GROUP BY user_id, market_symbol
                """
            ).fetchall()
        }
        spot_fee_map = {
            (int(row["user_id"]), row["market_symbol"]): int(row["total_fee_points"] or 0)
            for row in conn.execute(
                """
                SELECT user_id, market_symbol, COALESCE(SUM(fee_points), 0) AS total_fee_points
                FROM trading_fills
                GROUP BY user_id, market_symbol
                """
            ).fetchall()
        }
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
            service._position_payload_with_metrics(
                row,
                market=market_map.get(row["market_symbol"]),
                realized_points=spot_realized_map.get((int(row["user_id"]), row["market_symbol"]), 0),
                total_fees=spot_fee_map.get((int(row["user_id"]), row["market_symbol"]), 0),
            )
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
                **service._margin_position_payload_with_risk(conn, row, market=market_map.get(row["market_symbol"])),
                "interest_due_points": max(0, int(row["interest_points"] or 0) - int(row["interest_paid_points"] or 0)),
                "total_fee_points": int(row["open_fee_points"] or 0) + int(row["close_fee_points"] or 0),
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
        spot_unrealized_pnl = sum(int(row.get("unrealized_pnl_points") or 0) for row in spot_positions)
        spot_realized_pnl = sum(int(row.get("realized_pnl_points") or 0) for row in spot_positions)
        spot_fee_points = sum(int(row.get("total_fee_points") or 0) for row in spot_positions)
        margin_unrealized_pnl = sum(int(row.get("unrealized_pnl_points") or 0) for row in margin_positions)
        margin_realized_pnl = sum(int(row.get("realized_pnl_points") or 0) for row in margin_positions)
        margin_fee_points = sum(int(row.get("total_fee_points") or 0) for row in margin_positions)
        margin_interest_due = sum(int(row.get("interest_due_points") or 0) for row in margin_positions)
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
                    "spot_unrealized_pnl_points": spot_unrealized_pnl,
                    "spot_realized_pnl_points": spot_realized_pnl,
                    "margin_unrealized_pnl_points": margin_unrealized_pnl,
                    "margin_realized_pnl_points": margin_realized_pnl,
                    "total_unrealized_pnl_points": spot_unrealized_pnl + margin_unrealized_pnl,
                    "total_realized_pnl_points": spot_realized_pnl + margin_realized_pnl,
                    "spot_fee_points": spot_fee_points,
                    "margin_fee_points": margin_fee_points,
                    "total_fee_points": spot_fee_points + margin_fee_points,
                    "margin_interest_due_points": margin_interest_due,
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
