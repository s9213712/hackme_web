# 2026-05-25 12:10 :5000 Continuous QA - pc0/Trading

## Findings

No confirmed product bug remains from this slice.

## Fixes Applied

- Updated `scripts/testing/points_chain_destructive_stress.py` for the pc0 dual-rail model:
  - Official pc0 grants are now treated as immediate internal ledger credits instead of pending/proved chain transfers.
  - Small-account transfer stress no longer selects the sender as recipient.
  - Priority-fee acceleration now targets only cold-chain pending transfers; pc0 internal transfers are skipped because they settle immediately and cannot be accelerated.

## Evidence

- Initial fixed-account member probe failed because the shared `test` account had reached the daily upload limit, not because previews/video were broken:
  - `/tmp/hackme_web_qa_5000_member_probe.json`
- Fresh active QA member probe passed cloud upload/preview, E2EE preview refusal, share download, remote download SSRF block, video password-share playback, and grid fee math:
  - `/tmp/hackme_web_qa_5000_fresh_member_probe.json`
- Low-intensity PointsChain/trading destructive smoke passed after script correction:
  - `/tmp/hackme_web_qa_5000_points_trading_stress_smoke.json`
  - `ok=true`, no findings, no duplicate request UUIDs, no duplicate active wallet address bindings, chain verify ok, 2/2 trading limit buys accepted.
- Chat frontend video share-link rendering passed with no browser errors:
  - `/tmp/hackme_web_qa_5000_chat_video_share_probe.json`
- Root/admin/test API smoke passed:
  - `/tmp/hackme_web_qa_5000_admin_api_smoke.json`
  - Covered admin health, server output, job center permissions, trading background status, root sitewide pools/positions, root trading verify, chain verify, admin user wallet/balance list, test trading dashboard, and negative permission checks.
- Multi-role frontend patrol passed on the live `:5000` instance:
  - `/tmp/hackme_web_qa_5000_frontend_patrol.json`
  - Logged in as `root`, `admin`, `test`, and `qa_bg_1779629872_limit`; clicked visible main modules for each role.
  - No browser page errors, console errors, or API 4xx/5xx surfaced during module switching.
  - Root-only server center stayed hidden from `admin` and regular members; root could see it.
- Trading sell-side hint was rechecked with a real held asset:
  - `/tmp/hackme_web_qa_5000_trading_sellable_targeted_v2.json`
  - `qa_bg_1779629872_limit` held `5 ETH` on `ETH/POINTS`; selecting sell showed `可賣 5 ETH`, total held, locked quantity, estimated value, and the pc0 wallet hint.
- Medium PointsChain/trading stress passed on the live runtime after the pc0 stress-script correction:
  - `/tmp/hackme_web_qa_5000_points_trading_stress_r2.json`
  - `ok=true`, 4 QA accounts, 8 transfers, 8 trading buys, chain seal/verify ok, duplicate UUID/address checks ok, no findings.
- Trading background jobs were manually queued and verified:
  - `/tmp/hackme_web_qa_5000_trading_background_run_once_r2.json`
  - `/tmp/hackme_web_qa_5000_job_center_admin_check.json`
  - Price refresh, order matching, TP/SL scan, bot trigger scan, margin liquidation scan, interest accrual, and sitewide metrics refresh all accepted queue requests and reported recent success.
  - Root task center uses `/api/admin/jobs`; it showed 7 `trading_background` jobs. `/api/jobs` only shows the current user's owner-scoped jobs, so root's personal list being empty is expected.
- Cloud-drive share expiry / reactivation and parallel background checks passed:
  - `/tmp/hackme_web_qa_5000_share_expiry_jobs_parallel_v2.json`
  - Created a fresh member, created a text file, created a short-expiry file share, and verified Share Management reported `active -> expired -> active` after reactivation.
  - Public share API returned 200 before expiry, unavailable with `reason=expired` after expiry, and 200 again after extending the expiry.
  - A malicious E2EE secret field in share creation was rejected with 400.
  - A direct `pc1 -> pc0` transfer attempt was rejected with `pc0_internal_address_not_chain_reachable`.
  - In parallel, root job center, trading background status, `price_refresh`, `order_matching`, and an admin-forbidden root chain verify permission check all returned expected statuses.
- QA-created BT/magnet remote download tasks were cancelled and removed after the run:
  - `/tmp/hackme_web_qa_5000_remote_cleanup_final.json`
- Parallel member/API QA passed on the live `:5000` instance:
  - `/tmp/hackme_web_qa_5000_parallel_member_flow_20260525_r3.json`
  - Created two fresh members, verified registration returned pc0 official hot wallets, pc1 deposit addresses, and immediate signup bonus ledgers, then root-approved and logged both in.
  - Ran 57 concurrent normal and malicious requests across pc0 wallet/deposit, pc0->pc0 transfer, pc1->pc0 direct-transfer rejection, cloud text file creation, 7-day file share creation, E2EE secret-leak rejection, chat script-like payload handling, community missing-board rejection, game score tamper rejection, trading grid preview, limit order, cold-wallet order rejection, margin open, notifications, personal jobs, root trading background run-once, root sitewide positions, root admin jobs, and admin-forbidden root background status.
  - Result: `ok=true`, 0 unexpected statuses, 0 transport failures, 0 5xx; p95 latency 830.774 ms, max 1222.462 ms.
- Frontend Playwright trading/wallet/jobs patrol passed after invalidating two harness false positives:
  - `/tmp/hackme_web_qa_5000_frontend_trading_wallet_jobs_20260525_r2.json`
  - `/tmp/hackme_web_qa_5000_trading_sell_hint_spot_playwright_20260525.json`
  - Root and a fresh member loaded the live frontend with no page errors and no hard JS console errors; specifically no `tradingSpotUnrealizedPnl is not defined` regression.
  - Root full-site positions board rendered PnL and fee fields, including spot positions, margin positions, and bot status.
  - Member wallet API reported a pc0 active wallet, and the spot order form sell-side hint rendered `可賣` on the actual spot page.
- Post-run log scan found no `Traceback`, `ERROR`, `NameError`, `ReferenceError`, `tradingSpotUnrealizedPnl`, `server_busy`, or CSRF-invalid flood in `runtime/logs/server_direct.out`; only self-signed TLS warnings from local browser probes appeared.

## Coverage Notes

- `:5000` remained up after the stress run.
- This slice did not reload the server because no product bug requiring code changes was confirmed.
- A first attempt at the share-expiry probe failed because the test harness forgot to disable TLS verification for anonymous public share requests against the local self-signed server; `/tmp/hackme_web_qa_5000_share_expiry_jobs_parallel_v2.json` is the corrected evidence.
- The first two parallel/member and frontend probes had harness false positives:
  - `/tmp/hackme_web_qa_5000_parallel_member_flow_20260525.json` used a stale CSRF token after login, so root approval was blocked by CSRF; rerun `r2` fixed CSRF but did not parse the new `active_wallet_address` wallet payload shape.
  - `/tmp/hackme_web_qa_5000_frontend_trading_wallet_jobs_20260525_r2.json` checked the sell hint after switching to "my positions", where the spot order form is intentionally hidden; `/tmp/hackme_web_qa_5000_trading_sell_hint_spot_playwright_20260525.json` is the corrected spot-page check.
- The fixed `test` account is still upload-limited for the day; future long-running live probes should use a fresh QA account or a clean isolated runtime to avoid false positives.
