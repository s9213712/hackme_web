# Video Streaming Architecture

This document is the formal Phase C streaming design for large media playback.
It is a canonical engineering reference, not a research draft.

Read this after:

- [VIDEO_PLATFORM.md](VIDEO_PLATFORM.md)
- [WEB.md](../WEB.md)
- [For_developer.md](../For_developer.md)

Current status:

- Video Platform v1 is implemented.
- Phase C-1 HLS streaming foundation is implemented here.
- Public/unlisted video publishes and `server_encrypted` media now try to
  prepare HLS derivatives automatically, while owners can manually retry
  preparation from the watch page.
- Later Phase C stages are still not fully implemented yet.

## Problem Statement

The current platform can already stream plain media with HTTP range support, but
large files still show noticeable startup delay in one important path:

- `standard_plain`: direct file streaming is acceptable for small and medium
  media.
- `server_encrypted`: the current implementation decrypts the entire file into
  memory before range slicing, which creates large startup latency and memory
  pressure for big video and audio files.
- `e2ee`: the server cannot safely decrypt plaintext, so it cannot transparently
  transcode or package a normal server-side streaming derivative. E2EE videos
  may still be published as `持連結可看` browser-side decrypted shares, but that
  path remains distinct from HLS.

Because of these constraints, browser-side buffering alone is not enough.

## Goals

Phase C should provide:

1. Lower startup latency for large video playback.
2. Seek behavior that does not require full-file decrypt first.
3. Adaptive streaming support for long/high-bitrate videos.
4. A formal split between:
   - user-private source files
   - server-streamable derivatives
   - strict E2EE files
5. A storage/layout model that stays compatible with snapshot/restore, quota,
   audit, and access control.

## Non-Goals

Phase C does not automatically mean:

- livestreaming
- LL-HLS / WebRTC
- full CDN integration on day one
- E2EE files becoming transparently streamable by the server
- replacing all direct file preview with HLS

Small media can continue using direct HTTP range streaming where it remains
simpler and cheaper.

## Current Baseline

Today:

- Cloud Drive preview for plain audio/video uses direct preview URLs.
- Video Platform v1 streams media through `/api/videos/<id>/stream`.
- E2EE files are intentionally blocked from server-streamed video publishing.
  They may instead use browser-side share playback with a wrapped file key
  envelope and a fragment-held viewer key.
- `server_encrypted` files can be streamed, but the current path is expensive
  for large files because it decrypts the whole object before serving ranges.
- Phase C-1 already adds:
  - `POST /api/media/<file_id>/prepare-stream`
  - `GET /api/media/<file_id>/stream-status`
  - `GET /api/videos/<id>/playback`
  - `GET /api/videos/<id>/hls/master.m3u8`
  - `GET /api/videos/<id>/hls/<variant>/playlist.m3u8`
  - `GET /api/videos/<id>/hls/<variant>/<segment>`
- Current implementation packages a single prepared HLS variant and lets the
  frontend prefer native-HLS playback when the derivative is ready. Browsers
  without native HLS support still fall back to `/api/videos/<id>/stream`.
- Auto-prepare is currently best-effort and synchronous in the publish path.
  A failed derivative must not block the base video publish action.

This design keeps those v1 rules, but adds a media-derivative pipeline for
larger assets.

## Why HLS

Normal large streaming platforms usually do not rely on a single giant `mp4`
response. The common pattern is:

- package video into many short segments
- provide a playlist manifest
- let the player fetch only the next few segments
- optionally switch bitrate based on current network conditions

For this project, the default target should be:

- HLS
- CMAF / fragmented MP4 segments (`.m4s`)
- multiple quality variants for larger videos

This gives better startup behavior, easier seeking, and a cleaner long-term path
to CDN or cache acceleration.

## Mode Matrix

### `standard_plain`

Allowed:

- direct range preview
- HLS derivative generation
- direct Cloud Drive download

Recommended behavior:

- keep direct range playback for small media
- generate HLS derivatives for large published video

### `server_encrypted`

Allowed:

- server-side decrypt in controlled jobs
- server-generated HLS derivative pipeline

Required change:

- do not keep the current "decrypt whole file, then slice" model for large
  playback
- instead, generate and serve streamable derivatives

Recommended behavior:

- decrypt inside a background worker
- transcode / package to HLS
- store the resulting derivatives in server-controlled protected storage
- serve segments with per-request ACL checks

### `e2ee`

Not allowed:

- transparent server-side transcoding of the original file
- normal server-side HLS from the original ciphertext

Recommended product rule:

- strict E2EE files remain non-publishable for server-streamed video / HLS
- unlisted E2EE video shares may use browser-side decryption only:
  - owner enters the original E2EE password once at publish time
  - browser unwraps the original file key locally
  - browser generates a random 256-bit share key
  - browser re-wraps the file key with AES-GCM and stores only the wrapped
    envelope on the server
  - the share key travels only in the URL fragment `#vk=...`
- if the user wants platform-grade HLS / ABR streaming, they must explicitly
  create a separate streamable derivative with weaker privacy semantics such as
  `server_encrypted`

That keeps the original E2EE promise intact instead of silently downgrading
security while still allowing users to share E2EE media.

## Storage Model

Derivatives should live under the existing runtime storage root, not in a new
top-level filesystem namespace.

Recommended layout:

```text
runtime/storage/media_derivatives/<uploaded_file_id>/
  master.m3u8
  1080p/
    playlist.m3u8
    init.mp4
    seg_00001.m4s
    seg_00002.m4s
  720p/
    playlist.m3u8
    init.mp4
    seg_00001.m4s
```

This keeps:

