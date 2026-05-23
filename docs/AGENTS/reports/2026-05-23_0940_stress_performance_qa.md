# 2026-05-23 09:40 Stress / Performance QA

## Result

No data-corruption, negative-balance, chain-verify, duplicate-wallet, duplicate-request, DB-lock-timeout, or browser-error failure was confirmed.

One capacity boundary was observed: creating/logging in 50 new stress accounts rapidly from the same localhost IP triggers the login frequency limiter after 30 accounts. The chain/trading parts still completed correctly, but that run is marked failed by the stress script because 20 accounts received HTTP 429. A 30-account rerun passed.

## Coverage

Target runtime:

- `https://127.0.0.1:54344`
- runtime: `/tmp/hackme_web_isolated_54344/hackme_web/runtime`
- server PID: `2220492`

### HTTP Light Endpoint Throughput

Artifact:

- `artifacts/perf/http_stress_54344_2000/stress_20260523T012905Z.json`

Result:

- 2,000 requests
- 50 concurrency
- paths: `/api/version`, `/api/site-config`, `/api/csrf-token`
- 2,000 HTTP 200
- 0 failed
- approx 115.27 req/s
- latency p50 415.90ms, p95 617.53ms, p99 747.40ms

Post-chain-load artifact:

- `artifacts/perf/http_stress_54344_5000_after_chain/stress_20260523T013759Z.json`

Result:

- 5,000 requests
- 100 concurrency
- 5,000 HTTP 200
- 0 failed
- approx 115.10 req/s
- latency p50 851.33ms, p95 1082.71ms, p99 1176.02ms

### Mixed System Stress

Artifact:

- `artifacts/perf/system_stress_54344_500.json`

Result:

- 528 ops
- 25 concurrency
- 20 session clones
- `ok=true`, `degraded=false`
- hard failures excluding 503: 0
- QoS `/api/version`: all 200, p95 47.435ms
- CPU avg 22.85%, max 48.49%
- monitored RSS max 164.84MB

Notes:

- Many 503 responses were feature-disabled or controlled `server_busy` responses because this runtime has several optional modules disabled.
- No transport failure or uncontrolled 5xx was observed.

### SQLite / Job Center DB Stress

Artifact:

- `artifacts/perf/db_stress_54344_30s.json`

Result:

- 30 seconds
- 24 threads
- 2 external worker processes
- `ok=true`
- error_count 0
- lock_error_count 0
- CPU avg 37.57%, max 69.02%
- monitored RSS max 177.20MB
- main DB WAL peak 28.667MB

Observed latency under intentional lock contention:

- main_write p50 1211.766ms, p95 1546.037ms
- online_activity_write p50 1242.252ms, p95 1576.083ms
- mixed_read p50 6.759ms, p95 14.558ms

### PointsChain / Exchange Heavy Stress

Artifact:

- `artifacts/perf/points_chain_destructive_stress_54344_heavy.json`

Result:

- Requested 50 accounts
- Active 30 accounts
- 20 account logins hit HTTP 429 rate limiting
- 300 wallet transfers completed
- 180 trading limit buys completed
- overspend rejected with 409
- margin exhaustion rejected with 400
- chain verify passed
- duplicate active wallet address groups: 0
- duplicate request UUID groups: 0
- prefix failed: 0
- prefix pending: 0

Classification:

- Capacity boundary / anti-abuse throttle, not a ledger correctness failure.

Passing rerun artifact:

- `artifacts/perf/points_chain_destructive_stress_54344_30acct.json`

Result:

- 30 accounts
- 300 wallet transfers
- 180 trading limit buys
- 20 concurrency
- `ok=true`
- findings: 0
- duplicate active wallet address groups: 0
- duplicate request UUID groups: 0
- prefix confirmed: 333
- prefix failed: 0
- prefix pending: 0
- latency p50 1150.648ms, p95 2187.187ms, p99 2780.182ms
- sealed block 11 with 348 ledger entries
- final chain verify: 2,225 ledger entries, 11 sealed blocks, 0 unsealed, 2,333 audit events, 200 wallets

Fee market behavior:

- Congestion stayed at `congested` after previous heavy load.
- Base fee stayed at 10 points.
- Suggested priority fee stayed at 100 points.
- Suggested total fee stayed at 110 points.

### Post-Stress Frontend

Artifact:

- `artifacts/perf/points_chain_post_stress_playwright_54344_after_perf.json`

Result:

- `ok=true`
- browser_errors: []
- root wallet API 200
- root transactions API 200
- root report API 200
- fee estimate API 200
- member wallet / transactions / notifications APIs 200
- root chain UI showed 2,225 ledger entries, 11 sealed blocks, 0 unsealed entries, and full chain verification normal.

## Final Health Check

After all stress runs:

- `/api/version`: 200
- root login: 200
- `/api/root/points/chain/verify`: 200
- verify ok: true
- counts: 2,225 ledger entries, 11 sealed blocks, 0 unsealed entries, 2,333 audit events, 200 wallets
- verify errors: []

## Runtime State

Existing runtimes were reused. No new runtime tree was created.

Servers left running:

- 54343 PID `2220299`
- 54344 PID `2220492`
