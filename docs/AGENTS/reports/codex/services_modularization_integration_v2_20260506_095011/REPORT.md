## Trading Orders Integration Step

Branch: `03.Points`

Summary:
- Extracted spot order placement / matching / execution / cancellation orchestration into `services/trading/orders.py`
- Kept `services/trading_engine.py` as stable public façade
- Preserved existing payload / audit / notification / PnL semantics
- Corrected one accidental `cancel_order` response-shape regression during extraction

Files changed:
- `services/trading/orders.py`
- `services/trading_engine.py`

Primary extracted methods:
- `place_order`
- `match_open_limit_orders`
- `execute_order`
- `cancel_order`

Behavior change:
- Public trading behavior: `No`

Validation:
- `git diff --check`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py -k "order or payload or position or fee or pnl or grid"`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py tests/test_trading_reference_prices.py tests/test_frontend_economy.py`
- `PYTHONPATH=. python3 -m pytest -q tests/test_security_issue_regressions.py`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_orders_full_final_<timestamp> PYTHONPATH=. python3 -m pytest -q tests/`
- `python3 scripts/pre_push_checks.py --ci`

Results:
- Orders/grid/payload subset: `52 passed`
- Trading/reference/frontend suite: `200 passed`
- Security regressions: `32 passed`
- Full pytest: `1059 passed`
- Pre-push: `10 PASS / 1 FAIL`

Known blocker:
- `release id sync`

Granularity check:
- `orders.py` is a single medium-granularity module at ~794 lines
- No new wrapper shard files were introduced
- Current extracted files that are very small are limited to `__init__.py`, `constants.py`, and a few compact cohesive helpers, not compatibility shards

Rollback plan:
- Revert commit `trading: extract order orchestration module`
- `services/trading_engine.py` public method names remain unchanged, so re-inline rollback is straightforward
