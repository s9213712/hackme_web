# Grid Trading Bot Design Report

Status: research/design only. This report is intended for a later implementation
branch and does not enable a Grid Bot in the current server.

## Executive Summary

Grid Trading Bot should be implemented as a conservative spot-only strategy
first. It should repeatedly buy near lower grid levels and sell near upper grid
levels inside a configured price range. The first version must reuse the
existing spot trading engine, PointsChain accounting, audit events, live price
fallbacks, and bot/backtest infrastructure.

The main design goal is not high-frequency execution. It is predictable,
auditable simulated trading that users can understand and root can control.

Recommended implementation branch:

```text
03c.grid_trading_bot
```

## First Version Scope

Enabled:

- Spot grid trading for `BTC/USDT` and `ETH/USDT`.
- Arithmetic and geometric grid spacing.
- Buy-low / sell-high grid pairs.
- Per-level state tracking.
- Existing trading fee calculation.
- Existing PointsChain-backed funds for normal users.
- Existing root simulated trading funds.
- Backtesting with the same Grid Bot config.
- Audit events for create, start, pause, level trigger, order success, order
  failure, and bot stop.

Disabled in the first version:

- Borrow trading grid.
- Futures grid.
- Short grid.
- PVP matching.
- Martingale auto-increase.
- External exchange execution.
- Direct wallet mutation.

## Fit With Existing System

The current trading system already contains the right primitives:

- `services/trading_engine.py`: spot order execution, price fetching,
  validation, simulated root funds, funding pool, and verification.
- `routes/economy.py`: trading APIs.
- `public/js/56-trading.js`: trading UI, wallet, bots, backtest, and chart.
- `workflows/`: system and user-created strategy templates.
- `security/trading_stress_pentest.py`: trading validation and stress testing.

Grid Bot should not create a parallel order engine. It should call the same
spot-order path used by manual spot orders. This keeps:

- fee behavior consistent.
- insufficient-funds rejection consistent.
- PointsChain writes consistent.
- audit behavior consistent.
- reset/restore verification meaningful.

## Strategy Model

User config:

```json
{
  "market": "BTC/USDT",
  "lower_price": 70000,
  "upper_price": 90000,
  "grid_count": 10,
  "spacing": "arithmetic",
  "investment_points": 1000,
  "per_grid_budget_points": 100,
  "take_profit_mode": "paired_sell",
  "stop_when_price_outside_range": true,
  "max_orders_per_scan": 3,
  "scan_interval_seconds": 30,
  "enabled": true
}
```

Derived grid levels:

```text
lower_price <= buy levels < sell levels <= upper_price
```

Each level tracks:

- level index.
- buy trigger price.
- sell trigger price.
- allocated budget.
- acquired quantity.
- state: `idle`, `bought`, `sold`, `cancelled`, `error`.
- last order ID.
- realized PnL.
- last triggered time.

State machine:

```text
idle -> bought -> sold -> idle
```

The bot buys when current price is at or below the level's buy trigger. After a
successful buy, that level waits for the paired sell trigger. When current price
is at or above the sell trigger, it sells only the quantity acquired by that
level.

## Arithmetic Vs Geometric Grid

Arithmetic spacing:

```text
step = (upper_price - lower_price) / grid_count
```

Best for stable price ranges where each absolute price step should be equal.

Geometric spacing:

```text
ratio = (upper_price / lower_price) ** (1 / grid_count)
```

Best for wide ranges where percentage movement matters more than absolute
movement.

The UI should show a preview table before saving:

- level.
- buy price.
- sell price.
- estimated fee.
- estimated gross spread.
- estimated net spread after fees.

If net spread after fees is less than or equal to zero, the config should be
rejected or require root-configured advanced override in test mode only.

## Data Model Proposal

Reuse `trading_bots` where possible:

```text
trading_bots
  bot_type = 'grid'
  market
  enabled
  config_json
  state_json
  last_run_at
  next_run_at
  last_error
```

New table:

