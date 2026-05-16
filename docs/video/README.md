# Video Reference Set

Use this folder for deep video/media architecture docs. Entry guides remain in
[04_USER_GUIDE.md](../04_USER_GUIDE.md), [05_FEATURES_OVERVIEW.md](../05_FEATURES_OVERVIEW.md),
and [docs/README.md](../README.md).

- [VIDEO_PLATFORM.md](VIDEO_PLATFORM.md): detailed video module reference
- [VIDEO_STREAMING_ARCHITECTURE.md](VIDEO_STREAMING_ARCHITECTURE.md): HLS / encrypted-media streaming design

Current operator notes:

- Video publish controls are button-opened, not a permanently visible card.
- HLS preparation should be represented as a background job and handled by the
  external worker path; the main Flask server must not synchronously decode or
  package large media.
- Videos that are still preparing HLS should not sit in the public video list
  as a permanent "preparing" item. Show the uploader a processing notice and
  send a notification when the derivative is ready.
- Share management is the canonical place to edit file / album / video share
  options. "My videos" share actions should hand off to Share Management so
  the owner can continue setting password, expiry, max views, preview
  permission, and targeted access.
- Strict E2EE Streaming v2 remains browser-decrypt: the server stores and
  serves encrypted manifest/chunks only, and never accepts raw `vk`, raw file
  key, or E2EE password.
