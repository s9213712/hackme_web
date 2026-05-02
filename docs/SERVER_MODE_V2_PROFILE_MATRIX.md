# Server Mode v2 Profile Matrix

Server Mode v2 makes server mode a first-class operational control, not just a
collection of feature flags. Mode switching is a root-only high-risk operation
with checkpoint creation, independent mode switch logging, and explicit restore
validation.

## Mode Names

| Canonical mode | Legacy name | Purpose | Notes |
| --- | --- | --- | --- |
| `superweak` | none | Deliberately weak security lab mode. | Never for normal development or operations. Dirty state is discarded on exit. |
| `test` | none | QA, API automation, security testing, controlled attack simulation. | Tester changes go to shadow state, not production state. |
| `internal_test` | none | Controlled feature preview for root-approved testers. | Tighter than `test`; access requires tester token. |
| `dev_ready` | `preprod` | Development-ready / pre-release mode. | `preprod` is accepted only as a legacy alias and is stored/displayed as `dev_ready`. |
| `production` | none | Public online operation. | Requires strict report gate and all mandatory security controls. |
| `maintenance` | previous `maintenance_mode` setting | Operational maintenance, updates, DB migration, repair. | Formal server mode; setting remains an implementation detail. |
| `incident_lockdown` | none | Security incident containment. | Auto-entered on restore failure, chain mismatch, high-risk integrity findings, and failed mode switch. |

## Mandatory Invariants

| Invariant | Required behavior |
| --- | --- |
| Root only | Only root can switch mode, create mode checkpoint, upload production reports, create/revoke tester tokens, enter/resolve incident mode. |
| Two-phase confirmation | Every mode switch requires the mode-specific confirmation phrase plus reason. |
| Independent logging | `mode_switch_logs` is written directly to DB and does not depend on audit chain. No delete API is exposed. |
| Checkpoint gate | Mode switch is rejected if checkpoint creation fails. |
| Restore validation | Restore must verify DB, test content removal, PointsChain hash, Cloud Drive metadata hash, config/security hash, and integrity manifest hash. |
| Production gate | Production entry requires all mandatory reports passing with zero critical/high unresolved findings. |
| Incident safety | Restore validation failure, PointsChain mismatch, high-risk integrity finding, mode switch failure, or production critical file change enters `incident_lockdown`. |

## Mode Behavior Matrix

| Mechanism | superweak | test | internal_test | dev_ready | production | maintenance | incident_lockdown |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CSRF | off | on | on | on | on | on | on |
| Password strength | off | optional/off | on for non-testers | optional/off | on | on | on |
| Force default password reset | off | optional/off | on for non-testers | off | on | on | on |
| Login IP lock | off | off | on | off | on | on | on |
| Account lock | off | limited | on | limited | on | on | on |
| Rate limit | off | token/request capped | on | on | on | on | strict |
| General audit chain | off | off or shadow | on | off | on | on | on |
| `mode_switch_logs` | on | on | on | on | on | on | on |
| Integrity Guard | off | off | on | off | on strict | on | on strict |
| PointsChain production writes | off | shadow only | production for normal users, shadow for testers | off | on | paused for writes | paused |
| Trading | off | shadow only | limited/shadow for testers | off by default | on if feature enabled | paused | paused |
| Cloud Drive | 10MB quota, sandbox | overlay/shadow for testers | overlay/shadow for testers | normal dev data | quota enforced | read-only optional | read-only |
| Public registration | on/off for lab | configurable | off | off | off | off | off |
| Test vulnerability features | on | token-limited | off by default | off | off | off | off |
| UI banner | red warning | orange testing | orange internal | blue dev | green production | purple maintenance | black/red incident |

## Confirmation Phrases

| Target mode | Confirmation phrase |
| --- | --- |
| `superweak` | `ENABLE_SUPERWEAK` |
| `test` | `SWITCH_TO_TEST` |
| `internal_test` | `SWITCH_TO_INTERNAL_TEST` |
| `dev_ready` / `preprod` | `SWITCH_TO_DEV_READY` |
| `production` | `GO_LIVE` |
| `maintenance` | `ENTER_MAINTENANCE` |
| `incident_lockdown` | `ENTER_INCIDENT_LOCKDOWN` |

