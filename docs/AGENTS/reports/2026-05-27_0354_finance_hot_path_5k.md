# 2026-05-27 03:54 Finance Hot Path 5K

Scope: post-optimization pure-finance baseline on an isolated temporary server.

Runtime:
- URL: `https://127.0.0.1:55352`
- Runtime root: `/tmp/hackme_finance_5k_opt_20260527_r3/hackme_web`
- Runner: gunicorn, `2` workers x `6` threads, timeout `60`, backlog `512`
- Result JSON: `/tmp/hackme_finance_5k_opt_20260527_r3/finance_5k_result.json`

Command:

```bash
python3 scripts/testing/points_chain_destructive_stress.py \
  --base-url https://127.0.0.1:55352 \
  --runtime-root /tmp/hackme_finance_5k_opt_20260527_r3/hackme_web \
  --out /tmp/hackme_finance_5k_opt_20260527_r3/finance_5k_result.json \
  --root-password RootQa123! \
  --accounts 24 \
  --grant-points 100000 \
  --transfer-ops 600 \
  --direct-transfer-ops 4000 \
  --trading-ops 400 \
  --concurrency 8 \
  --external-transfer-every 5 \
  --max-external-transfers 120 \
  --timeout 60 \
  --mode dev_ready \
  --server-pids 2315827,2315885,2315904 \
  --resource-interval 1.0
```

## Result

Pass.

- `ok=true`
- `findings=0`
- `sample_errors=0`
- `duplicate_request_uuid_groups=0`
- `duplicate_active_wallet_address_groups=0`
- `prefix_pending=0`
- `prefix_failed=0`
- `PointsChain verify ok=true`
- `financial_ok=true`
- financial invariant status: `pass`

## Load Mix

- Accounts: `24`
- HTTP wallet transfers: `600 / 600` returned `200`
- Direct service-layer pc0 transfers: `4000 / 4000` returned `200`
- Trading limit buys: `400 / 400` returned `200`
- Duplicate request_uuid probe: idempotent
- Overspend burst: `10` expected `409`, `2` accepted before balance exhaustion
- Hot-to-cold/external transfers: `120`
- Forced proved transfers: `122`, final pending `0`
- Margin exhaustion probe: expected `400`

## Latency

HTTP/API sample latency:
- Count: `1074`
- p50: `398.937 ms`
- p95: `1085.257 ms`
- p99: `1842.644 ms`
- max: `28767.811 ms`

Direct pc0 transfer hot path:
- Count: `4000`
- median: `23.117 ms`
- p95: `349.416 ms`
- p99: `1047.799 ms`
- max: `2549.653 ms`

The high max API latency came from slow tail cases during the mixed HTTP transfer burst and finality/trading phases. It did not produce failed requests, duplicate credits, pending leftovers, or invariant drift.

## Resource

- Monitored CPU average: `12.92%`
- Monitored CPU max: `29.07%`
- Monitored RSS max: `376.53 MB`
- Main DB max: `46.414 MB`
- Main WAL max: `12.074 MB`
- Runtime memory available min: `7100.78 MB`

## Notes

The first two trial runs exposed a recurring local transport race: `RemoteDisconnected` before the request reached the app, with no matching request row in the DB and no gunicorn traceback. The stress script now retries idempotent wallet submits with the same `request_uuid` and records `transport_retry_count`.

Official run transport retry count: `1`. The retry succeeded and no duplicate request UUID rows were created.

This baseline is pure-finance only. HLS, ComfyUI, BT, cloud-drive upload/download, and frontend browser/mobile interference were intentionally excluded so this run measures the optimized finance hot path rather than full-load degradation.