```text
trading_grid_levels
  id
  bot_id
  level_index
  buy_price
  sell_price
  budget_points
  acquired_quantity
  state
  buy_order_id
  sell_order_id
  realized_pnl_points
  last_triggered_at
  created_at
  updated_at
```

New event table:

```text
trading_grid_events
  id
  bot_id
  level_id
  event_type
  market
  price
  quantity
  points_amount
  order_id
  error_message
  created_at
```

Events should be informational. Funds and final settlement still come from
spot fills and PointsChain.

## Execution Flow

Scanner loop:

1. Load enabled grid bots whose `next_run_at <= now`.
2. Halt if trading safe mode, PointsChain safe mode, server maintenance, or
   incident lockdown is active.
3. Fetch current execution price through the existing price service.
4. Reject stale or outlier price according to existing circuit-breaker rules.
5. Lock the bot row or acquire an application-level bot lock.
6. Scan levels in deterministic order.
7. Trigger at most `max_orders_per_scan` orders.
8. Execute orders through the existing spot order service.
9. Update level state only after order success.
10. Write audit and grid event records.
11. Update `next_run_at`.

Buy trigger:

```text
if level.state == idle and price <= level.buy_price:
    place market buy using level.budget_points
```

Sell trigger:

```text
if level.state == bought and price >= level.sell_price:
    place market sell using level.acquired_quantity
```

The first version should use market orders for triggered execution. Limit-order
grid can be added later after the scheduled limit-order matcher is proven
stable under load.

## Fund Safety

Grid Bot must never modify `points_wallets` directly.

Normal user order path:

- buy freezes/debits points through PointsChain.
- sell credits points through PointsChain.
- fees go through the existing trading fee path.
- failure rolls back the whole order.

Root order path:

- uses root simulated trading balance.
- does not affect PointsChain.
- still writes audit and trading events.

Trial trading funds:

- if trial funds are enabled, the spot engine should decide how much of the
  order uses trial funds and how much uses real points.
- Grid Bot should not implement separate trial accounting.

## Risk Controls

Required validation:

- `upper_price > lower_price`.
- `grid_count` within root-configured min/max.
- `investment_points > 0`.
- `per_grid_budget_points > 0`.
- enough available points for the initial reserved grid budget or explicitly
  choose "pay per trigger".
- estimated net spread after fees is positive.
- market is enabled.
- bot owner may trade the selected market.

Runtime guards:

- max orders per scan.
- minimum interval between scans.
- stop when price leaves configured range.
- stop on price-source failure.
- stop on PointsChain safe mode.
- stop on trading verification failure.
- stop on repeated order failures.
- stop on insufficient funds if configured as strict-reserve mode.

Suggested repeated failure rule:

```text
3 consecutive order failures -> pause bot and notify user
```

## Strict Reserve Vs Pay-Per-Trigger

Two funding modes are possible.

Strict reserve:

- reserve the full grid investment at bot start.
- safer, because all planned buys are funded.
- less flexible, because points are locked even if triggers never happen.

Pay-per-trigger:

- no full upfront reserve.
- each buy checks funds at trigger time.
- more user-friendly for small accounts.
- bot can fail later due to insufficient funds.

Recommendation for first version:

```text
default = pay-per-trigger
optional strict reserve = root-configured later
```

Reason: current users expect normal spot-like behavior and visible failure
reasons. Strict reserve can be added after wallet locking UX is clearer.

## UI Design

Add a separate Grid Bot tab under the trading bot area. Do not merge it into
Workflow Editor.

Grid Bot form:

- market selector.
- lower price.
- upper price.
- grid count.
- spacing: arithmetic/geometric.
- total budget.
- per-grid budget.
- scan interval.
- max orders per scan.
- stop outside range toggle.
- preview grid button.
- create button.

Bot card:

- enabled/paused/error state.
- current price.
- range.
- grid count.
- active bought levels.
- realized PnL.
- estimated unrealized value.
- next scan countdown.
- last error.
- pause/resume/delete buttons.

Level table:

- level.
- buy price.
- sell price.
- state.
- quantity.
- realized PnL.
- last event.

Every button must show a result message. Silent failure is not acceptable.

## Backtest Design

