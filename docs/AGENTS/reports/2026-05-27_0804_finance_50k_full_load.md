# Finance 50K Full-Load Exploratory Stress Report

Date: 2026-05-27 08:04 Asia/Taipei

## Verdict

This run is **not** a passing 50K full-load gate.

It was useful as an exploratory full-load run because it exposed several blocking issues before an official 50K gate should be trusted:

- non-finance service quality degraded under concurrent finance + media load;
- the finance stress harness had a stale pending-finalization path at 50K scale;
- large server-encrypted HLS processing can become orphaned/stuck;
- the HLS quality script can false-pass when playback is blocked and subtitles are absent;
- normal-member large uploads are rejected only after the full body has already been uploaded.

## Environment

- Repo: `/home/s92137/hackme_web`
- Branch: `04.BLOCKCHAIN_RC1`
- Server URL: `https://127.0.0.1:55360`
- Run root: `/tmp/hackme_finance_50k_full_20260527_035824`
- Runtime: `/tmp/hackme_finance_50k_full_20260527_035824/hackme_web/runtime`
- Cloud storage root: `/mnt/d/tmp/hackme_50k_cloud_20260527_035824`
- Gunicorn: 2 workers x 6 threads, timeout 60, max_requests 0
- Big media source: `/mnt/d/[TSDM][Cosmic Princess Kaguya][2026][NF_Web-DL][HEVC-10bit 1080p AAC][CHS_JP].mkv`

## Size Snapshot

- Whole run root: `554M`
- Artifacts: `384K`
- Runtime database directory: `439M`
- Main DB: `436M`
- Audit DB: `2.8M`
- Runtime DB WAL files: `0` at final sample
- Cloud storage root: `9.8G`
- HLS/media derivatives: `5.1G`

## Workloads Attempted

### Finance 50K Attempt

Started `scripts/testing/points_chain_destructive_stress.py` with:

- 48 accounts
- transfer operations: 6,000
- direct pc0 transfer operations: 40,000
- trading operations requested: 4,000
- concurrency: 8
- external bridge every 5 operations, capped at 1,200

Observed progress:

- 6K HTTP wallet/cold bridge stage completed.
- 40K direct pc0 stage completed with 61 direct errors reported by stdout.
- Database reached roughly:
  - `points_chain_transfer_requests`: 45,990
  - `points_ledger`: 91,629
  - `points_wallet_identity_balances`: 103
  - `trading_orders`: 0
  - `trading_fills`: 0
  - remaining pending requests after partial sweep: 200

The run did not produce a final JSON artifact because it hit a stale harness finalization path before the trading stage.

### Non-Finance Interference

Completed `scripts/testing/system_stress_probe.py`.

Artifact: `/tmp/hackme_finance_50k_full_20260527_035824/artifacts/system_full_load.json`

Key results:

- `ok=false`
- `degraded=true`
- elapsed: `1463.328s`
- throughput: `5.88 ops/s`
- total operations: `8600`
- hard failures excluding expected 503: `39`
- server_busy count: `0`
- overall latency:
  - p50: `1458.558ms`
  - p95: `3794.316ms`
  - p99: `6708.326ms`
  - max: `23170.827ms`
- degraded reasons:
  - `overall_p95_gt_1500ms`
  - `overall_p99_gt_5000ms`
  - `qos_version_p95_gt_1000ms`

High-latency labels:

- `qos_version`: p95 `2289.145ms`, p99 `5003.95ms`
- `trading_dashboard`: p95 `3910.731ms`, p99 `6708.326ms`
- `drive_upload`: p95 `5228.227ms`
- `video_playback`: p99 `12270.94ms`
- `hls_master`: p95 `4003.787ms`, p99 `7282.513ms`
- `hf_generate`: expected 503, p95 `3879.147ms`

Resource sample:

- RSS max: `546.46MB`
- main DB max: `81.219MB` during monitor sample
- WAL max: `16.062MB` during monitor sample

### Big Video / HLS Interference

Normal-account encrypted upload attempt:

- Artifact: `/tmp/hackme_finance_50k_full_20260527_035824/artifacts/video_hls_full_load.json`
- Both normal-account uploads were rejected after about 956s with `400 upload_rejected` due cloud-drive capacity limit.
- This still generated upload load, but it did not validate HLS.

Root server-encrypted HLS attempt:

