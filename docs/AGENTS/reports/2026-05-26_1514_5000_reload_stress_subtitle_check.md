# 2026-05-26 15:14 - 5000 reload stress and subtitle check

## Scope

- Rechecked the live QA server on `https://127.0.0.1:5000`.
- Kept the previous large encrypted/E2EE video server on `https://127.0.0.1:51475` running for user inspection.
- Reran normal/malicious mixed load after restart.
- Verified front-end subtitle loading on the shared large-video page.

## Confirmed Issue Fixed

The previous `:5000` background gunicorn process was launched with:

- `--access-logfile -`
- `--error-logfile -`

That caused repeated `BrokenPipeError` logging stack traces once the detached stdout/stderr pipeline broke. I changed `test_for_develop.sh` so background gunicorn writes to runtime files instead:

- `runtime/logs/gunicorn_access.log`
- `runtime/logs/gunicorn_error.log`

Relevant repo lines:

- `test_for_develop.sh:2044`
- `test_for_develop.sh:2771`

The current tmp instance script was patched the same way and `:5000` was restarted.

## Validation

- `bash -n test_for_develop.sh`: passed.
- `bash -n /tmp/hackme_web_accept_20260526_server_mode_prelaunch_update_card/hackme_web/test_for_develop.sh`: passed.
- `https://127.0.0.1:5000/`: `200`, about `0.043s`.
- `https://127.0.0.1:51475/shared/videos/cH-WHf4PoOWr4sKdlVYNLF7vNZk4_RumLz3-Gl-3dec`: `200`, about `0.021s`.

Post-restart stress probe on `:5000`:

- logical users: 12
- requested ops: 96
- concurrency: 8
- ok: true
- degraded: false
- throughput: `25.78 ops/s`
- 5xx / transport failures: `0`
- server_busy: `0`
- p50: `35.712ms`
- p95: `80.156ms`
- p99: `859.696ms`
- max: `859.696ms`
- avg CPU: `11.83%`
- max CPU: `13.58%`
- max monitored RSS: `336.34MB`

The stress seed still hit existing `test` account upload quota (`已達每日上傳限制`). I registered and approved a fresh QA account, promoted it to `normal`, then verified txt/json/png upload and preview all returned `200`. That makes the probe upload error an environment/account-limit false positive, not a confirmed upload-preview breakage.

## Subtitle Check

Playwright front-end check on the large shared video passed:

- player tag: `VIDEO`
- HLS source: loaded
- subtitle track: attached
- track label: `JPSC`
- srclang: `chi`
- text track mode: `showing`
- cue count: `45,800`
- cue samples include both Chinese and Japanese cues
- subtitle time-shift controls are present in the page text

Artifacts:

- `/tmp/hackme_web_real_hls_20260526_encrypted/shared_video_subtitle_frontend_check_after_5000_qa.json`
- `/tmp/hackme_web_real_hls_20260526_encrypted/shared_video_subtitle_frontend_check_after_5000_qa.png`
- `/tmp/hackme_web_qa_5000_stress_after_reload.json`

## Servers Left Running

- `:5000`: master PID `1248386`, workers `1248444`, `1248445`, `1248446`, `1248465`
- `:51475`: master PID `1077386`, workers `1126219`, `1126262`, `1126292`, `1126310`

No server was shut down at the end of this check.
