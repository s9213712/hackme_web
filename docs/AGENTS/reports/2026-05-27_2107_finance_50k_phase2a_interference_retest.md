# 2026-05-27 21:07 Finance 50K Phase 2a Interference Retest

## Summary

- Result: FAIL overall, but the original `180s` root/control timeout class is fixed at the request boundary.
- Finance artifact: `/tmp/hackme_finance_50k_split_20260527_0230/artifacts/finance_50k_phase2a_interference.json`
- Interference artifact: `/tmp/hackme_finance_50k_split_20260527_0230/artifacts/interference_phase2a/system_stress_overlap.json`
- Runtime: `/tmp/hackme_finance_50k_split_20260527_0230/hackme_web/runtime`
- Server: `2026.05.27-007`, gunicorn on `127.0.0.1:54271`, 2 workers x 6 threads.
- DB: reused the existing split DB from prior 50K runs; no rebuild.
- Scope: `6000` HTTP wallet transfers, `40000` direct service-layer pc0 transfers, `4000` trading limit-order attempts, plus 5K broad non-trading interference.

The important change from the previous interference run is that root/admin heavy endpoints no longer block the client for `180s`. `seal`, `verify`, `points report`, and `trading refresh` moved to fast async starts. The remaining failures moved to queue/snapshot completion and edge-case finality semantics.

## Finance Result Details

| Metric | Value |
| --- | ---: |
| `ok` | `false` |
| Elapsed | `3997.654s` |
| HTTP wallet transfers | `6000` status `200` |
| Direct transfers | `40000/40000`, errors `0`, status `200` |
| Trading limit orders | `3999` status `200`, `1` status `400` |
| Prefix confirmed / pending / failed | `46049 / 2 / 0` |
| Duplicate request UUID groups | `0` |
| Duplicate active wallet address groups | `0` |
| Main latency p50 / p95 / p99 | `343.472ms / 1164.166ms / 1557.232ms` |
| Max client latency | `2979.680ms` |
| Direct latency median / p95 / p99 / max | `145.430ms / 285.281ms / 380.204ms / 993.662ms` |
| Transport retry count | `10` |
| Monitored RSS max | `6646.74MB` |

The failing finding was:

- `forced-proved pending transfers remained pending after root list and explorer finalization`
- Remaining request UUIDs:
  - `dstress-20260527115546-overspend-00`
  - `dstress-20260527115546-overspend-01`

This means the happy-path finance data-plane held, but the adversarial overspend/finality probe is still not clean.

## Management Plane Result

Root/control endpoints returned quickly instead of timing out:

| Endpoint/op | Status | Elapsed |
| --- | ---: | ---: |
| `root_chain_seal` | `202` | `177.992ms` |
| `root_chain_verify` | `202` | `427.919ms` |
| `root_points_report` | `202` | access-log same-second completion |
| `root_trading_refresh` | `202` | `245.637ms` |
| `root_trading_pools` | `200` | `182.466ms` |

Snapshot reads were fast but had no fresh snapshots yet:

| Snapshot | Status | Elapsed |
| --- | ---: | ---: |
| `points_chain_seal` | `404` | `133.741ms` |
| `points_chain_verify` | `404` | `133.518ms` |
| `points_root_report` | `404` | `129.230ms` |
| `trading_sitewide_refresh` | `404` | `146.691ms` |

Immediately after the run, the created management jobs were still `running` at `5%`:

- `points_chain_seal`
- `points_chain_verify`
- `points_root_report`
- `trading_sitewide_refresh`

So Phase 2a fixed synchronous request blocking, but the async worker/snapshot completion path still needs a real bounded execution model.

## DB Sizes

Final files in the split runtime:

| DB file | Size |
| --- | ---: |
| `finance.db` | `1.8G` |
| `finance.db-wal` | `54M` |
| `database.db` | `12M` |
| `database.db-wal` | `4.0M` |
| `audit.db` | `18M` |
| `auth.db` | `624K` |
| `control.db` | `96K` |

The split remains effective: the main DB stayed near `12MB` while finance growth remained in `finance.db`.

## Interference Result

The 5K broad non-trading interference completed degraded:

| Metric | Value |
| --- | ---: |
| `ok` | `false` |
| `degraded` | `true` |
| Elapsed | `2161.790s` |
| Throughput | `3.12 ops/s` |
| Accepted throughput | `2.91 ops/s` |
| Hard failure rate | `0.065788` |
| Transport/5xx failures | `453 / 6749` |
| Server-busy 503 | `9` |
| Overall p50 / p95 / p99 / max | `258.386ms / 20016.804ms / 20026.129ms / 39947.867ms` |

