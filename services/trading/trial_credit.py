"""Trading trial-credit orchestration extracted from the engine facade."""

from __future__ import annotations

import uuid
from datetime import datetime

from services.server_mode.routing import resolve_table
from services.trading.accounting.trial_credit import (
    trial_allocate_sell_result,
    trial_credit_expires_at,
    trial_credit_status_after_delta,
    trial_units_for_buy,
)


def _now():
    return datetime.now().isoformat()


def trial_credit_row(service, conn, user_id):
    return conn.execute("SELECT * FROM trading_trial_credits WHERE user_id=?", (int(user_id),)).fetchone()


def ensure_trial_credit(service, conn, user_id, *, actor=None, allow_reclaim=True):
    user_id = int(user_id)
    if service._is_root_user_id(conn, user_id):
        return None
    row = service._trial_credit_row(conn, user_id)
    now = _now()
    if not row:
        expires_at = trial_credit_expires_at(now, days_valid=service.TRIAL_CREDIT_DAYS)
        conn.execute(
            """
            INSERT INTO trading_trial_credits (
                user_id, initial_points, available_points, locked_points, deployed_points,
                status, activated_at, expires_at, updated_at
            ) VALUES (?, ?, ?, 0, 0, 'active', ?, ?, ?)
            """,
            (user_id, service.TRIAL_CREDIT_INITIAL_POINTS, service.TRIAL_CREDIT_INITIAL_POINTS, now, expires_at, now),
        )
        service._audit_event(
            conn,
            "TRADING_TRIAL_CREDIT_GRANTED",
            "exchange trial credit granted as system loan",
            actor=actor or service._system_actor(),
            target_user_id=user_id,
            severity="info",
            metadata={
                "loan_type": "exchange_trial_credit",
                "amount_points": service.TRIAL_CREDIT_INITIAL_POINTS,
                "expires_at": expires_at,
                "reclaim_policy": "principal_only; user keeps realized profit",
            },
        )
        row = service._trial_credit_row(conn, user_id)
    if allow_reclaim and row and row["status"] == "active":
        try:
            expires_at = datetime.fromisoformat(str(row["expires_at"]))
        except Exception:
            expires_at = None
        if expires_at and datetime.fromisoformat(_now()) >= expires_at:
            service._reclaim_trial_credit(conn, user_id, actor=actor or service._system_actor(), reason="TRIAL_CREDIT_EXPIRED")
            row = service._trial_credit_row(conn, user_id)
    return row


def trial_position(service, conn, user_id, symbol):
    now = _now()
    conn.execute(
        """
        INSERT OR IGNORE INTO trading_trial_position_costs
            (user_id, market_symbol, quantity_units, trial_cost_points, updated_at)
        VALUES (?, ?, 0, 0, ?)
        """,
        (int(user_id), symbol, now),
    )
    return conn.execute(
        "SELECT * FROM trading_trial_position_costs WHERE user_id=? AND market_symbol=?",
        (int(user_id), symbol),
    ).fetchone()


def trial_delta(service, conn, user_id, *, available_delta=0, locked_delta=0, deployed_delta=0, status=None, reclaimed=False):
    row = service._ensure_trial_credit(conn, user_id, allow_reclaim=False)
    if not row:
        return None
    next_available = int(row["available_points"] or 0) + int(available_delta)
    next_locked = int(row["locked_points"] or 0) + int(locked_delta)
    next_deployed = int(row["deployed_points"] or 0) + int(deployed_delta)
    if min(next_available, next_locked, next_deployed) < 0:
        raise ValueError("trial credit accounting would become negative")
    next_status = trial_credit_status_after_delta(
        status or row["status"],
        next_available=next_available,
        next_locked=next_locked,
        next_deployed=next_deployed,
    )
    conn.execute(
        """
        UPDATE trading_trial_credits
        SET available_points=?, locked_points=?, deployed_points=?, status=?,
            reclaimed_at=CASE WHEN ? THEN ? ELSE reclaimed_at END,
            updated_at=?
        WHERE user_id=?
        """,
        (next_available, next_locked, next_deployed, next_status, 1 if reclaimed else 0, _now(), _now(), int(user_id)),
    )
    return service._trial_credit_row(conn, user_id)


