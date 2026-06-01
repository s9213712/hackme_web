# 2026-06-01 Storage root and video streaming fix

## Scope

This change addresses two related production issues:

- Changing the cloud-drive storage root could leave existing database records pointing at files that were only present under the old root.
- Video playback advertised direct, realtime proxy, or HLS options even when the backing source file or HLS derivative files were missing.

## Root cause

Uploaded files and HLS derivatives are stored as relative paths in the database. When the effective storage root changes, those relative paths are resolved under the new root. If the old root contents are not copied first, existing records still exist but the physical files are missing at the new root.

The visible symptoms were:

- Basic direct streaming reported browser decode/load error code 4 after receiving an invalid or missing source.
- Standard realtime proxy could report HTTP 404 when the original source file was not present under the active storage root.
- Prepared HLS could fail because a database asset was marked ready while the master or variant playlist files were missing.
- Missing HLS variant playlists could raise a server 500 instead of a clean missing-file response.

## Fixes

- Added `services.storage.migration.sync_storage_root_contents`.
- The root system setting flow now copies existing files from the current storage root into the new storage root before saving `cloud_drive_storage_root`.
- The migration copies only missing files and keeps the old root intact.
- Upload temp directories such as `.upload_tmp` are skipped during storage-root migration.
- Playback payload generation now checks that the original source file exists before advertising direct or realtime proxy playback.
- Playback payload generation now checks that HLS master, variant playlists, audio-track playlists, and subtitles exist before advertising prepared HLS assets.
- HLS master, subtitle, and storage file responses now return clean JSON 404 errors when the physical file is missing instead of throwing `FileNotFoundError`.
- Realtime proxy random seek now uses an absolute MSE timeline with `SourceBuffer.timestampOffset`, so native video controls keep the full-video timeline.

## Operational note

Changing the storage root remains a restart-required operation for the running server process. The new behavior prevents data loss by copying files before the setting is saved, but the active process still uses the storage root that was loaded at startup until restart.

For the current deployment, a one-time sync was also run:

```text
source: /tmp/hackme_web_review_20260531_174845/runtime/storage
target: /mnt/d/temp/hackme_web_storage
copied_files: 87
copied_bytes: 215880160
```

## Playback test notes

The Scarlet long-video test asset was used for three-mode playback and random seek checks.

```text
video_id: 8
duration_seconds: 6677.713
seek_targets: 1117.62, 1490.84, 1597.14
```

Latest recorded three-mode results before the storage-root guard changes:

```text
direct: passed, startup 762 ms, seek waits 2244.3 / 2190.5 / 2314.8 ms, dropped 0
realtime_proxy: passed, startup 567 ms, seek waits 2791.7 / 2666.0 / 2796.7 ms, dropped 0
prepared_hls: passed, startup 457 ms, seek waits 2243.5 / 2214.4 / 2200.3 ms, dropped 0
```

Realtime absolute timeline check:

```text
timeline_mode: absolute
duration_seconds: 6677.713
timestampOffset applied: true
buffer ranges after seek: absolute seconds
```

## Expected behavior after this change

- If the source file is missing, direct and realtime proxy are not advertised as available in the playback payload.
- If HLS files are missing, prepared HLS is not advertised as available in the playback payload.
- If a client still requests a missing file directly, the server returns a clean 404 JSON error.
- Changing storage root from the admin settings copies existing files into the new root before persisting the new setting.