Worst affected operations:

| Operation | Status mix | p95 | Max |
| --- | --- | ---: | ---: |
| `me` | `435x200`, `57x0`, `8x503` | `20035.217ms` | `39947.867ms` |
| `trading_dashboard` | `209x200`, `39x0` | `20022.072ms` | `37160.701ms` |
| `trading_markets` | `219x200`, `34x0` | `20021.828ms` | `33193.287ms` |
| `hf_quote` | `21x200`, `89x0` | `20119.324ms` | `36325.367ms` |
| `jobs` | `260x200`, `15x0`, `1x503` | `20005.352ms` | `20023.782ms` |

This confirms the bottleneck has moved from finance write corruption/timeouts to worker/thread/DB contention across ordinary user-facing endpoints during broad interference.

## Comparison

| Run | Profile | Result | Finance DB | Main DB | Data path | Root/control result |
| --- | --- | --- | ---: | ---: | --- | --- |
| `1111` split core | no broad interference | PASS | `464MB` | `2.3MB` | 40K direct `0` errors, 4K trading OK | one root report `60s` client timeout |
| `1316` split + interference | existing DB, broad interference | FAIL | `928MB` | `3.5MB` | 40K direct `0` errors, 4K trading OK | accelerate/list/seal/verify/report exceeded `180s` |
| `1605` opt pass1 + interference | current code, existing DB | FAIL | `1.4GB` | `12MB` | 40K direct `0` errors, 4K trading OK | seal/verify/report/trading admin exceeded `180s` |
| `2107` Phase 2a + interference | async/snapshot request boundary, existing DB | FAIL | `1.8GB` | `12MB` | 40K direct `0` errors, 6K HTTP OK, 3999/4000 trading OK | heavy starts `202` under `0.5s`; jobs/snapshots not completed |

## Diagnosis

Phase 2a achieved the intended first cut:

- Heavy root/control endpoints no longer hold the HTTP request for minutes.
- Compact transfer submit response worked; access-log response size was about `355` bytes instead of the previous large receipt payload.
- `/api/points/transactions/submit` was not emitted as a `management_plane_slow` endpoint in this run.
- Split DB remains effective even after finance reaches `1.8GB`.

The new bottlenecks are:

- Async management jobs are only decoupled at the request boundary; execution remains effectively unbounded and had no fresh snapshots by collection time.
- Broad non-trading interference can still starve ordinary user-facing routes (`/api/me`, trading dashboard/markets, jobs).
- `GET/POST /api/admin/users` bootstrap was heavily delayed under interference before finance data-plane work could start.
- Two accepted overspend probes remained pending after root list and explorer finalization.
- One trading limit-order attempt returned `400`; it did not create a harness finding, but it should be reviewed before calling trading a clean 4K pass.

## Next Optimization Order

1. Add a real management worker loop with bounded concurrency and job lease semantics.
   - One active `finance_db` heavy job at a time.
   - Explicit timeout/cancel/fail states instead of jobs sitting at `running 5%`.
   - Snapshot write on success and clear error snapshot on failure.

2. Isolate planes at the process or queue level.
   - Keep finance write/data-plane workers separate from root/admin/analytics workers.
   - Reserve threads for data-plane and `/api/version`/health/qos.
   - Put heavy dashboard/trading analytics behind snapshot reads.

3. Fix overspend/finality semantics.
   - Accepted overspend probes should either deterministically fail, or be finalized into a terminal failed state.
   - Release gate should distinguish expected rejected overspend from true pending leakage.

4. Bound admin/user bootstrap APIs.
   - `/api/admin/users?q=...&page_size=100` should stay sub-second under broad interference.
   - Add indexed exact username lookup for stress/bootstrap paths.
   - Avoid root user-list hydration during high-volume test setup.

5. Finish snapshot coverage.
   - Seal/verify/report/trading refresh snapshots need fresh successful results, not only fast `404`.
   - Add job-status polling to the 50K harness and require eventual success for management jobs separately from data-plane pass/fail.

6. Re-test sequence.
   - First: small targeted replay for overspend/finality pending leak.
   - Second: management job worker smoke on the existing `1.8GB` finance DB.
   - Third: 50K with controlled interference after worker isolation.
   - Fourth: broad system interference as a separate control-plane resilience profile.
