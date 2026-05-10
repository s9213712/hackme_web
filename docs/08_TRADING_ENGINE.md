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

- 現貨交易：`BTC/USDT`、`ETH/USDT`、`XRP/USDT`、`BNB/USDT`、`PAXG/USDT`
  前台顯示
- 內部符號仍是 `BTC/POINTS`、`ETH/POINTS`、`XRP/POINTS`、`BNB/POINTS`、
  `PAXG/POINTS`
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
- 現貨交易 fee 預設為 `0.10%`；Grid-trade 預設不是半價，而是套用
  `25%` 折扣後的現貨 fee
- 預設 live 價格來源是多交易所融合價格；系統會抓多家交易所掛單簿中價，
  以深度加權平均生成執行參考價。root 也可改成手動權重，API 失效時會用剩餘健康來源自動補位；
  root 設定頁另有即時比例 dashboard，可直接看到各來源當下的 normalized weight、
  被排除來源，以及是否已降級成保守模式
- 使用者交易資金走 PointsChain
- root 有獨立模擬餘額，不污染正式點數
- POINTS 帳本仍是整數制；交易手續費自 `2026.05.03-063` 起改用 `Decimal`
  計算後四捨五入到最近整點，避免舊版小額單一律 `ceil` 造成系統性超收
- 借貸利率已拆成兩組 root 可調設定：
  - `BTC / ETH = 8% APR`
  - `USDT / POINTS = 10% APR`
  系統會依實際借入資產決定用哪一組
- 借貸利息自 `2026.05.04-066` 起改成先累積 `micropoints` 殘值，再跨過整點時才入帳；
  這樣 `50 @ 1% / day` 不會再在 1 天後直接被記成 `1` 點
- 借貸現在預設每 `1` 小時計息，不足 `1` 小時以 `1` 小時計；前台倉位列表
  會直接顯示 `累積利息`、`已實扣` 與 `下一次計息`
- 每位使用者的成交名目、成交次數與總 fee 會累積到後端 volume stats，供後續
  VIP 規則或 root 報表使用，不再只能從單次 fills 臨時重算
- DCA 機器人的 `max_runs` 支援 `-1`，代表不限制總執行次數
- 交易機器人稽核已接到後端 scheduler。新 bot 啟用後不會立刻被打燈，
  而是先維持 `未稽核`；等它至少成交 1 筆，或啟用滿 `24h`，才會被列入
  定期稽核並得到綠 / 黃 / 紅燈結果。root 可在專屬 dashboard 手動重跑稽核，
  也可同頁看 trading bug reports
- `BTC_trade` 若有設定 repo / branch / project path，root 現在可在 `交易所參數`
  直接按 `一鍵啟動預測`。後端會先檢查資料是否過期、模型是否晚於資料，
  必要時補跑 `update_data.py` / `retrain_models.py`，最後再執行 `hourly_check.py`
  並等待新的 report。這段已改成背景工作，所以訓練很久時只會顯示執行中，
  不會因 request timeout 被誤報成失敗
- Grid Bot 建立前不再只顯示每格價差。後端現在會先做 fee-aware preview，
  以最不利一格計算毛利、手續費、扣費後淨利與損益兩平間距；紅燈直接阻擋，
  黃燈需二次確認，避免看起來有價差但扣完費其實虧損
- 價格來源失效、價格跳動過大或借貸池不足時，系統應 fail closed
- Backtest 現在把「總上限」和「內部分段上限」拆開：單次請求總上限為
  `trading.backtest_max_candles`（預設 `20,000`，root 可在交易設定頁調整），
  內部分段每批最多 `10,000` 根；因此像
  `BTC/USDT 2024-01-01 ~ 2024-12-31 @ 1h` 這類全年回測現在可直接執行，
  而且不需要前端自己切成多次獨立回測
- 回測日期欄位不再只丟給使用者一個 `20,000` 根上限。前端會依目前週期 +
  目前 `backtest_max_candles` 設定，即時計算「若保留開始時間，結束最晚可選到哪裡」與
  「若保留結束時間，開始最早可選到哪裡」，並同步收斂 `datetime-local`
  欄位的可選範圍
