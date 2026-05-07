# Production Sign-off Checklist

This checklist is a release gate. Any failed item blocks production mode.

## Server Mode Core Safety

Status machine:

- [ ] Mode switching is only available through official root-only APIs.
- [ ] Every mode switch creates a checkpoint.
- [ ] Production entry cannot bypass the production gate.
- [ ] `maintenance` and `incident_lockdown` are formal server modes.
- [ ] `mode_switch_log` is written even when the normal audit chain is disabled.

Mode switch logs:

- [ ] `mode_switch_logs` is append-only at DB level for update/delete.
- [ ] Every row has `event_uuid`, `prev_hash`, `row_hash`,
  `hmac_signature`, `key_version`, `server_boot_id`, request metadata, and
  actor metadata.
- [ ] Hash chain verification reports `broken_links = 0`.
- [ ] HMAC verification reports `invalid_signatures = 0`.
- [ ] There is only one canonical chain.
- [ ] Snapshot restore does not remove or overwrite mode switch logs.
- [ ] Superweak rollback does not remove or overwrite mode switch logs.
- [ ] No frontend or backend API can delete or edit mode switch logs.
- [ ] `GET /api/server-mode/logs/verify` and
  `GET /api/root/server-mode/logs/verify` return `result=PASS`.

Audit export:

- [ ] Every mode switch creates a JSON event under
  `runtime/reports/server_mode_audit/`.
- [ ] Daily JSONL bundle and `.sha256` digest are generated.
- [ ] Restore and superweak rollback do not remove audit exports.
- [ ] Export failure blocks `production` / `dev_ready` and enters
  `incident_lockdown`.

Snapshot and restore:

- [ ] Restore rolls back database state.
- [ ] Restore does not roll back protected mode switch logs.
- [ ] Restore failure enters `incident_lockdown`.
- [ ] Post-restore validation checks DB, PointsChain, Cloud Drive metadata, and
  integrity manifest state.

Superweak sandbox:

- [ ] Superweak writes are disposable.
- [ ] Exiting superweak restores the checkpoint and leaves no dirty data.
- [ ] Crash/startup recovery restores the checkpoint.
- [ ] Superweak cannot be used to gain persistent privilege.
- [ ] Superweak Cloud Drive quota is forced to 10MB for every account, including
  root.

Incident lockdown:

- [ ] Non-root APIs are blocked.
- [ ] Tester tokens are invalid.
- [ ] Existing non-root sessions are invalidated by the live request guard.
- [ ] Switching to superweak is blocked.
- [ ] Only root recovery APIs remain available.

## Tester Token Security

- [ ] Tester token routes are whitelist-scoped.
- [ ] Path traversal and encoded bypass are rejected.
- [ ] Route normalization rejects `%2f`, `%5c`, encoded dot traversal,
  semicolon path params, backslashes, and `..`.
- [ ] Rate limit is enforced.
- [ ] Expiration is enforced.
- [ ] Revocation is immediate.
- [ ] Every tester-token allow/deny is recorded in `tester_token_audit`.
- [ ] Tester token cannot call root APIs.
- [ ] Tester token cannot delete checkpoints.
- [ ] Tester token cannot read another user's Cloud Drive.

## Shadow Isolation

- [ ] `shadow_role` does not participate in formal permission checks.
- [ ] `shadow_points` does not affect formal PointsChain.
- [ ] Shadow role/wallet/transactions stay in shadow tables.
- [ ] Code scan confirms no formal permission context uses `shadow_role`.

## Production Gate

- [ ] Required reports exist:
  - clean_smoke
  - adversarial
  - redteam_l2
  - pytest
  - log_chain_verify
  - integrity_guard
  - stress
  - permission
  - functional
  - pentest
  - snapshot_restore
  - points_chain_consistency
  - cloud_drive_quota_permission
- [ ] Report hash uses `sha256:<64 hex>`.
- [ ] Report includes target commit, target branch, server mode, test result,
  tester, and signature.
- [ ] Replay of the same report hash and commit is rejected.
- [ ] Critical/high findings block production.
- [ ] Unresolved findings block production.

## Required Test Evidence

- [ ] `security/server_mode_v2_clean_smoke.py` passes.
- [ ] `security/server_mode_v2_adversarial.py` passes.
- [ ] Adversarial report includes payloads, state snapshots, expected/actual,
  hash-chain evidence, restore evidence, and lockdown evidence.
- [ ] Relevant pytest suite passes.
- [ ] `git diff --check` passes.
- [ ] Secret scan passes.
- [ ] `security/server_mode_v2_redteam_l2.py` passes with
  `production_readiness: YES`.
- [ ] `security/server_mode_v2_live_http_smoke.py` passes with
  `production_readiness: YES`.
- [ ] Live HTTP smoke evidence includes real HTTP CSRF/session login, tester
  token traversal requests against live routes, true SIGKILL superweak
  recovery, incident-lockdown old session/token rejection, and live log-chain
  verification.
- [ ] Off-host append-only log replication / filesystem-level immutable storage
  is either verified in the deployment environment or explicitly accepted as a
  deployment residual risk.

## Scope Note

Server Mode v2 `production_readiness: YES` means the server-mode control plane
passed its dedicated clean smoke, adversarial, Red Team L2, and live HTTP
session/kill-9 evidence. It does not mean the whole site is production-ready.

Whole-site production still requires separate passing evidence for:

- stress
- permission
- functional
- pentest
- snapshot_restore
- points_chain_consistency
- cloud_drive_quota_permission
- off-host append-only audit backup / immutable log replication

The aggregate check is:

```bash
PYTHONPATH=. scripts/security/pentest/run_pentest.sh \
  --target http://127.0.0.1:5000 \
  --only whole-site-production-gate
```

The aggregate report must end with:

```text
WHOLE_SITE_PRODUCTION_GATE_SUMMARY:
- result: PASS
- production_readiness: YES
- critical_findings: 0
- high_findings: 0
```

Latest local release evidence before the Video Platform module for `2026.05.02-046`:

```text
runtime/reports/security/20260502T150309Z/raw/whole_site_production_gate_20260502_230524.md
runtime/reports/security/20260502T150309Z/raw/whole_site_production_gate_20260502_230524.json
```

Result:

```text
modules_total: 12
modules_passed: 12
modules_failed: 0
critical_findings: 0
high_findings: 0
medium_findings: 0
production_readiness: YES
```

The current gate also includes Video Platform checks. Re-run the whole-site
gate after video-module changes before treating a deployment as signed off.

Implementation notes from this sign-off:

- Password history lookups use monotonic `user_passwords.id DESC` rather than
  textual `created_at` ordering, so mixed timestamp formats cannot select an
  older password as the active one.
- Disabled feature gates authenticate first for anonymous API requests, so
  unauthenticated callers receive `401` instead of a misleading
  feature-disabled `503`.
- Whole-site gate targets must use initialized test credentials. The trading
  stress runner does not rotate root's password unless `--root-new-password`
  is passed explicitly.

## Final Decision

Production is allowed only when every item above is checked.

```text
ALL PASS -> production allowed
ANY FAIL -> production blocked
```
