# Services Modularization Integration v2

## Step

Bot service extraction and grid module expansion.

## Exact Files Changed

- `services/trading/bots/__init__.py`
- `services/trading/bots/service.py`
- `services/trading/constants.py`
- `services/trading/grid.py`
- `services/trading_engine.py`

## Functional Boundary

This step keeps two full feature areas together instead of fragmenting them:

- `services/trading/bots/service.py`
  - trading bot CRUD
  - workflow live context glue
  - bot run orchestration
  - bot audit orchestration
- `services/trading/grid.py`
  - grid preview math
  - grid bot payload
  - grid bot CRUD
  - grid scan orchestration

## Exact Methods Delegated Out of `services/trading_engine.py`

### Bot service

- `_workflow_live_context`
- `_legacy_workflow`
- `_validate_bot_payload`
- `list_trading_bots`
- `save_trading_bot`
- `delete_trading_bot`
- `increase_trading_bot_max_runs`
- `_bot_trigger_hit`
- `_quantity_text_from_budget`
- `_bot_condition_checks`
- `_workflow_order_from_decision`
- `run_trading_bots`
- `run_trading_bot_once`
- `run_due_trading_bots`
- `_run_trading_bot_rows`
- `_record_bot_run`
- `_bot_audit_latest_map`
- `_bot_audit_enabled_at`
- `_bot_audit_is_eligible`
- `_bot_audit_run_findings`
- `_record_bot_audit_run`
- `_bot_audit_candidates`
- `_bot_audit_dashboard_on_conn`
- `run_due_bot_audits`
- `get_bot_audit_dashboard`

### Grid module

- `preview_grid_bot`
- `create_grid_bot`
- `list_grid_bots`
- `toggle_grid_bot`
- `delete_grid_bot`
- `scan_grid_bots`
- `_scan_one_grid_bot`

## File Size Check

No new over-fragmented wrapper files were introduced.

Largest cohesive modules after this step:

- `services/trading/margin.py`: `1559` LOC
- `services/trading/bots/service.py`: `1249` LOC
- `services/trading/orders.py`: `794` LOC
- `services/trading/grid.py`: `729` LOC

These are intentionally kept as complete functional modules rather than split into tiny shards.

## Behavior Change

No.

## Tests

### Targeted

- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py -k "audit or bot or workflow or indicator"`
  - `42 passed, 116 deselected`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py -k "grid or fee or preview"`
  - `18 passed, 140 deselected`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py tests/test_trading_reference_prices.py tests/test_frontend_economy.py`
  - `200 passed`

### Full

- `HACKME_RUNTIME_DIR=/tmp/hackme_web_fullpytest_20260506_bots_grid PYTHONPATH=. python3 -m pytest -q tests/`
  - `1059 passed`

### Pre-push

- `python3 scripts/pre_push_checks.py --ci`
  - `10 PASS / 1 FAIL`
  - only blocker: `release id sync`

## Rollback Plan

- Revert commit `trading: extract bot service and expand grid module`
- This restores bot/grid orchestration to `services/trading_engine.py`
- No schema migration or public API rollback is required
