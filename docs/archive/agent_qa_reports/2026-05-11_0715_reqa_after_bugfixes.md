# 2026-05-11 Re-QA After Bugfixes

Scope: verify fixes from the previous full-feature QA report, add a reusable `hackme-web-qa` skill, then run a fresh heuristic QA pass against the current working tree.

## Skill

- Created local skill: `<codex_home>/skills/hackme-web-qa`
- Mirrored project copy: `docs/AGENTS/skills/hackme-web-qa`
- Both copies passed `quick_validate.py`.
- Added a sync rule to the skill: future changes to either copy must be mirrored to the other location.

## Test Artifacts

- Stable source snapshot: `/tmp/hackme_web_stable_reqa_20260511_0620/hackme_web`
- Isolated member-probe server/runtime: `/tmp/hackme_web_reqa_20260511_0620/hackme_web`
- Member probe JSON: `/tmp/hackme_web_reqa_20260511_0620/member_probe/member_probe.json`
- Playwright runtime: `/tmp/hackme_web_reqa_deep_20260511_0620`
- Playwright JSON: `/tmp/hackme_web_reqa_deep_20260511_0620/reports/qa/playwright_deep_site_check_20260510T230025Z.json`

Note: a stable source snapshot was used because `test_for_develop.sh` hit `tar: ./docs/chess_debug/reports: file changed as we read it` while another process was updating that volatile report directory.

## Results

- Previous-finding targeted pytest:
  - `41 passed in 1.39s`
- Domain pytest:
  - `1108 passed in 81.85s`
- Full pytest:
  - `1640 passed in 729.34s`
- Member-behavior probe:
  - `17 passed, 0 failed`
- Playwright deep site check:
  - `32 passed, 1 failed`

## Fix Verification

Verified fixed:

- Malformed E2EE upload now returns a client error instead of 500.
- `.torrent` localhost/private tracker path is now blocked consistently with direct URL and magnet.
- ComfyUI generation helper contract regression is fixed.
- ComfyUI/static asset cache-bust snapshot tests pass.
- Password toggle/touch target sizing tests pass.
- Album CSS/version snapshot test passes.
- Trading settings schema snapshot drift is resolved.
- `/api/comfyui/models` authenticated API surface now returns 200 in the deep check.
- Grid fee math still matches independent Decimal calculation.
- Reserve allocation works with required `ROOT_RESERVE_ALLOCATION` reason.

## Remaining Noise

No new confirmed product bugs found in this pass.

Known QA harness issue:

- `playwright_deep_site_check.py::video_upload_share_flow` still fails with `shared_hls=False` because it checks password-protected shared playback before unlocking the share. The dedicated member probe uploads a real MP4, unlocks with the share password, and confirms shared playback returns OK.

Environment-only noise:

- Playwright captured a browser 500 for `/api/root/server-update/status`. This run used a source snapshot without `.git`, so the git-state endpoint reported failure in the test environment. The normal `test_for_develop.sh` path points `HTML_LEARNING_GIT_REPO_DIR` at the real repo; this was not treated as a product bug.

## Coverage Highlights

Passed in this run:

- Register/login/root/test sessions and CSRF-protected API calls.
- Admin member governance, blocking/unblocking, settings, security health.
- Cloud drive uploads/previews for txt, md, json, html, pdf, png, zip.
- Valid E2EE upload and server-preview rejection behavior.
- Malformed E2EE upload error behavior.
- Share-link download and album password share.
- Remote direct URL, magnet, and `.torrent` private endpoint guards.
- Real MP4 upload, HLS preparation, password share unlock, and shared playback.
- Unsupported video E2EE privacy mode explicit rejection.
- Forum, chat, notifications, games, chess, solo score paths via Playwright.
- ComfyUI workflow builder, visual editor drag/edge behavior, offline Civitai guard.
- Points wallet/ledger/catalog, admin adjustment, trading dashboard/markets/orders.
- Trading grid fee math and reserve verification.
