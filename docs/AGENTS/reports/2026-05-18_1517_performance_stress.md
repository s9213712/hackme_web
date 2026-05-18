# 2026-05-18 Performance Stress Check

## Scope

This pass focused on server quality under pressure after the bounded server and backpressure work.

Covered:

- Isolated `test_for_develop.sh` runtime on `https://127.0.0.1:52180`.
- Gunicorn runner with 2 workers x 12 threads.
- 1000 logical online users DB stress with concurrent reads/writes.
- 3000 logical HTTP mixed stress with 192 concurrency across login, drive, upload, chat, community, games, trading, jobs, video, HLS, HuggingFace rejection, BT/direct-link rejection, and QoS probes.
- Runtime resource monitoring and SQLite state checks.

Not covered in this pass:

- Long real video HLS/transcode saturation using `/mnt/d/test.mp4`.
- Real ComfyUI/HuggingFace generation load.
- Browser visual QA.

## Environment

- Branch: `03.Points`
- Server mode: `test`
- Runtime root: `/tmp/hackme_web_stress_52180b/runtime`
- Runner command used `test_for_develop.sh --server-runner gunicorn --gunicorn-workers 2 --gunicorn-threads 12 --gunicorn-timeout 20 --gunicorn-backlog 96 --feature-mode all --server-mode test --security off --tmp-runtime --in-place`
- Accounts: `root/root`, `admin/admin`, `test/test`, `test2/test2`, `test3/test3`

## Result Summary

The server did not go down during the mixed HTTP stress run. `/api/version` and `/readyz` still responded after the test, and log scanning did not find traceback, worker timeout, or SQLite lock errors.

The overload behavior is now mostly controlled: the server returns explicit `503 server_busy` with the user-facing message `目前是流量高峰，伺服器正在保護服務品質。請稍候 2 秒後再試。` instead of silently hanging.

The main remaining problem is capacity and latency. Under 3000 logical users / 192 concurrency, about 79% of requests were intentionally rejected by backpressure. Accepted throughput was much lower than total throughput, and a few transport-level connection aborts still occurred.

## DB Stress Findings

Command:

```bash
python3 scripts/testing/db_stress_probe.py --runtime-root /tmp/hackme_db_stress_20260518_1515 --out /tmp/hackme_db_stress_20260518_1515/result.json --duration 20 --threads 64 --user-count 1200 --online-users 1000 --main-writers 6 --user-writers 12 --user-readers 12 --job-writers 10 --auth-writers 8 --session-writers 12 --audit-writers 6 --control-writers 2 --readers 8 --external-workers 4 --backend file --flush-interval 1.0 --event-flush-interval 3.0 --monitor-interval 1.0
```

Confirmed good:

- `ok: true`
- `lock_error_count: 0`
- `error_count: 0`
- Main/auth/audit/control databases stayed in WAL mode.
- CPU remained moderate: avg `31.78%`, max `35.16%`.
- Monitored RSS max: `289.12 MB`.

Confirmed issue:

- SQLite write contention is no longer surfacing as `database is locked`, but high-write latency is still severe under 64 threads / 1000 logical online users.
- Worst p95/max examples:
  - `main_write`: `16050.974ms / 16050.974ms`
  - `auth_write`: `15397.126ms / 15397.126ms`
  - `user_activity_write`: `16050.222ms / 16050.222ms`
  - `online_session_touch`: `12383.05ms / 13903.148ms`
  - `audit_write`: `7028.923ms / 8007.558ms`

Interpretation:

- The DB split/WAL work prevented hard lock failures.
- High-frequency write paths still need more buffering, coalescing, or lower write frequency. Session touch, user activity, audit, and auth-side writes are the main candidates.

## HTTP Stress Findings

Command:

```bash
python3 scripts/testing/system_stress_probe.py --base-url https://127.0.0.1:52180 --runtime-root /tmp/hackme_web_stress_52180b/runtime --server-pids 2415111,2415540,2415613 --out /tmp/hackme_web_stress_52180b/runtime/reports/system_stress_3000.json --logical-users 3000 --ops 3000 --concurrency 192 --session-pool 96 --timeout 20 --qos-interval 1 --resource-interval 1 --root-password root --test-password test --accounts test:test,test2:test2,test3:test3 --session-mode clone --allow-server-busy --max-drive-uploads 80 --max-resumable-starts 60 --max-hf-generates 10 --max-remote-rejects 80 --max-bt-rejects 80 --max-bad-logins 60 --max-bad-community 80 --max-bad-chat 80
```

Confirmed good:

- `ok: true`
- `degraded: false`
- Server stayed online after the run.
- Total HTTP stress elapsed: `20.217s`
- Total throughput: `149.14 ops/s`
- Accepted throughput: `30.62 ops/s`
- Server-busy throughput: `118.02 ops/s`
- RSS max: `208.23 MB`
- CPU avg/max: `30.13% / 41.18%`
- Runtime free disk remained stable.
- Main DB WAL peak stayed small: `2.102 MB`.
- `/readyz` after stress reported DB check ok in `2.019ms`.

Confirmed issue:

- `server_busy_503`: `2386 / 3015` (`79.14%`)
- Accepted operations excluding server-busy/hard-failure: `619`
- Hard failures excluding controlled 503: `10` (`0.33%`)
- Overall latency p95/p99/max: `1217.101ms / 1932.522ms / 3794.591ms`
- `/api/version` QoS had one transport failure in the run summary. Explicit periodic QoS samples were all HTTP 200, but p95 was still `793.84ms`.

Hard failure samples included transport-level connection aborts on:

- `chat_rooms`
- `drive_list`
- `drive_upload`
- `me`
- `resumable_start`
- `chat_bad_message`
- `version`

No traceback or worker-timeout signature was found in the scanned server logs.

## Slow Endpoint Buckets

Accepted and mixed-load endpoint p95 values that still deserve profiling:

- `trading_dashboard`: p95 `2308.511ms`, max `3794.591ms`
- `community_boards`: p95 `1933.18ms`
- `chess_leaderboard`: p95 `1613.289ms`
- `drive_list`: p95 `1473.636ms`
- `video_list`: p95 `1294.717ms`
- `notifications`: p95 `1284.796ms`
- `trading_markets`: p95 `1182.381ms`
- `jobs`: p95 `941.07ms`

Interpretation:

- Backpressure is preventing process blow-up, but root/user-visible dashboards and list endpoints still become slow under load.
- Next optimization should prefer snapshots, pagination, cache headers, and lower polling frequencies before raising concurrency limits.

## Operational Notes

- `/readyz` backpressure counters are process-local under gunicorn. A single `/readyz` response is not a whole-server aggregate.
- In this run, `/readyz` hit a worker that had zero local rejected counters after stress, while the stress probe recorded the real run-level `503` count.
- The meaningful run-level rejection source is the stress probe JSON, not one worker's `/readyz` counters.

## Follow-Up Recommendations

1. Keep current bounded serving/backpressure enabled. It prevented server-down behavior in this pass.
2. Reduce write frequency for session touch, user activity, auth activity, and audit bursts. Use coalescing/checkpoint writes for non-critical high-frequency state.
3. Profile and snapshot `trading_dashboard`, `community_boards`, `chess_leaderboard`, `drive_list`, `video_list`, and `notifications`.
4. Preserve fast lane QoS more aggressively. `/api/version` should target p95 under `200ms`; this pass was under 1s but not yet ideal.
5. Add aggregate backpressure counters through a DB/file/Redis-compatible collector if root needs whole-server charts.
6. Run the separate long-video HLS quality/transcode stress scenario for the upload/HLS failure class; it was intentionally not mixed into this pass.
