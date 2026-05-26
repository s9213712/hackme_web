"""Pure trading funding-pool helpers."""


def funding_pool_outstanding_principal(*, lent, repaid):
    return max(0, abs(int(lent or 0)) - int(repaid or 0))


def _effective_apr_display(*, base_apr_percent, base_rate, scaled_rate, apr_from_daily):
    """Return the APR % to display.

    The base APR ↔ daily-rate round trip uses Decimal quantize at 1e-8 which
    introduces ~1e-7 cosmetic drift on the way back. When the scaled rate is
    bit-for-bit equal to the base rate (utilisation × pressure == 0) we just
    surface the base APR exactly, sidestepping the drift entirely. Otherwise
    we apply the round-trip and round the result to 6 decimals — more than
    enough precision for an APR display, and absorbs the residual drift.
    """
    if scaled_rate == base_rate:
        return round(float(base_apr_percent or 0), 6)
    return round(apr_from_daily(scaled_rate), 6)


def funding_pool_payload(
    *,
    balance,
    outstanding,
    requested_principal,
    borrowed_asset,
    base_apr,
    pressure,
    initial_points,
    daily_from_apr,
    apr_from_daily,
    lendable_capacity=None,
    liquid_available=None,
    exchange_fund_balance=None,
    cfd_profit_reserve_required=0,
):
    balance = int(balance or 0)
    outstanding = int(outstanding or 0)
    requested = max(0, int(requested_principal or 0))
    capacity = max(0, int(lendable_capacity if lendable_capacity is not None else balance + outstanding))
    available = max(0, int(liquid_available if liquid_available is not None else balance))
    available = min(available, max(0, capacity - outstanding))
    projected_balance = max(0, available - requested)
    projected_outstanding = outstanding + requested
    projected_capacity = capacity
    utilization = (outstanding / capacity) if capacity > 0 else 0.0
    projected_utilization = (projected_outstanding / projected_capacity) if projected_capacity > 0 else 1.0
    pressure = max(0.0, float(pressure or 0))
    base_rate = daily_from_apr(base_apr)
    effective_rate = base_rate * (1.0 + max(0.0, utilization) * pressure)
    projected_rate = base_rate * (1.0 + max(0.0, projected_utilization) * pressure)
    borrowed_asset = str(borrowed_asset or "POINTS").strip().upper() or "POINTS"
    base_apr_display = round(float(base_apr or 0), 6)
    return {
        "name": "借貸基金",
        "initial_points": int(initial_points or 0),
        "balance_points": available,
        "available_points": available,
        "outstanding_principal_points": outstanding,
        "capacity_points": capacity,
        "exchange_fund_balance_points": int(exchange_fund_balance if exchange_fund_balance is not None else balance),
        "cfd_profit_reserve_required_points": max(0, int(cfd_profit_reserve_required or 0)),
        "utilization_percent": round(utilization * 100, 4),
        "projected_utilization_percent": round(projected_utilization * 100, 4),
        "borrowed_asset_symbol": borrowed_asset,
        "base_interest_apr_percent": base_apr_display,
        "effective_interest_apr_percent": _effective_apr_display(
            base_apr_percent=base_apr,
            base_rate=base_rate,
            scaled_rate=effective_rate,
            apr_from_daily=apr_from_daily,
        ),
        "projected_interest_apr_percent": _effective_apr_display(
            base_apr_percent=base_apr,
            base_rate=base_rate,
            scaled_rate=projected_rate,
            apr_from_daily=apr_from_daily,
        ),
        "base_interest_percent_daily": round(base_rate, 8),
        "interest_pool_pressure_multiplier": round(pressure, 8),
        "effective_interest_percent_daily": round(effective_rate, 8),
        "projected_interest_percent_daily": round(projected_rate, 8),
    }
