# 2026-05-24 11:01 +0800 `:5000` trading/background continuous QA

## Result

- No confirmed product defect in this pass.
- Trading background automation passed live `:5000` verification without an active member or root browser session.
- The task center contains recurring `trading_background` jobs for price refresh, order matching, TP/SL scan, bot scan, liquidation scan, and interest accrual.
- Post-trading live smoke and a final multi-account concurrent probe passed.

## Trading Background Evidence

- Wrapper: `/tmp/hackme_5000_trading_background_wrapper.py`
- Artifacts:
  - `/tmp/hackme_5000_trading_background_1779591380/trading_background_correctness.json`
  - `/tmp/hackme_5000_trading_background_1779591380/trading_background_correctness.md`
- Inner trading probe result:
  - `ok=True`
  - `failures=0`
  - `checks=57`
  - `reserve_before=5000000`
  - `reserve_after=5000000`
- Covered:
  - Root feature enablement and background status API initialization.
  - Governed PointsChain treasury grants to 11 fresh trading users.
  - Member trading UI load.
  - Spot stop-loss and take-profit.
  - Limit order background matching.
  - Margin open, interest accrual, take-profit, and liquidation.
  - Conditional workflow bot, DCA bot, and grid bot automatic execution.
  - Browser sessions closed before background jobs ran, proving server-owned execution.
  - Root background UI panel selectors and background status API after no-login jobs.
  - 36 concurrent order requests: 34 successful fills, 2 expected 403 responses, no 5xx.
  - `/api/root/trading/verify` and `/api/root/points/chain/verify`.
  - Non-negative wallet balances/frozen amounts and spot locked quantities.

## Task Center Evidence

Direct DB inspection of `job_center_jobs` found these `source_module='trading_background'` rows:

- `trading.background.price_refresh`: running, stage `success`.
- `trading.background.order_matching`: running, stage `success`.
- `trading.background.take_profit_stop_loss_scan`: running, stage `success`.
- `trading.background.bot_trigger_scan`: running, stage `success`.
- `trading.background.margin_liquidation_scan`: running, stage `success`.
- `trading.background.interest_accrual`: running, stage `success`.

## Post-Stress Regression

- `/tmp/hackme_5000_update_smoke.py` passed after the trading background run.
  - Covered home HTML, malicious login rejection, root login, `/api/me`, site config, jobs, shares, storage albums, community, chat, videos, trading dashboard/grid bots/asset overview, root backpressure, CSRF rejection, album share creation/listing, and key static assets.
- First post-trading concurrent probe:
  - Artifact: `/tmp/hackme_5000_concurrent_multifeature_1779591507.json`
  - 150 samples; one transport-level `ChunkedEncodingError` on the intentional wrong-CSRF request.
  - No server traceback and worker PIDs stayed stable.
- Focused wrong-CSRF repro:
  - Script: `/tmp/hackme_5000_csrf_repro_probe.py`
  - 160 wrong-CSRF requests: 158 returned 403 `csrf_invalid`, 2 returned 503 `server_busy` from backpressure.
  - No connection abort reproduced.
- Final concurrent multi-account probe:
  - Artifact: `/tmp/hackme_5000_concurrent_multifeature_1779591631.json`
  - 150 samples: 120 HTTP 200, 24 HTTP 400, 6 HTTP 403.
  - Hard failures: 0.

## Logs

- `runtime/logs/server.log` mtime remained `2026-05-24 10:09:19 +0800`.
- `runtime/logs/server_direct.out` mtime remained `2026-05-24 07:53:04 +0800`.
- The only tracebacks present are older `database is locked` traces from earlier stress windows; this pass did not write new server errors.

## Notes

- The first wrapper run had a wrapper-only restore bug: it assumed `trading_markets.id` existed, but the live schema keys markets by `symbol`.
- The live DB snapshot was restored manually with `/tmp/hackme_5000_restore_trading_snapshot.py`, and the wrapper was patched for future use.
- This did not require product-code changes or a `:5000` reload.

