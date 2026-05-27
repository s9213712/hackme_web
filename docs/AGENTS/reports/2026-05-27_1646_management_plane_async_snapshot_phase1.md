# Management Plane Async/Snapshot Phase 1

Date: 2026-05-27

## Scope

Implemented the first response to the finance 50K pass1 interference retest:
the data plane remains synchronous, while root/admin heavy work moves to
Job Center jobs and snapshot reads.

## Changes

- `POST /api/root/points/chain/seal` now returns `202` with `job_id`.
- `GET /api/root/points/chain/verify` and
  `POST /api/root/points/chain/verify/jobs` now start async verification jobs.
- `GET /api/root/points/report` reads the latest snapshot when available; when
  missing or `refresh=1`, it starts an async report job.
- `POST /api/root/trading/sitewide/refresh` now starts an async trading
  snapshot refresh job.
- Added generic root job/snapshot reads:
  `/api/root/management/jobs/<job_id>` and
  `/api/root/management/snapshots/<snapshot_key>`.
- Added `management_plane_snapshots` in the small main DB, keeping latest root
  snapshots away from the large finance DB read path.
- Added wallet snapshot reads, compact transaction-list mode, and compact
  `/api/points/transactions/submit` responses for high-volume tests.
- Added management-plane microbenchmark headers/log fields and included
  `/api/root/trading` in management-plane observation.
- Added a cross-worker management-plane file lock so concurrent background
  seal/verify/report/trading jobs wait for the worker slot instead of failing
  with SQLite `database is locked`.
- Updated the root economy/trading frontend to treat async starts as queued
  background work and to read latest snapshots instead of expecting synchronous
  report payloads.

## Validation

Commands run:

```bash
python3 -m py_compile services/management_plane.py routes/economy.py routes/trading.py services/points_chain/service.py services/users/auth.py server.py scripts/testing/points_chain_destructive_stress.py
pytest -q tests/platform/test_job_center.py
pytest -q tests/points/test_points_explorer.py tests/trading/core/test_trading_root_sitewide_api.py
pytest -q tests/frontend/trading/test_frontend_economy.py
node --check public/js/55-economy.js
node --check public/js/56-trading.js
```

Result:

- Job Center tests passed.
- Points explorer/management tests passed.
- Trading root sitewide snapshot API tests passed.
- Frontend economy/trading static tests and JS syntax checks passed.

Live smoke on the existing 1.4GB finance runtime:

- Runtime: `/tmp/hackme_finance_50k_split_20260527_0230/hackme_web/runtime`
- Server: temporary gunicorn on `127.0.0.1:54261`, stopped after smoke.
- Async start timings:
  - seal: `202`, `0.108s`
  - verify: `202`, `0.233s`
  - root report refresh: `202`, `0.046s`
  - trading sitewide refresh: `202`, `0.067s`
- Latest snapshot reads while snapshots were still missing returned fast `404`:
  - seal: `0.040s`
  - verify: `0.037s`
  - root report: `0.035s`
  - trading refresh: `0.037s`
- Concurrent background jobs after the file-lock fix showed one active worker
  and the rest in `waiting_worker_lock`; no immediate `database is locked`
  failure in the request path.

## Remaining Work

- Add per-handler SQL and Python aggregation timers instead of the Phase 1
  default `0` slots.
- Move root transaction-list finality sweeps into their own bounded job so
  `compact=0` is no longer needed for release-gate finalization.
- Replace full root report generation with incremental high-water-mark
  snapshots.
- Re-run the finance 50K interference profile after this phase to confirm
  async start endpoints stay under 2 seconds and latest snapshot reads stay
  under 2 seconds on the existing 1GB+ finance DB.
