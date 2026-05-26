# 2026-05-26 21:08 :5000 Large HLS / Subtitle / Points Probe

## Scope

- Target: `https://127.0.0.1:5000`
- Runtime: `/tmp/hackme_web_dev_20260526_195929_1631630/hackme_web`
- Storage root: `/mnt/d/tmp`
- Source video: `/mnt/d/[TSDM][Cosmic Princess Kaguya][2026][NF_Web-DL][HEVC-10bit 1080p AAC][CHS_JP].mkv`
- Privacy mode: `server_encrypted`

## Findings

No confirmed P0/P1 regressions in this pass.

## Confirmed Behavior

- Large server-encrypted upload completed.
- HLS background job completed with `status=succeeded`, `progress_percent=100`, `stage=ready`.
- Generated HLS variants:
  - `original` 1080p, 1988 segments, 3.78GB
  - `q480` 480p, 818 segments, 1.65GB
  - `q720` 720p, 818 segments, 3.12GB
- Source MKV contains an embedded `ass` subtitle stream.
- HLS extraction generated `sub01_chi.vtt`.
- `/api/videos/1/playback` returned `streaming_ready=true`, three variants, and one subtitle track.
- `/api/videos/1/hls/subtitles/sub01_chi.vtt` returned HTTP 200 and valid `WEBVTT` content.
- During sampled segment bursts, `/api/version` stayed healthy:
  - original burst p95: 12.59ms
  - q480 burst p95: 13.74ms
  - q720 burst p95: 12.19ms
- `member_probe.py` completed 17 checks with no findings.
- PointsChain financial invariants on the live instance reported `ok=true`.
- Targeted strict E2EE regression coverage passed:
  - shared E2EE video requires password + fragment-key envelope.
  - simulated shared E2EE payload can decrypt original plaintext.
  - E2EE Streaming v2 bundle upload size guard rejects oversized inline bundles.
  - strict E2EE is excluded from server-side stream preparation/transcoding.
  - frontend video/E2EE UI guardrail static tests pass.

## Artifacts

- `/tmp/hackme_5000_mntd_large_server_encrypted_hls_root_20260526.json`
- `/tmp/hackme_5000_mntd_large_server_encrypted_hls_measure_subtitles_20260526.json`
- `/tmp/hackme_5000_member_probe_after_large_hls_20260526.json`

## Code Changes Made During This Pass

- `scripts/testing/video_hls_quality_stress.py`
  - streams multipart upload bodies instead of buffering large files in the probe process.
  - stops waiting immediately with `no_hls_jobs` when upload failed and no HLS job exists.
  - records `media_stream_subtitles` state.
  - adds `--expect-subtitles`.
  - verifies playback API subtitle tracks by fetching the VTT and checking for `WEBVTT`.
- `test_for_develop.sh`
  - adds `--max-content-mb` / `--upload-request-max-mb` / `--html-learning-max-content-mb`.
  - exports `HTML_LEARNING_MAX_CONTENT_MB` and `HACKME_DEV_MAX_CONTENT_MB` for large upload QA.

## Verification Commands

- `python3 -m py_compile scripts/testing/video_hls_quality_stress.py`
- `bash -n test_for_develop.sh`
- `python3 scripts/testing/video_hls_quality_stress.py --base-url https://127.0.0.1:5000 --video '/mnt/d/[TSDM][Cosmic Princess Kaguya][2026][NF_Web-DL][HEVC-10bit 1080p AAC][CHS_JP].mkv' --db /tmp/hackme_web_dev_20260526_195929_1631630/hackme_web/runtime/database/database.db --runtime-marker /tmp/hackme_web_dev_20260526_195929_1631630/hackme_web --out /tmp/hackme_5000_mntd_large_server_encrypted_hls_measure_subtitles_20260526.json --measure --expect-subtitles --measure-username root --measure-password root --segment-concurrency 2 --max-segments-per-variant 4`
- `python3 /home/s92137/.codex/skills/hackme-web-qa/scripts/member_probe.py --base-url https://127.0.0.1:5000 --root-password root --test-password test --out /tmp/hackme_5000_member_probe_after_large_hls_20260526.json`
- `python3 -m pytest tests/points/test_points_chain.py::test_financial_invariant_report_exposes_reserve_liability_and_bridge_state tests/points/test_points_chain.py::test_financial_invariant_report_flags_corrupt_bridge_settlement tests/points/test_points_chain.py::test_financial_invariant_flags_pc0_ledger_sealed_into_pc1_block -q`
- `python3 -m pytest tests/video/streaming/test_video_streaming.py::test_shared_e2ee_video_requires_password_fragment_and_exposes_browser_side_payload tests/video/streaming/test_video_streaming.py::test_shared_e2ee_video_simulation_can_decrypt_original_plaintext tests/video/streaming/test_video_streaming.py::test_e2ee_stream_v2_bundle_upload_has_inline_size_guard tests/video/streaming/test_video_streaming.py::test_prepare_stream_auto_policy_distinguishes_plain_server_encrypted_and_e2ee tests/video/streaming/test_video_streaming.py::test_strict_e2ee_prepare_stream_route_rejects_server_transcode_without_worker tests/frontend/video/test_frontend_videos.py -q`

## Remaining Follow-Up

- Run strict E2EE browser upload/share/playback coverage separately; the current evidence covers backend/API invariants and frontend static guardrails, not a real browser-side large-file E2EE transcode.
- Continue broader multi-account trading, governance, cloud-drive, and malicious behavior audit on the same QA instance.
