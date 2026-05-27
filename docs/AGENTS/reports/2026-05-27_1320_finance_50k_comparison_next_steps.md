# 2026-05-27 Finance 50K Comparison And Next Steps

## Compared Runs

| Run | Profile | Result | Finance data path | Interference | Main bottleneck |
| --- | --- | --- | --- | --- | --- |
| `0804` full-load exploratory | Pre-split/single main DB, external bridge every 5 capped at 1200, big media load | FAIL | 6K wallet stage completed, 40K direct stage had 61 stdout errors, trading did not run | System stress degraded, large HLS stuck | Harness finalizer, HLS, QoS, single main DB growth |
| `1111` split core | Finance DB split, no non-trading interference, external bridge disabled | PASS | 40K direct OK, 4K trading OK, pending 0 | None | One root report client timeout at 60s |
| `1316` split + existing DB interference | Same existing split DB after prior 50K, non-trading interference active | FAIL overall, data path OK | 40K direct OK, 4K trading OK, pending 0 | System stress degraded; member/HLS probes passed | Root/admin PointsChain reads exceed 180s |

## Key Metrics

| Metric | `0804` full-load | `1111` split core | `1316` split + interference |
| --- | ---: | ---: | ---: |
| Final JSON artifact | No | Yes | Yes |
| Main DB size | 436MB | 2.3MB | 3.5MB |
| Finance DB size | N/A | 464MB | 928MB |
| Transfer requests | ~45,990 | 46,051 | 92,102 total |
| Ledger rows | ~91,629 | 95,625 | 191,249 total |
| Trading orders | 0 | 4,000 | 8,000 total |
| Direct transfer errors | 61 observed | 0 | 0 |
| Prefix pending / failed | 200 pending | 0 / 0 | 0 / 0 |
| 50K elapsed | Interrupted | 1,918.5s | 5,368.2s |
| Main latency p50 / p95 / p99 | N/A | 244 / 824 / 1,123ms | 339 / 1,060 / 1,390ms |
| Max request latency | N/A | 60.1s | 196.9s |
| Monitored RSS max | 546MB sample | 2,269MB | 4,855MB |

## What Improved

- The DB split worked. The finance load moved out of `database.db`; after two 50K-scale runs the main DB stayed around 3.5MB while `finance.db` grew to 928MB.
- The finance write path is now stable for the core 50K shape. Direct pc0 transfers went from 61 observed errors in the exploratory run to 0 errors in both split runs.
- Trading closure is now covered. The first exploratory run never reached trading; the split runs completed 4K orders each.
- The HLS small-file regression path improved. In the interference run, HLS upload, wait, and measure all passed.

## Current Bottleneck

The next blocker is not finance writes. It is root/admin read and report work on the larger finance DB:

- `POST /api/points/explorer/accelerate` exceeded the client `180s` timeout, but server later returned `200`.
- `GET /api/points/transactions?limit=100` returned `200` but took long enough for the harness to record timeout.
- `POST /api/root/points/chain/seal`, `GET /api/root/points/chain/verify`, and `GET /api/root/points/report` exceeded `180s` from the client. Access logs show the server later returned `200`.
- Worker RSS peaked at 4.85GB in the interference run, so these reads also have a memory-pressure dimension.

## Optimization Order

1. Make root/admin operations bounded or async.
   - Convert chain seal, verify, and points report to job/snapshot flows.
   - Return a job id quickly, then let the UI/API poll job state or serve the last completed snapshot.
   - Keep synchronous paths only for small bounded checks.

2. Remove implicit heavy work from list/read endpoints.
   - `/api/points/transactions?limit=100` should not perform expensive global finalization or full summary recomputation during ordinary listing.
   - Move finalization sweep to an explicit bounded endpoint/job, for example `sweep(limit=5|25)`.
   - Keep list payloads lean; do not hydrate full finality/report data unless requested.

3. Cache and incrementally maintain expensive root report data.
   - Use materialized/snapshot tables for root points report, network fee state, recent ledger counts, and wallet balance summaries.
   - Recompute incrementally from last processed ledger/transfer id instead of replaying or scanning all 191K+ rows per request.

4. Add query instrumentation before changing more schema.
   - Log SQL timing for the five slow endpoints.
   - Capture `EXPLAIN QUERY PLAN` for the slowest queries on the existing 928MB DB.
   - Add only targeted covering indexes after confirming query plans. Likely candidates are status/time scans on `points_chain_transfer_requests` and report-time scans over `points_ledger`.

5. Fix harness accuracy for large DB runs.
   - If prefix pending count is already 0, skip finalizer list sweeps.
   - Separate data-path success from admin/report timeout findings in the final JSON, so a valid 40K+4K write pass is not obscured.
   - Keep admin timeout failures as release blockers, but classify them as management-plane performance.

6. Re-test in three layers.
   - First, benchmark the five slow endpoints on the existing 928MB DB after each optimization.
   - Second, rerun split core 50K on a fresh DB to preserve apples-to-apples comparison.
   - Third, rerun split + interference and then a dedicated external-bridge profile. Do not combine 1200 bridge pending transfers with broad interference until the root/admin slow paths are under budget.

## Target Budgets For Next Pass

- Data path: 40K direct errors `0`, 4K trading status `200`, prefix pending `0`, failed `0`.
- Root/admin endpoints on ~1GB finance DB:
  - transaction list under 10s;
  - acceleration under 10s;
  - seal under 30s or async accepted under 2s;
  - verify under 30s or async accepted under 2s;
  - points report under 30s or snapshot read under 2s.
- Interference QoS:
  - system stress hard failure rate below 0.1%;
  - p95 below 1500ms for ordinary user-facing endpoints, excluding explicitly queued heavy admin jobs.

