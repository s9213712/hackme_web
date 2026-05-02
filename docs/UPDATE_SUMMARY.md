# Update Summary

Release ID: `2026.05.02-041`

## Highlights

- Root GitHub updates now create a `pre_update` server snapshot before applying
  the selected remote branch.
- Root GitHub updates now create and verify a `pre_server_update` PointsChain
  ledger backup before merge.
- If either the snapshot or PointsChain backup fails, the update is aborted
  before touching the checked-out source.
- Successful updates now automatically schedule a server restart.
- The frontend update center now reports the snapshot id, PointsChain backup id,
  and restart mode after applying an update.
- Workflow bot conditions can now evaluate live/backtest unrealized PnL for
  stop-loss and take-profit percentage rules.

## Operator Notes

- Every future push to a shared branch must bump `APP_RELEASE_ID` and update
  this file before pushing.
- Server updates applied from the root settings page are still marked
  unverified until the operator reruns smoke, permission, and relevant trading
  tests after restart.
