# Server Modularization Integration v2

## Step

Extract `server.py` startup/bootstrap orchestration into a single
`services/server_startup.py` module.

## Files Changed

- `server.py`
- `services/server_startup.py`

## Boundary

This step keeps one cohesive startup boundary together:

- recurring background worker loops
- startup recovery/bootstrap flow
- TLS/bind bootstrap
- `__main__` server entry orchestration

It deliberately does **not** move runtime path assignments or source-text
guarded security defaults that tests currently assert directly from
`server.py`.

## Functions Moved

- `start_daily_snapshot_worker`
- `start_storage_maintenance_worker`
- `start_points_chain_block_worker`
- `start_trading_liquidation_worker`
- `start_trading_bot_worker`
- `__main__` startup body into `run_server_main(...)`

`server.py` keeps the public wrapper names and remains the stable entrypoint.

## Fragmentation Check

- `server.py`: `1739` LOC
- `services/server_startup.py`: `392` LOC

No tiny compatibility shard files were introduced.

## Behavior Change

No.

## Validation

- `python3 -m py_compile server.py services/server_startup.py`
- `git diff --check`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_server_split PYTHONPATH=. python3 -m pytest -q tests/test_security_defaults.py tests/test_feature_flags.py`
  - `17 passed`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_fullpytest_20260506_server_startup PYTHONPATH=. python3 -m pytest -q tests/`
  - `1059 passed`
- `python3 scripts/pre_push_checks.py --ci`
  - `10 PASS / 1 FAIL`
  - only blocker: `release id sync`

## Rollback Plan

Revert the single commit for this step. `server.py` wrapper functions isolate
the extraction cleanly.
