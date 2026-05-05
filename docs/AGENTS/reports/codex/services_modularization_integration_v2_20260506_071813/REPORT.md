**Scope**
First trading integration commit on `03.Points`, aligned to the `Services Modularization Integration Plan v2` baseline.

**Base Commit**
- `558685045b2e10b91b5c92b1feb6fc622b6b29b5`

**Files Changed**
- `services/trading/__init__.py`
- `services/trading/settings_schema.py`
- `services/trading/accounting/__init__.py`
- `services/trading/accounting/core.py`
- `services/trading/accounting/units.py`
- `services/trading/accounting/notional.py`
- `services/trading/accounting/fees.py`
- `services/trading_engine.py`

**Functions Moved / Centralized**
- Moved into `services/trading/accounting/core.py`:
  - `quantity_to_units`
  - `units_to_quantity`
  - `_quantity_step_units_from_precision`
  - `_decimal_units`
  - `notional_points`
  - `fee_points`
- Centralized in `services/trading/settings_schema.py`:
  - trading root bool setting key map
  - raw bool/int/float/choice parsing helpers
  - input bool/int/float/text/choice normalization helpers
  - APR/daily-rate payload normalization helpers used by `_settings_payload` and `update_root_settings`

**Before / After Import Summary**
- Before:
  - `services.trading_engine` imported quantity/notional/fee helpers from three separate compatibility modules.
  - settings validation lived inline inside `_settings_payload` and `update_root_settings`.
- After:
  - `services.trading_engine` imports accounting primitives from `services.trading.accounting.core`.
  - `services.trading.accounting.{units,notional,fees}` remain as compatibility wrappers.
  - settings parsing/normalization is delegated to `services.trading.settings_schema`.

**Behavior Change**
- `No`

**API / Schema Guard**
- No DB schema changes
- No migration changes
- No public API schema changes
- No route changes

**Baseline Snapshot Before Editing**
- `git diff --check`: pass
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py tests/test_trading_reference_prices.py tests/test_frontend_economy.py`
  - `196 passed`
- `HACKME_RUNTIME_DIR=/tmp/... PYTHONPATH=. python3 -m pytest -q tests/`
  - `1055 passed`
- `python3 scripts/pre_push_checks.py --ci`
  - `11 PASS / 0 FAIL`

**Verification After Editing**
- `git diff --check`
  - pass
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py tests/test_trading_reference_prices.py tests/test_frontend_economy.py`
  - `196 passed`
- `HACKME_RUNTIME_DIR=/tmp/... PYTHONPATH=. python3 -m pytest -q tests/`
  - `1055 passed`
- `python3 scripts/pre_push_checks.py --ci`
  - `10 PASS / 1 FAIL`

**Pre-push Status**
- Merge blocker: `release id sync`
- Failure detail:
  - `significant code/config files changed but release_info.py was not updated`

**Rationale**
- This step starts converging toward the final medium-granularity trading package without over-fragmenting:
  - shared numeric primitives now live in `accounting/core.py`
  - existing smaller files remain as wrappers for compatibility and rollback safety
  - settings parsing is centralized without changing DB write orchestration

**Rollback Plan**
1. Revert this commit only.
2. `services.trading_engine` will fall back to its pre-integration imports and inline settings parsing.
3. Delete `services/trading/settings_schema.py` and `services/trading/accounting/core.py`.
4. The compatibility wrappers already preserve the old import surface, so rollback is isolated to this step.
