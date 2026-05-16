# Trading Background Engine

Status: base worker and root snapshot path implemented. The current code starts
a server-owned trading background worker, creates job / lease / run / queue /
root snapshot tables, exposes root status / pause / resume / enqueue run-once
APIs, and runs the first job set through existing trading services. Root
`report`, sitewide pools, and sitewide user positions read stored snapshots
instead of recalculating inside the root HTTP request. Deeper order, bot,
TP/SL, liquidation, and typed lending drilldowns remain staged work.

## Core Rule

Trading lifecycle must be owned by the server, not by a browser tab.

The system must keep core trading work running when:

- the user is not logged in
- root is not logged in
- the user is on another module
- every browser tab is closed

The frontend trading page may only:

- display current state
- submit user commands
- show results and warnings

The frontend trading page must not be the only trigger for:

- price refresh
- order matching
- liquidation checks
- bot scans
- take-profit / stop-loss triggers
- interest accrual
- lending pool settlement
- sitewide risk snapshots

## Background Jobs

The first server-side worker can run in-process for the Flask single-node
deployment. It should still be designed as an idempotent scheduler so a future
queue or multi-process worker can reuse the same job metadata and retry rules.

Recommended modules:

- `services/trading/background_engine.py`
- `services/trading/scheduler.py`
- `services/trading/jobs.py`
- `services/trading/settlement.py`
- `services/trading/sitewide_reports.py`

Implemented first job set:

| Job | Purpose | Suggested cadence |
|---|---|---:|
| `price_refresh` | refresh reference and risk-grade prices | 2-5s, provider-limit aware |
| `order_matching` | match open market/limit orders | 2-5s |
| `take_profit_stop_loss_scan` | trigger TP/SL rules | 2-5s |
| `bot_trigger_scan` | trigger DCA, grid, workflow, BTC_trade bridge bots | 10-30s |
| `margin_liquidation_scan` | scan cross-margin risk and liquidate when required | 10-30s |
| `interest_accrual` | accrue borrow interest and micropoints carry | 1h |
| `sitewide_metrics_refresh` | publish root-visible report, pool, and user-position snapshots | 30-60s |

Planned next job families:

| Job | Purpose | Suggested cadence |
|---|---|---:|
| `funding_or_fee_settlement` | settle fees, pool income, and funding side effects | 30-60s or event-driven |
| `risk_snapshot_refresh` | publish root-visible risk snapshots | 30-60s |
| `bot_audit_refresh` | keep existing bot audit scheduler semantics | 5-15m or current setting |

Borrow interest already uses hourly accrual, a minimum started-hour billing
window, and micropoints carry. The background engine must own that cadence so
interest is not delayed until a user opens the page.

## Idempotency

Every job must be safe to retry after crash, timeout, restart, snapshot restore,
or duplicate launch. Retrying must not cause duplicate fills, duplicate
interest charges, duplicate liquidation, or duplicate bot actions.

Each scheduled job needs:

- `job_key`
- `lease_owner`
- `lease_until`
- `last_started_at`
- `last_finished_at`
- `last_success_at`
- `last_error`
- `run_count`
- `failure_count`
- `next_run_at`

Each emitted trading event needs:

- `idempotency_key`
- `source_job_key`
- `source_job_run_id`
- `source_event_uuid`
- `server_mode_scope`
- `created_at`

Recommended idempotency key patterns:

| Event | Key pattern |
|---|---|
| Order match | `match:order:<order_uuid>:<price_snapshot_id>` |
| Interest charge | `interest:position:<position_uuid>:<period_start>` |
| Liquidation | `liquidation:position:<position_uuid>:<risk_snapshot_id>` |
| Bot run | `bot:run:<bot_uuid>:<trigger_window>` |
| TP/SL trigger | `tp_sl:position:<position_uuid>:<trigger_price_snapshot_id>` |

## Single-Node Lease Lock

hackme_web is a Flask single-node site today, so the first version does not need
a distributed queue. It still needs a lease lock because local dev, reloaders,
tests, or a bad process manager can start two workers.

Recommended table:

```sql
CREATE TABLE trading_background_locks (
    job_key TEXT PRIMARY KEY,
    lease_owner TEXT NOT NULL,
    lease_until TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    renewed_at TEXT NOT NULL
);
```

Execution sequence:

1. Attempt to acquire the job lease.
2. If the lease exists and has not expired, skip the run.
3. If the lease has expired, atomically take over.
4. Renew while long-running work continues.
5. Record run metadata and either release the lease or update `next_run_at`.

Lease ownership must be visible in root UI so a stuck lease is diagnosable
without directly editing SQLite.

## Server Mode Matrix

Background trading must obey Server Mode v2. A background job must never bypass
the same scope routing that foreground trading APIs use.

| Mode | Price update | Matching | Bots | TP/SL | Liquidation | Interest | Root UI |
|---|---|---|---|---|---|---|---|
| `production` | on | on | on | on | on | on | on |
| `internal_test` | shadow only | shadow only | shadow only | shadow only | shadow only | shadow only | on |
| `test` | isolated/fake | isolated/fake | off or fake | fake | fake | fake | on |
| `dev_ready` | optional fake | off by default | off | off | off | off | root only |
| `maintenance` | read-only | paused | paused | paused | paused | paused | root status only |
| `incident_lockdown` | read-only | paused | paused | paused | paused | paused | root rescue only |
| `superweak` | off | off | off | off | off | off | off |

The `internal_test` rule is strict: tester activity must route to
`test_shadow_*` tables and shadow ledger paths. A background job must not
silently write production wallets, production orders, production positions, or
PointsChain.

