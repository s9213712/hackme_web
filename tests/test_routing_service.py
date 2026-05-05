"""Phase 2 of SERVER_MODE_V2_IMPLEMENTATION_PLAN.md — resolve_table().

Locks the contract:
- production -> production tables
- internal_test -> test_shadow_* tables
- points_chain_blocks always raises in non-production
- everything else (dev_ready / test / maintenance / incident_lockdown /
  superweak) raises RoutingNotAllowed
- unknown logical / None ctx / typo'd mode all raise loudly
"""

import pytest

from services import server_mode_routing as routing
from services.points_chain import ChainModeViolation
from services.server_mode_context import SmV2Context


def _ctx(mode):
    return SmV2Context(mode=mode, tester_id=None, actor_role=None, request_id="r")


# ── production routing ───────────────────────────────────────────────


def test_production_routes_wallets_to_prod():
    assert routing.resolve_table("wallets", _ctx("production")) == "wallets"


def test_production_routes_orders_to_trading_orders():
    assert routing.resolve_table("orders", _ctx("production")) == "trading_orders"


def test_production_routes_positions_to_trading_spot_positions():
    assert routing.resolve_table("positions", _ctx("production")) == "trading_spot_positions"


def test_production_routes_points_ledger_to_prod():
    assert routing.resolve_table("points_ledger", _ctx("production")) == "points_ledger"


def test_production_routes_chain_blocks_to_prod():
    assert routing.resolve_table("points_chain_blocks", _ctx("production")) == "points_chain_blocks"


# ── internal_test routing ─────────────────────────────────────────────


def test_internal_test_routes_wallets_to_shadow():
    assert routing.resolve_table("wallets", _ctx("internal_test")) == "test_shadow_wallets"


def test_internal_test_routes_orders_to_shadow():
    assert routing.resolve_table("orders", _ctx("internal_test")) == "test_shadow_orders"


def test_internal_test_routes_positions_to_shadow():
    assert routing.resolve_table("positions", _ctx("internal_test")) == "test_shadow_positions"


def test_internal_test_routes_points_ledger_to_shadow():
    assert routing.resolve_table("points_ledger", _ctx("internal_test")) == "test_shadow_ledger"


def test_internal_test_chain_blocks_raises():
    """No shadow chain — chain is production-only, period."""
    with pytest.raises(ChainModeViolation) as exc:
        routing.resolve_table("points_chain_blocks", _ctx("internal_test"))
    assert exc.value.mode == "internal_test"
    assert "resolve_table:points_chain_blocks" in exc.value.action


# ── unsupported modes raise RoutingNotAllowed ─────────────────────────


@pytest.mark.parametrize("mode", ["dev_ready", "test", "maintenance", "incident_lockdown", "superweak"])
@pytest.mark.parametrize("logical", ["wallets", "orders", "positions", "points_ledger"])
def test_unsupported_modes_raise_routing_not_allowed(mode, logical):
    with pytest.raises(routing.RoutingNotAllowed) as exc:
        routing.resolve_table(logical, _ctx(mode))
    assert exc.value.mode == mode
    assert exc.value.logical == logical


@pytest.mark.parametrize("mode", ["dev_ready", "test", "maintenance", "incident_lockdown", "superweak"])
def test_unsupported_modes_chain_raise_chain_mode_violation(mode):
    """Chain-blocks check fires before mode-routability check."""
    with pytest.raises(ChainModeViolation):
        routing.resolve_table("points_chain_blocks", _ctx(mode))


# ── error handling ────────────────────────────────────────────────────


def test_unknown_logical_raises():
    with pytest.raises(routing.UnknownLogicalName):
        routing.resolve_table("not_a_known_table", _ctx("production"))


def test_empty_logical_raises():
    with pytest.raises(ValueError):
        routing.resolve_table("", _ctx("production"))


def test_none_ctx_raises():
    with pytest.raises(RuntimeError):
        routing.resolve_table("wallets", None)


def test_strict_mode_equality():
    """Mode strings are compared with strict equality — typos raise."""
    for spoof in ("Production", "INTERNAL_TEST", "production ", " production", ""):
        with pytest.raises(routing.RoutingNotAllowed):
            routing.resolve_table("wallets", _ctx(spoof))


# ── mode-only helper ──────────────────────────────────────────────────


def test_resolve_table_for_mode_helper():
    assert routing.resolve_table_for_mode("orders", "production") == "trading_orders"
    assert routing.resolve_table_for_mode("orders", "internal_test") == "test_shadow_orders"
    with pytest.raises(routing.RoutingNotAllowed):
        routing.resolve_table_for_mode("orders", "dev_ready")
