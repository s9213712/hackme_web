"""Pure trading grid helpers.

This module groups deterministic grid preview math and payload helpers.
`TradingEngineService` still owns DB access, order placement, and scan
orchestration.
"""

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from services.trading.constants import (
    ASSET_SCALE,
    DEFAULT_GRID_FEE_DISCOUNT_PERCENT,
    GRID_PREVIEW_YELLOW_NET_SPREAD_PERCENT,
)
from services.trading.validators import _decimal_text, _to_decimal


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
