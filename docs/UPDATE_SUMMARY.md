# Update Summary

Release ID: `2026.05.02-042`

## Highlights

- Trading Workflow templates now live under `workflows/`, with system templates
  tracked in `workflows/system/` and user custom templates written under
  `workflows/custom/<username>/`.
- Official Workflow templates now include structured explanations covering
  purpose, trigger conditions, actions, risk notes, suitable usage, and tuning
  guidance.
- The trading page loads Workflow templates from the backend, displays template
  explanations, and supports saving custom templates to the runtime workflow
  directory.
- Added `security/trading_workflow_template_validation.py` to validate official
  templates, confirm trigger behavior, download public K-line data, run backend
  backtests, and compare results against an independent replay.
- Backtest responses now expose the engine candle limit and automatic provider
  download limit so users can see the actual tested range.
- Trading API 404 errors now render as actionable frontend messages instead of
  raw `NOT FOUND` text.

## Operator Notes

- Every future push to a shared branch must bump `APP_RELEASE_ID` and update
  this file before pushing.
- Server updates applied from the root settings page are still marked
  unverified until the operator reruns smoke, permission, and relevant trading
  tests after restart.
