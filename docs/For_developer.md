# For_developer

This document is for developers, operators, and API consumers. User-facing WEB
behavior is documented in [WEB.md](WEB.md).

## Release and Schema

- Release ID: `2026.04.29-022`
- Schema version: `26`
- Release ID source: `services/release_info.py`
- Runtime version endpoint: `GET /api/version`
- Branch and release policy: [BRANCHING_AND_RELEASE.md](BRANCHING_AND_RELEASE.md)

## Fast Local Setup

```bash
scripts/run_prod.sh
```

The script creates `.venv` when needed, installs `requirements.txt`, opens the
first deployment wizard when `.env` is missing, initializes or migrates the
database, and starts Gunicorn. Use `scripts/run_prod.sh --check` for a read-only
environment check and `scripts/run_prod.sh --skip-install` when an external
package manager owns the Python environment.

Default local URL:

```text
http://127.0.0.1:5000/
```

If `cert.pem` and `key.pem` exist in the project root, startup switches to
HTTPS and prints the active URL.

## Runtime State

The repository should run from tracked source files only. Runtime state is
generated at boot and must not be committed.

Ignored runtime state includes:

- `database/database.db`
- `logs/`
- `storage/`
- `chats/*.jsonl`
- `anchors/*.json` and `anchors/*.jsonl`
- `.fkey`, `.csrfkey`, `.integrity_key`, `.chain_seed`
- `integrity_manifest.json`
- `reports/bugs/`
- `security/reports/`

Override paths with:

- `HTML_LEARNING_DB_DIR`
- `HTML_LEARNING_LOG_DIR`
- `HTML_LEARNING_CHAT_DIR`
- `HTML_LEARNING_ANCHOR_DIR`
- `HTML_LEARNING_STORAGE_DIR`
- `HTML_LEARNING_REPORTS_DIR`
- `HTML_LEARNING_HOST`
- `HTML_LEARNING_PORT`

Do not point storage at `/`, `/etc`, the project root, or `public/`.

## Bootstrap Accounts

On a fresh database:

- `root` is created from `HTML_LEARNING_ROOT_PASSWORD`
- `admin` is created only when `HTML_LEARNING_MANAGER_PASSWORD` is set
- `test` is created only when `HTML_LEARNING_TEST_PASSWORD` is set

Bootstrap accounts force password change on first login when the password still
matches the configured bootstrap value.

## API Overview

All write endpoints require CSRF unless explicitly designed as public bootstrap
or login flow. Authenticated browser clients should fetch `/api/csrf-token` and
send `X-CSRF-Token`.

### Public and Session

- `GET /api/version`
- `GET /api/site-config`
- `GET /api/csrf-token`
- `GET /api/captcha/challenge`
- `POST /api/register`
- `POST /api/login`
- `POST /api/logout`
- `GET /api/me`
- password reset and email verification endpoints under the public auth routes

### Chat

- `GET /api/chat/rooms`
- `POST /api/chat/rooms`
- `POST /api/chat/rooms/join`
- `GET /api/chat/rooms/{room_id}/messages`
- `POST /api/chat/rooms/{room_id}/messages`
- message delete/report flows through chat and reports routes

### Direct Messages

- `GET /api/dm/threads`
- `POST /api/dm/threads`
- `GET /api/dm/threads/{id}/messages`
- `POST /api/dm/threads/{id}/messages`
- `POST /api/dm/threads/{id}/read`
- `DELETE /api/dm/messages/{id}`
- `GET /api/dm/blocks`
- `POST /api/dm/blocks`
- `DELETE /api/dm/blocks/{user_id}`

### Notifications and Reports

- `GET /api/notifications`
- `POST /api/notifications/{id}/read`
- `POST /api/notifications/read-all`
- `POST /api/reports`
- `GET /api/admin/reports`
- `POST /api/admin/reports/{id}/claim`
- `POST /api/admin/reports/{id}/resolve`

### Appeals and Violations

- `GET /api/appeals`
- `POST /api/appeals`
- `GET /api/admin/appeals`
- `POST /api/admin/appeals/{id}/claim`
- `POST /api/admin/appeals/{id}/resolve`
- `GET /api/admin/violations`
- `POST /api/admin/users/{user_id}/violation`
- `POST /api/admin/users/{user_id}/reset-violations`

### Users and Governance

- `GET /api/admin/users`
- user create/update/status/role endpoints under `/api/admin/users`
- `GET /api/admin/member-level-rules`
- `PUT /api/admin/member-level-rules/{level}`
- governance proposal endpoints under moderation routes
- reputation summary/history endpoints under account moderation routes

### Forum and Announcements

- category, board, board-request, thread, reply, reaction, review, and moderator
  operations under the community routes
- `POST /api/cloud-drive/announcement-attachment-requests`
- `POST /api/root/announcement-attachment-requests/{id}/review`

### Cloud Drive and Files

