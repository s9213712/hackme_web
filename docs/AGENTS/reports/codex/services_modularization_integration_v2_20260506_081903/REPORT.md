## Trading Integration Step: grid module

Behavior change: No

### Files changed

- `services/trading/grid.py`
- `services/trading/payloads.py`
- `services/trading_engine.py`

### Extracted helper boundary

This step groups deterministic grid preview and payload helpers into a
single medium-granularity module.

Moved/extracted helpers:

- `grid_fee_rate_percent`
- `grid_levels`
- `grid_quantity_units`
- `grid_preview_fee_rates`
- `grid_preview_risk`
- `grid_preview_summary`
- `grid_bot_payload`

`TradingEngineService` still owns:

- `preview_grid_bot()` orchestration
- `create_grid_bot()` DB writes / order creation
- `scan_grid_bots()` and `_scan_one_grid_bot()` execution flow

### Import summary

Before:

- grid preview math lived inline in `services/trading_engine.py`
- grid bot payload lived in `services/trading/payloads.py`

After:

- `services/trading_engine.py` delegates grid pure helpers to
  `services.trading.grid`
- `services/trading/payloads.py` keeps general trading serializers and no
  longer owns the grid bot payload helper

### Regression check

An intermediate refactor briefly changed decimal precision for grid
preview fee math by routing one preview path through a float-based helper.
That was corrected before commit, restoring the original Decimal-based
preview calculation path. Final test results below are green.

### Tests

Syntax / diff hygiene:

- `python3 -m py_compile services/trading_engine.py services/trading/grid.py services/trading/payloads.py`
- `git diff --check`

Focused tests:

- `PYTHONPATH=. python3 -m pytest -q tests/test_grid_fee_model.py::test_grid_preview_calculates_gross_fee_net_and_break_even_with_decimal_math tests/test_grid_preview_api.py::test_grid_preview_api_returns_fee_break_even_and_risk_sections`
  - `2 passed`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py -k "grid or fee or preview"`
  - `18 passed, 136 deselected`

Full suite:

- `HACKME_RUNTIME_DIR=/tmp/hackme_web_grid_integration_retry_<timestamp> PYTHONPATH=. python3 -m pytest -q tests/`
  - `1055 passed`

Pre-push:

- `python3 scripts/pre_push_checks.py --ci`
  - `10 PASS / 1 FAIL`
  - merge blocker: `release id sync`

### Rollback plan

- revert the commit for this step on `03.Points`
- remove `services/trading/grid.py`
- restore inline grid preview helpers in `services/trading_engine.py`
- restore `grid_bot_payload` to `services/trading/payloads.py`
