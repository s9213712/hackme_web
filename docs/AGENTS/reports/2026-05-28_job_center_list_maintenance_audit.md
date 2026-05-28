# Job Center List Maintenance Audit

## Finding

`GET /api/jobs` and `GET /api/admin/jobs` were still doing bounded write-side
maintenance on every list read: stale cloud remote-download expiration,
resumable-upload expiration, media HLS expiration, and terminal job purge. Each
operation was individually bounded, but visible Job Center polling could still
multiply these writes across users and root/admin pages.

## Change

- Added process-local rate limiting around Job Center list maintenance.
- Kept the first list read able to recover stale rows, then skipped repeated
  sweeps inside `HACKME_JOB_LIST_MAINTENANCE_INTERVAL_SECONDS` (default `30`).
- Added `maintenance` response metadata with run/skip reason and cleanup
  counts.
- Allowed root to force a sweep with `maintenance=1` or `sweep=1`; normal users
  cannot force global maintenance from their personal list API.
- Updated API/developer docs to keep Job Center list polling observational.
- Added `limit` / `offset` pagination to `GET /api/cloud-drive/refs`, so a
  single chat/forum/announcement context cannot force unbounded attachment
  hydration and per-row permission checks.
- Bounded chat send fanout. Group notifications are capped by
  `HACKME_CHAT_NOTIFICATION_FANOUT_LIMIT`, and attachment grant creation now
  rejects over-limit rooms with `chat_attachment_grant_fanout_too_large` instead
  of inserting unbounded per-member grants in the send path.
- Bounded chat room export to latest-page slices with `pagination.next_before_id`
  so full history export can be explicit iteration instead of one large
  request.
- Reused the Security Center audit-chain integrity result across readiness,
  anomaly, and audit summary sections to remove duplicate verification scans in
  a single `/api/admin/security-center` response. Security Center readiness also
  uses the schema-only DB summary instead of running SQLite `quick_check`.
- Changed fast `/api/admin/health` to reuse one audit-chain result and pass a
  schema-only DB summary into readiness. Full SQLite `quick_check` /
  `foreign_key_check` stays on `/api/admin/health/db-integrity`.
- Replaced root/admin log-tail `readlines()[-N:]` paths with bounded
  `deque(maxlen=N)` tail reads for security test jobs, Security Center server
  logs, and server-output fallback logs.

## Verification

- `python3 -m py_compile routes/jobs.py tests/platform/test_job_center.py`
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest -q /home/s92137/hackme_web/tests/platform/test_job_center.py`
- `python3 -m py_compile routes/files.py tests/storage/test_cloud_drive_attachments.py`
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest -q /home/s92137/hackme_web/tests/storage/test_cloud_drive_attachments.py -k refs`
- `python3 -m py_compile routes/chat.py tests/community/test_chat_permissions.py`
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest -q /home/s92137/hackme_web/tests/community/test_chat_permissions.py -k "fanout or official_chat_message or export_is_paginated"`
- `python3 -m py_compile routes/system_admin.py tests/security/integrity/test_health_center.py`
- `python3 -m py_compile routes/system_admin_sections/security_routes.py`
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest -q /home/s92137/hackme_web/tests/security/integrity/test_health_center.py -k "security_center_reuses_audit_integrity_result or fast_admin_health_reuses_audit"`

## Residual Risk

This is process-local throttling, not a cross-worker distributed lock. In a
multi-worker deployment, each worker may run one sweep per interval. That is
still a large reduction from per-request maintenance and keeps the change local
to the existing SQLite-backed Job Center design.
