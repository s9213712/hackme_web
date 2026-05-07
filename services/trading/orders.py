"""Trading order placement, execution, matching, and cancellation helpers."""

import json
import uuid
from decimal import Decimal, ROUND_HALF_UP

from services.server_mode.routing import resolve_table
from services.trading._clock import now_text as _now_text
from services.trading.accounting.core import (
    fee_points,
    notional_points,
    quantity_to_units,
    units_to_quantity,
)
from services.trading.validators import _to_decimal, _to_int


OPEN_ORDER_STATUSES = {"open", "partially_filled"}


def _json_dumps(value):
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def place_order(
    service,
    *,
    actor,
    market_symbol,
    side,
    order_type,
    quantity,
    limit_price_points=None,
    emergency_close=False,
    is_grid_order=False,
    ctx=None,
):
    ctx = service._resolve_trading_ctx(ctx, action="place_order")
    user_id = service._actor_id(actor)
    if not user_id:
        raise ValueError("login required")
    side = str(side or "").lower()
    order_type = str(order_type or "").lower()
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if order_type not in {"market", "limit"}:
        raise ValueError("order_type must be market or limit")
    emergency_close = bool(emergency_close)
    is_grid_order = bool(is_grid_order)
    if emergency_close and (side != "sell" or order_type != "market"):
        raise ValueError("emergency close only supports market sell")
    quantity_units = quantity_to_units(quantity)
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        service._assert_writable(conn)
        market = service._market(conn, market_symbol)
        service._assert_market_boot_ready(market, usage="spot order")
        service._validate_market_quantity_constraints(market, quantity_units)
        if int(market["futures_enabled"] or 0):
            raise ValueError("futures interface is reserved but not enabled in v1")
        if int(market["pvp_matching_enabled"] or 0):
            raise ValueError("pvp matching interface is reserved but not enabled in v1")
        current_price, price_source, price_meta = service._current_market_price_points(
            conn, market, with_meta=True, high_risk=(order_type == "market")
        )
        if order_type == "limit":
            limit_price = service._validate_market_limit_price(market, limit_price_points)
        else:
            limit_price = None
        check_price = float(
            _to_decimal(limit_price or current_price, name="check_price", minimum=0.00000001)
        )
        estimated_notional = notional_points(quantity_units, check_price)
        base_fee_rate = float(market["fee_rate_percent"] or 0)
        settings = service._settings_payload(conn)
        if emergency_close:
            effective_fee_rate_percent = base_fee_rate * 2
        elif is_grid_order:
            effective_fee_rate_percent = service._grid_fee_rate_percent(base_fee_rate, settings)
        else:
            effective_fee_rate_percent = base_fee_rate
        fee = fee_points(estimated_notional, effective_fee_rate_percent)
        total_points = estimated_notional + fee
        if estimated_notional < int(market["min_order_points"]):
            raise ValueError("order notional is below market minimum")
        if estimated_notional > int(market["max_order_points"]):
            raise ValueError("order notional exceeds market maximum")
        if side == "sell" and estimated_notional - fee <= 0:
            raise ValueError("sell notional after fee must be positive")

        executable, execution_price = service._is_executable(
            market,
            side=side,
            order_type=order_type,
            limit_price=limit_price,
            current_price=current_price,
        )
        if executable:
            service._assert_price_meta_allows_high_risk_use(
                conn,
                actor=actor,
                market_symbol=market["symbol"],
                usage="market order" if order_type == "market" else "immediately executable limit order",
                price_meta=price_meta,
            )
        now = _now_text()
        order_uuid = str(uuid.uuid4())
        funding_mode = "root_simulated" if service._is_root_actor(actor) else "points_chain"
        trial_frozen = 0
        chain_frozen = 0
        if side == "buy" and funding_mode == "root_simulated":
            account = service._root_sim_account(conn, user_id)
            root_available = int(account["balance_points"] or 0)
            if total_points > root_available:
                raise ValueError(
                    f"root 模擬交易資金不足：需要 {total_points} 點，目前可用 {root_available} 點"
                )
        elif side == "buy" and funding_mode != "root_simulated":
            trial = service._ensure_trial_credit(conn, user_id)
            trial_available = (
                int(trial["available_points"] or 0)
                if trial and trial["status"] == "active"
                else 0
            )
            wallet_payload = service._wallet_payload(conn, user_id, ctx=ctx)
            wallet_available = int(wallet_payload.get("points_balance") or 0)
            total_available = trial_available + wallet_available
            if total_points > total_available:
                raise ValueError(
                    f"交易資金不足：需要 {total_points} 點，目前可用 {total_available} 點"
                    f"（體驗金 {trial_available} + 真實積分 {wallet_available}）"
                )
            trial_frozen = service._trial_lock_for_buy(conn, user_id, total_points)
            chain_frozen = total_points - trial_frozen
            funding_mode = "trial_mixed" if trial_frozen else "points_chain"
        elif side == "sell" and funding_mode != "root_simulated":
            trial_position = service._trial_position(conn, user_id, market["symbol"])
            if int(trial_position["quantity_units"] or 0) > 0:
                funding_mode = "trial_mixed"
        frozen_points = total_points if side == "buy" else 0
        if emergency_close:
            order_reason = "EMERGENCY_MARKET_CLOSE"
        elif is_grid_order:
            order_reason = "GRID_ORDER"
        else:
            order_reason = ""
        orders_table = resolve_table("orders", ctx)
        positions_table = resolve_table("positions", ctx)
        if orders_table == "test_shadow_orders":
            cur = conn.execute(
                f"""
                INSERT INTO {orders_table} (
                    order_uuid, tester_user_id, user_id, market_symbol, side, order_type, funding_mode, execution_mode,
                    quantity_units, limit_price_points, execution_price_points, status,
                    frozen_points, trial_frozen_points, chain_frozen_points, fee_points,
                    filled_quantity_units, reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'house_counterparty', ?, ?, ?, 'open', ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    order_uuid,
                    service._shadow_actor_user_id(ctx, user_id),
                    user_id,
                    market["symbol"],
                    side,
                    order_type,
                    funding_mode,
                    quantity_units,
                    limit_price,
                    execution_price,
                    frozen_points,
                    trial_frozen,
                    chain_frozen,
                    fee,
                    order_reason,
                    now,
                    now,
                ),
            )
        else:
            cur = conn.execute(
                f"""
                INSERT INTO {orders_table} (
                    order_uuid, user_id, market_symbol, side, order_type, funding_mode, execution_mode,
                    quantity_units, limit_price_points, execution_price_points, status,
                    frozen_points, trial_frozen_points, chain_frozen_points, fee_points,
                    filled_quantity_units, reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'house_counterparty', ?, ?, ?, 'open', ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    order_uuid,
                    user_id,
                    market["symbol"],
                    side,
                    order_type,
                    funding_mode,
                    quantity_units,
                    limit_price,
                    execution_price,
                    frozen_points,
                    trial_frozen,
                    chain_frozen,
                    fee,
                    order_reason,
                    now,
                    now,
                ),
            )
        order_id = cur.lastrowid
        if side == "buy":
            if funding_mode == "root_simulated":
                service._sim_delta(conn, user_id, balance_delta=-total_points, locked_delta=total_points)
            elif chain_frozen > 0:
                service._ledger(
                    conn,
                    user_id=user_id,
                    currency_type="points",
                    direction="freeze",
                    amount=chain_frozen,
                    action_type="trading_freeze",
                    reference_type="trading_order",
                    reference_id=order_uuid,
                    idempotency_key=f"trading:freeze:{order_uuid}",
                    reason="TRADING_FREEZE",
                    public_metadata={
                        "order_id": order_id,
                        "market": market["symbol"],
                        "side": side,
                        "order_type": order_type,
                        "price_source": price_source,
                        "fee_rate_percent": effective_fee_rate_percent,
                        "trial_frozen_points": trial_frozen,
                        "chain_frozen_points": chain_frozen,
                    },
                    actor=actor,
                    ctx=ctx,
                )
        else:
            position = service._position(conn, user_id, market["symbol"], ctx=ctx)
            if int(position["quantity_units"]) < quantity_units:
                raise ValueError("insufficient spot position")
            conn.execute(
                f"""
                UPDATE {positions_table}
                SET quantity_units=quantity_units-?, locked_quantity_units=locked_quantity_units+?, updated_at=?
                WHERE user_id=? AND market_symbol=?
                """,
                (quantity_units, quantity_units, now, user_id, market["symbol"]),
            )

        if executable:
            order = conn.execute(f"SELECT * FROM {orders_table} WHERE id=?", (order_id,)).fetchone()
            fill = execute_order(service, conn, order, market, actor=actor, ctx=ctx)
            order = conn.execute(f"SELECT * FROM {orders_table} WHERE id=?", (order_id,)).fetchone()
            event_type = (
                "TRADING_EMERGENCY_MARKET_CLOSE"
                if emergency_close
                else "TRADING_ORDER_FILLED"
            )
            message = "emergency market close filled" if emergency_close else "spot order filled"
            service._audit_event(
                conn,
                event_type,
                message,
                actor=actor,
                target_user_id=user_id,
                order_id=order_id,
                market_symbol=market["symbol"],
                severity="warning" if emergency_close else "info",
                metadata={
                    "fill_id": fill["id"],
                    "price_source": price_source,
                    "execution_price_points": execution_price,
                    "fee_rate_percent": effective_fee_rate_percent,
                },
            )
            service._notify_trade_filled(conn, fill)
        else:
            order = conn.execute(f"SELECT * FROM {orders_table} WHERE id=?", (order_id,)).fetchone()
            service._matching_orderbook_apply_order(order, ctx=ctx)
            service._audit_event(
                conn,
                "TRADING_ORDER_OPEN",
                "limit order stored as open order",
                actor=actor,
                target_user_id=user_id,
                order_id=order_id,
                market_symbol=market["symbol"],
                metadata={
                    "price_source": price_source,
                    "current_price_points": current_price,
                },
            )
        conn.commit()
        return {"ok": True, "order": service._order_payload(order), "executed": executable}
    except Exception as exc:
        conn.rollback()
        if service._is_insufficient_error(exc):
            service._notify_insufficient_balance(
                user_id=user_id,
                market_symbol=market_symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                error=exc,
            )
        raise
    finally:
        conn.close()


