# Management Plane Async/Snapshot Phase 2a

Date: 2026-05-27

## Outcome

Implemented the next optimization slice after Phase 1. This is not the full
incremental snapshot layer yet; it removes more synchronous management-plane
pressure before the next finance 50K interference retest.

## Changes

- Management-plane jobs now carry `queue_class`, `resource_locks`, and
  `reused_recent_success` metadata in job rows and `202` start responses.
- PointsChain heavy jobs use `points_chain_admin`; trading heavy jobs use
  `trading_admin`; both serialize on the shared `finance_db` resource lock.
- Fresh successful management jobs can be reused for a short burst window, so
  repeated root dashboard refreshes do not enqueue identical report/verify work.
- `/api/root/trading/verify` now follows the async/snapshot contract:
  `GET /api/root/trading/verify?refresh=1` or
  `POST /api/root/trading/verify/jobs` starts a job, and
  `GET /api/root/trading/verify/latest` reads the latest snapshot.
- Root economy UI transaction refreshes now request
  `/api/points/transactions?limit=50&compact=1`.
- The 50K destructive stress harness now reads root transactions with
  `compact=1`, avoiding the full hydrate / hidden finality-maintenance path
  during high-load list refreshes.

## Validation

Commands run:

```bash
python3 -m py_compile services/management_plane.py routes/economy.py routes/trading.py scripts/testing/points_chain_destructive_stress.py scripts/testing/predeploy_capacity_probe.py scripts/testing/playwright_trading_background_correctness.py
node --check public/js/55-economy.js
PYTHONPATH=/home/s92137/hackme_web python3 -m pytest -q tests/services/test_management_plane.py
PYTHONPATH=/home/s92137/hackme_web python3 -m pytest -q tests/points/test_points_explorer.py -k "management_endpoints_start_async_jobs or wallet_transaction_submit_compact_response"
PYTHONPATH=/home/s92137/hackme_web python3 -m pytest -q tests/trading/core/test_trading_root_sitewide_api.py -k "root_sitewide_refresh_rebuilds_snapshot_before_read or root_trading_verify_runs_as_management_job"
```

Result: all commands passed.

## Remaining Work

- Implement true incremental high-water-mark snapshots for root report, wallet
  summary, and recent transaction read models.
- Move any remaining full-path finality maintenance behind an explicit bounded
  root job.
- Add more precise per-handler SQL, Python aggregation, JSON serialization, RSS,
  and response-byte attribution to the slow log.
- Re-run the existing finance 50K interference profile after this slice to
  confirm async start and latest snapshot reads stay under 2 seconds.
