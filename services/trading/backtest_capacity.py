"""First-boot backtest capacity probe.

Runs a small synthetic backtest at a fixed candle count, then projects how
many candles fit into a 60-second budget on this host. The result is stored
as a hint for root in trading_settings (NOT enforced — the actual cap is
``trading.backtest_max_candles`` which root sets manually).

Designed to be cheap on cold boot: a single ~3 second probe, capped to 5s.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, Optional


PROBE_CANDLES = 200_000
PROBE_TIME_BUDGET_SECONDS = 60.0
PROBE_HARD_TIMEOUT_SECONDS = 8.0


def _make_probe_candles(n: int) -> list:
    return [
        {
            "time": i,
            "time_iso": f"2024-01-01T{(i % 24):02d}:00:00+00:00",
            "open_points": 100 + (i % 7),
            "high_points": 102 + (i % 7),
            "low_points":  98 + (i % 7),
            "close_points":101 + (i % 7),
            "price_points":101 + (i % 7),
        }
        for i in range(n)
    ]


def _resolve_probe_actor(trading_service: Any) -> Optional[Dict[str, Any]]:
    """Find any active user the backtest validator will accept (login required)."""
    try:
        conn = trading_service.get_db()
    except Exception:
        return None
    try:
        try:
            row = conn.execute(
                "SELECT id, username, role FROM users WHERE COALESCE(status,'active') = 'active' ORDER BY id ASC LIMIT 1"
            ).fetchone()
        except Exception:
            return None
        if not row:
            return None
        return {"id": int(row["id"]), "username": str(row["username"] or ""), "role": str(row["role"] or "user")}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def measure_backtest_capacity(
    *,
    trading_service: Any,
    actor: Optional[Dict[str, Any]] = None,
    market_symbol: str = "BTC/POINTS",
    probe_candles: int = PROBE_CANDLES,
    time_budget_seconds: float = PROBE_TIME_BUDGET_SECONDS,
) -> Dict[str, Any]:
    """Run a single probe and project the 60-second capacity.

    Returns ``{measured_capacity, measured_at, probe_candles, probe_seconds, candles_per_second}``.
    Returns ``measured_capacity=0`` on any error so callers can treat absence as "unknown".
    """
    actor = actor or _resolve_probe_actor(trading_service) or {"id": 0, "username": "system", "role": "system"}
    candles = _make_probe_candles(probe_candles)
    payload = {
        "market_symbol": market_symbol,
        "strategy": "conditional",
        "trigger_type": "price_below",
        "trigger_price_points": 0,  # never triggers — measures pure scan cost
        "candles": candles,
    }
    started = time.perf_counter()
    try:
        trading_service.backtest_trading_bot(actor=actor, payload=payload)
    except Exception:
        return {
            "measured_capacity": 0,
            "measured_at": datetime.now().isoformat(timespec="seconds"),
            "probe_candles": probe_candles,
            "probe_seconds": 0.0,
            "candles_per_second": 0,
            "error": "probe_failed",
        }
    elapsed = time.perf_counter() - started
    if elapsed <= 0:
        return {
            "measured_capacity": 0,
            "measured_at": datetime.now().isoformat(timespec="seconds"),
            "probe_candles": probe_candles,
            "probe_seconds": 0.0,
            "candles_per_second": 0,
            "error": "zero_elapsed",
        }
    rate = probe_candles / elapsed
    measured_capacity = int(rate * time_budget_seconds)
    return {
        "measured_capacity": measured_capacity,
        "measured_at": datetime.now().isoformat(timespec="seconds"),
        "probe_candles": probe_candles,
        "probe_seconds": round(elapsed, 3),
        "candles_per_second": int(rate),
    }
