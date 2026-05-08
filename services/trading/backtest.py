"""Trading backtest helpers.

This module keeps the deterministic candle/range/replay helpers plus the
single-process backtest orchestration used by
``TradingEngineService.backtest_trading_bot``.
"""

import math
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from services.trading.accounting.core import fee_points, notional_points, units_to_quantity
from services.trading.constants import ASSET_SCALE
from services.trading.validators import _to_decimal, _to_int, _to_price_float


def filter_backtest_candles_by_range(candles, *, start_time="", end_time=""):
    if not start_time and not end_time:
        return list(candles or [])
    filtered = []
    for candle in candles or []:
        stamp = str(candle.get("time_iso") or candle.get("time") or "")
        if start_time and stamp < start_time:
            continue
        if end_time and stamp > end_time:
            continue
        filtered.append(candle)
    return filtered


def build_backtest_initial_state(
    *,
    cash,
    initial_units=0,
    initial_avg_cost=0,
    initial_trade_count=0,
    initial_candle_offset=0,
    initial_workflow_state=None,
    grid_fee_rate=0.0,
):
    workflow_state = initial_workflow_state or {}
    return {
        "cash": int(cash),
        "units": int(initial_units or 0),
        "avg_cost_bt": float(initial_avg_cost or 0),
        "trades": [],
        "equity_curve": [],
        "peak_value": int(cash),
        "max_drawdown_percent": 0.0,
        "wins": 0,
        "sells": 0,
        "trade_count": int(initial_trade_count or 0),
        "processed_candles": int(initial_candle_offset or 0),
        "workflow_state": {
            "executed_action_ids": set(workflow_state.get("executed_action_ids") or []),
            "branch_step_counts": {
                str(key): int(value)
                for key, value in (workflow_state.get("branch_step_counts") or {}).items()
            },
        },
        "grid_initialized": False,
        "grid_state": {},
        "grid_levels": [],
        "grid_order_amount": 0,
        "grid_fee_rate": float(grid_fee_rate or 0),
        "last_valid_price": None,
        "recent_valid_prices": [],
        "outlier_skipped_count": 0,
    }


def backtest_equity_value(*, cash, units, price):
    return int(cash or 0) + notional_points(units, price)


def update_backtest_drawdown(*, peak_value, max_drawdown_percent, equity):
    next_peak = max(int(peak_value or 0), int(equity or 0))
    next_drawdown = float(max_drawdown_percent or 0.0)
    if next_peak > 0:
        next_drawdown = max(
            next_drawdown,
            round((next_peak - equity) * 100 / next_peak, 4),
        )
    return next_peak, next_drawdown


def build_backtest_equity_point(*, global_index, candle, price, equity):
    return {
        "index": global_index,
        "time": candle.get("time") or candle.get("time_iso") or global_index,
        "equity_points": equity,
        "price_points": price,
    }