def match_open_limit_orders(service, *, actor=None, market_symbol=None, limit=200, ctx=None):
    ctx = service._resolve_trading_ctx(ctx, action="match_open_limit_orders")
    limit = _to_int(limit or 200, name="limit", minimum=1, maximum=1000)
    actor = actor or {"username": "system", "role": "system"}
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.commit()
        orders_table = resolve_table("orders", ctx)
        routed_market = None
        if market_symbol:
            routed_market = service._normalize_market_symbol_on_conn(conn, market_symbol)
        order_uuids = service._matching_orderbook_order_uuids(
            conn,
            market_symbol=routed_market,
            limit=limit,
            ctx=ctx,
        )
    finally:
        conn.close()

    matched = []
    skipped = 0
    errors = []
    for order_uuid in order_uuids:
        conn = service.get_db()
        try:
            service.ensure_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            service._assert_writable(conn)
            order = conn.execute(
                f"SELECT * FROM {orders_table} WHERE order_uuid=?",
                (order_uuid,),
            ).fetchone()
            if not order or order["status"] not in OPEN_ORDER_STATUSES or order["order_type"] != "limit":
                conn.rollback()
                skipped += 1
                continue
            market = service._market(conn, order["market_symbol"])
            if not service._is_market_boot_ready(market):
                conn.rollback()
                skipped += 1
                continue
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
                usage="limit order match",
                price_meta=price_meta,
            )
            executable, execution_price = service._is_executable(
                market,
                side=order["side"],
                order_type=order["order_type"],
                limit_price=order["limit_price_points"],
                current_price=current_price,
            )
            if not executable:
                conn.rollback()
                skipped += 1
                continue
            conn.execute(
                f"UPDATE {orders_table} SET execution_price_points=?, updated_at=? WHERE id=?",
                (execution_price, _now_text(), order["id"]),
            )
            order = conn.execute(f"SELECT * FROM {orders_table} WHERE id=?", (order["id"],)).fetchone()
            fill = execute_order(service, conn, order, market, actor=actor, ctx=ctx)
            service._audit_event(
                conn,
                "TRADING_LIMIT_ORDER_MATCHED",
                "limit order matched by scheduled matcher",
                actor=actor,
                target_user_id=int(order["user_id"]),
                order_id=order["id"],
                market_symbol=market["symbol"],
                metadata={
                    "fill_id": fill["id"],
                    "price_source": price_source,
                    "execution_price_points": execution_price,
                },
            )
            service._notify_trade_filled(conn, fill)
            conn.commit()
            matched.append(
                {
                    "order_uuid": order["order_uuid"],
                    "fill_uuid": fill["fill_uuid"],
                    "market_symbol": market["symbol"],
                    "side": order["side"],
                    "execution_price_points": execution_price,
                }
            )
        except Exception as exc:
            conn.rollback()
            errors.append({"order_uuid": order_uuid, "error": str(exc)})
        finally:
            conn.close()
    return {
        "ok": not errors,
        "scanned": len(order_uuids),
        "matched": matched,
        "skipped": skipped,
        "errors": errors,
    }


