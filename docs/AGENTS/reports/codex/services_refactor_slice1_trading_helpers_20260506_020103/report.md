# Services Refactor Slice 1: Trading Pure Helpers

Timestamp: `2026-05-06 02:01:03 Asia/Taipei`
Branch: `05.services-refactor-slice1-trading-helpers`

## Files Changed

- `services/trading_engine.py`
- `services/trading/__init__.py`
- `services/trading/constants.py`
- `services/trading/validators.py`
- `services/trading/accounting/__init__.py`
- `services/trading/accounting/units.py`
- `services/trading/accounting/notional.py`
- `services/trading/accounting/fees.py`

## Functions / Constants Moved

### Constants

- `ASSET_SCALE`
- `POINT_MICRO_SCALE`
- `DEFAULT_SPOT_FEE_RATE_PERCENT`
- `DEFAULT_GRID_FEE_DISCOUNT_PERCENT`
- `GRID_PREVIEW_YELLOW_NET_SPREAD_PERCENT`
- `APR_DAYS_PER_YEAR`

### Validators

- `_to_int`
- `_to_float`
- `_to_decimal`
- `_to_price_float`
- `_decimal_text`
- `_daily_percent_from_apr`
- `_apr_percent_from_daily`
- `_normalize_borrow_interest_timing`
- `_billable_interest_hours_from_elapsed_seconds`

### Accounting helpers

- `quantity_to_units`
- `units_to_quantity`
- `_quantity_step_units_from_precision`
- `_decimal_units`
- `notional_points`
- `fee_points`

## Behavior Change

`No`

This slice only extracts pure helpers and rewires `services/trading_engine.py`
to import them. No schema, API, route, fallback, wallet, ledger, order, margin,
bot, or price-fusion behavior was intentionally changed.

## Before / After Import Summary

### Before

- `services/trading_engine.py` defined all listed constants and pure helper
  functions inline.

### After

- `services/trading_engine.py` imports:
  - constants from `services.trading.constants`
  - strict parsing helpers from `services.trading.validators`
  - accounting helpers from `services.trading.accounting.units`
  - accounting helpers from `services.trading.accounting.notional`
  - accounting helpers from `services.trading.accounting.fees`

The legacy public entrypoint remains `services/trading_engine.py`.

## Tests Run

### Baseline Before Editing

- `python3 scripts/pre_push_checks.py --ci`
  - `11 PASS / 0 FAIL`
- `git diff --check`
  - `pass`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py`
  - `154 passed`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_reference_prices.py`
  - `35 passed`
- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_economy.py`
  - `7 passed`

### After Editing

- `git diff --check`
  - `pass`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py`
  - `154 passed`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_reference_prices.py`
  - `35 passed`
- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_economy.py`
  - `7 passed`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_slice1_fullpytest_20260506 PYTHONPATH=. python3 -m pytest -q tests/`
  - `1055 passed`
- `python3 scripts/pre_push_checks.py --ci`
  - `FAIL`
  - only failing check: `release id sync`
  - message: `significant code/config files changed but release_info.py was not updated`

## Pre-push Failure Assessment

The only post-edit failure is policy-driven:

- changed file: `services/trading_engine.py`
- blocked by: `scripts/prepush/checks/release_check.py`
- reason: this slice authorization does not allow touching
  `services/release_info.py` or release docs

There is no functional regression evidence in the trading suites or in full
pytest. The pre-push failure is caused by release-bump policy, not by test
breakage or behavior change.

## Rollback Plan

1. Remove the newly added `services/trading/` package files.
2. Restore `services/trading_engine.py` from `HEAD`.
3. Re-run:
   - `git diff --check`
   - `python3 -m pytest -q tests/test_trading_engine.py`
   - `python3 -m pytest -q tests/test_trading_reference_prices.py`
   - `python3 -m pytest -q tests/test_frontend_economy.py`

Because this slice does not touch schema or high-risk mutation code, rollback is
limited to import rewiring and file deletion.