- `GET /api/files/quota`
- `GET /api/files/security-policy`
- `GET /api/files/privacy-modes`
- `POST /api/files/upload`
- `GET /api/files/{file_id}/status`
- `GET /api/files/{file_id}/download`
- `POST /api/files/{file_id}/share`
- `POST /api/files/{file_id}/share/revoke`
- `GET /api/cloud-drive/files`
- `POST /api/cloud-drive/upload`
- `POST /api/cloud-drive/attach-existing`
- `GET /api/cloud-drive/files/{file_id}/preview`
- `GET /api/cloud-drive/files/{file_id}/preview/content`
- `PUT /api/cloud-drive/files/{file_id}/text`
- `DELETE /api/cloud-drive/files/{file_id}`
- `GET /api/cloud-drive/files/{file_id}/download`

Remote download APIs:

- `GET /api/cloud-drive/remote-download/capabilities`
- `POST /api/cloud-drive/remote-download/tasks`
- `POST /api/cloud-drive/remote-download/torrent-tasks`
- `GET /api/cloud-drive/remote-download/tasks/{task_id}`

BT/magnet/`.torrent` support depends on `aria2c`.

### Optional Web Terminal

Web Terminal is intentionally optional. It requires Docker, Node/npm for local
xterm.js assets, Python WebSocket packages, and the local
`hackme-web-terminal:base` container image. The installer is designed to handle
the common setup path:

```bash
./install_web_terminal_dependencies.sh --doctor --venv .venv
./install_web_terminal_dependencies.sh --all --venv .venv
```

`--all` installs host packages with sudo when needed, installs Python packages,
copies xterm.js assets into `public/vendor/xterm`, and builds the terminal
container image. If Docker group membership changes, start a new login shell or
restart the service process before opening Web Terminal from the browser.

Use `./install_web_terminal_dependencies.sh --doctor --venv .venv` after installation. It
prints concrete repair commands for missing Docker access, missing xterm assets,
or a missing container image.

Web Terminal network mode is stored in `web_terminal_network_mode`:

- `none`: Docker `--network none`
- `bridge`: Docker `--network bridge`, current default
- `host`: Docker `--network host`, high-risk host network namespace

Web Terminal distribution is stored in `web_terminal_distribution`:

- `ubuntu-24.04`: `hackme-web-terminal:ubuntu-24.04`, current default
- `ubuntu-22.04`: `hackme-web-terminal:ubuntu-22.04`

### Storage and Albums

- `GET /api/storage/files`
- `POST /api/storage/files`
- `POST /api/storage/files/attach-existing`
- `GET /api/storage/files/{id}/download`
- `PUT /api/storage/files/{id}/organize`
- `DELETE /api/storage/files/{id}`
- `POST /api/storage/files/{id}/restore`
- `DELETE /api/storage/files/{id}/purge`
- `GET /api/storage/trash`
- `GET /api/storage/albums`
- `POST /api/storage/albums`
- `GET /api/storage/albums/{id}`
- `PUT /api/storage/albums/{id}`
- `DELETE /api/storage/albums/{id}`
- `POST /api/storage/albums/{id}/files`
- `DELETE /api/storage/albums/{id}/files/{album_file_id}`
- `GET /api/storage/share-links`
- `POST /api/storage/share-links`
- `POST /api/storage/share-links/{id}/revoke`
- `GET /api/storage/shared/{token}/download`

Admin storage APIs:

- `GET /api/admin/storage/summary`
- `GET /api/admin/storage/users`
- `GET /api/admin/storage/files`
- `POST /api/admin/storage/sync-quota`
- `POST /api/admin/storage/maintenance`
- `POST /api/admin/storage/trash/purge`

### ComfyUI

- `GET /api/comfyui/status`
- `GET /api/comfyui/models`
- `POST /api/comfyui/generate`
- `POST /api/comfyui/save-to-drive`
- root can configure the API port from server settings

### Security Center and Operations

- `GET /api/admin/health/readiness`
- `GET /api/admin/health/anomaly`
- `GET /api/admin/health/audit-chain`
- `GET /api/admin/health/db-integrity`
- `GET /api/admin/access-controls`
- `PUT /api/admin/access-controls`
- `POST /api/admin/access-controls/maintenance-bypass-token`
- `GET /api/admin/server-mode`
- `POST /api/admin/server-mode`
- `POST /api/admin/server-mode/exit-superweak`
- `POST /api/admin/snapshots`
- `GET /api/admin/snapshots`
- `GET /api/admin/snapshots/daily`
- `POST /api/admin/snapshots/daily`
- `GET /api/admin/snapshots/{snapshot_id}`
- `GET /api/admin/snapshots/{snapshot_id}/download`
- `POST /api/admin/snapshots/{snapshot_id}/restore`
- `POST /api/admin/snapshots/upload-restore`
- `DELETE /api/admin/snapshots/{snapshot_id}`
- `POST /api/admin/system-reset`
- `GET /api/root/integrity/status`
- `POST /api/root/integrity/rescan`
- `GET /api/root/integrity/findings`
- `GET /api/root/integrity/findings/{id}`
- `POST /api/root/integrity/findings/{id}/approve`
- `POST /api/root/integrity/findings/{id}/reject`
- `POST /api/root/integrity/findings/{id}/ignore`
- `GET /api/root/integrity/report`

