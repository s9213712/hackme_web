# 2026-05-26 03:02 5000 Financial Invariants And Bridge Gap

## Result

No remaining blocker in the reported live wallet formula.

The reported `帳本/事件差 10` came from a bug-report reward ledger row
(`valid_bug_report_critical`) that credited a member `pc0` wallet without a
matching economy event. That path now routes reward facade credits from the
PROMO fund and backfills existing unclassified auto-distribution rows.

The reported `鏈上/橋外在外流通 499` is correct for the live scenario:

- `pc0出站`: 1000
- `入金入站`: 500
- `入金鏈費`: 1
- remaining cold/bridge-external balance: 499

The UI now also shows bridge network fee details so the 499 remainder is
explainable from the card.

## Changes

- `services/points_chain/wallet_facade.py`
  - `grant_reward()` now defaults rewards to `source_fund_key=promo_fund` and
    `settlement_rail=internal_hot_wallet`.
- `services/points_chain/service.py`
  - `valid_bug_report_*` / `bug_bounty_*` are classified as PROMO-funded
    configured auto-distribution rewards.
  - Economy backfill now runs when the closed-loop formula is balanced but
    wallet ledger vs economy event reconciliation is not.
  - Added `financial_invariant_report()` with separate canonical reserve,
    wrapped operational liabilities, pending settlement, bridge reconstruction,
    and machine-readable invariant errors.
- `routes/economy.py`
  - Added root endpoint: `/api/root/points/financial-invariants`.
- `public/js/55-economy.js`
  - Bridge flow detail now includes出金/入金 chain fee fields.
- `docs/architecture/PC0_DUAL_RAIL_WALLET_MODEL.md`
  - Added financial invariant gate rules.

## Live Verification

Against current `https://localhost:5000`:

- `ledger_vs_economy_external_gap_points`: 0
- `audit_reconciliation_balanced`: true
- `off_wallet_economy_external_points`: 499
- `hot_to_cold_confirmed_points`: 1000
- `deposit_credited_points`: 500
- `hot_to_cold_network_fee_points`: 22
- `deposit_network_fee_points`: 1
- `economy_flow_reconciliation_gap_points`: 0
- `financial_invariants.ok`: true
- `financial_invariants.error_count`: 0

The live report backfilled 1 missing economy event for the old bug reward.

## Validation

- `python3 -m py_compile services/points_chain/wallet_facade.py services/points_chain/service.py services/points_chain/economy_layer.py routes/economy.py routes/bug_reports.py`
- `node --check public/js/55-economy.js`
- `python3 -m pytest tests/points/test_points_chain.py tests/economy/test_economy_layer.py tests/regressions/test_bug_reports.py -q`
- `python3 -m pytest tests/points/test_points_explorer.py tests/points/test_chain_production_only.py -q`

