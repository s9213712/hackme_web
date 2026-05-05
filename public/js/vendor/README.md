## Vendored Player Libraries

### `hls.light.min.js`

- Upstream project: `hls.js`
- Version: `1.6.15`
- Source URL:
  - `https://cdn.jsdelivr.net/npm/hls.js@1.6.15/dist/hls.light.min.js`
- License:
  - `BSD-3-Clause`

This file is vendored locally so desktop Chrome / Firefox / Edge can use the
same-origin HLS fallback without depending on a third-party CDN at playback
time. Safari continues to use native HLS and does not require this bundle.
