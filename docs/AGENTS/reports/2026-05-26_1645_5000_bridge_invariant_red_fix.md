# 2026-05-26 16:45 :5000 Bridge Invariant Red Fix

## Trigger

User reported red text in the :5000 blockchain / PointsChain dashboard.

## Finding

The red state came from `bridge_flow_reconstructs_external_supply`.

Before the fix, the supply equation itself was balanced:

- `bridged_supply_equation_gap_points = 0`
- `ledger_vs_economy_external_gap_points = 0`

But the bridge flow reconstruction showed:

- `current_cold_chain_or_bridge_external_points = 638`
- `economy_external_flow_net_points = 778`
- `economy_flow_reconciliation_gap_points = -140`

Root cause: `_pc0_bridge_flow_totals_locked()` counted pc0 fund wallet flows twice. A pc0 fund wallet movement to an external/receivable address matched both `hot_to_external` and `fund_to_external`; the reverse matched both `external_to_hot` and `external_to_fund`.

## Fix

Changed the invariant reconstruction to use per-event address net flow:

- `economy_external_address_in_points`
- `economy_external_address_out_points`
- `economy_external_flow_net_points = in - out`

The existing hot/fund breakdown counters remain available for dashboard context, but no longer drive the invariant net value by double-counted category sums.

## Verification

Repo tests:

- `python3 -m py_compile services/points_chain/service.py services/points_chain/economy_layer.py`
- `pytest tests/points/test_points_chain.py::test_bridge_flow_reconstruction_does_not_double_count_pc0_fund_wallets -q`
- `pytest tests/points/test_points_chain.py tests/points/test_rc1_1_operational_integrity.py tests/frontend/trading/test_frontend_economy.py -q`
- `pytest tests/economy/test_economy_layer.py -q`
- `python3 scripts/on_live_reports/points_chain_consistency.py`
- `python3 scripts/qa/points_chain_release_gate.py --skip-live`

Live :5000 after copying the fix and HUP reload:

```json
{
  "financial_invariants_ok": true,
  "financial_invariants_status": "pass",
  "financial_invariants_error_count": 0,
  "bridged_gap": 0,
  "ledger_gap": 0,
  "external_current": 638,
  "external_in": 2011,
  "external_out": 1373,
  "external_net": 638,
  "flow_gap": 0
}
```

## Note

This was an audit calculation bug, not evidence of a failed deposit bridge. The underlying replayed balances and finalized supply equation were already internally balanced.
