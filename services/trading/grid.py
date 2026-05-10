"""Trading grid feature helpers and orchestration."""

import json
import uuid
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from services.server_mode.routing import resolve_table
from services.trading.accounting.core import fee_points, notional_points, units_to_quantity
from services.trading.constants import (
    ASSET_SCALE,
    DEFAULT_GRID_FEE_DISCOUNT_PERCENT,
    GRID_PREVIEW_YELLOW_NET_SPREAD_PERCENT,
)
from services.trading._clock import now_text as _now_text
from services.trading.validators import _decimal_text, _to_decimal, _to_int, _to_price_float


def _json_loads(value, default=None):
    if not value:
        return default if default is not None else {}
    try:
        return json.loads(value)
    except Exception:
        return default if default is not None else {}


def grid_fee_rate_percent(base_fee_rate_percent, settings):
    discount = float(settings.get("grid_fee_discount_percent") or DEFAULT_GRID_FEE_DISCOUNT_PERCENT)
    discount = max(0.0, min(discount, 100.0))
    return max(0.0, float(base_fee_rate_percent or 0) * ((100.0 - discount) / 100.0))


def grid_levels(lower, upper, count, spacing_mode="arithmetic"):
    count = max(2, int(count))
    lower = _to_decimal(lower, name="lower_price_points", minimum=0.00000001)
    upper = _to_decimal(upper, name="upper_price_points", minimum=0.00000002)
    if count == 2:
        return [float(lower), float(upper)]
    if spacing_mode == "geometric":
        ratio = (float(upper) / float(lower)) ** (1 / (count - 1))
        return [
            float(
                Decimal(str(float(lower) * (ratio ** i))).quantize(
                    Decimal("0.00000001"),
                    rounding=ROUND_HALF_UP,
                )
            )
            for i in range(count)
        ]
    step = (upper - lower) / Decimal(count - 1)
    return [
        float((lower + (step * Decimal(i))).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP))
        for i in range(count)
    ]


def grid_quantity_units(amount_points, price_points):
    amount = int(amount_points or 0)
    price = _to_decimal(price_points, name="price_points", minimum=0)
    if amount <= 0 or price <= 0:
        return 0
    units = (Decimal(amount) * Decimal(ASSET_SCALE) / price).quantize(Decimal("1"), rounding=ROUND_DOWN)
    return int(units)


def grid_preview_fee_rates(market, settings, *, order_mode="maker"):
    mode = str(order_mode or "maker").strip().lower()
    if mode not in {"maker", "taker"}:
        raise ValueError("order_mode must be maker or taker")
    spot_fee_percent = Decimal(str(market["fee_rate_percent"] or 0))
    discount_percent = Decimal(str(settings.get("grid_fee_discount_percent") or DEFAULT_GRID_FEE_DISCOUNT_PERCENT))
    discount_percent = max(Decimal("0"), min(discount_percent, Decimal("100")))
    discounted_grid_fee_percent = spot_fee_percent * (Decimal("100") - discount_percent) / Decimal("100")
    return {
        "order_mode": mode,
        "spot_fee_percent": spot_fee_percent,
        "grid_discount_percent": discount_percent,
        "maker_fee_percent": spot_fee_percent,
        "taker_fee_percent": spot_fee_percent,
        "buy_fee_percent": discounted_grid_fee_percent,
        "sell_fee_percent": discounted_grid_fee_percent,
        "round_trip_fee_percent": discounted_grid_fee_percent * Decimal("2"),
    }


