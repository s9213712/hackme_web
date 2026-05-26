# Finance Hot Path Optimization Design

Status: design only. Do not implement from this document until reviewed.

## Goal

Make `mixed_finance_5k` and later `50K full-load` measure real system throughput,
not avoidable architectural bottlenecks.

Approved route:

1. read-only hot-path inventory
2. index plan
3. durable materialized wallet balances
4. asset overview read model
5. market price snapshots outside writer locks
6. 1K micro baseline
7. 5K pure-finance baseline
8. 50K full-load only after 5K is meaningful

This is not a Redis rewrite and not a DB split. The financial source of truth
remains append-only ledger/event tables.

## Current Evidence

The isolated pure-finance run was stopped before a complete 5K report, but the
partial run is enough to identify false bottlenecks:

| Phase | Observation |
| --- | --- |
| `c1 500/500` | no unexpected failures, about 3.47 ops/s by the script progress line |
| `c4 750/750` | no unexpected failures, about 2.10 ops/s by the script progress line |
| `c8 750/1000` | unexpected failures appeared, throughput around 1.94 ops/s |

This is reverse scaling: more concurrency made throughput worse. CPU was not
fully saturated. The likely constraint is SQLite single writer plus repeated
full replay/read work inside hot request paths.

Observed DB shape in the interrupted isolated run:

| Table | Rows | Approx table bytes | Approx bytes/row |
| --- | ---: | ---: | ---: |
| `points_ledger` | 4,020 | 8.8 MB | 2.1 KB |
| `points_chain_audit_logs` | 4,217 | 5.6 MB | 1.3 KB |
| `points_economy_events` | 2,331 | 2.4 MB | 1.0 KB |
| `notifications` | 4,873 | 1.7 MB | 349 B |
| `points_chain_transfer_requests` | 1,585 | 848 KB | 535 B |
| `trading_orders` | 231 | 64 KB | 284 B |
| `trading_fills` | 231 | 36 KB | 160 B |
| `trading_margin_positions` | 87 | 20 KB | 235 B |

The highest write amplification is intentional financial/audit durability, but
some read paths replay or scan this data too often.

## Non-Negotiable Guardrails

- Do not use Redis, TTL, or file cache as financial truth.
- Do not split `finance.db` in this phase.
- Do not async financial commits.
- Do not remove audit rows, economy events, transfer requests, bridge events, or
  trading fills.
- Do not call external price APIs while holding SQLite `BEGIN IMMEDIATE`.
- Do not let `/api/trading/asset-overview` call full `user_dashboard()`.
- Do not replay all `points_ledger` for every wallet balance check.

## 1. Hot-Path Query Inventory

### PointsChain Wallet Balance

Hot callers:

- `submit_wallet_transaction()`
- `spend_points()`
- trading funding and collateral flows through wallet helpers
- final integrity checks and wallet pages

Current hot helper:

```text
_wallet_identity_available_for_address()
  -> _wallet_identity_balances_for_user(include_pending=True)
       -> SELECT * FROM points_ledger
          WHERE status='confirmed' AND chain_branch=?
          ORDER BY id ASC
       -> parse public_metadata_json for wallet_flow_snapshot
       -> query pending transfer requests
```

Problem:

- For users with multiple wallet identities, balance lookup is O(total ledger
  rows in branch), not O(user wallets).
- `public_metadata_json` parse is repeated for each lookup.
- The current one-wallet fast path helps only users with exactly one wallet.
  Cold-wallet-heavy finance tests still fall back to full replay.

Measured on the interrupted isolated DB:

| Operation | Rows | Time |
| --- | ---: | ---: |
| fetch confirmed branch ledger | 4,020 | 24.8 ms |
| parse `public_metadata_json` for rows | 4,020 | 23.5 ms |

At 50K rows this becomes structural, not incidental.

### PointsChain Bridge and Transfer Reconcile

Hot callers:

