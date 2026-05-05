**Scope**
Second trading integration commit on `03.Points`, extracting pure `price_fusion` helpers into the final medium-granularity package shape.

**Base Commit**
- `e8e9fa8` `trading: bootstrap settings and accounting core`

**Files Changed**
- `services/trading/price_fusion/__init__.py`
- `services/trading/price_fusion/orderbook.py`
- `services/trading/price_fusion/weights.py`
- `services/trading/price_fusion/context.py`
- `services/trading_engine.py`

**Functions Moved**
- Into `services/trading/price_fusion/orderbook.py`
  - `provider_depth_request_limit`
  - `parse_orderbook_side`
  - `depth_notional_snapshot`
  - `depth_notional_score`
- Into `services/trading/price_fusion/weights.py`
  - `price_fusion_effective_score`
  - `price_fusion_reference_score`
  - `apply_price_fusion_weight_cap`
  - `build_price_fusion_weight_model`
- Into `services/trading/price_fusion/context.py`
  - `price_usage_label`
  - `price_source_label`
  - `price_context_confidence`
  - `price_context_risk_grade_usable`

**Before / After Import Summary**
- Before:
  - `services.trading_engine` owned all pure `price_fusion` helper logic inline.
- After:
  - `services.trading_engine` delegates deterministic orderbook/weight/context helpers to `services.trading.price_fusion.*`
  - provider fetchers, fallback handling, and high-risk gate enforcement remain in `services.trading_engine`

**Behavior Change**
- `No`

**Formula / Risk Guard Confirmation**
- No provider API fetch behavior changes
- No weight formula changes
- No fallback behavior changes
- No risk gate semantic changes
- No DB/schema changes
- No route/API changes

**Verification**
- `python3 -m py_compile services/trading_engine.py services/trading/price_fusion/context.py services/trading/price_fusion/orderbook.py services/trading/price_fusion/weights.py`
  - pass
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py -k "price_fusion or depth_notional or risk_grade"`
  - `20 passed, 134 deselected`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_reference_prices.py tests/test_frontend_economy.py`
  - `42 passed`
- `HACKME_RUNTIME_DIR=/tmp/... PYTHONPATH=. python3 -m pytest -q tests/`
  - `1055 passed`
- `python3 scripts/pre_push_checks.py --ci`
  - `10 PASS / 1 FAIL`

**Pre-push Status**
- Merge blocker: `release id sync`

**Rollback Plan**
1. Revert this commit only.
2. `services.trading_engine` falls back to its previous inline helper implementations.
3. Delete the `services/trading/price_fusion/` package.
