# PointsChain L1 Address + Exchange Pool QA

Date: 2026-05-22 12:19 Asia/Taipei
Runtime: `https://127.0.0.1:54343`

## Confirmed Fixes

- Arbitrary valid `pc1...` destination addresses now accept transfers even when no user currently owns the address.
- Pending transfers to unowned addresses freeze the sender amount plus fee, do not credit the destination until 20/20 Proved, and show `未綁定地址` in transaction management.
- Confirmed transfers to an unowned address are queryable by explorer address and can later be claimed when a user imports the matching private key.
- If a recipient wallet becomes `lost` before finality, the transaction now confirms to the address instead of failing as `failed_inactive_wallet`.
- Official Treasury grants can target unowned public addresses; system-fund restrictions still block unsupported fund targets.
- Official Treasury transfers to `exchange_fund` now synchronize `trading_reserve_pool`, and root funding-pool UI shows the PointsChain EXCHANGE balance with alignment status.
- Root PointsChain audit metadata no longer exposes an exact `user_id` key in the root report payload.

## Runtime Evidence

- Backend runtime probe:
  - unowned transfer `6b020a018f29985afe508b0adfe822923abd68988c3a29b97434c73a7fd9b59b`
  - pending destination balance `0`, source frozen `12`
  - proved destination balance `11`, no transfer-in ledger UUID
  - exchange fund sync transaction `899277cfe1d31a53b0c8921bba95311c0e2c32fe70b45c992f8999a83dcf8a52`
  - EXCHANGE Fund `100164 -> 100181`, reserve pool `100164 -> 100181`
- Playwright runtime probe:
  - member UI unowned transfer `7078d728813a6bbbe5d29d1ea96083df728493abfc8e6967a3164ac1127661d4`
  - transaction management displayed `未綁定地址`
  - root UI exchange sync transaction `47be413f8b478595cf553fec3a4e0cd15bedbfc9d29c071deef849ee3239cc1c`
  - funding-pool text: `PointsChain EXCHANGE 100,185 · 已對齊`

## Automated Checks

- `pytest -q tests/points/test_points_chain.py tests/points/test_points_explorer.py tests/points/test_wallet_identity.py ...`
- Result: 60 passed.

## Current Residual State

- Chain verification: ok.
- Economy health remains yellow because EXCHANGE liquid balance is `100,185`, below policy `exchange_critical_watermark = 250,000`.
- EXCHANGE total assets include receivables: `5,100,349`, with receivable principal `5,000,164`.
