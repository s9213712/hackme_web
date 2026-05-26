# 2026-05-26 02:06 +08:00 - :5000 Bug Report Review Reward And Announcement Draft

## Scope
- User request: bug report rewards must be manually set by root, and announcement publishing must open an editable draft before posting.
- Target live server: `https://127.0.0.1:5000`
- Live root: `/tmp/hackme_web_accept_20260526_server_mode_prelaunch_update_card/hackme_web`

## Changes
- `routes/bug_reports.py`
  - Approving a bug report now rejects requests that omit `reward_points`.
  - `reward_points=0` remains valid, meaning root approves the report but waives the reward.
- `public/js/50-admin.js`
  - Root bug report detail now has an editable announcement draft panel.
  - Publishing an announcement reads the root-edited title/body/pinned state from the draft.
  - Removed the direct canned announcement flow.
  - Trading bot audit bug-report shortcut now asks root for a reward amount before approval.
- `public/index.html`
  - Updated the admin JS cache-bust query so the live page loads the new UI.

## Verification
- `node --check public/js/50-admin.js`
- `python3 -m py_compile routes/bug_reports.py`
- `python3 -m pytest tests/regressions/test_bug_reports.py tests/frontend/admin/test_root_bug_report_admin.py -q`
- `curl -k -sS https://127.0.0.1:5000/api/version`
- Live API check:
  - Created temporary bug report as `test`.
  - Root approve without `reward_points` returned HTTP 400 with the new manual reward requirement message.
  - Temporary QA report was rejected afterward to avoid leaving it pending.

## Live Apply
- Copied updated files into the active `:5000` run root.
- Reloaded gunicorn master PID `211291` with `HUP`.
- Confirmed `:5000` is listening with 4 workers and `/api/version` returns OK.
