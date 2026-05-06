# Server Runtime Bootstrap Integration Step

- Branch: `03.Points`
- Step: `server: extract runtime bootstrap module`
- Behavior change: `No`

## Files Changed

- `server.py`
- `services/server/runtime.py`

## Functional Organization Result

This step continues the `services/` reorganization by moving runtime,
environment, secret-bootstrap, and local TLS/bootstrap helpers into a dedicated
server runtime module.

- `services/server/runtime.py`
  - env/path readers
  - DB-backed storage-root setting lookup
  - secret file load/create helpers
  - local TLS file generation
  - chain seed loading
  - JSON load/save helpers
  - trusted proxy/IP parsing
  - numeric/boolean/samesite env normalization

`server.py` still keeps:

- runtime path assignment lines required by source-based tests
- CSP / upload-size configuration
- Flask app construction
- guard wrappers and route façade

## Size Snapshot

- `server.py`: `1238` lines
- `services/server/runtime.py`: `208` lines

## Tests Run

- `python3 -m py_compile server.py services/server/runtime.py services/server/routes.py services/server/startup.py services/server/request_guards.py`
- `git diff --check`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_server_runtime PYTHONPATH=. python3 -m pytest -q tests/test_security_defaults.py tests/test_security_issue_regressions.py tests/test_feature_flags.py tests/test_server_update_feature.py tests/test_frontend_drive_preview.py tests/test_frontend_personalization.py tests/test_trading_workflow_editor_ui.py`
  - `64 passed`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_server_runtime_full_20260506 PYTHONPATH=. python3 -m pytest -q tests/`
  - `1059 passed`
- `python3 scripts/pre_push_checks.py --ci`
  - `10 PASS / 1 FAIL`
  - Merge blocker only: `release id sync`

## Rollback Plan

- Revert commit `server: extract runtime bootstrap module`
- This restores the runtime/env/secret/bootstrap helpers to `server.py`
- No DB schema or public API schema migration is involved
