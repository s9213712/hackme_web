# 2026-05-27 50K Finance DB Split Interference Retest

## Summary

- Result: FAIL overall because root/admin PointsChain endpoints exceeded the `180s` client timeout after the DB grew to the second 50K-scale dataset.
- Artifact: `/tmp/hackme_finance_50k_split_20260527_0230/artifacts/finance_50k_interference.json`
- Runtime: `/tmp/hackme_finance_50k_split_20260527_0230/hackme_web/runtime`
- Server: reused the existing runtime/database; restarted gunicorn on port `55489`, 2 workers x 6 threads.
- Scope: `6000` HTTP wallet transfers, `40000` direct service-layer pc0 transfers, `4000` trading limit orders.
- Non-trading interference was active during the 50K run:
  - `/tmp/hackme_finance_50k_split_20260527_0230/artifacts/interference/system_stress_overlap.json`
  - `/tmp/hackme_finance_50k_split_20260527_0230/artifacts/interference/member_probe_overlap.json`
  - `/tmp/hackme_finance_50k_split_20260527_0230/artifacts/interference/video_hls_quality_overlap.json`

## Confirmed Findings

### High: Root PointsChain/Admin Reads Are Too Slow At ~92K Transfers

- The 50K data path completed, but management endpoints timed out from the client at `180s`.
- Affected operations in the artifact: `accelerate_pending`, `root_finalize_transfers`, `root_chain_seal`, `root_chain_verify`, `root_points_report`.
- Server access logs show several of these eventually returned `200` after the client had timed out:
  - `POST /api/points/explorer/accelerate` returned `200` at `12:44:18`.
  - `GET /api/points/transactions?limit=100` returned `200` at `12:48:17` and `12:48:30`.
  - `POST /api/root/points/chain/seal` returned `200` at `13:02:23`.
  - `GET /api/root/points/chain/verify` returned `200` at `13:05:42`.
  - `GET /api/root/points/report` returned `200` at `13:09:45`.
- Impact: QA/client callers see false failures and long blocking requests; root workflows become unreliable at this DB size.

## Result Details

- `ok=false`, findings `2`
- Direct transfers: `40000/40000`, errors `0`, status `{"200": 40000}`
- Trading orders: `{"200": 4000}`
- HTTP wallet transfers: `{"200": 6000}`
- Prefix counts: confirmed `46051`, pending `0`, failed `0`
- Duplicates: request UUID groups `0`, active wallet address groups `0`
- Runtime finance totals after this run:
  - `points_chain_transfer_requests`: `92102`
  - `points_ledger`: `191249`
  - `trading_orders`: `8000`

## Interference Results

- System stress: `5305` mixed non-trading ops; `degraded=true` due latency (`overall_p95_gt_1500ms`, `overall_p99_gt_5000ms`, `qos_version_p95_gt_1000ms`), hard failure rate `0.002451`.
- Member probe: findings `0`.
- HLS quality stress: upload, wait, and measure phases all `ok=true`.

## DB Sizes

- `finance.db`: `928333824` bytes, plus WAL `11297072` bytes.
- `database.db`: `3543040` bytes, plus WAL `1701592` bytes.
- `audit.db`: `9093120` bytes.
- `auth.db`: `331776` bytes, plus WAL `16512` bytes.
- `control.db`: `98304` bytes.

## Resource Peaks

- Finance DB peak: `885.328 MB`
- Main DB peak: `3.379 MB`
- Audit DB peak: `8.672 MB`
- Auth DB peak: `0.316 MB`
- Monitored RSS max: `4855.28 MB`
- CPU avg/max: `20.11%` / `42.79%`

## Notes

- External bridge stress was not intentionally enabled (`external_transfer_count=0`), but the overspend probe still created two unowned pending transfers and exercised acceleration/finality paths.
- The finance split itself still held: high-volume finance writes remained in `finance.db`; `database.db` stayed small.
- The test server and the unrelated stale capacity-probe server were stopped after collection.
