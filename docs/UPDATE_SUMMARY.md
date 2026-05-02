# Update Summary

Release ID: `2026.05.02-047`

## Highlights

- Whole-site production gate is now available through
  `security/whole_site_production_gate.py` and
  `security/run_pentest.sh --only whole-site-production-gate`.
- Latest local gate evidence passed against `http://127.0.0.1:5000`:
  12/12 modules PASS, `critical_findings=0`, `high_findings=0`,
  `medium_findings=0`, `production_readiness=YES`.
- Latest evidence files:
  `security/reports/20260502T150309Z/raw/whole_site_production_gate_20260502_230524.json`
  and
  `security/reports/20260502T150309Z/raw/whole_site_production_gate_20260502_230524.md`.
- The gate aggregates Server Mode v2, auth/session, RBAC, snapshot/restore,
  PointsChain/economy, Cloud Drive, trading, forum/community/reporting,
  integrity, audit/logs, stress/reliability, pytest, `py_compile`, generated
  report policy, and `git diff --check`.
- Latest-password lookup now uses the monotonic `user_passwords.id` order
  instead of textual `created_at` ordering, avoiding stale-password selection
  when timestamp formats differ.
- Feature-disabled API gates now return unauthenticated requests as `401`
  before reporting feature-disabled `503`, so permission tests see the real
  authorization boundary.
- `functional_permission_pentest.py` now accepts `PENTEST_USER_PASSWORD` in
  addition to the legacy `PENTEST_TEST_PASSWORD`.
- `trading_stress_pentest.py` no longer rotates root's password by default;
  production-gate targets must use already-initialized test credentials or pass
  `--root-new-password` explicitly.

## Operator Notes

- Keep the whole-site gate evidence together with the Server Mode v2
  adversarial, Red Team L2, and live HTTP reports. The whole-site gate is the
  aggregate production decision; the Server Mode v2 reports remain its
  control-plane evidence.
- Server Mode v2 production_ready is narrower than whole-site
  production_ready. The whole-site gate must be run before production sign-off.
- Off-host append-only log replication / filesystem-level immutable storage is
  still a deployment-environment control; the local gate records it as an
  unresolved deployment risk unless verified separately.
- Runtime logs, generated reports, SQLite databases, pycache, and local keys are
  generated artifacts. They should remain ignored and must not be committed.
