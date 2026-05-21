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
- root report 會統計目前在外積分、root-held points、ledger 淨額、供給差異、
  未封塊 ledger 數與 sealed coverage，作為未來全站區塊鏈化的供給口徑基礎
- root 積分錢包頁應提供唯讀的資金池管理與全用戶倉位管理摘要，讓部署者能對照交易資金池、
  借貸倉位與 PointsChain 供給，不直接在頁面改用戶倉位
- 可 seal chain、verify chain、建立 backup、執行 recovery
- 可在 safe mode 下使用 one-click anomaly handler

## 原理

- `points_ledger` 是 source of truth
- `points_wallets` 是從 ledger replay 出來的結果，不是最終可信來源
- video tip、admin adjustment、trading settle 都應寫入 PointsChain
- 恢復時重建 wallet，不信任舊 wallet snapshot 自己就是正確答案
- 全站供給相關 dashboard 應讀 ledger / report / snapshot 口徑，不應在前端自行加總後當作可信總量

## 模擬鏈錢包身份

- 一般會員初次登入後要先完成 PointsChain 錢包 onboarding，才能領取註冊禮。
- 可選官方熱錢包、瀏覽器建立的自管冷錢包、匯入冷錢包或多簽 policy 錢包。
- 自管與匯入冷錢包的私鑰只在瀏覽器內產生或匯入；伺服器只收 public JWK、地址與簽章。
- root 可查看 mint / burn 系統錢包身份；這些身份只用於模擬供給 bookkeeping，不保存私鑰。

詳細 contract 見 [architecture/BLOCKCHAIN_WALLET_IDENTITY_CONTRACT.md](architecture/BLOCKCHAIN_WALLET_IDENTITY_CONTRACT.md)。

## 自動發放規則

- 新註冊一般會員的註冊禮會延後到完成錢包 onboarding 後發放，且仍以 ledger idempotency 保證只入帳一次。
- 會員生日禮金為 500 點，只在會員生日當天成功登入時發放。
- 生日判定使用 root 設定的伺服器時區；未在生日當天登入則不補發。
- 生日禮金透過 `birthday_gift:<year>:<user_id>` idempotency key 寫入 PointsChain，同一會員同一年最多入帳一次。
- root 帳號不領取生日禮金；管理者帳號若有生日資料，仍以會員登入規則處理。

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
- root report 的目前在外積分、ledger 淨額與 wallet replay 對帳
- root 積分錢包資金池 / 全用戶倉位唯讀摘要與交易快照對帳
- restore 後的 wallet rebuild
- 極小額、多次累加、精度與手續費驗算

## 相關文件連結

- [08_TRADING_ENGINE.md](08_TRADING_ENGINE.md)
- [09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md)
- [10_BLOCKCHAIN_WALLETIZATION_PREWORK_PLAN.md](10_BLOCKCHAIN_WALLETIZATION_PREWORK_PLAN.md)
- [architecture/BLOCKCHAIN_WALLET_IDENTITY_CONTRACT.md](architecture/BLOCKCHAIN_WALLET_IDENTITY_CONTRACT.md)
- [RUNTIME_RESET_AND_RECOVERY.md](ops_boundaries/RUNTIME_RESET_AND_RECOVERY.md)
- [For_developer.md](For_developer.md)
- [VIDEO_PLATFORM.md](video/VIDEO_PLATFORM.md)
- [TRADING.md](trading/TRADING.md)
