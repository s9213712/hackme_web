# Management Plane Observability And CI Follow-up

## Findings

No blocking regression was confirmed in this implementation pass.

## Changes

- Added bounded PointsChain transfer-finality observability to `GET /api/admin/health`, including pending transfer age/counts, pending rails, recent transfer status sample, unsealed ledger sample, safe-mode state, and latest process-local compact sweep metadata.
- Added Health Center `鏈佇列` and `DB 維護` sections so root/admin can inspect finality pressure and split-DB sidecar/largest-file state without starting a heavy report.
- Added root-only `POST /api/root/points/finality-sweep` management-plane job and Health Center button so bounded finality maintenance no longer depends on transaction-list refreshes.
- Health now also surfaces the persisted latest finality-sweep snapshot, so operators retain the last sweep result after process restarts instead of relying only on process-local markers.
- Changed transaction list endpoints to skip hidden finality/deposit maintenance by default; `sweep=1` remains explicit compatibility, and the destructive stress harness now queues the finality-sweep job before observing compact transaction pages.
- Added `long-needle-simulation` GitHub Actions workflow and matching template. PR/push changes to economy/PointsChain/stress paths run `quick`; nightly schedule runs `medium`; artifacts are uploaded from `/tmp/hackme_web_long_needle_ci/reports/qa/`.
- Extended the Nginx production template with `X-Hackme-Edge-Lane`, `X-Hackme-RateLimit-Status`, lane-aware access logs, and upload-before-management regex ordering.

## Verification

- `python3 -m py_compile services/points_chain/service.py routes/economy.py routes/system_admin_sections/security_routes.py scripts/testing/points_chain_destructive_stress.py`
- `node --check public/js/50-admin.js`
- `node --check public/js/90-bootstrap.js`
- `pytest -q tests/frontend/admin/test_frontend_health_center.py tests/points/test_points_chain.py tests/points/test_points_explorer.py tests/scripts/deploy/test_nginx_template.py tests/scripts/testing/test_system_stress_probe.py tests/security/integrity/test_health_center.py tests/security/auth/test_access_controls.py::test_admin_environment_exposes_relative_paths_and_pid tests/security/auth/test_access_controls.py::test_admin_environment_resources_is_lightweight_resource_endpoint -q`
- `git diff --check`

## Residual Risk

- The new finality sweep job is bounded and explicit. A future phase should move the remaining legacy root transaction-list maintenance call behind this job path once the UI and probes consistently use the job.
- The workflow was statically verified locally. The first GitHub Actions run should be inspected because dependency install and long needle runtime duration are environment-dependent.
