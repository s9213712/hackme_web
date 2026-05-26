# :5000 Cloud 7-Day And Trading Background QA

## Findings

1. High: trading background run-once queue could leave later jobs queued.
   - Cause: the root run-once kick processed the legacy 3-job default batch while rapid root enqueues added 5 jobs.
   - Fix: queue drain now loops batches and defaults queued processing to 10 jobs.
   - Evidence: `playwright_trading_background_correctness.py` passed after reload at `/tmp/hackme_5000_trading_background_after_price_window_fix/trading_background_correctness.json`.

2. High: `test_live_price_provider` TP/SL windows could use public candle highs/lows.
   - Cause: recent price window fetched indicator candles even when QA synthetic pricing was active.
   - Impact: price drop tests could trigger take-profit from unrelated public market candles.
   - Fix: synthetic provider windows now return the injected manual test price as low/high.
   - Evidence: `tests/trading/core/test_trading_engine.py::test_recent_price_window_uses_synthetic_provider_without_public_candles` passed, and live background run showed synthetic scan windows at the injected price.

3. Medium: cloud storage capacity preset text/duration had to be aligned to 7 days.
   - Fix: root quick settings, root catalog fallback, service recommendation, schema/default catalog and frontend tests now use `雲端容量 1GB / 7 天` with `duration_days: 7`.
   - Evidence: live :5000 catalog returned `cloud_storage_1gb_30d` with `duration_days: 7`; targeted share probe created a 7-day future share that dashboard marked active and public metadata/preview/download all returned 200.

4. Test harness issue: background interest fixture set legacy daily interest but left new APR fields at 0.
   - Fix: the Playwright trading background probe now sets both APR fields to match the test daily rate.
   - Evidence: live background run accrued margin interest with member browsers closed.

## Coverage

- Target server: `https://127.0.0.1:5000`, reloaded after code sync.
- Unit checks:
  - `python3 -m py_compile services/trading/price_runtime.py scripts/testing/playwright_trading_background_correctness.py`
  - `pytest -q tests/trading/core/test_trading_engine.py::test_recent_price_window_uses_synthetic_provider_without_public_candles`
  - `pytest -q tests/trading/core/test_trading_background_engine.py::test_background_queue_drains_more_than_legacy_three_job_batch`
  - Earlier focused cloud/catalog tests passed for 7-day metadata.
- Live trading foreground/background:
  - `python3 scripts/testing/playwright_trading_background_correctness.py --base-url https://127.0.0.1:5000 ... --stress-orders 20`
  - Passed: frontend trading load, governed treasury funding, spot SL/TP, limit matching, margin TP/liquidation/interest, conditional bot, root background UI, concurrent order stress, trading verify, PointsChain verify.
- Live cloud drive 7-day share:
  - `/tmp/hackme_cloud_7d_share_probe.py`
  - Passed: storage upgrade catalog is 7 days, dashboard share status active, public metadata/preview/download 200.
- Mixed system stress:
  - `/tmp/hackme_5000_system_stress_after_cloud7_trading.json`
  - Passed with `ok: true`: 160 requested mixed operations, no hard failures, only controlled `server_busy` 503 responses.
- Post-stress invariants:
  - `/tmp/hackme_post_stress_invariants.py`
  - Passed: trading verify ok, PointsChain verify ok, no queued/running background jobs, no negative points wallets, no negative spot locks.

## Notes

- The generic member probe on the reused `test` account reported video upload limit reached and one torrent request gated by `server_busy`. Targeted cloud share behavior passed, so those are treated as environment/load observations for this run, not confirmed product regressions.
- Current :5000 runtime still has accumulated QA data from repeated stress runs; repeated upload/video tests against `test` can hit quota limits unless a fresh account or quota reset is used.