- snapshot/restore compatibility
- storage quota accounting compatibility
- predictable cleanup behavior
- one canonical storage root

## Data Model

Recommended new tables:

### `media_stream_assets`

- `id`
- `uploaded_file_id`
- `source_mode`
- `status`
- `master_manifest_path`
- `duration_seconds`
- `created_at`
- `updated_at`

### `media_stream_variants`

- `asset_id`
- `name`
- `width`
- `height`
- `bitrate`
- `codec`
- `playlist_path`

### `media_stream_segments`

- `variant_id`
- `sequence_number`
- `path`
- `duration_seconds`
- `byte_size`

### `media_stream_jobs`

- `asset_id`
- `job_type`
- `status`
- `started_at`
- `finished_at`
- `error_message`

## Pipeline

### Ingest and Preparation

1. User uploads or publishes a media file.
2. Server inspects metadata with `ffprobe`.
3. Policy decides whether the media should remain direct-only or get a stream
   derivative.
4. If needed, a background job creates HLS output.

Suggested initial thresholds:

- file size over `200 MB`
- or duration over `10 minutes`
- or bitrate above a configurable threshold

### Derivative Build

For streamable assets:

1. open source file
2. decrypt if `server_encrypted`
3. transcode / package with `ffmpeg`
4. emit:
   - master playlist
   - variant playlists
   - CMAF init + media segments
5. write derivative metadata into DB
6. mark stream asset ready

### Playback

When a client opens a video page:

1. server resolves ACL
2. server chooses playback mode:
   - `direct`
   - `hls`
   - `unavailable`
3. frontend uses:
   - native `<video>` for direct mode
   - `hls.js` or native HLS support for HLS mode

## API Shape

Implemented baseline:

### Preparation and status

```text
POST /api/media/<file_id>/prepare-stream
GET  /api/media/<file_id>/stream-status
```

### Video playback description

```text
GET /api/videos/<id>/playback
```

Current baseline response:

```json
{
  "ok": true,
  "mode": "hls",
  "master_url": "/api/videos/123/hls/master.m3u8",
  "fallback_url": "/api/videos/123/stream",
  "source_mode": "server_encrypted"
}
```

### HLS routes

```text
GET /api/videos/<id>/hls/master.m3u8
GET /api/videos/<id>/hls/<variant>/playlist.m3u8
GET /api/videos/<id>/hls/<variant>/<segment>
```

## Encryption Strategy

### Plain media

- store plain source file as today
- generate plain or access-controlled HLS derivative

### Server-encrypted media

Short answer:

- decrypt in the background worker
- never require whole-file decrypt during end-user playback

Recommended derivative policy:

- original upload remains `server_encrypted`
- derivative segments are stored in protected server-side storage
- derivative access remains ACL-gated

If stronger at-rest protection is still required for derivatives, use a
segment-friendly server-side encryption scheme:

- fixed-size segments
- each segment independently encryptable/decryptable
- metadata keeps nonce/tag per segment

That allows on-demand decrypt of only the requested segment instead of the full
asset.

### E2EE media

Do not pretend the server can safely package E2EE media into HLS while keeping
the same trust boundary.

Approved product paths should be:

1. keep the file strict E2EE and disallow server-streamed publishing
2. or let the user explicitly create a separate streamable derivative under a
   different privacy mode

This preserves the E2EE contract.

## Frontend Strategy

### Cloud Drive

- keep direct preview for small audio/video
- allow large video preview to switch to stream mode when a derivative exists

### Video Platform

- prefer HLS for large or prepared videos
- fall back to direct `/stream` only when no derivative exists

Suggested player behavior:

- start with poster + manifest fetch
- load first segments only
- let browser/player buffer forward naturally

## Operational Controls

Root-configurable knobs should include:

- enable/disable HLS derivative generation
- max simultaneous transcode jobs
- derivative segment duration
- bitrate ladder presets
- minimum file size / duration before HLS generation
- whether Cloud Drive preview may use derivatives
- whether users may create streamable derivatives from non-plain source modes

## Security Notes

- segment and manifest routes must reuse the same video/file ACL checks
- do not expose raw storage paths
- do not cache private content without scoped authorization
- signed URLs may be added later if CDN/front-cache support is needed
- audit should record derivative generation, playback mode, and privacy-mode
  transitions

## Rollout Plan

### Phase C-1

- metadata tables
- background media job
- plain-video HLS generation
- `server_encrypted` decrypt-and-package path
- video page playback decision route
- native-HLS-or-direct frontend fallback

### Phase C-2

- multi-variant ABR ladder
- explicit queue/backoff and retry policy
- remove any remaining whole-file decrypt bottlenecks from non-derivative
  playback paths

### Phase C-3

- Cloud Drive large-video preview can reuse stream derivatives
- derivative lifecycle cleanup and quota accounting
- optional `hls.js` support for non-native browsers

### Phase C-4

- explicit user flow for "create streamable derivative" from E2EE-adjacent
  content
- no silent downgrade of strict E2EE assets

## Acceptance Criteria

Phase C should not be considered complete until:

1. large video startup latency is materially lower than direct whole-file
   decrypt playback
2. seeking no longer implies full source decrypt for `server_encrypted` assets
3. E2EE behavior remains explicit and honest
4. derivative files are covered by snapshot/restore and cleanup rules
5. video ACL and private/unlisted rules still apply to all manifests and
   segments

## Related Documents

- [VIDEO_PLATFORM.md](VIDEO_PLATFORM.md)
- [WEB.md](../WEB.md)
- [For_developer.md](../For_developer.md)
- [12_TROUBLESHOOTING.md](../12_TROUBLESHOOTING.md)
