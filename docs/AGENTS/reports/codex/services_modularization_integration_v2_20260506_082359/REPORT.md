## Trading Integration Step: audit and notifications

Behavior change: No

### Files changed

- `services/trading/audit.py`
- `services/trading/notifications.py`
- `services/trading_engine.py`

### Extracted helper boundary

This step moves trading audit event insertion and notification payload /
wrapper helpers into dedicated medium-granularity modules.

Moved/extracted helpers:

- `emit_trading_audit_event`
- `create_trading_user_notification`
- `create_trading_root_notification`
- `trade_fill_notification_payload`
- `insufficient_balance_notification_payload`
- `margin_liquidated_notification_payload`
- `margin_near_liquidation_notification_payload`
- `margin_price_jump_notification_payload`
- `bot_audit_notification_payload`

`TradingEngineService` still owns:

- notification trigger timing
- unread margin alert deduplication query
- bot audit run DB write orchestration
- all trading state mutations

### Import summary

Before:

- `services/trading_engine.py` owned inline audit event insert SQL
- `services/trading_engine.py` owned inline notification body assembly and
  direct notification wrapper calls

After:

- `services/trading_engine.py` delegates audit insert formatting to
  `services.trading.audit`
- `services/trading_engine.py` delegates notification body assembly and
  notification wrapper calls to `services.trading.notifications`

### Tests

Syntax / diff hygiene:

- `python3 -m py_compile services/trading_engine.py services/trading/audit.py services/trading/notifications.py`
- `git diff --check`

Focused tests:

- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py -k "audit or notification"`
  - `7 passed, 147 deselected`

Full suite:

- `HACKME_RUNTIME_DIR=/tmp/hackme_web_audit_notify_<timestamp> PYTHONPATH=. python3 -m pytest -q tests/`
  - `1055 passed`

Pre-push:

- `python3 scripts/pre_push_checks.py --ci`
  - `10 PASS / 1 FAIL`
  - merge blocker: `release id sync`

### Rollback plan

- revert the commit for this step on `03.Points`
- remove `services/trading/audit.py`
- remove `services/trading/notifications.py`
- restore inline audit / notification helpers in `services/trading_engine.py`
