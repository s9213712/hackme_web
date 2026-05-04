# Trading QA Regression Matrix

一句話說明：這份文件把交易系統每次都必跑的高風險回歸清單固定下來，避免只驗正常路徑、只看 engine 一致性，卻漏掉 reject-path、對抗輸入與財務邊界。

## 設計目的

Claude 與 Codex 的交易 QA 報告證明，同一套交易功能如果只做「正常案例 + 一致性驗證」，很容易漏掉：

- `candles=[]` / `1 candle` 這種應拒絕卻被靜默改抓外部行情的路徑
- 指標在 `flat sequence` 上的錯誤觸發
- 異常跳價沒有 outlier / jump filter 的風險
- `trial_credit-only`、小本金、整數點數等帳務邊界
- `30s polling` 造成的 stop-loss / liquidation / grid 漏觸發

這份矩陣的目標不是取代完整交易 QA 任務書，而是把「不管誰來測都不能省」的回歸最小集合固定下來。

## 使用方法

1. 先讀 [TRADING_SYSTEM_QA_FOR_AGENTS.md](TRADING_SYSTEM_QA_FOR_AGENTS.md) 了解完整任務邊界。
2. 在隔離 `/tmp` runtime 跑完整交易 QA 前，先用這份矩陣規劃案例。
3. 每次只要改到以下任一領域，就必須逐項勾過本矩陣：
   - `routes/trading.py`
   - `services/trading_engine.py`
   - `public/js/56-trading.js`
   - `public/js/trading-workflow-editor.js`
   - 交易 worker / scheduler / price-source / liquidation / DCA / grid / backtest 相關設定
4. 若某項無法實測，必須在報告中寫明阻塞、替代驗證方式與最小重現腳本。

## 原理

- 交易 QA 不能只驗「有沒有報錯」，要驗「是否拒絕錯的輸入」、「是否在極端行情仍維持不變量」。
- `engine_vs_replay_match = yes` 只代表兩邊一致，不代表兩邊都正確。
- 真實歷史區間回測和 synthetic 對抗序列都要跑；前者看市場區間表現，後者挖規則漏洞。
- 每個高風險模組都要同時對帳：
  - API 回應
  - 成交 / 倉位 / 利息 / 手續費
  - wallet / debt / reserve / audit event

## 必跑矩陣

### 1. Backtest API 輸入驗證

每次都必測：

- `candles=[]`
- `candles=[single candle]`
- `candles` 長度超過上限
- `negative / zero / NaN / null / missing / out-of-order tick`
- `market_symbol` 合法但資料不完整
- 使用者自帶 `candles` 時，不得靜默改抓外部行情，除非 API 明確 opt-in

必須確認：

- 應拒絕的案例回 `4xx` 或清楚錯誤
- 若系統選擇略過非法 tick，報告要明寫這是設計，不可默默吃掉且不留痕
- `data_source` 必須可解釋，不可讓使用者誤以為仍在測自帶資料

### 2. Workflow Template 語義驗證

12 個 system templates 每個都至少要有：

- `normal trigger`
- `no trigger`
- `boundary equal`
- `jump-over trigger`
- `flat sequence`
- `has_position / no_position` 前置條件
- `balance insufficient`
- `restart or repeated-scan dedupe`

特別是指標型 template 必測：

- `flat 100000,100000,...`
- 低波動但非完全平盤
- 極端單邊上漲 / 下跌

必須確認：

- 不只是 `trade_count > 0`
- 要檢查「是不是在該觸發時才觸發」
- 風控型 template 若本來需要前置持倉，報告必須註明它是 coverage node，不是獨立 entry strategy

### 3. Backtest 數學對帳

至少固定保留這些手算類型：

- 單次 round-trip
- 分批買入賣出
- 持倉未平倉
- 小額資金
- 小數精度 / truncation / rounding
- 手續費前後順序
- 滑價
- 價格跳空
- 極端報酬幻覺案例，例如 `100 -> 10 -> 150`

必須確認：

- 手算結果 vs 系統結果
- 差異是否來自明確設計，例如 base unit / round-half-up / ceil
- 若差異不可解釋，就不是「小誤差」，而是 bug

### 4. Grid Trading 狀態機

每次都必測：

- 震盪
- 單邊下跌
- 單邊上漲
- 跳空
- V 反轉
- sawtooth
- 極端暴跌直到超出 grid lower bound

每筆成交後都要驗：

- 反向掛單是否存在
- 是否有重複掛單
- 是否有漏掛單
- 是否有孤兒掛單
- fee / inventory / cash 是否一致

