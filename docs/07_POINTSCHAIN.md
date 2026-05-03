# 07 PointsChain

一句話說明：PointsChain 是本專案的站內點數帳本與驗證鏈，影片打賞、經濟功能與交易都依賴它作為可信來源。

## 設計目的

如果金額、點數、交易手續費、打賞直接改 wallet balance，就很難做審計、
恢復與異常修復。PointsChain 把所有重要資金變動收斂到同一條可回放的 ledger。

## 使用方法

### 一般使用者

- 在站內消費、打賞、交易時，不直接碰鏈設定
- 看自己的 wallet 與 ledger 即可

### root

- 可查看 root report / audit
- 可 seal chain、verify chain、建立 backup、執行 recovery
- 可在 safe mode 下使用 one-click anomaly handler

## 原理

- `points_ledger` 是 source of truth
- `points_wallets` 是從 ledger replay 出來的結果，不是最終可信來源
- video tip、admin adjustment、trading settle 都應寫入 PointsChain
- 恢復時重建 wallet，不信任舊 wallet snapshot 自己就是正確答案

## 失敗情境與提示

- 前端餘額顯示與後端不一致：
  先跑 chain verify，再看是否需要 recovery。
- 想用 server snapshot restore 修好 PointsChain：
  不一定對；若只有經濟鏈壞掉，先評估 PointsChain recovery。
- chain verify fail 但沒有 healthy backup：
  應回 manual required，而不是硬覆蓋 live ledger。
- root 以為自己交易也會寫 PointsChain：
  root 的模擬交易餘額是分開的，與正常使用者點數結算不同。

## 測試方式

- wallet / ledger / adjust / seal / verify / backup / recovery
- 影片打賞與交易後的 ledger 對帳
- restore 後的 wallet rebuild
- 極小額、多次累加、精度與手續費驗算

## 相關文件連結

- [08_TRADING_ENGINE.md](08_TRADING_ENGINE.md)
- [09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md)
- [RUNTIME_RESET_AND_RECOVERY.md](RUNTIME_RESET_AND_RECOVERY.md)
- [For_developer.md](For_developer.md)
- [VIDEO_PLATFORM.md](VIDEO_PLATFORM.md)
- [TRADING.md](TRADING.md)
