# Server Modularization Integration v2

## Step

Extract `server.py` request guard and feature-gate logic into a single
`services/server_request_guards.py` module.

## Files Changed

- `server.py`
- `services/server_request_guards.py`

## Boundary

This step keeps one cohesive request-guard boundary together:

- maintenance bypass parsing/validation
- root recovery allowlist checks
- root IP whitelist enforcement
- browser-only mode enforcement
- maintenance / incident-lockdown request gating
- feature gate routing
- required-password-change enforcement
- protected trading workflow editor static-page gating

The Flask `@app.before_request` decorators remain in `server.py` so hook
ordering and the public entrypoint stay explicit.

## Functions Moved

- `get_request_maintenance_bypass_token`
- `has_valid_maintenance_bypass`
- `path_is_root_recovery_allowed_during_lockdown`
- `root_ip_is_allowed`
- `feature_gate_for_path`
- protected static-page guard logic
- root IP whitelist guard logic
- browser-only mode guard logic
- maintenance / incident-lockdown guard logic
- feature flag guard logic
- required-password-change guard logic

`server.py` keeps thin wrapper functions for compatibility and for
source-based tests that intentionally inspect some guard markers there.

## Fragmentation Check

- `server.py`: `1588` LOC
- `services/server_request_guards.py`: `366` LOC

No tiny compatibility shards were introduced.

## Behavior Change

No.

## Validation

- `python3 -m py_compile server.py services/server_request_guards.py`
- `git diff --check`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_server_guards PYTHONPATH=. python3 -m pytest -q tests/test_feature_flags.py tests/test_security_defaults.py tests/test_frontend_drive_preview.py tests/test_server_update_feature.py`
  - `29 passed`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_server_guards_fix PYTHONPATH=. python3 -m pytest -q tests/test_trading_workflow_editor_ui.py tests/test_feature_flags.py tests/test_security_defaults.py tests/test_frontend_drive_preview.py tests/test_server_update_feature.py`
  - `31 passed`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_fullpytest_20260506_server_guards_fix PYTHONPATH=. python3 -m pytest -q tests/`
  - `1059 passed`
- `python3 scripts/pre_push_checks.py --ci`
  - `10 PASS / 1 FAIL`
  - only blocker: `release id sync`

## Rollback Plan

Revert the single commit for this step. The decorator wrappers in
`server.py` isolate the extraction cleanly.
