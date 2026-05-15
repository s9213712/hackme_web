# Root Sitewide Trading Management

Status: background-engine health controls are partially implemented; the full
sitewide management tab is still staged. Root can already inspect background
job status and run audited pause / resume / run-once actions. Order, bot,
TP/SL, and margin-risk drilldowns still need snapshot-backed pages before they
are suitable for production operations.

## Location

Root UI path:

```text
root -> 交易所 -> 全站交易管理
```

Purpose:

- supervise the trading background engine
- inspect sitewide orders, bots, TP/SL, liquidation, and risk state
- pause/resume background work through audited root actions
- diagnose stuck jobs, stale prices, failed bot scans, and lending risk

Root UI is an observability and supervision surface. It must not become a
shortcut that mutates user balances or positions directly.

## A. Background Engine Health

Display:

- `worker_status`
- `current_server_mode`
- `last_price_refresh_at`
- `last_order_match_at`
- `last_bot_scan_at`
- `last_liquidation_scan_at`
- `last_interest_accrual_at`
- `last_success_at`
- `last_error`
- `paused_reason`
- `risk_grade_price_status`
- `provider_health`
- active lease owner and lease expiry per job
- queue delay / next run time per job

Status lights:

| Light | Meaning |
|---|---|
| green | normal |
| yellow | degraded provider, partial failure, or delayed queue |
| red | stopped, stuck lease, unusable risk-grade price, or failed high-risk scan |
| gray | paused by Server Mode v2 or explicit root pause |

Root actions:

- pause background engine
- resume background engine
- run one named job once with explicit confirmation
- inspect recent job runs and audit records

All actions must use existing root permission checks, CSRF protection, and
audit logging. No action may directly edit database rows.

## B. Sitewide Orders

Display:

- `open_orders_count`
- `market_orders_pending`
- `limit_orders_open`
- `orders_matched_last_24h`
- `orders_cancelled_last_24h`
- `failed_matches_last_24h`
- `stale_orders_count`

Filters:

- market
- user
- order type
- side
- status
- server mode scope

Order rows should expose enough state to debug matching without leaking more
than root already has permission to see:

- order UUID
- owner user id / username
- market
- side
- order type
- requested quantity / notional
- limit price
- freeze state
- last matching attempt
- last error
- source job run id

## C. Sitewide Bots

Display all bot families:

- DCA
- grid
- workflow
- BTC_trade prediction bridge
- future planned bots

Suggested columns:

- `bot_uuid`
- `owner_user_id`
- `owner_username`
- `bot_type`
- `market`
- `enabled`
- `audit_status`
- `last_scan_at`
- `last_trigger_at`
- `last_trade_at`
- `next_scan_at`
- `run_count`
- `max_runs`
- `realized_pnl`
- `unrealized_pnl`
- `total_fee_paid`
- `failure_count`
- `last_error`
- `risk_status`
- `server_mode_scope`

Root actions:

- pause bot
- resume bot
- force re-audit
- view recent trigger records
- view recent fills
- view risk-control reason

Root actions must call the existing service/API layer and must write audit
events. They must not edit bot rows directly.

## D. TP/SL And Risk Triggers

Display:

- `active_tp_sl_orders`
- `triggered_tp_last_24h`
- `triggered_sl_last_24h`
- `failed_tp_sl_triggers`
- `positions_without_tp_sl`
- `positions_near_liquidation`

Trigger rows:

- position UUID
- owner
- market
- trigger type
- trigger price snapshot
- risk-grade price context
- idempotency key
- status
- last error
- source job run id

High-risk trigger failures must be visible as red/yellow states instead of
being silently swallowed by the worker.

## E. Sitewide Margin Risk Overview

The sitewide management tab may include a compact overview and link to the
dedicated lending pool report.

Display:

- `user_id`
- `username`
- `total_margin_equity`
- `total_margin_debt`
- `maintenance_margin_ratio`
- `margin_ratio`
- `risk_level`
- `positions_count`
- `near_liquidation_count`
- `liquidation_required`
- `last_risk_check_at`

Risk levels:

- `safe`
- `watch`
- `warning`
- `critical`
- `liquidation_required`

Root may drill into a user detail page that shows:

- positions
- borrowed assets
- collateral
- interest ledger
- risk history
- liquidation history

Do not provide a direct "edit user position" shortcut. Any manual intervention
must be a separate admin action with explicit confirmation, audit logging, and
service-layer settlement semantics.

## Implemented Background APIs

- `GET /api/root/trading/background/status`
- `POST /api/root/trading/background/pause`
- `POST /api/root/trading/background/resume`
- `POST /api/root/trading/background/run-once`

## Planned Sitewide APIs

These routes describe the intended drilldown surface. Do not document them as
available to operators until the matching route handlers and snapshot tables
exist.

- `GET /api/root/trading/sitewide/summary`
- `GET /api/root/trading/sitewide/orders`
- `GET /api/root/trading/sitewide/bots`
- `GET /api/root/trading/sitewide/tp-sl`
- `GET /api/root/trading/sitewide/margin-risk`
- `GET /api/root/trading/sitewide/user/<user_id>`

- `GET /api/root/trading/background/jobs`
- `GET /api/root/trading/background/audit`

## Snapshot Data Sources

Preferred root UI sources:

- `trading_background_jobs`
- `trading_background_job_runs`
- `trading_sitewide_risk_snapshots`
- `trading_margin_account_snapshots`
- `trading_bot_runtime_status`
- `trading_tp_sl_triggers`

The UI should read recent snapshots for dashboard cards and only run heavier
queries when root opens a drilldown table or exports a report.

## Security Notes

- root-only
- CSRF required for all write actions
- audit required for all pause/resume/run-once/bot actions
- no direct wallet or PointsChain mutation
- no bypass of Server Mode v2 routing
- no production data writes in `internal_test`
- no high-risk operations when risk-grade price is unusable