def grid_preview_risk(*, min_net_spread_percent, break_even_spread_percent, spacing_percent):
    net_spread = Decimal(str(min_net_spread_percent or 0))
    break_even = Decimal(str(break_even_spread_percent or 0))
    spacing = Decimal(str(spacing_percent or 0))
    if net_spread <= 0:
        return {
            "status": "red",
            "message": f"扣除手續費後預期虧損：每格間距 {_decimal_text(spacing, places='0.0001')}%，但損益兩平至少需要 {_decimal_text(break_even, places='0.0001')}%",
            "blocked": True,
            "requires_confirmation": False,
        }
    if net_spread < GRID_PREVIEW_YELLOW_NET_SPREAD_PERCENT:
        return {
            "status": "yellow",
            "message": f"利潤過薄：每格扣費後僅剩 {_decimal_text(net_spread, places='0.0001')}%，可能被滑價吃掉",
            "blocked": False,
            "requires_confirmation": True,
        }
    return {
        "status": "green",
        "message": f"手續費後仍有利潤：每格預估淨利 {_decimal_text(net_spread, places='0.0001')}%",
        "blocked": False,
        "requires_confirmation": False,
    }


def grid_preview_summary(*, lower_price_points, upper_price_points, grid_count, order_amount_points, spacing_mode, fee_rates):
    levels = grid_levels(lower_price_points, upper_price_points, grid_count, spacing_mode)
    if len(levels) < 2:
        raise ValueError("grid_count must be at least 2")
    buy_fee_rate = Decimal(str(fee_rates["buy_fee_percent"])) / Decimal("100")
    sell_fee_rate = Decimal(str(fee_rates["sell_fee_percent"])) / Decimal("100")
    if sell_fee_rate >= Decimal("1"):
        raise ValueError("sell_fee_percent out of range")

    pair_summaries = []
    total_gross = Decimal("0")
    total_fee = Decimal("0")
    total_net = Decimal("0")
    break_even_spread_percent = ((Decimal("1") + buy_fee_rate) / (Decimal("1") - sell_fee_rate) - Decimal("1")) * Decimal("100")
    blocked_reason = ""

    for level_index in range(len(levels) - 1):
        buy_price = Decimal(str(levels[level_index]))
        sell_price = Decimal(str(levels[level_index + 1]))
        quantity_units = grid_quantity_units(order_amount_points, buy_price)
        if quantity_units <= 0:
            blocked_reason = "每格金額不足以買入最小單位，請提高每格金額或降低價格區間"
            break
        quantity = Decimal(quantity_units) / Decimal(ASSET_SCALE)
        gross_profit = (sell_price - buy_price) * quantity
        buy_notional = buy_price * quantity
        sell_notional = sell_price * quantity
        buy_fee = buy_notional * buy_fee_rate
        sell_fee = sell_notional * sell_fee_rate
        fees = buy_fee + sell_fee
        net_profit = gross_profit - fees
        spacing_percent = ((sell_price - buy_price) / buy_price) * Decimal("100")
        net_spread_percent = (net_profit / buy_notional) * Decimal("100") if buy_notional > 0 else Decimal("0")
        pair_summary = {
            "level_index": level_index,
            "buy_price_points": float(buy_price),
            "sell_price_points": float(sell_price),
            "quantity_units": quantity_units,
            "quantity": quantity,
            "grid_spacing_points": sell_price - buy_price,
            "grid_spacing_percent": spacing_percent,
            "gross_profit_points": gross_profit,
            "buy_fee_points": buy_fee,
            "sell_fee_points": sell_fee,
            "fee_points": fees,
            "net_profit_points": net_profit,
            "net_spread_percent": net_spread_percent,
        }
        pair_summaries.append(pair_summary)
        total_gross += gross_profit
        total_fee += fees
        total_net += net_profit

    if blocked_reason:
        risk = {
            "status": "red",
            "message": blocked_reason,
            "blocked": True,
            "requires_confirmation": False,
        }
        return {
            "grid_levels": levels,
            "pair_summaries": [],
            "break_even_spread_percent": break_even_spread_percent,
            "risk": risk,
            "pair_count": len(levels) - 1,
            "estimated_total_gross_profit_points": Decimal("0"),
            "estimated_total_fee_points": Decimal("0"),
            "estimated_total_net_profit_points": Decimal("0"),
            "worst_pair": None,
        }

    worst_pair = min(
        pair_summaries,
        key=lambda item: (item["net_spread_percent"], item["grid_spacing_percent"], item["level_index"]),
    )
    risk = grid_preview_risk(
        min_net_spread_percent=worst_pair["net_spread_percent"],
        break_even_spread_percent=break_even_spread_percent,
        spacing_percent=worst_pair["grid_spacing_percent"],
    )
    return {
        "grid_levels": levels,
        "pair_summaries": pair_summaries,
        "break_even_spread_percent": break_even_spread_percent,
        "risk": risk,
        "pair_count": len(pair_summaries),
        "estimated_total_gross_profit_points": total_gross,
        "estimated_total_fee_points": total_fee,
        "estimated_total_net_profit_points": total_net,
        "worst_pair": worst_pair,
    }


