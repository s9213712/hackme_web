# hackme_web

[繁體中文 README](docs/README.zh-TW.md)

![status](https://img.shields.io/badge/status-active-2ea043)
![backend](https://img.shields.io/badge/backend-Flask-000000)
![database](https://img.shields.io/badge/database-SQLite-0f6ab4)
![security](https://img.shields.io/badge/focus-auth%20%2B%20RBAC%20%2B%20audit-b31d28)

**Current Release ID: `2026.05.03-051`**

`hackme_web` is a security-focused Flask web application for studying
authentication, RBAC, moderation workflows, auditability, and operational
hardening in a compact single-node deployment.

Release `2026.05.03-051` adds asynchronous ComfyUI job progress, root-only
Civitai model inspection/download, governance-aware account review/delete flows,
grid trading bot operations/backtests, safer server-encrypted media fallback
behavior after key rotation, and a modular pre-push v2 validation suite with
cleanup helpers and broader regression coverage.

Release `2026.05.02-047` adds the whole-site production gate. The latest local
sign-off evidence before the Video Platform module passed 12/12 modules with
`critical/high/medium` findings all 0 and `production_readiness=YES`; rerun the
gate after video-module changes before using it as final release evidence. The
gate aggregates Server Mode v2, auth/session, RBAC, snapshot/restore,
PointsChain, Cloud Drive, Video Platform, trading, community/reporting,
integrity, audit/log, stress/reliability, pytest, `py_compile`, and `git diff
--check`. This release also fixes latest-password lookup to use monotonic
password-history IDs and makes disabled-feature API gates return
login/permission failures before feature-disabled 503 responses.

Release `2026.05.02-045` hardens Server Mode v2 enterprise sign-off: live HTTP
smoke now drives the real Flask session/cookie/CSRF stack, tester-token
traversal probes, superweak SIGKILL rollback, incident-lockdown old
session/token rejection, and live mode-log verification. Server Mode v2 is now
marked `production_readiness=YES` for its own control plane; whole-site
production still requires the remaining production gate checks. This release
also reduces SQLite session-write contention by throttling `last_seen`
refreshes and clarifies mode-token documentation.

Release `2026.05.02-044` adds smart server update (auto-stash runtime files
before merge, pop after), pre-push version-bump hook, DCA bot first-deduction
fix, Binance backtest pagination up to 5000 candles, and update-summary display
after settings-page update.

Release `2026.05.02-043` makes the optional BTC_trade signal integration
disabled by default, adds root-triggered clone/update/build setup, verifies
clean deployment and BTC_trade first-build behavior, and repairs the production
DB init script for fresh installs.

Release `2026.05.02-042` organizes official trading Workflow templates under
`workflows/`, adds detailed template explanations, validates every official
template with trigger checks and K-line backtests, and surfaces backtest length
limits in the UI/API.

Release `2026.05.02-041` hardens the root GitHub update flow: applying an
update now creates a server snapshot and PointsChain ledger backup first, aborts
if either protection point fails, and automatically restarts the server after a
successful update.

Release `2026.05.02-040` makes DCA bots execute their first run immediately,
adds next-run countdowns to bot cards, improves visible bot action errors,
upgrades Workflow bot templates/editor behavior, and exposes the tracked update
summary in the root GitHub update center.

Release `2026.05.02-039` moves the BTC_trade bridge into this project, updates
the BTC signal panel for the newer BTC_trade runtime report fields, and keeps
the trading documentation aligned with the current Economy workflow branch.
BTC_trade remains optional and disabled by default; when `root` enables it, the
server can clone/update the configured GitHub branch, download data, train, run
prediction, and hide the signal panel safely if setup fails.

Release `2026.05.01-038` adds browser-only E2EE preview, a consolidated cloud
drive file toolbar, and improved direct link / BT remote download routing.

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

This blocking pre-push gate compiles Python, verifies release metadata,
rejects tracked runtime artifacts and local workstation paths, runs
`git diff --check`, scans plaintext secrets, optionally runs `gitleaks` and
`node --check` when installed, and runs a focused pytest set. It is intentionally
fast; isolated server smoke, API contract, snapshot, Server Mode, and
PointsChain checks run only with `--full`. `--ci` means non-interactive CI mode,
not heavyweight mode. Use `--clean --yes` to remove safe repo caches and
`--clean-temp --yes` to remove old `/tmp/html_learning_prepush_*` and
`/tmp/html_learning_secrets_*` directories while keeping the newest two.

For focused test runs:

```bash
PYTHONPATH=. python3 -m pytest -q tests
```
