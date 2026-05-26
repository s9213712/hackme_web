# 2026-05-26 51475 Encrypted Video HLS / E2EE QA

## Scope

- Isolated server: `https://127.0.0.1:51475`
- Run root: `/tmp/hackme_web_real_hls_20260526_encrypted/hackme_web`
- Storage root: `/mnt/d/tmp`
- Source file: `/mnt/d/[TSDM][Cosmic Princess Kaguya][2026][NF_Web-DL][HEVC-10bit 1080p AAC][CHS_JP].mkv`
- Source characteristics: 3.53 GiB MKV, HEVC 1080p, AAC JPN, embedded ASS subtitles, font attachments.
- Server intentionally left running for manual inspection.

## Confirmed Findings

### P1 - Strict E2EE large video cannot auto-generate HLS/subtitles server-side

Strict E2EE publish/share works, but the server correctly refuses server-side transcode/decrypt for E2EE video. The shared E2EE playback falls back to `e2ee_direct` full ciphertext browser decrypt, with no HLS manifest and no extracted subtitles.

Impact: large E2EE video shares are functional as encrypted files, but not yet a good streaming experience. This needs client-side encrypted Streaming v2 derivative generation, and the current single-bundle limit is too small for this 3.79 GB source.

Evidence:

- E2EE share: `https://127.0.0.1:51475/shared/videos/Xd-Cf3FYI919VCejd_0EJjXMGjgM9xkhXjtxjLW5Huo`
- Report: `/tmp/hackme_web_real_hls_20260526_encrypted/e2ee_publish_existing_video_probe.json`
- Playback mode: `e2ee_direct`
- `streaming_ready=false`
- E2EE prepare-stream result: `409 strict_e2ee_server_transcode_disabled`

### P2 - Server-side encryption expands storage and needs large staging headroom

The 3.79 GB MKV became a 5.05 GB server-encrypted object after chunked Fernet encryption. During import, plaintext staging and encrypted target coexist.

Impact: large encrypted uploads need quota and disk headroom policy that accounts for encryption expansion and temporary staging, otherwise users will see unexpected failures on large video imports.

Evidence:

- Source size: `3,790,022,687` bytes
- Stored encrypted file: `5,053,460,995` bytes
- Server-encrypted file id: `303ca09c747f44159670fa73d6133475`
- Stored path: `/mnt/d/tmp/users/1/0bf67cac6c774d09a62a1b53bba3b3ac/_TSDM__Cosmic Princess Kaguya__2026__NF_Web-DL__HEVC-10bit 1080p AAC__CHS_JP_.mkv`

### P2 - Processing share previously appeared invalid instead of showing progress

While server-encrypted HLS was still processing, the active share link resolved as `not_ready`, so the share page could look expired/unavailable even though share management showed it active.

Fix applied:

- `services/media/videos.py`: added `allow_processing` support to share resolution/payload.
- `routes/videos.py`: shared page/detail/playback/unlock routes now allow processing payloads while stream-serving paths remain strict.
- Added targeted regression test in `tests/video/api/test_video_publish.py`.

Validation:

- `python3 -m py_compile services/media/videos.py routes/videos.py`
- `pytest tests/video/api/test_video_publish.py tests/video/streaming/test_video_streaming.py::test_shared_standard_video_playback_uses_shared_hls_and_stream_urls -q`
- Result: `17 passed`

## Passed Coverage

### Server-encrypted MKV

Server-encrypted import, publish to video, shared HLS preparation, HLS playback metadata, and subtitle extraction all passed.

- Video share: `https://127.0.0.1:51475/shared/videos/cH-WHf4PoOWr4sKdlVYNLF7vNZk4_RumLz3-Gl-3dec`
- Video id: `1`
- File id: `303ca09c747f44159670fa73d6133475`
- HLS status: `ready`
- Master manifest: `media_derivatives/303ca09c747f44159670fa73d6133475/master.m3u8`
- Variants: original 1080p, 720p, 480p
- Subtitle: `sub01_chi.vtt`, label `JPSC`, language `chi`, default enabled
- Job center status: `succeeded`, progress `100`, stage `ready`

### Frontend Subtitle Verification

The shared video page was opened through Playwright and the frontend subtitle path was verified, not just the backend API.

Evidence:

- JSON: `/tmp/hackme_web_real_hls_20260526_encrypted/shared_video_subtitle_frontend_check.json`
- Screenshot: `/tmp/hackme_web_real_hls_20260526_encrypted/shared_video_subtitle_frontend_check.png`

Observed:

- Player tag: `VIDEO`
- Player source: shared HLS `q720/playlist.m3u8`
- One subtitle track attached
- Track label: `JPSC`
- Track language: `chi`
- Track default: `true`
- TextTrack mode: `showing`
- Cue count: `45,800`
- Sample cues include Chinese/Japanese subtitle text
- Subtitle time-shift controls were present in the quality panel.

### E2EE Share Verification

E2EE upload/import and share publishing passed when using a supported share key envelope.

- E2EE file id: `0faf6105bfff4ddbb3be83f3f790e515`
- E2EE share: `https://127.0.0.1:51475/shared/videos/Xd-Cf3FYI919VCejd_0EJjXMGjgM9xkhXjtxjLW5Huo`
- Share requires fragment key: `true`
- Shared detail: `200`
- Shared playback: `200`
- Shared E2EE key endpoint: `200`

Expected limitation under strict E2EE:

- No server HLS
- No server subtitle extraction
- Full browser-side decrypt fallback

## Artifacts

- Server log: `/tmp/hackme_web_real_hls_20260526_encrypted/hackme_web/runtime/logs/server_direct.out`
- Server-encrypted probe script: `/tmp/encrypted_real_mkv_video_probe.py`
- E2EE import script: `/tmp/e2ee_real_mkv_video_probe.py`
- E2EE publish script: `/tmp/e2ee_publish_existing_video_probe.py`
- Frontend subtitle script: `/tmp/shared_video_subtitle_frontend_check.py`

## Current Server State

Server remains running on `https://127.0.0.1:51475`.

Last process check showed gunicorn master `1077386` and four workers alive. No active ffmpeg/HLS worker was observed after HLS completion.
