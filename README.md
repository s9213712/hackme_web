# hackme_web

[繁體中文 README](README.zh-TW.md)

![status](https://img.shields.io/badge/status-active-2ea043)
![backend](https://img.shields.io/badge/backend-Flask-000000)
![database](https://img.shields.io/badge/database-SQLite-0f6ab4)
![security](https://img.shields.io/badge/focus-auth%20%2B%20RBAC%20%2B%20audit-b31d28)

`hackme_web` is a security-focused Flask web application for studying
authentication, RBAC, moderation workflows, auditability, and operational
hardening in a compact single-node deployment.

It is intentionally positioned between a teaching target and a production-style
service:

- real account, review, moderation, and chat workflows
- small enough to understand end to end
- hardened enough to exercise realistic auth, CSRF, session, and audit behavior

## Fast Start

```bash
python3 -m pip install -r requirements.txt
export HTML_LEARNING_ROOT_PASSWORD='change-this-root-password'
export HTML_LEARNING_MANAGER_PASSWORD='change-this-manager-password'
export HTML_LEARNING_TEST_PASSWORD='change-this-test-password'
python3 server.py
```

Then open:

```text
https://127.0.0.1:5000/
```

Bootstrap accounts are no longer hard-coded. On a fresh database, `root` is created from `HTML_LEARNING_ROOT_PASSWORD`; `admin` and `test` are only created if `HTML_LEARNING_MANAGER_PASSWORD` and `HTML_LEARNING_TEST_PASSWORD` are set.

## Developer Security Dependencies

Python dependencies are in `requirements.txt`. Secret scanning also requires the
external `gitleaks` CLI because it is not a Python package.

Install local security tooling:

```bash
python3 -m pip install --user pre-commit
GITLEAKS_VERSION=8.30.1
curl -sSfL "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" -o /tmp/gitleaks.tar.gz
tar -xzf /tmp/gitleaks.tar.gz -C /tmp gitleaks
install -m 0755 /tmp/gitleaks ~/.local/bin/gitleaks
export PATH="$HOME/.local/bin:$PATH"
pre-commit install
gitleaks version
```

macOS users can install gitleaks with Homebrew:

```bash
brew install gitleaks
```

CI installs `gitleaks` automatically in `.github/workflows/security-secrets-scan.yml`.
For this workstation, the verified local binary is
`/home/s92137/.local/bin/gitleaks` and `gitleaks version` should print
`8.30.1`. If the command is not found after installation, add
`export PATH="$HOME/.local/bin:$PATH"` to your shell startup file and reopen the
terminal.

## Deployment FAQ

### The site does not open after `python3 server.py`

Check which host and port the server is listening on. By default, the built-in
Flask server uses `HTML_LEARNING_HOST=0.0.0.0` and
`HTML_LEARNING_PORT=5000`.

```bash
export HTML_LEARNING_HOST=0.0.0.0
export HTML_LEARNING_PORT=5000
python3 server.py
```

If root changed `server_listen_host` or `server_listen_port` in the admin UI,
restart the server before testing again. Bind changes only apply on next boot.

### Should I open `http://` or `https://`?

If `cert.pem` and `key.pem` exist in the project root, the app starts with HTTPS.
Otherwise it starts with HTTP. The startup log prints the actual scheme.

### Root login does not work on a fresh database

Set `HTML_LEARNING_ROOT_PASSWORD` before the first successful database
initialization. If the database was already created without the intended value,
use the existing root password or recreate the database only if you intentionally
want a fresh instance.

### I changed environment variables but nothing changed

Most runtime settings are stored in SQLite `system_settings` after bootstrap.
Root can change them from the server settings UI. Environment variables are
mostly boot-time fallbacks for fresh deployments and directory/bind defaults.

### Where should I put the database and uploads?

Use persistent paths outside temporary directories. Important runtime data lives
in `database/`, `storage/`, `logs/`, `anchors/`, and `chats/` by default. For
production-style deployment, set absolute paths such as:

```bash
export HTML_LEARNING_DB_DIR=/var/lib/hackme_web/database
export HTML_LEARNING_STORAGE_DIR=/var/lib/hackme_web/storage
export HTML_LEARNING_LOG_DIR=/var/log/hackme_web
```

Do not point `HTML_LEARNING_STORAGE_DIR` at `/`, `/etc`, the project root, or
`public/`; startup validation rejects dangerous storage roots.

### The server says maintenance mode blocks access

Log in as root through a browser, disable maintenance mode in server settings,
or rotate a maintenance bypass token and send it with:

```text
X-Maintenance-Bypass-Token: <raw-token>
```

Use the raw token shown once after rotation, not
`maintenance_bypass_token_hash`.

### How do I confirm the server is running the latest code?

Check the release ID at the bottom of the login page or call:

```bash
curl http://127.0.0.1:5000/api/version
```

It should match `services/release_info.py` and the README release ID.

### Admin UI says listen IP/port needs restart

That is expected. Root can save `server_listen_host` and `server_listen_port`
from the UI, but the running socket remains unchanged until the service is
restarted.

### Static files load but API calls fail

Verify you are using the same scheme, host, and port that the server printed at
startup. Also check reverse proxy headers if running behind nginx/Caddy; only
enable forwarded headers when the proxy IP is trusted.

### What should I run before pushing or deploying?

Run the same local gate used by CI:

```bash
python3 scripts/pre_push_checks.py
```

For faster focused verification during development, run:

```bash
PYTHONPATH=. python3 -m pytest -q tests
```

## Why This Project Exists

Many demo auth apps stop at login, logout, and a few protected routes.

This repository is useful when you need a local target that also includes:

- role-based account administration
- approval-based registration
- violation scoring and appeal workflows
- chat and message-report moderation
- tamper-evident audit logging
- operational settings that can be exercised under real attack/defense testing

## Capability Overview

### Authentication and Session Handling

- Argon2id password hashing
- database-backed session validation
- CSRF tokens with server-side persistence
- logout invalidation
- login failure tracking and optional IP blocking
- inactivity auto logout

### Authorization

- `super_admin`, `manager`, and `user` roles
- server-side RBAC checks on sensitive endpoints
- approval flow for newly registered users
- self-service profile editing with restricted field updates

### Moderation and State Workflows

- violation point tracking
- appeal submission and administrative review
- message reporting and administrative review
- account role and status transitions with explicit policy checks

### Audit and Integrity

- tamper-evident audit chain in SQLite
- local `anchors/` snapshots for audit head tracking
- security event logging for auth and moderation activity
- encrypted chat transcript sidecar storage at rest

## Current Feature Inventory

Release ID is shown at the bottom of the login page and returned by
`GET /api/version`. Bump `services/release_info.py` for each published build.

- Current release ID: `2026.04.27-014`
- Current schema version: `19`

### Governance and Member Levels

Member level data is split into durable base state and effective runtime state:

- `base_level`: original member level
- `effective_level`: actual active level after sanctions
- `trust_score`: trust score
- `reputation`: reputation score
- `violation_score`: violation score
- `sanction_status`: `none`, `restricted`, or `suspended`
- `sanction_until`: optional sanction expiry
- `level_updated_at`, `level_updated_by`, `level_update_reason`

`restricted` and `suspended` always override `base_level`. For example, a `vip`
member under restriction keeps `base_level=vip`, but receives
`effective_level=restricted` until the sanction expires or is cleared.

| Level | Default Interaction Model |
|---|---|
| `newbie` | comments allowed, posts moderated/limited, no DM, no uploads |
| `normal` | normal post/comment/DM, no uploads by default |
| `trusted` | higher limits, uploads enabled, higher report weight |
| `vip` | highest quotas, uploads enabled, promotion requires admin/root approval |
| `restricted` | read-only interaction model, no post/comment/DM/upload |
| `suspended` | login only for appeal/notification surfaces; no interaction/reporting |

Bootstrap accounts (`root`, `admin`, and `test` when configured through their
environment variables) are marked with `must_change_password=1` when their
initial password is created. Their first login is allowed only far enough to
change that default password, then the user must sign in again with the new
password.

Rules are loaded from the DB table `member_level_rules`, not hard-coded at route
level. Root can update rule rows through `/api/admin/member-level-rules` or the
admin Settings -> Member Levels UI.

Configurable rule fields include:

- permissions: post, comment, DM, upload, report
- rate limits: post/comment/DM/upload limits
- session idle timeout minutes
- attachment size and quota
- moderation requirement
- report weight
- promotion thresholds: account age, approved content, points, trust, reputation, max violation score
- downgrade threshold
- admin/root approval requirements

All member level changes write `member_level_audit` with actor, target, old/new
base level, old/new effective level, reason, source, and timestamp.

### Moderation Governance

- `moderation_proposals` and `moderation_votes` support admin voting workflows.
- Supported proposal actions: `warn`, `mute`, `restrict`, `suspend`, `delete`, `downgrade_level`, `force_password_reset`.
- Approved proposals can be executed; root can override.
- The admin UI includes a Governance tab for proposal creation, voting, execution, and member rule summaries.
- Governance records are stored in `moderation_actions`, `user_mod_notes`, and `reputation_events`.

### Snapshot, Restore, and Server Modes

Root can manage operational rollback through:

- `POST /api/admin/snapshots`
- `GET /api/admin/snapshots`
- `GET /api/admin/snapshots/daily`
- `POST /api/admin/snapshots/daily`
- `GET /api/admin/snapshots/<snapshot_id>`
- `POST /api/admin/snapshots/<snapshot_id>/restore`
- `DELETE /api/admin/snapshots/<snapshot_id>`
- `POST /api/admin/system-reset`
- `GET /api/admin/server-mode`
- `POST /api/admin/server-mode`
- `POST /api/admin/server-mode/exit-superweak`

Snapshot contents include:

- SQLite database backup
- runtime user files archive from upload/media roots
- redacted config archive, excluding plaintext secrets
- `metadata.json`
- `manifest.json`
- `checksums.sha256`

Server modes:

- `preprod`: normal hardened mode
- `test`: test mode state holder
- `superweak`: intentionally weakened mode for controlled testing

Entering `superweak` requires root confirmation and automatically creates a
`before_superweak` snapshot. Exiting can restore that snapshot by default or let
root explicitly keep the dirty state with a high-risk audit event.

Daily auto snapshot is controlled by `snapshot_daily_auto_enabled`,
`snapshot_daily_time`, and `snapshot_daily_last_date`. The server checks the
schedule in a background worker and creates one `scheduled` snapshot per day.
`POST /api/admin/system-reset` is a root-only runtime reset: it first creates a
`pre_reset` snapshot, then clears resettable runtime tables and user file roots
without deleting users, settings, audit logs, or snapshot records.

Server access controls:

- `GET /api/admin/access-controls`: root-only read of root IP whitelist, browser-only mode, and maintenance bypass token state.
- `PUT /api/admin/access-controls`: root-only update for `root_ip_whitelist_enabled`, `root_ip_whitelist`, `browser_only_mode_enabled`, and bypass token clearing.
- `POST /api/admin/access-controls/maintenance-bypass-token`: root-only token rotation; the raw token is returned once, only its hash is stored, and it expires by default after 30 minutes.

Root IP whitelist blocks root login and root API usage from non-whitelisted IPs
when enabled. Browser-only mode blocks non-browser API clients unless they hold
a valid maintenance bypass token. Maintenance bypass tokens can temporarily
allow API access during maintenance mode without disabling maintenance globally.
Failures include the required header name `X-Maintenance-Bypass-Token`; users
must provide the raw token, never `maintenance_bypass_token_hash`.

Root can also set the next boot listen address through `server_listen_host` and
`server_listen_port` in the server settings UI/API. Empty host or port `0`
falls back to `HTML_LEARNING_HOST` / `HTML_LEARNING_PORT`. Changing these values
requires a server restart because the running socket cannot be rebound safely.

Maintenance mode forces every non-root API session to be revoked and clears the
browser cookies. Root remains allowed so recovery and settings stay reachable.

### Integrity Guard

Integrity Guard detects unauthorized changes to protected application files.
On startup it scans backend code, frontend code, security/auth/admin/root logic,
snapshot/superweak/maintenance code, cloud drive/storage/upload/download code,
migrations, dependency/config files, scripts, and the integrity checker/API
itself. Runtime data such as uploads, storage, logs, snapshots, reports,
caches, `node_modules`, `.git`, `__pycache__`, databases, and temp files are not
hashed.

The first deployment creates a signed `integrity_manifest.json` baseline. Later
scans compare current files to that approved manifest and create
`integrity_findings` for modified, added, or deleted files. Findings remain
pending until root approves, rejects, or ignores them from the Integrity Guard
root panel or API:

- `GET /api/root/integrity/status`
- `POST /api/root/integrity/rescan`
- `GET /api/root/integrity/findings`
- `GET /api/root/integrity/findings/<id>`
- `POST /api/root/integrity/findings/<id>/approve`
- `POST /api/root/integrity/findings/<id>/reject`
- `POST /api/root/integrity/findings/<id>/ignore`
- `GET /api/root/integrity/report`

Approve requires the exact confirmation string
`APPROVE INTEGRITY UPDATE`. Approving updates the signed manifest; rejecting or
ignoring preserves the finding without trusting the change. All review actions
write audit log entries. High-risk findings include auth, admin/root,
maintenance, superweak, snapshot/restore, storage/upload/download, migrations,
dependency lock/config files, `server.py`, and Integrity Guard itself.

Preprod mode is blocked while pending or rejected high-risk findings exist.
Strict mode (`integrity_guard_strict_mode`) blocks startup if high-risk findings
are present. Integrity Guard detects unauthorized modifications, but it does not
replace git, CI/CD, backups, host hardening, or offline review; a fully
compromised host/root can still tamper with the runtime.

Normal deployment workflow:

1. Deploy trusted code.
2. Start the server and open the Integrity Guard panel.
3. Review pending findings.
4. Approve only changes that match the intended deployment.
5. Reject unexpected changes and restore from git/snapshot before rescanning.

### Health Center

Root health diagnostics now expose separate machine-readable probes:

- `GET /api/admin/health/readiness`: database/schema, runtime directories, audit chain, maintenance mode, and snapshot service readiness.
- `GET /api/admin/health/anomaly`: pending moderation queues, quarantined uploads, maintenance mode, and audit chain anomaly signals.
- `GET /api/admin/health/audit-chain`: audit chain verification result.
- `GET /api/admin/health/db-integrity`: SQLite `quick_check`, foreign key check, and schema version check.

### Privacy Upload Security

Phase 1 of the privacy upload system is in place. The DB now tracks file
privacy mode, risk level, scan status, encrypted file keys, scan results,
access logs, and configurable file type policies.

Supported upload modes:

- `public_attachment`: server-readable public files that must be scanned.
- `private_scannable`: private files that can be scanned before encrypted storage.
- `e2ee_vault`: client-encrypted ciphertext only; server/root/admin cannot decrypt.
- `e2ee_vault_with_client_scan`: E2EE plus an untrusted client scan report.

Default risk policy blocks executable-like files from public/private uploads,
marks E2EE files as `unknown_encrypted` or high risk, and requires archives and
macro documents to be scanned before release.

Local malware scanning is designed for free self-hosted tools and is treated as
a soft dependency. Root can enable the `clamav` backend, optionally pin a scanner
command path, set scan timeout, choose fail-closed behavior, quarantine infected
files, enable Office macro checks, recursively inspect ZIP members, and keep
extension/MIME magic-byte validation enabled. If no ClamAV command is configured,
the service looks for `clamdscan` first and then `clamscan`; if neither exists,
the scan is recorded as unavailable/skipped so normal website features still
work unless root explicitly configures stricter policy.

Optional host packages:

- ClamAV: install `clamav` / `clamav-daemon`, run `freshclam`, and set
  `scanner_backend=clamav`. Use `scanner_command=/usr/bin/clamdscan` or leave it
  blank for auto-detect.
- YARA: install `yara`, place rules in a local file/directory, enable
  `yara_enabled`, and set `yara_rules_path`. If `yara` or rules are missing,
  YARA is skipped and recorded as `not_required`.
- ZIP/Office deep checks: no external package is required. ZIP recursion is
  bounded by `max_archive_depth`, `max_archive_files`, and
  `max_archive_uncompressed_bytes`.

For server-readable `public_attachment` and `private_scannable` files, the
central scan flow performs magic-byte validation, Office macro detection, ZIP
archive safety checks, optional recursive ZIP member scanning, optional YARA
matching, and optional ClamAV scanning before a pending file can become `clean`.
Infected files become `quarantined` by default. E2EE files are never advertised
as fully server-scanned because the server cannot decrypt their content.

Cloud drive safety now exposes:

- `GET /api/files/quota`: current user storage usage, remaining bytes, file count, per-level upload limits, and grouping by privacy/risk/scan status.
- `GET /api/files/security-policy`: active cloud drive safety policy plus user-visible restrictions.
- `GET /api/files/privacy-modes`: the four privacy modes and their user-facing warnings.
- `POST /api/files/upload`: compatibility upload API backed by the same cloud drive storage/quota/scan pipeline.
- `GET /api/files/{file_id}/status`: file status, scan results, grants, and E2EE recipient key metadata visible to the owner/root.
- `GET /api/files/{file_id}/download`: compatibility download API with the same permission and scan checks as cloud drive downloads.
- `POST /api/files/{file_id}/share`: E2EE share API; stores a recipient-wrapped file key and creates a download grant.
- `POST /api/files/{file_id}/share/revoke`: revokes recipient-wrapped file keys and active grants.
- `GET/PUT /api/admin/cloud-drive/security-policy`: root-managed scan, archive, preview, E2EE claim, share revocation, and download quota policy.
- `GET /api/cloud-drive/files`: list the current user's cloud drive files.
- `POST /api/cloud-drive/upload`: upload into the owner's cloud drive and optionally attach the uploaded file to a context.
- `POST /api/cloud-drive/attach-existing`: attach an existing cloud drive file to `dm`, `group_chat`, `forum_post`, or `forum_comment` without copying the physical file.
- `GET /api/cloud-drive/files/{file_id}/download`: download after server-side permission, scan status, and deletion checks.
- `POST /api/cloud-drive/announcement-attachment-requests`: manager/admin announcement attachment request.
- `POST /api/root/announcement-attachment-requests/{id}/review`: root-only approve/reject; approved announcement files become root-owned management files.

The logged-in UI includes a cloud drive tab that shows used capacity, remaining
capacity, single-file limit, daily upload limit, risk distribution, scan status,
privacy mode distribution, and the currently enforced safety measures.

Messages, posts, comments, and announcements should store only `cloud_file_refs`
records. The physical file is stored once under the owner's cloud drive, and
`file_access_grants` controls who can download or preview it. Deleting the
source cloud file invalidates all references.

Root can configure cloud drive storage from Settings -> Cloud Drive with
`cloud_drive_storage_root`. The value must be an absolute, safe path outside
the web `public/` directory and project root. Changing it is a restart-required
runtime setting; the UI shows current and next-start roots so operators can
confirm whether the server is still running an old storage location.

### Community Forum

The forum core includes root/manager-managed categories, board requests, board
review, thread review, pinned posts, locked threads, reactions, and automatic
root reports when downvotes exceed the configured threshold. Managers can create
forum categories from the community UI and assign new boards to a category.

Reports and notifications expose these Phase 9 backend APIs:

- `POST /api/reports`: submit a report for a chat message, forum post, forum thread, user, or other target.
- `GET /api/admin/reports`: manager/root report queue with status filtering.
- `POST /api/admin/reports/{id}/claim`: manager/root claim guard so two reviewers do not process the same report.
- `POST /api/admin/reports/{id}/resolve`: approve/reject a claimed report and notify affected users.
- `GET /api/notifications`: current user's notifications plus unread count.
- `POST /api/notifications/{id}/read`: mark one notification as read.
- `POST /api/notifications/read-all`: mark all current-user notifications as read.

### Feature Flags and Defaults

Feature flags and operational settings live in DB-backed `system_settings` and
are editable by root under the admin settings UI. Root can also tune server
listen host/port, access controls, daily snapshot scheduling, cloud drive
storage, and per-level member quotas from the same web surface.

| Setting | Default |
|---|---:|
| `feature_chat_enabled` | `true` |
| `feature_community_enabled` | `true` |
| `feature_accounts_enabled` | `true` |
| `feature_appeals_enabled` | `true` |
| `feature_audit_log_enabled` | `true` |
| `feature_violation_center_enabled` | `true` |
| `feature_reports_enabled` | `true` |
| `feature_system_health_enabled` | `true` |
| `feature_identity_governance_enabled` | `true` |
| `feature_account_security_enabled` | `false` |
| `feature_member_governance_enabled` | `false` |
| `feature_server_modes_enabled` | `false` |
| `feature_snapshot_restore_enabled` | `false` |
| `feature_health_center_enabled` | `true` |
| `feature_forum_core_enabled` | `true` |
| `feature_ui_rebuild_enabled` | `false` |
| `feature_reports_notifications_enabled` | `true` |
| `feature_dm_enabled` | `false` |
| `feature_attachments_enabled` | `false` |
| `feature_storage_albums_enabled` | `false` |
| `feature_personalization_enabled` | `false` |
| `feature_social_search_enabled` | `false` |
| `feature_advanced_security_enabled` | `false` |
| `feature_privacy_uploads_enabled` | `false` |

Other important defaults:

| Setting | Default |
|---|---:|
| `audit_chain_enabled` | `false` |
| `ip_blocking_enabled` | `true` |
| `maintenance_mode` | `false` |
| `root_ip_whitelist_enabled` | `false` |
| `root_ip_whitelist` | empty |
| `browser_only_mode_enabled` | `false` |
| `maintenance_bypass_token_hash` | empty |
| `maintenance_bypass_token_expires_at` | empty |
| `server_listen_host` | empty; use `HTML_LEARNING_HOST` |
| `server_listen_port` | `0`; use `HTML_LEARNING_PORT` |
| `snapshot_daily_auto_enabled` | `false` |
| `snapshot_daily_time` | `03:00` |
| `snapshot_daily_last_date` | empty |
| `allow_register` | `true` |
| `require_email_verification` | `false` |
| `max_login_failures` | `3` |
| `block_duration_minutes` | `10` |
| `session_ttl_hours` | `4` |

## Current Architecture

The backend is now split into route modules and service modules instead of
keeping all behavior in one giant file.

### Backend Route Modules

- `routes/public.py`
- `routes/chat.py`
- `routes/users.py`
- `routes/appeals.py`
- `routes/reports_notifications.py`
- `routes/moderation.py`
- `routes/system_admin.py`
- `routes/operations.py`

### Backend Service Modules

- `services/auth.py`
- `services/audit.py`
- `services/settings.py`
- `services/violations.py`
- `services/security_events.py`
- `services/bootstrap.py`
- `services/chat_support.py`
- `services/governance_records.py`
- `services/member_levels.py`
- `services/moderation_proposals.py`
- `services/notifications.py`
- `services/permissions.py`
- `services/release_info.py`
- `services/snapshots.py`

### Frontend Structure

The frontend no longer relies on a single large application file.

- `public/index.html` loads ordered browser scripts from `public/js/`
- `public/js/00-core.js` contains shared state and utility helpers
- `public/js/10-users.js` contains account-table rendering
- `public/js/20-chat.js` contains chat UI logic
- `public/js/30-appeals.js` contains appeal and report UI logic
- `public/js/40-auth-users.js` contains login, registration, and profile actions
- `public/js/50-admin.js` contains admin, audit, settings, and health views
- `public/js/90-bootstrap.js` wires DOM events and application startup

## Role Model

| Role | Purpose | Authority |
|---|---|---|
| `super_admin` | full control plane | account lifecycle, settings, moderation review, audit, server operations |
| `manager` | operational moderation | view users, review registrations, handle user-level moderation within policy bounds |
| `user` | normal application use | login, profile updates, chat, report submission, appeal submission |

## Data Protection Model

### Protected at Rest

- password hashes are stored with Argon2id
- PII fields such as nickname, real name, birthdate, ID number, and phone are encrypted before storage
- chat transcript sidecar files in `chats/` are sealed before being written
- session tokens are stored as hashes in SQLite-backed session tables

### Operational Storage

- `database/` holds SQLite state
- `logs/` holds runtime logs
- `anchors/` holds audit-chain head snapshots
- `chats/` holds encrypted chat transcript sidecars
- `.fkey`, `.csrfkey`, `.integrity_key`, and `.chain_seed` are generated on first boot and must be persisted across restarts

For test automation, all of these directories can be overridden with:

- `HTML_LEARNING_DB_DIR`
- `HTML_LEARNING_LOG_DIR`
- `HTML_LEARNING_CHAT_DIR`
- `HTML_LEARNING_ANCHOR_DIR`
- `HTML_LEARNING_HOST`
- `HTML_LEARNING_PORT`

## Security Controls

Current hardening includes:

- Argon2id password hashing
- generic authentication error responses
- request rate limiting on sensitive public flows
- CSRF verification on write routes
- database-backed session validation
- CSP via Flask-Talisman
- audit-chain integrity checks
- role-aware server-side authorization enforcement
- optional IP blocking driven by `system_settings`
- emergency maintenance mode for integrity failures

## Testing Strategy

### Local Static and Smoke Checks

`hackme_web` now ships with a dedicated pre-push quality gate:

```bash
python3 scripts/pre_push_checks.py
```

That runner performs:

- Python syntax compilation for backend, scripts, and tests
- isolated runtime directory boot with a disposable SQLite database
- functional smoke checks
- security smoke checks

The shell entrypoint remains available:

```bash
./scripts/pre_push_scan.sh
```

### Smoke Test Coverage

`tests/smoke_suite.py` covers a focused set of end-to-end checks:

- configured bootstrap account login for `root`, `admin`, and `test`
- `/api/me` role verification
- admin access allowed for manager routes
- low-privilege access denied for admin routes
- chat room listing and room creation
- appeal list access for normal users
- login without CSRF denied
- invalid CSRF denied on authenticated writes
- cross-session CSRF token misuse denied
- logout invalidates the session

### GitHub Actions CI

CI runs on push to `main` and on pull requests.

Workflow:

- install Python dependencies
- execute `python scripts/pre_push_checks.py --ci`

This gives the repository a reproducible local-and-CI quality gate using the
same isolated smoke harness.

## Repository Layout

| Path | Role |
|---|---|
| `server.py` | Flask entrypoint and application assembly |
| `routes/` | route modules |
| `services/` | domain and infrastructure services |
| `public/index.html` | frontend structure |
| `public/js/` | split frontend logic |
| `public/styles.css` | frontend styling |
| `database/bootstrap.schema.sql` | bootstrap schema |
| `scripts/run_prod.sh` | production startup helper |
| `scripts/pre_push_scan.sh` | static scan + local quality gate wrapper |
| `scripts/pre_push_checks.py` | isolated functional and security pre-push runner |
| `tests/smoke_suite.py` | end-to-end smoke and security checks |
| `.github/workflows/ci.yml` | GitHub Actions pipeline |

## Configuration Model

Configuration comes from three layers:

1. environment variables
2. database-backed `system_settings`
3. application defaults

Legacy JSON settings files are no longer the primary source of truth.

## Production Start

Use the provided template:

```bash
cp .env.production.example .env
source .env
./scripts/run_prod.sh
```

Recommended production defaults include:

- `FORCE_HTTPS=true`
- `SESSION_COOKIE_SECURE=true`
- `SESSION_COOKIE_HTTPONLY=true`
- `SESSION_COOKIE_SAMESITE=Strict`
- `IP_BLOCKING_ENABLED=true`

## Operational Notes

- local security artifacts and attack scripts are intentionally kept out of Git tracking
- runtime secrets and local state files are intentionally kept out of Git tracking
- the application remains a single-node Flask service, not a distributed platform
- the built-in quality gate is designed to be safe for repeated local runs because it uses isolated runtime directories
