"""First-boot backtest capacity probe.

Measures the host's worst-case backtest throughput by running a small probe
against every supported bot strategy (and every system workflow template),
then projects the slowest per-candle cost into a configurable time budget.

The result is a hint for root, NOT enforced: the actual cap is
``trading.backtest_max_candles`` which root sets manually. The hint exists
so root can pick a cap that even the slowest bot can finish within the
budget.

Designed to be cheap on cold boot: each probe runs ~20K candles
(~0.2-0.5s each on commodity hardware), so ~16 probes complete in well
under 10 seconds.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


PROBE_CANDLES = 20_000
PROBE_TIME_BUDGET_SECONDS = 60.0
WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / "workflows" / "system"


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


def _load_workflow_templates() -> List[Tuple[str, Dict[str, Any]]]:
    if not WORKFLOWS_DIR.is_dir():
        return []
    templates = []
    for path in sorted(WORKFLOWS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        wf = data.get("workflow")
        if isinstance(wf, dict):
            templates.append((path.stem, wf))
    return templates


def _build_probe_payloads(market_symbol: str, candles: list) -> List[Tuple[str, Dict[str, Any]]]:
    """Return [(label, payload), ...] for one probe per bot type."""
    payloads: List[Tuple[str, Dict[str, Any]]] = []
    payloads.append(("conditional", {
        "market_symbol": market_symbol,
        "strategy": "conditional",
        "trigger_type": "price_below",
        "trigger_price_points": 0,
        "candles": candles,
    }))
    payloads.append(("dca", {
        "market_symbol": market_symbol,
        "strategy": "dca",
        "interval_seconds": 3600,
        "order_amount_points": 100,
        "candles": candles,
    }))
    payloads.append(("grid", {
        "market_symbol": market_symbol,
        "strategy": "grid",
        "lower_price_points": 100,
        "upper_price_points": 110,
        "grid_count": 10,
        "order_amount_points": 100,
        "candles": candles,
    }))
    for name, wf in _load_workflow_templates():
        payloads.append((f"workflow:{name}", {
            "market_symbol": market_symbol,
            "strategy": "workflow",
            "workflow_json": wf,
            "candles": candles,
        }))
    return payloads


def measure_backtest_capacity(
    *,
    trading_service: Any,
    actor: Optional[Dict[str, Any]] = None,
    market_symbol: str = "BTC/POINTS",
    probe_candles: int = PROBE_CANDLES,
    time_budget_seconds: float = PROBE_TIME_BUDGET_SECONDS,
) -> Dict[str, Any]:
    """Run probes across all bot types and return the worst-case 60-second capacity.

    Returns ``{measured_capacity, measured_at, probe_candles, time_budget_seconds,
    bottleneck_strategy, bottleneck_seconds, runs}`` where ``runs`` lists the
    per-strategy timing. ``measured_capacity = floor(budget / max_per_candle_cost)``
    so root knows the slowest bot can finish within the budget at this cap.
    """
    actor = actor or _resolve_probe_actor(trading_service) or {"id": 0, "username": "system", "role": "system"}
    candles = _make_probe_candles(probe_candles)
    payloads = _build_probe_payloads(market_symbol, candles)

    runs: List[Dict[str, Any]] = []
    for label, payload in payloads:
        started = time.perf_counter()
        ok = False
        error = ""
        try:
            trading_service.backtest_trading_bot(actor=actor, payload=payload)
            ok = True
        except Exception as exc:
            error = str(exc)[:200]
        elapsed = time.perf_counter() - started
        runs.append({
            "strategy": label,
            "ok": ok,
            "elapsed_seconds": round(elapsed, 4),
            "candles_per_second": int(probe_candles / elapsed) if (ok and elapsed > 0) else 0,
            "error": error,
        })

    successful = [r for r in runs if r["ok"] and r["elapsed_seconds"] > 0]
    if not successful:
        return {
            "measured_capacity_min": 0,
            "measured_capacity_max": 0,
            "measured_at": datetime.now().isoformat(timespec="seconds"),
            "probe_candles": probe_candles,
            "time_budget_seconds": time_budget_seconds,
            "bottleneck_strategy": "",
            "bottleneck_seconds": 0.0,
            "fastest_strategy": "",
            "fastest_seconds": 0.0,
            "runs": runs,
            "error": "no_successful_probes",
        }

    bottleneck = max(successful, key=lambda r: r["elapsed_seconds"])
    fastest = min(successful, key=lambda r: r["elapsed_seconds"])
    worst_per_candle = bottleneck["elapsed_seconds"] / probe_candles
    best_per_candle = fastest["elapsed_seconds"] / probe_candles
    capacity_min = int(time_budget_seconds / worst_per_candle) if worst_per_candle > 0 else 0
    capacity_max = int(time_budget_seconds / best_per_candle) if best_per_candle > 0 else 0
    return {
        "measured_capacity_min": capacity_min,
        "measured_capacity_max": capacity_max,
        "measured_at": datetime.now().isoformat(timespec="seconds"),
        "probe_candles": probe_candles,
        "time_budget_seconds": time_budget_seconds,
        "bottleneck_strategy": bottleneck["strategy"],
        "bottleneck_seconds": bottleneck["elapsed_seconds"],
        "fastest_strategy": fastest["strategy"],
        "fastest_seconds": fastest["elapsed_seconds"],
        "runs": runs,
    }