- **Backtest cap 是動態 setting，不是寫死的常數**：
  `services/trading/trading_engine.py` 仍保留 `MAX_BACKTEST_CANDLES = 20_000` 作為
  fallback，但實際 cap 透過 `trading_service.get_max_backtest_candles()` 取出。
  Root 可改的範圍是 `1,000 – 10,000,000`。
- **首次啟動會自動量測本機回測上限**：
  `services/server/startup.py:measure_backtest_capacity_if_needed` 在
  daemon thread 跑一輪 15 種 bot 的 probe（3 基本 + 12 system workflow），
  取最慢者作為「本機在 60 秒內可跑的根數」，自動填入 `backtest_max_candles`。
  方法/原理/實測結果見 [`BACKTEST_CAPACITY_AND_TEMPLATE_BENCHMARKS.md`](trading/BACKTEST_CAPACITY_AND_TEMPLATE_BENCHMARKS.md)。

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
- 你以為 Grid 仍是舊版半價 fee：
  不是。現在預設是現貨 fee 的 `75%`，也就是 `25%` 折扣；若你手算還在用
  `0.5x`，結果一定會偏差
- Grid 預覽看起來是綠燈，但你手算覺得會虧：
  先確認你看的是否是新版 preview。新版不是只看價差，而是後端直接回
  `每格毛利 - 手續費 = 扣費後淨利`；若仍不一致，應視為 release blocker
- 小本金借貸看起來 `interest_points` 還沒跳動：
  先看 `interest_exact_points` 或 `interest_carry_micropoints`；若還沒跨過整點，
  系統現在會先保留殘值，而不是直接進位多收。
- 借貸顯示和你預期的 APR 不同：
  先分辨倉位借的是 `BTC / ETH` 還是 `USDT / POINTS`。做多通常借 quote，
  放空通常借 base，所以同一個市場的多單與空單可以吃不同 APR 組
- root 把借貸池壓力倍率設成 `0`，但利率還像有加成：
  這在 `2026.05.04-066` 前是 bug；新版會正確尊重 `0`
- 回測長區間以前會卡在 `5000` 或 `10000`：
  先確認目前 release 是否已經是 `2026.05.04-067` 之後；新版會由後端自動分段續跑，
  但總量仍受 `20,000` 根保護，超過時會明確要求縮小區間
- BTC_trade 一鍵啟動等很久卻還沒結束：
  先看 root 設定頁的狀態列是否仍停在 `重訓 BTC_trade 模型` 或 `等待 BTC_trade 預測資料`。
  新版會保留背景工作並持續輪詢，不再把長時間訓練直接當 timeout；只有腳本真的失敗，
  或預測腳本跑完後仍等不到新的 `runtime/report_log_4h.jsonl`，才應視為異常
- 你刻意送很短或異常的回測資料，但系統卻像是自己換了一套行情：
  `2026.05.04-070` 之後，這不應再靜默發生。若 `candles < 2`，系統只有在
  顯式設定 `auto_fetch_reference_candles=true` 時才會抓 reference candles，
  否則應明確拒絕
- flat Bollinger 序列竟然出現交易：
  `2026.05.04-070` 之後，`std=0` 的 flat 序列不應再觸發
  `below_lower` / `above_upper`
- root 開了 trading，但 economy / PointsChain 沒先驗證：
  這是不完整部署。
- 網格 / workflow bot 看得到但不該直接上 production：
  先做回測、壓力、restore consistency。

## 測試方式

- 正常買賣、市價 / 限價、取消單
- 極小額 / 大額 / 負數 / 字串 / 科學記號輸入
- 多次累加、手續費、PnL、借貸利息手算驗證
- 驗證預設現貨 fee `0.10%`、Grid 折扣 `25%` 是否反映在 spot / grid / backtest
- 驗證 Grid preview 是否同時顯示每格毛利、手續費、扣費後淨利、損益兩平間距，
  且紅 / 黃 / 綠燈判定和後端 API 一致
