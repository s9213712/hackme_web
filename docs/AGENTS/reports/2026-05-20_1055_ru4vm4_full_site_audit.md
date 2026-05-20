# ru4vm4 Full Site Audit Report

Date: 2026-05-20

Scope:

- Fresh full-site audit for `ru4vm4` request.
- Browser QA, platform centers, member behavior probe, security headers, HTTP
  stress, ComfyUI workflow/editor UI, games, video/HLS, Cloud Drive/E2EE,
  remote downloads, CSRF/auth, plaintext secrets, and trading core/pricing.
- Remote ComfyUI backend setting: `http://192.168.18.19:8188`.

Confirmed findings fixed:

1. Medium: trading live quote cache could hold `boot_pending`.
   - Impact: the first live quote after clearing boot-ready state could be
     cached, so a follow-up stable quote still returned `boot_pending` and bot /
     matching / risk gates stayed blocked longer than intended.
   - Evidence: `tests/trading/pricing/test_trading_boot_ready_gate.py::test_first_quote_from_default_does_not_release_bot_gate`
     failed before the fix.
   - Fix: `services/trading/price_runtime.py` now treats `boot_pending` payloads
     as non-cacheable and avoids serving them as stale fallback.

2. Low: deep Playwright ComfyUI visual button check did not handle collapsed
   workflow action menus.
   - Impact: QA falsely reported the visual workflow load button as missing
     after the UI was intentionally simplified into "更多操作".
   - Evidence: first deep run failed `comfyui_main_page_visual_button`; manual
     DOM check found the button inside a collapsed `<details>` menu.
   - Fix: `scripts/testing/playwright_deep_site_check.py` opens the containing
     details menu before asserting visibility.

Environment blockers / false positives:

- Remote ComfyUI `http://192.168.18.19:8188` is unreachable from this QA host:
  `curl` returned `No route to host`, and app-side generation attempts returned
  a controlled `503` with `ComfyUI 連線失敗：[Errno 113] No route to host`.
  This blocks live remote ComfyUI generation verification from this machine.
- Member probe still labels BT private tracker handling as a critical SSRF
  issue. Direct `127.0.0.1` URL is blocked with HTTP 400, while magnet/torrent
  jobs are allowed to start under the current product policy. Targeted tests
  confirm the intended behavior: unsafe/private trackers are excluded/reported
  without rejecting the entire BT task.

Coverage summary:

- Deep Playwright rerun: all non-ComfyUI-network checks passed. The corrected
  ComfyUI visual button check passed; only remote ComfyUI connection remained
  blocked by network route.
- Platform health Playwright: passed.
- Security headers: `24/24` passed.
- Low-volume HTTP stress: `24/24` passed, no server errors.
- Plaintext secrets scan: passed with `0` blocking findings.
- Member probe: passed except the known BT policy mismatch above.
- No browser console/page errors were reported by the deep/platform runs.

Validation commands:

- `python3 scripts/testing/playwright_deep_site_check.py --runtime-root /tmp/hackme_web_audit_ru4vm4_deep2_20260520 --comfyui-api-url http://192.168.18.19:8188`
- `python3 scripts/testing/playwright_platform_health_check.py --runtime-root /tmp/hackme_web_audit_ru4vm4_platform_20260520 --comfyui-api-url http://192.168.18.19:8188`
- `python3 /home/s92137/.codex/skills/hackme-web-qa/scripts/member_probe.py --base-url https://127.0.0.1:55448 --root-password RootQa123! --test-password TestQa123! --out /tmp/hackme_web_audit_ru4vm4_member/member_probe/member_probe.json`
- `python3 scripts/security/gate/header_security_check.py --base-url https://127.0.0.1:55448 --out-json /tmp/hackme_web_audit_ru4vm4_member/header_security.json --out-md /tmp/hackme_web_audit_ru4vm4_member/header_security.md`
- `python3 scripts/security/pentest/stress_test.py --target https://127.0.0.1:55448 --requests 24 --concurrency 4 --timeout 10 --out /tmp/hackme_web_audit_ru4vm4_member/stress --i-own-this-target`
- `python3 scripts/security/gate/scan_plaintext_secrets.py --report-json /tmp/hackme_web_audit_ru4vm4_member/plaintext_secrets.json --report-md /tmp/hackme_web_audit_ru4vm4_member/plaintext_secrets.md --fail-on high`
- `python3 -m pytest -q tests/frontend/comfyui/test_comfyui_media_picker_ui.py tests/comfyui/test_template_ui_schema.py tests/comfyui/test_template_acceptance.py tests/frontend/games/test_frontend_games.py`
- `python3 -m pytest -q tests/storage/test_remote_downloads.py tests/storage/test_cloud_drive_attachments.py::test_remote_download_torrent_upload_accepts_and_excludes_private_tracker`
- `python3 -m pytest -q tests/account/auth/test_account_register.py tests/security/auth/test_auth_csrf_safe.py tests/video/streaming/test_video_streaming.py::test_shared_standard_video_playback_uses_shared_hls_and_stream_urls tests/video/streaming/test_video_streaming.py::test_shared_video_three_privacy_modes_complete_unlock_flow`
- `python3 -m pytest -q tests/trading/core/test_trading_engine.py tests/trading/pricing/test_trading_boot_ready_gate.py`
- `python3 -m pytest -q tests/trading/core/test_trading_background_engine.py tests/trading/grid/test_grid_fee_model.py tests/trading/pricing/test_trading_reference_prices.py`
- `python3 -m compileall -q services/trading/price_runtime.py scripts/testing/playwright_deep_site_check.py`

Artifacts:

- Deep report:
  `/tmp/hackme_web_audit_ru4vm4_deep2_20260520/reports/qa/playwright_deep_site_check_20260520T025009Z.md`
- Platform report:
  `/tmp/hackme_web_audit_ru4vm4_platform_20260520/reports/qa/playwright_platform_health_check_20260520T024114Z.md`
- Member probe:
  `/tmp/hackme_web_audit_ru4vm4_member/member_probe/member_probe.json`
- Header/security/stress/secret reports:
  `/tmp/hackme_web_audit_ru4vm4_member/header_security.md`,
  `/tmp/hackme_web_audit_ru4vm4_member/stress/`,
  `/tmp/hackme_web_audit_ru4vm4_member/plaintext_secrets.md`