- Artifact: `/tmp/hackme_finance_50k_full_20260527_035824/artifacts/video_hls_full_load_root.json`
- Upload accepted.
- Stored encrypted source size: about `5,053,460,995` bytes.
- HLS derivative directory reached `5.1G`.
- Original 1080p derivative contained 1,988 segments.
- Asset stayed `processing`.
- HLS job stayed `running` at about `69%` / `transcoding`.
- No ffmpeg process was present at the final process sample.
- No master manifest was available.
- Playback probe returned 403 (`video is private or blocked`).
- Subtitle count was 0 despite `--expect-subtitles`.

## Findings

### P0/P1: 50K Full-Load Gate Is Not Ready

This run cannot be accepted as a 50K pass. The financial workload did not reach the trading phase, direct transfer errors were observed, and the concurrent full-site QoS probe failed degradation gates.

The next official 50K gate should wait until the harness and HLS blockers are fixed.

### P1: Finance Stress Harness Used a Stale Finalization Primitive

The old finalizer called:

`GET /api/points/explorer/search?q=<request_uuid>&limit=1`

one pending request at a time. At 50K scale this was both too slow and stale: it returned 400 for request UUID searches and would have taken hours.

Patch applied:

- `scripts/testing/points_chain_destructive_stress.py`
- `finalize_prefix_pending_via_explorer()` now triggers batched root transaction-list sweeps through `/api/points/transactions?limit=2000` instead of per-request explorer search.

Verification:

- `python3 -m py_compile scripts/testing/points_chain_destructive_stress.py` passed.

### P1: Full-Load QoS Degraded Without Useful Backpressure

The system stress probe reported 39 transport-level hard failures and no `server_busy` count. That suggests users may see timeouts or dropped responses instead of controlled queue/backpressure messaging.

This needs a follow-up focused on:

- request capacity/backpressure behavior;
- graceful degradation response paths;
- frontend user-visible queue/progress states.

### P1: Large Server-Encrypted HLS Can Become Orphaned/Stuck

The root large-video test reached a stuck state:

- job still `running`;
- progress about `69%`;
- stage `transcoding`;
- no ffmpeg process;
- asset still `processing`;
- no master playlist;
- subtitles missing.

The HLS worker needs orphan detection and recovery:

- detect missing child process for a running transcode job;
- mark failed with a useful reason or retry safely;
- expose decode/transcode/subtitle extraction progress in UI;
- assert subtitle extraction before declaring ready.

### P1: HLS Quality Script Can False-Pass

`video_hls_quality_stress.py --expect-subtitles` did not fail even though:

- playback probe got 403;
- no master manifest was available;
- subtitle count was 0.

The script must treat blocked playback, missing manifest, and missing subtitles as failures when those expectations are requested.

### P1: Large Upload Quota Rejection Happens Too Late

Normal users uploaded a multi-GB body and only then received `400 upload_rejected` for capacity limit.

The upload flow should preflight quota and max-file eligibility before consuming the full request body where possible.

### P1: Job Center Shows Stale Running Upload Jobs

The test DB had resumable upload jobs still showing `running` at 0%. Completed/failed/orphaned background jobs need more aggressive cleanup or recovery states so the task list remains trustworthy.

### P1: Finance Direct Transfer Errors Need a Clean Re-Run Artifact

Stdout reported 61 direct pc0 transfer errors during the 40K direct stage. The first run was interrupted before a JSON report, so the exact error samples were not captured.

After the harness fix, rerun a smaller patched finance-only closure test first, then repeat the mixed full-load run.

### P1: Trading Was Not Validated In This 50K Run

The requested 4,000 trading operations did not execute because the first finance run stopped in stale finalization. Therefore this run does not validate:

- spot order correctness;
- CFD/margin correctness;
- lending/interest correctness;
- three bot classes under concurrent load;
- exchange fund PnL and fee correctness.

## Next Required Fixes Before Official 50K

1. Fix HLS orphan detection and `video_hls_quality_stress.py` assertions.
2. Add or improve upload quota preflight for large uploads.
3. Rerun patched finance-only test to capture direct error samples and trading closure.
4. Investigate full-load QoS hard failures and add controlled backpressure where appropriate.
5. Only then rerun official 50K full-load with non-finance interference.

## Artifacts

- `/tmp/hackme_finance_50k_full_20260527_035824/artifacts/system_full_load.json`
- `/tmp/hackme_finance_50k_full_20260527_035824/artifacts/video_hls_full_load.json`
- `/tmp/hackme_finance_50k_full_20260527_035824/artifacts/video_hls_full_load_root.json`
- `/tmp/hackme_finance_50k_full_20260527_035824/hackme_web/runtime/logs/gunicorn_access.log`
- `/tmp/hackme_finance_50k_full_20260527_035824/hackme_web/runtime/logs/gunicorn_error.log`
