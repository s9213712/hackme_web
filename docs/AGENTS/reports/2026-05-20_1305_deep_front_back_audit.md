# Deep Front/Back Audit Report

Date: 2026-05-20

Scope:

- Full repo test discovery, full isolated pytest, pre-push gates, browser QA,
  member behavior probe, ComfyUI workflow UI, platform centers, Cloud Drive /
  E2EE / remote downloads, video share playback, games, CSRF/auth/security
  smoke, snapshots, audit-chain checks, and docs/release consistency.
- Remote ComfyUI backend under test: `http://192.168.18.19:8188`.

Confirmed findings fixed:

1. High: remote-download task status could disappear under multi-worker
   Gunicorn.
   - Impact: a BT/direct remote-download task created by one worker could be
     polled by another worker and return `404 找不到下載任務`, making the
     frontend progress look like a silent failure.
   - Fix: remote-download tasks now sync creation/progress/terminal state into
     Job Center, status/list routes fall back to persisted Job Center records,
     and persisted records preserve file/storage metadata.
   - Evidence: `tests/storage/test_cloud_drive_attachments.py::test_remote_download_task_status_falls_back_to_persisted_job`.

2. High: QA member probe had stale BT and video assumptions.
   - Impact: the audit tool reported false critical/high failures after product
     behavior changed: BT magnet/torrent tasks should start and sanitize private
     trackers instead of hard-blocking the whole task; video share unlock must
     wait for stream readiness.
   - Fix: repo and Codex skill `member_probe.py` now checks direct-localhost
     blocking, BT task observability, waits for video stream readiness, and
     avoids stale keep-alive reuse against Gunicorn.
   - Evidence: clean member probe result has `17` checks and `0` findings.

3. High: isolated full pytest originally exposed cross-domain regressions.
   - Fixed areas: ComfyUI interrupt ownership policy, global language switcher
     wiring/overlap, muted contrast regression, chess neural incremental state,
     games user/invite behavior, chess default difficulty, snapshot restore
     concurrency, and security-smoke feature flag setup.
   - Evidence: full isolated pytest passed `2562 passed in 486.02s`.

4. Medium: pre-push gates were stale or too shallow for current layout.
   - Fixed areas: API contract snapshot, smoke-suite path, snapshot/log/points
     checks across subdirectories, and password/CSRF smoke setup.
   - Evidence: full pre-push passed `PASS: 19 WARN: 0 FAIL: 0 SKIP: 0`.

5. Medium: root pytest collection included archived docs scripts.
   - Impact: root `pytest --collect-only` failed on docs/archive test-like files.
   - Fix: `pytest.ini` now restricts discovery to real tests and excludes
     docs/reference/runtime/cache.

Environment blocker:

- Remote ComfyUI `http://192.168.18.19:8188` remains unreachable from this QA
  host. Direct check on 2026-05-20 returned:
  `curl: (7) Failed to connect to 192.168.18.19 port 8188 ... No route to host`.
  Browser QA correctly surfaces this as a controlled `503` instead of a silent
  success. Live remote GPU generation cannot be verified from this machine until
  network routing/firewall access is available.

Coverage summary:

- Full isolated pytest: passed.
- Full pre-push gates: passed after this report edit with
  `PASS: 19 WARN: 0 FAIL: 0 SKIP: 0`.
- Deep Playwright: all app/browser flows passed except the remote ComfyUI
  connection blocker above.
- Platform Playwright: passed, with only mobile target-size warnings on small
  icon buttons.
- ComfyUI visual workflow builder: passed render, drag, wire, delete edge,
  import JSON, and mobile layout checks.
- Member probe: passed `17/17`, covering auth, drive previews, E2EE rejection,
  share links, album password sharing, remote download SSRF/BT observability,
  video password share playback, unsupported video privacy mode, and trading
  grid fee math.

Validation commands:

- `python3 -m pytest --collect-only -q`
- `KEEP_TMP=0 PYTEST_TMP_ROOT=/tmp/hackme_web_full_pytest_audit_after_20260520 scripts/testing/pytest_in_tmp.sh tests`
- `ALLOW_MISSING_GITLEAKS=1 python3 scripts/prepush/pre_push_checks.py --ci --full`
- `python3 scripts/testing/playwright_deep_site_check.py --runtime-root /tmp/hackme_web_deep_audit_playwright_after_20260520 --comfyui-api-url http://192.168.18.19:8188`
- `python3 scripts/testing/playwright_platform_health_check.py --runtime-root /tmp/hackme_web_platform_audit_20260520_final --comfyui-api-url http://192.168.18.19:8188`
- `python3 scripts/testing/playwright_comfyui_workflow_builder_check.py`
- `python3 /home/s92137/.codex/skills/hackme-web-qa/scripts/member_probe.py --base-url https://127.0.0.1:57485 --root-password RootProbe123! --test-password TestProbe123! --out /tmp/hackme_web_member_probe_20260520_clean/member_probe/member_probe.json`
- `python3 -m pytest tests/storage/test_cloud_drive_attachments.py::test_remote_download_task_status_falls_back_to_persisted_job tests/storage/test_cloud_drive_attachments.py::test_remote_download_task_reports_progress_and_completion tests/storage/test_cloud_drive_attachments.py::test_remote_download_task_can_pause_and_resume tests/storage/test_cloud_drive_attachments.py::test_remote_download_task_accepts_uploaded_torrent_file tests/video/security/test_video_module_pentest_script.py -q`
- `python3 -m py_compile docs/AGENTS/skills/hackme-web-qa/scripts/member_probe.py routes/files.py routes/file_sections/remote_download_routes.py`
- `curl -sS -m 8 -i http://192.168.18.19:8188/system_stats`

Artifacts:

- Deep Playwright:
  `/tmp/hackme_web_deep_audit_playwright_after_20260520/reports/qa/playwright_deep_site_check_20260520T042702Z.md`
- Platform Playwright:
  `/tmp/hackme_web_platform_audit_20260520_final/reports/qa/playwright_platform_health_check_20260520T045155Z.md`
- Member probe:
  `/tmp/hackme_web_member_probe_20260520_clean/member_probe/member_probe.json`
