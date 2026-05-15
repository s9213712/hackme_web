# 2026-05-15 Notification Polling Performance Hardening

## Findings

- No blocking regression found in this pass.
- No trading regression found: the hardening only changed notification polling, and the trading validation suite still passed all 21 checks.

## Change Verified

- `public/js/32-notifications.js`
  - Delays the first automatic notification fetch by 10 seconds after login.
  - Extends passive notification polling from 30 seconds to 60 seconds.
  - Skips passive polling while the document is hidden.
  - Adds an in-flight request guard so overlapping notification refreshes do not stack.
  - Keeps user-driven refresh immediate for opening the notification panel, read, read-all, and dismiss actions.

- `tests/frontend/chat/test_frontend_notifications.py`
  - Covers the notification hardening wiring so future edits do not silently remove the delayed/hidden-tab/concurrency behavior.

## Evidence

- `node --check /home/s92137/hackme_web/public/js/32-notifications.js`: pass.
- `pytest -q /home/s92137/hackme_web/tests/frontend/chat/test_frontend_notifications.py`: pass, 1 test.
- `python3 /home/s92137/hackme_web/scripts/trading/validation/trading_exchange_validation.py`: pass, 21 checks.
- `python3 /tmp/hackme_perf_audit.py > /tmp/hackme_perf_audit_notification_harden_20260515.json`: pass.
- `git -C /home/s92137/hackme_web diff --check`: pass.

Playwright perf artifact:

- JSON: `/tmp/hackme_perf_audit_notification_harden_20260515.json`
- Runtime root: `/tmp/hackme_web_perf_audit_20260515_113324_4033004`

Key Playwright metrics from the saved JSON:

- Static script count: 25.
- Static script bytes: 1,744,427.
- Notification script bytes: 6,914.
- Initial authenticated API resource count: 5.
- After 6.5 seconds idle API resource count: 5.
- Initial live intervals: `[15000, 60000, 60000, 1000]`.
- Trading module API resource count during switch: 3.
- Trading module timers remained present, including active trading refresh intervals.
- Console errors: none.
- Page errors: none.
- Server log findings: none.

## Notes

- The startup path no longer includes an immediate notification API fetch. The first passive fetch is delayed, and manual notification UI actions still force an immediate refresh.
- This pass intentionally did not lazy-load or alter `public/js/56-trading.js`, because trading page timers and trading background calculations must not be weakened by frontend load reduction work.
- Existing unrelated `server.py` processes were observed after the audit command, but the isolated Playwright audit process completed and returned normally; no unrelated process was stopped.