def trial_lock_for_buy(service, conn, user_id, total_points):
    row = service._ensure_trial_credit(conn, user_id)
    if not row or row["status"] != "active":
        return 0
    amount = min(int(total_points or 0), int(row["available_points"] or 0))
    if amount <= 0:
        return 0
    service._trial_delta(conn, user_id, available_delta=-amount, locked_delta=amount)
    return amount


def trial_spend(service, conn, user_id, amount):
    row = service._ensure_trial_credit(conn, user_id)
    if not row or row["status"] != "active":
        return 0
    amount = min(int(amount or 0), int(row["available_points"] or 0))
    if amount <= 0:
        return 0
    service._trial_delta(conn, user_id, available_delta=-amount)
    return amount


def trial_deploy(service, conn, user_id, amount):
    row = service._ensure_trial_credit(conn, user_id)
    if not row or row["status"] != "active":
        return 0
    amount = min(int(amount or 0), int(row["available_points"] or 0))
    if amount <= 0:
        return 0
    service._trial_delta(conn, user_id, available_delta=-amount, deployed_delta=amount)
    return amount


def trial_unlock(service, conn, user_id, amount):
    amount = int(amount or 0)
    if amount <= 0:
        return
    service._trial_delta(conn, user_id, available_delta=amount, locked_delta=-amount)


def set_trial_reclaim_blocked(service, conn, user_id, *, reason):
    reason = str(reason or "").strip()[:500]
    conn.execute(
        """
        UPDATE trading_trial_credits
        SET reclaim_blocked_reason=?, reclaim_blocked_at=?, updated_at=?
        WHERE user_id=?
        """,
        (reason, _now(), _now(), int(user_id)),
    )
    return service._trial_credit_row(conn, user_id)


def clear_trial_reclaim_blocked(service, conn, user_id):
    conn.execute(
        """
        UPDATE trading_trial_credits
        SET reclaim_blocked_reason='', reclaim_blocked_at=NULL, updated_at=?
        WHERE user_id=?
        """,
        (_now(), int(user_id)),
    )
    return service._trial_credit_row(conn, user_id)


def trial_mark_buy_executed(service, conn, *, user_id, market_symbol, quantity_units, trial_used_points, total_points):
    trial_used_points = int(trial_used_points or 0)
    if trial_used_points <= 0:
        return 0
    trial_units = trial_units_for_buy(
        quantity_units=quantity_units,
        trial_used_points=trial_used_points,
        total_points=total_points,
    )
    service._trial_delta(conn, user_id, locked_delta=-trial_used_points, deployed_delta=trial_used_points)
    trial_pos = service._trial_position(conn, user_id, market_symbol)
    conn.execute(
        """
        UPDATE trading_trial_position_costs
        SET quantity_units=?, trial_cost_points=?, updated_at=?
        WHERE user_id=? AND market_symbol=?
        """,
        (
            int(trial_pos["quantity_units"] or 0) + trial_units,
            int(trial_pos["trial_cost_points"] or 0) + trial_used_points,
            _now(),
            int(user_id),
            market_symbol,
        ),
    )
    return trial_units


