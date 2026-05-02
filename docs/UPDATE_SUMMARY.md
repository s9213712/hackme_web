# Update Summary

Release ID: `2026.05.02-044`

## Highlights

- Server update (settings page) no longer hard-blocks when the working directory
  has uncommitted changes. Runtime-generated files (logs, DB, caches) are now
  auto-stashed before the merge and restored afterwards, so a live server can
  always be updated without manual git cleanup.
- Binance klines fetch now paginates backwards (up to 5000 candles / 5 requests)
  so backtest windows up to the engine limit are fully covered.
- Backtest API accepts a `days` parameter; the server auto-calculates the candle
  count and returns `backtest_window_days` / `max_backtest_days` / `backtest_limits`
  so the frontend never needs to compute candle counts.
- DCA bot: enabling a bot via toggle now triggers the first deduction immediately
  (same as a fresh create). Countdown shows "等待首次執行…" before the first run
  then ticks down with the interval period label.
- Update summary from `docs/UPDATE_SUMMARY.md` is now displayed in the settings
  panel after each server update.
- Pre-push hook (`hooks/pre-push`) auto-bumps `APP_RELEASE_ID` and syncs the
  Release ID in this file on every push. Run `bash hooks/install-hooks.sh` to
  install after cloning.

## Operator Notes

- The pre-push hook amends the tip commit with the version bump before the push
  is sent. You still need to manually write the Highlights section in this file
  before pushing.
- Server updates applied from the root settings page are still marked
  unverified until the operator reruns smoke, permission, and relevant trading
  tests after restart.
- If `git stash pop` fails after a merge (conflict between stashed runtime files
  and merged code files), the stash is dropped automatically. Check
  `stash_pop_ok` in the audit log if anything looks wrong post-update.
