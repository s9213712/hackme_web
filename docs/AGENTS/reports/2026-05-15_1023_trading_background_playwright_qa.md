# Trading Background Playwright QA

- Date: 2026-05-15 10:23 Asia/Taipei
- Runtime: `/tmp/hackme_web_trading_bg_qa9_20260515/hackme_web`
- URL: `https://127.0.0.1:55348`
- Mode: isolated `dev_ready` with explicit trading background QA opt-in
- Result: PASS

## Scope

This run verified that trading calculations continue after every browser context is closed. The Playwright QA created multiple users and exercised spot orders, limit matching, stop-loss, take-profit, conditional bot trigger, margin take-profit, hourly interest accrual, forced liquidation, reserve-pool accounting, root background UI/API visibility, and concurrent order stress.

The QA intentionally did not keep root or user sessions open while waiting for background jobs. Browser contexts were closed before background matching, bot, TP/SL, interest, and liquidation assertions.

## Playwright Result

- Script: `scripts/testing/playwright_trading_background_correctness.py`
- Checks: 43/43 passed
- Failures: none
- Artifacts:
  - `/tmp/hackme_web_trading_bg_qa9_20260515/hackme_web/runtime/reports/qa/trading_background_correctness/trading_background_correctness.json`
  - `/tmp/hackme_web_trading_bg_qa9_20260515/hackme_web/runtime/reports/qa/trading_background_correctness/trading_background_correctness.md`

Key assertions passed:

- Background worker matched a limit order without any active login.
- Background worker triggered spot stop-loss without any active login.
- Background worker triggered conditional bot trade without any active login.
- Background worker accrued margin interest without any active login.
- Background worker triggered spot take-profit without any active login.
- Background worker triggered margin take-profit without any active login.
- Background worker liquidated the margin account without any active login.
- Root background UI panel and job/audit APIs were wired.
- Background job run log contained expected jobs and no recorded failures.
- Concurrent order stress completed without 5xx: 60 requests, 57 success, statuses `[200, 403]`.
- Trading state verification and PointsChain verification passed after background/stress flow.
- Wallet balances, frozen balances, and spot locked quantities remained non-negative.
- Trading reserve stayed non-negative and collected income: `10000 -> 10006`.

The two stress `403` responses were CSRF/session races from intentionally concurrent browser requests. They did not create 5xx responses or accounting drift.

## Validation

Passed:

- `python3 -m py_compile services/trading/background_engine.py services/trading/price_runtime.py services/trading/admin.py scripts/testing/playwright_trading_background_correctness.py`
- `bash -n test_for_develop.sh`
- `node --check public/js/50-admin.js public/js/55-economy.js public/js/56-trading.js`
- `pytest -q tests/trading/core/test_trading_background_engine.py tests/platform/test_routing_service.py tests/server_mode/test_smv2_acceptance.py` (`64 passed`)
- `pytest -q tests/trading`
- `python3 scripts/trading/validation/trading_exchange_validation.py` (`21/21 passed`)

Server log scan found no `Traceback`, `ERROR`, `Exception`, `database is locked`, or HTTP `500` entries in the isolated run log.

The isolated QA server was stopped after validation; port `55348` is no longer listening.

## Implementation Notes

- `test_for_develop.sh` now applies the selected server mode to both main DB and `control.db`, preventing isolated QA from starting in an unintended runtime mode.
- `dev_ready` background trading remains disabled by default. Isolated QA must explicitly set `trading.background_worker_dev_ready_enabled`.
- The QA live-price provider requires both environment opt-in and DB setting opt-in. Production and normal manual-root pricing still fail closed for high-risk operations.
- `trading_exchange_validation.py` now runs directly from the repo root context, registers the DB-level `app_mode()` guard, and writes default reports to `runtime/reports/trading_validation`.
