# 2026-05-26 17:21 :5000 PointsChain Red Text Check

## Finding

- Severity: P2 display/cache issue
- Behavior: The live `:5000` PointsChain backend invariants were already passing, but a browser could still show stale red settlement text if it kept the previous immutable `/js/55-economy.js` asset.
- Impact: Operators may think the ledger is still broken even though `/api/root/points/financial-invariants` reports `status=pass`.

## Fix

- Bumped `public/index.html` asset versions for:
  - `/js/50-admin.js`
  - `/js/55-economy.js`
- Synced the updated `public/index.html` into the live `:5000` tmp instance.

## Evidence

- Live API check:
  - `financial_invariants.ok=true`
  - `status=pass`
  - `bridge_flow_reconstructs_external_supply.gap_points=0`
  - `wallet_ledger_matches_economy_events.gap_points=0`
- Browser check on `https://127.0.0.1:5000`:
  - `差額 0 · Settlement invariant 正常`
  - no legacy strings: `鏈上/橋外在外流通`, `帳本/事件差`, `pc0出站`, `殘差舊算法`
  - screenshot: `/tmp/hackme_web_5000_points_red_check.png`
- Tests:
  - `python3 -m py_compile services/points_chain/service.py services/points_chain/economy_layer.py`
  - `node --check public/js/55-economy.js`
  - `node --check public/js/50-admin.js`
  - `pytest tests/frontend/trading/test_frontend_economy.py -q`
  - `python3 scripts/on_live_reports/points_chain_consistency.py`

## Status

Resolved on live `:5000`. If a currently open browser tab still shows the old red line, refresh once so it fetches the new asset version.
