# 2026-05-16 DB Stress B and Performance Audit

Scope: isolated runtime DB stress after the Job Center progress-buffer and
hardened SQLite changes. This did not use the developer's real runtime DB.

Follow-up: the 1000 logical online user pass is documented separately in
`docs/AGENTS/reports/2026-05-16_db_stress_1000.md`.

## What changed before the stress run

- Main/auth/audit/control DB helpers now use hardened SQLite connections with
  WAL, busy timeout, same-process serialized writes by DB path, and short retry
  for transient lock errors.
- Job Center high-frequency `running` progress can be deferred into the
  progress backend and checkpointed to DB by interval. Terminal states still
  write DB immediately.
- Progress backend interface now supports `memory`, `file`, `redis`, and
  `auto`. Server default is `auto`, so Redis can be introduced later without
  making it a required dependency.
- Job Center schema ensure is cached per DB path/connection context so reads do
  not repeatedly run DDL/PRAGMA work.

## Stress Probe

New reusable probe:

```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/testing/db_stress_probe.py
```

It creates 100+ users in an isolated runtime and concurrently exercises:

- main DB business writes
- per-user activity writes and profile/leaderboard reads
- auth/session writes
- audit append writes
- control-plane writes
- Job Center progress/event writes
- Job Center list reads
- cross-process Job Center progress workers
- optional long write-lock holder for hostile contention

## High-Pressure Result

Command shape:

```bash
python3 scripts/testing/db_stress_probe.py \
  --duration 8 --threads 64 --user-count 180 \
  --main-writers 4 --user-writers 12 --user-readers 10 \
  --job-writers 8 --auth-writers 4 --session-writers 8 \
  --audit-writers 4 --control-writers 3 --readers 6 \
  --external-workers 4 --backend file \
  --flush-interval 0.5 --event-flush-interval 1.0
```

Result:

- `ok=true`
- `error_count=0`
- `lock_error_count=0`
- users created: `180`
- external workers: `4/4` succeeded

Notable p95 latency:

- `mixed_read`: 15.878 ms
- `user_profile_read`: 20.344 ms
- `control_write`: 68.826 ms
- `audit_write`: 88.269 ms
- `auth_write`: 223.100 ms
- `session_write`: 304.252 ms
- `job_progress`: 853.990 ms
- `main_write`: 878.456 ms
- `user_activity_write`: 940.315 ms

## Violent Contention Result

Command shape added `--lock-contention`, 6 external workers, 80 local threads,
shorter checkpoint interval, and intentional 80 ms `BEGIN IMMEDIATE` lock
holding.

Result:

- `ok=true`
- `error_count=0`
- `lock_error_count=0`
- external workers: `6/6` succeeded

Notable p95 latency:

- `mixed_read`: 15.212 ms
- `user_profile_read`: 19.115 ms
- `control_write`: 92.926 ms
- `audit_write`: 142.330 ms
- `auth_write`: 449.678 ms
- `session_write`: 446.539 ms
- `job_progress`: 1456.074 ms
- `main_write`: 2380.663 ms
- `user_activity_write`: 1410.481 ms

## Audit Findings

1. Lock-induced 500 risk is substantially reduced.
   The violent DB probe produced no `database is locked` errors. This validates
   WAL + busy timeout + serialized write retry as a stability improvement for
   the current single-node SQLite deployment.

2. The main DB remains the bottleneck under concurrent writes.
   When many domains write `database.db` at once, p95 write latency rises into
   hundreds of ms, and hostile lock holding pushes main writes into seconds.
   This is the SQLite single-writer limit, not a frontend issue.

3. Job Center progress buffering prevents event-table spam.
   In violent mode, external workers produced tens of thousands of progress
   updates, while DB `job_center_events` stayed small because progress events
   were coalesced.

4. Auth/audit/control DB split is working.
   These DBs did not throw lock errors while main DB was under pressure. They
   still show their own writer queues under extreme concurrency, which is
   expected for SQLite.

5. Read paths stayed usable.
   Mixed reads and per-user profile reads stayed in low tens of milliseconds
   p95 even during violent write pressure.

## Deployment Guidance

- Keep Job Center progress flush intervals conservative in production:
  `HACKME_JOB_PROGRESS_FLUSH_INTERVAL_SECONDS=1.5` and
  `HACKME_JOB_PROGRESS_EVENT_FLUSH_INTERVAL_SECONDS=5.0` are safer than very
  short intervals on a small server.
- Use `HACKME_JOB_PROGRESS_BACKEND=auto`; add Redis later by setting
  `HACKME_REDIS_URL` or `REDIS_URL`.
- Do not move financial truth, PointsChain, trading settlement, or final job
  state into Redis. Redis/file backend is for volatile latest progress only.
- The next real DB scaling step is not more SQLite retry. It is to reduce main
  DB write domains: trading/points/storage-social hot paths should be
  snapshot/buffered or moved behind dedicated worker queues before adding more
  traffic.
