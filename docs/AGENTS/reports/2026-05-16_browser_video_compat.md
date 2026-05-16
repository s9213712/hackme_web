# 2026-05-16 Browser Video Compatibility

## Scope

- Started an isolated hackme_web runtime.
- Published a tiny MP4 through the video publish UI.
- Opened the generated password-protected share page anonymously.
- Checked desktop and mobile viewports in Playwright Chromium, Firefox, and WebKit.
- Verified unlock, playback descriptor, HLS manifest, player DOM sizing, and HLS/direct media reads.

## Findings Fixed

1. Shared playback descriptors for standard videos returned owner-only `/api/videos/<id>/...` URLs.
   Anonymous shared pages could unlock successfully but later hit 403 on HLS/direct media reads. Shared playback now returns `/api/videos/shared/<token>/...` URLs.

2. Shared HLS playlists appended `share_session` to playlist and segment lines but not to `#EXT-X-MAP:URI="init.mp4"`.
   Firefox/WebKit through HLS.js requested the init segment without a session and received 401. HLS manifest rewriting now also handles quoted `URI="..."` attributes.

3. CSP did not allow HLS.js blob workers.
   Firefox/WebKit logged worker-src CSP errors. `worker-src 'self' blob:` is now included while keeping `script-src 'self'`.

4. The Playwright fixture assumed published videos immediately appeared in `/api/videos`.
   The current product behavior hides videos until HLS is ready, so the fixture now uses the upload response and share URL directly.

## Final Result

Final artifact:

- `/tmp/hackme_web_browser_video_20260516T153902Z/reports/qa/browser_video_compat.md`
- `/tmp/hackme_web_browser_video_20260516T153902Z/reports/qa/browser_video_compat.json`

Matrix:

- Chromium desktop: PASS
- Chromium mobile: PASS
- Firefox desktop: PASS
- Firefox mobile: PASS
- WebKit desktop: PASS
- WebKit mobile: PASS

## Verification

- `python3 -m py_compile routes/videos.py server.py scripts/testing/playwright_browser_video_compat.py tests/video/streaming/test_video_streaming.py`
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest tests/video/streaming/test_video_streaming.py tests/frontend/storage/test_frontend_drive_preview.py::test_cloud_drive_preview_ui_is_wired -q`
- `PYTHONPATH=/home/s92137/hackme_web python3 scripts/testing/playwright_browser_video_compat.py`
- `git diff --check`
