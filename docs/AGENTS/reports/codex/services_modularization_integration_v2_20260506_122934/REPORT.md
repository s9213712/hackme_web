# Services Modularization / Issue Cleanup Report

Date: `2026-05-06`
Branch: `03.Points`

## Scope

This batch closed the remaining issue-focused blockers that were still open
after the trading/server modularization work:

- add a global API exception handler so `/api/...` no longer falls back to
  Flask's default HTML 5xx page
- document the Cloud Drive trust boundary for `standard_plain`,
  `server_encrypted`, and strict `e2ee`
- remove the remaining tracked local-path leak from
  `security/trading_backtest_benchmark.py`
- align release metadata and required docs for the current code state

## Files Changed

- `server.py`
- `docs/06_SECURITY_MODEL.md`
- `tests/test_security_defaults.py`
- `security/trading_backtest_benchmark.py`
- `services/release_info.py`
- `docs/UPDATE_SUMMARY.md`
- `README.md`
- `docs/README.zh-TW.md`
- `docs/For_developer.md`

## Behavior Notes

- `/api/...` unhandled exceptions now return a stable JSON envelope:
  - `{"ok": false, "msg": "...", "error": "..."}`
- non-API requests still keep a minimal non-JSON 500 fallback
- no public API success schema changed
- no DB schema changed

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_security_defaults.py`
  - `6 passed`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_errorhandler_full_20260506 PYTHONPATH=. python3 -m pytest -q tests/`
  - `1064 passed`
- `python3 scripts/pre_push_checks.py --ci`
  - `11 PASS / 0 FAIL`
- `git diff --check`
  - `pass`

## Outcome

Issue-focused cleanup is in a releasable state:

- API error handling is consistent
- security docs now explain the actual encryption trust model
- local path leak is removed
- release metadata is synchronized