### 5. DCA 時間與上限

每次都必測：

- 正常 interval 觸發
- 未到 interval 不得重複下單
- restart 後是否重複單
- backdate `last_run_at` 後是否補單
- `max_runs = 1`
- `max_runs > 1`
- `max_runs = -1` 不限制
- 餘額不足
- 極端行情下持續執行

### 6. Spot / Matcher / Order Life Cycle

每次都必測：

- market buy
- market sell
- limit buy
- limit sell
- cancel
- insufficient balance
- multiple orders same window
- execution ordering
- closed order 不得再次成交
- canceled order 不得成交

若當前架構不支援 partial fill，也要明寫：

- 是架構限制還是測試覆蓋不足
- 哪條 code path 實際沒有被走到

### 7. Lending / Margin / Liquidation

每次都必測：

- 小本金利息，例如 `principal=50`
- `wallet=0 + trial_credit_only`
- `opened_at` 時間倒退後的利息累計
- 剛好等於清算線
- 跳空穿越清算線
- 極端穿倉後是否 clamp / bad debt / insurance
- negative balance invariant
- close / liquidate 後 principal / interest / fee 對帳

必須確認：

- `debt >= 0`
- `fee >= 0`
- 若系統宣稱不允許負餘額，wallet / asset 不得掉到負值

### 8. 價格來源 / 融合價格 / 備援

每次只要改到交易所來源，就必測：

- 單一 provider 正常
- 單一 provider timeout / 5xx
- 多 provider 中一個掛掉
- 多 provider 中一個價格離群
- manual weights 總和正常
- manual weights 全部設成 `0`
- auto-depth 與 manual-weight 切換
- stale cache fallback

必須確認：

- 融合價確實由多來源計算，而不是只回第一家成功的值
- 失效來源被排除後，其餘健康來源會重算比例
- root 設定權重後，前後端顯示與實際計算一致

### 9. Scheduler / Scan Interval / Tick Loss

每次都必測：

- full tick: `[100, 80, 120]`
- sampled tick: `[100, 120]`
- stop-loss / liquidation / grid level 在同一 polling window 內穿越
- worker restart 中價格觸發
- 多 bot 同時 scan

必須明確回答：

- 現在是 `polling` 還是 `tick-driven`
- 哪些情境會漏觸發
- 若仍是 polling，該 interval 是否已足夠
- 是否需要 tick replay 補償

### 10. 報告與 issue 品質

每次交易 QA 報告都必須含：

- synthetic 對抗序列
- 真實歷史區間
- 手算案例
- evidence JSON / log / commands
- 已知限制與 blocked cases
- 與前次 issue 的關聯

若發現 bug，issue 內容至少要有：

- 重現步驟
- 預期結果
- 實際結果
- 嚴重度
- 證據路徑
- 建議修法

## 失敗情境與提示

- 只看 `trade_count` 或 `pnl`：
  不夠，很多 bug 是「不該成交卻成交」。
- 只用真實歷史區間：
  不夠，市場不一定自然撞到 reject-path 或 flat-sequence。
- 只用 synthetic 對抗序列：
  不夠，還要確認真實市場窗口下沒有結構性偏差。
- 只跑 pytest / validation script：
  不夠，既有 oracle 本身可能已經錯。
- 發現 `by design` 就直接略過：
  先確認這是不是 UX / 任務定義不清，而不是單純不是 bug。

## 測試方式

建議至少同時保留兩種執行方式：

1. 真實歷史區間：
   - full-cycle
   - calm regime
   - crash regime
   - whipsaw regime
2. synthetic 對抗序列：
   - flat
   - jump
   - gap collapse
   - sampled vs full tick
   - zero / negative / NaN / missing

執行後，至少更新：

- `docs/AGENTS/reports/<agent>/.../report.md`
- `issue_body.md`
- `commands.log`
- `evidence/workflow`
- `evidence/grid`
- `evidence/backtest`
- `evidence/lending`
- `evidence/liquidation`
- `evidence/extreme_market`
- `evidence/scan_interval`

## 相關文件連結

- [QA_MISSION_FOR_AGENTS.md](QA_MISSION_FOR_AGENTS.md)
- [TRADING_SYSTEM_QA_FOR_AGENTS.md](TRADING_SYSTEM_QA_FOR_AGENTS.md)
- [11_QA_TESTING.md](../11_QA_TESTING.md)
- [reports/claude/README.md](reports/claude/README.md)
- [reports/codex/README.md](reports/codex/README.md)
