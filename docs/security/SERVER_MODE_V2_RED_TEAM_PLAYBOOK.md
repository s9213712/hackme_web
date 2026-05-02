# Server Mode v2 Red Team Playbook

This playbook defines adversarial checks for Server Mode v2. The automated
implementations live in:

- `security/server_mode_v2_adversarial.py`
- `security/server_mode_v2_redteam_l2.py`
- `security/server_mode_v2_live_http_smoke.py`

## Scope

Target controls:

- mode switching
- tester token route boundaries
- snapshot and restore
- shadow role isolation
- superweak rollback
- incident lockdown
- production gate

## Phase 1: Tester Token Escape

Payloads:

```text
/api/tester/../admin
/api/tester%2f../admin
/api/tester%2e%2e/admin
/api/tester;/admin
/api/tester//../admin
```

Record:

- payload
- target function or API
- HTTP status or service result
- response summary
- whether unauthorized API access succeeded

Expected result:

```text
All payloads are rejected.
```

## Phase 2: Permission Confusion

Attack:

1. Create tester token.
2. Set `shadow_role=manager`.
3. Attempt `shadow_role=admin`.
4. Probe admin/root routes.

Expected result:

- `shadow_role=manager` remains shadow-only.
- `shadow_role=admin` is rejected.
- Formal `users.role` does not change.
- Shadow role is not used by formal permission checks.

## Phase 3: Mode Switch Tampering

Attack:

- `UPDATE mode_switch_logs SET reason='tampered'`
- `DELETE FROM mode_switch_logs`
- Insert forged mode switch log row with invalid hashes.

Expected result:

- Update/delete are blocked by DB triggers.
- Forged insert is detected by hash-chain verification and cannot pass sign-off.
- Final canonical chain has `broken_links = 0`.

## Phase 4: Snapshot Attack

Flow:

1. Create snapshot A.
2. Switch mode after snapshot A.
3. Restore snapshot A.

Expected result:

- Mode switch logs created after snapshot A still exist.
- Hash chain remains valid.
- Restore status is explicit.

## Phase 5: Superweak Crash Attack

Flow:

1. Enter superweak.
2. Write dirty data.
3. Simulate crash/startup recovery.

Expected result:

- Dirty data is removed.
- Server exits superweak.
- Mode switch logs remain valid.
- Recovery failure enters `incident_lockdown`.

## Phase 6: Production Gate Bypass

Payloads:

- fake report hash
- missing required fields
- replayed report
- critical/high finding report

Expected result:

```text
All invalid reports are rejected.
```

## Phase 7: Incident Lockdown Escape

Flow:

1. Create active tester token.
2. Enter `incident_lockdown`.
3. Reuse tester token.
4. Attempt switch to superweak.
5. Probe sensitive APIs.

Expected result:

- Tester token is invalid.
- Superweak switch is rejected.
- Sensitive APIs are blocked unless explicitly root recovery APIs.

## Phase 7B: Live HTTP Session and Kill-9 Verification

Flow:

1. Start an isolated loopback Flask server.
2. Login through real HTTP CSRF/session-cookie flow.
3. Create a tester token and send traversal payloads to live routes.
4. Enter superweak.
5. Write dirty DB state.
6. Kill the server process with SIGKILL.
7. Restart and verify startup rollback removed dirty state.
8. Enter `incident_lockdown`.
9. Reuse an old non-root session and tester tokens.

Expected result:

- Real login/session/CSRF stack works for valid root/test users.
- Tester traversal payloads do not reach privileged APIs.
- Dirty superweak state is removed after true process crash and restart.
- Old non-root sessions and tester tokens are blocked after lockdown.
- Live log-chain verification returns `PASS` before lockdown.

## Phase 8: HMAC Signature Tamper

Attack:

- Temporarily alter `mode_switch_logs.hmac_signature`.
- Run mode log verification.

Expected result:

- Verification reports at least one invalid signature.
- Production readiness is `NO` until the tamper is removed or the DB is
  recovered from a trusted state.

## Phase 9: Token Replay After Revoke

Attack:

1. Create a tester token in `test` or `internal_test`.
2. Confirm it works for an allowed tester route.
3. Revoke it.
4. Reuse the same token.

Expected result:

- Token is accepted before revoke.
- Token is rejected immediately after revoke.
- `tester_token_audit` records both the allowed and denied events.

## Phase 10: Integrity Manifest Tamper Signal

Attack:

- Modify the integrity manifest and compare the manifest hash before/after.

Expected result:

- Tamper produces a different hash.
- Runtime integrity guard or sign-off validation must not treat the modified
  manifest as trusted without root approval.

## Required Output

Each attack must record:

- payload
- expected result
- actual result
- status or exception
- state snapshot before and after
- breach true/false

Final report must include:

```text
RED_TEAM_SUMMARY:
  vulnerabilities_found
  breach_count
  risk_level
  production_readiness

RED_TEAM_L2_SUMMARY:
  attacks_total
  blocked_total
  breaches_total
  critical_findings
  high_findings
  production_readiness
```
