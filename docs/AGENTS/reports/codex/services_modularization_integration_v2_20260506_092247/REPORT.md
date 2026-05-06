## Trading Margin Integration Step

Branch: `03.Points`

Summary:
- Extracted margin risk/account/liquidation helpers into `services/trading/margin.py`
- Kept `services/trading_engine.py` as orchestration/façade
- Hardened risk-grade price handling so close/liquidation paths fail closed when `high_risk_blocked=true`
- Restricted `price_override_points` to internal liquidation replay only
- Replaced silent margin-risk notification failures with trading audit events

Files changed:
- `services/trading/margin.py`
- `services/trading_engine.py`
- `tests/test_trading_engine.py`
- `tests/test_security_issue_regressions.py`

Primary extracted helpers:
- `margin_risk_payload`
- `margin_position_payload_with_risk`
- `margin_free_margin_points`
- `margin_account_payload`
- `margin_summary_payload`
- `margin_liquidation_order_key`
- `margin_summary_payload_legacy`
- `notify_margin_risk_alerts`
- `close_margin_position`
- `scan_margin_liquidations`

Safety fixes folded into this step:
- `margin_risk_payload(..., strict_high_risk=True)` now raises on unavailable risk-grade price
- `price_override_points` now requires `allow_internal_price_override=True`
- short risk classification now accepts both `short` and legacy `margin_short`
- notification failures emit `TRADING_MARGIN_RISK_NOTIFY_FAILED`
- liquidation replay uses strict risk evaluation and internal-only override path

Behavior change:
- Public trading behavior: `No`
- Safety hardening inside margin risk/liquidation path: `Yes, intentional fail-closed correction required by review`

Tests:
- `git diff --check`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py -k "margin or liquidation or borrow or funding or trial_credit"`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py tests/test_trading_reference_prices.py tests/test_frontend_economy.py`
- `PYTHONPATH=. python3 -m pytest -q tests/test_security_issue_regressions.py -k "root_margin_trading_uses_simulated_funds_not_pointschain or margin_collateral_and_account_maintenance_are_supported"`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_margin_full_final_<timestamp> PYTHONPATH=. python3 -m pytest -q tests/`
- `python3 scripts/pre_push_checks.py --ci`

Results:
- Margin subset: `45 passed`
- Trading/reference/frontend suite: `200 passed`
- Security regression subset: `2 passed`
- Full pytest: `1059 passed`
- Pre-push: `10 PASS / 1 FAIL`

Known blocker:
- `release id sync`

Rollback plan:
- Revert commit `trading: extract margin risk and liquidation helpers`
- `services/trading_engine.py` still contains the orchestration boundaries required to re-inline margin logic if needed