## Safety Requirements

The background worker is not a second trading engine. It must call existing
safety services and must not write around them.

Forbidden:

- directly updating wallet balances
- directly editing PointsChain / `points_ledger`
- directly mutating margin positions outside settlement services
- matching orders without revalidating price and account state
- running bots without risk-grade price checks
- using cached, stale, degraded, or synthetic prices for high-risk operations

Required before high-risk writes:

- re-fetch or verify risk-grade price
- check provider health and freshness
- check market enabled state
- check trading pause, safe mode, and circuit breakers
- check user balance, frozen balance, and margin requirements
- route writes through PointsChain or shadow ledger according to mode
- write structured audit events
- persist idempotency keys
- fail closed on unavailable risk-grade price, exhausted lending pool, or
  unverified PointsChain state

Reference prices may remain available for display while risk-grade operations
are paused.

## Implemented API Surface

Background engine status:

- `GET /api/root/trading/background/status`
- `POST /api/root/trading/background/pause`
- `POST /api/root/trading/background/resume`
- `POST /api/root/trading/background/run-once`

These routes are root-only, CSRF protected where state changes, and audit
root-triggered state changes.

`run-once` requires explicit confirmation:

```json
{
  "job_key": "order_matching",
  "confirm": "RUN_TRADING_JOB_ONCE"
}
```

`run-once` is enqueue-only on the root request path. A successful request
returns `202 Accepted` with a `queue_uuid` immediately; the background worker
claims and executes the queued job later. Operators should inspect
`GET /api/root/trading/background/status` for `queued_runs`, `recent_runs`, and
the snapshot metadata rather than expecting the POST response to contain the
heavy job result.

## Planned API Surface

The following routes are still planning targets for deeper drilldown pages and
should not be treated as deployed endpoints until the implementation lands:

- `GET /api/root/trading/background/jobs`
- `GET /api/root/trading/background/audit`

Sitewide root dashboards and lending pool reports are specified in:

- [TRADING_SITEWIDE_MANAGEMENT.md](TRADING_SITEWIDE_MANAGEMENT.md)
- [TRADING_LENDING_POOL_REPORTS.md](TRADING_LENDING_POOL_REPORTS.md)

## Implemented Tables

Scheduler and lease tables:

- `trading_background_jobs`
- `trading_background_locks`
- `trading_background_job_runs`
- `trading_background_job_queue`
- `trading_root_snapshots`

## Planned Snapshot Tables

The generic `trading_root_snapshots` table is the first deployed root report
cache. Typed snapshot and rollup tables still needed for full sitewide
reporting:

- `trading_price_snapshots`
- `trading_sitewide_risk_snapshots`
- `trading_lending_pool_snapshots`
- `trading_margin_account_snapshots`
- `trading_bot_runtime_status`
- `trading_tp_sl_triggers`

Daily rollup/report tables:

- `trading_lending_income_daily`
- `trading_fee_income_daily`

The most important next typed tables are:

- `trading_margin_account_snapshots`
- `trading_lending_pool_snapshots`

These let deeper root UI pages read recent typed snapshots instead of
recalculating all users, orders, positions, interest, and pool income on every
request.

## Implementation Phases

Phase 0 - docs hardening: done.

- this file
- [TRADING_SITEWIDE_MANAGEMENT.md](TRADING_SITEWIDE_MANAGEMENT.md)
- [TRADING_LENDING_POOL_REPORTS.md](TRADING_LENDING_POOL_REPORTS.md)
- [TRADING_BACKGROUND_QA.md](TRADING_BACKGROUND_QA.md)
- links from `08_TRADING_ENGINE.md`, `TRADING.md`, and Server Mode v2 docs

Phase 1 - background status and server-owned base jobs: implemented.

- job table
- lease lock
- run log
- root run-once queue
- generic root report snapshot table
- server-owned `price_refresh`, `order_matching`, `take_profit_stop_loss_scan`,
  `bot_trigger_scan`, `margin_liquidation_scan`, `interest_accrual`, and
  `sitewide_metrics_refresh`
- root status / pause / resume / enqueue run-once routes

Phase 2 - root reporting hardening:

- implemented: `GET /api/admin/trading/report`,
  `GET /api/root/trading/sitewide/pools`, and
  `GET /api/root/trading/sitewide/user-positions` read
  `trading_root_snapshots`
- snapshot tables for margin accounts and lending pools
- sitewide order / bot / TP-SL / risk drilldowns
- background job audit drilldown

Phase 3 - matching and TP/SL:

- continue hardening idempotency and job-run audit for matching and TP/SL edge cases

Phase 4 - bot scan / trigger:

- expand bot runtime status snapshots and root drilldowns

Phase 5 - lending interest and liquidation:

- reconcile interest accrual, liquidation, and lending pool income at sitewide scale

Phase 6 - root UI:

- `全站交易管理`
- `借貸交易池收支`

Phase 7 - release gate:

- stress tests
- restore consistency tests
- production-mode gate
- double-worker lease race tests

## Release Blockers

The following are release blockers:

- a trade only matches when a browser trading page is open
- a bot only scans when a user is on the trading page
- interest only accrues when a borrower opens the UI
- liquidation only runs when root clicks a page button
- a worker retry duplicates fills, interest, liquidation, or bot orders
- `internal_test` background jobs write production tables or PointsChain
- `maintenance`, `incident_lockdown`, or `superweak` jobs mutate trading state
- a high-risk background operation uses stale/degraded/cached prices