def backtest_anchor_price(*, recent_valid_prices=None, last_valid_price=None):
    anchor_prices = [float(value) for value in (recent_valid_prices or []) if float(value or 0) > 0]
    if anchor_prices:
        sorted_anchor = sorted(anchor_prices)
        return float(sorted_anchor[len(sorted_anchor) // 2])
    return float(last_valid_price or 0)


def build_backtest_outlier_warning(*, global_index, candle, price, anchor_price, max_price_jump_percent):
    jump_percent = abs(price - anchor_price) * 100.0 / anchor_price
    candle_time = candle.get("time_iso") or candle.get("time") or global_index
    return (
        f"已略過跳價 {jump_percent:.2f}% 的 K 線（時間 {candle_time}，價格 {price}，"
        f"參考價 {anchor_price}，上限 {max_price_jump_percent:.2f}%）"
    )


def push_recent_valid_price(recent_valid_prices, price, *, limit=5):
    return list((recent_valid_prices or []) + [price])[-limit:]


def backtest_segment_count(candle_count, segment_size):
    return max(1, math.ceil(int(candle_count or 0) / int(segment_size or 1)))


def iter_backtest_segments(candles, segment_size):
    segment_size = int(segment_size or 1)
    for start in range(0, len(candles or []), segment_size):
        chunk = candles[start:start + segment_size]
        if chunk:
            yield chunk


def build_backtest_range_warnings(
    *,
    existing_warnings=None,
    start_time="",
    end_time="",
    all_candles_raw=None,
    candle_count=0,
    max_backtest_candles=0,
    segment_count=1,
    max_backtest_candles_per_batch=0,
    outlier_skipped_count=0,
    max_price_jump_percent=0.0,
):
    warnings = list(existing_warnings or [])
    raw_candles = all_candles_raw or []
    if start_time and raw_candles:
        first_raw = str(raw_candles[0].get("time_iso") or raw_candles[0].get("time") or "")
        if first_raw and start_time < first_raw:
            warnings.append(f"請求起始時間 {start_time} 早於資料最早 K 線 {first_raw}，實際回測從 {first_raw} 開始")
    if end_time and raw_candles:
        last_raw = str(raw_candles[-1].get("time_iso") or raw_candles[-1].get("time") or "")
        if last_raw and end_time > last_raw:
            warnings.append(f"請求結束時間 {end_time} 晚於資料最新 K 線 {last_raw}，實際回測至 {last_raw}")
    if len(raw_candles) >= max_backtest_candles:
        warnings.append(f"K 線數量達到上限 {max_backtest_candles} 根，更早的歷史資料可能未被包含")
    if segment_count > 1:
        warnings.append(
            f"回測資料共 {candle_count} 根 K 線，後端已自動分成 {segment_count} 批連續執行（每批最多 {max_backtest_candles_per_batch} 根）"
        )
    if outlier_skipped_count > 5:
        warnings.append(
            f"另有 {outlier_skipped_count - 5} 根跳價 K 線超過 {max_price_jump_percent:.2f}% 已被略過"
        )
    return warnings


def build_backtest_result_payload(
    *,
    state,
    candles,
    strategy,
    market_symbol,
    initial_cash,
    start_time="",
    end_time="",
    range_warnings=None,
    max_backtest_candles=0,
    max_backtest_candles_per_batch=0,
    requested_candle_limit=0,
    data_source="",
    provider_symbol="",
    max_price_jump_percent=0.0,
    segment_count=1,
):
    last_price = float(state.get("last_valid_price") or 0)
    position_value = notional_points(state.get("units"), last_price) if last_price else 0
    final_value = int(state.get("cash") or 0) + position_value
    position_quantity = units_to_quantity(state.get("units"))
    return {
        "ok": True,
        "strategy": strategy,
        "market_symbol": market_symbol,
        "data_source": data_source,
        "provider_symbol": provider_symbol,
        "candle_count": len(candles),
        "max_backtest_candles": max_backtest_candles,
        "max_backtest_candles_per_batch": max_backtest_candles_per_batch,
        "requested_candle_limit": requested_candle_limit,
        "first_candle_time": (candles[0].get("time_iso") or candles[0].get("time")) if candles else "",
        "last_candle_time": (candles[-1].get("time_iso") or candles[-1].get("time")) if candles else "",
        "initial_cash_points": initial_cash,
        "cash_points": state.get("cash"),
        "position_quantity": position_quantity,
        "position_value_points": position_value,
        "final_value_points": final_value,
        "pnl_points": final_value - initial_cash,
        "return_percent": round(((final_value - initial_cash) * 100) / initial_cash, 4),
        "max_drawdown_percent": state.get("max_drawdown_percent"),
        "win_rate_percent": round((state.get("wins", 0) * 100 / state.get("sells", 0)), 4) if state.get("sells") else 0.0,
        "trade_count": len(state.get("trades") or []),
        "trades": state.get("trades") or [],
        "equity_curve": state.get("equity_curve") or [],
        "start_time": start_time,
        "end_time": end_time,
        "range_warnings": list(range_warnings or []),
        "outlier_skipped_count": state.get("outlier_skipped_count", 0),
        "max_price_jump_percent": max_price_jump_percent,
        "end_units": state.get("units"),
        "end_avg_cost": state.get("avg_cost_bt"),
        "end_cash_points": state.get("cash"),
        "segmented_backtest": segment_count > 1,
        "segmented_backtest_batches": segment_count,
    }


def backtest_trading_bot(service, *, actor, payload):
    if not service._actor_id(actor):
        raise ValueError("login required")
    payload = payload or {}
    bot_config = payload.get("bot_config") if isinstance(payload.get("bot_config"), dict) else {}
    if bot_config:
        payload = {**bot_config, **payload}
    candles = payload.get("candles") or []
    if not isinstance(candles, list) or len(candles) < 2:
        raise ValueError("candles are required for backtest")
    active_max_candles = service.get_max_backtest_candles()
    if len(candles) > active_max_candles:
        raise ValueError(f"candles length must be <= {active_max_candles}")
    start_time = str(payload.get("start_time") or "").strip()
    end_time = str(payload.get("end_time") or "").strip()
    if start_time or end_time:
        candles = filter_backtest_candles_by_range(
            candles,
            start_time=start_time,
            end_time=end_time,
        )
        if len(candles) < 2:
            raise ValueError("candles are required for selected backtest range")
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        market = service._market(conn, payload.get("market_symbol"))
        settings = service._settings_payload(conn)
        fee_rate_percent = float(market["fee_rate_percent"] or 0)
        grid_fee_rate_percent = service._grid_fee_rate_percent(fee_rate_percent, settings)
        if payload.get("max_price_jump_percent") is not None:
            max_price_jump_percent = float(payload.get("max_price_jump_percent"))
        else:
            max_price_jump_percent = max(float(market["max_price_jump_percent"] or 0), 70.0)
    finally:
        conn.close()
    strategy = str(payload.get("strategy") or payload.get("bot_type") or "conditional").strip().lower()
    if strategy == "strategy":
        strategy = "workflow"
    if strategy not in {"conditional", "dca", "workflow", "grid"}:
        raise ValueError("backtest strategy must be conditional, workflow, dca, or grid")
    workflow = None
    if strategy == "workflow":
        workflow = service._validate_workflow(payload.get("workflow_json") or payload.get("workflow"))
    cash = _to_int(payload.get("initial_cash_points", 10_000), name="initial_cash_points", minimum=1, maximum=10**12)
    order_points = _to_int(payload.get("order_points", 100), name="order_points", minimum=1, maximum=10**12)
    trigger_type = str(payload.get("trigger_type") or "price_below").strip().lower()
    trigger_price = float(_to_decimal(payload.get("trigger_price_points") or 0, name="trigger_price_points", minimum=0))
    interval_candles = _to_int(payload.get("interval_candles", 1), name="interval_candles", minimum=1, maximum=10_000)
    stop_loss_percent = float(_to_decimal(payload.get("stop_loss_percent") or 0, name="stop_loss_percent", minimum=0))
    take_profit_percent = float(_to_decimal(payload.get("take_profit_percent") or 0, name="take_profit_percent", minimum=0))
    initial_cash = cash
    initial_workflow_state = payload.get("initial_workflow_state") if isinstance(payload.get("initial_workflow_state"), dict) else {}
    range_warnings = []
    state = build_backtest_initial_state(
        cash=cash,
        initial_units=payload.get("initial_units") or 0,
        initial_avg_cost=payload.get("initial_avg_cost") or 0,
        initial_trade_count=payload.get("initial_trade_count") or 0,
        initial_candle_offset=payload.get("initial_candle_offset") or 0,
        initial_workflow_state=initial_workflow_state,
        grid_fee_rate=grid_fee_rate_percent,
    )
    workflow_indicator_series = service._build_workflow_indicator_series(candles) if strategy == "workflow" else []
    segment_size = int(getattr(service, "BACKTEST_SEGMENT_CANDLES", 10_000) or 10_000)

    def _record_equity(global_index, candle, price):
        equity = backtest_equity_value(cash=state["cash"], units=state["units"], price=price)
        state["peak_value"], state["max_drawdown_percent"] = update_backtest_drawdown(
            peak_value=state["peak_value"],
            max_drawdown_percent=state["max_drawdown_percent"],
            equity=equity,
        )
        state["equity_curve"].append(
            build_backtest_equity_point(
                global_index=global_index,
                candle=candle,
                price=price,
                equity=equity,
            )
        )

    def _ensure_grid_state(chunk_candles):
        if strategy != "grid" or state["grid_initialized"]:
            return
        g_lower = _to_price_float(payload.get("lower_price_points", 0), name="lower_price_points", minimum=0.00000001)
        g_upper = _to_price_float(payload.get("upper_price_points", 0), name="upper_price_points", minimum=0.00000002)
        g_count = _to_int(payload.get("grid_count", 10), name="grid_count", minimum=2, maximum=500)
        state["grid_order_amount"] = _to_int(payload.get("order_amount_points", 100), name="order_amount_points", minimum=1)
        g_mode = str(payload.get("spacing_mode") or "arithmetic").strip().lower()
        if g_upper <= g_lower:
            raise ValueError("upper_price_points must be greater than lower_price_points")
        if g_mode == "geometric":
            g_ratio = (g_upper / g_lower) ** (1 / (g_count - 1))
            state["grid_levels"] = [
                float(
                    Decimal(str(g_lower * (g_ratio ** i))).quantize(
                        Decimal("0.00000001"),
                        rounding=ROUND_HALF_UP,
                    )
                )
                for i in range(g_count)
            ]
        else:
            g_step = (g_upper - g_lower) / (g_count - 1)
            state["grid_levels"] = [
                float(
                    Decimal(str(g_lower + g_step * i)).quantize(
                        Decimal("0.00000001"),
                        rounding=ROUND_HALF_UP,
                    )
                )
                for i in range(g_count)
            ]
        g_start = 0
        for chunk_candle in chunk_candles:
            try:
                g_start = float(
                    _to_decimal(
                        chunk_candle.get("close_points") or chunk_candle.get("price_points") or chunk_candle.get("close_usdt") or chunk_candle.get("price_usdt") or 0,
                        name="grid_start_price",
                        minimum=0,
                    )
                )
                if g_start > 0:
                    break
            except Exception:
                pass
        if g_start <= 0:
            raise ValueError("no valid starting price in candles for grid backtest")
        sell_levels = [price_level for price_level in state["grid_levels"] if price_level > g_start]
        buy_levels = [price_level for price_level in state["grid_levels"] if price_level < g_start]
        spot_units_needed = sum(int((state["grid_order_amount"] * ASSET_SCALE) // price_level) for price_level in sell_levels if price_level > 0)
        spot_cost = notional_points(spot_units_needed, g_start)
        spot_fee_cost = fee_points(spot_cost, fee_rate_percent)
        spot_total = spot_cost + spot_fee_cost
        buy_fee_per = fee_points(state["grid_order_amount"], state["grid_fee_rate"])
        buy_total = len(buy_levels) * (state["grid_order_amount"] + buy_fee_per)
        if state["cash"] >= spot_total + buy_total:
            state["cash"] -= spot_total
            state["units"] = spot_units_needed
        else:
            affordable_spot = max(0, state["cash"] - buy_total)
            if affordable_spot > 0 and g_start > 0:
                state["units"] = int(affordable_spot * ASSET_SCALE // g_start)
                state["cash"] -= notional_points(state["units"], g_start) + fee_points(notional_points(state["units"], g_start), fee_rate_percent)
                if state["cash"] < 0:
                    state["cash"] = 0
        state["grid_state"] = {}
        for price_level in state["grid_levels"]:
            if price_level < g_start:
                state["grid_state"][price_level] = "buy"
            elif price_level > g_start:
                state["grid_state"][price_level] = "sell"
            else:
                state["grid_state"][price_level] = None
        state["grid_initialized"] = True

    def _run_chunk(chunk_candles):
        _ensure_grid_state(chunk_candles)
        for local_index, candle in enumerate(chunk_candles):
            global_index = state["processed_candles"] + local_index
            try:
                price = float(candle.get("close_points") or candle.get("price_points") or candle.get("close_usdt") or candle.get("price_usdt"))
            except Exception:
                continue
            if not math.isfinite(price) or price <= 0:
                continue
            anchor_price = backtest_anchor_price(
                recent_valid_prices=state.get("recent_valid_prices"),
                last_valid_price=state.get("last_valid_price"),
            )
            if anchor_price > 0 and max_price_jump_percent > 0:
                jump_percent = abs(price - anchor_price) * 100.0 / anchor_price
                if jump_percent > max_price_jump_percent:
                    state["outlier_skipped_count"] += 1
                    if state["outlier_skipped_count"] <= 5:
                        range_warnings.append(
                            build_backtest_outlier_warning(
                                global_index=global_index,
                                candle=candle,
                                price=price,
                                anchor_price=anchor_price,
                                max_price_jump_percent=max_price_jump_percent,
                            )
                        )
                    continue
            state["last_valid_price"] = price
            state["recent_valid_prices"] = push_recent_valid_price(
                state["recent_valid_prices"],
                price,
                limit=5,
            )

            if strategy == "grid":
                try:
                    low_price = float(candle.get("low_points") or candle.get("low_usdt") or price)
                    high_price = float(candle.get("high_points") or candle.get("high_usdt") or price)
                except Exception:
                    low_price = high_price = price
                state_at_open = dict(state["grid_state"])
                for level in sorted(state_at_open):
                    if state_at_open[level] == "sell" and high_price >= level:
                        sell_units = int((state["grid_order_amount"] * ASSET_SCALE) // level)
                        if state["units"] >= sell_units > 0:
                            gross = notional_points(sell_units, level)
                            fee = fee_points(gross, state["grid_fee_rate"])
                            net = max(0, gross - fee)
                            state["cash"] += net
                            state["units"] -= sell_units
                            state["trades"].append({
                                "index": global_index,
                                "time": candle.get("time") or candle.get("time_iso") or global_index,
                                "side": "sell",
                                "price_points": level,
                                "spend_points": 0,
                                "fee_points": fee,
                                "quantity": units_to_quantity(sell_units),
                            })
                            state["trade_count"] += 1
                            state["grid_state"][level] = None
                            try:
                                counter_index = state["grid_levels"].index(level) - 1
                            except ValueError:
                                counter_index = -1
                            if counter_index >= 0:
                                counter_level = state["grid_levels"][counter_index]
                                if state["grid_state"].get(counter_level) is None:
                                    state["grid_state"][counter_level] = "buy"
                            state["sells"] += 1
                            state["wins"] += 1
                for level in sorted(state_at_open, reverse=True):
                    if state_at_open[level] == "buy" and low_price <= level:
                        fee = fee_points(state["grid_order_amount"], state["grid_fee_rate"])
                        spend = state["grid_order_amount"] + fee
                        if state["cash"] >= spend:
                            buy_units = int((state["grid_order_amount"] * ASSET_SCALE) // level)
                            if buy_units > 0:
                                state["cash"] -= spend
                                prev_units = state["units"]
                                state["units"] += buy_units
                                if state["units"] > 0:
                                    state["avg_cost_bt"] = int((prev_units * state["avg_cost_bt"] + buy_units * level) // state["units"])
                                state["trades"].append({
                                    "index": global_index,
                                    "time": candle.get("time") or candle.get("time_iso") or global_index,
                                    "side": "buy",
                                    "price_points": level,
                                    "spend_points": spend,
                                    "fee_points": fee,
                                    "quantity": units_to_quantity(buy_units),
                                })
                                state["trade_count"] += 1
                                state["grid_state"][level] = None
                                try:
                                    counter_index = state["grid_levels"].index(level) + 1
                                except ValueError:
                                    counter_index = len(state["grid_levels"])
                                if counter_index < len(state["grid_levels"]):
                                    counter_level = state["grid_levels"][counter_index]
                                    if state["grid_state"].get(counter_level) is None:
                                        state["grid_state"][counter_level] = "sell"
                _record_equity(global_index, candle, price)
                continue

            should_buy = False
            should_sell = False
            workflow_spend = order_points
            workflow_sell_percent = 0.0
            decision = None
            if state["units"] > 0 and state["avg_cost_bt"] > 0:
                pnl_low_percent = round(((float(candle.get("low_points") or candle.get("low_usdt") or price) - state["avg_cost_bt"]) * 100.0) / state["avg_cost_bt"], 4)
                pnl_high_percent = round(((float(candle.get("high_points") or candle.get("high_usdt") or price) - state["avg_cost_bt"]) * 100.0) / state["avg_cost_bt"], 4)
                if stop_loss_percent > 0 and pnl_low_percent <= -abs(stop_loss_percent):
                    should_sell = True
                    workflow_sell_percent = 100.0
                elif take_profit_percent > 0 and pnl_high_percent >= abs(take_profit_percent):
                    should_sell = True
                    workflow_sell_percent = 100.0
            if strategy == "dca":
                should_buy = not should_sell and global_index % interval_candles == 0
            elif strategy == "workflow":
                context = dict(workflow_indicator_series[global_index] or {})
                context["price"] = price
                context["has_position"] = state["units"] > 0
                context["avg_cost"] = state["avg_cost_bt"]
                context["pnl_percent"] = round((price - state["avg_cost_bt"]) * 100.0 / state["avg_cost_bt"], 4) if state["units"] > 0 and state["avg_cost_bt"] > 0 else None
                if not should_sell:
                    decision = service._workflow_decision(
                        workflow,
                        context=context,
                        run_count=state["trade_count"],
                        last_run_at=None,
                        execution_state=state["workflow_state"],
                    )
                    action = (decision or {}).get("action") or {}
                    action_type = str(action.get("type") or "hold")
                    if action_type in {"buy_percent", "buy_amount"}:
                        should_buy = True
                        workflow_spend = int(float(action.get("amount_points") or 0))
                        if action_type == "buy_percent":
                            workflow_spend = int(state["cash"] * max(0.0, min(float(action.get("percent") or 0), 100.0)) / 100)
                    elif action_type in {"sell_percent", "close_all"}:
                        should_sell = True
                        workflow_sell_percent = 100.0 if action_type == "close_all" else max(0.0, min(float(action.get("percent") or 0), 100.0))
            elif trigger_type == "price_below":
                should_buy = not should_sell and trigger_price > 0 and price <= trigger_price
            elif trigger_type == "price_above":
                should_buy = not should_sell and trigger_price > 0 and price >= trigger_price
            elif trigger_type == "always":
                should_buy = not should_sell
            if should_sell and state["units"] > 0:
                sell_units = int(state["units"] * workflow_sell_percent / 100)
                if sell_units > 0:
                    gross = notional_points(sell_units, price)
                    fee = fee_points(gross, fee_rate_percent)
                    state["cash"] += max(0, gross - fee)
                    state["units"] -= sell_units
                    if state["units"] <= 0:
                        state["avg_cost_bt"] = 0
                    state["trades"].append({
                        "index": global_index,
                        "time": candle.get("time") or candle.get("time_iso") or global_index,
                        "side": "sell",
                        "price_points": price,
                        "spend_points": 0,
                        "fee_points": fee,
                        "pnl_points": max(0, gross - fee),
                        "quantity": units_to_quantity(sell_units),
                    })
                    state["trade_count"] += 1
                    state["sells"] += 1
                    if gross - fee > 0:
                        state["wins"] += 1
                    if strategy == "workflow" and decision:
                        action_id = decision.get("action_id") or (decision.get("branch") or {}).get("id")
                        if action_id:
                            state["workflow_state"]["executed_action_ids"].add(action_id)
                        branch_id = (decision.get("branch") or {}).get("id")
                        if branch_id:
                            state["workflow_state"]["branch_step_counts"][branch_id] = int(state["workflow_state"]["branch_step_counts"].get(branch_id, 0)) + 1
                    _record_equity(global_index, candle, price)
                else:
                    _record_equity(global_index, candle, price)
                continue
            if not should_buy or state["cash"] <= 0:
                _record_equity(global_index, candle, price)
                continue
            spend = min(workflow_spend, state["cash"])
            fee = fee_points(spend, fee_rate_percent)
            net_spend = max(0, spend - fee)
            buy_units = int((Decimal(str(net_spend)) * Decimal(ASSET_SCALE) / Decimal(str(price))).quantize(Decimal("1"), rounding=ROUND_DOWN))
            if buy_units <= 0:
                _record_equity(global_index, candle, price)
                continue
            state["cash"] -= spend
            prev_units = state["units"]
            state["units"] += buy_units
            if state["units"] > 0:
                state["avg_cost_bt"] = float(((Decimal(str(prev_units)) * Decimal(str(state["avg_cost_bt"]))) + (Decimal(str(buy_units)) * Decimal(str(price)))) / Decimal(str(state["units"])))
            state["trades"].append({
                "index": global_index,
                "time": candle.get("time") or candle.get("time_iso") or global_index,
                "side": "buy",
                "price_points": price,
                "spend_points": spend,
                "fee_points": fee,
                "quantity": units_to_quantity(buy_units),
            })
            state["trade_count"] += 1
            if strategy == "workflow" and decision:
                action_id = decision.get("action_id") or (decision.get("branch") or {}).get("id")
                if action_id:
                    state["workflow_state"]["executed_action_ids"].add(action_id)
                branch_id = (decision.get("branch") or {}).get("id")
                if branch_id:
                    state["workflow_state"]["branch_step_counts"][branch_id] = int(state["workflow_state"]["branch_step_counts"].get(branch_id, 0)) + 1
            _record_equity(global_index, candle, price)
        state["processed_candles"] += len(chunk_candles)

    segment_count = backtest_segment_count(len(candles), segment_size)
    for chunk in iter_backtest_segments(candles, segment_size):
        _run_chunk(chunk)
    all_candles_raw = payload.get("candles") or []
    range_warnings = build_backtest_range_warnings(
        existing_warnings=range_warnings,
        start_time=start_time,
        end_time=end_time,
        all_candles_raw=all_candles_raw,
        candle_count=len(candles),
        max_backtest_candles=active_max_candles,
        segment_count=segment_count,
        max_backtest_candles_per_batch=segment_size,
        outlier_skipped_count=state["outlier_skipped_count"],
        max_price_jump_percent=max_price_jump_percent,
    )
    return build_backtest_result_payload(
        state=state,
        candles=candles,
        strategy=strategy,
        market_symbol=market["symbol"],
        initial_cash=initial_cash,
        start_time=start_time,
        end_time=end_time,
        range_warnings=range_warnings,
        max_backtest_candles=active_max_candles,
        max_backtest_candles_per_batch=segment_size,
        requested_candle_limit=payload.get("requested_candle_limit") or payload.get("candle_limit") or payload.get("limit") or len(candles),
        data_source=str(payload.get("data_source") or ("provided_candles" if payload.get("candles") else "")),
        provider_symbol=str(payload.get("provider_symbol") or ""),
        max_price_jump_percent=max_price_jump_percent,
        segment_count=segment_count,
    )
