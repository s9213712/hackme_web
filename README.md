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
python3 server.py
```

Then open:

```text
https://127.0.0.1:5000/
```

Default local accounts:

- `root / root` — `super_admin`
- `admin / admin` — `manager`
- `test / test` — `user`

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

## Current Architecture

The backend is now split into route modules and service modules instead of
keeping all behavior in one giant file.

### Backend Route Modules

- `routes/public.py`
- `routes/chat.py`
- `routes/users.py`
- `routes/appeals.py`
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
- `public/app.js` is now only a compatibility stub

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

- default account login for `root`, `admin`, and `test`
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