- `list_wallet_transactions()`
- root explorer/report
- confirmed cold-to-deposit reconcile
- deposit bridge credit idempotency

Important query patterns:

```sql
SELECT *
FROM points_chain_bridge_events
WHERE chain=? AND chain_tx_hash=?
LIMIT 1;

SELECT r.*
FROM points_chain_transfer_requests r
JOIN points_chain_deposit_addresses d
  ON LOWER(r.destination_wallet_address)=LOWER(d.address)
 AND d.status IN ('active','rotated')
WHERE r.status='confirmed'
ORDER BY r.id ASC
LIMIT ?;

SELECT COALESCE(SUM(amount_points + fee_points), 0)
FROM points_chain_transfer_requests
WHERE source_wallet_address=? AND chain_branch=? AND status='pending';
```

The pending outgoing query already has a useful index. Bridge chain hash and
deposit reconcile need better support.

### Trading Dashboard and Asset Overview

Current endpoint:

```text
/api/trading/asset-overview
  -> trading_service.user_dashboard(user_id)
  -> build_asset_overview(payload)
```

`user_dashboard()` loads far more than the overview needs:

- enabled markets plus price contexts
- spot positions and realized maps
- futures positions
- margin positions with risk payload
- wallet onboarding status
- bot order maps
- raw orders
- fills and PnL maps
- margin trade records
- bots and bot runs
- funding, settings, funding pool, volume stats

Observed access log:

- 20 `GET /api/trading/asset-overview` calls returned about 718 KB total.
- Frontend caller only uses `json.overview`.

This endpoint should be a read model, not a full dashboard proxy.

### Trading Orders, Fills, Bots, Grid Bots

Current full dashboard and bot pages use:

```sql
SELECT * FROM trading_orders WHERE user_id=? ORDER BY id DESC LIMIT 50;
SELECT * FROM trading_fills WHERE user_id=? ORDER BY id DESC LIMIT 50;
SELECT * FROM trading_margin_positions WHERE user_id=? ORDER BY id DESC LIMIT 50;
SELECT * FROM trading_bots WHERE user_id=? ORDER BY id DESC LIMIT 50;
SELECT * FROM trading_bot_runs WHERE user_id=? ORDER BY id DESC LIMIT 50;
SELECT * FROM trading_grid_orders WHERE user_id=? AND trading_order_uuid=?;
```

These were full table scans in the interrupted DB.

### Price Fetch Inside Writer Lock

Current trading write flow:

```text
place_order()
  -> BEGIN IMMEDIATE
  -> _current_market_price_points()
       -> live provider or fused provider may fetch external HTTP/orderbook
  -> write order/fill/ledger

open_margin_position()
  -> BEGIN IMMEDIATE
  -> _current_market_price_points()
  -> write margin/ledger/fund events
```

External price fetch under writer lock is unacceptable. A slow Binance/fused
provider request serializes unrelated financial writes.

### Notifications and Audit

Wallet transfers synchronously create notifications and audit logs in the same
main DB transaction. This durability is intentional, but it increases writer
hold time and table growth.

Do not remove them in this phase. Optimize only with indexes and read-path
changes. A future notification outbox can be considered only if the financial
event is already durable and idempotent before notification delivery.

## 2. Low-Risk Index Plan

The following index list is low-risk because it does not change semantics. It
targets observed scans and does not replace correctness checks.

