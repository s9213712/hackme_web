# Scripts Index

This is the registration table for maintained operator, QA, security, and gate
scripts.

## Governance Rules

- Every new QA, security, pentest, stress, smoke, or production-gate script must
  be registered here in the same change that adds the script.
- Every script that can be called by the production gate must include owner,
  purpose, artifact, and failure meaning.
- Thin wrappers and symlinks must be registered as wrappers and point to their
  implementation path.
- One-off experiments do not belong in `scripts/`. Move them outside the repo or
  promote them into a maintained entry with an owner and artifact contract.
- Focused regression checks are not full validation and must not be labeled as
  full validation in docs, reports, PR descriptions, or script output.
- User-facing scripts must print progress by default: target/runtime, phase
  start, phase result, artifact path, and failure hint. Machine-readable
  `--json` modes may suppress progress text.

## Production Gate Usable Scripts

| Report type | Entry | Owner | Purpose | Artifact | Failure meaning |
|---|---|---|---|---|---|
| `clean_smoke` | `scripts/on_live_reports/clean_smoke.py` -> `scripts/security/server_mode/server_mode_v2_clean_smoke.py` | Server Mode / Security | Verify clean Server Mode v2 baseline behavior. | `runtime/reports/security/production_gate/clean_smoke_*` | Baseline server-mode behavior is unsafe or inconsistent; do not unlock production. |
| `adversarial` | `scripts/on_live_reports/adversarial.py` -> `scripts/security/server_mode/server_mode_v2_adversarial.py` | Server Mode / Security | Exercise adversarial mode, log, tester-token, shadow, and gate boundaries. | `runtime/reports/security/production_gate/adversarial_*` | A bypass or tamper path may exist; production gate must fail closed. |
| `redteam_l2` | `scripts/on_live_reports/redteam_l2.py` -> `scripts/security/server_mode/server_mode_v2_redteam_l2.py` | Server Mode / Security | Run level-2 replay, revocation, lockdown, fake-report, and integrity tamper checks. | `runtime/reports/security/production_gate/redteam_l2_*` | A higher-risk security invariant regressed; do not treat other green checks as sufficient. |
| `log_chain_verify` | `scripts/on_live_reports/log_chain_verify.py` | Audit / Security | Verify audit log hash-chain continuity and tamper evidence. | `runtime/reports/security/production_gate/log_chain_verify_*` | Audit evidence cannot be trusted for this target commit. |
| `integrity_guard` | `scripts/on_live_reports/integrity_guard.py` | Integrity / Security | Check integrity guard status and pending findings. | `runtime/reports/security/production_gate/integrity_guard_*` | Filesystem or manifest integrity is unknown or compromised. |
| `cloud_drive_quota_permission` | `scripts/on_live_reports/cloud_drive_quota_permission.py` | Storage / Security | Validate cloud-drive quota and permission boundaries. | `runtime/reports/security/production_gate/cloud_drive_quota_permission_*` | Storage isolation or quota enforcement may leak across users. |
| `stress` | `scripts/on_live_reports/stress.py` -> `scripts/security/pentest/trading_stress_pentest.py` plus production-gate direct stress drivers | Trading / Reliability | Validate trading stress and gate-level stress/reliability behavior. | `runtime/reports/security/stress_*`, `runtime/reports/security/trading_stress_report_*` | Runtime or trading reliability/correctness cannot be trusted under load. |
| `permission` | `scripts/on_live_reports/permission.py` -> `scripts/security/pentest/functional_permission_pentest.py` | RBAC / Security | Verify role, permission, and privilege-abuse matrix. | `runtime/reports/security/functional_permission_pentest_*` | A user role can do something it should not, or a valid role is blocked unexpectedly. |
| `functional` | `scripts/on_live_reports/functional.py` -> `scripts/security/pentest/run_functional_smoke.sh` + `tests/security/smoke/smoke_suite.py` | QA / Product Areas | Run isolated runtime functional smoke and smoke-suite coverage. | `runtime/reports/security/functional_<RUN_ID>/` | A broad functional workflow regressed; this is still not a full production validation by itself. |
| `pentest` | `scripts/on_live_reports/pentest.py` -> `scripts/security/pentest/session_security_pentest.py`; gate also calls `scripts/security/pentest/run_pentest.sh` | Security | Run session/security pentest and external scanner orchestration. | `runtime/reports/security/<RUN_ID>/` | Web/session/security posture is not acceptable for promotion. |
| `snapshot_restore` | `scripts/on_live_reports/snapshot_restore.py` | Snapshot / Server Mode | Validate snapshot, restore, reset, and runtime cleanup behavior. | `runtime/reports/security/production_gate/snapshot_restore_*` | Recovery boundaries are not reliable; production rollback cannot be trusted. |
| `pytest` | `scripts/on_live_reports/pytest.py` and `scripts/testing/pytest_in_tmp.sh` | QA | Run the selected pytest suite in an isolated copy. | `runtime/reports/security/production_gate/pytest_*` or pytest output captured by the caller | Unit/integration regression exists in the selected suite; scope depends on selected tests. |
| `points_chain_consistency` | `scripts/on_live_reports/points_chain_consistency.py` | PointsChain / Ledger | Validate wallet, ledger, hash-chain, and consistency invariants. | `runtime/reports/security/production_gate/points_chain_consistency_*` | Ledger/economy state cannot be trusted. |
| `on_live_reports_make` | `scripts/on_live_reports/on_live_reports_make.py` -> `scripts/security/gate/on_live_reports_make.py` | Release / Security | Orchestrate and verify the production gate report set. | `runtime/reports/security/production_gate/on_live_reports_make_*` | Gate evidence is missing, stale, fake, or failed; production unlock must be blocked. |

