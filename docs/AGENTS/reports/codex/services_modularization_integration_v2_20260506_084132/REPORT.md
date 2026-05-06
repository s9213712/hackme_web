## Trading Integration Step

Files changed:
- `services/trading_engine.py`
- `services/trading/accounting/interest.py`
- `services/trading/accounting/trial_credit.py`
- `services/trading/accounting/funding_pool.py`
- `services/trading/bots/audit.py`

Helpers extracted:
- margin interest pure calculations
- trial credit expiry / allocation / payload helpers
- funding pool payload / outstanding-principal helpers
- bot audit eligibility / scoring / dashboard item helpers

Import summary:
- `services/trading_engine.py` now delegates pure accounting helpers to:
  - `services.trading.accounting.interest`
  - `services.trading.accounting.trial_credit`
  - `services.trading.accounting.funding_pool`
- `services/trading_engine.py` now delegates pure bot-audit helpers to:
  - `services.trading.bots.audit`

Behavior change: No

Validation:
- `git diff --check`: pass
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest -q /home/s92137/hackme_web/tests/test_trading_engine.py -k "audit or bot or trial_credit or funding or wallet or ledger or interest or margin"`: `62 passed, 92 deselected`
- `bash -lc 'cd /home/s92137/hackme_web && HACKME_RUNTIME_DIR=/tmp/hackme_web_finish2_$(date +%Y%m%d%H%M%S) PYTHONPATH=/home/s92137/hackme_web python3 -m pytest -q tests/'`: `1055 passed`
- `python3 /home/s92137/hackme_web/scripts/pre_push_checks.py --ci`: `10 PASS / 1 FAIL`

Pre-push status:
- only blocker: `release id sync`

Rollback plan:
- revert this commit only
- keep earlier integration commits intact
- `services/trading_engine.py` still remains the compatibility facade
