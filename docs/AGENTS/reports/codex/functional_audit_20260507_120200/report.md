# Functional Audit Report

## Verdict
PASS for end-to-end functional audit.

Repo-level hygiene is still BLOCKED by deferred `release id sync`, not by the
functional changes themselves.

## Scope

This round performed real operations against the application rather than static
inspection only. The focus was:

- public/auth/admin/security-center flows
- PointsChain / economy / trading / internal_test routed trading
- Cloud Drive / remote download / video share / shared playback
- snapshot restore / runtime reset / reconnect
- user-facing error guidance and no-silent-failure checks
- strengthening the existing smoke/test scripts instead of adding a parallel
  duplicated harness

## Real Runtime Validation

- Full live smoke passed:
  - [00_FUNCTIONAL_SMOKE.md](/home/s92137/hackme_web/security/reports/functional_20260507T034748Z/00_FUNCTIONAL_SMOKE.md)
- Full smoke included real verification of:
  - video upload / share / revoke / anonymous playback
  - custom-profile trading write block
  - test-mode trading diagnostics
  - `internal_test` tester-token routed order placement and cancellation
  - snapshot restore preserving baseline and removing residual data
  - runtime reset forcing offline and reconnect within the configured window
  - cloud drive upload / preview / download / delete
  - remote downloader rejection guidance
  - ComfyUI guardrails
  - unknown-path `OPTIONS` hardening regression

## Real Bugs Fixed

- `services/trading/schema_ddl.py` had a fresh-import `SyntaxError` caused by a
  nested triple-quote example inside the module docstring. This broke
  `ensure_trading_schema` on a clean interpreter path.
- `services/server/database.py` now explicitly creates `csrf_tokens` in
  `ensure_security_support_schema()`, fixing `/api/csrf-token` 500 on fresh
  startup.
- `services/server/request_guards.py` now skips SMv2 context lookup for
  `OPTIONS`, preventing unknown-path preflight 500s.
- `services/snapshots/service.py` now stages runtime-secret restore files
  before moving them into the runtime tree, avoiding repo-root `runtime`
  sentinel collisions during restore.
- `routes/videos.py` share-link update/revoke now commits before the real audit
  write path, fixing a live 500 in the share management flow.
- `services/trading/orders.py` now writes `tester_user_id` into
  `test_shadow_orders`, fixing `internal_test` shadow order inserts.
- `services/snapshots/server_mode.py` now rejects invalid tester-token expiry at
  creation time with operator-facing guidance:
  - invalid format
  - timezone-aware timestamp
  - already-expired timestamp
- `security/run_functional_smoke.sh` now generates tester-token expiry using
  local wall time instead of naive UTC, fixing the live `internal_test` login
  403 regression.
- `security/run_functional_smoke.sh` now fails clearly when free-port probing is
  blocked by a restricted environment instead of silently passing with a blank
  port.

## Test / Script Coverage Added

- [tests/test_trading_schema_snapshot.py](/home/s92137/hackme_web/tests/test_trading_schema_snapshot.py)
  - added direct `py_compile` coverage for `services/trading/schema_ddl.py`
- [tests/test_auth_csrf_safe.py](/home/s92137/hackme_web/tests/test_auth_csrf_safe.py)
  - guards fresh creation of `csrf_tokens`
- [tests/test_smv2_context.py](/home/s92137/hackme_web/tests/test_smv2_context.py)
  - guards tester-token identity hydration and `OPTIONS` bypass behavior
- [tests/test_trading_engine.py](/home/s92137/hackme_web/tests/test_trading_engine.py)
  - guards `internal_test` shadow-order insert path
- [tests/test_snapshots.py](/home/s92137/hackme_web/tests/test_snapshots.py)
  - guards staged runtime-secret restore
  - guards tester-token expiry validation
- [tests/test_video_streaming.py](/home/s92137/hackme_web/tests/test_video_streaming.py)
  - guards real-audit share-link update/revoke path
- [tests/test_frontend_videos.py](/home/s92137/hackme_web/tests/test_frontend_videos.py)
  - guards shared-video timeout / error-guidance contract
- [tests/test_functional_smoke_script.py](/home/s92137/hackme_web/tests/test_functional_smoke_script.py)
  - guards:
    - real session cookie checks
    - port auto-pick failure visibility
    - internal-test local-time tester-token generation
    - existing video/trading functional smoke coverage

## Before / After

- Before:
  - full smoke could fail on a false-negative `internal_test` login because the
    script generated a tester token that was already expired in UTC+offset
    environments
  - fresh interpreter imports could explode on `services/trading/schema_ddl.py`
  - `/api/csrf-token` could 500 on a fresh schema path
  - restore could collide with the repo-root `runtime` sentinel
- After:
  - full live smoke passes end-to-end
  - the tester-token expiry mismatch is blocked at creation time and fixed in
    the smoke harness
  - fresh schema/bootstrap paths are covered by regression tests
  - restore/reset and video-share regressions are exercised by the existing
    smoke surface

## Tests Run

- `python3 -m py_compile services/trading/schema_ddl.py`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_schema_snapshot.py -k "schema_ddl_module_compiles_cleanly or produces_expected_tables or is_idempotent"`
- `PYTHONPATH=. python3 -m pytest -q tests/test_functional_smoke_script.py tests/test_trading_schema_snapshot.py tests/test_snapshots.py -k "functional_smoke or schema_ddl_module_compiles_cleanly or create_tester_token_rejects_expired_or_timezone_aware_expiry"`
- `PYTHONPATH=. python3 -m pytest -q tests/test_auth_csrf_safe.py tests/test_smv2_context.py tests/test_trading_engine.py -k "csrf_tokens_table or tester_token_identity or internal_test_root_limit_order_routes_row_to_shadow_orders"`
- `timeout 420s security/run_functional_smoke.sh --keep-runtime`
- `git diff --check`

## Known Risks

- This was a live functional audit, not full browser automation; DOM presence
  and JS error-handling contracts are covered, but not pixel-level UI behavior.
- `server_encrypted` storage still is not zero-knowledge by design. That is a
  trust-boundary limitation, not a silent-failure bug.
- `scripts/pre_push_checks.py --ci` is still blocked by deferred release-id sync
  because this branch already contains significant un-synced code changes.

## Follow-up Items

- Sync release id and `docs/UPDATE_SUMMARY.md` once the current working tree is
  ready for a real release checkpoint.
- If we want browser-grade interaction coverage beyond the shell smoke, add it
  by extending the existing surfaces, not by introducing a second overlapping
  end-to-end harness.

## Rollback Plan

- Revert the functional-audit fixes as a single audit slice if any unexpected
  downstream regression appears.
- The highest-risk rollback points are:
  - tester-token expiry validation in `services/snapshots/server_mode.py`
  - `csrf_tokens` schema creation in `services/server/database.py`
  - runtime-secret staged restore in `services/snapshots/service.py`
