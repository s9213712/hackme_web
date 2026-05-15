# Frontend Performance Audit - 2026-05-15 07:27

## Scope

Performance-oriented audit for code patterns that make the web UI slower than necessary. This pass focused on initial page weight, hidden module initialization, background polling, per-frame DOM work, and module switching.

Repo: `/home/s92137/hackme_web`  
Branch observed: `03b.Comfyui`  
Probe runtime: `/tmp/hackme_web_perf_audit_20260515_072549_3702659`  
Raw probe JSON: `/tmp/hackme_perf_audit_latest.json`

## Commands

- Static scans:
  - `git -C /home/s92137/hackme_web status -sb`
  - script inventory from `/home/s92137/hackme_web/public/index.html`
  - `rg` scans for `setInterval`, `DOMContentLoaded`, document-wide listeners, RAF HUD updates
- Browser probe:
  - isolated server via `scripts/testing/playwright_deep_site_check.py` helpers
  - Playwright Chromium login as root
  - switched `chat`, `drive`, `comfyui`, `games`, `trading`, `videos`, `accounts`, `server`
  - collected resource entries, fetches, live intervals, DOM node counts, console/page/server errors

## Measurements

Initial authenticated page:

- `public/index.html`: 375,861 bytes
- `public/styles.css`: 233,029 bytes
- Unconditional scripts on index: 45 files / 2,903,261 bytes from filesystem
- Browser resource entries after load: 70
- Script resources after load: 45
- DOM nodes after login: 5,310
- Module sections in DOM: 16
- Hidden module sections: 14
- API calls during initial authenticated load: 16
- Live intervals after initial authenticated load: 13

Largest unconditional scripts:

- `/js/three.min.js`: 669,884 bytes
- `/js/50-admin.js`: 325,441 bytes
- `/js/56-trading.js`: 306,673 bytes
- `/js/36-comfyui.js`: 185,058 bytes
- `/js/35-drive.js`: 161,105 bytes
- `/js/games/stickman-shooter.js`: 108,694 bytes
- `/js/38-fps-arena.js`: 92,180 bytes
- `/js/36-comfyui-workflows.js`: 86,109 bytes
- `/js/games/open-world.js`: 74,209 bytes
- `/js/39-videos.js`: 73,209 bytes

## Findings

### P1 - All Major Apps Load on Every Page Open

`public/index.html` loads 45 scripts unconditionally, including all games, Three.js, admin, trading, ComfyUI, cloud drive, videos, and bootstrap. The DOM also contains all major modules up front, with 14 of 16 modules hidden after login.

Primary references:

- `/home/s92137/hackme_web/public/index.html`
- script block around the final script list
- module sections such as `module-drive`, `module-games`, `module-comfyui`, `module-trading`, `module-accounts`, `module-server`

Impact:

- Mobile and low-end devices pay parse/compile cost for features the user may never open.
- Three.js and every local game load even if the user only wants chat or cloud drive.
- Hidden DOM still increases selector scans, style calculation, memory, and event binding cost.

Recommended fix:

- Keep only core/auth/nav/bootstrap critical scripts in the initial page.
- Lazy-load module scripts on first activation with a module registry such as `loadModuleAssets("games")`.
- Split 3D dependencies: load `three.min.js` only for 3D FPS/open-world modules.
- Move game modules behind the game catalog; load one game bundle only when selected.
- Split `styles.css` into critical shell CSS plus module CSS loaded on demand.

### P1 - Trading Timers Start Globally and Stay Alive Off Page

The probe recorded trading timers active on the initial authenticated page and still active while switching to unrelated modules. Background trading requests appeared in `videos`, `accounts`, and `server` module measurements.

Primary references:

