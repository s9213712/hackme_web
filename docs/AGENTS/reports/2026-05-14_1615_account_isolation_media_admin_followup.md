# Account Isolation Follow-up: Media Shares and Admin Surfaces

Date: 2026-05-14 16:15 Asia/Taipei

## Trigger

User reported that the `admin` account could revoke media shared by `test`, raising concern that account isolation was incomplete.

## Confirmed Root Cause

Several private user-data surfaces treated `manager/admin` as equivalent to the resource owner. That made management accounts able to see or operate another user's personal resources outside explicit moderation/root-only workflows.

Confirmed affected areas:

- Media videos: `can_edit`, private/unlisted video reads, share-link update/revoke, stream preparation.
- Share center: `?all=1` listed all shares for manager/admin, and revoke/access-events accepted manager/admin for other owners.
- Cloud drive: file status, E2EE key listings, download/preview, E2EE share revoke, attaching existing files, soft delete, announcement attachment request.
- Cloud drive context refs and remote downloads: manager/admin could see or remove other users' refs/tasks.
- Job center: manager/admin could read/cancel/retry all jobs via `/api/admin/jobs`.

## Fixes Applied

- Media video ownership is now owner-scoped for edit/share/stream-preparation operations.
- Share center now always returns only the current user's shares. `all=1` is ignored for this personal center.
- Share revoke/access-events are owner-only for file, album, and video shares.
- Cloud drive personal file operations are owner/grant scoped. Manager/admin no longer bypasses owner checks for private files.
- Remote download task status/removal and context attachment refs are owner/grant scoped.
- Job center uses `/api/jobs` for non-root users. `/api/admin/jobs` is now root-only.
- Frontend platform center no longer asks for all shares or all jobs unless the user is root.
- Removed dead manager/root helper code from updated media/share/job routes to reduce future confusion.

## Deliberately Not Changed

Explicit moderation and system administration surfaces were left intact when they are designed as moderation/root workflows, for example community moderation, report/appeal handling, user administration, and system admin dashboards. Those are not personal resource centers.

## Verification

Targeted tests:

```bash
PYTHONPATH=/home/s92137/hackme_web python3 -m pytest \
  /home/s92137/hackme_web/tests/video/api/test_video_permission.py \
  /home/s92137/hackme_web/tests/video/api/test_video_publish.py \
  /home/s92137/hackme_web/tests/video/streaming/test_video_streaming.py::test_media_prepare_stream_route_requires_owner \
  /home/s92137/hackme_web/tests/video/streaming/test_video_streaming.py::test_manager_cannot_update_another_users_unlisted_share_link \
  /home/s92137/hackme_web/tests/share/test_share_management_access_events.py \
  /home/s92137/hackme_web/tests/storage/test_cloud_drive_attachments.py::test_dm_upload_enters_owner_drive_and_grants_counterparty_download \
  /home/s92137/hackme_web/tests/storage/test_cloud_drive_attachments.py::test_e2ee_share_and_revoke_controls_download_grant \
  /home/s92137/hackme_web/tests/storage/test_cloud_drive_attachments.py::test_remote_download_tasks_are_owner_scoped_for_manager \
  /home/s92137/hackme_web/tests/platform/test_job_center.py \
  /home/s92137/hackme_web/tests/frontend/test_platform_centers_frontend.py
```

Result: `25 passed in 1.54s`.

Additional checks:

```bash
node --check /home/s92137/hackme_web/public/js/57-platform-centers.js
git -C /home/s92137/hackme_web diff --check -- <touched isolation files>
```

Result: passed.
