# hackme_web

[繁體中文 README](docs/README.zh-TW.md)

![status](https://img.shields.io/badge/status-active-2ea043)
![backend](https://img.shields.io/badge/backend-Flask-000000)
![database](https://img.shields.io/badge/database-SQLite-0f6ab4)
![security](https://img.shields.io/badge/focus-auth%20%2B%20RBAC%20%2B%20audit-b31d28)

**Current Release ID: `2026.04.29-022`**

`hackme_web` is a security-focused Flask web application for studying
authentication, RBAC, moderation workflows, auditability, and operational
hardening in a compact single-node deployment.

This README is intentionally short. Server features, default settings, and API
details have been moved out of README.

## Documents

All guides live under [docs/](docs/README.md). Start there for the web UI guide,
developer/API notes, security policy, testing scripts, release policy, and
project status.

## Fast Start

```bash
scripts/run_prod.sh
```

On a fresh checkout this creates `.venv`, installs Python dependencies, opens
the first deployment wizard, initializes the database, and starts Gunicorn.
Open the URL printed by the server. Default local URL:

```text
http://127.0.0.1:5000/
```

## Clean Checkout

The repository is intended to run from tracked source files only. Runtime state
is generated at boot and should not be committed.

For a clean deployment:

1. Clone the repository.
2. Run `scripts/run_prod.sh` from a terminal.
3. Complete the first deployment setup wizard.

Runtime files and operational defaults are documented in
[docs/For_developer.md](docs/For_developer.md).

## Optional Web Terminal

Web Terminal is an optional root-only feature. It can be disabled from the root
server settings UI. If you plan to enable it, install its host dependencies
first:

```bash
./install_web_terminal_dependencies.sh --doctor --venv .venv
./install_web_terminal_dependencies.sh --all --venv .venv
```

The feature is designed to run commands only inside a restricted container and
to use Cloud Drive as the persistent storage source. When root opens the Web
Terminal page, the frontend runs an environment check first and reports missing
Docker, xterm.js assets, Python WebSocket packages, or the terminal container
image before allowing a session to start.

Web Terminal network mode is configurable in root server settings. The available
modes are `none` for offline sessions, `bridge` for full standard Docker
internet access, and `host` for high-risk host-network debugging. The current
default is `bridge`.

Root can also choose the terminal Ubuntu distribution from the same settings UI:
`ubuntu-24.04` or `ubuntu-22.04`. Run
`./install_web_terminal_dependencies.sh --image` after updates to build both
images.

If Docker group membership changes during installation, restart the login shell
or the service process before using Web Terminal. `docker info` must work without
`sudo` from the same user/session that launches Hackme Web. If the account is in
the docker group but the current shell is stale, start from a fresh login shell
or run `sg docker -c 'scripts/run_prod.sh'` from the repository root.

## Local Checks

Before pushing:

```bash
python3 scripts/pre_push_checks.py
```

For focused test runs:

```bash
PYTHONPATH=. python3 -m pytest -q tests
```
