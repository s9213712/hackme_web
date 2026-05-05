"""Phase 5 (boundary) of SERVER_MODE_V2_IMPLEMENTATION_PLAN.md.

Locks in the trading mode-gate contract — the entry-point guard every
trading entry point should call before doing anything else. The deeper
G-1 .. G-5 refactor of services/trading_engine.py to route every SQL
through resolve_table is Phase 5b and lands separately; this commit
proves the gate primitives behave correctly.
"""

import pytest

from services.points_chain import ChainModeViolation
from services.server_mode_context import SmV2Context
from services.trading_mode_gate import (
    CrossWorldContamination,
    TradingDisabledInMode,
    assert_same_world,
    assert_trading_allowed,
    funding_channel_key,
    liquidation_settle_table,
    liquidation_target_table,
    matching_orderbook_key,
)


def _ctx(mode, tester_id=None):
    return SmV2Context(mode=mode, tester_id=tester_id, actor_role=None, request_id="r")


# ── assert_trading_allowed ────────────────────────────────────────────


@pytest.mark.parametrize("mode", ["production", "internal_test", "test"])
def test_trading_allowed_in_trading_modes(mode):
    ctx = _ctx(mode, tester_id=1 if mode == "internal_test" else None)
    assert assert_trading_allowed(ctx).mode == mode


@pytest.mark.parametrize("mode", ["dev_ready", "maintenance", "incident_lockdown", "superweak", ""])
def test_trading_refused_in_non_trading_modes(mode):
    with pytest.raises(TradingDisabledInMode) as exc:
        assert_trading_allowed(_ctx(mode))
    assert exc.value.mode == mode


def test_trading_refuses_none_ctx():
    with pytest.raises(RuntimeError):
        assert_trading_allowed(None)


# ── assert_same_world ─────────────────────────────────────────────────


def test_same_world_same_mode_passes():
    a = _ctx("production")
    b = _ctx("production")
    assert assert_same_world(a, b, action="liquidate") is None


def test_same_world_cross_world_raises():
    prod = _ctx("production")
    inter = _ctx("internal_test", tester_id=1)
    with pytest.raises(CrossWorldContamination) as exc:
        assert_same_world(prod, inter, action="liquidate")
    assert exc.value.source_mode == "production"
    assert exc.value.sink_mode == "internal_test"


# ── matching_orderbook_key ────────────────────────────────────────────


def test_orderbook_keys_differ_per_mode():
    prod = matching_orderbook_key("BTC/POINTS", _ctx("production"))
    test = matching_orderbook_key("BTC/POINTS", _ctx("test"))
    inter = matching_orderbook_key("BTC/POINTS", _ctx("internal_test", tester_id=7))
    assert prod != test != inter


def test_orderbook_internal_test_requires_tester_id():
    with pytest.raises(ValueError):
        matching_orderbook_key("BTC/POINTS", _ctx("internal_test"))


def test_orderbook_refused_in_non_trading_mode():
    with pytest.raises(TradingDisabledInMode):
        matching_orderbook_key("BTC/POINTS", _ctx("dev_ready"))


# ── funding_channel_key ───────────────────────────────────────────────


def test_funding_channels_differ_per_mode():
    prod = funding_channel_key("BTC", _ctx("production"))
    inter = funding_channel_key("BTC", _ctx("internal_test", tester_id=1))
    assert prod != inter
    assert ":production:" in prod
    assert ":internal_test:" in inter


def test_funding_channel_refused_in_non_trading_mode():
    for bad in ("dev_ready", "maintenance", "incident_lockdown", "superweak"):
        with pytest.raises(TradingDisabledInMode):
            funding_channel_key("BTC", _ctx(bad))


# ── liquidation tables ────────────────────────────────────────────────


def test_liquidation_target_in_production():
    assert liquidation_target_table(_ctx("production")) == "trading_margin_positions"


def test_liquidation_target_in_internal_test_uses_shadow():
    assert liquidation_target_table(_ctx("internal_test", tester_id=1)) == "test_shadow_margin_positions"


def test_liquidation_settle_in_production():
    assert liquidation_settle_table(_ctx("production")) == "wallets"


def test_liquidation_settle_in_internal_test_uses_shadow():
    assert liquidation_settle_table(_ctx("internal_test", tester_id=1)) == "test_shadow_wallets"


def test_liquidation_refused_in_non_trading_mode():
    for bad in ("dev_ready", "maintenance", "incident_lockdown", "superweak"):
        with pytest.raises(TradingDisabledInMode):
            liquidation_target_table(_ctx(bad))


def test_liquidation_in_test_mode_uses_routing_not_allowed_for_now():
    """test mode is "trading allowed" at the gate but has no routing
    target for positions — caller should see the routing error, not a
    silent fallback.
    """
    from services.server_mode_routing import RoutingNotAllowed
    with pytest.raises(RoutingNotAllowed):
        liquidation_target_table(_ctx("test"))
