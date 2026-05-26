# Finance Hot Path A1 Micro

## Scope

Batch A1 only:

- Added low-risk finance hot-path indexes for PointsChain and trading read paths.
- Rewrote bridge event duplicate lookup to use the existing partial unique index with `chain_tx_hash<>''`.
- Fixed wallet identity balance reads so the single-wallet aggregate fast path is only used when it is semantically safe.
- Fixed transfer ledger recording to separate actual wallet balances from pending-adjusted spendable balances.

No Redis, DB split, materialized wallet balance table, price snapshot rewrite, or 5K/50K run was performed.

## Verification

Commands:

- `python3 -m py_compile services/points_chain/wallet_identity.py services/points_chain/schema.py services/points_chain/service.py routes/economy.py routes/public.py services/trading/engine.py`
- `node --check public/js/55-economy.js`
- `node --check public/js/56-trading.js`
- `pytest tests/points/test_points_chain.py tests/trading/mode_boundaries/test_trading_schema_snapshot.py tests/trading/core/test_trading_engine.py tests/points/test_wallet_identity.py tests/points/test_points_explorer.py tests/trading/core/test_trading_background_engine.py -q`

Result: pass.

## A1 Micro Stress

Environment:

- Isolated run root: `/tmp/hackme_finance_a1_micro2/hackme_web`
- URL: `https://127.0.0.1:55232`
- Gunicorn: 2 workers, 6 threads
- Stress artifact: `/tmp/hackme_finance_a1_micro2/a1_micro_stress.json`

Scenario:

- 10 accounts
- 120 wallet transfer requests
- 800 service-layer pc0 transfers
- 80 trading limit buy requests
- 24 hot-to-cold external transfers
- duplicate/replay/overspend probes

Result:

- Overall: pass
- Direct pc0 transfers: 800/800 completed, 0 errors
- PointsChain verify/replay: pass
- Financial invariants: pass
- Duplicate active wallet addresses: 0
- Duplicate request UUID groups: 0
- Confirmed stress prefix ledgers: 933
- Failed stress prefix ledgers: 0
- Database size: 11,526,144 bytes

Latency:

- Mixed API sample p95: 1326.275 ms
- Mixed API max: 1841.555 ms
- Direct pc0 transfer median: 16.282 ms
- Direct pc0 transfer p95: 243.061 ms
- Direct pc0 transfer p99: 1148.026 ms
- Direct pc0 transfer max: 3149.411 ms

## Notes

The first A1 micro attempt exposed a real accounting bug: pending-adjusted wallet identity state was being written back into durable aggregate wallet balances during pending transfer finalization. The fix keeps durable aggregate balances as actual balances and uses pending-adjusted state only for spendability checks.

Next approved batch should be Batch B: move market price reads out of `BEGIN IMMEDIATE` writer lock via durable price snapshots.
