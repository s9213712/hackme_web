# 2026-05-26 03:27 - :5000 settlement control plane UI

## Scope

- Reworked the PointsChain financial summary from a single flat supply equation into a layered settlement control plane.
- Kept backend accounting fields unchanged; this pass is UI terminology and presentation cleanup.

## Changes

- `public/js/55-economy.js`
  - Replaced `closed loop formula` wording with `multi-ledger settlement control plane`.
  - Split the summary into:
    - PC1 Canonical Reserve
    - PC0 Wrapped Operational Supply
    - Bridge Settlement / Pending Isolation
    - Financial Reconciliation
  - Removed misleading live UI terms such as `chain/bridge external circulation`, `pc0 outbound`, and `deposit inbound`.
- `public/js/50-admin.js`
  - Renamed the compact platform supply chart to multi-ledger supply reconciliation.
  - Replaced `closed loop normal` with `Settlement invariant normal`.
- `public/index.html`
  - Updated the loading placeholder and JS cache keys for the changed frontend bundles.
- `public/styles.css`
  - Added responsive section layout for the layered financial summary.
- `tests/frontend/trading/test_frontend_economy.py`
  - Added guardrails so old mixed-ledger terminology does not return to the economy frontend.

## Validation

- `node --check public/js/55-economy.js`
- `node --check public/js/50-admin.js`
- `python3 -m pytest tests/frontend/trading/test_frontend_economy.py -q`

All passed.

## Live :5000

- Synced the changed frontend files into `/tmp/hackme_web_accept_20260526_server_mode_prelaunch_update_card/hackme_web`.
- Reloaded gunicorn master `211291` with `HUP`.
- Verified live files contain the new settlement control plane labels and no longer contain the old mixed-ledger labels.
- Verified `/api/root/points/financial-invariants` still reports:
  - `ok=true`
  - `status=pass`
  - `finalized_supply_equation_balanced=true`
  - `wallet_ledger_matches_economy_events=true`
  - `bridge_flow_reconstructs_external_supply=true`
  - `pc0_operational_ledgers_not_sealed_into_pc1_blocks=true`
