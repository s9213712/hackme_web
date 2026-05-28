# 2026-05-27 22:29 Multi-Audio Streaming Service Tiers

## Scope

- Target project: `hackme_web`
- Source requirement: handle MKV-style multi-language audio/subtitle media such
  as `/mnt/d/Scarlet.2025.1080p.NF.WEB-DL.DUAL.DDP5.1.H.264.MSubs-ToonsHub.mkv`
- Product requirement: keep three customer-selectable streaming paths with
  differentiated service fees, and apply the same handling to shared video /
  shared-file playback.
- Reference checked: `s9213712/lcd_OS`

## Implementation Summary

- Prepared HLS now stores video variants and alternate audio tracks in the
  stream metadata model. Audio tracks are generated as separate HLS playlists
  when the source has multiple audio streams or browser-unfriendly audio such
  as E-AC-3.
- Subtitle extraction now uses a configurable text-track limit, preserves forced
  subtitle metadata, and keeps WebVTT subtitle URLs in the playback payload.
- Normal video, shared video, Cloud Drive preview, and storage-share preview
  HLS routes can serve both video renditions and alternate audio playlists.
- Frontend playback controls for those surfaces now render audio-track
  selectors when multiple tracks are available.
- Playback payloads now include `service_policy` and fully structured
  `streaming_options` for Basic direct streaming, Standard realtime proxy, and
  Premium prepared HLS. Each option reports fee level, billing basis, cost
  drivers, advantages, tradeoffs, best-fit use cases, availability reason, and
  multi-audio / multi-subtitle support.
- Customer-facing service-tier documentation was added at
  `docs/video/VIDEO_STREAMING_SERVICE_TIERS.md`.

## Customer Service Tiers

| Tier | Customer name | Fee reason |
|---|---|---|
| Basic | Direct streaming | Lowest server work: read source file and send bytes. Compatibility depends on browser support. |
| Standard | Realtime proxy / transwrap | Per-viewer CPU work: selected audio can be transcoded live while video is copied when possible. |
| Premium | Prepared HLS | Worker CPU, derivative storage, cache lifecycle, multi-audio/subtitle packaging, and authorization on child resources. |

## lcd_OS Reference Value

`lcd_OS` is useful for the Standard route because it demonstrates a low-end
ffmpeg pipe design: seek with `-ss`, map one video stream, map the selected
audio stream, copy video where possible, transcode audio to AAC, and output
fragmented MP4 to stdout. That keeps RPi0-class hardware viable for one viewer,
but it does not replace prepared HLS for multi-viewer public/share playback.

## Verification

- `python3 -m py_compile` passed for modified backend Python modules and the
  video streaming test file.
- `pytest -q tests/video/streaming/test_video_streaming.py` passed.
- `node --check` passed for modified video/share/drive frontend files.

## Remaining Follow-Up

- The Standard realtime proxy route is documented as a product tier but remains
  unavailable in the playback payload until route-level authorization,
  concurrency limits, process cleanup, and UI selection are production-ready.
- A live QA run against the actual Scarlet MKV can be used as the final
  acceptance pass once the target environment has the file mounted and ffmpeg /
  ffprobe available.
