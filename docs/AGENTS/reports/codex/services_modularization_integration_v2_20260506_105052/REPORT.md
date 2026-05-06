# Services Modularization Integration v2

## Step

Expand `services/trading/markets.py` into the full market registry and provider
mapping module.

## Exact Files Changed

- `services/trading/constants.py`
- `services/trading/markets.py`
- `services/trading_engine.py`

## Functional Boundary

This step keeps the whole market-registry feature together instead of splitting
it into validation shards:

- market alias normalization
- registry seed drift inspection
- provider capability metadata
- registry payload assembly
- registry validation
- provider mapping validation
- provider probe status generation
- registry CRUD
- provider mapping CRUD

`services/trading_engine.py` remains the public façade and now delegates the
registry/admin flow into `services/trading/markets.py`.

## Exact Methods Delegated

- `_market_registry_audit`
- `_market_registry_payload`
- `_market_provider_mapping_payload`
- `_validate_market_registry_payload`
- `_validate_market_provider_mapping_payload`
- `_probe_market_registry_on_conn`
- `_persist_market_registry_probe`
- `list_market_registry`
- `get_market_provider_registry`
- `create_market_registry`
- `update_market_registry`
- `disable_market_registry`
- `create_market_provider_mapping`
- `update_market_provider_mapping`
- `disable_market_provider_mapping`
- `probe_market_registry`

## File Size Check

- `services/trading/markets.py`: `749` LOC

This is intentionally a medium-large cohesive module. No new tiny wrapper files
were introduced.

## Behavior Change

No.

## Tests

### Targeted

- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_market_registry.py`
  - `8 passed`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py -k "market or provider or live_price or price_fusion" tests/test_trading_reference_prices.py tests/test_frontend_economy.py`
  - `50 passed, 150 deselected`

### Full

- `HACKME_RUNTIME_DIR=/tmp/hackme_web_fullpytest_20260506_markets PYTHONPATH=. python3 -m pytest -q tests/`
  - `1059 passed`

### Pre-push

- `python3 scripts/pre_push_checks.py --ci`
  - `10 PASS / 1 FAIL`
  - only blocker: `release id sync`

## Rollback Plan

- Revert commit `trading: expand market registry module`
- This restores market-registry/provider-mapping orchestration to
  `services/trading_engine.py`
- No schema rollback is required