## Direct QA And Security Entrypoints

| Path | Type | Owner | Purpose | Artifact | Failure meaning |
|---|---|---|---|---|---|
| `scripts/security/pentest/run_functional_smoke.sh` | Functional smoke | QA / Product Areas | Start an isolated runtime and exercise broad product workflows. | `runtime/reports/security/functional_<RUN_ID>/` | A broad user/admin workflow failed, or runtime cleanup/restart invariants failed. |
| `scripts/security/pentest/run_pentest.sh` | Pentest orchestrator | Security | Run built-in and optional external security checks by check ID. | `runtime/reports/security/<RUN_ID>/` | At least one selected security check failed; inspect the per-check raw output. |
| `scripts/security/pentest/functional_permission_pentest.py` | Permission pentest | RBAC / Security | Exercise anonymous/user/manager/root access boundaries. | `runtime/reports/security/functional_permission_pentest_*` | Permission matrix regressed or test credentials are invalid. |
| `scripts/security/pentest/session_security_pentest.py` | Session pentest | Auth / Security | Validate session, CSRF, and auth hardening behavior. | Called report path or caller raw output | Session/auth security invariant failed. |
| `scripts/security/pentest/stress_test.py` | HTTP stress | Reliability | Run generic HTTP stress against an owned target. | `runtime/reports/security/stress_*` | Target failed under configured load or returned unacceptable error rates. |
| `scripts/security/pentest/trading_stress_pentest.py` | Trading stress/correctness | Trading / Reliability | Validate trading correctness, stress, restore, and numeric invariants. | `runtime/reports/security/trading_stress_report_*` | Trading state, pricing, restore, or risk gates regressed. |
| `scripts/security/pentest/video_module_pentest.py` | Video security smoke | Video / Security | Validate video sharing, access, and E2EE envelope boundaries. | Caller report path or raw output | Video access control or share isolation regressed. |
| `scripts/security/gate/on_live_reports_make.py` | Production-gate orchestrator | Release / Security | Generate and verify live production-gate evidence. | `runtime/reports/security/production_gate/on_live_reports_make_*` | Gate evidence cannot unlock production. |
| `scripts/security/gate/whole_site_production_gate.py` | Whole-site gate checker | Release / Security | Aggregate release, security, runtime, pytest, and diff checks. | `runtime/reports/security/whole_site_production_gate_*` | Whole-site release criteria are not met. |
| `scripts/security/gate/full_generator_live_validate.py` | Generator live validation | Release / QA | Validate live generator behavior used by gate workflows. | Caller output or production-gate artifact | Generator validation failed or returned incomplete evidence. |
| `scripts/security/gate/header_security_check.py` | Header security | Security | Check HTTP security headers. | Caller output | Security header posture regressed. |
| `scripts/security/gate/scan_plaintext_secrets.py` | Secret scan | Security | Scan tracked text for plaintext secret patterns. | Caller output | A likely plaintext secret is present and must be removed or allowlisted intentionally. |
| `scripts/security/dependency/dep_audit.sh` | Dependency audit | Security | Audit Python dependencies for known issues. | Caller output | Dependency audit found an unacceptable issue. |
| `scripts/security/server_mode/server_mode_v2_clean_smoke.py` | Server-mode smoke | Server Mode / Security | Validate clean mode behavior. | Caller output or production-gate artifact | Server-mode baseline failed. |
| `scripts/security/server_mode/server_mode_v2_adversarial.py` | Server-mode adversarial | Server Mode / Security | Exercise adversarial boundaries. | Caller output or production-gate artifact | A mode boundary or tamper check failed. |
| `scripts/security/server_mode/server_mode_v2_redteam_l2.py` | Server-mode red team | Server Mode / Security | Exercise higher-risk replay/tamper paths. | Caller output or production-gate artifact | High-risk security invariant failed. |
| `scripts/security/server_mode/server_mode_v2_full_smoke.py` | Server-mode broad smoke | Server Mode / QA | Exercise broad server-mode behavior. | Caller output | Selected broad mode smoke failed; not a full production validation alone. |
| `scripts/security/server_mode/server_mode_v2_live_http_smoke.py` | Live HTTP smoke | Server Mode / QA | Exercise live HTTP mode behavior. | Caller output | Live HTTP mode behavior failed. |
| `scripts/security/server_mode/server_mode_v2_phase_5b_acceptance.sh` | Server-mode acceptance | Server Mode / QA | Run phase 5b acceptance checks for Server Mode v2. | Caller output | Acceptance criteria for the phase are not met. |
| `scripts/security/server_mode/server_mode_v2_token_smoke.py` | Token smoke | Server Mode / Auth | Validate tester-token behavior. | Caller output | Token issuance or enforcement regressed. |
| `scripts/testing/pytest_in_tmp.sh` | Pytest wrapper | QA | Run pytest against a `/tmp` copy to avoid repo pollution. | Pytest output; optional caller artifact | Selected pytest suite failed. |

