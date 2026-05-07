# Trading Risk Price Model

This document explains how `hackme_web` separates trading prices into
`reference price` and `risk-grade price`, how fallback/degraded states behave,
and how the root price-fusion dashboard should be interpreted.

## Price Types

### `reference price`

Use for:

- current-price display
- chart / K-line display
- general valuation
- low-risk previews

Do not use `reference price` alone for:

- financing decisions
- liquidation
- maintenance-margin enforcement
- bot risk gating
- high-risk market-order checks

### `risk-grade price`

Use for:

- financing
- liquidation
- margin maintenance
- trading limits
- bot risk checks
- formal risk-side PnL context

If `risk-grade price` is unavailable, the frontend should clearly warn users
that high-risk flows are paused. This does **not** mean the whole market has no
price; it means the system no longer trusts the price for high-risk actions.
Reference price may degrade for display, but risk-grade price must fail closed
for any settlement or execution path.

## Source Modes

Root can choose:

- fused multi-provider price
- Binance single-provider price
- root manual price

The system also may temporarily use:

- cached last-good price
- degraded fallback provider sets

### Important rule

Having “a price” is not the same thing as having a price that is acceptable for
high-risk use.

`manual_root`, cached, stale, degraded, fallback, and synthetic test-provider
contexts can still be useful as `reference price`, but they are marked
`risk_grade_usable=false`.

By contrast, some fused-price conditions are only `warning-only`:

- one provider has incomplete coverage
- a small number of providers are auto-excluded, but enough healthy providers
  remain
- weight-cap normalization is applied successfully

In those cases the system may still keep:

- `risk_grade_usable=true`
- green trading-page status
- high confidence for risk-grade price

So warning-only diagnostics must not be conflated with actual degraded price
health.

## Fusion Dashboard Meaning

The root dashboard showing provider weights does **not** represent the real
global market share of those exchanges.

It represents:

- the effective provider weighting used by this system
- under the current sampling depth
- coverage thresholds
- provider health checks
- caps and exclusion rules

So the correct interpretation is:

- “current provider usage weight inside this system”

not:

- “true global market liquidity share”

## `auto_depth` vs `manual_weights`

### `auto_depth`

The backend scores providers using order-book depth and health checks. This is
useful for adaptive reference pricing, but the result is still bounded by:

- available provider depth levels
- coverage thresholds
- stale/deviation filters
- provider caps

### `manual_weights`

Root manually assigns provider percentages. If the configuration is invalid,
the engine falls back to `auto_depth` and marks the condition explicitly.

## Degraded / Fallback Behavior

When the engine detects a degraded price state, the UI should not imply that
all trading is down.

The correct user-facing meaning is:

- high-risk actions pause
- general limit-order submission may still be available
- but limit orders still go through backend validation for balance, market
  status, and risk controls

Recommended wording:

> 目前風控級價格不可用，已暫停市價單與高風險交易；限價單仍可使用

Operationally, this means:

- market orders can be blocked
- financing can be blocked
- liquidation/risk automation can be blocked
- bot high-risk paths can be blocked

while:

- reference display remains available
- charts remain available
- normal limit-order flow can remain open if backend checks still pass

### What should actually trigger low trust

Low-trust / yellow-state behavior should be reserved for conditions such as:

- provider transport fallback
- stale WebSocket/provider input
- conservative mode (`risk_grade_provider_count` too low)
- cached/manual/synthetic test price paths
- abnormal live-price movement that trips backend guardrails

It should **not** be triggered merely because a provider had partial depth
coverage while the remaining healthy providers still produced a valid
`risk-grade price`.

## API Fields To Trust

Important trading APIs now expose structured metadata:

- `price_type`
- `source`
- `confidence`
- `stale`
- `degraded`
- `provider_count`
- `high_risk_blocked`
- `risk_grade_usable`
- `reference_price_context`
- `risk_grade_price_context`
- provider transport state such as
  - `connected`
  - `fallback`
  - `last_update_at`
  - `exclusion_reason`
  - `transport_state`

Clients should use these fields instead of inferring price trust from raw
numbers alone.

## Developer Notes

- `GET /api/trading/live-price` is a read-refresh endpoint, not a perfectly
  side-effect-free probe. It can refresh runtime market price cache state.
- WebSocket ticker/depth is provider input only; it does not replace the
  `reference price` / `risk-grade price` trust split.
- Synthetic test providers may exist for test harnesses, but production root
  settings must not expose them as normal price-source configuration.

## Related Docs

- [08_TRADING_ENGINE.md](../08_TRADING_ENGINE.md)
- [TRADING.md](TRADING.md)
- [TRADING_BOT_AUDIT.md](TRADING_BOT_AUDIT.md)
- [API_REFERENCE.md](../API_REFERENCE.md)
