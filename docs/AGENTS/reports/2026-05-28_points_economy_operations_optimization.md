# Points / Economy / Exchange Operations Optimization

Date: 2026-05-28

## Scope

- Full-site service-fee linkage to PointsChain.
- Points private-chain root/admin control-plane endpoints.
- Points exchange/economy fund operations and initial distribution posture.
- Emergency recovery handling and management-plane snapshots.

## Changes

- Added `PointsLedgerService.operations_control_snapshot()` as a bounded
  management snapshot for initial grants, service-fee charges, private-chain
  queues, wallet identities, economy fund watermarks, exchange fund status,
  disputes, freezes, and emergency governance counts.
- Moved `/api/root/points/financial-invariants`,
  `/api/admin/points/economy/stats`, and
  `/api/root/points/chain/recovery/auto-handle` to async management-plane job
  starts with `/latest` snapshot reads.
- Added `/api/admin/points/operations/snapshot` and job/latest routes for the
  new bounded operations snapshot.
- Added hot indexes for initial-grant/action lookups, transfer queue status,
  and service-fee status/item queries.
- Updated the Economy frontend to treat recovery auto-handle and financial
  invariant audit as background jobs when the server returns `202 + job_id`.

## Verification

- `pytest -q tests/points/test_points_chain.py -k "operations_control_snapshot or finance_hot_path_indexes"`
- `pytest -q tests/points/test_points_explorer.py -k "management_endpoints_start_async_jobs"`
- `pytest -q tests/frontend/trading/test_frontend_economy.py`

## Next Queue

- Add a browser-visible operations panel section for the new bounded snapshot.
- Add a low-frequency background refresh job for `points_operations_control`.
- Extend the 50K interference probe to sample the new latest snapshot endpoints
  while transaction submit load is running.