def trial_allocate_sell(service, conn, *, user_id, market_symbol, quantity_units, net_credit_points):
    trial_pos = service._trial_position(conn, user_id, market_symbol)
    allocation = trial_allocate_sell_result(
        available_trial_units=int(trial_pos["quantity_units"] or 0),
        trial_cost_total=int(trial_pos["trial_cost_points"] or 0),
        quantity_units=quantity_units,
        net_credit_points=net_credit_points,
    )
    conn.execute(
        """
        UPDATE trading_trial_position_costs
        SET quantity_units=?, trial_cost_points=?, updated_at=?
        WHERE user_id=? AND market_symbol=?
        """,
        (allocation["remaining_units"], allocation["remaining_cost"], _now(), int(user_id), market_symbol),
    )
    service._trial_delta(
        conn,
        user_id,
        available_delta=allocation["trial_repaid_points"],
        deployed_delta=-allocation["trial_cost_points"],
    )
    return {
        "trial_units": allocation["trial_units"],
        "trial_cost_points": allocation["trial_cost_points"],
        "trial_repaid_points": allocation["trial_repaid_points"],
        "trial_profit_points": allocation["trial_profit_points"],
        "wallet_credit_points": allocation["wallet_credit_points"],
    }


def cancel_trial_reclaim_sell_orders(service, conn, user_id, *, actor, reason, ctx=None):
    route_ctx = service._routing_ctx_for_read(ctx)
    orders_table = resolve_table("orders", route_ctx)
    positions_table = resolve_table("positions", route_ctx)
    orders = conn.execute(
        f"""
        SELECT o.*
        FROM {orders_table} o
        JOIN trading_trial_position_costs t
          ON t.user_id=o.user_id AND t.market_symbol=o.market_symbol
        WHERE o.user_id=?
          AND o.side='sell'
          AND o.status IN ('open', 'partially_filled')
          AND t.quantity_units > 0
        ORDER BY o.id ASC
        """,
        (int(user_id),),
    ).fetchall()
    for order in orders:
        remaining_units = max(0, int(order["quantity_units"] or 0) - int(order["filled_quantity_units"] or 0))
        if remaining_units:
            conn.execute(
                f"""
                UPDATE {positions_table}
                SET quantity_units=quantity_units+?,
                    locked_quantity_units=MAX(locked_quantity_units-?, 0),
                    updated_at=?
                WHERE user_id=? AND market_symbol=?
                """,
                (remaining_units, remaining_units, _now(), int(user_id), order["market_symbol"]),
            )
        conn.execute(
            f"""
            UPDATE {orders_table}
            SET status='cancelled', reason=?, updated_at=?
            WHERE id=?
            """,
            (f"{reason}: trial credit reclaim unlocked sell order", _now(), order["id"]),
        )
        updated_order = conn.execute(f"SELECT * FROM {orders_table} WHERE id=?", (order["id"],)).fetchone()
        service._matching_orderbook_apply_order(updated_order, ctx=route_ctx)
        service._audit_event(
            conn,
            "TRADING_TRIAL_CREDIT_SELL_ORDER_CANCELLED",
            "open sell order cancelled so expired trial credit positions can be reclaimed",
            actor=actor,
            target_user_id=int(user_id),
            order_id=order["id"],
            market_symbol=order["market_symbol"],
            severity="warning",
            metadata={"reason": reason, "released_quantity_units": remaining_units},
        )


def release_trial_margin_collateral(service, conn, user_id, *, collateral_trial, available_delta_if_active=0):
    collateral_trial = int(collateral_trial or 0)
    if collateral_trial <= 0:
        return
    row = service._trial_credit_row(conn, user_id)
    if not row:
        return
    deployed_release = min(collateral_trial, int(row["deployed_points"] or 0))
    if deployed_release <= 0:
        return
    available_delta = int(available_delta_if_active or 0) if row["status"] == "active" else 0
    service._trial_delta(conn, user_id, available_delta=available_delta, deployed_delta=-deployed_release)


