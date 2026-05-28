# Social Read Load Optimization

Date: 2026-05-28

Scope:

- Chat rooms/messages
- Notifications
- Community announcements
- Forum category / board / thread reads

Changes:

- Chat room lists aggregate visible-room member counts in one SQL pass.
- Chat message reads now accept `after_id` / `before_id` cursors and return
  cursor metadata. Frontend chat polling uses `after_id` deltas and periodically
  falls back to a full refresh. Delta polls request compact room metadata so
  member-count aggregation is skipped during high-frequency polling.
- Notification polling uses `/api/notifications/unread-count` while the panel is
  closed; the full notification list is loaded only when the panel is opened or
  explicitly forced. Unread-count queries have a composite
  `(user_id, is_read, dismissed_at)` index.
- Announcement list reads emit ETag and can return `304 Not Modified`; the
  frontend revalidates with `If-None-Match` and reuses the current list on 304.
- Forum category board counts and board thread/post counts use grouped queries
  rather than per-row count loops.
- Board thread lists batch reply counts and reaction counts for the returned
  page.
- Thread detail replies are bounded by `posts_page` / `posts_limit` and return
  `posts_total`, `posts_limit`, and `posts_has_more`.
- The forum frontend renders a "load more replies" action when a bounded thread
  response has additional reply pages, then appends the next page without
  replacing the already displayed replies.
- Current community schemas backfill the new read-load indexes opportunistically
  and tolerate transient SQLite lock/busy errors on read requests.

Validation:

- `python3 -m py_compile routes/chat.py routes/community.py routes/reports_notifications.py services/system/notifications.py tests/community/test_chat_permissions.py tests/community/test_community_permissions.py`
- `node --check public/js/20-chat.js`
- `node --check public/js/25-community.js`
- `node --check public/js/32-notifications.js`
- `pytest -q tests/community/test_chat_permissions.py`
- `pytest -q tests/community/test_community_permissions.py tests/community/test_community_board_counts.py tests/community/test_reports_notifications.py tests/community/test_dm_routes.py`
- `pytest -q tests/platform/test_notification_center_schema.py tests/frontend/chat/test_frontend_chat.py tests/frontend/chat/test_frontend_notifications.py tests/frontend/community/test_frontend_community_layout.py tests/frontend/community/test_frontend_governance.py`
- `pytest -q tests/platform/test_release_policy.py tests/scripts/prepush/test_prepush_v2.py`
- `git diff --check`
- No residual HLS/realtime proxy stress worker process was found after this
  pass.

Remaining architecture items:

- Chat export is still a synchronous JSON export. It should become an async
  export job before very large rooms are offered as a customer-facing feature.
- Live chat at higher concurrency should move from polling to SSE/WebSocket or a
  shared message fanout layer.
- Forum search is still LIKE-based. Large deployments should add FTS or an
  external search index.
