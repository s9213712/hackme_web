# Video Platform v1

Video Platform v1 is a display and interaction layer on top of the existing
Cloud Drive. It does not create a second storage system.

For the shorter deployer-facing summary, start with
[05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md) and
[04_USER_GUIDE.md](04_USER_GUIDE.md). This file keeps the detailed module
reference.

The formal large-media HLS / segmented streaming design is documented in
[VIDEO_STREAMING_ARCHITECTURE.md](VIDEO_STREAMING_ARCHITECTURE.md). Video
Platform v1 is still the user-facing baseline, but Phase C-1 foundation is now
implemented for prepared HLS playback, automatic stream preparation on eligible
published media, and manual retry controls in the watch page.
For the runtime trust boundary between `server_encrypted` and strict `e2ee`,
see [ENCRYPTION_RUNTIME_BOUNDARY.md](ENCRYPTION_RUNTIME_BOUNDARY.md).

## Architecture

- Cloud Drive is the storage layer.
- `videos` metadata is the presentation layer.
- PointsChain is the economic layer for tips.
- Server Mode / feature flags control whether the module is exposed.

## Feature Flag

The module is controlled by:

```text
feature_videos_enabled
module_videos_min_role
```

When disabled, `/api/videos*` is blocked by the same feature gate used by other
optional modules.

## User Flow

1. User uploads a video file through Cloud Drive.
2. User opens the `影音` page.
3. User selects one of their own Cloud Drive video files and publishes it.
4. Other users can watch public videos, open unlisted videos by link, or only
   view private videos when they are the owner or a manager/root account.
5. Logged-in users can like, comment, and tip.

## Cloud Drive Rules

Publishing uses `cloud_file_id` only.

The server never exposes `storage_path` to the browser. Playback goes through:

```text
GET /api/videos/<id>/stream
```

Prepared stream assets can now also be served through:

```text
POST /api/media/<file_id>/prepare-stream
GET  /api/media/<file_id>/stream-status
GET  /api/videos/<id>/playback
GET  /api/videos/<id>/hls/master.m3u8
GET  /api/videos/<id>/hls/<variant>/playlist.m3u8
GET  /api/videos/<id>/hls/<variant>/<segment>
```

Current playback behavior:

- public / unlisted video publishes now try to prepare an HLS derivative
  automatically
- `server_encrypted` media also try to prepare HLS automatically so playback
  does not stay on the whole-file decrypt path
- owners and manager/root accounts can re-run stream preparation from the video
  watch page when a derivative is still pending or failed
- Safari keeps native HLS playback
- desktop Chrome / Firefox / Edge use a same-origin `hls.js` bundle for
  prepared HLS playback
- if `hls.js` fails to initialize or hits a fatal playback error, the player
  falls back to direct `/stream` with a user-visible warning
- strict `e2ee` media stay on browser-side decryption and do not use
  server-side HLS; when the owner publishes an unlisted E2EE video, the
  browser re-wraps the file key into a share envelope and stores the fragment
  key only in the URL fragment / local session state
- the video detail page now includes a share-management panel for unlisted
  videos, showing link state, remaining views, expiry, second-layer password
  status, fragment-loss warnings, and copy / regenerate / revoke controls

The stream endpoint resolves the file with the existing Cloud Drive safe path
resolver, so path traversal, absolute paths, and storage-root escape are handled
by the Cloud Drive safety layer.

Rules:

- Only the file owner can publish a Cloud Drive file.
- The file MIME type must start with `video/`.
- E2EE files cannot be published as normal server-streamed videos.
- E2EE files can be published as `持連結可看` shared videos when the browser
  creates a wrapped share envelope at publish time.
- The server never accepts `raw_file_key`, `e2ee_password`, or the fragment
  key `vk`.
- Blocked or quarantined files cannot be published.
- Private videos require owner or manager/root access.
- Unlisted videos are not listed publicly but can be opened by direct link.

## PointsChain Tips

Tips use PointsChain and do not directly update wallet balances.

For each tip:

1. Viewer wallet gets a PointsChain debit.
2. Uploader wallet gets a PointsChain credit for the net amount.
3. The official fee account (`root`) gets a PointsChain credit for the platform fee.
4. The request can provide an idempotency key to avoid double-spend on retry.

`video_tips` records `fee_points`, `fee_user_id`, `ledger_debit_uuid`,
`ledger_credit_uuid`, and `ledger_fee_uuid`, so the gross payment, uploader
revenue, and official platform fee can all be audited from PointsChain.

