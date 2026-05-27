# 2026-05-27 16:05 Finance 50K Opt Pass 1 Interference Retest

## Summary

- Result: FAIL overall, but the finance data path held.
- Artifact: `/tmp/hackme_finance_50k_split_20260527_0230/artifacts/finance_50k_interference_opt_pass1.json`
- Runtime: `/tmp/hackme_finance_50k_split_20260527_0230/hackme_web/runtime`
- Server: current working tree after management-plane optimization pass 1, gunicorn on `127.0.0.1:54251`, 2 workers x 6 threads.
- DB: reused the existing split DB from the earlier 50K runs.
- Scope: `6000` HTTP wallet transfers, `40000` direct service-layer pc0 transfers, `4000` trading limit orders.

The important result is that transfer/trading correctness stayed intact under the larger DB and overlapping non-trading interference. The failures are concentrated in synchronous root/control/analytics endpoints.

## Result Details

| Metric | Value |
| --- | ---: |
| `ok` | `false` |
| Elapsed | `5494.602s` |
| HTTP wallet transfers | `6000` status `200` |
| Direct transfers | `40000/40000`, errors `0`, status `200` |
| Trading orders | `4000` status `200` |
| Prefix confirmed / pending / failed | `46051 / 0 / 0` |
| Duplicate request UUID groups | `0` |
| Duplicate active wallet address groups | `0` |
| Main latency p50 / p95 / p99 | `341.701ms / 1388.901ms / 9318.922ms` |
| Max client latency | `180109.913ms` |
| Monitored RSS max | `5198.81MB` |

The five client timeouts were:

- `root_chain_seal`: `180104.189ms`
- `root_chain_verify`: `180107.938ms`
- `root_points_report`: `180011.845ms`
- `root_trading_refresh`: `180107.959ms`
- `root_trading_pools`: `180109.913ms`

## DB Sizes

Final files in the split runtime:

| DB file | Size |
| --- | ---: |
| `finance.db` | `1.4G` |
| `finance.db-wal` | `56M` |
| `database.db` | `12M` |
| `database.db-wal` | `4.0M` |
| `audit.db` | `14M` |
| `auth.db` | `484K` |
| `control.db` | `96K` |

The split still works: the main DB remained small while finance growth stayed in `finance.db`.

## Interference Coverage

Completed non-trading interference artifact:

- `/tmp/hackme_finance_50k_split_20260527_0230/artifacts/interference_opt_pass1/system_stress_overlap.json`
- Result: `ok=false`, `degraded=true`
- Elapsed: `1169.251s`
- Throughput: `5.18 ops/s`
- Hard failure rate: `0.008594`
- Overall p95 / p99 / max: `9111.776ms / 18287.707ms / 22805.571ms`

Additional interference attempts were intentionally stopped after they proved they were suppressing finance progress rather than usefully covering the write path:

- `system_stress_overlap2`: stopped during cold wallet initialization.
- `system_stress_overlap3_finance_main`: stopped after grants stalled behind management reads.
- `system_stress_overlap4_transfer`: stopped after several minutes of API transfer overlap; transfer requests still advanced and remained confirmed.

Member/HLS rerun artifacts exist, but they were not clean passes in this retest:

- `member_probe_overlap_rerun.json`: produced high findings under load.
- `video_hls_quality_overlap_rerun.json`: failed setup/measurement due the rerun credential/phase shape, so it is useful only as extra background load evidence.

## Management Plane Evidence

Slow logs from this pass:

- `GET /api/points/transactions`: `29645.214ms`, response `336107` bytes, RSS `2421.52MB -> 2426.24MB`.
- `GET /api/points/transactions`: `12436.833ms`, response `329720` bytes, RSS `2326.12MB -> 2787.52MB`.
- `POST /api/root/points/chain/seal`: `431093.351ms`, response `308` bytes, RSS `193.27MB -> 710.01MB`; client timed out at `180s`.
- `GET /api/root/points/chain/verify`: `466791.387ms`, response `10750` bytes, RSS `2802.4MB -> 2607.27MB`; client timed out at `180s`.
- `GET /api/points/explorer/fee-estimate`: `1873.329ms` after seal, with `unsealed_ledger_count=286872`.

One instrumentation issue was exposed: `/api/points/transactions/submit` is currently included by the broad management-plane prefix and generated many slow logs. It is a data-plane write endpoint and should be classified separately.

## Comparison

| Run | Profile | Result | Finance DB | Main DB | Data path | Root/control result |
| --- | --- | --- | ---: | ---: | --- | --- |
| `1111` split core | no broad interference | PASS | `464MB` | `2.3MB` | 40K direct `0` errors, 4K trading OK | one root report `60s` client timeout |
| `1316` split + interference | existing DB, broad interference | FAIL overall | `928MB` | `3.5MB` | 40K direct `0` errors, 4K trading OK | accelerate/list/seal/verify/report exceeded `180s` |
| `1605` opt pass1 + interference | current code, existing DB | FAIL overall | `1.4GB` | `12MB` | 40K direct `0` errors, 4K trading OK | seal/verify/report/trading admin exceeded `180s` |

Optimization pass 1 did help the explorer fee-estimate path by replacing full-ledger classification with bounded SQL counts. It did not solve full root/control jobs, and the larger `1.4GB` finance DB makes that distinction clearer.

## Current Diagnosis

The system has moved into a second-stage bottleneck:

- Data-plane writes are stable enough for the tested 50K shape.
- HTTP wallet transfer is slower than direct service-layer writes and has a large response payload around `12.8KB` per submit.
- Wallet summary reads became visibly slow after direct transfers; the stress harness spent minutes doing sequential `GET /api/points/wallet` calls.
- Root transaction list still allocates heavily and can jump RSS by hundreds of MB.
- Seal and verify are synchronous long-running control-plane jobs and exceeded practical request budgets.
- Root report and trading sitewide admin endpoints also need job/snapshot treatment.

## Next Optimization Order

1. Split endpoint classification and observability.
   - Exclude `/api/points/transactions/submit` from management-plane slow logs.
   - Track data-plane write timing separately from root/control/analytics timing.
   - Add `sql_ms`, `python_ms`, `json_ms`, `response_size`, and RSS deltas for wallet, transaction list, seal, verify, and report.

2. Make root/control operations async.
   - `POST /api/root/points/chain/seal` should return `202 + job_id`.
   - `GET /api/root/points/chain/verify` should become `POST start-job` plus `GET job-status`.
   - Add `latest-successful-seal` and `latest-successful-verify` snapshot endpoints.

3. Add root snapshot tables.
   - Points report snapshot.
   - Wallet summary snapshot.
   - Chain verify summary snapshot.
   - Explorer recent transaction snapshot.
   - Pending/finality queue snapshot with bounded sweep.

4. Bound transaction list and wallet endpoints.
   - Transaction list must not perform unbounded finalization or global summary hydration.
   - Wallet reads should avoid replaying or scanning ledger rows; use maintained balances/snapshots plus small recent activity queries.
   - Default list payloads should be lean; detailed finality/report data should be opt-in.

5. Reduce data-plane response cost.
   - `/api/points/transactions/submit` returns about `12.8KB` per successful transfer. Add a compact response mode for high-volume clients/harnesses.
   - Keep detailed receipt retrieval behind a separate endpoint keyed by transaction hash/request UUID.

6. Re-test sequence.
   - First: endpoint microbenchmarks on the existing `1.4GB` DB.
   - Second: core 50K on a fresh split DB.
   - Third: split + controlled interference with one completed system stress and one bounded transfer-overlap stress.
   - Fourth: external bridge profile separately.
