# Server Mode v2 Test Plan

Every phase must finish with targeted tests plus smoke checks. A failure in a
mode operation must never silently succeed.

## Phase 1 Tests

Unit tests:

- Non-root cannot call mode switch.
- Unknown mode is rejected.
- Legacy `preprod` maps to `dev_ready`.
- Missing or wrong confirmation phrase is rejected.
- Checkpoint creation failure rejects mode switch.
- Successful switch inserts exactly one `mode_switch_logs` row.
- Failed switch inserts a failed `mode_switch_logs` row.
- `mode_switch_logs` can be queried but has no delete API.
- `server_checkpoints` records DB snapshot, config hash, security hash,
  PointsChain hash, Cloud Drive metadata hash, and integrity manifest hash.

Smoke:

- `GET /api/root/server-mode`
- `POST /api/root/server-mode/checkpoint`
- `POST /api/root/server-mode/switch`
- `GET /api/root/server-mode/requirements`
- `GET /api/root/server-mode/logs`

## Phase 2 Tests

Unit/integration tests:

- Restore validation passes when no dirty state remains.
- Restore validation fails if test forum content remains.
- Restore validation fails if PointsChain hash differs.
- Restore validation fails if Cloud Drive metadata hash differs.
- Restore validation fails if config/security hash differs.
- Restore validation fails if integrity manifest hash differs.
- Any failed validation enters `incident_lockdown`.
- `incident_lockdown` blocks switching to `superweak`.
- Root can resolve incident only after required verification checks pass.

Smoke:

- Create checkpoint.
- Add temporary forum/thread/content row.
- Restore checkpoint.
- Verify temporary row is gone.

## Phase 3 Tests

Integration tests:

- Entering superweak creates checkpoint and switches mode.
- Superweak applies 10MB Cloud Drive quota to all users including root.
- Root cannot override superweak 10MB quota.
- Dirty DB row created in superweak disappears after exit.
- Dirty Cloud Drive metadata created in superweak disappears after exit.
- Dirty PointsChain entries do not remain after exit.
- Restore failure on superweak exit enters `incident_lockdown`.
- `keep_dirty_state` is rejected.

Security tests:

- Non-root cannot enter/exit superweak.
- Superweak cannot delete checkpoint.

## Phase 4 Tests

Unit tests:

- Tester token hash verification.
- Expired tester token rejected.
- Revoked tester token rejected.
- Token route outside `allowed_routes` rejected.
- Token feature outside `allowed_features` rejected.
- Token rate limit enforced.

Integration tests:

- Tester changes own role; production `users.role` remains unchanged.
- Tester changes own points; production wallet and PointsChain remain unchanged.
- Tester places test trade; production trading positions/fills remain unchanged.
- Closing test/internal_test removes shadow data.
- Tester cannot access root API.
- Tester cannot read other users' Cloud Drive.
- Tester cannot delete checkpoint/snapshot.
- Tester cannot switch server mode.

## Phase 5 Tests

Unit/integration tests:

- Production entry fails when any required report is missing.
- Production entry fails when report has `pass=false`.
- Production entry fails when critical/high findings are non-zero.
- Production entry fails when report hash/signature is missing.
- Production entry succeeds only with all required passing reports.
- Production mode enables required safety controls.
- Same-IP multi-account and same-account multi-IP settings exist but default to
  disabled.

## Phase 6 Tests

Frontend/static tests:

- Root server mode page exists.
- All buttons show progress and result messages.
- Mode colors match profile matrix.
- Production requirement list marks missing/failed/passing reports.
- Tester token management renders allowed features/routes and expiry.
- Incident status renders current state and resolution blockers.

End-to-end smoke:

- Start clean server.
- Login as root.
- Create checkpoint.
- Switch to `dev_ready`.
- Switch to `maintenance`.
- Enter incident manually.
- Attempt superweak from incident and confirm it is blocked.

## Required Report After Each Phase

After each phase, report:

- Modified files
- Added tables
- Added APIs
- Test commands and results
- Smoke test result
- Known incomplete items