Current setting:

```text
video_tip_fee_percent
video_tip_min_points
```

## API

```text
POST   /api/videos/publish
POST   /api/videos/upload
PUT    /api/videos/<id>/share-link
DELETE /api/videos/<id>/share-link
GET    /api/videos?sort=new|hot|trending&page=1
GET    /api/videos/<id>
POST   /api/media/<file_id>/prepare-stream
GET    /api/media/<file_id>/stream-status
GET    /api/videos/<id>/playback
GET    /api/videos/<id>/cover
GET    /api/videos/<id>/stream
GET    /api/videos/<id>/hls/master.m3u8
GET    /api/videos/<id>/hls/<variant>/playlist.m3u8
GET    /api/videos/<id>/hls/<variant>/<segment>
POST   /api/videos/shared/<token>/unlock
GET    /api/videos/shared/<token>
GET    /api/videos/shared/<token>/playback
GET    /api/videos/shared/<token>/e2ee-key
GET    /api/videos/shared/<token>/ciphertext
POST   /api/videos/<id>/view
POST   /api/videos/<id>/like
DELETE /api/videos/<id>/like
GET    /api/videos/<id>/comments
POST   /api/videos/<id>/comments
POST   /api/videos/<id>/comment
POST   /api/videos/<id>/tip
```

State-changing requests require CSRF through the shared `apiFetch()` wrapper.

Server-encrypted media note:

- If the current server file key cannot decrypt an older `server_encrypted`
  asset, `/api/videos/<id>/cover` returns an explanatory SVG placeholder and
  `/api/videos/<id>/stream` returns HTTP `409` with
  `error=decrypt_unavailable`. Re-upload the media after the key rotation/reset
  if playback is still required.

## Tables

```text
videos
video_views
video_likes
video_comments
video_tips
```

These tables are reset with runtime data and are covered by snapshot/restore
because the database snapshot includes application tables. Video metadata is
also included in the Cloud Drive metadata checkpoint hash.

## Security Tests

Run:

```bash
security/run_pentest.sh --only video-module
```

The script validates:

- owner-only Cloud Drive publish
- non-video MIME rejection
- private video access control
- comment XSS rejection
- watch-count dedupe
- PointsChain tip debit/credit
- idempotency against double spend
- insufficient-balance rejection

## hls.js Vendor

- Local bundle: `public/js/vendor/hls.light.min.js`
- Upstream: `hls.js`
- Version: `1.6.15`
- License: `BSD-3-Clause`
- Purpose: desktop Chrome / Firefox / Edge HLS fallback without a third-party
  CDN dependency at playback time; Safari still prefers native HLS.

Pytest coverage:

```text
tests/test_video_publish.py
tests/test_video_permission.py
tests/test_video_tips.py
tests/test_video_comments.py
tests/test_video_security.py
```

## Release Blockers For Streaming

Do not release a streaming build if any of the following are still broken:

- Safari native HLS playback regresses for prepared HLS media.
- Desktop Chrome / Firefox / Edge cannot initialize the local `hls.js`
  fallback for prepared HLS media.
- `hls.js` failure states do not fall back to direct `/stream` with a
  user-visible error.
- Strict `e2ee` playback accidentally tries to send `vk`, raw file keys, or
  original E2EE passwords to the server.
- The E2EE share-management panel fails to show share state, remaining views,
  password lock state, or expiry/max-view controls for unlisted videos.
- Fragment-loss messaging is unclear or implies the server can recover `#vk`.
- Shared strict `e2ee` pages do not clearly state that fragment loss is
  unrecoverable and requires share regeneration.
- Mobile playback UI overflows or hides the actionable error / fallback state.

## Explicit Non-Goals For v1 / Phase C-1

- No multi-bitrate ABR ladder yet.
- Auto-prepare is currently synchronous/best-effort, not a queued worker yet.
- No CDN.
- No recommendation algorithm.
- No subscription/follow system.
- No livestreaming.
- No advertising revenue split.

Current note:

- HLS-based large-media streaming is no longer only a paper design. Phase C-1
  provides prepare/status/playback/HLS routes and derivative packaging for
  plain or `server_encrypted` video, but direct `/stream` remains the fallback.
  Strict `e2ee` still stays non-streamable on the server side and instead uses
  browser-side decryption with a wrapped share key when published as an
  unlisted shared video.
