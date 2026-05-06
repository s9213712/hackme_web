"""Pure trading backtest helpers.

This module keeps the deterministic candle/range/replay helpers used by
``TradingEngineService.backtest_trading_bot``. The engine still owns the
strategy loop, workflow decisions, and all state mutation orchestration.
"""

import math

from services.trading.accounting.core import notional_points, units_to_quantity


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
