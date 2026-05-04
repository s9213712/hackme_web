# For_developer

This document is for developers, operators, and API consumers. User-facing WEB
behavior is documented in [WEB.md](WEB.md).

Read this after the deployer-first entry docs:
[00_START_HERE.md](00_START_HERE.md),
[01_DEPLOY_QUICKSTART.md](01_DEPLOY_QUICKSTART.md),
[02_DEPLOY_PRODUCTION.md](02_DEPLOY_PRODUCTION.md),
and [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md).
This file is the deep technical reference, not the first stop for a new
deployer.

## Release and Schema

- Release ID: `2026.05.05-108`
- Schema version: `29`
- Release ID source: `services/release_info.py`
- Runtime version endpoint: `GET /api/version`
- Branch and release policy: [BRANCHING_AND_RELEASE.md](BRANCHING_AND_RELEASE.md)
- Upload request-body cap: `HTML_LEARNING_MAX_CONTENT_MB` (default `1024`, minimum `128`)

## Project Working Principles

Feature work is not considered complete when only the code path is finished.
All new features, bug fixes, refactors, admin tools, and UI changes must also
follow the project-wide rules in [RULES_FOR_AGENTS.md](RULES_FOR_AGENTS.md).

Required follow-up areas include:

- related README / user / admin / developer documentation
- matching automated tests plus smoke / pre-push / QA workflow updates when
  needed
- explicit non-sensitive error feedback in both backend and frontend
- mobile layout and interaction checks
- server-side validation and recalculation for any trusted business logic
- final delivery reporting that lists feature scope, docs, tests, UX/error
  additions, mobile check result, moved server-side calculations, and any
  unfinished follow-up

If one of these areas is intentionally left incomplete, the delivery report must
state that gap explicitly instead of marking the feature as fully complete.

