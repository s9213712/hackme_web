# Issue #145 Closeout Report

Date: `2026-05-06`
Branch: `03.Points`

## Scope

Close GitHub issue `#145`:

- `server_encrypted` uploads must not write plaintext to any persistent disk
  path before scanning / encryption complete

Also repair the already-committed backtest-cap route regression that broke
`tests/test_trading_reference_prices.py` on this branch baseline.

## Files Changed

- `services/cloud_drive.py`
- `tests/test_cloud_drive_attachments.py`
- `services/release_info.py`
- `docs/UPDATE_SUMMARY.md`
- `README.md`
- `docs/README.zh-TW.md`
- `docs/For_developer.md`
- `routes/trading.py`

## What Changed

- `server_encrypted` upload now buffers plaintext in memory, exposes it to the
  scanner stack through a Linux `memfd` file-descriptor path (`/proc/self/fd/*`),
  and writes only ciphertext to the final storage path
- no plaintext temp file is created on disk during upload scanning
- the regression test now asserts:
  - scanner sees plaintext
  - scan path is not the final storage path
  - scan path is memory-backed (`/proc/self/fd/...`)
  - final storage path never contains plaintext during scan
- backtest auto-fetch routes now:
  - fall back to `MAX_BACKTEST_CANDLES` when a lightweight fake service does
    not implement `get_max_backtest_candles()`
  - keep `BACKTEST_PROVIDER_CANDLE_LIMIT` as the provider batch limit instead
    of incorrectly replacing it with the user-facing overall backtest cap

## Validation

- `PYTHONPATH=. python3 -m pytest -q tests/test_cloud_drive_attachments.py`
  - `54 passed`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_reference_prices.py -k "backtest_downloads_historical_candles_when_browser_did_not_send_any or backtest_download_supports_full_year_hourly_window or backtest_download_supports_ranges_above_single_execution_batch"`
  - `3 passed`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_issue145_clean2_20260506 PYTHONPATH=. python3 -m pytest -q tests/`
  - `1064 passed`
- `python3 scripts/pre_push_checks.py --ci`
  - `11 PASS / 0 FAIL`

## Outcome

Issue `#145` can be closed once the patch is committed/pushed, because the
remaining plaintext window in the upload path has been removed.
