# Management Plane Scaling

Status: Phase 2a implemented for the finance 50K pass1 interference findings.
Later phases still need true incremental high-water-mark snapshots and deeper
SQL/Python attribution.

## Problem

The 50K finance DB split runs changed the bottleneck.

The data plane now survives the target write profile:

- 40K direct pc0 transfers completed with 0 errors.
- 4K trading orders completed.
- prefix pending and failed counts ended at 0.
- `database.db` stayed small while finance growth moved to `finance.db`.

The failing path is now management and analytics work on top of the larger
finance database. At about 928MB `finance.db`, 92K transfer requests, and 191K
ledger rows, these endpoints exceeded the client timeout or returned only after
long blocking work:

- `POST /api/points/explorer/accelerate`
- `GET /api/points/transactions?limit=100`
- `POST /api/root/points/chain/seal`
- `GET /api/root/points/chain/verify`
- `GET /api/root/points/report`

This is not primarily a write-path failure. It is a management-plane and
analytics-plane scaling failure caused by synchronous heavy reads, aggregation,
verification, report generation, and JSON serialization.

## Plane Model

| Plane | Examples | Rule |
| --- | --- | --- |
| Data plane | wallet transfer, trading order submit, settlement writes | Must be synchronous and bounded |
| Control plane | seal, verify, finality sweep, root maintenance | May be async; must not block request workers for minutes |
| Analytics plane | explorer, reports, statistics, root dashboards | Must use snapshots, read models, or cursor-bounded reads |

## Non-Negotiable Rules

Root/admin endpoints must not synchronously:

- replay the full ledger;
- hydrate all wallets;
- scan all transfer requests;
- build full chain verification reports;
- seal or verify the chain end to end;
- generate large report JSON from live ledger tables;
- run unbounded finality sweeps from list endpoints.

If the operation can exceed an ordinary HTTP budget at 1GB `finance.db`, it
must be a job, snapshot read, or explicitly bounded batch.

## Root Snapshot Layer

The target model is a durable root snapshot layer, not an in-process cache.

| Snapshot | Update model | Read model |
| --- | --- | --- |
| points report snapshot | incremental by last processed ledger/transfer id | root report reads latest completed snapshot |
| wallet summary snapshot | incremental on wallet-affecting ledger/transfer writes | wallet/admin summary reads derived rows |
| chain verify summary | async job, stores result and evidence metadata | verify endpoint returns latest result or job status |
| explorer recent tx snapshot | append/cursor by id | explorer reads recent/cursor pages |
| pending/finality queue snapshot | bounded sweep job | list endpoints read queue counts only |

Snapshots must include enough provenance to be auditable:

- source DB path or database identity;
- source table high-water marks;
- generated timestamp;
- generating job id;
- result hash where practical;
- warning/error list;
- duration and row-count metrics.

## Endpoint Contract Changes

### Phase 1 Implemented Contract

The first migration keeps the existing user-facing paths but changes heavy
root/admin behavior to async start plus snapshot reads:

| Operation | Start endpoint | Status endpoint | Latest snapshot |
| --- | --- | --- | --- |
| PointsChain seal | `POST /api/root/points/chain/seal` | `GET /api/root/points/chain/seal/jobs/<job_id>` or `GET /api/root/management/jobs/<job_id>` | `GET /api/root/points/chain/seal/latest` |
| PointsChain verify | `GET /api/root/points/chain/verify` or `POST /api/root/points/chain/verify/jobs` | `GET /api/root/points/chain/verify/jobs/<job_id>` or `GET /api/root/management/jobs/<job_id>` | `GET /api/root/points/chain/verify/latest` |
| Points root report | `GET /api/root/points/report?refresh=1` or `POST /api/root/points/report/jobs` | `GET /api/root/points/report/jobs/<job_id>` or `GET /api/root/management/jobs/<job_id>` | `GET /api/root/points/report/latest` |
| Trading sitewide refresh | `POST /api/root/trading/sitewide/refresh` | `GET /api/root/management/jobs/<job_id>` | `GET /api/root/trading/sitewide/refresh/latest` |
| Trading verify | `GET /api/root/trading/verify?refresh=1` or `POST /api/root/trading/verify/jobs` | `GET /api/root/management/jobs/<job_id>` | `GET /api/root/trading/verify/latest` |

`GET /api/root/points/report` now reads the latest successful snapshot when it
exists. If no snapshot exists, it starts a job and returns `202` instead of
building the report synchronously.

Snapshots are stored in the small main DB table `management_plane_snapshots`.
The large finance DB is only touched by the background worker that generates the
next snapshot.

Management-plane background workers use host-local file locks beside the main
DB. Phase 2a records `queue_class` and `resource_locks` on each job and exposes
them in the start payload. PointsChain heavy jobs run in `points_chain_admin`,
trading heavy jobs run in `trading_admin`, and both serialize on the shared
`finance_db` resource lock so control-plane work cannot stampede the finance
SQLite file. Active job reuse checks the recorded worker/starter PID and a
short updated-at grace period, so stale running rows from a restarted server do
not suppress new jobs forever. Fresh successful jobs can also be reused for a
short burst window, preventing repeated root dashboard refreshes from starting
identical heavy work.

`GET /api/points/transactions?compact=1&cursor=<id>` provides a bounded compact
read path without per-row explorer hydration or hidden finality maintenance.
The root economy frontend and 50K destructive stress harness now use this
compact path for list refreshes. Finality sweeps that still need maintenance
semantics must be moved to an explicit bounded job instead of relying on
`compact=0` list calls.

