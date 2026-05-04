# 08 Trading Engine

一句話說明：這份文件給想啟用或驗收交易模組的人，快速說清楚交易所、借貸、機器人、回測與風控邊界。

## 設計目的

`TRADING.md` 很完整，但第一次接手的人不一定需要先看到全部細節。
這份文件先回答「現在到底支援什麼、依賴什麼、不能拿它當什麼、要怎麼驗」。

## 使用方法

### 啟用前先確認

1. PointsChain / economy 已可用
2. 你知道 root 模擬餘額與一般使用者真實 PointsChain 資金不同
3. 你願意先跑精度、壓力、restore consistency 測試，再開給更多人

### 目前範圍

- 現貨交易：`BTC/USDT`、`ETH/USDT` 前台顯示
- 內部符號仍是 `BTC/POINTS`、`ETH/POINTS`
- DCA / 網格 / workflow bots
- 回測
- 實驗性 borrow trading
- 多交易所融合價格（自動依深度加權，或由 root 手動調權重）

不屬於正式對外功能：

- 真實金流交割
- 一般用戶 futures / PVP
- 未驗證風險控制下的自動放大交易

## 原理

- 前端報價與圖表是參考值，最終執行價格由後端重抓與驗證
- 預設 live 價格來源是多交易所融合價格；系統會抓多家交易所掛單簿中價，
  以深度加權平均生成執行參考價。root 也可改成手動權重，API 失效時會用剩餘健康來源自動補位；
  root 設定頁另有即時比例 dashboard，可直接看到各來源當下的 normalized weight、
  被排除來源，以及是否已降級成保守模式
- 使用者交易資金走 PointsChain
- root 有獨立模擬餘額，不污染正式點數
- POINTS 帳本仍是整數制；交易手續費自 `2026.05.03-063` 起改用 `Decimal`
  計算後四捨五入到最近整點，避免舊版小額單一律 `ceil` 造成系統性超收
- 借貸利息自 `2026.05.04-066` 起改成先累積 `micropoints` 殘值，再跨過整點時才入帳；
  這樣 `50 @ 1% / day` 不會再在 1 天後直接被記成 `1` 點
- DCA 機器人的 `max_runs` 支援 `-1`，代表不限制總執行次數
- 價格來源失效、價格跳動過大或借貸池不足時，系統應 fail closed
- Backtest 現在把「總上限」和「內部分段上限」拆開：單次請求總上限為
  `20,000` 根 K 線，內部分段每批最多 `10,000` 根；因此像
  `BTC/USDT 2024-01-01 ~ 2024-12-31 @ 1h` 這類全年回測現在可直接執行，
  而且不需要前端自己切成多次獨立回測
- 回測日期欄位不再只丟給使用者一個 `20,000` 根上限。前端會依目前週期，
  即時計算「若保留開始時間，結束最晚可選到哪裡」與
  「若保留結束時間，開始最早可選到哪裡」，並同步收斂 `datetime-local`
  欄位的可選範圍

## 失敗情境與提示

- 交易頁顯示數字，但成交失敗：
  可能是後端重新驗價、餘額不足、circuit breaker、live provider 失效。
- root 把融合價格切到手動權重後，某家交易所又被設成 0：
  該交易所會完全退出融合；若手動權重全部為 0，系統會明確標示
  `manual weights invalid` 並退回 `auto_depth`。若 order book 有效來源全部失敗，
  系統會先退到單一公開 ticker，再退到最後健康快取，並在 root dashboard /
  audit event 標示 `價格來源降級`
- 小額交易顯示成 0 或精度怪異：
  應視為嚴重缺陷，不是純 UI 問題。先確認目前 release 的整數 POINT fee
  rounding 規則，並用同一套規則手算。
- 小本金借貸看起來 `interest_points` 還沒跳動：
  先看 `interest_exact_points` 或 `interest_carry_micropoints`；若還沒跨過整點，
  系統現在會先保留殘值，而不是直接進位多收。
- root 把借貸池壓力倍率設成 `0`，但利率還像有加成：
  這在 `2026.05.04-066` 前是 bug；新版會正確尊重 `0`
- 回測長區間以前會卡在 `5000` 或 `10000`：
  先確認目前 release 是否已經是 `2026.05.04-067` 之後；新版會由後端自動分段續跑，
  但總量仍受 `20,000` 根保護，超過時會明確要求縮小區間
- root 開了 trading，但 economy / PointsChain 沒先驗證：
  這是不完整部署。
- 網格 / workflow bot 看得到但不該直接上 production：
  先做回測、壓力、restore consistency。

## 測試方式

- 正常買賣、市價 / 限價、取消單
- 極小額 / 大額 / 負數 / 字串 / 科學記號輸入
- 多次累加、手續費、PnL、借貸利息手算驗證
- 小本金借貸利息 carry 驗證，例如 `principal=50, daily_rate=1%, 24h -> interest_points=0, carry=0.5`
- 融合價格自動權重 / 手動權重 / API 故障補位驗證
- DCA `max_runs=-1` 長期執行與重啟後續跑驗證
- `BTC/USDT 1h` 全年回測（約 `8784` 根）是否仍可通過，不再被舊的 `5000` 根上限擋住
- `10,001 ~ 20,000` 根 K 線時，是否由後端自動分段續跑，且 DCA / workflow / 持倉狀態不會在段與段之間被重置
- `security/trading_stress_pentest.py`
- snapshot / restore 後狀態一致性

## 相關文件連結

- [TRADING.md](TRADING.md)
- [07_POINTSCHAIN.md](07_POINTSCHAIN.md)
- [11_QA_TESTING.md](11_QA_TESTING.md)
- [security/TRADING_STRESS_PENTEST.md](security/TRADING_STRESS_PENTEST.md)
- [workflows/README.md](../workflows/README.md)
