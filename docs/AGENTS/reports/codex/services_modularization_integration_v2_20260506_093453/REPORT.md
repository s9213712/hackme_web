## Trading Margin Integration Step 2

Branch: `03.Points`

Summary:
- Extended `services/trading/margin.py` from risk/liquidation helpers into the main margin orchestration boundary
- Moved `open_margin_position` and `add_margin_collateral` out of `services/trading_engine.py`
- Kept `services/trading_engine.py` as public façade with stable method names
- Updated path-sensitive regression tests to assert behavior across the new helper location instead of hard-coding the old file body

Files changed:
- `services/trading/margin.py`
- `services/trading_engine.py`
- `tests/test_security_issue_regressions.py`

Primary extracted methods:
- `open_margin_position`
- `add_margin_collateral`

Still intentionally left in `services/trading_engine.py`:
- `_borrowing_settings`
- `_assert_borrowing_enabled`
- `_minimum_margin_collateral_points`
- `_accrue_margin_interest`
- verification / DB orchestration outside the margin boundary

Behavior change:
- Public trading behavior: `No`
- Module boundary: margin entry / collateral orchestration now delegates through `services/trading/margin.py`

Tests:
- `git diff --check`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py -k "margin or liquidation or borrow or funding or trial_credit"`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py tests/test_trading_reference_prices.py tests/test_frontend_economy.py`
- `PYTHONPATH=. python3 -m pytest -q tests/test_security_issue_regressions.py -k "margin_collateral_without_client_key_uses_stable_retry_key or root_margin_trading_uses_simulated_funds_not_pointschain or margin_collateral_and_account_maintenance_are_supported"`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_margin_open_full_final2_<timestamp> PYTHONPATH=. python3 -m pytest -q tests/`
- `python3 scripts/pre_push_checks.py --ci`

Results:
- Margin subset: `45 passed`
- Trading/reference/frontend suite: `200 passed`
- Security regression subset: `3 passed`
- Full pytest: `1059 passed`
- Pre-push: `10 PASS / 1 FAIL`

Known blocker:
- `release id sync`

Rollback plan:
- Revert commit `trading: move margin entry and collateral orchestration`
- `services/trading_engine.py` method names stay stable, so re-inlining remains straightforward
