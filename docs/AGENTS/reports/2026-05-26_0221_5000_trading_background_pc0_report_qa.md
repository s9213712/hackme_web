# 2026-05-26 02:21 +08:00 - :5000 Trading Background And PC0 Report QA

## Finding

### P2 - PointsChain root report showed contradictory closed-loop balance flags
- Evidence: `/tmp/hackme_web_goal_qa_20260526_0212/curl_api/points_report.json`
- Behavior:
  - `bridged_supply_equation_gap_points = 0`
  - `formula_gap_balanced = true`
  - `bridged_supply_equation_balanced = false`
  - `ledger_vs_economy_external_gap_points = 10`
- Impact: root-facing audit data could make a balanced supply equation look unbalanced. The ledger/event reconciliation gap should remain visible, but it should not flip the supply-equation-balanced flag when the supply equation gap is zero.

## Fix
- Updated `services/points_chain/economy_layer.py`:
  - `bridged_supply_equation_balanced` now means `bridged_supply_equation_gap_points == 0`.
  - `audit_reconciliation_balanced` remains the stricter flag that also requires `ledger_vs_economy_external_gap_points == 0`.
- Updated `tests/economy/test_economy_layer.py` to lock the distinction:
  - formula can be balanced while audit reconciliation remains not balanced.

## Verification
- `python3 -m py_compile services/points_chain/economy_layer.py`
- `python3 -m pytest tests/economy/test_economy_layer.py -q`
- `python3 -m pytest tests/points/test_points_chain.py::test_economy_stats_replays_official_hot_wallet_circulation tests/trading/core/test_trading_engine.py::test_spot_cfd_principal_payout_and_fee_flow_through_exchange_fund tests/trading/core/test_trading_engine.py::test_margin_cfd_price_loss_is_collected_by_exchange_reserve_pool -q`
- Live apply:
  - copied `services/points_chain/economy_layer.py` into the active `:5000` run root
  - `kill -HUP 211291`
  - confirmed `/api/version` OK
- Live root report after reload:
  - `/tmp/hackme_web_goal_qa_20260526_0212/curl_api/points_report_after_fix.json`
  - `bridged_supply_equation_gap_points = 0`
  - `bridged_supply_equation_balanced = true`
  - `formula_gap_balanced = true`
  - `audit_reconciliation_balanced = false`
  - `ledger_vs_economy_external_gap_points = 10`

## Trading Background Evidence
- DB/API probe artifact: `/tmp/hackme_web_goal_qa_20260526_0212/api_db_trading_pc0_probe.json`
- Automatic background jobs advanced without active browser input during an 8 second wait:
  - `price_refresh` delta `+1`
  - `order_matching` delta `+1`
  - `take_profit_stop_loss_scan` delta `+1`
- Authenticated root API checks:
  - `/api/root/trading/background/status?limit=20` OK
  - `/api/root/trading/sitewide/refresh` OK
  - `/api/admin/trading/report` OK
  - `/api/root/trading/sitewide/pools` OK
  - `/api/root/trading/sitewide/user-positions` OK
  - `/api/root/trading/verify` OK, errors `[]`
  - `/api/root/trading/bot-audit/dashboard?limit=20` OK
  - `/api/root/points/chain/verify` OK, errors `[]`

## Notes
- `scripts/testing/playwright_trading_background_correctness.py` was attempted against the live server but hung before producing an artifact; the process was killed. DB inspection showed background jobs were running during that time, so this was treated as probe/tool instability rather than product failure for this pass.
