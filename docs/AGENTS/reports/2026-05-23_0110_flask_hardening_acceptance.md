# Flask Hardening Acceptance

Date: 2026-05-23 CST

## Scope

Locked regression coverage for the Flask base-layer hardening added in the
previous audit:

- Host header allowlist enforcement
- multipart form part and memory limits
- header-only maintenance bypass tokens
- deployment documentation for production proxy/request guard settings

## Added Tests

- `tests/security/gates/test_flask_hardening.py`
  - allowed Host returns 200
  - `evil.com`, empty Host, malformed Host, and malformed port return
    `400 error=untrusted_host`
  - normal small multipart form succeeds
  - multipart request above `MAX_FORM_PARTS` returns `413 error=request_too_large`
  - multipart request above `MAX_FORM_MEMORY_SIZE` returns
    `413 error=request_too_large`
  - `?maintenance_bypass_token=...` is rejected
  - valid `X-Maintenance-Bypass-Token` is accepted
  - rejected payloads/events do not echo token values

## Documentation Synced

- `README.md`
- `docs/02_DEPLOY_PRODUCTION.md`
- `docs/DEPLOYMENT.md`
- `deploy/README.md`
- `deploy/systemd/hackme-web.env.example`

Documented:

- `HTML_LEARNING_TRUSTED_HOSTS` public-domain examples
- reverse proxy `Host` forwarding requirement
- `X-Maintenance-Bypass-Token` header-only bypass
- multipart defaults:
  - `HTML_LEARNING_MAX_FORM_MEMORY_KB=512`
  - `HTML_LEARNING_MAX_FORM_PARTS=1000`

## Verification

Local targeted run:

```text
pytest -q tests/security/gates/test_flask_hardening.py \
  tests/security/auth/test_access_controls.py::test_maintenance_bypass_token_only_uses_header_not_query_string \
  tests/regressions/test_security_issue_regressions.py::test_flask_base_security_guardrails_are_configured
```

Result: pass, 5 tests.

Existing isolated runtime sync:

```text
python3 -m pytest -q \
  /tmp/hackme_web_isolated_54343/hackme_web/tests/security/gates/test_flask_hardening.py \
  /tmp/hackme_web_isolated_54343/hackme_web/tests/security/auth/test_access_controls.py::test_maintenance_bypass_token_only_uses_header_not_query_string \
  /tmp/hackme_web_isolated_54343/hackme_web/tests/regressions/test_security_issue_regressions.py::test_flask_base_security_guardrails_are_configured
```

Result: pass, 5 tests. Server code was unchanged, so the existing `54343`
runtime did not need a restart.
