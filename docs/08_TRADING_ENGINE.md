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

不屬於正式對外功能：

- 真實金流交割
- 一般用戶 futures / PVP
- 未驗證風險控制下的自動放大交易

## 原理

- 前端報價與圖表是參考值，最終執行價格由後端重抓與驗證
- 使用者交易資金走 PointsChain
- root 有獨立模擬餘額，不污染正式點數
- 價格來源失效、價格跳動過大或借貸池不足時，系統應 fail closed

## 失敗情境與提示

- 交易頁顯示數字，但成交失敗：
  可能是後端重新驗價、餘額不足、circuit breaker、live provider 失效。
- 小額交易顯示成 0 或精度怪異：
  應視為嚴重缺陷，不是純 UI 問題。
- root 開了 trading，但 economy / PointsChain 沒先驗證：
  這是不完整部署。
- 網格 / workflow bot 看得到但不該直接上 production：
  先做回測、壓力、restore consistency。

## 測試方式

- 正常買賣、市價 / 限價、取消單
- 極小額 / 大額 / 負數 / 字串 / 科學記號輸入
- 多次累加、手續費、PnL、借貸利息手算驗證
- `security/trading_stress_pentest.py`
- snapshot / restore 後狀態一致性

## 相關文件連結

- [TRADING.md](TRADING.md)
- [07_POINTSCHAIN.md](07_POINTSCHAIN.md)
- [11_QA_TESTING.md](11_QA_TESTING.md)
- [security/TRADING_STRESS_PENTEST.md](security/TRADING_STRESS_PENTEST.md)
- [workflows/README.md](../workflows/README.md)