- `/home/s92137/hackme_web/public/js/56-trading.js:5915`
- `/home/s92137/hackme_web/public/js/56-trading.js:5916`
- `/home/s92137/hackme_web/public/js/56-trading.js:5918`
- `/home/s92137/hackme_web/public/js/56-trading.js:5929`
- `/home/s92137/hackme_web/public/js/56-trading.js:5940`
- `/home/s92137/hackme_web/public/js/56-trading.js:5943`
- `/home/s92137/hackme_web/public/js/56-trading.js:5948`

Observed live intervals:

- `syncTradingReserveUserOptions` every 1.5s
- reference price refresh every 1s
- reference chart refresh every 5s
- dashboard refresh every 5s
- live price refresh every 2s
- trial countdown every 1s
- BTC signal countdown every 1s

Impact:

- Server load and browser work continue outside the trading page.
- Hidden trading UI can still trigger `/api/trading/live-price` and reference-price fetches.
- This also explains the user's earlier symptoms where financial values appeared to jump in unrelated contexts.

Recommended fix:

- Convert trading to a lifecycle module:
  - `startTradingModule()` on entering trading/economy when needed.
  - `stopTradingModule()` when leaving.
  - clear all interval IDs, including `syncTradingReserveUserOptions`.
- Keep countdown rendering local to visible cards.
- Use document visibility to pause non-critical refresh when the tab is hidden.
- Prefer a single scheduler for all trading polling, with visible-state checks before creating the interval, not only inside each tick.

### P1 - Initial Login Triggers API Work for Hidden Modules

Initial authenticated load made 16 API calls, including admin users, admin appeals, notifications, chat rooms, ComfyUI status, chat friends/messages, cloud-drive refs, and game multiplayer invites.

Primary references:

- `/home/s92137/hackme_web/public/js/00-core.js:1535`
- `/home/s92137/hackme_web/public/js/00-core.js:1557`
- `/home/s92137/hackme_web/public/js/90-bootstrap.js:588`
- `/home/s92137/hackme_web/public/js/90-bootstrap.js:250`

Impact:

- Login latency is coupled to hidden modules.
- Root/admin users pay the heaviest startup cost.
- ComfyUI/admin/chat calls compete with the first visible page render.

Recommended fix:

- After login, fetch only `/api/me`, site config, and the active module's bootstrap payload.
- Delay `loadUsers`, `loadAdminAppeals`, `loadChatRooms`, `loadComfyuiStatus`, and module dashboards until their tab is entered.
- Keep notifications if required globally, but make it low-frequency/backoff.

### P2 - Game Multiplayer Invite Polling Runs Globally

Game invite polling starts on `DOMContentLoaded` and calls `/api/games/multiplayer/invites/pending` every 5 seconds regardless of active module.

Primary references:

- `/home/s92137/hackme_web/public/js/38-games.js:817`
- `/home/s92137/hackme_web/public/js/38-games.js:820`
- `/home/s92137/hackme_web/public/js/38-games.js:1408`

Impact:

- This is intentionally global for cross-area invite popups, but it currently has no login/visibility/backoff lifecycle.
- It adds permanent network noise on every logged-in page.

Recommended fix:

- Start only after authenticated state is known and games feature is enabled.
- Pause or slow down when `document.hidden`.
- Add exponential backoff when there are no pending invites or recent activity.
- Longer term: replace with SSE/WebSocket/user notification channel.

### P2 - Bootstrap Binds Most Modules Up Front

`bindUiEvents()` wires controls for chat, community, drive, games, ComfyUI, trading, admin, economy, and settings in one pass. Other modules also self-bind on `DOMContentLoaded`.

Primary references:

- `/home/s92137/hackme_web/public/js/90-bootstrap.js:250`
- `/home/s92137/hackme_web/public/js/90-bootstrap.js:335`
- `/home/s92137/hackme_web/public/js/55-economy.js:1068`
- `/home/s92137/hackme_web/public/js/56-trading.js:5948`

Impact:

- Startup cost scales with the whole product, not the visible module.
- Hidden modules still create document listeners, timers, local state, and DOM reads.

Recommended fix:

