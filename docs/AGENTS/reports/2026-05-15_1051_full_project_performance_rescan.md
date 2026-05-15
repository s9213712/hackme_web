# Full Project Performance Rescan

- Date: 2026-05-15 10:51 Asia/Taipei
- Scope: Flask routes/services, PointsChain/background jobs, storage admin paths, frontend boot bundle, module switching, polling timers, trading validation, and Playwright browser checks.
- Result: targeted fixes landed for confirmed server-load regressions; remaining high-impact work is frontend bundle/module lazy loading and API batching.

## Fixes Applied

1. PointsChain block worker no longer performs a full chain verification every 15-second schedule check when no block is due.
   - `seal_due_block()` now uses a cheap block schedule snapshot first.
   - Full `verify_chain()` still runs before any actual seal, preserving fail-closed behavior.
   - `root_report()` now reuses one verification result for the report, economy stats, and block schedule instead of scanning the chain repeatedly.

2. Admin storage quota sync no longer does an N+1 user lookup.
   - The route now selects full user rows once and passes the row directly into quota/usage calculation.

3. Frontend always-on polling pressure was reduced.
   - Server connection monitor: 8s -> 15s.
   - Game invite polling when not actively on games page: 30s -> 60s visible idle, 60s -> 180s hidden.
   - Active games page invite polling remains 5s.

4. Game frontend static test was updated for the current lazy Three.js design.
   - `three.min.js` is no longer expected in `index.html`.
   - The test now asserts the lazy loader in `00-core.js`.

## Playwright Rescan Evidence

Final artifact: `/tmp/hackme_perf_audit_rescan_after_fixes_20260515.json`

- Initial HTML: 378,090 bytes
- CSS: 233,029 bytes
- Initial script count: 44
- Initial script bytes: 2,251,100
- Initial authenticated DOM nodes: 5,326
- Initial authenticated API resources: 6
- Idle after 6.5s API resources: 6
- Live global intervals after fixes: 15s server connection, 30s notifications, 60s game invite idle, 1s inactivity countdown
- Browser console errors: 0
- Browser page errors: 0
- Server log findings: 0
- Perf audit process cleanup: no `hackme_web_perf_audit` process remained after the run

Top initial scripts still loaded eagerly:

| Script | Bytes |
| --- | ---: |
| `/js/50-admin.js` | 334,304 |
| `/js/56-trading.js` | 310,097 |
| `/js/36-comfyui.js` | 184,983 |
| `/js/35-drive.js` | 160,930 |
| `/js/games/stickman-shooter.js` | 108,694 |
| `/js/38-fps-arena.js` | 93,277 |
| `/js/36-comfyui-workflows.js` | 86,094 |
| `/js/games/open-world.js` | 75,138 |
| `/js/39-videos.js` | 73,209 |
| `/js/00-core.js` | 71,099 |

Module-switch API counts after fixes:

| Module | API calls | Live intervals | Notes |
| --- | ---: | --- | --- |
| chat | 4 | 15s, 30s, 60s, 2.5s, 1s | chat poll only while chat is active |
| drive | 9 | 15s, 30s, 60s, 1s | several independent dashboard endpoints |
| comfyui | 7 | 15s, 30s, 60s, 1s | model/history/workflow calls can be batched later |
| games | 9 | 15s, 30s, 1s, 5s | active game invite poll correctly switches to 5s |
| trading | 12 | 15s, 30s, 1s, 60s, 1.5s, 5s, 2s | heaviest runtime timer/API surface |
| videos | 4 | 15s, 30s, 1s, 60s | one trading price request was aborted during tab switch |
| accounts | 1 | 15s, 30s, 1s, 60s | acceptable |
| server | 2 | 15s, 30s, 1s, 60s, 2.5s | server output poll is scoped to server tab |

## Backend Static Scan Findings

- Scanned 220 Python files for heavy loops, repeated DB reads, full-table reads, sleep/poll loops, and verification paths.
- Confirmed and fixed:
  - `services/points_chain/service.py`: repeated full-chain verification in background schedule/root report paths.
  - `routes/file_sections/admin_storage_routes.py`: N+1 query during root storage quota sync.
- Confirmed existing safeguards:
  - Trading validation still passes after this performance pass.
  - Background trading validation covers prices, order matching, TP/SL, liquidation, interest, idempotency, lease contention, fail-closed provider behavior, and server mode scopes.

## Remaining Performance Risks

1. Initial frontend payload is still too large.
   - 44 scripts and 2.25 MB of JS are loaded on the first page even when most modules are hidden.
   - Next recommended fix: move admin, trading, comfyui, drive, videos, and game implementations behind route/module-level lazy loaders.

2. Trading remains the heaviest active module.
   - Switching into trading triggers 12 API calls and multiple short timers.
   - Next recommended fix: consolidate trading dashboard/bootstrap payloads and centralize live price/ticker timers through one module scheduler.

3. Drive, games, and comfyui still perform bursty module initialization.
   - Drive: 9 API calls.
   - Games: 9 API calls.
   - ComfyUI: 7 API calls.
   - Next recommended fix: add combined bootstrap endpoints or local short-lived response caches.

4. Global CSS is still large.
   - `styles.css` is 233 KB and is loaded globally.
   - Next recommended fix: split admin/trading/game/comfyui styles by feature module once JS lazy loading is in place.

5. Some full verification/restore paths are intentionally heavy.
   - PointsChain manual verification, restore consistency checks, and audit reports should remain full scans by default.
   - Next recommended fix: keep them root/manual or scheduled, and expose recent snapshot status for routine UI display.

## Validation Commands

- `python3 -m py_compile services/points_chain/service.py routes/file_sections/admin_storage_routes.py`
- `pytest -q tests/points/test_points_chain.py tests/storage/test_storage_maintenance.py tests/platform/test_startup_worker_feature_gates.py`
- `python3 scripts/trading/validation/trading_exchange_validation.py`
- `node --check public/js/00-core.js public/js/38-games.js`
- `pytest -q tests/frontend/games/test_frontend_games.py tests/frontend/auth/test_frontend_auth_timeout.py tests/frontend/chat/test_frontend_notifications.py`
- `python3 /tmp/hackme_perf_audit.py > /tmp/hackme_perf_audit_rescan_after_fixes_20260515.json`

All listed validation commands passed.
