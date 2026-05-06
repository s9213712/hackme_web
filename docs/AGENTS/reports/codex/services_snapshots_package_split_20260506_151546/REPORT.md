# Snapshots Package Split Report

Date: `2026-05-06`
Branch: `03.Points`
Release ID: `2026.05.06-146`

## Scope

Reduced `services/snapshots.py` by moving the live implementation into a real
package while keeping import compatibility and source-based regression coverage.

## Files Changed

- `services/snapshots.py`
- `services/snapshots/__init__.py`
- `services/snapshots/schema.py`
- `services/snapshots/service.py`
- `services/snapshots/server_mode.py`
- `services/release_info.py`
- `README.md`
- `docs/README.zh-TW.md`
- `docs/For_developer.md`
- `docs/UPDATE_SUMMARY.md`

## New Module Boundaries

- `services/snapshots/schema.py`
  - snapshot/server-mode constants
  - hash/signature helpers
  - runtime-path helper
  - `SnapshotResult`
  - `verify_mode_switch_log_hash_chain`
  - `ensure_snapshot_schema`
- `services/snapshots/service.py`
  - `SnapshotService`
  - snapshot create/list/get/verify/export/import/delete
  - restore/reset orchestration
- `services/snapshots/server_mode.py`
  - `ServerModeService`
  - mode profile management
  - production gate
  - mode checkpoints
  - tester token/shadow tooling
  - superweak/incident recovery

## Compatibility

- `import services.snapshots` now resolves to the package
  `services/snapshots/__init__.py`.
- Existing imports remain available from `services.snapshots`, including:
  - `SnapshotService`
  - `ServerModeService`
  - `ensure_snapshot_schema`
  - `MODE_CONFIRM_PHRASES`
  - `PRODUCTION_REQUIRED_REPORT_TYPES`
  - `BUILTIN_SECURITY_PROFILES`
  - `_canonical_json_text`
  - `_hmac_sha256`
  - `_production_report_signature_payload`
- Top-level `services/snapshots.py` remains as a tiny compatibility/source
  facade so file-path-based regression checks still have a stable target.

## Extra Fix Included

- `_default_runtime_base_dir()` now fails closed when `cwd/runtime` exists as a
  non-directory file, instead of silently creating a sibling fallback path.
- `ServerModeService(snapshot_service=None)` now prefers
  `integrity_guard.base_dir / "runtime"` when an Integrity Guard instance is
  available, so tests and app-local server-mode state do not need to touch the
  repo root runtime guard at all.

## Validation

- `git diff --check`
  - `pass`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py -k "ensure_snapshot_schema or funding or backtest or workflow or margin"`
  - `64 passed, 94 deselected`
- `PYTHONPATH=. python3 -m pytest -q tests/test_snapshots.py tests/test_production_gate_enforcement.py tests/test_integrity_guard.py tests/test_shadow_schema.py tests/test_smv2_acceptance.py tests/test_security_issue_regressions.py`
  - `110 passed`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_snapshots_pkg_20260506 PYTHONPATH=. python3 -m pytest -q tests/`
  - `1073 passed`

## Rollback Plan

1. Revert the snapshots package split commit.
2. Restore the single-file implementation in `services/snapshots.py`.
3. Re-run:
   - `tests/test_snapshots.py`
   - `tests/test_production_gate_enforcement.py`
   - `tests/test_integrity_guard.py`
   - `tests/test_trading_engine.py -k "ensure_snapshot_schema or funding or backtest or workflow or margin"`
   - `python3 scripts/pre_push_checks.py --ci`