- Introduce a module lifecycle contract:
  - `init()` once
  - `mount()` on visible
  - `unmount()` on hidden
  - `destroy()` on logout/full reset
- Move module-specific event binding into the module's `init()` and call it on first activation.

### P2 - 3D Game HUDs Rebuild DOM Every Frame

Open-world and FPS Arena update HUD via `innerHTML` inside RAF loops.

Primary references:

- `/home/s92137/hackme_web/public/js/games/open-world.js:1461`
- `/home/s92137/hackme_web/public/js/games/open-world.js:1609`
- `/home/s92137/hackme_web/public/js/38-fps-arena.js:248`
- `/home/s92137/hackme_web/public/js/38-fps-arena.js:1983`

Impact:

- Rebuilding HUD HTML at 60fps creates avoidable layout/style work.
- Open-world also redraws minimap each HUD update.
- This cost is visible on mobile and during 3D rendering, where GPU/CPU budget is already tight.

Recommended fix:

- Pre-create HUD spans and update `textContent`.
- Cache previous HUD values and update only when values change.
- Throttle HUD/minimap updates to 5-10Hz while keeping render RAF at display rate.

### P2 - Global CSS Is Large and Unsplittable

`public/styles.css` is 233KB and loaded for every user regardless of active module.

Impact:

- Style calculation includes selectors for unrelated modules.
- UI additions make the first page increasingly expensive.

Recommended fix:

- Keep shell/auth/nav/critical common styles in `styles.css`.
- Move large module surfaces into module CSS files loaded with their module.
- Start with high-churn modules: games, trading, ComfyUI, cloud drive, admin.

### P3 - Document-Wide Event Delegation Is Growing

Several modules attach document-wide listeners at script load.

Examples:

- `/home/s92137/hackme_web/public/js/35-drive.js:3589`
- `/home/s92137/hackme_web/public/js/38-games.js:1160`
- `/home/s92137/hackme_web/public/js/39-videos.js:1661`
- `/home/s92137/hackme_web/public/js/57-platform-centers.js:626`

Impact:

- Event delegation is acceptable, but each global listener adds path checks for unrelated interactions.
- This becomes more expensive as hidden module DOM and selectors grow.

Recommended fix:

- Bind document-level handlers only while the owning module is mounted where possible.
- Keep truly global handlers small and route by a single nearest module root check.

## Incidental Non-Performance Finding

The browser probe hit two unexpected 500s when switching to cloud drive:

- `GET /api/storage/albums`
- `GET /api/storage/folders`

Server log shows both routes concurrently called `ensure_output_album()`, which attempted to create `/output` and hit:

`sqlite3.IntegrityError: UNIQUE constraint failed: storage_folders.owner_user_id, storage_folders.virtual_path`

Primary references:

- `/home/s92137/hackme_web/routes/files.py:1506`
- `/home/s92137/hackme_web/routes/files.py:1765`
- `/home/s92137/hackme_web/services/storage/albums.py:317`
- `/home/s92137/hackme_web/services/storage/catalog.py:504`

This should be fixed separately by making output-folder creation idempotent/race-safe, for example `INSERT OR IGNORE` plus re-select, or catching the unique violation and returning the existing folder.

## Priority Plan

1. Add module lifecycle and lazy-load scripts for large modules.
2. Move trading timers behind trading/economy visibility and clear them on exit.
3. Stop hidden-module startup API calls after login.
4. Keep global invite/notification polling but add auth/feature/visibility/backoff guards.
5. Throttle 3D HUD/minimap DOM updates.
6. Split CSS by module after lifecycle boundaries exist.

## Verification Notes

The baseline Playwright perf probe completed and stopped its isolated server process. It found no page errors, but it did capture console errors caused by the two cloud drive 500 responses and a transient `site config load failed` fetch error during page initialization.

## Follow-Up Rescan and Optimizations - 2026-05-15 08:15

Raw probe JSON: `/tmp/hackme_perf_audit_after_second_pass.json`  
Probe runtime: `/tmp/hackme_web_perf_audit_20260515_081540_3773733`

