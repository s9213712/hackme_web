# Trading Background Engine QA Gate

Status: Phase 0 release-gate design. These checks become mandatory before
enabling server-owned trading lifecycle in production.

## Goal

Prove that trading continues correctly without any browser page acting as the
engine trigger, and prove that retries, restores, and double-worker races cannot
duplicate money-moving events.

## Mandatory Cases

1. User is not logged in and the server worker still refreshes prices.
2. Root is not logged in and the server worker still matches eligible orders.
3. User switches to another module and enabled bots can still trigger trades.
4. Every browser tab is closed and TP/SL can still trigger.
5. Borrow interest reaches its period boundary and the server worker accrues it.
6. Margin maintenance falls below the threshold and the server worker liquidates
   through the normal settlement path.
7. Worker restarts after a successful match and does not match the same order
   twice.
8. Worker restarts after interest accrual and does not charge the same period
   twice.
9. Price provider is stale/degraded and high-risk operations fail closed.
10. `maintenance` and `incident_lockdown` pause matching, bots, liquidation,
    and interest writes.
11. `internal_test` writes only shadow trading / shadow ledger state and does
    not pollute production PointsChain.
12. Root sitewide trading management shows all bot states without exposing
    extra sensitive material beyond root scope.
13. Lending-pool income can be reconciled against ledger, fills, and interest
    events.
14. Snapshot restore does not cause old jobs to replay fills, interest,
    liquidation, or bot triggers.
15. Two workers racing for the same job result in only one active lease holder.

## Required Evidence

Each QA run should preserve:

- command log
- isolated runtime root
- server mode
- job rows before and after
- job run rows
- lock rows
- price snapshots
- order/fill rows
- bot run rows
- interest events
- margin risk snapshots
- lending pool snapshots
- PointsChain or shadow ledger deltas
- audit events
- browser evidence only where the root UI itself is under test

Browser checks are supporting evidence. They are not sufficient proof that the
background engine works while browsers are closed.

## Phase Gates

### Phase 1 - fake jobs

Must prove:

- job table initialization
- lease acquisition
- expired lease takeover
- run logging
- pause/resume state
- root run-once confirmation
- no job runs in `superweak`

### Phase 2 - server-side price refresh

Must prove:

- canonical price updates continue without `/api/trading/live-price` polling
- provider failures produce degraded status
- risk-grade unusable state blocks high-risk jobs
- root status page reports last refresh and provider health

### Phase 3 - matching and TP/SL

Must prove:

- open orders match without a browser
- idempotency blocks duplicate fills
- TP/SL uses risk-grade price context
- failed matches write visible job/audit errors
- maintenance / incident lockdown pause writes

### Phase 4 - bot scan / trigger

Must prove:

- DCA, grid, workflow, and BTC_trade bridge scans are server-triggered
- cooldown and `max_runs` still hold
- risk-grade price gates high-risk bot actions
- bot audit scheduler still runs on the backend cadence
- owner/root pages only observe state and submit commands

### Phase 5 - interest and liquidation

Must prove:

- hourly interest accrual runs without user page visits
- micropoints carry is preserved
- insufficient user points capitalizes or fails according to existing service
  rules
- account-level maintenance ratio chooses the correct liquidation candidate
- liquidation writes audit and is idempotent

### Phase 6 - root UI

Must prove:

- `全站交易管理` renders worker, order, bot, TP/SL, and risk status
- `借貸交易池收支` renders pool, fee, interest, lending, and maintenance-ratio reports
- overview cards read snapshots instead of recomputing all rows synchronously
- root actions require CSRF, permission checks, confirmation where dangerous,
  and audit records

### Phase 7 - production gate

Must prove:

- stress test under concurrent users and bots
- restore consistency
- double-worker lease races
- mode transition correctness
- no production contamination from `internal_test`
- root reports reconcile with ledger/fill/event sources

## Server Mode Test Matrix

| Mode | Required QA behavior |
|---|---|
| `production` | real worker jobs can write through normal trading, settlement, and PointsChain paths |
| `internal_test` | jobs run only against shadow trading and shadow ledger state |
| `test` | jobs run only inside isolated runtime data |
| `dev_ready` | high-risk jobs are off unless explicitly using fake/dev-only configuration |
| `maintenance` | prices may be read-only; matching, bots, liquidation, and interest writes pause |
| `incident_lockdown` | read-only rescue status only; no state mutation |
| `superweak` | background trading is fully off |

## Failure Severity

Release blocker:

- duplicate fill, interest, liquidation, or bot trade after retry
- production PointsChain write from `internal_test`
- high-risk operation using stale/degraded/cached price
- job mutates trading state in paused Server Mode
- worker requires a browser page to trigger money-moving work

P1:

- root cannot see failed jobs or stuck leases
- root reports cannot reconcile to ledger/fills/events
- background price state diverges from order execution validation

P2:

- root dashboards are slow because they do heavy live aggregation
- non-critical report cards are delayed but job execution remains correct

## Suggested Test Entry Points

Existing trading validation remains useful:

```bash
python3 scripts/trading/validation/trading_exchange_validation.py --out /tmp/trading_background_validation
python3 scripts/trading/validation/trading_workflow_template_validation.py --no-download --limit 200 --out /tmp/trading_background_validation
python3 scripts/trading/probes/backtest_20000_probe.py --include-route --json-out /tmp/trading_background_validation/backtest_20000.json
```

New implementation work should add targeted tests for:

- scheduler lease acquisition and takeover
- idempotency key uniqueness
- Server Mode job policy
- shadow routing
- worker restart replay safety
- snapshot restore replay safety
- double-worker race behavior

