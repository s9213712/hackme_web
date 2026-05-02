# Update Summary

Release ID: `2026.05.02-043`

## Highlights

- BTC_trade signal integration is now disabled by default and only appears after
  `root` enables it in trading settings.
- Root can trigger automatic BTC_trade clone/update/build from the configured
  GitHub repo and branch; setup installs dependencies, downloads data, trains
  the 4H model, initializes first-run runtime state, runs prediction, and
  generates the report.
- BTC_trade setup failures are non-fatal: the signal panel stays hidden and the
  trading page continues to work.
- Fresh deployment was verified in a clean runtime, including dependency
  install, database initialization, login, and zero-state PointsChain/trading
  tables.
- Production DB initialization now calls the current bootstrap schema helpers
  and initializes trading schema instead of using the obsolete bare `init_db()`
  call.

## Operator Notes

- Every future push to a shared branch must bump `APP_RELEASE_ID` and update
  this file before pushing.
- Server updates applied from the root settings page are still marked
  unverified until the operator reruns smoke, permission, and relevant trading
  tests after restart.
