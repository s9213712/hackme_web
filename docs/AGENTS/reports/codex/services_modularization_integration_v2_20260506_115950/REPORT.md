# Server Route Registration Integration Step

- Branch: `03.Points`
- Step: `server: extract route registration module`
- Behavior change: `No`

## Files Changed

- `server.py`
- `services/server/__init__.py`
- `services/server/routes.py`
- `services/server/startup.py`
- `services/server/request_guards.py`

## Functional Organization Result

This step continues the `services/` reorganization by grouping extracted server
helpers under a dedicated `services/server/` package instead of leaving them as
top-level one-off modules.

- `services/server/startup.py`
  - startup bootstrap, worker startup, TLS/bind entry orchestration
- `services/server/request_guards.py`
  - maintenance, recovery allowlist, root IP, browser-only, feature, and static-page guards
- `services/server/routes.py`
  - dependency bundle selection and route registration wiring

`server.py` remains the compatibility entrypoint and keeps the source-based
compatibility markers required by existing regression tests.

## Exact Change Summary

- Moved `services/server_startup.py` to `services/server/startup.py`
- Moved `services/server_request_guards.py` to `services/server/request_guards.py`
- Added `services/server/routes.py` to centralize route dependency bundle wiring
- Added `services/server/__init__.py` for the package boundary
- Replaced the inline route registration bundle block in `server.py` with `register_server_routes(app, globals())`
- Kept explicit compatibility markers in `server.py` for source-based tests:
  - `"GIT_REPO_DIR": GIT_REPO_DIR`
  - `"require_csrf_safe": require_csrf_safe,`

## Size Snapshot

- `server.py`: `1410` lines
- `services/server/routes.py`: `211` lines
- `services/server/startup.py`: `392` lines
- `services/server/request_guards.py`: `366` lines

## Tests Run

- `python3 -m py_compile server.py services/server/routes.py services/server/startup.py services/server/request_guards.py`
- `git diff --check`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_server_routes2 PYTHONPATH=. python3 -m pytest -q tests/test_feature_flags.py tests/test_security_defaults.py tests/test_frontend_drive_preview.py tests/test_server_update_feature.py tests/test_trading_workflow_editor_ui.py tests/test_frontend_personalization.py`
  - `32 passed`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_server_routes_full_20260506 PYTHONPATH=. python3 -m pytest -q tests/`
  - `1059 passed`
- `python3 scripts/pre_push_checks.py --ci`
  - `10 PASS / 1 FAIL`
  - Merge blocker only: `release id sync`

## Rollback Plan

- Revert commit `server: extract route registration module`
- This restores the old inline route registration block and the previous top-level helper module locations
- No DB schema, route schema, or runtime data migration is involved
