## Trading Integration Step 6

- Date: 2026-05-06 07:57:02 Asia/Taipei
- Branch: `03.Points`
- Behavior change: `No`

### Scope

Extract pure workflow validation / trigger evaluation and pure indicator helpers
from `services/trading_engine.py` into medium-granularity bot modules:

- `services/trading/bots/indicators.py`
- `services/trading/bots/workflow.py`

`services/trading_engine.py` remains the facade and keeps bot execution,
order creation, DB access, and workflow order orchestration in place.

### Files Changed

- `services/trading_engine.py`
- `services/trading/bots/__init__.py`
- `services/trading/bots/indicators.py`
- `services/trading/bots/workflow.py`
- `docs/AGENTS/reports/codex/services_modularization_integration_v2_20260506_075702/REPORT.md`

### Functions Moved

- `_condition_label`
- `_validate_workflow`
- `_validate_workflow_graph`
- `_build_workflow_indicator_series`
- `_workflow_indicator_context`
- `_workflow_condition_hit`
- `_workflow_graph_decision`
- `_workflow_decision`

### Before / After Boundary

Before:

- workflow validation, condition evaluation, graph traversal, and indicator
  math lived inline inside `services/trading_engine.py`

After:

- pure workflow helpers live in `services.trading.bots.workflow`
- pure indicator helpers live in `services.trading.bots.indicators`
- engine methods keep the same names and delegate to extracted helpers
- bot execution, workflow order generation, and DB orchestration remain in
  `services/trading_engine.py`

### Behavior Freeze Confirmation

- No bot execution change
- No order creation change
- No grid bot change
- No backtest behavior change
- No DB/schema/route change
- No indicator formula change
- No workflow trigger semantic change

### Tests Run

- `python3 -m py_compile services/trading_engine.py services/trading/bots/__init__.py services/trading/bots/indicators.py services/trading/bots/workflow.py`
  - `pass`
- `git diff --check`
  - `pass`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py -k "workflow or indicator or bollinger or backtest or bot"`
  - `50 passed, 104 deselected`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_reference_prices.py tests/test_frontend_economy.py`
  - `42 passed`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_bots_workflow_<timestamp> PYTHONPATH=. python3 -m pytest -q tests/`
  - `1055 passed`
- `python3 scripts/pre_push_checks.py --ci`
  - `10 PASS / 1 FAIL`
  - merge blocker: `release id sync`

### Rollback Plan

If this step needs to be reverted:

1. revert only this integration commit
2. inline the moved workflow/indicator helpers back into `services/trading_engine.py`
3. remove `services/trading/bots/`
4. rerun the same targeted tests, full pytest, and pre-push checks
