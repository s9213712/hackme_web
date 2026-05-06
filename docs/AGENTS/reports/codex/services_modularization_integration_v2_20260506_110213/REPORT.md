# Services Modularization Integration v2

## Step

Extract trading verification and reconciliation into
`services/trading/verification.py`.

## Exact Files Changed

- `services/trading/constants.py`
- `services/trading/verification.py`
- `services/trading_engine.py`

## Functional Boundary

This step keeps trading state verification together as one system boundary:

- fill ledger verification
- open order lock verification
- reserve pool replay verification
- root simulated account verification
- margin collateral lock verification
- spot realized PnL replay verification
- full `verify_state` orchestration

`services/trading_engine.py` remains the façade and now delegates the entire
verification block.

## Exact Methods Delegated

- `_replay_positions`
- `_ledger_row`
- `_verify_fill_ledgers`
- `_verify_open_order_locks`
- `_verify_reserve_pool`
- `_verify_sim_accounts`
- `_verify_margin_position_locks`
- `_verify_spot_realized_pnl`
- `_verify_state_on_conn`
- `verify_state`

## File Size Check

- `services/trading/verification.py`: `509` LOC
- `services/trading_engine.py`: `7485` LOC after this step

No new over-fragmented files were introduced.

## Behavior Change

No.

## Tests

### Targeted

- `PYTHONPATH=. python3 -m pytest -q tests/test_security_issue_regressions.py -k "trading_fill_ledger_verification_uses_batch_lookup or root_margin_trading_uses_simulated_funds_not_pointschain or trading"`
  - `7 passed, 25 deselected`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py tests/test_trading_reference_prices.py tests/test_frontend_economy.py`
  - `200 passed`

### Full

- `HACKME_RUNTIME_DIR=/tmp/hackme_web_fullpytest_20260506_verify PYTHONPATH=. python3 -m pytest -q tests/`
  - `1059 passed`

### Pre-push

- `python3 scripts/pre_push_checks.py --ci`
  - `10 PASS / 1 FAIL`
  - only blocker: `release id sync`

## Rollback Plan

- Revert commit `trading: extract verification module`
- This restores reconciliation logic to `services/trading_engine.py`
- No schema rollback is required
