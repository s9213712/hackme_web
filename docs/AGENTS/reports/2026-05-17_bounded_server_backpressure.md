# 2026-05-17 Bounded Server And Backpressure Hardening

## Scope

Implemented and smoke-tested the first hardening pass after the 10000 logical
user stress result:

- bounded gunicorn runner support for `test_for_develop.sh`;
- app-level normal/heavy/root-priority request backpressure;
- health fast-lane endpoints;
- stress probe reporting that separates controlled `503 server_busy` from real
  transport/5xx failures.

This used isolated runtimes under `/tmp` and did not use the developer's real
runtime DB.

## Changes

- Added `services/server/backpressure.py`.
  - `HTML_LEARNING_BACKPRESSURE_ENABLED`, default on.
  - `HTML_LEARNING_BACKPRESSURE_NORMAL_LIMIT` / `HEAVY_LIMIT` /
    `ROOT_LIMIT` now accept `auto`; root settings can override the dynamic
    result.
  - auto mode derives per-worker normal/heavy/root-priority/fast-lane reserve from worker
    thread capacity, CPU count, and total RAM. The default profile is moderately
    aggressive: 8 threads -> `5/1/1/1`, 12 threads -> `8/1/2/1`, 16 threads ->
    `11/2/2/1` for normal/heavy/root/reserved.
  - root can switch `server_backpressure_mode` between `auto`, `manual`, and
    `off`, then set normal/heavy/root/reserved/retry-after values from the
    system settings UI or `/api/root/backpressure`.
  - verified root/admin API requests can use a dedicated bounded root
    management lane during traffic peaks. This keeps root operations from
    competing with normal user requests while still preventing unbounded root
    request pileups.
  - returns `503` with `error=server_busy`, `Retry-After`, and
    `X-Hackme-Backpressure`.
  - user-facing 503 payload now says the server is in a traffic peak and asks
    the user to retry after the advertised delay, instead of returning only an
    engineering-oriented error string.
  - keeps a lightweight in-memory rolling traffic window per worker for root
    observation without writing high-frequency counters to SQLite.
- Added user-visible busy handling in the shared frontend `apiFetch`.
  - `503 server_busy` triggers a throttled toast: traffic peak, server is
    protecting service quality, retry later.
  - callers can still render their local inline error, but the failure is no
    longer silent when an endpoint forgets to display the payload.
- Added a root Backpressure traffic chart in the system settings UI.
  - shows recent total, accepted, root management, and traffic-peak rejected
    requests.
  - chart is process-local under gunicorn and labels the sampled worker PID.
  - `/api/root/backpressure` is in the fast lane so root can keep observing
    pressure while normal/heavy requests are being rejected.
- Added `/livez`, `/api/livez`, `/healthz`, `/api/healthz`, `/readyz`,
  `/api/readyz`.
  - live endpoints avoid DB.
  - ready endpoints run a minimal DB `SELECT 1` and report backpressure state.
- Made `/api/version` and health endpoints skip server-mode hydration and other
  heavier request guards.
- Added `--server-runner gunicorn` to `test_for_develop.sh`.
  - gthread worker class.
  - configurable workers, threads, timeout, keep-alive, backlog, max-requests.
  - workers/threads default to `auto` under gunicorn and are derived from CPU
    and RAM unless explicitly set.
  - generates local TLS files before launching gunicorn.
- Updated `scripts/testing/system_stress_probe.py`.
  - reports `server_busy_503` and `hard_failures_excluding_503`.
  - reports `total_ops_per_second`, `accepted_ops_per_second`,
    `server_busy_ops_per_second`, and `hard_failure_rate`.
  - keeps separate error sample buckets for controlled 503s, HTTP 5xx,
    timeouts, connection errors, and unexpected statuses.
  - supports `--allow-server-busy` for controlled-degradation tests.

## Verification

Static checks:

- `python3 -m py_compile server.py routes/public.py services/server/backpressure.py`
- `python3 -m py_compile scripts/testing/system_stress_probe.py`
- `bash -n test_for_develop.sh`
- `git diff --check`

Gunicorn launch:

```bash
./test_for_develop.sh --cli --in-place \
  --run-root /tmp/hackme_web_bp_20260517b \
  --port 58028 --host 127.0.0.1 \
  --feature-mode all --security off --server-mode test \
  --skip-install --root-password root --manager-password admin --test-password test \
  --port-conflict fallback --no-btc-trade-autostart \
  --server-runner gunicorn --gunicorn-workers 2 --gunicorn-threads 8 \
  --gunicorn-timeout 20 --gunicorn-backlog 64
```

Health checks:

- `GET /api/version`: 200
- `GET /livez`: 200
- `GET /readyz`: 200
- `/readyz` showed backpressure enabled with normal limit `6` and heavy limit
  `1`.

Stress smoke:

Artifacts:

- `/tmp/hackme_web_bp_20260517b/system_stress_gunicorn_smoke_allow_busy.json`
- `/tmp/hackme_web_bp_aggressive_20260517/system_stress_aggressive.json`

Profile:

- logical users / ops: `1000`
- active concurrency: `128`
- session mode: cloned authenticated session
- `--allow-server-busy` enabled

Result:

