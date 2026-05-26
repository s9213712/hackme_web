# 2026-05-26 03:34 - :5000 PointsChain financial settlement network formalization

## Scope

- Formalized PointsChain as a permissioned multi-ledger financial settlement
  network rather than a traditional single-chain dashboard.
- Kept the existing runtime accounting model compatible while adding stronger
  terminology, API aliases, and tests.

## Changes

- Added `docs/architecture/POINTSCHAIN_FINANCIAL_SETTLEMENT_NETWORK.md`.
  - Defines PC1 Canonical Settlement Layer, PC0 Operational Wrapped Layer, and
    Bridge Cross-Ledger Settlement Layer.
  - Defines supply semantics, mandatory invariants, target ledger separation,
    bridge state machine, explorer federation, and hash-chain audit direction.
- Updated `docs/architecture/PC0_DUAL_RAIL_WALLET_MODEL.md`.
  - Marked it active instead of draft.
  - Linked it to the formal financial settlement network architecture.
  - Replaced closed-loop wording with multi-ledger settlement reconciliation.
- Updated `docs/07_POINTSCHAIN.md` and docs indexes.
  - Describes PointsChain as PC1 reserve truth + PC0 wrapped operational
    balances + Bridge settlement.
- Updated `services/points_chain/service.py`.
  - Added `canonical_locked_reserve_points`.
  - Added `wrapped_supply_points`.
  - Renamed the first invariant to
    `wrapped_supply_within_canonical_locked_reserve`.
  - Kept existing `active_supply_points` and `finalized_total_points` aliases
    for compatibility.
- Updated Explorer UI labels.
  - Layer tabs now read `Settlement Explorer`, `Operational Explorer`,
    `Bridge Explorer`, and `Audit Explorer`.
  - Audit card displays `PC1 Canonical Reserve` and `PC0 Wrapped Outstanding`.

## Validation

- `python3 -m py_compile services/points_chain/service.py routes/economy.py`
- `node --check public/js/55-economy.js`
- `python3 -m pytest tests/points/test_financial_settlement_architecture_docs.py tests/frontend/trading/test_frontend_economy.py tests/points/test_points_chain.py::test_financial_invariant_report_exposes_reserve_liability_and_bridge_state -q`
- `python3 -m pytest tests/points/test_points_explorer.py -q`
- `git diff --check -- <touched files>`

All passed.

## Live :5000

- Synced frontend, service, tests, and docs into
  `/tmp/hackme_web_accept_20260526_server_mode_prelaunch_update_card/hackme_web`.
- Reloaded gunicorn master `211291` with `HUP`.
- Verified live files include:
  - `Settlement Explorer`
  - `Operational Explorer`
  - `Bridge Explorer`
  - `Audit Explorer`
  - `canonical_locked_reserve_points`
  - `wrapped_supply_within_canonical_locked_reserve`
- Verified live root financial invariant endpoint:
  - `ok=true`
  - `status=pass`
  - `canonical_locked_reserve_points=19999977`
  - `wrapped_supply_points=19999478`
  - `wrapped_supply_within_canonical_locked_reserve=true`
  - `bridge_settlement_integrity=true`
  - `pc0_operational_ledgers_not_sealed_into_pc1_blocks=true`

## Remaining Architecture Work

- Physical ledger separation is still a future migration:
  `pc1_settlement_ledger`, `pc0_operational_ledger`,
  `bridge_settlement_events`, and `reserve_audit_snapshots`.
- Bridge events should continue moving toward a formal state machine and
  per-row hash-chain auditability.