def grid_bot_payload(row, *, json_loads, orders=None):
    item = dict(row)
    item["enabled"] = bool(item["enabled"])
    item["grid_levels"] = json_loads(item.get("grid_levels_json"), [])
    item["orders"] = orders or []
    return item


def preview_grid_bot(service, *, actor, payload):
    user_id = service._actor_id(actor)
    if not user_id:
        raise ValueError("login required")
    source = payload or {}
    market_symbol = str(source.get("market_symbol") or "").strip().upper()
    upper_price = _to_price_float(source.get("upper_price_points", source.get("upper_price")), name="upper_price_points", minimum=0.00000001)
    lower_price = _to_price_float(source.get("lower_price_points", source.get("lower_price")), name="lower_price_points", minimum=0.00000001)
    if upper_price <= lower_price:
        raise ValueError("upper_price_points must be greater than lower_price_points")
    grid_count = _to_int(source.get("grid_count", 10), name="grid_count", minimum=2, maximum=200)
    order_amount_decimal = _to_decimal(source.get("order_amount_points", source.get("investment_amount")), name="order_amount_points", minimum=1, maximum=10**12)
    if order_amount_decimal != order_amount_decimal.to_integral_value():
        raise ValueError("order_amount_points must be an integer")
    order_amount_points = int(order_amount_decimal)
    spacing_mode = str(source.get("spacing_mode") or "arithmetic").strip().lower()
    if spacing_mode not in ("arithmetic", "geometric"):
        spacing_mode = "arithmetic"
    order_mode = str(source.get("order_mode") or "maker").strip().lower()
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        market = service._market(conn, market_symbol)
        settings = service._settings_payload(conn)
    finally:
        conn.close()
    fee_rates = service._grid_preview_fee_rates(market, settings, order_mode=order_mode)
    summary = service._grid_preview_summary(
        lower_price_points=lower_price,
        upper_price_points=upper_price,
        grid_count=grid_count,
        order_amount_points=order_amount_points,
        spacing_mode=spacing_mode,
        fee_rates=fee_rates,
    )
    worst_pair = summary["worst_pair"] or {}
    return {
        "ok": True,
        "market_symbol": market_symbol,
        "spacing_mode": spacing_mode,
        "order_mode": order_mode,
        "levels": summary["grid_levels"],
        "pair_count": summary["pair_count"],
        "fee_model": {
            "spot_fee_percent": _decimal_text(fee_rates["spot_fee_percent"], places="0.0001"),
            "grid_discount_percent": _decimal_text(fee_rates["grid_discount_percent"], places="0.0001"),
            "maker_fee_percent": _decimal_text(fee_rates["maker_fee_percent"], places="0.0001"),
            "taker_fee_percent": _decimal_text(fee_rates["taker_fee_percent"], places="0.0001"),
            "buy_fee_percent": _decimal_text(fee_rates["buy_fee_percent"], places="0.0001"),
            "sell_fee_percent": _decimal_text(fee_rates["sell_fee_percent"], places="0.0001"),
            "round_trip_fee_percent": _decimal_text(fee_rates["round_trip_fee_percent"], places="0.0001"),
        },
        "break_even": {
            "min_spread_percent": _decimal_text(summary["break_even_spread_percent"], places="0.0001"),
        },
        "grid_profit": {
            "grid_spacing_percent": _decimal_text(worst_pair.get("grid_spacing_percent", 0), places="0.0001"),
            "grid_spacing_points": _decimal_text(worst_pair.get("grid_spacing_points", 0), places="0.0001"),
            "estimated_net_spread_percent": _decimal_text(worst_pair.get("net_spread_percent", 0), places="0.0001"),
            "estimated_gross_profit_per_grid": _decimal_text(worst_pair.get("gross_profit_points", 0)),
            "estimated_fee_per_grid": _decimal_text(worst_pair.get("fee_points", 0)),
            "estimated_net_profit_per_grid": _decimal_text(worst_pair.get("net_profit_points", 0)),
            "estimated_total_gross_profit": _decimal_text(summary["estimated_total_gross_profit_points"]),
            "estimated_total_fee": _decimal_text(summary["estimated_total_fee_points"]),
            "estimated_total_net_profit": _decimal_text(summary["estimated_total_net_profit_points"]),
            "reference_buy_price_points": _decimal_text(worst_pair.get("buy_price_points", 0), places="0.0001"),
            "reference_sell_price_points": _decimal_text(worst_pair.get("sell_price_points", 0), places="0.0001"),
            "reference_quantity": _decimal_text(worst_pair.get("quantity", 0)),
        },
        "risk": summary["risk"],
    }