Static rescan coverage:

- Frontend: script inventory, large module files, `setInterval`, `requestAnimationFrame`, `innerHTML`, global listeners, and forced CSRF refreshes.
- Backend: `SELECT *`, `fetchall()`, subprocess use, sleeps, and query loops in `services/`, `routes/`, and `scripts/`.
- Vendor/minified matches were ignored as source-level findings unless they were loaded unconditionally by `index.html`.

Implemented fixes:

- Removed unconditional `three.min.js` from `public/index.html` and added `ensureThreeJsLoaded()` lazy loading for FPS Arena and Open World.
- Deferred hidden-module startup API work after login: chat/admin/appeals/ComfyUI data now loads through module activation instead of every authenticated page open.
- Added lifecycle guards for chat polling, game multiplayer invite polling, trading timers, and economy auto-refresh so hidden modules stop doing background work.
- Reduced GET/read-only CSRF refreshes across users, chat, appeals, notifications, drive, ComfyUI, games, trading, admin, and server-mode read paths.
- Removed the high-frequency forced CSRF refresh from cloud-drive remote-download status polling and preview/read flows.
- Throttled 3D HUD/minimap DOM work in FPS Arena and Open World.
- Made storage output-folder creation race-safe by re-reading after a unique constraint conflict.
- Removed the `list_grid_bots()` N+1 order query by loading all visible bot orders in one `IN (...)` query.

Before/after probe summary:

| Metric | Baseline | After |
| --- | ---: | ---: |
| Initial scripts | 45 | 44 |
| Initial script bytes | 2,903,261 | 2,242,442 |
| Initial authenticated API calls | 16 | 6 |
| Initial live intervals | 13 | 4 |
| 6.5s idle API calls | 24 | 7 |
| 6.5s idle live intervals | 13 | 4 |
| Console errors | 3 | 0 |
| Server log findings | 6 | 0 |

Final module-switch probe:

| Module | API calls | Live intervals | CSRF fetches |
| --- | ---: | ---: | ---: |
| chat | 4 | 5 | 0 |
| drive | 9 | 4 | 1 |
| comfyui | 7 | 4 | 1 |
| games | 9 | 4 | 0 |
| trading | 13 | 11 | 1 |
| videos | 3 | 4 | 0 |
| accounts | 2 | 4 | 0 |
| server | 2 | 5 | 0 |

Remaining performance risks:

1. `index.html` still loads large first-party modules up front, especially admin, trading, ComfyUI, cloud drive, game shell, and videos. Full module-level lazy loading is still the largest remaining startup win.
2. `public/styles.css` is still a single 233KB global stylesheet. Module CSS splitting should follow the module lifecycle boundary work.
3. Trading is now scoped to active trading/economy views, but the active trading module still has 13 API calls and 11 live intervals in the probe. Batching or SSE/WebSocket fanout would reduce active-page load.
4. Cloud-drive remote download status still polls every 900ms while a transfer is running. It no longer refreshes CSRF every tick, but server-pushed job updates would scale better.
5. Backend scans still contain many legitimate `SELECT *`/`fetchall()` uses in admin, reports, snapshots, and trading. The confirmed N+1 in grid bot listing was fixed; remaining hits should be reviewed per endpoint with pagination and result-size limits rather than changed mechanically.

Verification run after the follow-up pass:

- `node --check` on changed frontend files, including `00-core.js`, `35-drive.js`, `38-games.js`, `38-fps-arena.js`, `51-admin-server-mode-launch-check.js`, `56-trading.js`, and `games/open-world.js`.
- `python3 -m py_compile services/storage/catalog.py services/trading/grid.py`
- Storage regression subset: `tests/storage/test_storage_albums_schema.py` and targeted cloud-drive attachment/storage tests.
- Trading regression subset: targeted grid bot and trading boot-ready tests.
- Playwright perf probe: clean console errors, page errors, and server log findings.