## Fast Local Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 server.py
```

Default local URL:

```text
https://127.0.0.1:5000/
```

If `runtime/cert.pem` and `runtime/key.pem` are missing, startup generates a
local self-signed certificate/key pair for local development. Runtime DB, logs,
storage, secrets, and integrity files also default to `runtime/` so they stay
out of the repo root. These deployment-local runtime files must not be
committed.

## Runtime State

The repository should run from tracked source files only. Runtime state is
generated at boot and must not be committed.

Ignored runtime state includes:

- `runtime/database/database.db`
- `runtime/logs/`
- `runtime/storage/`
- `runtime/chats/*.jsonl`
- `runtime/anchors/*.json` and `runtime/anchors/*.jsonl`
- `runtime/.fkey`, `runtime/.filekey`, `runtime/.csrfkey`, `runtime/.integrity_key`, `runtime/.chain_seed`
- `runtime/cert.pem`, `runtime/key.pem`
- `runtime/integrity_manifest.json`
- `runtime/reports/bugs/`
- `security/reports/`

Override paths with:

- `HACKME_RUNTIME_DIR`
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

- `root/root` is created as the highest administrator (`super_admin`)
- `admin/admin` is created as `manager`
- `test/test` is created as a normal user with `trusted` member level

Bootstrap accounts force password change on first login when the password still
matches the bootstrap value. Override the first-boot passwords with
`HTML_LEARNING_ROOT_PASSWORD`, `HTML_LEARNING_MANAGER_PASSWORD`, and
`HTML_LEARNING_TEST_PASSWORD`.

## API Overview

Canonical API route listing now lives in [API_REFERENCE.md](API_REFERENCE.md).
Use this file for:

- runtime layout
- schema / release / environment notes
- high-level API grouping

Use [CLI_ADMIN_PLAYBOOK.md](CLI_ADMIN_PLAYBOOK.md) when you want to operate the
site with `curl` / shell commands instead of the web UI.

The formal HLS / segmented streaming Phase C design for large media now lives
in [VIDEO_STREAMING_ARCHITECTURE.md](VIDEO_STREAMING_ARCHITECTURE.md). Use that
document for:

- large-video streaming architecture
- `server_encrypted` media derivative strategy
- strict E2EE streaming boundaries
- rollout sequencing for HLS playback

All write endpoints require CSRF unless explicitly designed as public bootstrap
or login flow. Authenticated browser clients should fetch `/api/csrf-token` and
send `X-CSRF-Token`.

## Trading Market Catalog

Trading market metadata is now centralized in
`services/trading_markets.py`. That module is the canonical source for:

- internal symbols such as `BTC/POINTS`, `ETH/POINTS`, `XRP/POINTS`,
  `BNB/POINTS`, and `PAXG/POINTS`
- user-facing display symbols such as `BTC/USDT`, `ETH/USDT`, `XRP/USDT`,
  `BNB/USDT`, and `PAXG/USDT`
- per-provider identifiers for Binance / OKX / Coinbase / Kraken / Gemini /
  Bitstamp / CoinGecko
- which markets support live price, reference candles, and BTC_trade
- default seeded markets and their sort order

## Cloud Drive Browser UX

Cloud Drive folder navigation now supports row-level double-click open in
addition to the explicit `開啟` action button. Action buttons remain outside the
double-click target path, so delete/download controls must not trigger folder
navigation.

If you need to add a new points-quoted asset such as `SOL` or `GOLD`, update
the market catalog first, then extend provider support or UI behavior only if
that asset needs custom handling.

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
- `POST /api/chat/rooms/{room_id}/join`
- `POST /api/chat/rooms/{room_id}/invites`
- `GET /api/chat/rooms/{room_id}/export`
- `GET /api/chat/rooms/{room_id}/messages`
- `POST /api/chat/rooms/{room_id}/messages`
- message delete/report flows through chat and reports routes

### Notifications and Reports

- `GET /api/notifications`
- `POST /api/notifications/{id}/read`
- `POST /api/notifications/read-all`
- `POST /api/admin/notifications/send`
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
- `POST /api/admin/users`
- `GET /api/admin/users/{user_id}`
- `PUT /api/admin/users/{user_id}`
- `DELETE /api/admin/users/{user_id}`
- `POST /api/admin/users/{user_id}/review-registration`
- `POST /api/admin/users/{user_id}/promote`
- `POST /api/admin/users/{user_id}/demote`
- `GET /api/admin/member-level-rules`
- `PUT /api/admin/member-level-rules/{level}`
- governance proposal endpoints under moderation routes
- reputation summary/history endpoints under account moderation routes

Governance notes:

- Rejecting a pending registration deletes the application account and revokes
  any pending sessions/tokens.
- Deleting an existing user is a soft-delete that preserves audit/trading/video
  history while revoking access and trashing owned storage rows.
- Role/status/points-rights changes can generate member-governance notices with
  appeal restore context; governance-only notices may use negative synthetic
  `violation_id` values internally.

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

Server-encrypted preview/download note:

- If a file was encrypted with an older unavailable server file key,
  preview/content routes return `error=decrypt_unavailable` with HTTP `409`
  instead of a generic `500`. Image/video style UIs may render a placeholder.

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

### Video Platform

Video Platform v1 uses existing Cloud Drive files as source media. It never
accepts or returns a raw storage path.

- `POST /api/videos/publish`
- `GET /api/videos`
- `GET /api/videos/{id}`
- `POST /api/media/{file_id}/prepare-stream`
- `GET /api/media/{file_id}/stream-status`
- `GET /api/videos/{id}/playback`
- `GET /api/videos/{id}/stream`
- `GET /api/videos/{id}/hls/master.m3u8`
- `GET /api/videos/{id}/hls/{variant}/playlist.m3u8`
- `GET /api/videos/{id}/hls/{variant}/{segment}`
- `POST /api/videos/{id}/view`
- `POST /api/videos/{id}/like`
- `DELETE /api/videos/{id}/like`
- `GET /api/videos/{id}/comments`
- `POST /api/videos/{id}/comments`
- `POST /api/videos/{id}/tip`

Tips are PointsChain ledger operations. The viewer is debited for the gross
amount, the uploader receives the net amount, and the official `root` fee
account receives the platform fee. All rows are written in one database
transaction, and retry protection uses `Idempotency-Key` when supplied.

Streaming notes:

- plain video can now be prepared into HLS derivatives
- `server_encrypted` video can be prepared through a controlled
  decrypt-and-package path
- strict `e2ee` remains unavailable for server-side streaming derivatives
- eligible public/unlisted or `server_encrypted` media now auto-prepare HLS
  derivatives on publish as a best-effort path
- browsers without native HLS support still fall back to direct `/stream`

### ComfyUI

- `GET /api/comfyui/status`
- `POST /api/comfyui/start`
- `GET /api/comfyui/models`
- `POST /api/comfyui/billing-quote`
- `POST /api/comfyui/generate`
- `GET /api/comfyui/jobs/{job_id}`
- `POST /api/comfyui/interrupt`
- `POST /api/comfyui/save`
- `POST /api/comfyui/discard`
- `POST /api/comfyui/share`
- `POST /api/root/comfyui/test-connection`
- `POST /api/root/comfyui/civitai/inspect`
- `POST /api/root/comfyui/civitai/download`
- `POST /api/root/comfyui/stop`
- `GET /api/me/appearance`
- `PUT /api/me/appearance`
- `DELETE /api/me/appearance`
- root can configure the API port from server settings

ComfyUI notes:

- `POST /api/comfyui/generate` can return an async job payload; the frontend
  polls `/api/comfyui/jobs/{job_id}` for progress and final result.
- Each selected LoRA keeps its own `strength_model` and `strength_clip` values
  in the frontend draft and sends them back in the generation payload.
- Root-only Civitai endpoints inspect a page URL, list versions/files, and
  download the selected checkpoint or LoRA into the configured local project.
  The model-download UI is intentionally separated from the main generation form
  and rendered as a collapsed panel at the bottom of the AI page.
- LoRA availability is metadata-driven. The frontend and backend only allow
  LoRAs whose recorded `base_model` normalizes into `sdxl`, `pony`,
  `illustrious`, or `noob`. `SD1.5`, `Flux`, and unknown-metadata LoRAs are
  disabled in the picker and rejected by `POST /api/comfyui/generate`.
- Local mode supports explicit start and root-only stop operations for the
  shared ComfyUI process.
- Remote mode is generation-only. Root settings hide Civitai key / download UI
  in that mode because the server cannot push models into a remote ComfyUI host
  through the standard API.
- Frontend idle auto-logout is suspended while a ComfyUI generation is active.

### PointsChain

- `GET /api/points/wallet`
- `GET /api/points/ledger`
- `GET /api/points/catalog`
- `POST /api/points/spend`
- `GET /api/admin/points/ledger`
- `POST /api/admin/points/adjust`
- `GET /api/admin/points/wallets/{user_id}`
- `GET /api/root/points/report`
- `GET /api/root/points/audit`
- `POST /api/root/points/chain/seal`
- `GET /api/root/points/chain/verify`
- `GET /api/root/points/chain/recovery`
- `POST /api/root/points/chain/backups`
- `POST /api/root/points/chain/recovery/approve`
- `POST /api/root/points/chain/recovery/auto-handle`

`recovery/auto-handle` is root-only and CSRF-protected. It verifies the chain,
returns clean status when no recovery is needed, or applies the recommended
healthy ledger backup only when PointsChain is already in safe mode. Wallets are
rebuilt from ledger replay; current wallet balances are never trusted as the
source of truth.

### Trading System

User trading APIs:

- `GET /api/trading/markets`
- `GET /api/trading/dashboard`
- `GET /api/trading/reference-prices`
- `POST /api/trading/orders`
- `POST /api/trading/orders/{order_uuid}/cancel`
- `GET /api/trading/bots`
- `POST /api/trading/bots`
- `PUT /api/trading/bots/{bot_uuid}`
- `DELETE /api/trading/bots/{bot_uuid}`
- `POST /api/trading/bots/{bot_uuid}/increase-runs`
- `POST /api/trading/bots/scan`
- `POST /api/trading/bots/backtest`
- `POST /api/trading/grid/preview`
- `GET /api/trading/grid-bots`
- `POST /api/trading/grid-bots`
- `POST /api/trading/grid-bots/{bot_uuid}/toggle`
- `DELETE /api/trading/grid-bots/{bot_uuid}`
- `POST /api/trading/grid-bots/scan`
- `POST /api/trading/margin/open`
- `POST /api/trading/margin/{position_uuid}/collateral`
- `POST /api/trading/margin/{position_uuid}/close`

Root/admin trading APIs:

- `GET /api/admin/trading/report`
- `GET /api/root/trading/settings`
- `GET /api/root/trading/price-fusion-status`
- `POST /api/root/trading/settings`
- `POST /api/root/trading/markets/{symbol}`
- `POST /api/root/trading/orders/match`
- `POST /api/root/trading/liquidations/scan`
- `POST /api/root/trading/reserve/allocate`
- `POST /api/root/trading/simulated-balance/reset`
- root contract simulation endpoints under `/api/root/trading/contracts`

Trading API notes:

- Public UI pairs are displayed as `BTC/USDT`, `ETH/USDT`, `XRP/USDT`,
  `BNB/USDT`, and `PAXG/USDT`; internal symbols remain `BTC/POINTS`,
  `ETH/POINTS`, `XRP/POINTS`, `BNB/POINTS`, and `PAXG/POINTS`.
- Trading uses `1 POINT = 1 USDT`.
- User funds must flow through PointsChain. Do not directly update wallet
  balances for trading.
- Percent API fields use human percent values directly: `0.3` means `0.3%`,
  `15` means `15%`.
- Root trading settings now default `price_source` to `fused_weighted`.
  `price_fusion_mode` accepts `auto_depth` or `manual_weights`, and
  `price_fusion_manual_weights` is a per-provider map for
  `binance_public_api / okx_public_api / coinbase_exchange / kraken_public_api / gemini_public_api / bitstamp_public_api`.
- In fused mode the backend uses exchange order-book midpoint plus depth score,
  not a single ticker. If some providers fail, the surviving providers are
  re-normalized automatically; if all order-book sources fail, the backend
  falls back to the single-source public ticker chain and then cached last-good
  price according to `max_price_staleness_seconds`.
- Workflow bots use `workflow_json` with `nodes` and `edges`; legacy branch
  workflow JSON is normalized on save/import.
- DCA bots accept `max_runs = -1` to mean unlimited. This is stored as a
  sentinel in SQLite and returned to the UI again as `-1`.
- Grid bots are spot-first range bots; creation may prompt for a底倉 buy before
  initial sell levels are placed.
- Backtests can accept frontend-supplied candles or fetch Binance historical
  K-lines from `start_time`, `end_time`, and `timeframe`.

Detailed usage is documented in [TRADING.md](TRADING.md).

### Security Center and Operations

- `GET /api/admin/health/readiness`
- `GET /api/admin/health/anomaly`
- `GET /api/admin/health/audit-chain`
- `GET /api/admin/health/db-integrity`
- `GET /api/admin/access-controls`
- `PUT /api/admin/access-controls`
- `POST /api/admin/access-controls/maintenance-bypass-token`
- `GET /api/root/server-mode`
- `POST /api/root/server-mode/checkpoint`
- `POST /api/root/server-mode/restore-check`
- `POST /api/root/server-mode/switch`
- `GET /api/root/server-mode/requirements`
- `GET /api/root/server-mode/logs`
- `GET /api/root/server-mode/logs/verify`
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
The `/api/admin/server-mode*` routes remain only as compatibility wrappers for
older scripts; the root UI and current Server Mode v2 control plane use
`/api/root/server-mode*`.

## Server Modes and Snapshot Rules

Canonical Server Mode v2 states:

- `test`: default mode for fresh deployment and server reset
- `internal_test`: root-approved tester mode with tighter access control
- `dev_ready`: hardened pre-release mode; legacy `preprod` is only an alias
- `production`: public online mode
- `maintenance`: controlled maintenance / repair mode
- `incident_lockdown`: forced containment mode after critical integrity failures
- `superweak`: intentionally weakened mode for controlled security experiments

Entering `superweak` requires root confirmation and creates a
`before_superweak` snapshot. Reset creates a `pre_reset` snapshot before
clearing resettable runtime state. The authoritative mode matrix and
confirmation rules live in [SERVER_MODE_V2_PROFILE_MATRIX.md](SERVER_MODE_V2_PROFILE_MATRIX.md).

Snapshot archives are downloadable and can be uploaded for restore on another
host.

## Feature Flags and Default Settings

Feature flags and operational settings live in DB-backed `system_settings`.
Root can change them from Security Center / server settings.

| Setting | Default |
|---|---:|
| `feature_chat_enabled` | `false` |
| `feature_community_enabled` | `false` |
| `feature_accounts_enabled` | `true` |
| `feature_appeals_enabled` | `false` |
| `feature_audit_log_enabled` | `true` |
| `feature_violation_center_enabled` | `true` |
| `feature_reports_enabled` | `false` |
| `feature_system_health_enabled` | `true` |
| `feature_identity_governance_enabled` | `true` |
| `feature_account_security_enabled` | `false` |
| `feature_member_governance_enabled` | `true` |
| `feature_server_modes_enabled` | `true` |
| `feature_snapshot_restore_enabled` | `true` |
| `feature_health_center_enabled` | `true` |
| `feature_forum_core_enabled` | `false` |
| `feature_ui_rebuild_enabled` | `false` |
| `feature_reports_notifications_enabled` | `true` |
| `feature_attachments_enabled` | `false` |
| `feature_storage_albums_enabled` | `false` |
| `feature_personalization_enabled` | `true` |
| `feature_social_search_enabled` | `false` |
| `feature_advanced_security_enabled` | `false` |
| `feature_privacy_uploads_enabled` | `false` |
| `feature_comfyui_enabled` | `false` |
| `feature_economy_enabled` | `false` |
| `feature_trading_enabled` | `false` |
| `feature_games_enabled` | `false` |
| `feature_videos_enabled` | `false` |

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
- `routes/files.py`
- `routes/bug_reports.py`
- `routes/appeals.py`
- `routes/reports_notifications.py`
- `routes/moderation.py`
- `routes/system_admin.py`
- `routes/operations.py`
- `routes/trading.py`

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
- `services/trading_engine.py`
- `services/upload_security.py`
- `services/violations.py`

Frontend scripts:

- `public/js/00-core.js`
- `public/js/10-users.js`
- `public/js/20-chat.js`
- `public/js/25-community.js`
- `public/js/30-appeals.js`
- `public/js/32-notifications.js`
- `public/js/34-markdown-editor.js`
- `public/js/35-drive.js`
- `public/js/36-comfyui.js`
- `public/js/37-bug-report.js`
- `public/js/40-auth-users.js`
- `public/js/50-admin.js`
- `public/js/56-trading.js`
- `public/js/90-bootstrap.js`
- `public/js/trading-workflow-editor.js`

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

The default gate is intentionally lightweight: Python compilation,
release-document synchronization, generated/runtime file checks, local
workstation path leak checks, config safety, CI portability checks,
`git diff --check`, plaintext secret scanning, optional `gitleaks`, optional
`node --check`, and focused pytest. It does not start the server by default.
Use `--full` for isolated `/tmp` server startup, smoke tests, API contract,
snapshot/restore, Server Mode, PointsChain, and log-chain checks. `--ci` makes
the run non-interactive and sanitized; it does not imply `--full`.

Cleanup helpers:

```bash
python3 scripts/pre_push_checks.py --clean --clean-temp --yes
```

- `--clean` removes safe repository caches and repo-root `runtime/`: `__pycache__`,
  `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.coverage`, `htmlcov`,
  `dist`, `build`, `*.pyc`, `*.pyo`, and a mistakenly generated `runtime/`
  directory.
- `--clean` never removes DB/log/storage/report data, security reports, bug
  reports, key material, `.gitkeep`, or tracked files unless they are explicit
  cache artifacts.
- `--clean-temp` removes old pre-push and secret-scan temp roots under `/tmp`,
  keeping the newest two by default.
- `--yes` skips cleanup confirmation.
- `--keep-temp` keeps the current run's isolated runtime even in `--ci` success.

Install the blocking hook:

```bash
bash hooks/install-hooks.sh
```

The hook bumps `APP_RELEASE_ID`, amends the tip commit, runs `--clean --yes
--ci`, and blocks the push if the cleanup or validation fails.

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
