# 2026-05-24 16:48 :5000 Capacity Normal vs Full Load

## Scope
- Tested ordinary online member load against `https://127.0.0.1:5000`.
- Compared with prior full high-pressure flow artifacts.
- Updated capacity probe UX threshold rule: a UX crossing must be confirmed by 3 repeated rounds before being reported as the UX degradation point.

## Artifacts
- Normal boundary: `/tmp/hackme_5000_normal_online_ladder_boundary_pscpu_latest.json`
- Normal confirmed boundary: `/tmp/hackme_5000_normal_online_confirmed_boundary_latest.json`
- Comparison summary: `/tmp/hackme_5000_capacity_comparison_latest.json`
- Full 8-account high-pressure: `/tmp/hackme_5000_live_full_flow_8_accounts.json`
- Full 10-account high-pressure: `/tmp/hackme_5000_live_full_flow_10_accounts.json`

## Results
- Ordinary online, 23 accounts: p95 1482ms, p99 2818ms, max 3342ms, CPU peak 92.9%, RSS peak 459.48MB, 0 hard failures.
- Ordinary online, 24 accounts: initial round crossed UX line and 3/3 confirmations crossed; confirmed UX threshold. Worst confirmation p95 1875ms, p99 3137ms, max 3436ms, CPU peak 105.7%, RSS peak 456.84MB, 0 hard failures.
- Full high-pressure, 8 accounts: p95 1402ms, p99 3939ms, max 7939ms, CPU peak 81.6%, RSS peak 581.44MB, 0 hard failures.
- Full high-pressure, 10 accounts: p95 3022ms, p99 7200ms, max 11439ms, CPU peak 100.0%, RSS peak 471.77MB, 5 controlled `server_busy` failures.

## Trading Share
- Ordinary online load included trading dashboard, markets, asset overview, and grid preview.
- Ordinary 23-account load: trading was 92/506 requests, 18.2% by request count; estimated latency share was 18.9% by p50-weighted time and 17.6% by p95-weighted time.
- Ordinary 24-account threshold round: trading was 96/528 requests, 18.2% by request count; estimated latency share was 18.6% by p50-weighted time and 21.5% by p95-weighted time.
- Full high-pressure 8-account load: trading was 212/615 requests, 34.5% by request count; estimated p95-weighted latency share was 40.5%.
- Full high-pressure 10-account load: trading was 262/763 requests, 34.3% by request count; estimated p95-weighted latency share was 44.7%.

## Notes
- Ordinary online threshold is therefore conservatively 23 acceptable concurrent accounts, with 24 as the confirmed UX degradation point under the current 4x6 live server.
- The ordinary load's trading portion is material but not dominant; chat, album/share creation, storage upload, PointsChain reads, and trading endpoints all contribute near the boundary.
- The full high-pressure load is a different class: bot competition, spot orders, DCA/grid bot creation, root matching, background trading scans, wallet creation, disputes, heavy download/upload, and malicious probes.

## Verification
- `python3 -m py_compile scripts/testing/predeploy_capacity_probe.py /tmp/hackme_5000_normal_online_ladder.py`
- `pytest -q tests/scripts/deploy/test_predeploy_capacity_probe.py -q`
