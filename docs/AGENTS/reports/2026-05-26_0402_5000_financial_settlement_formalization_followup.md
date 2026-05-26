# 2026-05-26 04:02 Financial Settlement Formalization Follow-up

Scope: apply the latest PC1/PC0/Bridge architecture direction as a project-level contract and remove a remaining legacy finance-dashboard label from the live `:5000` frontend.

## Architecture Contract

- Expanded `docs/architecture/POINTSCHAIN_FINANCIAL_SETTLEMENT_NETWORK.md` with:
  - `Reserve Transparency Dashboard Contract`
  - `Immutable Daily Audit Snapshots`
  - `Forbidden Mixing Patterns`
- The contract now explicitly gates:
  - PC1 canonical reserve
  - PC0 wrapped outstanding liabilities
  - Bridge pending settlement
  - Treasury reserve and operational liquidity
  - Machine-readable invariant status
- Added doc-test assertions in `tests/points/test_financial_settlement_architecture_docs.py` so future changes cannot silently drop these terms.

## Frontend Cleanup

- Removed the remaining old `帳本/事件差` display string from `public/js/55-economy.js`.
- Replaced it with `PC1 Reserve 對帳差`, keeping the dashboard in the new multi-ledger settlement vocabulary.
- Added a frontend regression assertion in `tests/frontend/trading/test_frontend_economy.py`.
- Synced updated `public/js/55-economy.js` to the live `:5000` run root.

## Validation

- `python3 -m py_compile tests/points/test_financial_settlement_architecture_docs.py`
- `python3 -m pytest tests/points/test_financial_settlement_architecture_docs.py -q` -> 2 passed
- `node --check public/js/55-economy.js`
- `python3 -m pytest tests/frontend/trading/test_frontend_economy.py -q` -> 10 passed
- `git diff --check -- public/js/55-economy.js tests/frontend/trading/test_frontend_economy.py docs/architecture/POINTSCHAIN_FINANCIAL_SETTLEMENT_NETWORK.md tests/points/test_financial_settlement_architecture_docs.py`
- Live static JS check confirms `PC1 Reserve 對帳差` is served and `帳本/事件差` is no longer served.
- Live `/api/root/points/financial-invariants` remains `ok:true`, `status:"pass"`, with bridge `flow_gap_points:0`.