Pending Integrity Guard findings are automatically approved after 24 hours.
Rejected findings remain explicit operator decisions and are not auto-approved.

## Server Modes and Snapshot Rules

Server modes:

- `preprod`: normal hardened mode
- `test`: test mode state holder
- `superweak`: intentionally weakened mode for controlled testing

Entering `superweak` requires root confirmation and creates a
`before_superweak` snapshot. Reset creates a `pre_reset` snapshot before
clearing resettable runtime state.

Snapshot archives are downloadable and can be uploaded for restore on another
host.

## Feature Flags and Default Settings

Feature flags and operational settings live in DB-backed `system_settings`.
Root can change them from Security Center / server settings.

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
| `feature_dm_enabled` | `true` |
| `feature_attachments_enabled` | `true` |
| `feature_storage_albums_enabled` | `true` |
| `feature_personalization_enabled` | `false` |
| `feature_social_search_enabled` | `false` |
| `feature_advanced_security_enabled` | `false` |
| `feature_privacy_uploads_enabled` | `true` |

Other defaults:

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
| `captcha_mode` | `none` |
| `captcha_ttl_seconds` | `300` |
| `captcha_turnstile_site_key` | empty |
| `storage_maintenance_auto_enabled` | `false` |
| `storage_maintenance_daily_time` | `04:00` |
| `storage_trash_retention_days` | `30` |
| `web_terminal_distribution` | `ubuntu-24.04` |
| `web_terminal_network_mode` | `bridge` |
| `snapshot_daily_auto_enabled` | `false` |
| `snapshot_daily_time` | `03:00` |
| `snapshot_daily_last_date` | empty |
| `allow_register` | `true` |
| `require_email_verification` | `false` |
| `max_login_failures` | `3` |
| `block_duration_minutes` | `10` |
| `session_ttl_hours` | `4` |

## Architecture

Route modules:

- `routes/public.py`
- `routes/chat.py`
- `routes/users.py`
- `routes/community.py`
- `routes/dm.py`
- `routes/files.py`
- `routes/bug_reports.py`
- `routes/appeals.py`
- `routes/reports_notifications.py`
- `routes/moderation.py`
- `routes/system_admin.py`
- `routes/operations.py`

Service modules:

- `services/access_controls.py`
- `services/auth.py`
- `services/audit.py`
- `services/bootstrap.py`
- `services/captcha.py`
- `services/chat_support.py`
- `services/cloud_drive.py`
- `services/file_previews.py`
- `services/governance_records.py`
- `services/identity.py`
- `services/integrity_guard.py`
- `services/member_levels.py`
- `services/moderation_proposals.py`
- `services/notifications.py`
- `services/password_strength.py`
- `services/permissions.py`
- `services/release_info.py`
- `services/security_events.py`
- `services/server_bind.py`
- `services/settings.py`
- `services/snapshots.py`
- `services/storage_albums.py`
- `services/storage_maintenance.py`
- `services/storage_paths.py`
- `services/upload_security.py`
- `services/violations.py`

Frontend scripts:

- `public/js/00-core.js`
- `public/js/10-users.js`
- `public/js/20-chat.js`
- `public/js/25-community.js`
- `public/js/30-appeals.js`
- `public/js/32-notifications.js`
- `public/js/33-dm.js`
- `public/js/34-markdown-editor.js`
- `public/js/35-drive.js`
- `public/js/36-comfyui.js`
- `public/js/37-bug-report.js`
- `public/js/40-auth-users.js`
- `public/js/50-admin.js`
- `public/js/90-bootstrap.js`

## Security Tooling

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

## Test Gates

Full local gate:

```bash
python3 scripts/pre_push_checks.py
```

Focused test run:

```bash
PYTHONPATH=. python3 -m pytest -q tests
```

Functional smoke runner:

```bash
security/run_functional_smoke.sh --port 50741
```

Security and pentest runner documentation:

- [security/PRE_RELEASE_CHECKLIST.md](security/PRE_RELEASE_CHECKLIST.md)
- [security/FUNCTIONAL_SMOKE.md](security/FUNCTIONAL_SMOKE.md)
- [security/PENTEST.md](security/PENTEST.md)

## Production Start

For first deployment, run the guided setup:

```bash
./scripts/run_prod.sh
```

If `.env` does not exist and the script is attached to a terminal, it opens an
interactive setup wizard. The wizard asks for bootstrap account passwords,
runtime directories, bind address, HTTPS/cookie policy, proxy trust, and
Gunicorn settings, then writes `.env` with mode `600`.

Automation-friendly modes:

```bash
./scripts/run_prod.sh --check
./scripts/run_prod.sh --init-db-only
./scripts/run_prod.sh --no-wizard
```

To regenerate `.env` intentionally:

```bash
./scripts/run_prod.sh --wizard
```

Recommended production defaults:

- `FORCE_HTTPS=true`
- `SESSION_COOKIE_SECURE=true`
- `SESSION_COOKIE_HTTPONLY=true`
- `SESSION_COOKIE_SAMESITE=Strict`
- `IP_BLOCKING_ENABLED=true`