Backtest should use the exact same Grid Bot config.

Inputs:

- market.
- timeframe.
- start/end time.
- initial cash.
- fee percent.
- grid config.

Simulation:

1. Download historical candles through existing provider fallback.
2. Generate grid levels.
3. For each candle, use `low <= buy_price` to trigger buys and
   `high >= sell_price` to trigger sells.
4. If both buy and sell could happen in the same candle, use conservative
   ordering:
   - without lower timeframe data, assume the less favorable order.
   - record a warning: `same_candle_ambiguous`.
5. Deduct simulated fees.
6. Track cash, position quantity, realized PnL, unrealized value, and equity.

Outputs:

- total return percent.
- max drawdown percent.
- win rate.
- trade count.
- fee total.
- grid utilization.
- per-level realized PnL.
- every simulated trade.
- equity curve.
- candle provider, candle count, first/last candle time.
- ambiguity warnings.

Backtest must not mutate PointsChain, wallets, orders, or audit chain.

## Security And Abuse Considerations

Grid Bot adds automated order generation, so rate and abuse controls matter.

Controls:

- owner can only manage own bots, root can inspect all.
- normal user cannot create bots for another account.
- CSRF required for create/update/delete/start/stop.
- bot scanner must enforce root-configured global order rate.
- scanner must ignore disabled markets and disabled trading.
- input values must be numeric and finite.
- no negative price, negative budget, zero grid count, or extreme grid count.
- audit bot lifecycle and automated order events.

The trading stress pentest should add:

- create grid bot.
- invalid grid config rejection.
- repeated trigger safety.
- insufficient funds pause.
- concurrent scanner double-trigger check.
- user cannot control another user's grid bot.
- grid bot halts when PointsChain verification fails.

## Clean Implementation Phases

### G1 Schema And Validation

- Add bot type `grid`.
- Add `trading_grid_levels`.
- Add `trading_grid_events`.
- Add config parser and validator.
- Add grid preview function.
- Unit-test invalid config rejection.

### G2 Backend Execution

- Add scanner entry for grid bots.
- Add row/application lock.
- Execute buy/sell through existing spot order path.
- Add audit and event logs.
- Add pause-on-repeated-failure.
- Add API endpoints for list/detail/pause/resume/delete.

### G3 Frontend

- Add Grid Bot tab.
- Add preview table.
- Add bot cards and level table.
- Add visible success/error messages.
- Add next scan countdown.

### G4 Backtest

- Add grid backtest path.
- Reuse historical candle downloader.
- Add same-candle ambiguity warning.
- Compare output with a direct local simulation test.

### G5 Tests And Docs

- Update trading stress pentest.
- Add permission tests.
- Add reset/restore consistency checks.
- Update `docs/trading/TRADING.md`.
- Move this report to `docs/research/finished/` only after implementation and
  validation are complete.

## Acceptance Criteria

First implementation can be considered complete only when:

- Grid Bot can be created, paused, resumed, deleted.
- Grid preview matches stored levels.
- Buy levels trigger exactly once until sold.
- Sell levels trigger only after paired buy.
- No duplicate order occurs under concurrent scans.
- Insufficient funds creates a clear bot error and pauses or skips according to
  config.
- All successful normal-user fund movement goes through PointsChain.
- Root simulated trades do not mutate PointsChain.
- Backtest uses downloaded historical candles and reports candle source/count.
- Trading stress pentest includes grid cases.
- Reset/restore leaves bot, level, order, wallet, and PointsChain state
  consistent.

## Open Decisions Before Coding

1. Should first version reserve the whole grid budget or pay per trigger?
   Recommendation: pay per trigger.
2. Should triggered orders be market or limit orders?
   Recommendation: market orders first, limit grid later.
3. Should users be allowed to run more than one grid bot per market?
   Recommendation: yes, but root should set a max active bot count.
4. Should grid bot use trial funds?
   Recommendation: let the existing spot engine decide, do not add grid-only
   trial accounting.
5. Should grid levels auto-recenter when price leaves range?
   Recommendation: no for first version. Pause and ask user to edit range.
