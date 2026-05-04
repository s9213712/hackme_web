# 09 Snapshot Reset Restore

一句話說明：這份文件專門說明 snapshot、portable restore、runtime reset、PointsChain recovery 的邊界與實際操作觀念。

## 設計目的

部署者最容易混淆的就是：

- server snapshot restore
- PointsChain restore
- runtime reset
- server mode checkpoint / rollback

這幾個都像「恢復」，但責任完全不同。這份文件就是把這些責任邊界拉清楚。

## 使用方法

### 你要整站回滾時

用 server snapshot restore。

### 你只要修復經濟鏈時

先看 PointsChain recovery，不要先動全站 restore。

### 你要把站點清回最小可跑狀態時

用 runtime reset，但先理解它是 destructive cleanup。

### 你在做模式切換或高風險測試時

看 server mode checkpoint / superweak rollback。

## 原理

- server snapshot：保護整站 DB + runtime file roots + config archive
- server snapshot 也會帶入目前設定的 runtime secret files，例如 `runtime/.chain_seed`、`runtime/.csrfkey`、`runtime/.filekey`、`runtime/.fkey`、`runtime/.integrity_key`、`runtime/integrity_manifest.json`、`runtime/cert.pem`、`runtime/key.pem`
- PointsChain backup：只保護經濟 ledger / chain
- runtime reset：清掉可重建 runtime 與 live data，並要求重啟
- server mode checkpoint：保護 mode switch / rollback 場景

## 失敗情境與提示

- restore 完後 runtime key / TLS cert 沒回來，或 hash 驗證失敗：
  先看 snapshot metadata 的 `runtime_secret_files`，以及 restore event 的 `runtime secret validation failed`。目前 server snapshot 會一起帶入這些檔案。
- reset 後發現東西都沒了：
  這是設計目的；先去找 `pre_reset` snapshot。
- 只壞了 PointsChain 卻直接做整站 restore：
  可能把不需要回滾的其他模組也一起覆蓋。
- 做了 restore 卻沒驗 post-restore consistency：
  視同沒完成恢復演練。

## 測試方式

- create/list/download/upload-restore
- pre-reset snapshot 是否存在
- reset 後離線 / 重連 / `started_at` 更新
- restore 後 baseline data 保留、殘留 dirty data 被清掉
- PointsChain verify / recovery / wallet rebuild

## 相關文件連結

- [RUNTIME_RESET_AND_RECOVERY.md](RUNTIME_RESET_AND_RECOVERY.md)
- [SERVER_MODE_V2_PROFILE_MATRIX.md](SERVER_MODE_V2_PROFILE_MATRIX.md)
- [SERVER_MODE_V2_TEST_PLAN.md](SERVER_MODE_V2_TEST_PLAN.md)
- [11_QA_TESTING.md](11_QA_TESTING.md)
- [security/FUNCTIONAL_SMOKE.md](security/FUNCTIONAL_SMOKE.md)


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
