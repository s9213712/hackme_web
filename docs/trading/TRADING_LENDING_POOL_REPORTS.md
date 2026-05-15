# Trading Lending Pool Reports

Status: staged reporting design. Background interest and liquidation jobs have
server-side ownership, but this root reporting tab still needs snapshot tables,
daily rollups, and reconciliation views before it is an operator-ready
production page. This document complements
[TRADING_BACKGROUND_ENGINE.md](TRADING_BACKGROUND_ENGINE.md) and
[TRADING_SITEWIDE_MANAGEMENT.md](TRADING_SITEWIDE_MANAGEMENT.md).

## Location

Root UI path:

```text
root -> 交易所 -> 借貸交易池收支
```

Purpose:

- inspect lending pool assets, utilization, income, recovery, and bad debt
- reconcile fees, interest, fills, ledger writes, and pool movements
- monitor user maintenance margin ratios without opening every account
- verify hourly interest and micropoints carry behavior at sitewide scale

## A. Lending Pool Overview

Display per asset:

- `asset`
- `pool_total`
- `pool_available`
- `pool_lent`
- `pool_reserved`
- `utilization_rate`
- `base_apr`
- `utilization_apr_multiplier`
- `effective_apr`
- `interest_accrued_total`
- `interest_collected_total`
- `bad_debt_total`
- `liquidation_recovered_total`
- `updated_at`

At minimum, grouping must support:

- `POINTS` / `USDT`
- `BTC`
- `ETH`
- other enabled market assets

Current borrowing APR design is asset-group based:

- `BTC / ETH`
- `USDT / POINTS`

Reports should group by actual borrowed asset so long and short positions can be
audited under the APR group they actually use.

## B. Sitewide Fee Income

Daily/period rows:

- `date`
- `market`
- `fee_type`
- `asset`
- `fee_amount`
- `fee_points_equivalent`
- `trade_count`
- `user_count`
- `bot_trade_count`
- `manual_trade_count`

Fee types:

- `spot_trade_fee`
- `grid_trade_fee`
- `bot_trade_fee`
- `margin_open_fee`
- `margin_close_fee`
- `liquidation_fee`
- `transfer_or_future_fee_if_any`

The report should reconcile to fills, open fee micropoints, and ledger entries.
Accumulated fees stay decimal internally; reporting can show exact points, but
integer fee income is recognized only at settlement boundaries such as spot
sell, bot stop sell, margin close, or liquidation. Margin open fee is computed
from full notional. Example: using 100 points of collateral to borrow 400 points
and buy 500 points notional accrues the margin-open fee on 500 points.

## C. Sitewide Interest Income

Daily/period rows:

- `date`
- `asset`
- `borrowed_amount`
- `interest_exact_points`
- `interest_charged_points`
- `interest_carry_micropoints`
- `borrower_count`
- `position_count`
- `overdue_interest_count`
- `failed_interest_charge_count`

The report must surface:

- accrued but not yet settled `micropoints`
- integer points already settled at margin close or liquidation
- next scheduled interest time
- settlement failures, if any

This protects the current micropoints design: small principals must not be
overcharged by rounding every period up to one point.

## D. Lending, Repayment, Liquidation, And Recovery

Display by asset and period:

- `lent_out_total`
- `repaid_total`
- `currently_borrowed_total`
- `liquidated_debt_total`
- `liquidation_recovered_total`
- `bad_debt_total`
- `pool_profit_loss`

Period filters:

- today
- 7d
- 30d
- all
- custom range

Liquidation rows must include the risk-grade price context and source job run
that caused liquidation. A liquidation without a traceable risk snapshot should
be treated as a release blocker.

## E. Sitewide Maintenance Ratio Detail

Table columns:

- `user_id`
- `username`
- `margin_equity`
- `borrowed_value`
- `maintenance_requirement`
- `margin_ratio`
- `maintenance_margin_ratio`
- `risk_level`
- `open_margin_positions`
- `largest_market_exposure`
- `unrealized_pnl`
- `accrued_interest`
- `next_interest_at`
- `liquidation_price_summary`
- `last_checked_at`

Risk levels:

- `safe`
- `watch`
- `warning`
- `critical`
- `liquidation_required`

User detail drilldown:

- positions
- borrowed assets
- collateral
- interest ledger
- risk history
- liquidation history

No direct "root edit position" action belongs on this page. Any intervention
must route through a separate audited admin action and settlement service.

## Planned APIs

Lending pool reports:

- `GET /api/root/trading/lending-pool/summary`
- `GET /api/root/trading/lending-pool/assets`
- `GET /api/root/trading/lending-pool/fees`
- `GET /api/root/trading/lending-pool/interest`
- `GET /api/root/trading/lending-pool/borrowed`
- `GET /api/root/trading/lending-pool/maintenance-ratios`
- `GET /api/root/trading/lending-pool/income-statement`

These endpoints should prefer snapshot tables for overview cards and accept
filters for drilldowns:

- asset
- market
- user id
- risk level
- date range
- server mode scope

## Proposed Tables

Snapshot and rollup tables:

- `trading_lending_pool_snapshots`
- `trading_lending_income_daily`
- `trading_fee_income_daily`
- `trading_margin_account_snapshots`

Event-source tables that reports should reconcile against:

- fills
- fees
- interest events
- margin position events
- PointsChain ledger
- shadow ledger in `internal_test`
- liquidation events
- background job runs

## Reconciliation Rules

The report is not authoritative by itself. It is a root-facing projection that
must be reconcilable against the event and ledger sources.

Required reconciliation:

- fee income totals match fills and fee ledger references
- charged interest matches interest events and PointsChain/shadow ledger writes
- carry micropoints match open position state
- lending pool deltas match borrow, repayment, liquidation, and bad-debt events
- maintenance-ratio snapshots are newer than the latest risk job success
- `internal_test` reports read shadow data and never mix production ledger rows

## Release Blockers

- interest only updates when a user opens the trading page
- lending pool income cannot be reconciled to ledger/fills/events
- micropoints carry is hidden or rounded away
- production and shadow lending data are mixed
- liquidation recovery lacks a risk-grade price snapshot
- root UI recomputes full sitewide risk synchronously on every page load and
  becomes a performance bottleneck
