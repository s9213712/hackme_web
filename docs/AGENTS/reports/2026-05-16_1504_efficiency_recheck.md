# Efficiency Recheck - 2026-05-16 15:04

## Result

Confirmed improvement. The current working tree reduces request latency and avoids the previously reproduced timeout path under mixed load.

## Evidence

- Isolated server: `https://127.0.0.1:56543`
- Runtime: `/tmp/hackme_web_efficiency_check_20260516_01/hackme_web/runtime`
- Latency probe: `/tmp/hackme_comfy_latency_probe.py`
- Mixed pressure probe output: `/tmp/hackme_web_efficiency_check_20260516_01/timeout_attribution_efficiency.json`

## Current Measurements

- Idle baseline health: max `18.5ms`, no health failures.
- Trading pressure: health max `39.4ms`, response p95 `120.8ms`, peak RSS `101560 KB`, peak threads `11`.
- Mixed load without filename collision: health max `55.0ms`, response p95 `179.9ms`, peak RSS `135164 KB`, peak threads `14`.
- Mixed load with collision: health max `89.8ms`, response p95 `193.1ms`, peak RSS `143944 KB`, peak threads `14`.
- Post-stress idle CPU delta over 5 seconds: `2.8%`.

## Hot Path Checks

- `/api/comfyui/models`: max `456.15ms`, avg `207.08ms`.
- `/api/comfyui/node-catalog`: avg `40.61ms`.
- `/api/trading/live-price?market=BTC/POINTS`: avg `31.33ms`.
- `/api/root/trading/background/status`: avg `18.88ms`.

## Comparison Against Earlier Artefacts

- Earlier clean mixed collision run had response p95 `289.8ms`; current run is `193.1ms`.
- Earlier clean mixed collision response max was `1141.5ms`; current run is `915.2ms`.
- Earlier baseline peak RSS was `95228 KB`; current baseline is `96244 KB`, effectively flat.
- Earlier mixed collision peak RSS was `142376 KB`; current is `143944 KB`, effectively flat.
- Earlier ComfyUI models route could hit `30s` when `/object_info` stalled; current repeated route max is under `0.5s`.

## Remaining Hotspots

- `POST /api/root/trading/background/run-once` remains the slowest root-only operation under stress, peaking around `0.8s-0.9s`.
- `GET /api/admin/trading/report` remains a root-only aggregation hotspot, peaking around `0.8s-0.9s` in this run.
- Root sitewide reports are acceptable for admin views but should move further toward snapshots if they become frequently polled.

## Cleanup

The isolated server should be stopped after reporting. ComfyUI at `8189` was not started by this run and should be left alone.
