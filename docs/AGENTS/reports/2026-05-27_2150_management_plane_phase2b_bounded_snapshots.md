# Management Plane Phase2b Bounded Snapshots

Date: 2026-05-27
Branch: `04.BLOCKCHAIN_RC1`

## Context

The Phase2a 50K finance interference retest proved the data-plane write path
remained stable, but root/admin jobs were still incomplete: start endpoints
returned quickly while latest snapshots stayed `404` and jobs remained
`running`.

## Changes

- Added `verify_chain_bounded_snapshot()` for root/admin management jobs.
  It verifies recent ledger continuity and recent block signatures without
  replaying the full 1GB+ ledger.
- Added `root_report_bounded_snapshot()` for root report jobs.
  It builds a snapshot from bounded counts, recent blocks, recent risk rows,
  audit logs, recovery state, and deferred full financial/governance audit
  markers.
- Changed root PointsChain management jobs to use the bounded snapshot methods.
- Changed management-plane job progress updates to flush to DB, so progress is
  visible across gunicorn workers instead of only in process-local progress
  cache.
- On worker failure, management-plane now writes a failed snapshot summary
  before marking the job failed, so `/latest` can return a bounded result
  instead of staying missing forever.

## Existing 1.8GB DB Smoke

Runtime DB:
`/tmp/hackme_finance_50k_split_20260527_0230/hackme_web/runtime/database`

Measurements on the existing post-50K DB:

| Probe | Result |
| --- | ---: |
| `verify_chain_bounded_snapshot()` | `166.471ms` |
| `root_report_bounded_snapshot()` | `802.864ms` |
| management job smoke | `succeeded`, snapshot written |
| smoke snapshot summary | `elapsed_ms=791.798`, `bounded=true` |

The previous slow part was `_root_recent_unsealed_transactions()`, which spent
about `48s` classifying unsealed rows. The bounded report now uses a pure SQL
limited snapshot and marks PC1/PC0 classification as deferred.

## Verification

```text
PYTHONPATH=/home/s92137/hackme_web python3 -m py_compile \
  services/points_chain/service.py routes/economy.py services/management_plane.py

PYTHONPATH=/home/s92137/hackme_web python3 -m pytest \
  tests/services/test_management_plane.py \
  tests/points/test_points_explorer.py::test_root_points_management_endpoints_start_async_jobs -q

PYTHONPATH=/home/s92137/hackme_web python3 -m pytest \
  tests/points/test_points_chain.py::test_points_chain_root_report_reuses_single_verification \
  tests/points/test_points_chain.py::test_points_chain_seal_verify_and_proof \
  tests/points/test_points_chain.py::test_points_chain_seal_adds_local_signature_and_root_report -q
```

All checks passed.

## Next

- Re-run targeted management endpoint smoke on the live server path.
- Re-run 50K interference with job-status polling and latest-snapshot reads.
- Keep full financial/governance verification as a separate offline/full-audit
  worker instead of root UI synchronous or request-spawned replay.
