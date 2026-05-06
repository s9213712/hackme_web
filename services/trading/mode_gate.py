"""Server Mode v2 — trading-engine mode gate.

Phase 5 (boundary) of SERVER_MODE_V2_IMPLEMENTATION_PLAN.md.

The full trading-engine refactor (G-1 .. G-5: route every SQL through
resolve_table, split matching/liquidation/funding workers per mode)
is a multi-PR effort and lives in Phase 5b. This file lands the
**boundary** — the single gate that every future trading entry point
should call to refuse trading in modes that have no shadow path. The
gate is the cheapest meaningful enforcement layer until the full
refactor is in place.

Mode -> trading-allowed mapping (mirrors PROFILE_MATRIX §Mode Behavior
Matrix Trading row):

    | mode              | trading allowed | notes                       |
    |-------------------|-----------------|-----------------------------|
    | production        | yes             | real wallets / chain        |
    | internal_test     | yes (shadow)    | tester-scoped shadow tables |
    | test              | yes (isolated)  | isolated runtime             |
    | dev_ready         | NO              | trading off by default      |
    | maintenance       | NO              | trading paused              |
    | incident_lockdown | NO              | read-only                   |
    | superweak         | NO              | weakest-mode hard rule      |

Liquidation / funding-rate writes additionally restricted via dedicated
guards.
"""

from __future__ import annotations

from typing import Optional

from services.core.cache_keys import make_cache_key
from services.points_chain import ChainModeViolation
from services.server_mode.context import SmV2Context, assert_ctx
from services.server_mode.routing import resolve_table


_TRADING_MODES = {"production", "internal_test", "test"}


class TradingDisabledInMode(RuntimeError):
    """Trading is not permitted in the current mode.

    Distinct from RoutingNotAllowed (which is raised when there is no
    table routing) — TradingDisabledInMode is raised earlier, as the
    very first gate, so callers don't have to special-case the
    routing exception.
    """

    def __init__(self, mode: str, action: str = "trade"):
        self.mode = mode
        self.action = action
        super().__init__(
            f"trading {action} forbidden in mode={mode!r} — "
            "trading is enabled only in production / internal_test / test"
        )


class CrossWorldContamination(RuntimeError):
    """A trading operation tried to read or write across the
    production <-> shadow boundary.

    Raised by the worker-side liquidation / funding gates when, e.g.,
    a shadow-positions worker tries to publish to the production
    funding channel.
    """

    def __init__(self, source_mode: str, sink_mode: str, action: str):
        self.source_mode = source_mode
        self.sink_mode = sink_mode
        self.action = action
        super().__init__(
            f"cross-world contamination refused: action={action!r}, "
            f"source_mode={source_mode!r}, sink_mode={sink_mode!r}"
        )


def assert_trading_allowed(ctx: Optional[SmV2Context], action: str = "trade") -> SmV2Context:
    """Refuse if the current mode does not permit trading. Returns the
    ctx (so callers can chain).
    """
    ctx = assert_ctx(ctx)
    if ctx.mode not in _TRADING_MODES:
        raise TradingDisabledInMode(ctx.mode, action=action)
    return ctx


def assert_same_world(source_ctx: SmV2Context, sink_ctx: SmV2Context, action: str) -> None:
    """Liquidation / funding-rate workers MUST run end-to-end in the
    same mode. A shadow position can never write to a production
    wallet; a production funding tick can never be republished into
    shadow orderbooks.
    """
    source_ctx = assert_ctx(source_ctx)
    sink_ctx = assert_ctx(sink_ctx)
    if source_ctx.mode != sink_ctx.mode:
        raise CrossWorldContamination(source_ctx.mode, sink_ctx.mode, action)


def matching_orderbook_key(market: str, ctx: SmV2Context) -> str:
    """Convenience: the in-memory matching engine should never compute
    its own cache key — call this so prod and shadow orderbooks live in
    isolated namespaces from day 1, before Phase 5b lands the deeper
    matching refactor.
    """
    ctx = assert_trading_allowed(ctx, action="orderbook")
    if ctx.mode == "internal_test" and ctx.tester_id is None:
        # The cache_keys helper would raise — preempt with a clearer message.
        raise ValueError(
            "internal_test orderbook needs a tester_id on the ctx; "
            "set it before entering the matching path"
        )
    return make_cache_key("orderbook", mode=ctx.mode, tester_id=ctx.tester_id, market=market)


def funding_channel_key(market: str, ctx: SmV2Context) -> str:
    """Funding-rate publish channel name. Same isolation rules as
    matching: prod-mode publish goes to a prod channel, internal_test
    to a per-tester channel. Re-using the cache-key helper keeps the
    namespace discipline uniform.
    """
    ctx = assert_trading_allowed(ctx, action="funding_publish")
    return make_cache_key("funding", mode=ctx.mode, tester_id=ctx.tester_id, market=market)


def liquidation_target_table(ctx: SmV2Context) -> str:
    """The "where do liquidation effects land" answer. Wrapper around
    resolve_table('margin_positions', ctx) plus the trading-mode gate, so the
    liquidation worker can refuse a non-trading mode upfront.
    """
    ctx = assert_trading_allowed(ctx, action="liquidation")
    return resolve_table("margin_positions", ctx)


def liquidation_settle_table(ctx: SmV2Context) -> str:
    """Where the liquidation's settle-out effects (wallet credit/debit)
    land. resolve_table('wallets', ctx) plus gate.
    """
    ctx = assert_trading_allowed(ctx, action="liquidation_settle")
    return resolve_table("wallets", ctx)


# Re-export for callers who want a single import line.
__all__ = [
    "TradingDisabledInMode",
    "CrossWorldContamination",
    "assert_trading_allowed",
    "assert_same_world",
    "matching_orderbook_key",
    "funding_channel_key",
    "liquidation_target_table",
    "liquidation_settle_table",
    "ChainModeViolation",
]
