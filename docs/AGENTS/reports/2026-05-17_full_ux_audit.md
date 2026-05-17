# Full UX / Frontend-Backend Audit

## Scope
- Ran heuristic Playwright coverage against an isolated local server on `https://127.0.0.1:55412`.
- Covered root and normal user accounts across desktop and mobile viewports.
- Checked module activation, console errors, request failures, horizontal overflow, fixed UI overlap, unlabeled visible controls, unnamed buttons, and mobile layout regressions.

## Fixes Applied
- Prevented desktop module headers and action buttons from sitting under the fixed quick-action bar by increasing authenticated desktop content top clearance.
- Stopped chat room auto-focus from scrolling the page into the fixed quick-action bar; focus now uses `preventScroll`.
- Changed community review polling for normal users to avoid a user-visible 403 console error; non-reviewers now receive an empty friendly payload.
- Changed missing root trading report snapshots from HTTP 503 to a normal not-ready JSON state so the page does not surface resource errors during expected snapshot warmup.
- Fixed mobile trading indicator controls and economy subtabs so they no longer overflow horizontally.
- Added missing accessible labels to trading and other visible select/input controls that only had nearby visual text.

## Verification
- `timeout 240s python3 /tmp/hackme_full_ux_probe.py`
  - Result: `failures=0`
  - Coverage: root desktop/mobile and test desktop/mobile across chat, profile, announcements, community, drive, albums, videos, games, experiments, jobs, shares, comfyui, economy, trading, accounts, and server modules.
- `node --check public/js/20-chat.js`
- `node --check public/js/50-admin.js`
- `node --check public/js/25-community.js`
- `node --check public/js/10-users.js`
- `python3 -m py_compile server.py routes/public.py routes/community.py routes/trading.py`
- `git diff --check`

## Remaining Notes
- The audit server intentionally runs in an isolated `/tmp` runtime and should not be treated as production data.
- One unrelated dirty file was already present during this pass: `scripts/games/chess_exp6_v7_3_ranking.py`.
