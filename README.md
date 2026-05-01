# hackme_web

[繁體中文 README](docs/README.zh-TW.md)

![status](https://img.shields.io/badge/status-active-2ea043)
![backend](https://img.shields.io/badge/backend-Flask-000000)
![database](https://img.shields.io/badge/database-SQLite-0f6ab4)
![security](https://img.shields.io/badge/focus-auth%20%2B%20RBAC%20%2B%20audit-b31d28)

**Current Release ID: `2026.05.01-037`**

`hackme_web` is a security-focused Flask web application for studying
authentication, RBAC, moderation workflows, auditability, and operational
hardening in a compact single-node deployment.

Release `2026.05.01-037` adds a root-only one-click PointsChain anomaly handler,
refreshes the server health dashboard layout, and updates the smoke, permission
pentest, stress, trading, and pre-push validation scripts for the current
control plane. The Economy line also includes the spot trading MVP, borrow
trading experiments, DCA bots, node-graph workflow bots, and workflow backtests.

This README is intentionally short. Server features, default settings, and API
details have been moved out of README.

## Documents

All guides live under [docs/](docs/README.md). Start there for the web UI guide,
the [trading system and bot guide](docs/TRADING.md), developer/API notes,
security policy, testing scripts, release policy, and project status.

## Fast Start

Recommended first deployment:

```bash
./deploy.sh
```

Manual development start:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 server.py
```

Fresh local databases create `root/root`, `admin/admin`, and `test/test`, then
force those accounts to change password on first login. Set
`HTML_LEARNING_ROOT_PASSWORD`, `HTML_LEARNING_MANAGER_PASSWORD`, and
`HTML_LEARNING_TEST_PASSWORD` before first boot if you want different bootstrap
passwords.

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
[docs/For_developer.md](docs/For_developer.md).

## Local Checks

Before pushing:

```bash
python3 scripts/pre_push_checks.py
```

For focused test runs:

```bash
PYTHONPATH=. python3 -m pytest -q tests
```
