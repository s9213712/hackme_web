# Server Mode v2 Migration Plan

This plan keeps the migration incremental. The existing mode controls in
`services/snapshots.py`, `routes/system_admin.py`, and the root security UI are
kept alive while Server Mode v2 becomes the authoritative backend.

## Phase 1: Core Schema And Checkpoint Gate

Goals:

- Extend mode names to `superweak`, `test`, `internal_test`, `dev_ready`,
  `production`, `maintenance`, and `incident_lockdown`.
- Treat legacy `preprod` as an alias for `dev_ready`.
- Add independent tables:
  - `mode_switch_logs`
  - `server_checkpoints`
  - `production_entry_reports`
  - `incident_reports`
  - `tester_tokens`
  - `test_shadow_roles`
  - `test_shadow_wallets`
  - `test_shadow_transactions`
  - `test_chain_blocks`
- Add root-only APIs:
  - `GET /api/root/server-mode`
  - `POST /api/root/server-mode/checkpoint`
  - `POST /api/root/server-mode/switch`
  - `GET /api/root/server-mode/requirements`
  - `GET /api/root/server-mode/logs`
- Mode switch must create a checkpoint before changing state.
- Checkpoint must include at least:
  - DB snapshot ID
  - config/security settings hash
  - PointsChain checkpoint/hash
  - Cloud Drive metadata hash
  - integrity manifest hash
- Any mode switch failure writes `mode_switch_logs`.

Exit criteria:

- Non-root switch is rejected.
- Checkpoint failure rejects switch.
- Successful switch writes checkpoint and `mode_switch_logs`.
- `mode_switch_logs` remains query-only and does not use audit chain.

## Phase 2: Incident Lockdown And Restore Validation

Goals:

- Make `incident_lockdown` a formal server mode.
- Add root-only APIs:
  - `POST /api/root/incident/enter`
  - `POST /api/root/incident/resolve`
  - `GET /api/root/incident/status`
- Restore validation must compare checkpoint baseline to restored state:
  - DB fingerprint
  - known test content absence
  - PointsChain hash
  - Cloud Drive metadata hash
  - config/security settings hash
  - integrity manifest hash
- Restore validation failure automatically enters `incident_lockdown`.

Exit criteria:

- Failed restore validation switches mode to `incident_lockdown`.
- Incident mode pauses user login/registration, trading, PointsChain writes, and
  Cloud Drive writes.
- Incident cannot switch directly to `superweak`.

## Phase 3: Superweak Sandbox And Discard

Goals:

- Entering `superweak` creates a checkpoint and records it.
- Superweak applies a hard 10MB Cloud Drive quota to every account including
  root; this is not root-editable while in superweak.
- Leaving superweak always restores checkpoint.
- Dirty state is never merged.

Exit criteria:

- Superweak dirty DB row disappears after exit.
- Dirty Cloud Drive metadata disappears after exit.
- PointsChain hash returns to checkpoint value.
- Restore failure enters `incident_lockdown`.

## Phase 4: Test/Internal Test Shadow Layer

Goals:

- Implement tester token registry with:
  - `expires_at`
  - `allowed_routes`
  - `allowed_features`
  - `max_requests_per_minute`
  - `revoked_at`
  - `created_by_root`
- Implement shadow state:
  - `test_shadow_roles`
  - `test_shadow_wallets`
  - `test_shadow_transactions`
  - `test_chain_blocks`
- Route tester self-modification to shadow layer.
- Deny tester access to root APIs, checkpoint delete, other users' Cloud Drive,
  production snapshot deletion, and server mode switching.

Exit criteria:

- Tester can modify own points/role in test mode.
- Production wallet, PointsChain, trading state, and leaderboard are unchanged.
- Revoking tester token blocks further tester actions.

## Phase 5: Production Gate

Goals:

- Add root-only APIs:
  - `POST /api/root/production-report/upload`
  - `GET /api/root/production-report/status`
  - `POST /api/root/production/enter`
- Require all production reports:
  - stress
  - permission
  - functional
  - pentest
  - snapshot_restore
  - points_chain_consistency
  - cloud_drive_quota_permission
- Block production if any report is missing, failed, unsigned/unhashed, or has
  critical/high unresolved findings.
- Keep these settings present but disabled by default:
  - same IP cannot log into multiple accounts
  - same account cannot log in from different IPs

Exit criteria:

- Production entry fails with missing report list.
- Production entry succeeds only with complete passing reports.
- Critical/high findings block production.

## Phase 6: Root UI And Script Integration

Goals:

- Add root-only server mode page.
- Display:
  - current mode
  - color
  - activated at/by
  - checkpoint status
  - security switch state
  - production requirements
  - tester token management
  - incident status
  - maintenance quick action
  - checkpoint creation
  - restore verification
- Update smoke, permission pentest, and production checklist scripts to emit
  production-entry-compatible reports.

Exit criteria:

- Root UI can switch modes through v2 APIs.
- Frontend shows success/failure for every button.
- Scripts generate reports accepted by production gate.

## Compatibility Notes

- `preprod` remains accepted as an input alias during migration but is displayed
  as `dev_ready`.
- Existing `/api/admin/server-mode` remains as a compatibility wrapper until the
  UI fully migrates to `/api/root/server-mode`.
- Existing `maintenance_mode` setting remains an implementation detail of the
  formal `maintenance` and `incident_lockdown` modes.

## Current Implementation Status

Implemented:

- Canonical modes and `preprod` to `dev_ready` normalization.
- Checkpoint-gated mode switch with mode-specific confirmation phrases.
- Independent DB-backed `mode_switch_logs`; no delete endpoint is exposed.
- Formal `maintenance` and `incident_lockdown` runtime gates.
- Production report gate and root-only production report upload/status APIs.
- Superweak checkpoint restore on exit and forced 10MB Cloud Drive quota for all
  users including root.
- Tester token registry, request rate logging, route allow-list enforcement, and
  root API denial.
- Tester shadow role and shadow wallet APIs:
  - `GET /api/tester/shadow-state`
  - `POST /api/tester/shadow-role`
  - `POST /api/tester/shadow-wallet`
- PointsChain manual verification failure enters `incident_lockdown`.
- Root UI can switch modes, show production gate state, and show recent switch
  logs.

Known limitations:

- Shadow layer is implemented for tester self role/points changes. Existing
  production trading and leaderboard flows are protected from these shadow
  writes, but not every old testing workflow has been re-routed to shadow tables
  yet.
- Mode switch logs are independent of audit chain, but they are still stored in
  the application DB. A full DB restore can roll back earlier mode-switch rows;
  the restore/exit path writes a fresh post-restore log. A future hardening pass
  should add an append-only external mode-switch journal.
- `incident_lockdown` auto-trigger is wired for mode-switch/checkpoint failures,
  superweak restore validation failure, production high-risk integrity findings,
  and root PointsChain verify failure. Other background verifier failures should
  gradually call the same incident entry API.
