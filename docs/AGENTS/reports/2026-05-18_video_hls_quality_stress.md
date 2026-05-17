# 2026-05-18 Video HLS Quality Stress

## Scope

Targeted QA for long-video upload, server-side encryption, HLS background preparation, and HLS quality variants.

Environment:
- Branch: `03.Points`
- Server: direct gunicorn on `http://127.0.0.1:5017`
- Runtime: `/tmp/hackme_video_quality_direct_5017/runtime`
- Source video: `/mnt/d/test.mp4`
- Source media: 126 MB, 3840x2160 AV1 + AAC, about 149.65 seconds
- Upload mode: `server_encrypted`
- Accounts: `test`, `test2`, `test3`, `test4`
- HLS quality config: `1080,720,480`

Repo script retained for future re-runs:
- `scripts/testing/video_hls_quality_stress.py`

Evidence artifacts:
- `/tmp/hackme_video_quality_stress_result.json`
- `/tmp/hackme_hls_quality_measure_result.json`
- `/tmp/hackme_hls_quality_measure_seq.json`

## Findings

### Medium: 1080p transcode is larger than original AV1 and does not reduce bandwidth

Both completed videos produced the same HLS sizes:

| Variant | Codec | Resolution | Total bytes | Approx size |
| --- | --- | ---: | ---: | ---: |
| original | AV1 copy | 2160p | 131,526,607 | 125.4 MB |
| q1080 | H.264 | 1080p | 151,934,328 | 144.9 MB |
| q720 | H.264 | 720p | 91,936,744 | 87.7 MB |
| q480 | H.264 | 480p | 54,406,163 | 51.9 MB |

Impact: for this source, `1080p` increases storage and transfer relative to the original AV1. `720p` and `480p` reduce transfer, but `1080p` is not a useful load-reduction option unless encoding settings change.

Likely cause: the HLS transcode path uses `libx264 -crf 23` and records a target bitrate, but does not enforce that target as an actual bitrate cap.

### Medium: multi-quality HLS is safe for the main server but expensive for workers

Two successful server-encrypted 126 MB uploads completed in about 31.5s and 35.0s. Two concurrent uploads were intentionally rejected by heavy backpressure with a clear user-facing `server_busy` message.

The HLS preparation behavior was stable:
- HLS jobs appeared in Job Center.
- One worker held the HLS slot while the second waited at `waiting_worker_slot`.
- Only one ffmpeg transcode ran at a time.
- Both HLS jobs finished successfully.

Cost observed:
- Two 149.65s 4K AV1 uploads required about 41 minutes for all variants.
- ffmpeg commonly used about 28-39% CPU and 380-500 MB RSS.
- ffmpeg still showed about 21 threads even with `HACKME_MEDIA_FFMPEG_THREADS=1`.

Impact: the external worker design prevents main server collapse, but high-resolution AV1 multi-quality generation is slow on this host. The UI must keep showing background progress and completion notification.

### Low: high-concurrency HLS segment burst trips heavy backpressure

The high-concurrency burst phase intentionally fetched many HLS segments at once. Most extra segment requests returned controlled `503 server_busy` with the user-facing high-traffic message.

Impact: this is acceptable as overload protection, but it means HLS segment routes currently share the heavy gate. A real player or several simultaneous viewers may see stalls if it opens too many concurrent segment requests.

Recommendation: give HLS segment serving a separate streaming lane with a byte/connection limit instead of sharing the same heavy lane as upload/HLS/build tasks.

## Quality Measurements

Sequential playback-like measurement used 6 sampled segment/init requests per variant, one at a time.

Average across the two videos:

| Variant | Avg sampled bytes | Segment p95 avg | `/api/version` p95 during sample |
| --- | ---: | ---: | ---: |
| original 2160p | 12.18 MB | 906 ms | 6.5 ms |
| q1080 | 29.12 MB | 5461 ms | 160.1 ms |
| q720 | 17.43 MB | 788 ms | 20.2 ms |
| q480 | 10.56 MB | 231 ms | 4.8 ms |

Notes:
- The sampled segment bytes are not directly normalized by playback duration because original and transcoded variants have different segment boundaries.
- Full variant size is the better bandwidth comparison.
- Normal sequential playback succeeded for all variants: 6/6 segment samples per variant.
- High-concurrency burst produced controlled `503 server_busy`, not silent failure.

## Verification

Commands run:
- `python3 -m py_compile /tmp/hackme_video_quality_stress.py`
- `python3 -m py_compile /tmp/hackme_hls_quality_wait_measure.py`
- `python3 -m py_compile scripts/testing/video_hls_quality_stress.py`
- `git diff --check -- scripts/testing/video_hls_quality_stress.py`
- `python3 /tmp/hackme_video_quality_stress.py ...`
- `python3 /tmp/hackme_hls_quality_wait_measure.py`
- `python3 scripts/testing/video_hls_quality_stress.py --measure --segment-concurrency 1 ...`

Main server behavior:
- During upload/HLS observation, `/api/version` p95 was about 30.67 ms, max 401.17 ms, with 2 transient connection failures during the initial concurrent upload pressure.
- During normal playback-like measurement, health endpoint p95 remained low except during the problematic q1080 sample.
- No DB lock 500 error was observed.
- No HLS worker crash was observed.
- 5017 test server was stopped after the run.

## Follow-ups

1. Change HLS encoding so displayed target bitrate is actually enforced, or use quality presets that guarantee lower variants are smaller than source. Applied after this audit: ffmpeg now receives bitrate control arguments for transcoded variants.
2. Consider generating `480p` and `720p` first, then making `1080p` optional or deferred. Applied after this audit: default `HACKME_MEDIA_HLS_QUALITY_HEIGHTS` is now `480,720`; operators can still opt into 1080p by setting the environment variable.
3. Add a separate HLS streaming backpressure lane so playback is not throttled exactly like uploads/transcodes.
4. Add a report metric that separates upload success throughput from controlled `server_busy` rejections.

## Follow-up Patch: Quality Selection And Quota Boundary

Applied after the stress run:
- HLS playback payload now declares a default quality and fallback quality. The frontend prefers `720p` when present, then falls back to `480p`.
- The main video player and shared-video player show explicit quality controls. Auto fallback to `480p` is attempted when HLS stalls or reports network/buffer errors, unless the viewer manually selected a quality.
- HLS generation now deletes and hides any generated lower-quality derivative whose total package size is larger than the original HLS package.
- Cloud Drive quota accounting remains based on `uploaded_files.size_bytes`. HLS derivatives and E2EE Streaming v2 bundles are reported as service cache excluded from user quota.
- strict E2EE still does not allow server-side 480/720/1080 transcoding. The safe path for equal multi-quality behavior is browser-side generation of encrypted derivatives, then uploading those encrypted service bundles outside user quota.
