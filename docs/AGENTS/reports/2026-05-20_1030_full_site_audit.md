# Full Site Audit Report

Date: 2026-05-20

Scope:

- Isolated full-site browser QA against a fresh runtime.
- Auth, admin, account registration, CSRF, Cloud Drive/E2EE, remote download,
  video upload/share/HLS, games, economy/trading, ComfyUI frontend/workflow UI,
  platform centers, security headers, low-volume HTTP stress, and plaintext
  secret scan.
- Remote ComfyUI backend setting: `http://192.168.18.19:8188`.

Confirmed fixes made during audit:

- `scripts/security/gate/header_security_check.py` and
  `scripts/security/pentest/stress_test.py` failed as direct entrypoints because
  they imported `scripts.*` without adding the repo root to `sys.path`. Added
  the same direct-entry import guard used by maintained CI scripts.
- `tests/frontend/comfyui/test_comfyui_media_picker_ui.py` still asserted the
  old `<video src="...">` renderer. The product now uses
  `<video><source src="..." type="..."></video>` so generated videos can carry a
  MIME type. Updated the test to match the current renderer.

Audit results:

- Deep Playwright audit completed with no browser console/page errors.
- Platform health acceptance passed and verified job center, notifications,
  share center, trading asset overview, and 390x844 / 768x1024 / 1366x768
  responsive views.
- Security header audit passed `24/24`.
- Low-volume HTTP stress against the isolated server passed `24/24` requests
  with no server errors.
- Plaintext secret scan passed with `0` blocking findings.
- Focused pytest passed for ComfyUI frontend/template schema/acceptance, CSRF,
  registration, remote downloads, torrent private tracker handling, and shared
  video playback/unlock flows.

Findings / audit blockers:

- The configured remote ComfyUI backend `http://192.168.18.19:8188` was not
  reachable from this QA host: `[Errno 113] No route to host`. The UI handled
  this as a `503` remote connection failure instead of a white screen.
- The deep auth registration journey initially timed out waiting for
  `#reg-msg`. Manual reproduction showed `/api/register` returned `200` and the
  success message appeared, then auto-cleared after returning to the login tab.
  This is a Playwright timing mismatch, not a confirmed product failure.
- The deep ComfyUI visual-builder button check initially reported the button
  missing. Manual inspection found `#comfyui-workflow-load-visual-btn` present
  and visible below the first viewport. This is a viewport/location mismatch.
- The member probe still expects BT private tracker URLs to hard-block the
  whole download. Current product policy excludes unsafe/private trackers while
  allowing the BT task to continue. Targeted repo tests confirm the intended
  behavior.
- The member video probe reported a password-share playback issue while the
  uploaded media was still processing. Targeted HLS/share unlock tests passed.
- `playwright_trading_background_correctness.py` reached a liquidation check
  where background jobs ran, but the liquidation stayed open because the audit
  server used real live provider pricing. The job log showed
  `live trading price jump ... exceeds max 1000.00% for ETH/POINTS`, so the
  risk guard correctly refused a synthetic crash price. This check must be run
  with the QA live price provider enabled on the server process, otherwise it
  is not deterministic.
- The reported post-finish white/backlight screen was not reproduced in the
  deep/platform browser audits. Manual ComfyUI inspection showed the app body
  and active module backgrounds were dark and no full-screen white overlay was
  present.

Artifacts:

- Deep audit JSON:
  `/tmp/hackme_web_audit_20260520_fullsite/reports/qa/playwright_deep_site_check_20260520T015533Z.json`
- Deep audit Markdown:
  `/tmp/hackme_web_audit_20260520_fullsite/reports/qa/playwright_deep_site_check_20260520T015533Z.md`
- Platform health JSON:
  `/tmp/hackme_web_audit_platform_20260520/reports/qa/playwright_platform_health_check_20260520T022504Z.json`
- Platform health Markdown:
  `/tmp/hackme_web_audit_platform_20260520/reports/qa/playwright_platform_health_check_20260520T022504Z.md`
- Security header reports:
  `/tmp/hackme_web_audit_member/header_security.json`,
  `/tmp/hackme_web_audit_member/header_security.md`
- Secret scan report:
  `/tmp/hackme_web_audit_member/plaintext_secrets.md`

Validation commands:

- `python3 scripts/testing/playwright_deep_site_check.py --runtime-root /tmp/hackme_web_audit_20260520_fullsite --comfyui-api-url http://192.168.18.19:8188`
- `python3 scripts/testing/playwright_platform_health_check.py --runtime-root /tmp/hackme_web_audit_platform_20260520 --comfyui-api-url http://192.168.18.19:8188`
- `python3 /home/s92137/.codex/skills/hackme-web-qa/scripts/member_probe.py --base-url https://127.0.0.1:55348 --root-password RootQa123! --test-password TestQa123! --out /tmp/hackme_web_audit_member/member_probe/member_probe.json`
- `python3 scripts/security/gate/header_security_check.py --base-url https://127.0.0.1:55348 --out-json /tmp/hackme_web_audit_member/header_security.json --out-md /tmp/hackme_web_audit_member/header_security.md`
- `python3 scripts/security/pentest/stress_test.py --target https://127.0.0.1:55348 --requests 24 --concurrency 4 --timeout 10 --out /tmp/hackme_web_audit_member/stress --i-own-this-target`
- `python3 scripts/security/gate/scan_plaintext_secrets.py --report-json /tmp/hackme_web_audit_member/plaintext_secrets.json --report-md /tmp/hackme_web_audit_member/plaintext_secrets.md --fail-on high`
- `python3 -m pytest -q tests/frontend/comfyui tests/comfyui/test_template_ui_schema.py tests/comfyui/test_template_acceptance.py`
- `python3 -m pytest -q tests/storage/test_remote_downloads.py tests/storage/test_cloud_drive_attachments.py::test_remote_download_torrent_upload_accepts_and_excludes_private_tracker`
- `python3 -m pytest -q tests/account/auth/test_account_register.py tests/security/auth/test_auth_csrf_safe.py`
- `python3 -m pytest -q tests/video/streaming/test_video_streaming.py::test_shared_standard_video_playback_uses_shared_hls_and_stream_urls tests/video/streaming/test_video_streaming.py::test_shared_video_three_privacy_modes_complete_unlock_flow`
- `python3 -m compileall -q scripts/security/gate/header_security_check.py scripts/security/pentest/stress_test.py`
