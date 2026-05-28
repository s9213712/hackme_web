# Management Plane Observability And CI Follow-up

## Findings

No blocking regression was confirmed in this implementation pass.

## Changes

- Added bounded PointsChain transfer-finality observability to `GET /api/admin/health`, including pending transfer age/counts, pending rails, recent transfer status sample, unsealed ledger sample, safe-mode state, and latest process-local compact sweep metadata.
- Added Health Center `鏈佇列` and `DB 維護` sections so root/admin can inspect finality pressure and split-DB sidecar/largest-file state without starting a heavy report.
- Added root-only `POST /api/root/points/finality-sweep` management-plane job and Health Center button so bounded finality maintenance no longer depends on transaction-list refreshes.
- Health now also surfaces the persisted latest finality-sweep snapshot, so operators retain the last sweep result after process restarts instead of relying only on process-local markers.
- Changed transaction list endpoints to skip hidden finality/deposit maintenance by default; `sweep=1` remains explicit compatibility, and the destructive stress harness now queues the finality-sweep job before observing compact transaction pages.
- Fixed the non-compact root transaction list path so it also honors
  `run_maintenance=False`; root reads without `sweep=1` no longer finalize rows
  while building the response.
- Replaced remaining synchronous PointsChain full verification in force seal,
  due seal, server-update pre-check, post-restore validation, root verify jobs,
  and recovery auto-handle with bounded verification snapshots.
- Changed Health Center finality snapshot lookup to a read-only schema peek so
  health GET does not create management-plane tables.
- Bounded adjacent admin hot paths found by the follow-up audit:
  `/api/admin/platform-stats` reads the operations control snapshot,
  storage capacity health/list endpoints skip per-user quota scans, storage
  quota sync is paginated, purge/maintenance only sync affected users,
  announcement attachment requests are paginated, and violation integrity/user
  summaries are bounded.
- PointsChain forensic safe-mode bundles no longer inline the full ledger; they
  keep head/counts plus recent samples to avoid giant JSON generation on the
  incident path.
- Added `long-needle-simulation` GitHub Actions workflow and matching template. PR/push changes to economy/PointsChain/stress paths run `quick`; nightly schedule runs `medium`; artifacts are uploaded from `/tmp/hackme_web_long_needle_ci/reports/qa/`.
- Extended the Nginx production template with `X-Hackme-Edge-Lane`, `X-Hackme-RateLimit-Status`, lane-aware access logs, and upload-before-management regex ordering.

## Verification

- `python3 -m py_compile services/points_chain/service.py routes/economy.py routes/system_admin_sections/security_routes.py scripts/testing/points_chain_destructive_stress.py`
- `python3 -m py_compile routes/file_sections/admin_storage_routes.py routes/files.py routes/moderation.py routes/system_admin.py routes/system_admin_sections/runtime_routes.py services/points_chain/backup_recovery.py services/server/container.py services/storage/capacity_audit.py services/storage/maintenance.py`
- `node --check public/js/50-admin.js`
- `node --check public/js/90-bootstrap.js`
- `pytest -q tests/frontend/admin/test_frontend_health_center.py tests/points/test_points_chain.py tests/points/test_points_explorer.py tests/scripts/deploy/test_nginx_template.py tests/scripts/testing/test_system_stress_probe.py tests/security/integrity/test_health_center.py tests/security/auth/test_access_controls.py::test_admin_environment_exposes_relative_paths_and_pid tests/security/auth/test_access_controls.py::test_admin_environment_resources_is_lightweight_resource_endpoint -q`
- `pytest -q tests/frontend/admin/test_frontend_security_center_layout.py::test_moderation_violation_integrity_scan_is_bounded tests/frontend/storage/test_frontend_drive_preview.py::test_admin_storage_maintenance_routes_are_bounded tests/platform/test_server_update_feature.py tests/storage/test_storage_maintenance.py tests/storage/test_upload_security.py::test_storage_capacity_audit_summary_mode_skips_user_quota_scan -q`
- `python3 scripts/prepush/pre_push_checks.py --ci`
- `git diff --check`

## Residual Risk

- The new finality sweep job is bounded and explicit. Root transaction-list
  maintenance now requires `sweep=1`; future load tests should continue using
  the explicit job path so list reads remain observational.
- The workflow was statically verified locally. The first GitHub Actions run should be inspected because dependency install and long needle runtime duration are environment-dependent.
