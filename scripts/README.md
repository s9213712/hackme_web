# Scripts Map

This directory is for operator entrypoints and local validation tooling.

It should not become a dumping ground for one-off experiments.

## Stable Root Entry Points

These paths are intentionally easy to remember and may stay at `scripts/`
root:

- `run_prod.sh`: production launcher and environment check
- `pre_push_checks.py`: canonical local validation entrypoint
- `root_recovery.py`: offline root recovery CLI

## Existing Subtree

- `prepush/`: implementation details for `pre_push_checks.py`

## Planned Grouping

New scripts should prefer one of these homes:

- `scripts/trading/`: trading probes, bridges, benchmarks, validators
- `scripts/comfyui/`: ComfyUI smoke/probe helpers
- `scripts/templates/`: reusable operator templates
- `scripts/prepush/`: pre-push internals only

## Current Top-Level Files That Should Eventually Move

- `btc_signal_bridge.py`
- `trading_backtest_20000_probe.py`
- `comfyui_feature_probe.py`
- `comfyui_run_in_linux.template.sh`

They are still valid today because existing docs and tests reference them, but
they should be treated as migration candidates, not permanent root clutter.

## Compatibility Rule

When moving a published script path:

- move the real implementation first
- keep a thin wrapper at the old path for one release
- update docs and tests in the same slice

Do not silently break operator commands that are already documented.
