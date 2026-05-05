"""Pure orderbook helpers for trading price fusion."""


def provider_depth_request_limit(source, depth_levels, *, default_depth_levels=100):
    requested = max(1, int(depth_levels or default_depth_levels))
    if source == "binance_public_api":
        for value in (5, 10, 20, 50, 100, 500, 1000, 5000):
            if requested <= value:
                return value
        return 5000
    if source == "okx_public_api":
        return max(1, min(requested, 400))
    if source == "kraken_public_api":
        return max(1, min(requested, 500))
    if source == "gemini_public_api":
        return max(1, min(requested, 500))
    return requested


def parse_orderbook_side(rows, *, max_levels):
    raw_rows = list(rows or [])
    parsed = []
    for row in raw_rows[:max_levels]:
        if isinstance(row, dict):
            price = row.get("price")
            quantity = row.get("amount", row.get("quantity", row.get("size")))
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            price, quantity = row[0], row[1]
        else:
            continue
        try:
            parsed.append((float(price), float(quantity)))
        except Exception:
            continue
    return {
        "raw_count": len(raw_rows),
        "used_count": len(parsed),
        "levels": parsed,
    }


def depth_notional_snapshot(bids, asks, *, max_levels=100, band_percent=1.0):
    bid_info = parse_orderbook_side(bids, max_levels=max_levels)
    ask_info = parse_orderbook_side(asks, max_levels=max_levels)
    bid_levels = bid_info["levels"]
    ask_levels = ask_info["levels"]
    if not bid_levels or not ask_levels:
        raise ValueError("order book is empty")
    best_bid = bid_levels[0][0]
    best_ask = ask_levels[0][0]
    if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
        raise ValueError("order book spread is invalid")
    midpoint = (best_bid + best_ask) / 2.0
    lower_bound = midpoint * (1.0 - band_percent / 100.0)
    upper_bound = midpoint * (1.0 + band_percent / 100.0)
    min_bid = min(price for price, _quantity in bid_levels)
    max_ask = max(price for price, _quantity in ask_levels)
    bid_coverage_percent = min(
        max(((midpoint - min_bid) / midpoint) * 100.0, 0.0) if midpoint > 0 else 0.0,
        float(band_percent),
    )
    ask_coverage_percent = min(
        max(((max_ask - midpoint) / midpoint) * 100.0, 0.0) if midpoint > 0 else 0.0,
        float(band_percent),
    )
    bid_reached_lower_bound = min_bid <= lower_bound + 1e-12
    ask_reached_upper_bound = max_ask >= upper_bound - 1e-12
    orderbook_truncated = not (bid_reached_lower_bound and ask_reached_upper_bound)
    bid_notional = sum(price * quantity for price, quantity in bid_levels if price >= lower_bound)
    ask_notional = sum(price * quantity for price, quantity in ask_levels if price <= upper_bound)
    score = min(bid_notional, ask_notional)
    if score <= 0:
        score = (bid_notional + ask_notional) / 2.0
    if score <= 0:
        raise ValueError("order book depth score is invalid")
    coverage_ratio = 1.0
    if float(band_percent) > 0:
        coverage_ratio = max(0.0, min(min(bid_coverage_percent, ask_coverage_percent) / float(band_percent), 1.0))
    effective_depth_score = score * coverage_ratio
    min_coverage_percent = min(float(bid_coverage_percent or 0.0), float(ask_coverage_percent or 0.0))
    depth_density_score = (score / min_coverage_percent) if min_coverage_percent > 0 else 0.0
    spread_points = best_ask - best_bid
    spread_percent = (spread_points / midpoint * 100.0) if midpoint > 0 else 0.0
    stronger_side = max(bid_notional, ask_notional)
    side_balance_ratio = (score / stronger_side) if stronger_side > 0 else 0.0
    return {
        "midpoint": midpoint,
        "depth_score": score,
        "effective_depth_score": effective_depth_score,
        "depth_density_score": depth_density_score,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_points": spread_points,
        "spread_percent": spread_percent,
        "bid_notional": bid_notional,
        "ask_notional": ask_notional,
        "side_balance_ratio": side_balance_ratio,
        "bid_coverage_percent": bid_coverage_percent,
        "ask_coverage_percent": ask_coverage_percent,
        "bid_reached_lower_bound": bid_reached_lower_bound,
        "ask_reached_upper_bound": ask_reached_upper_bound,
        "orderbook_truncated": orderbook_truncated,
        "coverage_ratio_percent": coverage_ratio * 100.0,
        "raw_bid_levels_count": bid_info["raw_count"],
        "raw_ask_levels_count": ask_info["raw_count"],
        "used_bid_levels_count": bid_info["used_count"],
        "used_ask_levels_count": ask_info["used_count"],
        "band_percent": float(band_percent),
        "depth_levels_requested": int(max_levels),
    }


def depth_notional_score(bids, asks, *, max_levels=100, band_percent=1.0):
    snapshot = depth_notional_snapshot(bids, asks, max_levels=max_levels, band_percent=band_percent)
    return snapshot["midpoint"], snapshot["depth_score"]
