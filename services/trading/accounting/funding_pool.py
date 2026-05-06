"""Pure trading funding-pool helpers."""


def funding_pool_outstanding_principal(*, lent, repaid):
    return max(0, abs(int(lent or 0)) - int(repaid or 0))


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
):
    balance = int(balance or 0)
    outstanding = int(outstanding or 0)
    requested = max(0, int(requested_principal or 0))
    capacity = max(0, balance + outstanding)
    projected_balance = max(0, balance - requested)
    projected_outstanding = outstanding + requested
    projected_capacity = max(0, projected_balance + projected_outstanding)
    utilization = (outstanding / capacity) if capacity > 0 else 0.0
    projected_utilization = (projected_outstanding / projected_capacity) if projected_capacity > 0 else 1.0
    pressure = max(0.0, float(pressure or 0))
    base_rate = daily_from_apr(base_apr)
    effective_rate = base_rate * (1.0 + max(0.0, utilization) * pressure)
    projected_rate = base_rate * (1.0 + max(0.0, projected_utilization) * pressure)
    borrowed_asset = str(borrowed_asset or "POINTS").strip().upper() or "POINTS"
    return {
        "name": "資金池",
        "initial_points": int(initial_points or 0),
        "balance_points": balance,
        "available_points": balance,
        "outstanding_principal_points": outstanding,
        "capacity_points": capacity,
        "utilization_percent": round(utilization * 100, 4),
        "projected_utilization_percent": round(projected_utilization * 100, 4),
        "borrowed_asset_symbol": borrowed_asset,
        "base_interest_apr_percent": round(float(base_apr or 0), 8),
        "effective_interest_apr_percent": round(apr_from_daily(effective_rate), 8),
        "projected_interest_apr_percent": round(apr_from_daily(projected_rate), 8),
        "base_interest_percent_daily": round(base_rate, 8),
        "interest_pool_pressure_multiplier": round(pressure, 8),
        "effective_interest_percent_daily": round(effective_rate, 8),
        "projected_interest_percent_daily": round(projected_rate, 8),
    }
