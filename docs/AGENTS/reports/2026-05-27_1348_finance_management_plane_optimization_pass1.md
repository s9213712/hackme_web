# 2026-05-27 13:48 Finance Management Plane Optimization Pass 1

## Scope

This pass targets the 50K split-finance run bottleneck transfer from data-plane writes to root/management/analytics endpoints.

Data-plane write semantics were intentionally left unchanged.

## Changes

- Added management-plane timing headers and slow logs for:
  - `/api/root/points*`
  - `/api/points/transactions`
  - `/api/points/explorer*`
- Slow log fields now include:
  - `slow_handler_ms`
  - `response_size`
  - `rss_before_mb`
  - `rss_after_mb`
- Added `verify_chain(include_financial=False)` so `root_report()` can verify the chain once and compute financial invariants once after `economy_stats()`.
- Added per-phase `management_timing` inside `root_report()`.
- Replaced explorer fee/finality network-state full ledger classification with bounded SQL counts.
- Added covering indexes:
  - `idx_points_ledger_branch_status_block(chain_branch, status, chain_block_id, id)`
  - `idx_points_ledger_branch_created(chain_branch, created_at)`
- Reused one network fee-state snapshot while returning accelerated transaction and fee ledger payloads.
- Stress harness now records `X-Management-Plane-*` headers in per-request samples when present.

## 50K DB Microbenchmark

Source DB copy:

`/tmp/hackme_finance_50k_opt_probe.db`

Rows:

- `points_ledger`: 191,249
- `points_chain_transfer_requests`: 92,102

Explorer network-state before/after shape:

| Query shape | Result | Min | Avg | Max | Plan |
|---|---:|---:|---:|---:|---|
| Old fetch for Python classification | 191,249 rows | 1004.561 ms | 1188.672 ms | 1446.003 ms | `idx_points_ledger_branch_id` |
| New unsealed count | 191,249 | 6.150 ms | 6.644 ms | 7.190 ms | covering `idx_points_ledger_branch_status_block` |
| New recent count | 0 | 0.003 ms | 0.009 ms | 0.021 ms | covering `idx_points_ledger_branch_created` |

This removes one repeated whole-ledger Python hydration path from explorer fee/finality endpoints.

## Verification

Passed:

- `python3 -m py_compile server.py services/points_chain/service.py services/points_chain/schema.py`
- `python3 -m py_compile scripts/testing/points_chain_destructive_stress.py`
- `pytest -q tests/points/test_points_explorer.py`
- `pytest -q tests/points/test_points_chain.py`
- `pytest -q tests/platform/test_finance_db_split.py`

Targeted tests also passed for:

- root report single verification
- explorer acceleration idempotency
- pending transfer acceleration
- root transaction management sweep
- financial invariant report
- hybrid auto seal scheduling

## Remaining Bottleneck

`verify_chain(include_financial=False)` against the 50K finance DB copy still exceeded a 70s timeout before completion.

That confirms root verify is still a true control-plane heavyweight job, even after removing explorer full-scan behavior and root report duplicate financial invariant work.

## Next Optimization

P0 next step:

- Make root `verify`, `seal`, and full `report` async job-backed endpoints.
- Keep synchronous endpoints only for bounded snapshot reads.
- Add latest-successful verify/seal/report snapshots for UI and stress harness reads.

P1 next step:

- Split `verify_chain()` into bounded phases with persisted checkpoint/snapshot output.
- Replace full wallet identity replay in synchronous admin views with incremental wallet/report snapshots.
