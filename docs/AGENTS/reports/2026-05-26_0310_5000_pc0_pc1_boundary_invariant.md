# 2026-05-26 03:10 5000 PC0/PC1 Boundary Invariant QA

## Findings

- Fixed: financial invariant did not explicitly fail when a `pc0` operational ledger row was already attached to a PC1 block via `chain_block_id`.
  Impact: future manual corruption, migration bug, or old data could make PC0 appear inside canonical PC1 block history while the normal sealer only prevents new pollution.
  Change: added `ledger_boundary` to `financial_invariants` and invariant `pc0_operational_ledgers_not_sealed_into_pc1_blocks`.
  Evidence: `tests/points/test_points_chain.py::test_financial_invariant_flags_pc0_ledger_sealed_into_pc1_block`.

## Live Verification

- `:5000` reloaded via gunicorn `HUP` after copying the updated `services/points_chain/service.py` to the active tmp instance.
- `GET /api/root/points/financial-invariants` on live `:5000` returned:
  - `ok=true`
  - `model=pc1_canonical_reserve_pc0_wrapped_operational_v1`
  - `ledger_boundary.ok=true`
  - `sealed_pc0_operational_ledgers=0`
  - `flow_gap_points=0`
  - `current_cold_chain_or_bridge_external_points=499`

## Checks

- `python3 -m py_compile services/points_chain/service.py routes/economy.py`
- `node --check public/js/55-economy.js`
- `python3 -m pytest tests/points/test_points_chain.py::test_financial_invariant_flags_pc0_ledger_sealed_into_pc1_block tests/points/test_points_chain.py::test_pc1_block_seal_excludes_pc0_operational_ledgers tests/points/test_points_chain.py::test_financial_invariant_report_exposes_reserve_liability_and_bridge_state tests/points/test_points_chain.py::test_financial_invariant_report_flags_corrupt_bridge_settlement -q`

## Notes

- Current implementation is still a transitional single `points_ledger` table with strict PC1/PC0 classification and invariant checks.
- The target architecture should still move toward physical three-ledger separation: PC1 settlement ledger, PC0 operational ledger, and bridge settlement ledger.
