# Server Security Modes

This page is kept only as a compatibility redirect.

The old content on this page is no longer authoritative because it still treats
`preprod` as a canonical mode and does not cover the formal Server Mode v2
states such as `dev_ready`, `maintenance`, and `incident_lockdown`.

Use these documents instead:

- [SERVER_MODE_V2_PROFILE_MATRIX.md](SERVER_MODE_V2_PROFILE_MATRIX.md): the
  canonical mode matrix, confirmation phrases, token classes, and production
  gate requirements.
- [SERVER_MODE_V2_TEST_PLAN.md](SERVER_MODE_V2_TEST_PLAN.md): the current test
  and validation plan for mode switching, incident handling, and live smoke.
- [For_developer.md](For_developer.md): API and settings overview.


---

## PointsChain v2 區塊鏈化規劃 (2026-05-04 拍板, 尚未實作)

本模組未來將與全站 PointsChain v2 區塊鏈化整合：

- 工程設計：[`docs/BLOCKCHAIN/POINTSCHAIN_ENGINEERING.md`](BLOCKCHAIN/POINTSCHAIN_ENGINEERING.md)
- 用戶白皮書：[`docs/BLOCKCHAIN/POINTSCHAIN_WHITEPAPER.md`](BLOCKCHAIN/POINTSCHAIN_WHITEPAPER.md)
- 地址規格：[`docs/BLOCKCHAIN/POINTS_WALLET_ADDRESSING.md`](BLOCKCHAIN/POINTS_WALLET_ADDRESSING.md)
- 轉帳 API：[`docs/BLOCKCHAIN/POINTS_TRANSFER_API.md`](BLOCKCHAIN/POINTS_TRANSFER_API.md)
- 多簽錢包：[`docs/BLOCKCHAIN/MULTISIG_WALLETS.md`](BLOCKCHAIN/MULTISIG_WALLETS.md)
- QA Mining / 貢獻獎勵 (Phase 7)：[`docs/BLOCKCHAIN/POINTS_MINING_REWARDS.md`](BLOCKCHAIN/POINTS_MINING_REWARDS.md)
- QA / Release Gate：[`docs/BLOCKCHAIN/POINTSCHAIN_QA.md`](BLOCKCHAIN/POINTSCHAIN_QA.md)

**狀態：設計已拍板（root, 2026-05-04），尚未實作完成。**
