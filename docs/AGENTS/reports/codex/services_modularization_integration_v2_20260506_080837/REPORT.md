## Trading Integration Step: backtest module

Behavior change: No

### Files changed

- `services/trading/backtest.py`
- `services/trading_engine.py`

### Extracted helper boundary

This step keeps `TradingEngineService.backtest_trading_bot()` as the
orchestration façade and moves only deterministic backtest helpers into
`services/trading/backtest.py`.

Moved/extracted helpers:

- `filter_backtest_candles_by_range`
- `build_backtest_initial_state`
- `backtest_equity_value`
- `update_backtest_drawdown`
- `build_backtest_equity_point`
- `backtest_anchor_price`
- `build_backtest_outlier_warning`
- `push_recent_valid_price`
- `backtest_segment_count`
- `iter_backtest_segments`
- `build_backtest_range_warnings`
- `build_backtest_result_payload`

### Import summary

Before:

- `services/trading_engine.py` owned inline range filtering, initial
  backtest state construction, anchor/outlier helpers, segment splitting,
  and final result payload assembly.

After:

- `services/trading_engine.py` imports those pure helpers from
  `services.trading.backtest`
- strategy selection, workflow decisions, grid state transitions, and
  trade state mutation remain in the façade

### Tests

Syntax / diff hygiene:

- `python3 -m py_compile services/trading_engine.py services/trading/backtest.py`
- `git diff --check`

Targeted tests:

- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py -k "backtest or candle or outlier or bollinger or workflow"`
  - `32 passed, 122 deselected`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_reference_prices.py tests/test_frontend_economy.py`
  - `42 passed`

Full suite:

- `HACKME_RUNTIME_DIR=/tmp/hackme_web_backtest_integration_<timestamp> PYTHONPATH=. python3 -m pytest -q tests/`
  - `1055 passed`

Pre-push:

- `python3 scripts/pre_push_checks.py --ci`
  - `10 PASS / 1 FAIL`
  - merge blocker: `release id sync`

### Rollback plan

- revert the commit for this step on `03.Points`
- remove `services/trading/backtest.py`
- restore the inline helper logic inside `services/trading_engine.py`
