# 2026-05-24 11:32 :5000 Backpressure / Multi-Core QA

## Findings

- No current blocking defects found after the 3 worker / 6 thread restart.
- The earlier intermittent half response on deliberate bad-CSRF traffic reproduced only under the old 2 worker / 12 thread shape. After restarting `:5000` as `workers=3 threads=6`, the focused probe returned `160/160` stable `403 csrf_invalid` responses and no `server_busy`.
- First-boot trading backtest capacity probing did not run in this runtime. Evidence: `trading_settings` has no `trading.backtest_capacity_measured_at` or measured-capacity keys, and `secure_audit` has no `TRADING_BACKTEST_CAPACITY_PROBE_*` entries. Current `trading.backtest_max_candles` remains the default `20000`.

## Changes

- `services/server/backpressure.py`
  - Auto mode no longer scales request gates upward from CPU core count.
  - Auto-detected gunicorn threads are capped conservatively, with heavier fast-lane reservation and fixed `heavy=1`, `root=1` defaults unless root/env explicitly overrides them.
  - Added tests proving large CPU counts do not inflate app concurrency.

- `test_for_develop.sh`
  - Gunicorn auto sizing now prefers more worker processes with fewer threads.
  - On this host it resolves to `workers=3 threads=6` instead of `workers=2 threads=12`.

- Live `:5000`
  - Restarted on `/tmp/hackme_web_dev_20260523_231210_3869876/hackme_web`.
  - Current gunicorn shape: master `1589942`, workers `1589947`, `1589958`, `1589966`, bind `127.0.0.1:5000`, `workers=3`, `threads=6`.
  - Current backpressure settings: manual, normal `6`, heavy `1`, root `1`, fast lane reserved `4`, retry-after `1`.

## Verification

- `pytest -q tests/security/gates/test_flask_hardening.py -q`: `7 passed`.
- `bash -n test_for_develop.sh`: passed.
- `./test_for_develop.sh --cli --dry-run --skip-install --server-runner gunicorn --port 59999 --port-conflict fail`: resolved `workers=3 threads=6`.
- `/tmp/hackme_5000_update_smoke.py`: passed after restart.
- `/tmp/hackme_5000_cloud_video_governance_probe.py`: passed, artifact `/tmp/hackme_5000_cloud_video_governance_1779593307.json`.
- `scripts/testing/chat_video_share_link_probe.py --base-url https://127.0.0.1:5000`: passed, artifact `/tmp/hackme_5000_chat_video_share_link_after_3x6.json`.
- `/tmp/hackme_5000_csrf_repro_probe.py`: passed, `160` responses, all `403`.
- `/tmp/hackme_5000_concurrent_multifeature_probe.py`: passed, artifact `/tmp/hackme_5000_concurrent_multifeature_1779593353.json`, `150` samples, `0` hard failures.
- Backpressure status after probes: `accepted=261`, `rejected=0`, `hard_5xx=0`.
- Runtime logs after restart: no new traceback or hard 5xx entries; old `server.log` SQLite lock traces are from earlier in the day.

## Notes

- This is a first-stage multi-core improvement. It uses more Python worker processes without raising SQLite write pressure per process.
- The deeper path for real multi-core utilization is to move CPU-heavy work such as large backtests and media/transcode jobs into separate worker processes or a queue, while keeping SQLite/PointsChain writes serialized and short.