### Trading Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_trading_orders_user_id_desc
ON trading_orders(user_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_trading_orders_status_market_id
ON trading_orders(status, market_symbol, id);

CREATE INDEX IF NOT EXISTS idx_trading_fills_user_id_desc
ON trading_fills(user_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_trading_fills_order_id
ON trading_fills(order_id);

CREATE INDEX IF NOT EXISTS idx_trading_spot_pnl_user_fill
ON trading_spot_realized_pnl(user_id, fill_id);

CREATE INDEX IF NOT EXISTS idx_trading_margin_user_id_desc
ON trading_margin_positions(user_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_trading_margin_user_status_id
ON trading_margin_positions(user_id, status, id DESC);

CREATE INDEX IF NOT EXISTS idx_trading_bots_user_id_desc
ON trading_bots(user_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_trading_bots_enabled_market_id
ON trading_bots(enabled, market_symbol, id);

CREATE INDEX IF NOT EXISTS idx_trading_bot_runs_user_id_desc
ON trading_bot_runs(user_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_trading_bot_runs_user_order
ON trading_bot_runs(user_id, order_uuid);

CREATE INDEX IF NOT EXISTS idx_trading_grid_bots_user_id_desc
ON trading_grid_bots(user_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_trading_grid_orders_user_order
ON trading_grid_orders(user_id, trading_order_uuid);

CREATE INDEX IF NOT EXISTS idx_trading_grid_orders_bot_status_level
ON trading_grid_orders(grid_bot_id, status, level_index);
```

### PointsChain and Notification Indexes

Some PointsChain indexes were already added in the current branch. Additional
candidate indexes for the first implementation batch:

```sql
CREATE INDEX IF NOT EXISTS idx_points_ledger_branch_user_id_desc
ON points_ledger(chain_branch, user_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_points_ledger_user_action_status_created
ON points_ledger(user_id, action_type, status, created_at);

CREATE INDEX IF NOT EXISTS idx_points_bridge_chain_tx_full
ON points_chain_bridge_events(chain, chain_tx_hash);

CREATE INDEX IF NOT EXISTS idx_points_deposit_lower_status
ON points_chain_deposit_addresses(LOWER(address), status);

CREATE INDEX IF NOT EXISTS idx_points_transfer_status_dest_id
ON points_chain_transfer_requests(status, destination_wallet_address, id);

CREATE INDEX IF NOT EXISTS idx_points_transfer_sender_id_desc
ON points_chain_transfer_requests(sender_user_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_points_transfer_recipient_id_desc
ON points_chain_transfer_requests(recipient_user_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_notifications_once_lookup
ON notifications(user_id, type, title, body, is_read);
```

`idx_points_bridge_chain_tx_full` overlaps the existing partial unique index.
The first attempt must be a query rewrite that lets SQLite use the existing
partial unique index, for example:

```sql
WHERE chain = ?
  AND chain_tx_hash = ?
  AND chain_tx_hash <> ''
```

Only add `idx_points_bridge_chain_tx_full` if `EXPLAIN QUERY PLAN` still scans
after that rewrite.

### Batch Scope

The index list above is a candidate inventory, not permission to add every index
in one migration. Each extra index increases write cost, so the first
implementation batch should be intentionally small.

Batch A1 core indexes:

- `idx_trading_orders_user_id_desc`
- `idx_trading_fills_user_id_desc`
- `idx_trading_margin_user_id_desc`
- `idx_trading_bots_user_id_desc`
- `idx_trading_bot_runs_user_id_desc`
- `idx_trading_grid_orders_user_order`
- `idx_points_ledger_branch_user_id_desc`
- bridge chain tx query rewrite that uses the existing partial unique index

Batch A1 optional only if the matching query still appears in the 1K micro
baseline:

- `idx_points_bridge_chain_tx_full`, only if the bridge chain tx query rewrite
  still scans
- `idx_points_deposit_lower_status`
- `idx_points_transfer_status_dest_id`
- `idx_points_transfer_sender_id_desc`
- `idx_points_transfer_recipient_id_desc`
- `idx_notifications_once_lookup`, only if write-cost measurement shows the
  large text index is acceptable

Batch A2 candidates after measuring write cost:

- `idx_trading_orders_status_market_id`
- `idx_trading_fills_order_id`
- `idx_trading_spot_pnl_user_fill`
- `idx_trading_margin_user_status_id`
- `idx_trading_bots_enabled_market_id`
- `idx_trading_bot_runs_user_order`
- `idx_trading_grid_bots_user_id_desc`
- `idx_trading_grid_orders_bot_status_level`

Do not add an index that includes `notifications.body` in Batch A1 core. If
notification dedupe remains hot, prefer a later schema change that adds a short
`notification_dedupe_key` and indexes `(user_id, type, notification_dedupe_key)`.

### EXPLAIN QUERY PLAN Before and After

These before/after plans were measured on a copy of the interrupted isolated DB.
The "after" side was measured on `/tmp/hackme_finance_analysis_indexes.db`, not
the live runtime DB.

| Query | Before | After |
| --- | --- | --- |
| recent user orders | `SCAN trading_orders` | `SEARCH trading_orders USING INDEX idx_trading_orders_user_id_desc (user_id=?)` |
| recent user fills | `SCAN trading_fills` | `SEARCH trading_fills USING INDEX idx_trading_fills_user_id_desc (user_id=?)` |
| open orders | `SCAN trading_orders` | `SEARCH trading_orders USING INDEX idx_trading_orders_status_market_id (status=?)` |
| recent user bots | `SCAN trading_bots` | `SEARCH trading_bots USING INDEX idx_trading_bots_user_id_desc (user_id=?)` |
| recent bot runs | `SCAN trading_bot_runs` | `SEARCH trading_bot_runs USING INDEX idx_trading_bot_runs_user_id_desc (user_id=?)` |
| grid order by user/order uuid | `SCAN trading_grid_orders` | `SEARCH trading_grid_orders USING INDEX idx_trading_grid_orders_user_order (user_id=? AND trading_order_uuid=?)` |
| user ledger branch recent | `SEARCH points_ledger USING INDEX idx_points_ledger_branch_id (chain_branch=?)` | `SEARCH points_ledger USING INDEX idx_points_ledger_branch_user_id_desc (chain_branch=? AND user_id=?)` |
| notification once lookup | `SEARCH notifications USING INDEX idx_notifications_user_read (user_id=? AND is_read=?)` | `SEARCH notifications USING COVERING INDEX idx_notifications_once_lookup (user_id=? AND type=? AND title=? AND body=? AND is_read=?)` |
| bridge chain tx lookup | `SCAN points_chain_bridge_events` | `SEARCH points_chain_bridge_events USING INDEX idx_points_bridge_chain_tx_full (chain=? AND chain_tx_hash=?)` |
| deposit reconcile | `SCAN d`, auto partial index on `r.status`, temp sort | indexed search on `r.status` and expression index on deposit address |

The open-orders and deposit-reconcile queries still show temp B-tree sorting.
That is acceptable for the first batch; if they remain hot after 5K, rewrite the
queries to use keyset scans or narrower status-specific loops.

Important limitation: `idx_points_ledger_branch_user_id_desc` improves recent
user ledger lookups, but it does not solve the largest wallet-balance bottleneck.
`_wallet_identity_balances_for_user()` currently replays all confirmed ledger
rows in a branch and parses `public_metadata_json`; that O(total branch ledger)
path is solved only by the Batch C durable materialized wallet balance work.

## 3. Durable Materialized Wallet Balance Design

### Purpose

Replace per-request full `points_ledger` replay for wallet identity balances
with a durable, derived balance table updated in the same transaction as the
financial event.

This is not financial truth. It is durable derived operational state with a
replay/verify path. It must not be TTL-based, disposable, eventually updated
outside the financial transaction, or treated like Redis/cache storage.

### Proposed Table

```sql
CREATE TABLE IF NOT EXISTS points_wallet_identity_balances (
    chain_branch TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    wallet_identity_id INTEGER,
    wallet_type TEXT NOT NULL DEFAULT '',
    custody_mode TEXT NOT NULL DEFAULT '',
    available_points INTEGER NOT NULL DEFAULT 0,
    frozen_points INTEGER NOT NULL DEFAULT 0,
    pending_outgoing_points INTEGER NOT NULL DEFAULT 0,
    last_ledger_id INTEGER NOT NULL DEFAULT 0,
    last_transfer_request_id INTEGER NOT NULL DEFAULT 0,
    last_bridge_event_id INTEGER NOT NULL DEFAULT 0,
    balance_hash TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (chain_branch, wallet_address),
    CHECK (available_points >= 0),
    CHECK (frozen_points >= 0),
    CHECK (pending_outgoing_points >= 0)
);

CREATE INDEX IF NOT EXISTS idx_points_wallet_identity_balances_user
ON points_wallet_identity_balances(chain_branch, user_id, wallet_type, wallet_address);
```

Optional state table:

```sql
CREATE TABLE IF NOT EXISTS points_wallet_identity_balance_state (
    chain_branch TEXT PRIMARY KEY,
    replay_height INTEGER NOT NULL DEFAULT 0,
    last_ledger_hash TEXT NOT NULL DEFAULT '',
    last_transfer_request_id INTEGER NOT NULL DEFAULT 0,
    last_bridge_event_id INTEGER NOT NULL DEFAULT 0,
    wallet_root_hash TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
```

### Update Rules

All updates occur inside the same SQLite transaction that writes the financial
source event.

Ledger-driven deltas:

| Ledger direction | Materialized update |
| --- | --- |
| `credit`, `transfer_in` | destination `available_points += amount` |
| `debit`, `transfer_out`, `reverse` | source `available_points -= amount` |
| `freeze` | source `available_points -= amount`, `frozen_points += amount` |
| `unfreeze` | source `available_points += amount`, `frozen_points -= amount` |

Pending request deltas:

| Request stage | Materialized update |
| --- | --- |
| pending pc0/cold outgoing inserted | source `pending_outgoing_points += amount + fee` |
| pending request finalized | source `pending_outgoing_points -= amount + fee`, then apply ledger deltas |
| pending request failed/refunded | source `pending_outgoing_points -= amount + fee` |

Read API:

```text
spendable = available_points - pending_outgoing_points
display_frozen = frozen_points + pending_outgoing_points
```

RC1 state-machine rule:

- `pending_outgoing_points` is the pre-freeze for ordinary outgoing transfers.
- `frozen_points` is only for sanctions, admin freezes, disputes, and
  non-transfer locks.
- Ordinary pending transfers must not also write `frozen_points`.
- Pending submit leaves `available_points` unchanged and increases
  `pending_outgoing_points`.
- Confirm/prove decreases `pending_outgoing_points`, then applies the confirmed
  ledger debit/credit.
- Fail/refund decreases `pending_outgoing_points` and leaves `available_points`
  unchanged.

This avoids double-freezing:

```text
available already debited
plus spendable subtracts pending_outgoing
= user is charged twice
```

The helper `_wallet_identity_available_for_address()` should read this table
when the derived state is valid. It may fall back to replay only if:

- materialized row missing
- balance state replay height is behind a committed ledger id
- verify detects mismatch
- server is in recovery/safe mode

### Atomicity

The materialized update must be in the same transaction as:

- `points_ledger` insert
- `points_chain_transfer_requests` insert/update
- `points_chain_bridge_events` credit status change

Do not use async update for this table.

## 4. Materialized Balance Rebuild and Verify

### Rebuild

Add a rebuild service method:

```text
rebuild_wallet_identity_balances(conn, chain_branch)
```

Inputs:

- `points_wallet_identities`
- `points_ledger`
- `points_chain_transfer_requests`
- `points_chain_bridge_events` only where needed for bridge-linked state

Algorithm:

1. Load active and pending-backup wallet identities.
2. Initialize every address to zero.
3. Replay `points_ledger` ordered by `id ASC`, using flattened columns if
   available, otherwise `wallet_flow_snapshot`.
4. Apply pending outgoing requests by source address.
5. Validate no negative available/frozen/pending values.
6. Compute per-row `balance_hash`.
7. Compute `wallet_root_hash` from sorted rows.
8. Replace materialized rows for the branch in one transaction.

### Verify

Add a verify service method:

```text
verify_wallet_identity_balances(conn, chain_branch, mode='sample'|'full')
```

Modes:

- `sample`: compare N hot wallet addresses, recent changed addresses, and any
  address touched by pending requests.
- `full`: replay all rows and compare every address.

Checks:

- materialized total equals replay total per address
- pending outgoing matches pending transfer request sums
- `last_ledger_id` is not ahead of actual ledger
- `wallet_root_hash` matches rebuilt root
- no negative balances

Recovery behavior:

- In dev/test, full rebuild can be run automatically if only derived operational
  state mismatch exists.
- In production, mismatch opens incident/safe-mode recommendation unless root
  explicitly runs a recovery action.

## 5. Asset Overview Lightweight Read Model

### Current Issue

`/api/trading/asset-overview` calls `user_dashboard()` and then uses only the
overview subset. This endpoint must stop loading full orders/fills/bots.

### Proposed Service Method

```text
trading_service.user_asset_overview(user_id)
```

Required output fields should match the existing `overview` object:

```json
{
  "available_points": 0,
  "locked_points": 0,
  "spot_market_value_points": 0,
  "margin_position_equity_points": 0,
  "unrealized_pnl_points": 0,
  "accrued_interest_points": 0,
  "total_equity_points": 0,
  "open_spot_positions": 0,
  "open_margin_positions": 0,
  "market_count": 0,
  "low_confidence_price_count": 0,
  "confidence_note": "價格可信度只作風險提示，不阻擋積分交易。"
}
```

Allowed queries:

- `trading_sim_accounts` by user id
- aggregate `trading_spot_positions` by user id
- aggregate `trading_margin_positions` by user id/status
- `trading_markets` plus `market_price_snapshots` for market count and
  confidence count
- optionally `trading_trial_credits` if UI needs it later

Forbidden in this endpoint:

- loading recent orders
- loading recent fills
- loading bot lists
- loading bot runs
- loading margin trade records
- wallet onboarding scan
- external price fetch

Route behavior:

```text
GET /api/trading/asset-overview
  -> user_asset_overview(user_id)
  -> {"ok": true, "overview": overview}
```

The current frontend only uses `json.overview`. Keep a compatibility placeholder
only if a regression test shows other code expects `json.trading`.

## 6. Market Price Snapshots Outside Writer Lock

### Purpose

Move provider IO and fused price calculation out of `BEGIN IMMEDIATE` financial
write transactions.

### Proposed Table

```sql
CREATE TABLE IF NOT EXISTS trading_market_price_snapshots (
    market_symbol TEXT PRIMARY KEY,
    reference_price_points REAL,
    risk_grade_price_points REAL,
    resolved_source TEXT NOT NULL DEFAULT '',
    price_health TEXT NOT NULL DEFAULT 'unknown',
    confidence TEXT NOT NULL DEFAULT 'unknown',
    reference_provider_count INTEGER NOT NULL DEFAULT 0,
    risk_grade_provider_count INTEGER NOT NULL DEFAULT 0,
    high_risk_blocked INTEGER NOT NULL DEFAULT 1 CHECK (high_risk_blocked IN (0,1)),
    high_risk_block_reason TEXT NOT NULL DEFAULT '',
    degraded INTEGER NOT NULL DEFAULT 0 CHECK (degraded IN (0,1)),
    stale INTEGER NOT NULL DEFAULT 0 CHECK (stale IN (0,1)),
    fallback INTEGER NOT NULL DEFAULT 0 CHECK (fallback IN (0,1)),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    fetched_at TEXT,
    expires_at TEXT,
    stale_until TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trading_market_price_snapshots_health
ON trading_market_price_snapshots(price_health, confidence, updated_at);
```

### Refresh Flow

Background refresh:

1. Trading price worker fetches provider data without holding a financial writer
   transaction.
2. It writes/updates `trading_market_price_snapshots` in a short transaction.
3. It may update `trading_markets.manual_price_points` or warmup fields only in
   the same short price-refresh transaction.

Request flow:

```text
place_order/open_margin_position
  -> before BEGIN: read price snapshot with readonly or normal read connection
  -> if snapshot missing/stale/unusable: return price_unavailable or enqueue refresh
  -> BEGIN IMMEDIATE
  -> re-read snapshot row only, no external IO
  -> validate snapshot still fresh and high-risk usable if needed
  -> write order/fill/ledger
```

High-risk operations:

- market orders
- margin open/close/liquidation
- bot execution

These must require `risk_grade_price_points` and a usable snapshot. If only
reference price exists, the request must not silently fetch live provider data
inside the writer lock.

Non-high-risk reads:

- `/api/trading/live-price` may force refresh, but must not run inside another
  financial transaction.
- Frontend can show stale/fallback warning from snapshot metadata.

## 7. JSON Metadata Hot Field Flattening

Flattening reduces repeated JSON parsing and makes read models indexable.

### `points_ledger`

Candidate columns:

```text
source_wallet_address
destination_wallet_address
source_fund_key
destination_fund_key
settlement_rail
chain_required
approval_required
network_fee_points
service_fee_points
transfer_request_uuid
tx_group_hash
wallet_flow_version
```

Backfill:

- For old rows, parse `public_metadata_json.wallet_flow_snapshot`.
- For rows without snapshot, use legacy descriptor only during migration/rebuild.
- Do not mutate ledger financial meaning. These are derived query columns.

Indexes after backfill:

```sql
CREATE INDEX IF NOT EXISTS idx_points_ledger_source_wallet
ON points_ledger(chain_branch, source_wallet_address, id);

CREATE INDEX IF NOT EXISTS idx_points_ledger_destination_wallet
ON points_ledger(chain_branch, destination_wallet_address, id);

CREATE INDEX IF NOT EXISTS idx_points_ledger_tx_group
ON points_ledger(tx_group_hash);
```

### `points_economy_events`

Already has source/destination fund and address columns. Candidate metadata
fields to flatten only if query plans show JSON parsing in hot dashboards:

```text
bridge_uuid
chain_tx_hash
transfer_request_uuid
legacy_ledger_uuid
```

### `points_chain_bridge_events`

Already mostly flat. Keep `bridge_uuid`, `bridge_type`, `chain_tx_hash`,
`status`, `risk_status`, `internal_ledger_uuid` indexed for bridge explorer and
reconcile.

### `trading_fills`

Avoid parsing `points_ledger_uuids_json` on hot user pages. Candidate normalized
child table:

```sql
CREATE TABLE IF NOT EXISTS trading_fill_ledger_links (
    fill_id INTEGER NOT NULL,
    ledger_uuid TEXT NOT NULL,
    link_type TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (fill_id, ledger_uuid)
);
```

This is lower priority than wallet balances and price snapshots.

## 8. Why Not Split `finance.db` Yet

Do not split `finance.db` before the first optimization round.

Reasons:

- Trading writes, PointsChain ledger writes, economy events, bridge events, and
  exchange fund movements currently rely on same-transaction atomicity.
- Splitting PointsChain and trading into separate SQLite files would require a
  two-phase commit, outbox, or saga model. That violates the current rule
  against async financial commits.
- Current evidence shows avoidable hot replay and full scans. Splitting first
  would hide these bugs and make correctness harder to prove.
- Snapshot, rollback/fork, RC1 gate, and verify/replay still assume one
  coherent financial runtime state.

Re-evaluate after optimized 5K if all are true:

- `mixed_finance_5k` correctness is green.
- `p95` for core financial APIs is below 5s, but throughput still plateaus with
  CPU underused.
- DB writer wait or lock retry metrics remain the top bottleneck.
- Non-finance service quality degrades only because it shares the main DB file
  with finance writes.
- `dbstat` shows finance tables and indexes dominate main DB hot pages.

If split is justified later, split as one coherent `finance.db` containing both
PointsChain and trading, not separate `points_chain.db` and `trading.db`, unless
there is a formal cross-DB commit design.

## 9. Mixed Finance 5K Before/After Test Method

### Fixed Conditions

Every before/after comparison must use the same:

- code revision pair
- clean isolated runtime root
- server runner and worker/thread profile
- account count
- random seed
- market setup
- initial grants
- operation mix
- security/server mode
- no HLS/ComfyUI/BT/cloud/video load in 5K pure-finance baseline

### 1K Micro Baseline

Purpose: catch correctness regressions quickly after each implementation batch.

Required operation mix:

- pc0 internal transfer
- service fee pc0 debit
- violation fine burn
- hot to cold withdrawal bridge
- cold to cold transfer
- cold to deposit bridge credit
- official wallet/fund transfer
- system burn
- trading spot order
- trading margin open
- three bot paths where possible
- duplicate replay attack
- overspend attack
- missing signature attack
- direct pc1 to pc0 rejection

Gate:

- `failed_unexpected = 0`
- no negative materialized or replayed balances
- no duplicate credit
- duplicate/replay/double-spend attacks blocked
- PointsChain verify/replay pass
- trading verify pass
- bot background status proves auto-trigger is active

### 5K Pure-Finance Shakedown

Gate:

- `failed_unexpected = 0`
- exchange closed-loop reconciliation pass
- PointsChain verify/replay pass
- no negative balance
- no duplicate credit
- duplicate/replay/double-spend attacks blocked
- background bots auto-trigger without manual scan
- each core financial API `p95 < 5s`
- max latency may exceed 5s only if slow cases are listed with cause

Collect:

- throughput by round and operation type
- p50/p95/p99/max latency by label
- status counts by endpoint and operation
- server CPU/RAM
- DB file/WAL growth
- dbstat top tables/indexes
- EXPLAIN QUERY PLAN snapshot for hot queries
- writer lock retry/busy counts if available
- root PointsChain report
- root trading verify
- economy replay report

### 50K Full-Load Later

Only after optimized 5K is meaningful:

- Add HLS, E2EE, cloud drive, ComfyUI, mobile/frontend browsing, and long-running
  background work.
- `50K` must measure degradation from non-finance interference, not hot-path
  replay bugs.

## Implementation Batches After Review

Batch A0: document and state-machine cleanup

- Apply the five review edits in this document.
- Do not change runtime code.

Batch A1: low-risk core indexes only

- Add only Batch A1 core items from the index section.
- Do not add an index over `notifications.body`.
- Do not add `idx_points_bridge_chain_tx_full` unless the query rewrite still
  scans.
- Add tests or schema snapshot assertions where appropriate.
- Run 1K micro baseline and hot EXPLAIN before/after.
- Report index write-cost impact.
- Do not run 5K or 50K from Batch A1 alone.

Batch B: price snapshot lock shrink

- Add `trading_market_price_snapshots`.
- Move external provider IO outside financial writer transactions.
- Ensure high-risk writes fail fast on stale/missing snapshots.
- Run 1K micro baseline with live price provider enabled.

Batch C: materialized wallet balance

- Add durable derived balance table.
- Update it in the same financial transaction.
- Add full rebuild and verify.
- Route wallet available/balance checks through the materialized table.
- Run 1K then 5K.

Batch D: asset overview read model

- Replace `asset-overview -> user_dashboard()` with lightweight read model.
- Keep frontend contract stable.
- Run 1K, 5K, and frontend smoke for the platform center trading card.

## Acceptance Criteria for This Design

This design is acceptable only if implementation preserves:

- append-only ledger/event truth
- deterministic replay
- idempotency
- bridge reserve accounting
- auditability
- same-transaction financial commit
- no external API under writer lock
- no full ledger replay for ordinary wallet balance reads
