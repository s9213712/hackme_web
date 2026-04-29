# hackme_web

[繁體中文 README](README.zh-TW.md)

![status](https://img.shields.io/badge/status-active-2ea043)
![backend](https://img.shields.io/badge/backend-Flask-000000)
![database](https://img.shields.io/badge/database-SQLite-0f6ab4)
![security](https://img.shields.io/badge/focus-auth%20%2B%20RBAC%20%2B%20audit-b31d28)

**Current Release ID: `2026.04.29-017`**

`hackme_web` is a security-focused Flask web application for studying
authentication, RBAC, moderation workflows, auditability, and operational
hardening in a compact single-node deployment.

This README is intentionally short. Server features, default settings, and API
details have been moved out of README.

## Documents

- [WEB.md](WEB.md): user-facing web UI and feature guide
- [For_developer.md](For_developer.md): API, server defaults, deployment, and developer notes
- [SECURITY.md](SECURITY.md): security policy
- [security/PRE_RELEASE_CHECKLIST.md](security/PRE_RELEASE_CHECKLIST.md): production pre-release checklist
- [security/FUNCTIONAL_SMOKE.md](security/FUNCTIONAL_SMOKE.md): functional smoke runner
- [security/PENTEST.md](security/PENTEST.md): pentest runner
- [docs/BRANCHING_AND_RELEASE.md](docs/BRANCHING_AND_RELEASE.md): branch numbering and release ID policy

## Fast Start

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
export HTML_LEARNING_ROOT_PASSWORD='change-this-root-password'
export HTML_LEARNING_MANAGER_PASSWORD='change-this-manager-password'
export HTML_LEARNING_TEST_PASSWORD='change-this-test-password'
python3 server.py
```

Then open the URL printed by the server. Default local URL:

```text
http://127.0.0.1:5000/
```

## Clean Checkout

The repository is intended to run from tracked source files only. Runtime state
is generated at boot and should not be committed.

For a clean deployment:

1. Clone the repository.
2. Install `requirements.txt`.
3. Run `scripts/run_prod.sh` from a terminal and complete the first deployment
   setup wizard.

Runtime files and operational defaults are documented in
[For_developer.md](For_developer.md).

## Local Checks

Before pushing:

```bash
python3 scripts/pre_push_checks.py
```

For focused test runs:

```bash
PYTHONPATH=. python3 -m pytest -q tests
```
