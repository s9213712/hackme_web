# 2026-05-24 15:55 :5000 Backpressure Live QA

## Findings

- **Fixed - auto heavy backpressure was too strict for normal full-load member activity.**
  - Evidence before fix: `/tmp/hackme_5000_live_full_flow_latest.json` had 9 controlled `503 server_busy` responses under only 4 full-flow accounts, while worker CPU peaked at 18.8% and p95 latency was 700 ms.
  - Intermediate evidence: `/tmp/hackme_5000_live_full_flow_after_backpressure.json` improved to 5 server failures; `/tmp/hackme_5000_live_full_flow_after_backpressure_v2.json` improved to 1 server failure.
  - Final evidence: `/tmp/hackme_5000_live_full_flow_after_backpressure_v3.json` passed with 319 samples, 0 hard failures, 0 server failures, p95 987 ms, p99 1710 ms, max 3355 ms, and worker CPU peak 117.6%.
  - Runtime evidence: `/api/root/backpressure` on `:5000` reports `thread_capacity=6`, `heavy.limit=4`, `root.limit=1`, `normal.limit=6`.

## Coverage

- Backend/API 4-account full flow covered normal, malicious, and heavy member actions, including PointsChain wallet/transfer/governance/disputes, appeals, trading spot/limit/margin, DCA/workflow/grid bots, bot scans, drive upload/preview/share/download, resumable upload, albums, chat, community, games, and root background chain/trading probes.
- Follow-up capacity ladder on the same `4 workers x 6 threads` runtime:
  - 6 full-load accounts: `/tmp/hackme_5000_live_full_flow_6_accounts.json`, 467 samples, 0 hard/server failures, p95 1559 ms, p99 2568 ms, max 5641 ms, CPU peak 62.6%.
  - 8 full-load accounts: `/tmp/hackme_5000_live_full_flow_8_accounts.json`, 615 samples, 0 hard/server failures, p95 1402 ms, p99 3939 ms, max 7939 ms, CPU peak 81.6%.
  - 10 full-load accounts: `/tmp/hackme_5000_live_full_flow_10_accounts.json`, 763 samples, 5 controlled `503 server_busy` heavy-gate responses, p95 3022 ms, p99 7200 ms, max 11439 ms, CPU peak 100.0%.
  - Current interpretation: 8 simultaneous full-load probe accounts are still within the tested safe envelope. 10 simultaneous full-load probe accounts are the observed high-pressure UX/controlled-backpressure boundary for this runtime, not the maximum number of ordinary online users.
- Frontend smoke artifact: `/tmp/hackme_5000_frontend_job_backpressure_smoke.json`.
  - Root login UI loaded the app shell.
  - Job Center rendered trading background jobs and resumable upload jobs.
  - Frontend session could read root backpressure status with `heavy=4` and `root=1`.
- Background jobs after load:
  - `/api/admin/jobs?limit=20` showed trading background jobs running and updating.
  - `/api/root/trading/background/status` showed enabled jobs with recent success and no failure count.
- Server health after reload and load: `GET https://127.0.0.1:5000/api/healthz` returned `ok=true`.
- Log tail after the final run showed no traceback; expected 400/403/404/409 responses came from malicious/negative test cases.

## Verification

- `python3 -m py_compile services/server/backpressure.py tests/security/gates/test_flask_hardening.py`
- `pytest -q tests/security/gates/test_flask_hardening.py -q` -> 9 passed
- `pytest -q tests/security/gates/test_security_events.py::test_capacity_probe_unlimited_disables_security_rate_limits tests/scripts/deploy/test_predeploy_capacity_probe.py tests/scripts/deploy/test_deploy_script.py -q` -> 11 passed

## Notes

- The left sidebar regrouping remains intentionally unmodified because the user requested confirmation before implementation.
- The running resumable upload jobs in Job Center are from active/incomplete probe sessions, not server crashes. They remain visible in the task list as expected.
