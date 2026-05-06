# Trading Modularization Integration v2

## Step

Extract funding snapshot and root simulated contract helpers into a single
`services/trading/funding.py` module.

## Files Changed

- `services/trading_engine.py`
- `services/trading/funding.py`

## Functions Moved

- `_funding_snapshot_ctx`
- `publish_funding_rate_snapshot`
- `get_funding_rate_snapshot`
- `settle_funding_adjustment`
- `_root_sim_account`
- `_sim_delta`
- `_funding_payload`
- `open_root_contract_position`
- `close_root_contract_position`
- `reset_root_simulated_balance`

## Boundary

This step keeps one cohesive subsystem together:

- funding-rate snapshot routing
- root simulated funding account
- root simulated contract open/close/reset flow

It intentionally does **not** split this area into separate `funding.py` /
`futures.py` / `simulation.py` shards.

## Fragmentation Check

New file sizes after extraction:

- `services/trading/funding.py`: `576` LOC
- `services/trading_engine.py`: `7183` LOC

No new tiny compatibility wrapper files were introduced.

## Behavior Change

No.

Public method names remain stable on `services/trading_engine.py`, which
continues to act as the compatibility façade.

## Validation

- `python3 -m py_compile services/trading_engine.py services/trading/funding.py`
- `git diff --check`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py -k "funding or contract or simulated"`
  - `7 passed, 151 deselected`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py tests/test_trading_reference_prices.py tests/test_frontend_economy.py`
  - `200 passed`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_fullpytest_20260506_funding PYTHONPATH=. python3 -m pytest -q tests/`
  - `1059 passed`
- `python3 scripts/pre_push_checks.py --ci`
  - `10 PASS / 1 FAIL`
  - only blocker: `release id sync`

## Rollback Plan

Revert the single commit for this step. The façade wrappers in
`services/trading_engine.py` isolate the extraction cleanly.
