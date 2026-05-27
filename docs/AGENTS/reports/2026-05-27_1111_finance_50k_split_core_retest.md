# 2026-05-27 50K Finance DB Split Core Retest

## Summary

- Result: PASS for core finance 50K profile.
- Artifact: `/tmp/hackme_finance_50k_split_20260527_0230/artifacts/finance_50k_split.json`
- Runtime: `/tmp/hackme_finance_50k_split_20260527_0230/hackme_web/runtime`
- Server: gunicorn, 2 workers x 6 threads, port `55489`
- Scope: `6000` HTTP internal wallet transfers, `40000` direct service-layer pc0 transfers, `4000` trading limit orders.
- External unowned bridge transfers were disabled for this pass (`external_transfer_count=0`) because the 1200-external profile exposed slow bridge finalization as a separate long-transaction issue.

## Result Details

- `ok=true`, `findings=[]`
- Direct transfers: `40000/40000`, errors `0`, status `{"200": 40000}`
- Trading orders: `{"200": 4000}`
- Prefix counts: confirmed `46051`, pending `0`, failed `0`
- Duplicates: request UUID groups `0`, active wallet address groups `0`
- Verify: status `200`, `financial_ok=true`, error count `0`
- Runtime DB split check:
  - `database.db`: `2347008` bytes; points/trading rows all `0`
  - `finance.db`: `464158720` bytes; transfer requests `46051`, ledger rows `95625`, trading orders `4000`

## Resource Peaks

- `finance.db`: `442.656 MB`
- `database.db`: `2.238 MB`
- `audit.db`: `4.305 MB`
- `auth.db`: `0.184 MB`
- Monitored RSS max: `2268.53 MB`
- CPU avg/max: `14.54%` / `27.0%`

## Notes

- The previous 50K profile with `1200` external unowned transfers hit `database is locked` after direct transfer because root transaction list tried to finalize too many proved pending bridge transfers in one request.
- The fix changed root transaction list finalization to short incremental batches and raised finance DB busy timeout.
- The core 50K pass still recorded one client-side timeout for `root_points_report` at `60s`; server access logs show `/api/root/points/report` returned `200` after the client timed out. This is a remaining report-performance risk, not a failed finance invariant.