`POST /api/points/transactions/submit` accepts `compact: true` or
`?compact=1`, returning only the fields needed by high-volume data-plane tests.

### Report

Current anti-pattern:

```text
GET /api/root/points/report
  -> scans live ledger/transfer state
  -> builds large response
  -> returns after minutes
```

Target:

```text
GET /api/root/points/report
  -> returns latest successful snapshot

POST /api/root/points/report/jobs
  -> 202 accepted, {job_id}

GET /api/root/points/report/jobs/<job_id>
  -> job status and snapshot pointer
```

### Seal And Verify

Current anti-pattern:

```text
POST /api/root/points/chain/seal
GET /api/root/points/chain/verify
```

Both may block for minutes at 50K+ scale.

Target:

```text
POST /api/root/points/chain/seal
  -> 202 accepted, {job_id}

POST /api/root/points/chain/verify
  -> 202 accepted, {job_id}

GET /api/root/points/chain/jobs/<job_id>
  -> status/result

GET /api/root/points/chain/latest-successful-seal
GET /api/root/points/chain/latest-successful-verify
```

Small bounded diagnostic checks can remain synchronous, but must declare and
enforce a row/time limit.

### Transaction List And Finality

Current risk:

```text
GET /api/points/transactions?limit=100
  -> list
  -> summary
  -> implicit proved-pending finalization sweep
```

Target:

```text
GET /api/points/transactions?limit=100&cursor=<id>
  -> bounded list only

POST /api/root/points/finality-sweep
  -> 202 accepted or bounded synchronous result
  -> payload includes {limit}
```

List endpoints must not perform hidden maintenance work.

## Instrumentation Required Before More Indexing

Timeouts here may be caused by SQL, Python aggregation, JSON encoding, or memory
pressure. Add per-endpoint measurement before adding more schema:

- `handler_total_ms`
- `sql_total_ms`
- slow SQL text hash and `EXPLAIN QUERY PLAN`
- `aggregation_ms`
- `json_serialize_ms`
- `response_bytes`
- `rss_before_mb`
- `rss_after_mb`
- rows scanned, rows hydrated, rows returned
- snapshot high-water marks

This should be logged for the five slow endpoints first:

- `/api/points/explorer/accelerate`
- `/api/points/transactions`
- `/api/root/points/chain/seal`
- `/api/root/points/chain/verify`
- `/api/root/points/report`

Phase 1 emits these HTTP headers on management/analytics-plane requests:

- `X-Management-Plane-Handler-Ms`
- `X-Management-Plane-SQL-Ms`
- `X-Management-Plane-Python-Aggregation-Ms`
- `X-Management-Plane-JSON-Serialize-Ms`
- `X-Management-Plane-Response-Bytes`
- `X-Management-Plane-RSS-MB`
- `X-Management-Plane-Slow-Reason`

The current SQL/Python aggregation values are explicit endpoint slots and
default to `0` until a handler sets them. Slow logs include the same fields and
keep `/api/points/transactions/submit` outside management-plane classification.

## Index Policy

Do not add speculative indexes before instrumentation. After query plans are
captured on the 928MB test DB, likely candidates to evaluate include:

- status/time scans on `points_chain_transfer_requests`;
- request UUID plus status lookups;
- report-time scans over `points_ledger`;
- structured fields or derived tables replacing JSON `LIKE` report predicates.

Indexes must be justified with before/after query plans and measured endpoint
latency, not just table size.

## Harness Changes

The 50K harness should separate data-plane success from management-plane
success:

```json
{
  "data_path_ok": true,
  "management_plane_ok": false,
  "analytics_plane_ok": false,
  "overall_ok": false
}
```

The harness should also skip root list finalizer sweeps when prefix pending is
already 0. A release gate can still fail on management-plane timeout, but the
artifact must make clear whether transfer/order correctness failed.

## Target Budgets

At approximately 1GB `finance.db`:

| Operation | Budget |
| --- | ---: |
| wallet transfer submit | existing data-plane budget; no regression |
| trading order submit | existing data-plane budget; no regression |
| transaction list | under 10s |
| accelerate pending | under 10s or async accepted under 2s |
| seal | async accepted under 2s, job result tracked |
| verify | async accepted under 2s, job result tracked |
| root points report | snapshot read under 2s, rebuild job tracked |
| ordinary user-facing endpoint under interference | p95 under 1500ms |

## Implementation Order

1. Add instrumentation to the five slow endpoints.
2. Make root points report read from a persisted snapshot.
3. Add async jobs for report rebuild, chain seal, and chain verify.
4. Split transaction listing from finality sweep.
5. Add bounded finality sweep endpoint/job.
6. Capture query plans from the 928MB DB and add only targeted indexes.
7. Update the 50K harness result model.
8. Re-test slow endpoints on the existing 928MB DB.
9. Rerun split core 50K.
10. Rerun split + interference 50K.
11. Run the external-bridge pending profile separately.

## Acceptance Criteria

The next official 50K gate should not be considered ready until:

- data-plane metrics remain at 0 direct transfer errors and 0 prefix pending;
- root report is snapshot-backed;
- seal and verify no longer block HTTP workers for minutes;
- transaction listing is bounded and no longer hides finality sweeps;
- system stress hard failure rate is below 0.1%;
- root/admin snapshots expose freshness and job provenance.
