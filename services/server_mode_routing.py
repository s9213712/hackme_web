"""Server Mode v2 — table routing service.

Phase 2 of SERVER_MODE_V2_IMPLEMENTATION_PLAN.md.

Production code that writes to "wallets" / "orders" / "positions" /
"points_ledger" / "points_chain_blocks" must NOT hardcode the table
name. Instead it asks `resolve_table(logical, ctx)` and gets back the
table the current request is allowed to write to. The mapping:

    | logical              | production-mode    | internal_test mode    |
    |----------------------|--------------------|-----------------------|
    | wallets              | wallets            | test_shadow_wallets   |
    | orders               | trading_orders     | test_shadow_orders    |
    | positions            | trading_spot_positions | test_shadow_positions |
    | margin_positions     | trading_margin_positions | test_shadow_margin_positions |
    | points_ledger        | points_ledger      | test_shadow_ledger    |
    | points_chain_blocks  | points_chain_blocks| RoutingNotAllowed     |

Other modes (test / dev_ready / maintenance / incident_lockdown /
superweak) are out of scope for trading-domain logical names — those
modes either run in an isolated runtime (test) or have trading
disabled (dev_ready / maintenance / incident_lockdown / superweak),
so the route is rejected with RoutingNotAllowed. Callers should be
gating on mode before they get here.

Important contracts:
1. The function accepts an `SmV2Context` (or anything with a `.mode`
   attribute) and refuses None — never silently default to production.
2. `points_chain_blocks` always raises `ChainModeViolation` outside
   production (mirrors the Phase 7 service-layer guard).
3. Strict equality on mode names — typos / case mismatches raise.
"""

from __future__ import annotations

from typing import Optional

from services.points_chain import ChainModeViolation
from services.server_mode_context import SmV2Context, assert_ctx


# logical -> physical table name mappings.
LOGICAL_TO_PROD = {
    "wallets": "wallets",
    "orders": "trading_orders",
    "positions": "trading_spot_positions",
    "margin_positions": "trading_margin_positions",
    "points_ledger": "points_ledger",
    "points_chain_blocks": "points_chain_blocks",
}
LOGICAL_TO_SHADOW = {
    "wallets": "test_shadow_wallets",
    "orders": "test_shadow_orders",
    "positions": "test_shadow_positions",
    "margin_positions": "test_shadow_margin_positions",
    "points_ledger": "test_shadow_ledger",
    # points_chain_blocks intentionally NOT in this map — never routable
    # outside production. See `resolve_table` below.
}

# Modes for which non-chain logical names are routable. Anything outside
# this set triggers RoutingNotAllowed for trading-domain queries.
_ROUTABLE_MODES = {"production", "internal_test"}


class RoutingNotAllowed(RuntimeError):
    """Raised when a logical name has no valid mapping in the current mode.

    Distinct from ChainModeViolation — this exception means the *trading*
    layer (orders / positions / ledger / wallets) has no shadow target
    for the requested mode (e.g. dev_ready / maintenance / superweak).
    Callers should gate on mode before calling resolve_table.
    """

    def __init__(self, logical, mode):
        self.logical = logical
        self.mode = mode
        super().__init__(
            f"logical={logical!r} not routable in mode={mode!r} — "
            "trading is disabled or runs in an isolated runtime in this mode"
        )


class UnknownLogicalName(RuntimeError):
    """The caller asked for a logical name we don't know how to route.

    Add it to LOGICAL_TO_PROD / LOGICAL_TO_SHADOW (or both) before
    using it. We refuse rather than guessing — silently routing to a
    table we don't know about is exactly the kind of bug Phase 2 exists
    to prevent.
    """

    def __init__(self, logical):
        self.logical = logical
        super().__init__(
            f"unknown logical table name: {logical!r}; "
            f"known: {sorted(LOGICAL_TO_PROD)}"
        )


def resolve_table(logical: str, ctx: Optional[SmV2Context]) -> str:
    """Return the physical table name to write to for the current mode.

    Raises:
        ValueError if logical is empty / not a string.
        UnknownLogicalName if logical is not in the routing tables.
        ChainModeViolation if logical=='points_chain_blocks' and mode != 'production'.
        RoutingNotAllowed for any other (logical, mode) combo without a mapping.
    """
    if not isinstance(logical, str) or not logical.strip():
        raise ValueError("logical name must be a non-empty string")
    if logical not in LOGICAL_TO_PROD:
        raise UnknownLogicalName(logical)
    ctx = assert_ctx(ctx)
    mode = ctx.mode

    # PointsChain has its own dedicated guard — there is NO shadow chain.
    if logical == "points_chain_blocks":
        if mode != "production":
            raise ChainModeViolation(mode, action=f"resolve_table:{logical}")
        return LOGICAL_TO_PROD[logical]

    # Other logical names: route to prod or shadow based on mode.
    if mode == "production":
        return LOGICAL_TO_PROD[logical]
    if mode == "internal_test":
        return LOGICAL_TO_SHADOW[logical]
    raise RoutingNotAllowed(logical, mode)


def resolve_table_for_mode(logical: str, mode: str) -> str:
    """Mode-only variant. Useful in tests or when the caller already
    has just the mode string and no full ctx (e.g. background workers
    that read the mode directly).
    """
    fake_ctx = SmV2Context(mode=mode, tester_id=None, actor_role=None, request_id="-")
    return resolve_table(logical, fake_ctx)
