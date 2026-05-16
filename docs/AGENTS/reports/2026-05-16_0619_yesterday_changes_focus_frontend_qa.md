# 2026-05-16 Yesterday Changes Focus QA

Scope: rechecked the main changes from 2026-05-15 on branch `03.Points`, with emphasis on Drive/background transfers, E2EE uploads, BT/direct link tasks, task center controls, share management, system resource UI, CSRF/access controls, video HLS, games, economy, trading, and admin/security pages.

## Findings

No open frontend blocker remains after this pass.

Fixed during QA:

- Drive refresh was inside the hidden `capacity` subpage, so Playwright and users on the default file-management subpage could not click `#drive-refresh-btn`. Moved the refresh button above the Drive subpage panels so both file management and capacity management can refresh Drive/background transfer state.
- Admin appeals visibility used a feature-flag check instead of the full `canAccessModule("appeals")` gate for root/admin tab display. Restored explicit guards for both user-side and root-side appeals tabs to prevent disabled appeals from being shown or prefetched.
- Anonymous media streaming routes returned a 3-value auth helper result on one branch, which produced a 500 in `/api/media/<file_id>/stream-status`. Normalized the helper return shape and added a regression so unauthenticated streaming endpoints return auth errors instead of internal errors.
- System resource board data collection now has a short server-side cache, so repeated environment-board refreshes do not spawn GPU/resource probes on every click.
- Server-side encrypted uploads now use chunked server-side encryption for all new files, with chunked download/inline content decryption instead of a small-file/large-file split. E2EE Streaming v2 bundle immediate processing now defaults to 128 MB and writes the bundle without an extra `bytes()` copy.
- Drive module switching now uses a lazy refresh path: recent Drive data is not fully refetched on every tab switch, while background transfer state still syncs and explicit actions still perform full refreshes.

## Verification

Passed:

- `pytest -q tests/frontend`
- `node --check public/js/00-core.js`
- `node --check public/js/35-drive.js`
- `node --check public/js/35-drive-preview-share.js`
- `node --check public/js/50-admin.js`
- `node --check public/js/57-platform-centers.js`
- `pytest -q tests/storage/test_cloud_drive_attachments.py -k "resumable_upload or remote_download or share_link_e2ee or e2ee"`: 28 passed
- `pytest -q tests/storage/test_remote_downloads.py`: 16 passed
- `pytest -q tests/security/auth/test_auth_csrf_safe.py tests/security/auth/test_access_controls.py`
- `pytest -q tests/frontend/admin/test_frontend_account_admin.py tests/frontend/admin/test_frontend_security_center_layout.py tests/frontend/storage/test_frontend_drive_preview.py tests/frontend/test_platform_centers_frontend.py tests/frontend/video/test_frontend_videos.py tests/frontend/trading/test_frontend_economy.py`: 42 passed
- `pytest -q tests/security/auth/test_access_controls.py::test_admin_environment_exposes_relative_paths_and_pid tests/frontend/admin/test_frontend_security_center_layout.py`: 16 passed
- `pytest -q tests/storage/test_cloud_drive_attachments.py -k "resumable_upload or server_encrypted"`: 12 passed
- `pytest -q tests/video/streaming/test_video_streaming.py -k "media_prepare_and_status_require_login_without_500 or e2ee_stream"`: 8 passed
- `pytest -q tests/frontend/storage/test_frontend_drive_preview.py tests/frontend/admin/test_frontend_security_center_layout.py tests/frontend/test_platform_centers_frontend.py`: 27 passed
- `python3 -m py_compile routes/system_admin_sections/security_routes.py routes/videos.py services/storage/cloud_drive.py services/media/e2ee_streaming.py`
- `node --check public/js/35-drive.js`
- `node --check public/js/35-drive-preview-share.js`
- `node --check public/js/50-admin.js`
- `git diff --check`

Browser QA:

- First Playwright run found `drive_e2ee_journey` could not click the hidden Drive refresh button.
- After the Drive refresh placement fix, rerun passed all checks.
- Report: `/tmp/hackme_web_frontend_playwright_20260516_qa_rerun/reports/qa/playwright_deep_site_check_20260515T221639Z.md`
- JSON: `/tmp/hackme_web_frontend_playwright_20260516_qa_rerun/reports/qa/playwright_deep_site_check_20260515T221639Z.json`

Covered Playwright flows included root login, feature enablement, authenticated API surface, registration/login, admin account management, forum posting/reactions, Drive standard/E2EE upload, video upload/share/HLS playback, games/chess, economy/trading wallet and order flow, launch/security health, ComfyUI workflow builder, desktop/mobile module tabs, and Civitai missing-key guard.

Heuristic follow-up:

- Custom Playwright/API probe: `/tmp/hackme_web_heuristic_20260516_0720/heuristic_probe/result.json`
- Result: 0 failed checks.
- Covered unauthenticated media streaming auth behavior, resumable upload partial progress, incomplete-complete rejection, task center visibility, resumable cancellation, root admin job visibility, randomized module switching, Drive refresh visibility across files/capacity pages, job center rendering, system resource board rendering, and browser console/page errors.
- System board API timing after cache hardening on the isolated server: 53.7 ms, 26.5 ms, 27.0 ms; all returned the same `sampled_at` within the cache window.

Full heuristic pass:

- Custom Playwright/API probe, without using the existing project test suite: `/tmp/hackme_web_full_heuristic_20260516_0815/full_heuristic/result.json`
- Result: 43 checks, 0 failures, 2 timing warnings.
- Timing warnings: Drive security policy took 1221.0 ms against a 1200 ms heuristic threshold; storage albums took 1277.6 ms against a 1200 ms heuristic threshold. No 500, traceback, severe browser console error, or silent failure was found in this run.
- Covered desktop and mobile navigation for Drive, albums, videos, games, jobs, shares, ComfyUI, economy, trading, accounts, and server pages, including basic responsiveness and horizontal-overflow checks.
- Verified the album picker is now a compact card grid instead of a full-width row selector.
- Verified partial resumable upload state survives reload as a waiting task, and the Drive page now tells the user to reselect the same file to continue. The browser cannot automatically resume the local file bytes after reload because the `File` object is intentionally not persisted by the browser.
- Verified the backend resumable session accepts the remaining chunk after reselect/resume and completes without duplicate-byte accounting.
- Verified BT and direct-link tasks can coexist in the task center, expose speed/progress metadata, and the remote-download scheduler prefers higher-availability BT jobs when a worker slot opens.
- Verified invalid BT/direct inputs return explicit user-facing errors instead of silently failing.

## Notes

- Optional live ComfyUI/Civitai checks were not configured; offline guard checks passed.
- Remaining performance caveat: server-side encrypted file operations still use Fernet whole-file encryption/decryption by design, so the immediate path is now capped more tightly. Larger files should move to a background/chunked encryption pipeline before raising this limit.
- Remaining performance caveat: E2EE Streaming v2 immediate bundle upload still accepts a bounded bundle in one request. The default cap is lower now; large media should use resumable/chunked preparation instead of increasing the inline cap.
- Remote downloads and HLS preparation are already external-worker oriented in the checked path; keep the external-worker feature flags enabled in deployment so aria2/ffmpeg work does not run inline in the main Flask process.
- Playwright isolated server stopped after the run; no runtime process remained for `/tmp/hackme_web_frontend_playwright_20260516_qa_rerun`.