## Non-Gate Maintained Tooling

| Path | Type | Owner | Purpose | Artifact | Failure meaning |
|---|---|---|---|---|---|
| `scripts/admin/root_recovery.py` | Offline recovery | Admin / Security | Recover root credentials outside the web app. | Audit/runtime side effects in target runtime | Recovery could not complete or audit state is invalid. |
| `scripts/comfyui/feature_probe.py` | ComfyUI probe | ComfyUI | Probe local ComfyUI capability metadata. | Console output | Local ComfyUI capability detection failed. |
| `scripts/comfyui/local_connection_smoke.py` | ComfyUI smoke | ComfyUI | Check local ComfyUI connectivity. | Console output | Local ComfyUI is unreachable or incompatible. |
| `scripts/comfyui/materialize_system_workflows.py` | ComfyUI operator | ComfyUI | Materialize system workflow presets. | Runtime/database changes in selected environment | Workflow preset materialization failed. |
| `scripts/prepush/pre_push_checks.py` | Pre-push runner | Release / QA | Run local pre-push checks. | Console output | The branch is not ready to push. |
| `scripts/trading/validation/trading_exchange_validation.py` | Trading validation | Trading | Validate exchange integration assumptions. | Console output | Exchange integration is unavailable or inconsistent. |
| `scripts/trading/validation/trading_workflow_template_validation.py` | Trading validation | Trading | Validate trading workflow templates. | Console output | Trading workflow template behavior regressed. |
| `scripts/trading/competition/trading_backtest_benchmark.py` | Trading benchmark | Trading | Benchmark trading backtest behavior. | Benchmark output | Performance or correctness expectations failed. |
| `scripts/trading/competition/workflow_template_backtest_benchmark.py` | Trading benchmark | Trading | Benchmark workflow-template backtests. | Benchmark output | Workflow backtest behavior or performance regressed. |

## Wrapper Registration

`scripts/on_live_reports/` contains stable operator-facing wrappers and
symlinks. The implementation path remains the source of behavior; the wrapper
path remains the stable production-gate or operator path. Adding a wrapper
requires:

1. a row in this file;
2. a clear implementation target;
3. a compatibility reason;
4. a removal policy if it is temporary.
