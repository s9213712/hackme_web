# Flask Base Security Audit

Date: 2026-05-23 00:13 CST

## Scope

Audited the project Flask/Werkzeug base-layer configuration against current upstream Flask 3.1 / Werkzeug 3.1 behavior.

References:
- Flask security considerations: https://flask.palletsprojects.com/en/stable/web-security/
- Flask configuration: https://flask.palletsprojects.com/en/stable/config/
- Flask 3.1 changelog: https://flask.palletsprojects.com/en/stable/changes/#version-3-1-0
- Werkzeug 3.1 changelog: https://werkzeug.palletsprojects.com/en/stable/changes/

## Fixed

1. Host header validation was not enabled.
   - Added `HTML_LEARNING_TRUSTED_HOSTS`.
   - Default trusted hosts: `127.0.0.1`, `localhost`, `[::1]`, plus explicit `HTML_LEARNING_HOST` when it is not wildcard.
   - Invalid API host now returns JSON `error=untrusted_host`.

2. Multipart resource limits were not explicitly configured.
   - Added `HTML_LEARNING_MAX_FORM_MEMORY_KB`, default `512`.
   - Added `HTML_LEARNING_MAX_FORM_PARTS`, default `1000`.
   - These map to Flask 3.1 `MAX_FORM_MEMORY_SIZE` and `MAX_FORM_PARTS`.

3. Maintenance bypass token could be supplied in query string.
   - Removed query-string fallback.
   - Token is accepted only through `X-Maintenance-Bypass-Token`.
   - This avoids token leakage through access logs, browser history, referrers, and screenshots.

4. Regression coverage was tightened.
   - Added tests for header-only maintenance bypass tokens.
   - Added static regression guard for Flask base security config.
   - Updated stale regression assertions to match the current governance/multisig treasury wording and route boundary.

## Verified

Local repo:
- `python3 -m py_compile server.py services/server/request_guards.py tests/security/auth/test_access_controls.py tests/regressions/test_security_issue_regressions.py`
- `pytest -q tests/security/auth/test_access_controls.py` -> pass, 42 tests
- `pytest -q tests/regressions/test_security_issue_regressions.py` -> pass, 38 tests

Isolated server:
- Runtime preserved at `/tmp/hackme_web_isolated_54343/hackme_web`
- Restarted existing port `54343`, PID `1558972`
- `pwdx 1558972` -> `/tmp/hackme_web_isolated_54343/hackme_web`
- `GET https://127.0.0.1:54343/api/version` -> `200`
- `Host: evil.example` against `/api/version` -> `400 {"error":"untrusted_host"}`
- `Host: 127.0.0.1:54343` against `/api/version` -> `200`
- Targeted tmp runtime pytest -> pass, 3 tests

## Remaining Notes

- The Werkzeug development server still emits its own `Server: Werkzeug/...` header before app-level headers. This cannot be fully removed inside Flask app code; production should run behind gunicorn/reverse proxy and strip upstream `Server` headers there.
- CSP still permits `style-src 'unsafe-inline'` because the existing UI uses inline styles and runtime positioning. Removing it requires a separate frontend cleanup.
- `HTML_LEARNING_TRUSTED_HOSTS` must be set to the public domain list before non-local production exposure.
