# hackme_web

![status](https://img.shields.io/badge/status-active-2ea043)
![backend](https://img.shields.io/badge/backend-Flask-000000)
![database](https://img.shields.io/badge/database-SQLite-0f6ab4)
![security](https://img.shields.io/badge/focus-auth%20%2B%20RBAC%20%2B%20audit-b31d28)

`hackme_web` is a security-focused Flask web application built for studying
authentication, RBAC, auditability, and operational hardening in a realistic
single-node deployment.

The project is intentionally positioned between a teaching system and a
production-style service:

- it exposes real account, moderation, chat, and audit workflows
- it keeps a narrow operational footprint
- it emphasizes defensive controls and observable failure modes

## Fast Start

If you want the shortest path from clone to a working local instance:

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

## Why This Exists

Most demo auth apps stop at login, logout, and a few protected routes.

This repo is useful when you want a system that also includes:

- role-based account administration
- approval-based registration
- violation tracking and appeal workflows
- chat and message-report moderation
- tamper-evident audit logging
- operational settings that can be exercised under real attack/defense testing

## Positioning

`hackme_web` is not a full production platform.

It is useful when you want one of these:

- a compact Flask codebase for offensive and defensive web security practice
- a local target with real RBAC and workflow state transitions
- a reference system for testing CSRF, session, moderation, and audit controls
- a small service that can be hardened incrementally without hiding complexity

## Core Capabilities

### Authentication and Session Handling

- Argon2id password hashing
- login failure tracking and optional IP blocking
- CSRF protection with server-side token persistence
- encrypted session tokens with database-backed session lookup
- logout invalidation and session rotation behavior

### Authorization

- `super_admin`, `manager`, and `user` roles
- server-side RBAC checks on administrative routes
- self-service profile editing with restricted field updates
- approval flow for newly registered accounts

### Moderation and State Workflows

- violation point tracking
- user appeals with administrative review
- message reporting with administrative review
- role/status transitions with explicit policy checks

### Audit and Integrity

- tamper-evident audit chain in SQLite
- local anchor snapshots for audit-chain head tracking
- security event recording for auth and moderation actions

## Role Model

| Role | Purpose | Current authority |
|---|---|---|
| `super_admin` | full control plane | account lifecycle, settings, moderation review, audit, server operations |
| `manager` | operational moderation | view users, review registrations, manage user-level enforcement within policy bounds |
| `user` | normal application use | login, profile updates, chat, report submission, appeal submission |

## Security Controls

Current hardening includes:

- Argon2id password hashing
- generic authentication error responses
- request rate limiting on sensitive public flows
- CSRF verification on write routes
- one-time CSRF token consumption on authenticated writes
- database-backed session validation
- CSP via Flask-Talisman
- audit-chain integrity checks
- role-aware server-side authorization enforcement

## Security Testing Coverage

Completed testing categories include:

- CSRF:
  missing token, invalid token, wrong header name, cross-session token, replay behavior
- Session:
  login rotation, logout invalidation, old cookie reuse, fixation checks, multi-login behavior
- Authorization:
  low-privilege access to admin routes, review routes, settings routes, and moderation routes
- Mass assignment:
  top-level and nested privilege-field smuggling attempts
- IDOR / BOLA:
  self, peer, admin, malformed id, and large id paths
- State machine:
  registration review, appeal submission, message reporting, duplicate submit, review replay
- Injection:
  SQLi probing, log-payload handling, administrative display-path checks

Current outcome summary:

- no confirmed low-privilege privilege-escalation path
- no confirmed logout-session replay path
- no confirmed session fixation path
- no confirmed SQL injection path
- `self-update` CSRF lifecycle mismatch was investigated and frontend token refresh behavior was stabilized

## API Surface

### Public

- `GET /api/csrf-token`
- `POST /api/register`
- `POST /api/login`
- `POST /api/logout`
- `GET /api/me`

### Manager and Above

- `GET /api/admin/users`
- `GET /api/admin/violations`
- `GET /api/admin/audit`

### Super Admin

- `POST /api/admin/users`
- `GET/PUT/DELETE /api/admin/users/<id>`
- `POST /api/admin/users/<id>/promote`
- `POST /api/admin/users/<id>/demote`
- `POST /api/admin/users/<id>/violation`
- `POST /api/admin/users/<id>/reset-violations`
- `POST /api/admin/users/<id>/block`
- `GET/PUT /api/admin/settings`
- `GET /api/admin/environment`
- `GET /api/admin/health`
- `POST /api/admin/restart`
- `GET /api/admin/appeals`
- `POST /api/admin/appeals/<id>/review`
- `GET /api/admin/message-reports`
- `POST /api/admin/message-reports/<id>/review`

## Repository Layout

| Path | Role |
|---|---|
| `server.py` | main Flask backend and route layer |
| `public/index.html` | frontend structure |
| `public/app.js` | frontend application logic |
| `public/styles.css` | frontend styling |
| `scripts/run_prod.sh` | production startup helper |
| `scripts/pre_push_scan.sh` | local pre-push health/sanity helper |
| `scripts/migrate_legacy_json.py` | one-off legacy sidecar migration helper |
| `database/` | local SQLite data directory |
| `logs/` | runtime log directory |
| `anchors/` | local audit head anchor snapshots |

## Configuration Model

Configuration now comes from three layers:

1. environment variables
2. database-backed `system_settings`
3. application defaults in `server.py`

This means legacy JSON settings files are no longer the primary source of
truth.

### Production Example

Use the included example as a template:

```bash
cp .env.production.example .env
```

Then set real values for:

- `SESSION_SECRET`
- `CSRF_SECRET_KEY`
- reverse-proxy related settings when applicable

## Production Start

```bash
cp .env.production.example .env
source .env
./scripts/run_prod.sh
```

The example configuration already enables production-oriented defaults such as:

- `FORCE_HTTPS=true`
- `SESSION_COOKIE_SECURE=true`
- `SESSION_COOKIE_HTTPONLY=true`
- `SESSION_COOKIE_SAMESITE=Strict`
- `IP_BLOCKING_ENABLED=true`

## Data and Migration Notes

The project previously used legacy JSON sidecar files for some operational
state. Those paths have been folded into SQLite-backed tables.

The remaining helper:

```bash
python3 scripts/migrate_legacy_json.py
```

is retained for controlled one-time import, recovery, and compatibility work.

## Operational Notes

- `server.py` is still the main concentration point in the codebase
- the next structural cleanup should split routing, auth, moderation, and audit concerns into separate modules
- local security test artifacts are intentionally kept out of Git tracking
- runtime secrets, seeds, and local state files are intentionally kept out of Git tracking

## Recommended Local Workflow

For day-to-day work:

```bash
python3 server.py
```

Before publishing changes:

```bash
./scripts/pre_push_scan.sh
```

## Current Engineering Priorities

The most valuable next improvements are:

- split `server.py` into smaller backend modules
- keep RBAC and workflow tests growing alongside feature work
- continue hardening moderation and audit display paths
- validate deployment-layer behavior behind a real reverse proxy

## License / Usage Context

This repository is intended for authorized local development, security testing,
and defensive engineering work. Do not use its attack or testing ideas against
systems you do not own or explicitly control.