def execute_order(service, conn, order, market, *, actor, ctx=None):
    orders_table, route_ctx = service._resolve_table("orders", ctx, action="execute_order")
    positions_table = resolve_table("positions", route_ctx)
    side = order["side"]
    user_id = int(order["user_id"])
    quantity_units = int(order["quantity_units"])
    price = float(
        _to_decimal(
            order["execution_price_points"] or market["manual_price_points"],
            name="execution_price_points",
            minimum=0.00000001,
        )
    )
    notional = notional_points(quantity_units, price)
    order_reason = str(order["reason"] or "")
    emergency_close = order_reason == "EMERGENCY_MARKET_CLOSE"
    is_grid_order = order_reason == "GRID_ORDER"
    base_fee_rate = float(market["fee_rate_percent"] or 0)
    settings = service._settings_payload(conn)
    if emergency_close:
        effective_fee_rate_percent = base_fee_rate * 2
    elif is_grid_order:
        effective_fee_rate_percent = service._grid_fee_rate_percent(base_fee_rate, settings)
    else:
        effective_fee_rate_percent = base_fee_rate
    fee = fee_points(notional, effective_fee_rate_percent)
    total = notional + fee
    ledger_uuids = []
    funding_mode = order["funding_mode"] if "funding_mode" in order.keys() else "points_chain"
    sell_pnl_data = None
    trial_repaid = 0
    trial_profit = 0
    if side == "buy":
        frozen_amount = int(order["frozen_points"] or total)
        trial_frozen = (
            int(order["trial_frozen_points"] or 0)
            if "trial_frozen_points" in order.keys()
            else 0
        )
        chain_frozen = (
            int(order["chain_frozen_points"] or 0)
            if "chain_frozen_points" in order.keys()
            else (0 if funding_mode == "root_simulated" else frozen_amount)
        )
        if funding_mode == "root_simulated":
            refund = max(0, frozen_amount - total)
            service._sim_delta(conn, user_id, balance_delta=refund, locked_delta=-frozen_amount)
        else:
            trial_used = min(trial_frozen, total)
            trial_refund = max(0, trial_frozen - trial_used)
            if trial_refund:
                service._trial_unlock(conn, user_id, trial_refund)
            if trial_used:
                service._trial_mark_buy_executed(
                    conn,
                    user_id=user_id,
                    market_symbol=market["symbol"],
                    quantity_units=quantity_units,
                    trial_used_points=trial_used,
                    total_points=total,
                )
            chain_spend = max(0, total - trial_used)
            chain_refund = max(0, chain_frozen - chain_spend)
            if chain_frozen > 0:
                ledger_uuids.append(
                    service._ledger(
                        conn,
                        user_id=user_id,
                        currency_type="points",
                        direction="unfreeze",
                        amount=chain_frozen,
                        action_type="trading_unfreeze",
                        reference_type="trading_order",
                        reference_id=order["order_uuid"],
                        idempotency_key=f"trading:unfreeze:settle:{order['order_uuid']}",
                        reason="TRADING_UNFREEZE_SETTLEMENT",
                        public_metadata={
                            "order_id": order["id"],
                            "market": market["symbol"],
                            "side": side,
                            "chain_refund_points": chain_refund,
                        },
                        actor=actor,
                        ctx=route_ctx,
                    )["ledger_uuid"]
                )
            if chain_spend > 0:
                ledger_uuids.append(
                    service._ledger(
                        conn,
                        user_id=user_id,
                        currency_type="points",
                        direction="debit",
                        amount=chain_spend,
                        action_type="trading_spot_buy",
                        reference_type="trading_order",
                        reference_id=order["order_uuid"],
                        idempotency_key=f"trading:spot_buy:{order['order_uuid']}",
                        reason="TRADING_SPOT_BUY",
                        public_metadata={
                            "order_id": order["id"],
                            "market": market["symbol"],
                            "price": price,
                            "quantity": units_to_quantity(quantity_units),
                            "notional": notional,
                            "fee": fee,
                            "trial_used_points": trial_used,
                            "chain_spend_points": chain_spend,
                        },
                        actor=actor,
                        ctx=route_ctx,
                    )["ledger_uuid"]
                )
        position = service._position(conn, user_id, market["symbol"], ctx=route_ctx)
        prev_qty = int(position["quantity_units"])
        prev_cost = _to_decimal(position["avg_cost_points"] or 0, name="avg_cost_points", minimum=0)
        next_qty = prev_qty + quantity_units
        next_avg = (
            float(
                (
                    (
                        (Decimal(prev_qty) * prev_cost)
                        + (Decimal(quantity_units) * Decimal(str(price)))
                    )
                    / Decimal(next_qty)
                ).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
            )
            if next_qty
            else 0
        )
        conn.execute(
            f"""
            UPDATE {positions_table}
            SET quantity_units=?, avg_cost_points=?, updated_at=?
            WHERE user_id=? AND market_symbol=?
            """,
            (next_qty, next_avg, _now_text(), user_id, market["symbol"]),
        )
        reserve_delta = (
            0
            if funding_mode == "root_simulated"
            else min(fee, max(0, total - trial_used if funding_mode != "root_simulated" else fee))
        )
        if funding_mode != "root_simulated" and reserve_delta:
            service._reserve_delta(
                conn,
                delta=reserve_delta,
                event_type="fee_retained",
                reason="TRADING_FEE",
                actor=actor,
                order_id=order["id"],
            )
    else:
        if notional <= 0:
            raise ValueError("sell notional is too small")
        net_credit = notional - fee
        if net_credit <= 0:
            raise ValueError("sell notional is too small after fee")
        if funding_mode == "root_simulated":
            service._sim_delta(conn, user_id, balance_delta=net_credit)
        else:
            trial_allocation = service._trial_allocate_sell(
                conn,
                user_id=user_id,
                market_symbol=market["symbol"],
                quantity_units=quantity_units,
                net_credit_points=net_credit,
            )
            trial_repaid = int(trial_allocation["trial_repaid_points"] or 0)
            trial_profit = int(trial_allocation["trial_profit_points"] or 0)
            wallet_credit = int(trial_allocation["wallet_credit_points"] or 0)
            if wallet_credit > 0:
                ledger_uuids.append(
                    service._ledger(
                        conn,
                        user_id=user_id,
                        currency_type="points",
                        direction="credit",
                        amount=wallet_credit,
                        action_type="trading_spot_sell",
                        reference_type="trading_order",
                        reference_id=order["order_uuid"],
                        idempotency_key=f"trading:spot_sell:{order['order_uuid']}",
                        reason="TRADING_SPOT_SELL",
                        public_metadata={
                            "order_id": order["id"],
                            "market": market["symbol"],
                            "price": price,
                            "quantity": units_to_quantity(quantity_units),
                            "notional": notional,
                            "fee": fee,
                            "trial_repaid_points": trial_repaid,
                            "trial_profit_points": trial_profit,
                        },
                        actor=actor,
                        ctx=route_ctx,
                    )["ledger_uuid"]
                )
            if fee:
                service._reserve_delta(
                    conn,
                    delta=fee,
                    event_type="fee_retained",
                    reason="TRADING_FEE",
                    actor=actor,
                    order_id=order["id"],
                )
        position = service._position(conn, user_id, market["symbol"], ctx=route_ctx)
        if int(position["locked_quantity_units"]) < quantity_units:
            raise ValueError("insufficient locked spot position")
        avg_cost = float(
            _to_decimal(position["avg_cost_points"] or 0, name="avg_cost_points", minimum=0)
        )
        gross_cost = notional_points(quantity_units, avg_cost) if avg_cost else 0
        buy_fee_estimate = fee_points(gross_cost, float(market["fee_rate_percent"] or 0)) if gross_cost else 0
        net_pnl = net_credit - gross_cost - buy_fee_estimate
        sell_pnl_data = {
            "avg_cost_points": avg_cost,
            "gross_cost_points": gross_cost,
            "buy_fee_estimate_points": buy_fee_estimate,
            "net_pnl_points": net_pnl,
        }
        next_total_units = (
            int(position["quantity_units"] or 0)
            + int(position["locked_quantity_units"] or 0)
            - quantity_units
        )
        next_avg_cost = avg_cost if next_total_units > 0 else 0
        conn.execute(
            f"""
            UPDATE {positions_table}
            SET locked_quantity_units=locked_quantity_units-?, avg_cost_points=?, updated_at=?
            WHERE user_id=? AND market_symbol=?
            """,
            (quantity_units, next_avg_cost, _now_text(), user_id, market["symbol"]),
        )
        reserve_delta = 0 if funding_mode == "root_simulated" else fee
    fill_uuid = str(uuid.uuid4())
    cur = conn.execute(
        """
        INSERT INTO trading_fills (
            fill_uuid, order_id, user_id, market_symbol, side, funding_mode, quantity_units,
            price_points, notional_points, fee_points, reserve_delta_points,
            trial_repaid_points, trial_profit_points, points_ledger_uuids_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fill_uuid,
            order["id"],
            user_id,
            market["symbol"],
            side,
            funding_mode,
            quantity_units,
            price,
            notional,
            fee,
            reserve_delta,
            trial_repaid,
            trial_profit,
            _json_dumps(ledger_uuids),
            _now_text(),
        ),
    )
    fill_id = cur.lastrowid
    if funding_mode != "root_simulated":
        service._record_user_trade_volume(
            conn,
            user_id=user_id,
            trade_kind="spot",
            notional_points=notional,
            fee_points=fee,
            occurred_at=_now_text(),
        )
    if sell_pnl_data is not None:
        conn.execute(
            """
            INSERT INTO trading_spot_realized_pnl (
                pnl_uuid, user_id, market_symbol, order_id, fill_id, funding_mode,
                quantity_units, avg_cost_points, sell_price_points, gross_cost_points,
                gross_proceeds_points, buy_fee_estimate_points, sell_fee_points,
                net_pnl_points, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                user_id,
                market["symbol"],
                order["id"],
                fill_id,
                funding_mode,
                quantity_units,
                sell_pnl_data["avg_cost_points"],
                price,
                sell_pnl_data["gross_cost_points"],
                notional,
                sell_pnl_data["buy_fee_estimate_points"],
                fee,
                sell_pnl_data["net_pnl_points"],
                _now_text(),
            ),
        )
    conn.execute(
        f"""
        UPDATE {orders_table}
        SET status='filled', execution_price_points=?, fee_points=?, filled_quantity_units=?, frozen_points=0, updated_at=?
        WHERE id=?
        """,
        (price, fee, quantity_units, _now_text(), order["id"]),
    )
    updated_order = conn.execute(f"SELECT * FROM {orders_table} WHERE id=?", (order["id"],)).fetchone()
    service._matching_orderbook_apply_order(updated_order, ctx=route_ctx)
    return conn.execute("SELECT * FROM trading_fills WHERE id=?", (fill_id,)).fetchone()