def reclaim_trial_credit(service, conn, user_id, *, actor=None, reason="TRIAL_CREDIT_RECLAIM", ctx=None):
    row = service._trial_credit_row(conn, user_id)
    if not row or row["status"] != "active":
        return row
    actor = actor or service._system_actor()
    reclaimed_before_sell = int(row["available_points"] or 0)
    route_ctx = service._routing_ctx_for_read(ctx)
    orders_table = resolve_table("orders", route_ctx)
    positions_table = resolve_table("positions", route_ctx)
    for order in conn.execute(
        f"""
        SELECT * FROM {orders_table}
        WHERE user_id=? AND side='buy' AND status IN ('open', 'partially_filled')
          AND trial_frozen_points > 0
        ORDER BY id ASC
        """,
        (int(user_id),),
    ).fetchall():
        trial_frozen = int(order["trial_frozen_points"] or 0)
        chain_frozen = int(order["chain_frozen_points"] or 0)
        if trial_frozen:
            service._trial_delta(conn, user_id, locked_delta=-trial_frozen)
        if chain_frozen:
            service._ledger(
                conn,
                user_id=user_id,
                currency_type="points",
                direction="unfreeze",
                amount=chain_frozen,
                action_type="trading_unfreeze",
                reference_type="trading_order",
                reference_id=order["order_uuid"],
                idempotency_key=f"trading:trial_reclaim_cancel_unfreeze:{order['order_uuid']}",
                reason="TRIAL_CREDIT_RECLAIM_CANCEL_ORDER",
                public_metadata={"order_id": order["id"], "market": order["market_symbol"], "side": order["side"]},
                actor=actor,
                ctx=route_ctx,
            )
        conn.execute(
            f"""
            UPDATE {orders_table}
            SET status='cancelled', frozen_points=0, trial_frozen_points=0, chain_frozen_points=0,
                reason=?, updated_at=?
            WHERE id=?
            """,
            (f"{reason}: trial credit reclaimed", _now(), order["id"]),
        )
        updated_order = conn.execute(f"SELECT * FROM {orders_table} WHERE id=?", (order["id"],)).fetchone()
        service._matching_orderbook_apply_order(updated_order, ctx=route_ctx)
        service._audit_event(
            conn,
            "TRADING_TRIAL_CREDIT_ORDER_CANCELLED",
            "open trial-funded buy order cancelled during trial credit reclaim",
            actor=actor,
            target_user_id=int(user_id),
            order_id=order["id"],
            market_symbol=order["market_symbol"],
            severity="warning",
            metadata={"reason": reason, "trial_frozen_points": trial_frozen, "chain_frozen_points": chain_frozen},
        )
    service._cancel_trial_reclaim_sell_orders(conn, user_id, actor=actor, reason=reason, ctx=route_ctx)
    validated_trial_sells = []
    for trial_pos in conn.execute(
        "SELECT * FROM trading_trial_position_costs WHERE user_id=? AND quantity_units>0 ORDER BY market_symbol",
        (int(user_id),),
    ).fetchall():
        position = service._position(conn, user_id, trial_pos["market_symbol"], ctx=route_ctx)
        sell_units = min(int(position["quantity_units"] or 0), int(trial_pos["quantity_units"] or 0))
        if sell_units <= 0:
            continue
        market = service._market(conn, trial_pos["market_symbol"])
        try:
            service._assert_market_boot_ready(market, usage="trial credit forced sell")
            current_price, price_source, price_meta = service._current_market_price_points(
                conn,
                market,
                with_meta=True,
                high_risk=True,
            )
            service._assert_price_meta_allows_high_risk_use(
                conn,
                actor=actor,
                market_symbol=market["symbol"],
                usage="trial credit forced sell",
                price_meta=price_meta,
            )
        except ValueError as exc:
            blocked_reason = str(exc)
            service._set_trial_reclaim_blocked(conn, user_id, reason=blocked_reason)
            service._audit_event(
                conn,
                "TRADING_TRIAL_CREDIT_RECLAIM_BLOCKED",
                "trial credit reclaim paused because no risk-grade settlement price is available",
                actor=actor,
                target_user_id=int(user_id),
                market_symbol=market["symbol"],
                severity="warning",
                metadata={
                    "reason": reason,
                    "reclaim_blocked_reason": blocked_reason,
                    "price_source": market.get("price_source"),
                },
            )
            return service._trial_credit_row(conn, user_id)
        validated_trial_sells.append(
            {
                "trial_pos": trial_pos,
                "sell_units": sell_units,
                "market": market,
                "current_price": current_price,
                "price_source": price_source,
            }
        )
    for planned_sell in validated_trial_sells:
        trial_pos = planned_sell["trial_pos"]
        sell_units = int(planned_sell["sell_units"])
        market = planned_sell["market"]
        current_price = planned_sell["current_price"]
        price_source = planned_sell["price_source"]
        order_uuid = str(uuid.uuid4())
        now = _now()
        conn.execute(
            f"""
            UPDATE {positions_table}
            SET quantity_units=quantity_units-?, locked_quantity_units=locked_quantity_units+?, updated_at=?
            WHERE user_id=? AND market_symbol=?
            """,
            (sell_units, sell_units, now, int(user_id), trial_pos["market_symbol"]),
        )
        cur = conn.execute(
            f"""
            INSERT INTO {orders_table} (
                order_uuid, user_id, market_symbol, side, order_type, funding_mode, execution_mode,
                quantity_units, limit_price_points, execution_price_points, status,
                frozen_points, trial_frozen_points, chain_frozen_points, fee_points,
                filled_quantity_units, reason, created_at, updated_at
            ) VALUES (?, ?, ?, 'sell', 'market', 'trial_mixed', 'house_counterparty',
                ?, NULL, ?, 'open', 0, 0, 0, 0, 0, ?, ?, ?)
            """,
            (order_uuid, int(user_id), trial_pos["market_symbol"], sell_units, current_price, reason, now, now),
        )
        order = conn.execute(f"SELECT * FROM {orders_table} WHERE id=?", (cur.lastrowid,)).fetchone()
        fill = service._execute_order(conn, order, market, actor=actor, ctx=route_ctx)
        service._audit_event(
            conn,
            "TRADING_TRIAL_CREDIT_FORCED_SELL",
            "trial credit expiry forced spot liquidation",
            actor=actor,
            target_user_id=int(user_id),
            order_id=order["id"],
            market_symbol=market["symbol"],
            severity="warning",
            metadata={"fill_id": fill["id"], "price_source": price_source, "reason": reason},
        )
    final = service._trial_credit_row(conn, user_id)
    reclaimed_after_sell = int(final["available_points"] or 0)
    open_margin_trial = int(conn.execute(
        """
        SELECT COALESCE(SUM(collateral_trial_points), 0)
        FROM trading_margin_positions
        WHERE user_id=? AND status='open' AND collateral_trial_points > 0
        """,
        (int(user_id),),
    ).fetchone()[0] or 0)
    final_deployed = int(final["deployed_points"] or 0)
    open_margin_trial = min(open_margin_trial, final_deployed)
    lost_points = max(0, final_deployed - open_margin_trial)
    conn.execute(
        """
        UPDATE trading_trial_credits
        SET available_points=0, locked_points=0, deployed_points=?, status='expired',
            reclaimed_at=?, updated_at=?
        WHERE user_id=?
        """,
        (open_margin_trial, _now(), _now(), int(user_id)),
    )
    conn.execute(
        "UPDATE trading_trial_position_costs SET quantity_units=0, trial_cost_points=0, updated_at=? WHERE user_id=?",
        (_now(), int(user_id)),
    )
    service._audit_event(
        conn,
        "TRADING_TRIAL_CREDIT_RECLAIMED",
        "exchange trial credit reclaimed from user",
        actor=actor,
        target_user_id=int(user_id),
        severity="warning",
        metadata={
            "loan_type": "exchange_trial_credit",
            "reason": reason,
            "reclaimed_available_before_sell": reclaimed_before_sell,
            "reclaimed_available_after_sell": reclaimed_after_sell,
            "lost_points": lost_points,
            "profit_policy": "realized profit remains with user",
        },
    )
    service._clear_trial_reclaim_blocked(conn, user_id)
    return service._trial_credit_row(conn, user_id)
