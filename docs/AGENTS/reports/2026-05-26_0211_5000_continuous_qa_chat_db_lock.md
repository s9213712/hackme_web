# 2026-05-26 02:11 +08:00 - :5000 Continuous QA: Chat Create DB Lock

## Finding

### P1 - Chat room creation could return 500 during concurrent writes
- Evidence: `/tmp/hackme_web_goal_qa_20260526_0207/system_stress/stress.json`
- Trigger: the stress seed uploaded drive/video fixtures, then created a chat room while background/media writes were still active.
- Runtime log:
  - `chat_room_create_failed user_id=3 username=test error=database is locked`
  - `POST /api/chat/rooms HTTP/1.1" 500`
- Impact: users could see a generic chat creation failure under normal concurrent site activity even though the request payload was valid.

## Fix
- Updated `routes/chat.py` chat-room creation transaction from deferred `BEGIN` to `BEGIN IMMEDIATE`.
- Reason: acquire the SQLite write lock before validation and inserts do additional DB work, so busy timeout can wait instead of failing mid-transaction at `INSERT`.

## Verification
- `python3 -m py_compile routes/chat.py`
- `python3 -m pytest tests/frontend/chat/test_frontend_chat.py tests/community/test_chat_permissions.py -q`
- Live reload:
  - copied `routes/chat.py` into the active `:5000` run root
  - `kill -HUP 211291`
  - confirmed `/api/version` OK
- Re-ran the same live stress profile:
  - `/tmp/hackme_web_goal_qa_20260526_0207/system_stress/stress_after_chat_fix.json`
  - `seed.chat_room.status=200`
  - total ops `190`
  - hard failures `0`
  - server busy `0`
  - p95 `146.548 ms`
- Log scan after reload found no new `chat_room_create_failed`, `database is locked`, `Traceback`, or HTTP `500` entries in the recent tail.

## Additional Coverage
- Member probe:
  - `/tmp/hackme_web_goal_qa_20260526_0207/member_probe/member_probe.json`
  - findings `0`
  - covered login, storage uploads/previews, E2EE reject behavior, share links, album share password flow, remote download guards, video upload/HLS/password playback, unsupported video privacy mode, trading grid fee math.
- Live stress:
  - accounts: `test`, `admin`, `root`
  - 18 logical users, 180 requested operations, concurrency 12
  - covered version/me/jobs/notifications, cloud drive, video/HLS, share management, ComfyUI quote/status, rejected remote/BT requests, trading markets/dashboard/grid preview, games, community, chat, bad login.