- 驗證 `BTC / ETH 8% APR`、`USDT / POINTS 10% APR` 是否會依借入資產正確套用
- 驗證每 `1` 小時計息、不足 `1` 小時以 `1` 小時計，且前台顯示 `累積利息` /
  `下一次計息`
- 小本金借貸利息 carry 驗證，例如 `principal=50, daily_rate=1%, 24h -> interest_points=0, carry=0.5`
- 驗證現貨與借貸成交後，`volume_stats` / root report `volume_summary` 是否同步增加
- 融合價格自動權重 / 手動權重 / API 故障補位驗證
- DCA `max_runs=-1` 長期執行與重啟後續跑驗證
- `BTC/USDT 1h` 全年回測（約 `8784` 根）是否仍可通過，不再被舊的 `5000` 根上限擋住
- `10,001 ~ 20,000` 根 K 線時，是否由後端自動分段續跑，且 DCA / workflow / 持倉狀態不會在段與段之間被重置
- `candles < 2` 時是否明確拒絕；只有顯式 opt-in 才允許後端抓 reference candles
- flat Bollinger 序列是否仍誤觸發；異常跳躍 candle 是否會被 skip 並在回測結果留下 warning
- workflow `stop_loss_percent` / `take_profit_percent` 是否明確維持 long-only
  語義；若測到 short / futures 也需要這種條件，必須獨立設計與驗證
- 交易機器人稽核 dashboard 是否正確區分 `未稽核` 與綠 / 黃 / 紅燈
- `scripts/security/pentest/trading_stress_pentest.py`
- `scripts/trading/validation/trading_workflow_template_validation.py`
- `scripts/trading/probes/backtest_20000_probe.py`
- snapshot / restore 後狀態一致性

## 相關文件連結

- [TRADING.md](trading/TRADING.md)
- [07_POINTSCHAIN.md](07_POINTSCHAIN.md)
- [11_QA_TESTING.md](11_QA_TESTING.md)
- [security/TRADING_STRESS_PENTEST.md](security/TRADING_STRESS_PENTEST.md)
- [workflows/README.md](../workflows/README.md)


---

## PointsChain v2 區塊鏈化規劃 (2026-05-04 拍板, 尚未實作)

本模組未來將與全站 PointsChain v2 區塊鏈化整合：

- 工程設計：[`docs/AGENTS/research/BLOCKCHAIN/POINTSCHAIN_ENGINEERING.md`](AGENTS/research/BLOCKCHAIN/POINTSCHAIN_ENGINEERING.md)
- 用戶白皮書：[`docs/AGENTS/research/BLOCKCHAIN/POINTSCHAIN_WHITEPAPER.md`](AGENTS/research/BLOCKCHAIN/POINTSCHAIN_WHITEPAPER.md)
- 地址規格：[`docs/AGENTS/research/BLOCKCHAIN/POINTS_WALLET_ADDRESSING.md`](AGENTS/research/BLOCKCHAIN/POINTS_WALLET_ADDRESSING.md)
- 轉帳 API：[`docs/AGENTS/research/BLOCKCHAIN/POINTS_TRANSFER_API.md`](AGENTS/research/BLOCKCHAIN/POINTS_TRANSFER_API.md)
- 多簽錢包：[`docs/AGENTS/research/BLOCKCHAIN/MULTISIG_WALLETS.md`](AGENTS/research/BLOCKCHAIN/MULTISIG_WALLETS.md)
- QA Mining / 貢獻獎勵 (Phase 7)：[`docs/AGENTS/research/BLOCKCHAIN/POINTS_MINING_REWARDS.md`](AGENTS/research/BLOCKCHAIN/POINTS_MINING_REWARDS.md)
- QA / Release Gate：[`docs/AGENTS/research/BLOCKCHAIN/POINTSCHAIN_QA.md`](AGENTS/research/BLOCKCHAIN/POINTSCHAIN_QA.md)

**狀態：設計已拍板（root, 2026-05-04），尚未實作完成。**
