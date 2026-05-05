## Trading Integration Step 3

- Date: 2026-05-06 07:33:43 Asia/Taipei
- Branch: `03.Points`
- Commit status: local changes only at report time
- Behavior change: `No`

### Scope

Extract pure trading payload / serializer helpers from `services/trading_engine.py`
into a single medium-granularity module:

- `services/trading/payloads.py`

`services/trading_engine.py` remains the compatibility facade and keeps orchestration,
DB access, and public method names unchanged.

### Files Changed

- `services/trading_engine.py`
- `services/trading/payloads.py`
- `docs/AGENTS/reports/codex/services_modularization_integration_v2_20260506_073343/REPORT.md`

### Functions Moved

- `_order_payload`
- `_bot_payload`
- `_bot_run_payload`
- `_market_payload`
- `_position_payload`
- `_futures_position_payload`
- `_margin_position_payload`
- `_fill_payload`
- `_grid_bot_payload`
- `_bot_audit_label`
- `_bot_audit_eligibility_reason_label`

### Before / After Import Summary

Before:

- `services/trading_engine.py` defined all payload / serializer helpers inline.

After:

- `services/trading_engine.py` imports pure payload helpers from
  `services.trading.payloads`
- local public helper method names remain stable and delegate to the extracted
  functions

### Payload Schema Comparison

- No field rename
- No field removal
- No new response field added
- No semantic change in payload assembly
- Response schemas remain byte-for-byte equivalent for the same inputs, except
  unordered JSON object key order

### Tests Before

- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_reference_prices.py tests/test_frontend_economy.py`
  - `42 passed`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py -k "payload or dashboard or order or position or bot or grid or audit"`
  - `62 passed, 92 deselected`
- `python3 scripts/pre_push_checks.py --ci`
  - `10 PASS / 1 FAIL`
  - merge blocker: `release id sync`

### Tests After

- `python3 -m py_compile services/trading_engine.py services/trading/payloads.py`
  - `pass`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_reference_prices.py tests/test_frontend_economy.py`
  - `42 passed`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py -k "payload or dashboard or order or position or bot or grid or audit"`
  - `62 passed, 92 deselected`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_integration_step3_<timestamp> PYTHONPATH=. python3 -m pytest -q tests/`
  - `1055 passed`
- `python3 scripts/pre_push_checks.py --ci`
  - `10 PASS / 1 FAIL`
  - merge blocker: `release id sync`

### Rollback Plan

If this step needs to be reverted:

1. revert the local integration commit for this step only
2. restore inline payload helpers in `services/trading_engine.py`
3. remove `services/trading/payloads.py`
4. rerun the same targeted trading tests and full pytest