def cancel_order(service, *, actor, order_uuid, ctx=None):
    ctx = service._resolve_trading_ctx(ctx, action="cancel_order")
    user_id = service._actor_id(actor)
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        service._assert_writable(conn)
        orders_table = resolve_table("orders", ctx)
        positions_table = resolve_table("positions", ctx)
        order = conn.execute(
            f"SELECT * FROM {orders_table} WHERE order_uuid=?",
            (str(order_uuid or ""),),
        ).fetchone()
        if not order:
            raise ValueError("order not found")
        if int(order["user_id"]) != int(user_id):
            raise ValueError("cannot cancel another user's order")
        if order["status"] not in OPEN_ORDER_STATUSES:
            raise ValueError("order is not open")
        funding_mode = order["funding_mode"] if "funding_mode" in order.keys() else "points_chain"
        if order["side"] == "buy" and int(order["frozen_points"] or 0) > 0:
            trial_frozen = (
                int(order["trial_frozen_points"] or 0)
                if "trial_frozen_points" in order.keys()
                else 0
            )
            chain_frozen = (
                int(order["chain_frozen_points"] or 0)
                if "chain_frozen_points" in order.keys()
                else int(order["frozen_points"] or 0)
            )
            if trial_frozen:
                service._trial_unlock(conn, user_id, trial_frozen)
            if funding_mode == "root_simulated":
                frozen = int(order["frozen_points"] or 0)
                service._sim_delta(conn, user_id, balance_delta=frozen, locked_delta=-frozen)
            elif chain_frozen > 0:
                service._ledger(
                    conn,
                    user_id=user_id,
                    currency_type="points",
                    direction="unfreeze",
                    amount=chain_frozen,
                    action_type="trading_unfreeze",
                    reference_type="trading_order",
                    reference_id=order["order_uuid"],
                    idempotency_key=f"trading:cancel_unfreeze:{order['order_uuid']}",
                    reason="TRADING_ORDER_CANCELLED",
                    public_metadata={
                        "order_id": order["id"],
                        "market": order["market_symbol"],
                        "side": order["side"],
                    },
                    actor=actor,
                    ctx=ctx,
                )
        if order["side"] == "sell":
            conn.execute(
                f"""
                UPDATE {positions_table}
                SET quantity_units=quantity_units+?, locked_quantity_units=locked_quantity_units-?, updated_at=?
                WHERE user_id=? AND market_symbol=?
                """,
                (
                    int(order["quantity_units"] or 0),
                    int(order["quantity_units"] or 0),
                    _now_text(),
                    user_id,
                    order["market_symbol"],
                ),
            )
        conn.execute(
            f"UPDATE {orders_table} SET status='cancelled', frozen_points=0, updated_at=? WHERE id=?",
            (_now_text(), order["id"]),
        )
        service._matching_orderbook_apply_order(
            conn.execute(f"SELECT * FROM {orders_table} WHERE id=?", (order["id"],)).fetchone(),
            ctx=ctx,
        )
        service._audit_event(
            conn,
            "TRADING_ORDER_CANCELLED",
            "order cancelled",
            actor=actor,
            target_user_id=user_id,
            order_id=order["id"],
            market_symbol=order["market_symbol"],
        )
        conn.commit()
        return {"ok": True, "order_uuid": order["order_uuid"], "status": "cancelled"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
