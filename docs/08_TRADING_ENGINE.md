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
  以深度加權平均生成執行參考價。root 也可改成手動權重，API 失效時會用剩餘健康來源自動補位
- 使用者交易資金走 PointsChain
- root 有獨立模擬餘額，不污染正式點數
- POINTS 帳本仍是整數制；交易手續費自 `2026.05.03-063` 起改用 `Decimal`
  計算後四捨五入到最近整點，避免舊版小額單一律 `ceil` 造成系統性超收
- DCA 機器人的 `max_runs` 支援 `-1`，代表不限制總執行次數
- 價格來源失效、價格跳動過大或借貸池不足時，系統應 fail closed

## 失敗情境與提示

- 交易頁顯示數字，但成交失敗：
  可能是後端重新驗價、餘額不足、circuit breaker、live provider 失效。
- root 把融合價格切到手動權重後，某家交易所又被設成 0：
  該交易所會完全退出融合；若手動權重有效來源全部失敗，系統會先退到其餘單一公開 API，再退到最後健康快取。
- 小額交易顯示成 0 或精度怪異：
  應視為嚴重缺陷，不是純 UI 問題。先確認目前 release 的整數 POINT fee
  rounding 規則，並用同一套規則手算。
- root 開了 trading，但 economy / PointsChain 沒先驗證：
  這是不完整部署。
- 網格 / workflow bot 看得到但不該直接上 production：
  先做回測、壓力、restore consistency。

## 測試方式

- 正常買賣、市價 / 限價、取消單
- 極小額 / 大額 / 負數 / 字串 / 科學記號輸入
- 多次累加、手續費、PnL、借貸利息手算驗證
- 融合價格自動權重 / 手動權重 / API 故障補位驗證
- DCA `max_runs=-1` 長期執行與重啟後續跑驗證
- `security/trading_stress_pentest.py`
- snapshot / restore 後狀態一致性

## 相關文件連結

- [TRADING.md](TRADING.md)
- [07_POINTSCHAIN.md](07_POINTSCHAIN.md)
- [11_QA_TESTING.md](11_QA_TESTING.md)
- [security/TRADING_STRESS_PENTEST.md](security/TRADING_STRESS_PENTEST.md)
- [workflows/README.md](../workflows/README.md)
