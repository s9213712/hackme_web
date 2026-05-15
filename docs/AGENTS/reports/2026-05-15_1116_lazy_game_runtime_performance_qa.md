# Lazy Game Runtime Performance QA

- Date: 2026-05-15 11:16 Asia/Taipei
- Branch: `03b.Comfyui`
- Scope: frontend lazy-load performance change with explicit trading exchange non-regression checks.
- Result: PASS.

## Change

- Removed non-critical game runtime scripts from the initial `index.html` script list.
- Kept `41-game-modules.js`, `games/game-view-registry.js`, `games/chess.js`, `38-games.js`, and all trading scripts eager-loaded.
- Added `ensureGameRuntimeScriptsLoaded()` in `38-games.js`; the remaining game modules now load only when the games module is opened.
- Did not lazy-load `56-trading.js` or any trading background engine code.

## Evidence

Final Playwright artifact: `/tmp/hackme_perf_audit_lazy_games_fixed_20260515.json`

- Initial script count: 44 -> 25.
- Initial script bytes: 2,251,100 -> 1,742,585.
- Initial HTML bytes: 378,090 -> 376,612.
- Games module switch lazy-loaded 19 runtime scripts.
- Trading module switch lazy-loaded 0 scripts.
- Console errors: 0.
- Page errors: 0.
- Server log findings: 0.
- QA perf server cleanup: no `hackme_web_perf_audit` process remained after the run.

Trading module Playwright snapshot:

- API calls on trading tab: 13.
- Live intervals remained trading-owned: 15s, 30s, 1s, 60s, 1.5s, 5s, 2s.
- No trading page error or console error.

## Trading Non-Regression

Command: `python3 scripts/trading/validation/trading_exchange_validation.py`

Result: 21 PASS.

Covered:

- spot buy/sell and fee reserve accounting
- DCA, conditional, workflow, and grid bot lifecycle
- guard rejection for extreme live price jumps
- long and short liquidation
- wallet non-negative invariant
- PointsChain verification and safe-mode blocking

Report artifacts:

- `/home/s92137/hackme_web/runtime/reports/trading_validation/trading_exchange_validation_20260515T031623Z.json`
- `/home/s92137/hackme_web/runtime/reports/trading_validation/trading_exchange_validation_20260515T031623Z.md`

## Other Checks

- `node --check public/js/38-games.js public/js/00-core.js public/js/56-trading.js`
- `pytest -q tests/frontend/games/test_frontend_games.py tests/frontend/auth/test_frontend_auth_timeout.py tests/frontend/chat/test_frontend_notifications.py`
- `git diff --check` for touched lazy-load/trading QA files

All listed checks passed.

## Remaining Load Sources

- `50-admin.js`, `56-trading.js`, `36-comfyui.js`, and `35-drive.js` remain the largest eager-loaded scripts.
- Trading was intentionally left eager-loaded to avoid changing exchange operation timing, root trading controls, or live-price bootstrap behavior in this pass.
