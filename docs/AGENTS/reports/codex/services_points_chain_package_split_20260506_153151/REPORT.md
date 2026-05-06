# PointsChain Package Split Report

Date: `2026-05-06`
Branch: `03.Points`
Release ID: `2026.05.06-147`

## Scope

Reduced `services/points_chain.py` by moving the live implementation into a
real package while keeping import compatibility and source-based regression
coverage.

## Files Changed

- `services/points_chain.py`
- `services/points_chain/__init__.py`
- `services/points_chain/schema.py`
- `services/points_chain/service.py`
- `services/release_info.py`
- `README.md`
- `docs/README.zh-TW.md`
- `docs/For_developer.md`
- `docs/UPDATE_SUMMARY.md`

## New Module Boundaries

- `services/points_chain/schema.py`
  - currency constants
  - public/private metadata helpers
  - ledger/block hash helpers
  - `ensure_points_economy_schema`
  - `ChainModeViolation`
- `services/points_chain/service.py`
  - `PointsLedgerService`
  - wallet/ledger writes
  - block sealing / verify / replay
  - admin reward / pending reward / rollback flows

## Compatibility

- `import services.points_chain` now resolves to the package
  `services/points_chain/__init__.py`.
- Existing imports remain available from `services.points_chain`, including:
  - `PointsLedgerService`
  - `ensure_points_economy_schema`
  - `DISPLAY_CURRENCY`
  - `DEFAULT_BLOCK_LEDGER_THRESHOLD`
  - `DEFAULT_BLOCK_MAX_INTERVAL_SECONDS`
  - `ChainModeViolation`
- The package facade also exposes `time`, so tests that monkeypatch
  `services.points_chain.time.time` continue to work.
- Top-level `services/points_chain.py` remains as a tiny source facade so
  file-path-based regression checks still have a stable target for the
  pending-reward maker-checker contract.

## Validation

- `git diff --check`
  - `pass`
- `PYTHONPATH=. python3 -m pytest -q tests/test_points_chain.py tests/test_shadow_schema.py tests/test_db_mode_triggers.py tests/test_integrity_guard.py tests/test_security_issue_regressions.py`
  - `100 passed`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py tests/test_video_tips.py tests/test_trading_market_registry.py tests/test_admin_points_wallet.py tests/test_grid_fee_model.py tests/test_grid_preview_api.py tests/test_trading_price_contexts.py tests/test_trading_websocket_inputs.py tests/test_workflow_templates_codex.py`
  - `185 passed`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_points_chain_pkg_20260506 PYTHONPATH=. python3 -m pytest -q tests/`
  - `1073 passed`
- `python3 scripts/pre_push_checks.py --ci`
  - `11 PASS / 0 FAIL`

## Rollback Plan

1. Revert the PointsChain package split commit.
2. Restore the single-file implementation in `services/points_chain.py`.
3. Re-run:
   - `tests/test_points_chain.py`
   - `tests/test_shadow_schema.py`
   - `tests/test_db_mode_triggers.py`
   - `tests/test_integrity_guard.py`
   - `tests/test_trading_engine.py`
   - `python3 scripts/pre_push_checks.py --ci`