def create_grid_bot(service, *, actor, payload):
    user_id = service._actor_id(actor)
    if not user_id:
        raise ValueError("login required")
    payload = payload or {}
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("grid bot name is required")
    if len(name) > 80:
        raise ValueError("grid bot name too long")
    market_symbol = str(payload.get("market_symbol") or "").strip().upper()
    upper_price = _to_price_float(payload.get("upper_price_points"), name="upper_price_points", minimum=0.00000001)
    lower_price = _to_price_float(payload.get("lower_price_points"), name="lower_price_points", minimum=0.00000001)
    if upper_price <= lower_price:
        raise ValueError("upper_price_points must be greater than lower_price_points")
    grid_count = _to_int(payload.get("grid_count", 10), name="grid_count", minimum=2, maximum=200)
    order_amount = _to_int(payload.get("order_amount_points"), name="order_amount_points", minimum=1)
    spacing_mode = str(payload.get("spacing_mode") or "arithmetic").strip()
    if spacing_mode not in ("arithmetic", "geometric"):
        spacing_mode = "arithmetic"
    preview = preview_grid_bot(
        service,
        actor=actor,
        payload={
            "market_symbol": market_symbol,
            "upper_price_points": upper_price,
            "lower_price_points": lower_price,
            "grid_count": grid_count,
            "order_amount_points": order_amount,
            "spacing_mode": spacing_mode,
            "order_mode": "maker",
        },
    )
    risk = preview.get("risk") or {}
    if risk.get("blocked"):
        raise ValueError(risk.get("message") or "grid preview blocked")
    if risk.get("requires_confirmation") and not bool(payload.get("confirm_thin_profit")):
        raise ValueError(risk.get("message") or "grid profit is too thin; confirmation required")

    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        market = service._market(conn, market_symbol)
        if not int(market.get("allow_bots") or 0):
            raise ValueError("bots are disabled for this market")
        service._assert_market_boot_ready(market, usage="grid bot create", conn=conn)
        current_price, _price_source, price_meta = service._current_market_price_points(
            conn,
            market,
            with_meta=True,
            high_risk=True,
        )
        service._assert_price_meta_allows_high_risk_use(
            conn,
            actor=actor,
            market_symbol=market["symbol"],
            usage="grid bot create",
            price_meta=price_meta,
        )
    finally:
        conn.close()

    grid_level_values = service._grid_levels(lower_price, upper_price, grid_count, spacing_mode)
    now = _now_text()
    bot_uuid = str(uuid.uuid4())
    conn = service.get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO trading_grid_bots
              (bot_uuid, user_id, name, market_symbol, upper_price_points, lower_price_points,
               grid_count, order_amount_points, enabled, initial_price_points, grid_levels_json,
               enabled_at, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,1,?,?,?,?,?)
            """,
            (bot_uuid, user_id, name, market_symbol, upper_price, lower_price,
             grid_count, order_amount, current_price,
             json.dumps(grid_level_values), now, now, now),
        )
        grid_bot_id = conn.execute(
            "SELECT id FROM trading_grid_bots WHERE bot_uuid=?", (bot_uuid,)
        ).fetchone()["id"]
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    else:
        conn.close()

    bot_actor = {"id": int(user_id), "username": service._actor_username(actor), "role": service._actor_role(actor)}
    placed = []
    errors = []
    for index, level_price in enumerate(grid_level_values):
        if level_price < current_price:
            side = "buy"
        elif level_price > current_price:
            side = "sell"
        else:
            continue
        qty_units = service._grid_quantity_units(order_amount, level_price)
        if qty_units <= 0:
            errors.append(f"level {index} price {level_price}: 金額不足以買入最小單位")
            continue
        qty_text = units_to_quantity(qty_units)
        try:
            order_result = service.place_order(
                actor=bot_actor,
                market_symbol=market_symbol,
                side=side,
                order_type="limit",
                quantity=qty_text,
                limit_price_points=level_price,
                is_grid_order=True,
            )
            trading_order_uuid = (order_result.get("order") or {}).get("order_uuid")
            placed.append({"level_index": index, "price_points": level_price, "side": side, "trading_order_uuid": trading_order_uuid, "qty_units": qty_units})
        except Exception as exc:
            errors.append(f"level {index} price {level_price}: {exc}")

    if placed:
        conn = service.get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            for placed_order in placed:
                conn.execute(
                    """
                    INSERT INTO trading_grid_orders
                      (order_uuid, grid_bot_id, user_id, level_index, price_points, side,
                       trading_order_uuid, status, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,'open',?,?)
                    """,
                    (str(uuid.uuid4()), grid_bot_id, user_id,
                     placed_order["level_index"], placed_order["price_points"], placed_order["side"],
                     placed_order["trading_order_uuid"], now, now),
                )
            service._audit_event(conn, "GRID_BOT_CREATED", "grid trading bot created", actor=actor, target_user_id=user_id, market_symbol=market_symbol, metadata={"bot_uuid": bot_uuid, "grid_count": grid_count, "placed": len(placed)})
            conn.commit()
        except Exception:
            conn.rollback()
            conn.close()
            raise
        else:
            conn.close()

    conn = service.get_db()
    try:
        bot_row = conn.execute("SELECT * FROM trading_grid_bots WHERE bot_uuid=?", (bot_uuid,)).fetchone()
        orders = conn.execute(
            "SELECT * FROM trading_grid_orders WHERE grid_bot_id=? ORDER BY level_index ASC",
            (grid_bot_id,),
        ).fetchall()
        return {"ok": True, "bot": service._grid_bot_payload(bot_row, [dict(o) for o in orders]), "placed": placed, "errors": errors, "current_price_points": current_price}
    finally:
        conn.close()


def list_grid_bots(service, *, actor):
    user_id = service._actor_id(actor)
    if not user_id:
        raise ValueError("login required")
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        bots = []
        for row in conn.execute("SELECT * FROM trading_grid_bots WHERE user_id=? ORDER BY id DESC LIMIT 50", (user_id,)).fetchall():
            orders = conn.execute(
                "SELECT * FROM trading_grid_orders WHERE grid_bot_id=? ORDER BY level_index ASC, id ASC",
                (row["id"],),
            ).fetchall()
            bots.append(service._grid_bot_payload(row, [dict(o) for o in orders]))
        return {"ok": True, "bots": bots}
    finally:
        conn.close()


def toggle_grid_bot(service, *, actor, bot_uuid, enabled):
    user_id = service._actor_id(actor)
    if not user_id:
        raise ValueError("login required")
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM trading_grid_bots WHERE bot_uuid=? AND user_id=?", (str(bot_uuid or ""), user_id)).fetchone()
        if not row:
            raise ValueError("grid bot not found")
        now = _now_text()
        conn.execute(
            "UPDATE trading_grid_bots SET enabled=?, enabled_at=?, updated_at=? WHERE id=?",
            (1 if enabled else 0, now if enabled and not bool(row["enabled"]) else (row["enabled_at"] if enabled else None), now, row["id"]),
        )
        conn.commit()
        return {"ok": True, "bot_uuid": bot_uuid, "enabled": bool(enabled)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_grid_bot(service, *, actor, bot_uuid):
    user_id = service._actor_id(actor)
    if not user_id:
        raise ValueError("login required")
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        row = conn.execute("SELECT * FROM trading_grid_bots WHERE bot_uuid=? AND user_id=?", (str(bot_uuid or ""), user_id)).fetchone()
        if not row:
            raise ValueError("grid bot not found")
        open_order_uuids = [
            go["trading_order_uuid"]
            for go in conn.execute(
                "SELECT trading_order_uuid FROM trading_grid_orders WHERE grid_bot_id=? AND status='open'",
                (row["id"],),
            ).fetchall()
            if go["trading_order_uuid"]
        ]
        bot_id = row["id"]
    finally:
        conn.close()
    bot_actor = {"id": int(user_id), "username": service._actor_username(actor), "role": service._actor_role(actor)}
    for order_uuid in open_order_uuids:
        try:
            service.cancel_order(actor=bot_actor, order_uuid=order_uuid)
        except Exception:
            pass
    conn = service.get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM trading_grid_bots WHERE id=?", (bot_id,))
        conn.commit()
        return {"ok": True, "bot_uuid": bot_uuid}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def scan_grid_bots(service, *, actor):
    user_id = service._actor_id(actor)
    if not user_id:
        raise ValueError("login required")
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        bots = conn.execute(
            "SELECT * FROM trading_grid_bots WHERE user_id=? AND enabled=1 ORDER BY id ASC",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()
    results = []
    for bot in bots:
        try:
            results.append(scan_one_grid_bot(service, bot, actor=actor))
        except Exception as exc:
            conn2 = service.get_db()
            try:
                conn2.execute("UPDATE trading_grid_bots SET last_error=?, updated_at=? WHERE id=?", (str(exc)[:500], _now_text(), bot["id"]))
                conn2.commit()
            except Exception:
                pass
            finally:
                conn2.close()
            results.append({"bot_uuid": bot["bot_uuid"], "error": str(exc)})
    return {"ok": True, "scanned": len(bots), "results": results}


def scan_one_grid_bot(service, bot, *, actor):
    user_id = int(bot["user_id"])
    bot_id = int(bot["id"])
    bot_actor = {"id": user_id, "username": service._actor_username(actor), "role": service._actor_role(actor)}
    now = _now_text()
    route_ctx = service._resolve_trading_ctx(action="grid_bot_scan")
    orders_table = resolve_table("orders", route_ctx)
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        market = service._market(conn, bot["market_symbol"])
        try:
            service._assert_market_boot_ready(market, usage="grid bot scan", conn=conn)
            current_price, _price_source, price_meta = service._current_market_price_points(
                conn,
                market,
                with_meta=True,
                high_risk=True,
            )
            service._assert_price_meta_allows_high_risk_use(
                conn,
                actor=actor,
                market_symbol=market["symbol"],
                usage="grid bot scan",
                price_meta=price_meta,
            )
        except ValueError as exc:
            blocked_reason = str(exc)
            conn.execute(
                "UPDATE trading_grid_bots SET last_error=?, updated_at=? WHERE id=?",
                (blocked_reason[:500], now, bot_id),
            )
            service._audit_event(
                conn,
                "GRID_BOT_SCAN_BLOCKED",
                "grid bot scan paused because no risk-grade execution price is available",
                actor=actor,
                target_user_id=user_id,
                market_symbol=market["symbol"],
                severity="warning",
                metadata={
                    "bot_uuid": bot["bot_uuid"],
                    "grid_scan_blocked_reason": blocked_reason,
                },
            )
            conn.commit()
            return {
                "bot_uuid": bot["bot_uuid"],
                "blocked": True,
                "grid_scan_blocked_reason": blocked_reason,
                "fills_processed": [],
                "counter_orders_placed": [],
            }
        price_window = service._recent_price_window(
            market["symbol"],
            lookback_seconds=65,
            since_time_text=bot["last_scan_at"] if "last_scan_at" in bot.keys() else None,
            conn=conn,
        )
        window_low = float((price_window or {}).get("low_points") or current_price)
        window_high = float((price_window or {}).get("high_points") or current_price)
        grid_level_values = _json_loads(bot["grid_levels_json"], [])
        if not grid_level_values:
            grid_level_values = service._grid_levels(bot["lower_price_points"], bot["upper_price_points"], bot["grid_count"])
        open_grid_orders = conn.execute(
            "SELECT * FROM trading_grid_orders WHERE grid_bot_id=? AND status='open' ORDER BY level_index ASC",
            (bot_id,),
        ).fetchall()
        fills_processed = []
        counter_orders_placed = []
        profit_delta = 0
        trades_delta = 0
        for go in open_grid_orders:
            if not go["trading_order_uuid"]:
                continue
            t_order = conn.execute(
                f"SELECT * FROM {orders_table} WHERE order_uuid=?",
                (go["trading_order_uuid"],),
            ).fetchone()
            if not t_order:
                continue
            if t_order["status"] in ("filled", "partially_filled"):
                filled_units = int(t_order["filled_quantity_units"] or 0)
            else:
                executable, _ = service._is_executable(
                    market,
                    side=t_order["side"],
                    order_type=t_order["order_type"],
                    limit_price=t_order["limit_price_points"],
                    current_price=current_price,
                )
                if not executable and t_order["order_type"] == "limit":
                    limit_price = float(_to_decimal(t_order["limit_price_points"] or 0, name="limit_price_points", minimum=0))
                    if t_order["side"] == "buy" and limit_price > 0 and window_low <= limit_price:
                        executable = True
                    elif t_order["side"] == "sell" and limit_price > 0 and window_high >= limit_price:
                        executable = True
                if not executable:
                    continue
                execution_price = float(t_order["limit_price_points"] or go["price_points"] or current_price)
                conn.execute(
                    f"UPDATE {orders_table} SET execution_price_points=?, updated_at=? WHERE id=?",
                    (execution_price, now, t_order["id"]),
                )
                t_order = conn.execute(f"SELECT * FROM {orders_table} WHERE id=?", (t_order["id"],)).fetchone()
                fill = service._execute_order(conn, t_order, market, actor=actor, ctx=route_ctx)
                filled_units = int(fill["quantity_units"] or 0)
                service._audit_event(
                    conn,
                    "GRID_ORDER_FILLED",
                    "grid order filled by CFD price crossing",
                    actor=actor,
                    target_user_id=user_id,
                    order_id=t_order["id"],
                    market_symbol=market["symbol"],
                    metadata={
                        "bot_uuid": bot["bot_uuid"],
                        "grid_order_uuid": go["order_uuid"],
                        "fill_id": fill["id"],
                        "level_index": int(go["level_index"]),
                        "side": go["side"],
                        "trigger_price_points": current_price,
                        "execution_price_points": execution_price,
                    },
                )
                service._notify_trade_filled(conn, fill)
                conn.commit()
            filled_units = int(filled_units or 0)
            if filled_units <= 0:
                continue
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE trading_grid_orders SET status='filled', filled_quantity_units=?, updated_at=? WHERE id=?",
                (filled_units, now, go["id"]),
            )
            conn.commit()
            fills_processed.append({"level_index": go["level_index"], "side": go["side"], "price_points": go["price_points"]})
            level_idx = int(go["level_index"])
            side = str(go["side"])
            filled_price = float(_to_decimal(go["price_points"] or 0, name="grid_price_points", minimum=0))
            if side == "buy":
                counter_level_idx = level_idx + 1
                counter_side = "sell"
            else:
                counter_level_idx = level_idx - 1
                counter_side = "buy"
                buy_price = grid_level_values[level_idx - 1] if level_idx > 0 else filled_price
                settings = service._settings_payload(conn)
                grid_fee_rate = service._grid_fee_rate_percent(float(market["fee_rate_percent"] or 0), settings)
                buy_notional = notional_points(filled_units, buy_price)
                sell_notional = notional_points(filled_units, filled_price)
                gross_profit = sell_notional - buy_notional
                total_fee = fee_points(buy_notional, grid_fee_rate) + fee_points(sell_notional, grid_fee_rate)
                profit_delta += gross_profit - total_fee
                trades_delta += 1
            if 0 <= counter_level_idx < len(grid_level_values):
                counter_price = int(grid_level_values[counter_level_idx])
                existing = conn.execute(
                    "SELECT id FROM trading_grid_orders WHERE grid_bot_id=? AND level_index=? AND status='open'",
                    (bot_id, counter_level_idx),
                ).fetchone()
                if not existing:
                    qty_units = filled_units if counter_side == "sell" else service._grid_quantity_units(int(bot["order_amount_points"]), counter_price)
                    if qty_units > 0:
                        qty_text = units_to_quantity(qty_units)
                        try:
                            order_result = service.place_order(
                                actor=bot_actor,
                                market_symbol=bot["market_symbol"],
                                side=counter_side,
                                order_type="limit",
                                quantity=qty_text,
                                limit_price_points=counter_price,
                                is_grid_order=True,
                            )
                            t_order_uuid = (order_result.get("order") or {}).get("order_uuid")
                            conn.execute("BEGIN IMMEDIATE")
                            conn.execute(
                                """
                                INSERT INTO trading_grid_orders
                                  (order_uuid, grid_bot_id, user_id, level_index, price_points, side,
                                   trading_order_uuid, status, created_at, updated_at)
                                VALUES (?,?,?,?,?,?,?,'open',?,?)
                                """,
                                (str(uuid.uuid4()), bot_id, user_id, counter_level_idx, counter_price, counter_side, t_order_uuid, now, now),
                            )
                            conn.commit()
                            counter_orders_placed.append({"level_index": counter_level_idx, "side": counter_side, "price_points": counter_price})
                        except Exception:
                            conn.rollback()
                            pass
        if profit_delta or trades_delta:
            conn.execute(
                "UPDATE trading_grid_bots SET total_profit_points=total_profit_points+?, total_trades=total_trades+?, last_scan_at=?, last_error=NULL, updated_at=? WHERE id=?",
                (profit_delta, trades_delta, now, now, bot_id),
            )
            conn.commit()
        else:
            conn.execute("UPDATE trading_grid_bots SET last_scan_at=?, updated_at=? WHERE id=?", (now, now, bot_id))
            conn.commit()
        return {
            "bot_uuid": bot["bot_uuid"],
            "current_price_points": current_price,
            "scan_window_low_points": window_low,
            "scan_window_high_points": window_high,
            "fills_processed": fills_processed,
            "counter_orders_placed": counter_orders_placed,
            "profit_delta": profit_delta,
        }
    finally:
        conn.close()