## Production Gate Reports

Production entry requires one latest passing report for each type:

| Report type | Required content |
| --- | --- |
| `stress` | Controlled traffic / trading stress report. |
| `permission` | Role and permission pentest report. |
| `functional` | Full functional smoke report. |
| `pentest` | Security penetration test report. |
| `snapshot_restore` | Snapshot/restore regression report. |
| `points_chain_consistency` | PointsChain verification report. |
| `cloud_drive_quota_permission` | Cloud Drive quota and permission report. |

Each report must include `report_id`, `report_type`, `generated_at`,
`target_commit`, `target_branch`, `server_mode`, `test_result`, `pass`,
`critical_findings_count`, `high_findings_count`, `unresolved_findings`,
`tester`, and `signature` or `hash`.

## Shadow Data Boundaries

`test` and `internal_test` testers may be allowed to change their own role,
points, and trading data, but only through:

- `test_shadow_roles`
- `test_shadow_wallets`
- `test_shadow_transactions`
- `test_chain_blocks` / shadow ledger

The shadow layer must not affect production wallet balances, production
PointsChain, production leaderboards, or production trading positions.

## Token Types

Server Mode v2 uses two different token classes. They are intentionally not
interchangeable:

| Token | Where it is used | Purpose | Authority |
| --- | --- | --- | --- |
| `internal_test` login token | `POST /api/login` payload field `internal_test_token` | Lets a root-approved tester log in while the server is in `internal_test` mode. | Login gate only. It does not grant API scopes by itself. |
| Server Mode v2 tester token | `X-Tester-Token` or `Authorization: Bearer ...` | Lets a tester call scoped `/api/tester/*` automation/shadow APIs in `test` or `internal_test`. | Route/method/mode scoped, rate-limited, expiring, revocable, HMAC-signed. It cannot access root/admin/server-mode/snapshot/integrity/audit APIs. |

The login token is a door key. The tester token is a scoped test API key. A
user may need one or both depending on whether the task is simply entering
`internal_test` or actively running shadow-state/API tests.

## Root APIs

| API | Purpose |
| --- | --- |
| `GET /api/root/server-mode` | Read current mode, profiles, production gate status, and incident summary. |
| `POST /api/root/server-mode/checkpoint` | Create a checkpoint before a planned mode operation. |
| `POST /api/root/server-mode/restore-check` | Validate current state against a stored checkpoint. |
| `POST /api/root/server-mode/switch` | Switch mode after confirmation phrase and checkpoint gate. |
| `GET /api/root/server-mode/requirements` | Read production gate report requirements. |
| `GET /api/root/server-mode/logs` | Read independent mode-switch log rows. |
| `POST /api/root/production-report/upload` | Upload a production-entry-compatible report record. |
| `GET /api/root/production-report/status` | Read production report status. |
| `POST /api/root/production/enter` | Shortcut for production entry using the same gate as mode switch. |
| `POST /api/root/tester-token/create` | Create a scoped tester token. |
| `POST /api/root/tester-token/revoke` | Revoke a tester token. |
| `GET /api/root/tester-token/list` | List tester token metadata. Token secret is never returned after creation. |
| `POST /api/root/incident/enter` | Manually enter incident lockdown. |
| `GET /api/root/incident/status` | Read open incident status. |
| `POST /api/root/incident/resolve` | Resolve the open incident after root confirmation. |

## Tester APIs

Tester APIs require `X-Tester-Token` or `Authorization: Bearer <token>`.
State-changing tester APIs still use the normal CSRF protection.

| API | Purpose | Formal data mutation |
| --- | --- | --- |
| `GET /api/tester/shadow-state` | Read tester shadow role, wallet, transactions, and test chain rows. | No |
| `POST /api/tester/shadow-role` | Change own role inside shadow layer. | No |
| `POST /api/tester/shadow-wallet` | Add/subtract own shadow points inside shadow layer. | No |
