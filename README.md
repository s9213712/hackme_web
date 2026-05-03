# hackme_web

[繁體中文入口](docs/README.zh-TW.md)

![status](https://img.shields.io/badge/status-active-2ea043)
![backend](https://img.shields.io/badge/backend-Flask-000000)
![database](https://img.shields.io/badge/database-SQLite-0f6ab4)
![security](https://img.shields.io/badge/focus-auth%20%2B%20RBAC%20%2B%20audit-b31d28)

**Current Release ID: `2026.05.03-063`**

`hackme_web` is a security-focused Flask web application that combines
authentication, RBAC, moderation, per-user appearance overrides, Cloud Drive,
ComfyUI integration, PointsChain, trading experiments, server-mode controls,
and auditable recovery tools in a single-node deployment.

This README keeps only the shortest entry route. Detailed deployment,
operations, feature, security, and QA references live under `docs/`.

## Fast Route

### First-time deployer

1. [docs/00_START_HERE.md](docs/00_START_HERE.md)
2. [docs/01_DEPLOY_QUICKSTART.md](docs/01_DEPLOY_QUICKSTART.md)
3. [docs/02_DEPLOY_PRODUCTION.md](docs/02_DEPLOY_PRODUCTION.md)

### Root / admin operator

1. [docs/03_ADMIN_GUIDE.md](docs/03_ADMIN_GUIDE.md)
2. [docs/05_FEATURES_OVERVIEW.md](docs/05_FEATURES_OVERVIEW.md)
3. [docs/11_QA_TESTING.md](docs/11_QA_TESTING.md)
4. [docs/12_TROUBLESHOOTING.md](docs/12_TROUBLESHOOTING.md)

### End user / product walkthrough

1. [docs/04_USER_GUIDE.md](docs/04_USER_GUIDE.md)
2. [docs/05_FEATURES_OVERVIEW.md](docs/05_FEATURES_OVERVIEW.md)

## Quick Start

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

`python3 server.py` 會在本機自動準備開發用 `cert.pem` / `key.pem`，因此預設
通常是 `https://127.0.0.1:5000/`，不是純 HTTP。若直接用 `curl` 檢查版本，
請加 `-k`：

```bash
curl -k -sS https://127.0.0.1:5000/api/version
```

Fresh local databases create `root/root`, `admin/admin`, and `test/test`, then
force those accounts to change password on first login. Set
`HTML_LEARNING_ROOT_PASSWORD`, `HTML_LEARNING_MANAGER_PASSWORD`, and
`HTML_LEARNING_TEST_PASSWORD` before first boot if you want different bootstrap
passwords.

## Documentation Map

### Start Here

- [docs/00_START_HERE.md](docs/00_START_HERE.md)
- [docs/01_DEPLOY_QUICKSTART.md](docs/01_DEPLOY_QUICKSTART.md)
- [docs/02_DEPLOY_PRODUCTION.md](docs/02_DEPLOY_PRODUCTION.md)

### Role Guides

- [docs/03_ADMIN_GUIDE.md](docs/03_ADMIN_GUIDE.md)
- [docs/04_USER_GUIDE.md](docs/04_USER_GUIDE.md)
- [docs/05_FEATURES_OVERVIEW.md](docs/05_FEATURES_OVERVIEW.md)

### Core Systems

- [docs/06_SECURITY_MODEL.md](docs/06_SECURITY_MODEL.md)
- [docs/07_POINTSCHAIN.md](docs/07_POINTSCHAIN.md)
- [docs/08_TRADING_ENGINE.md](docs/08_TRADING_ENGINE.md)
- [docs/09_SNAPSHOT_RESET_RESTORE.md](docs/09_SNAPSHOT_RESET_RESTORE.md)
- [docs/10_WEB_TERMINAL.md](docs/10_WEB_TERMINAL.md)

### QA And Support

- [docs/11_QA_TESTING.md](docs/11_QA_TESTING.md)
- [docs/12_TROUBLESHOOTING.md](docs/12_TROUBLESHOOTING.md)
- [docs/DOCUMENTATION_AUDIT_REPORT.md](docs/DOCUMENTATION_AUDIT_REPORT.md)

### Deep Reference

- [docs/README.md](docs/README.md)
- [docs/For_developer.md](docs/For_developer.md)
- [docs/WEB.md](docs/WEB.md)
- [docs/TRADING.md](docs/TRADING.md)
- [docs/VIDEO_PLATFORM.md](docs/VIDEO_PLATFORM.md)
- [docs/UPDATE_SUMMARY.md](docs/UPDATE_SUMMARY.md)

## Local Checks

```bash
python3 scripts/pre_push_checks.py
security/run_functional_smoke.sh --port 50741
security/run_pentest.sh --target https://127.0.0.1:5000
```

`tests/smoke_suite.py`, `security/run_functional_smoke.sh`, and
`security/run_pentest.sh --only functional-permissions` now share the same
default smoke credentials (`RootSmoke123! / ManagerSmoke123! / TestSmoke123!`).
The pentest wrapper also gives `whole-site-production-gate` a longer floor
timeout automatically, so the default `180s` wrapper no longer kills that gate
prematurely.
