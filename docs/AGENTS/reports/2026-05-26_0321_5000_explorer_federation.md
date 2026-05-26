# 2026-05-26 03:21 5000 Explorer Federation QA

## Findings

- Fixed: PointsChain Explorer was still presented as a single chain explorer even though the runtime model is now PC1 canonical settlement + PC0 wrapped operational + bridge settlement.
  Impact: users and auditors could confuse PC0 internal ledger events with PC1 canonical settlement events, especially for deposit bridge credits.
  Change: added layer-aware explorer UI tabs and bridge-event lookup.

## Changes

- Backend:
  - Added `GET /api/points/explorer/bridge/<ref>`.
  - Bridge lookup supports `bridge_uuid`, `chain_tx_hash`, and `internal_ledger_uuid`.
  - Explorer transactions now include `layer`, `asset_type`, `settlement_rail`, and `cross_references`.
  - Bridge results expose PC1 settlement tx, PC1 deposit address, PC0 wrapped credit ledger, PC0 hot wallet, and invariant status.
- Frontend:
  - Added Explorer layer tabs: `PC1 Settlement`, `PC0 Operational`, `Bridge`, `Audit`.
  - Added layer banner and asset type labels.
  - Added Bridge and Audit result cards.
  - Updated JS cache key to `20260526-explorer-federation`.

## Live Verification

- Applied to current `:5000` tmp instance and reloaded gunicorn.
- `GET /api/points/explorer/bridge/df509557ee4cfb7fe8ef64d5125a89996d6a8161716eb1a16a5ba110f96fc890` returned:
  - `kind=bridge`
  - `layer=bridge`
  - `invariant_status=valid`
  - `pc1_settlement_tx=df509557...`
  - `pc0_wrapped_credit=16de5c27-...`
  - internal transaction `layer=pc0`
- Live files contain the layer tabs and updated cache key.

## Checks

- `python3 -m py_compile services/points_chain/service.py routes/economy.py`
- `node --check public/js/55-economy.js`
- `python3 -m pytest tests/points/test_points_explorer.py tests/frontend/trading/test_frontend_economy.py -q`

## Residual Risk

- This is a federation UI/API boundary over the transitional single `points_ledger` storage model.
- Physical three-ledger separation remains a separate migration: PC1 settlement ledger, PC0 operational ledger, and bridge settlement ledger.
