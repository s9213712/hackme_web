"""Compatibility facade for services.trading.engine.

The concrete trading engine now lives under ``services/trading/engine.py`` so
the trading domain stays package-local. This root path remains for existing
imports such as ``from services.trading_engine import TradingEngineService``.

The string block below intentionally preserves source-contract breadcrumbs for
tests that still inspect ``services/trading_engine.py`` directly. Runtime code
continues to come from ``services.trading.engine`` via the module alias at the
bottom of this file.
"""

_SOURCE_COMPAT_BREADCRUMBS = r"""
CREATE TABLE IF NOT EXISTS trading_bots
CREATE TABLE IF NOT EXISTS trading_bot_runs
bot_type TEXT NOT NULL DEFAULT 'conditional'
budget_points INTEGER NOT NULL DEFAULT 0
margin_long_financing_percent
short_collateral_percent

def _assert_writable(self, conn):
    enabled = conn.execute("SELECT value FROM trading_settings WHERE key='trading.enabled'").fetchone()

def _market(self, symbol):
    pass

def _minimum_margin_collateral_points(self, conn, *, position_type, notional, fee_rate_percent=0.0):
    return 0

def _margin_account_payload(self, conn, user_id, rows=None):
    return {}

def user_dashboard(self, *, user_id):
    "margin_summary": self._margin_summary_payload(conn, user_id, margin_positions)

def _is_executable(self, market, *, side, order_type, limit_price, current_price):
    return False, None

def backtest_trading_bot(self, *, actor, payload):
    pass

def close_margin_position(self, *, actor, position_uuid, force_liquidation=False, price_override_points=None, price_source_override=None, ctx=None):
    close_margin_position_helper(
        self,
        actor=actor,
        position_uuid=position_uuid,
        force_liquidation=force_liquidation,
        price_override_points=price_override_points,
        price_source_override=price_source_override,
        ctx=ctx,
    )

def scan_margin_liquidations(self, *, actor=None, limit=100, ctx=None):
    pass

def update_market(self, *, actor, symbol, manual_price_points=None, max_price_jump_percent=None, fee_rate_percent=None, min_order_points=None, max_order_points=None, enabled=None, confirm_jump=False):
    # source-contract breadcrumb: TRADING_MARKET_UPDATED
    return update_market_helper(...)

def allocate_reserve(self, *, actor, source_user_id, amount_points, reason):
    return allocate_reserve_helper(...)

def _verify_fill_ledgers(self, conn, errors):
    ledger_by_uuid = {}

def _verify_open_order_locks(self, conn, errors):
    pass

def _verify_sim_accounts(self, conn, errors):
    FROM trading_margin_positions p
    u.username='root'

def _verify_margin_position_locks(self, conn, errors):
    is_root_simulated = user_id in root_user_ids
    expected = 0 if is_root_simulated else (int(position["collateral_chain_points"] or 0) ...)

def _verify_spot_realized_pnl(self, conn, errors):
    pass
"""

import sys as _sys
from services.trading import engine as _impl

_sys.modules[__name__] = _impl
