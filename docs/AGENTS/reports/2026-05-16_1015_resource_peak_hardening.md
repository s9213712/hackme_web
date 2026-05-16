# 2026-05-16 Resource Peak Hardening QA

## Reproduced Root Cause

The concrete reproduced crash was a trading first-hit race, not a generic frontend timeout. Multiple fresh sessions opened `/api/trading/dashboard` at the same time; each request saw no existing `trading_trial_credits` row and tried to insert the first trial-credit grant for the same user. SQLite correctly rejected the duplicate unique key, and the route returned 500.

The fix is to make trial-credit grant creation idempotent with `INSERT OR IGNORE`, then write the grant audit only when this request actually inserted the row. After restart, 48 concurrent dashboard hits returned `200`, `ok=true`, with no failures. The final server log also had no `Traceback`, `ERROR`, `500`, or `IntegrityError` matches.

## Findings

1. High: stale dev server still consumes production-sized resources.
   - Evidence: PID `3304746`, cwd `/tmp/hackme_web_dev_20260514_230057_3302903/hackme_web`, RSS about `1.8 GB`, 59 threads, average CPU about `31%`.
   - Server log showed in-process Diffusers/SDXL model loading inside Flask.
   - Fix applied in repo: `services/comfyui/diffusers_client.py` now refuses in-process Diffusers unless `HTML_LEARNING_ALLOW_IN_PROCESS_DIFFUSERS=1`. Existing stale PID was not killed because it was not started by this run.

2. High: `/api/trading/dashboard` had a first-hit race that could return 500 under concurrent user traffic.
   - Evidence: stress run logged `sqlite3.IntegrityError: UNIQUE constraint failed: trading_trial_credits.user_id`.
   - Fix applied: `services/trading/trial_credit.py` now creates trial credit with `INSERT OR IGNORE` and audits only the inserted row.
   - Verification: 48 concurrent dashboard requests after restart returned `200`, `ok=true`, failures `[]`.

3. Medium: root system resource board spawned `nvidia-smi` during concurrent reads.
   - Evidence: stress run saw child process `/usr/lib/wsl/lib/nvidia-smi ...` from `/api/admin/environment`.
   - Fix applied: `routes/system_admin_sections/security_routes.py` now caches resource snapshots for 5 seconds and protects refresh with a lock.
   - Verification: final stress read burst saw `child_count=0` for root environment reads.

4. Medium: Stockfish practice could spawn multiple heavy external engines.
   - Evidence: 3 concurrent Stockfish requests spawned 3 child processes; each Stockfish process temporarily used high RSS.
   - Fix applied: `services/games/chess_stockfish_teacher.py` defaults to one concurrent Stockfish engine, 2 second queue wait, and `Hash=16 MB`.
   - Verification: final Stockfish stress saw `child_count=1`; no child process remained after completion.

5. Medium: concurrent login is still intentionally expensive, but now bounded.
   - Evidence before hardening: 13 concurrent logins peaked at about `873%` CPU and `378 MB` RSS.
   - Fix applied: `services/users/auth.py` limits concurrent Argon2 verification with `HTML_LEARNING_ARGON2_VERIFY_CONCURRENCY` defaulting to `min(4, CPU cores)`.
   - Verification after hardening: comparable login burst peaked at about `751%` CPU and `266 MB` RSS. CPU remains high by design; memory burst is lower and bounded.

6. Medium: initial browser loads still request the full frontend script set.
   - Evidence: Playwright multi-context reload fetched all major modules, including drive, ComfyUI, games, videos, admin, economy, and trading scripts.
   - Partial fix applied: versioned `/js/*`, `/styles.css`, and `/assets/*` responses now use long immutable cache headers to reduce repeat server hits.
   - Remaining work: true module lazy loading still needs a separate frontend refactor. Trading scripts must stay eager enough that exchange status, worker visibility, and submitted commands remain reliable.

## Stress Coverage

- Startup check: temporary dev runtime no longer runs trading backtest capacity probe by default.
- API behavior: authenticated user reads, root environment reads, trading dashboard, jobs, shares, cloud drive, videos, albums, games, ComfyUI status.
- Upload behavior: standard upload, server-encrypted upload, resumable/chunk upload, duplicate/wrong/missing chunk paths.
- Fuzz behavior: invalid direct-link/magnet combinations, missing-CSRF POSTs.
- Browser behavior: desktop/mobile Playwright module switching and reload storms.
- Chess: Stockfish depth `99` fuzz path verifies server clamps depth and external process handling.

## Artifacts

- Pre-hardening authenticated probe: `/tmp/hackme_web_resource_user_20260516_0940/resource_probe/result_rerun.json`
- Pre-hardening mixed stress: `/tmp/hackme_web_resource_user_20260516_0940/resource_probe/stress_result.json`
- Post-hardening mixed stress: `/tmp/hackme_web_resource_hardened_20260516_1010/resource_probe/stress_result_after.json`
- Final short stress after trial-credit fix: `/tmp/hackme_web_resource_hardened_20260516_1020/resource_probe/stress_result_final_short.json`
- Final server log: `/tmp/hackme_web_resource_hardened_20260516_1020/hackme_web/runtime/logs/server_direct.out`

## Residual Risk

- One extreme 4-context browser storm timed out waiting for the app nav, but a normal mobile Playwright login immediately after passed. No 500 was logged.
- The frontend is still large on first load. Immutable cache reduces repeat load pressure, but real lazy loading remains the next meaningful frontend performance task.
- Existing stale local servers remain outside this QA run; the largest confirmed one is PID `3304746`.