- degraded: `false`
- elapsed: `6.072 s`
- throughput: `164.69 ops/s`
- controlled `503 server_busy`: `798 / 1005`, `79.403%`
- hard failures excluding 503: `2 / 1005`, `0.199%`
- overall latency: p50 `465 ms`, p95 `1128 ms`, p99 `1564 ms`
- QoS `/api/version`: all 200, p95 `519 ms`
- monitored RSS max: `215.39 MB`
- main DB WAL peak: `0.884 MB`
- no runtime log signature for `database is locked`, traceback, worker timeout,
  memory error, too many open files, or thread creation failure.

Aggressive auto result:

- resolved gunicorn capacity: `2 workers x 12 threads`
- resolved per-worker backpressure: normal `9`, heavy `1`, fast-lane reserved
  `2`
- elapsed: `15.871 s`
- total throughput: `66.85 ops/s`
- accepted throughput: `35.54 ops/s`
- controlled `503 server_busy`: `497 / 1061`, `46.843%`
- accepted ops: `564 / 1061`
- hard failures excluding 503: `0`
- overall latency: p95 `777 ms`, p99 `951 ms`
- QoS `/api/version`: all 200, p95 `20.259 ms`, max `60.592 ms`
- monitored RSS max: `203.17 MB`
- CPU max during sample window: `50.17%`
- minimum available memory: `9110.48 MB`
- main DB WAL peak: `2.636 MB`
- no runtime log signature for `database is locked`, traceback, worker timeout,
  memory error, too many open files, or thread creation failure.

Post-run `/readyz`:

- normal active: `0`
- heavy active: `0`
- normal rejected: `239`
- heavy rejected: `53`

## Findings

1. Fixed: unbounded thread/RSS blow-up is no longer the first behavior under
   this profile.

   The previous 10000 logical run reached more than 3000 threads and over 3 GB
   RSS. The bounded gunicorn smoke kept the web process set around the configured
   master plus two workers, with total monitored RSS around 215 MB.

2. Fixed: health fast lane stayed reachable under load.

   `/api/version` returned 200 for all QoS samples. The worst QoS p95 was still
   above the long-term target, but it no longer timed out or reset.

3. Expected: 503 ratio is still present, but the aggressive auto profile
   improved it without losing health QoS.

   Normal limit `6` and heavy limit `1` are deliberately small. This confirms
   the server now rejects predictably instead of accepting work until collapse,
   but it is too strict for user experience. The useful accepted throughput is
   closer to `205 / 6.072s ~= 33.8 ops/s`; the larger headline throughput
   included fast controlled 503 responses.

   Before the root priority lane, auto-resolved `2 workers x 12 threads` made
   the per-worker profile normal `9`, heavy `1`, reserved `2`. Controlled 503s dropped from about
   `79%` to about `47%`, hard failures dropped to zero, and `/api/version` p95
   improved to about `20 ms`.

   Do not tune `normal_limit` above per-worker thread count. A safer rule is:
   `normal_limit + heavy_limit + root_limit <= gunicorn_threads - fast_lane_reserved`.

4. Added: root gets highest operational QoS during traffic peaks.

   Root/admin API paths are not blindly fast-laned. The request path must be a
   root/admin API path and the session cookie must verify as `root`. Verified
   root traffic then uses the `root` gate; unauthenticated or non-root requests
   still use normal/heavy gates. `/api/root/backpressure` remains fast lane so
   root can observe pressure even when the root gate is saturated.

5. Gunicorn counters are process-local.

   Under multiple gunicorn workers, `/readyz` reports the process that handled
   that request. Stress probe totals are the source of truth for run-level
   rejected counts. `/readyz` and the root traffic chart include `pid` and
   `process_local` to make this explicit.

6. Residual: two non-503 hard failures remained in the 1000-op smoke.

   Rate was below the degraded threshold, but it is not yet zero. The next pass
   should inspect the new error buckets instead of relying on the first 100
   errors, because controlled 503s can dominate a flat sample list.

7. Known limitation: gunicorn import path does not start in-process background
   workers from `server.py __main__`.

   For production-like deployment this is actually the right direction: trading,
   HLS, BT/direct-link, HuggingFace generation, and maintenance jobs should be
   started as explicit worker processes, not hidden inside the web request
   server. The next implementation step should add first-class worker entrypoints
   rather than trying to recreate all daemon threads inside gunicorn workers.

## Next Steps

- Tune backpressure limits against the same stress profile using the thread
  capacity rule above.
- Suggested matrix:
  - 2 workers × 8 threads, normal 5, heavy 1, root 1, reserved 1: current
    bounded baseline.
  - 2 workers × 8 threads, normal 4, heavy 1, root 1, reserved 2: health p95 target.
  - 2 workers × 12 threads, normal 7, heavy 1, root 1, reserved 3: conservative health
    p95 comparison.
  - 2 workers × 12 threads, normal 8, heavy 1, root 2, reserved 1: default aggressive
    auto profile.
  - 2 workers × 16 threads, normal 11, heavy 2, root 2, reserved 1: default aggressive
    higher-throughput profile.
- Keep health p95 under 1 second during overload, then target under 200 ms.
- Add a dedicated worker entrypoint for background jobs.
- Move HLS, BT/direct-link, HuggingFace generation, and trading run-once paths
  further into 202/job queue semantics.
- Extend the stress probe to preserve representative hard-failure samples even
  when controlled 503s dominate.
