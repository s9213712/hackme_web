# 2026-05-26 03:46 :5000 Chat Audit And DB Lock QA

Scope: live QA on `https://127.0.0.1:5000` during the social/community pass.

## Findings

- Successful chat actions were being written to secure audit with `success=false` because `audit()` defaults to failure unless callers pass `success=True`.
- Chat room creation could return `500 chat_room_create_failed` during concurrent storage/video/trading writes when SQLite raised a transient `database is locked` inside the create-room transaction.

## Fixes

- Updated `routes/chat.py` so successful chat room, invite, report, edit, recall, delete, friend request/review/remove/block/unblock events explicitly write successful audit state.
- Added transaction-level retry for chat room creation. A transient SQLite lock now rolls back the whole room-create transaction and retries. Persistent lock contention returns `503 server_busy` with retry metadata instead of a generic 500.
- Added regression tests in `tests/community/test_chat_permissions.py` for successful audit flags, transient lock retry, persistent lock 503, and no duplicate room creation after retry.

## Verification

- `python3 -m py_compile routes/chat.py tests/community/test_chat_permissions.py`
- `python3 -m pytest tests/community/test_chat_permissions.py -q`
- `git diff --check -- routes/chat.py tests/community/test_chat_permissions.py`

Live `:5000` verification:

- Reloaded gunicorn master `211291` with `HUP`.
- Created `qa-db-lock-retry-0342` as `test`; API returned `200`.
- Audit log now shows `CHAT_ROOM_CREATED` for that room with `success:true`.
- `/api/root/points/financial-invariants` still reports `ok:true`, `status:"pass"`, and all financial invariants passing.

Residual note:

- Older audit rows before this fix still show `CHAT_ROOM_CREATED success:false`; they are historical data and were not rewritten.
