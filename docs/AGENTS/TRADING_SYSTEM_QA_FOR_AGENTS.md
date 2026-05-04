你現在是資深量化交易系統 QA 工程師。請針對目前hackme_web/專案中的交易系統，在隔離環境(複製到/tmp中進行完整實測、壓測、數學驗算與 GitHub issue 回報，報告相關測試腳本及結果報告放reports/harmes中，不要改代碼，製作報告跟issues，issues前記得查有沒有重複

先讀：

- [TRADING_QA_REGRESSION_MATRIX.md](TRADING_QA_REGRESSION_MATRIX.md)

這份任務書定義完整測試範圍；上面的回歸矩陣則定義「每次都不能省略」的高風險案例。若只完成本文件的大項目、但漏掉回歸矩陣裡的 reject-path、flat-sequence、gap、sampled-vs-full-tick、trial-credit-only 等案例，視為測試不完整。

重要規則：
1. 不得修改 production runtime、production DB、production state、production logs。
2. 不得使用真實金鑰、真實資產、真實交易所下單。
3. 必須在 /tmp/hackme_trading_qa_<timestamp>/ 建立隔離測試環境。
4. 必須複製目前專案到隔離目錄後執行測試。
5. 必須保留所有測試證據，包括：
   - 測試指令
   - 測試資料
   - 模擬價格序列
   - 預期結果
   - 實測結果
   - 成交紀錄
   - 餘額變化
   - 手續費計算
   - 利息計算
   - 清算紀錄
   - 錯誤 log
6. 不可以只做靜態程式碼檢查；必須實際執行測試。
7. 若某項無法實測，必須明確說明阻塞原因，並提供最小重現測試腳本或替代驗證方式。
8. 測試完成後，請建立 GitHub issue，上傳完整測試報告與所有重大問題。

請依照以下任務執行。

------------------------------------------------------------
A. 建立隔離測試環境
------------------------------------------------------------

1. 在 /tmp 建立隔離環境：

   RUNTIME="/tmp/hackme_trading_qa_$(date +%s)"

2. 將目前專案完整複製到該目錄，但排除：
   - .git
   - runtime
   - logs
   - node_modules
   - vendor
   - __pycache__
   - .pytest_cache
   - .venv
   - dist
   - build

3. 所有測試 DB、state、logs、cache 都必須指向 /tmp 隔離環境。

4. 啟動測試服務時，使用隨機 port，不得使用 production port。

5. 建立測試報告目錄：

   /tmp/hackme_trading_qa_report_<timestamp>/

報告目錄至少包含：

- report.md
- issue_body.md
- commands.log
- evidence/
- evidence/workflow/
- evidence/grid/
- evidence/backtest/
- evidence/lending/
- evidence/spot/
- evidence/extreme_market/
- evidence/fees/
- evidence/liquidation/
- evidence/scan_interval/

------------------------------------------------------------
B. 系統探索
------------------------------------------------------------

請先掃描並確認以下模組位置、API、資料表、設定檔、測試入口：

1. 定投機器人 DCA bot
2. Workflow bot
3. 回測機器人 Backtest bot
4. Grid trading bot
5. 現貨交易 spot trading
6. 借貸交易 lending / margin trading
7. 利息計算
8. 清算邏輯
9. 手續費計算
10. 掃描間隔 / scheduler / cron / worker
11. 價格來源 / exchange adapter / weighted exchange / mock exchange
12. 掛單、成交、餘額、倉位、交易紀錄資料結構

請在 report.md 中記錄實際找到的檔案路徑與入口。

------------------------------------------------------------
C. Workflow bot 12 templates 實測
------------------------------------------------------------

請找出 workflow bot 的全部 12 項 templates。

對每一個 template 都必須實測：

1. template 名稱
2. template 設計邏輯
3. 測試價格序列
4. 測試時間序列
5. 預期觸發條件
6. 預期成交紀錄
7. 實際觸發結果
8. 實際成交紀錄
9. 是否符合預期
10. 若不符合，列出錯誤原因與重現步驟

必須至少測以下情境：

- 正常觸發
- 不應觸發
- 邊界價格剛好等於條件
- 價格跳過觸發點
- 多條件 AND
- 多條件 OR
- 時間條件
- 連續觸發防重複
- 手續費計算
- 餘額不足
- 極端行情
- API / worker 重啟後是否仍正確運作

請輸出每個 template 的 JSON 證據檔，例如：

evidence/workflow/template_<name>.json

格式至少包含：

{
  "template": "...",
  "price_sequence": [],
  "time_sequence": [],
  "expected_triggers": [],
  "actual_triggers": [],
  "expected_orders": [],
  "actual_orders": [],
  "expected_balances": [],
  "actual_balances": [],
  "expected_fees": [],
  "actual_fees": [],
  "match": true,
  "issues": []
}

------------------------------------------------------------
D. Grid trading 實測
------------------------------------------------------------

請針對 grid-trade 測試以下項目：

1. 初始網格掛單是否正確
2. 價格下跌時是否觸發買單
3. 買單成交後是否自動在反方向重新掛賣單
4. 價格上漲時是否觸發賣單
5. 賣單成交後是否自動在反方向重新掛買單
6. 是否重複掛單
7. 是否漏掛單
8. 是否出現孤兒掛單
9. 是否正確扣除手續費
10. 餘額與持倉是否正確
11. 單邊暴跌時是否停止錯誤加倉
12. 單邊暴漲時是否停止錯誤賣出
13. worker 重啟後是否恢復掛單狀態
14. 多 grid bot 同時運作是否互相干擾

至少使用以下價格序列：

1. 震盪行情：
   100, 99, 98, 99, 100, 101, 102, 101, 100

2. 單邊下跌：
   100, 95, 90, 85, 80, 70

3. 單邊上漲：
   100, 105, 110, 120, 130

4. 跳空行情：
   100, 80, 120, 60, 140

請產生：

evidence/grid/grid_trade_result.json

並在 report.md 中明確列出每一筆成交後的反向掛單是否存在。

------------------------------------------------------------
E. 回測機器人實測與手算比對
------------------------------------------------------------

請建立固定歷史價格資料，不得依賴外部行情。

至少測試：

1. 單次買入賣出
2. 多次買入賣出
3. 持倉未平倉
4. 手續費
5. 滑價
6. 小數精度
7. rounding / truncation
8. 起始資金不足
9. 空資料
10. 價格異常值
11. 極端波動
12. 與實際手算結果比對

請至少建立以下手算案例：

案例 1：
- 初始 USDT：1000
- 價格：100 -> 120
- 買入數量：1 BTC
- fee rate：0.1%
- 預期買入手續費：100 * 0.001 = 0.1 USDT
- 預期賣出手續費：120 * 0.001 = 0.12 USDT
- 預期淨利：120 - 100 - 0.1 - 0.12 = 19.78 USDT

案例 2：
- 初始 USDT：1000
- 價格：100 -> 90 -> 110
- 分批買入
- 手算平均成本、手續費、最終盈虧

案例 3：
- 價格跳空：
  100 -> 50 -> 150
- 驗證止損、止盈、成交價與回測 engine 是否合理

請輸出：

evidence/backtest/backtest_manual_comparison.json

格式至少包含：

{
  "case": "...",
  "manual_result": {},
  "system_result": {},
  "difference": {},
  "match": true,
  "issues": []
}

------------------------------------------------------------
F. 定投機器人 DCA 實測
------------------------------------------------------------

請測試：

1. 是否依照設定時間觸發
2. 是否依照設定金額買入
3. 是否正確計算買入數量
4. 是否正確扣除手續費
5. 是否正確更新平均成本
6. 餘額不足時是否停止或報錯
7. 時間跨日、跨週、跨月是否正確
8. worker 停止後恢復是否補單或避免重複單
9. 極端行情下是否仍按規則執行

請輸出：

evidence/dca/dca_result.json

若沒有 dca evidence 目錄，請建立。

------------------------------------------------------------
G. 現貨交易實測
------------------------------------------------------------

請測試：

1. 市價單
2. 限價單
3. 買單
4. 賣單
5. 部分成交
6. 完全成交
7. 取消掛單
8. 餘額不足
9. 手續費
10. 小數精度
11. 價格跳空
12. 多筆掛單同時成交
13. 掛單成交順序
14. 成交紀錄與餘額是否一致

請輸出：

evidence/spot/spot_trading_result.json

------------------------------------------------------------
H. 借貸交易 / Margin / Lending 實測
------------------------------------------------------------

請測試：

1. 借貸是否正確建立
2. 借款時間是否正確記錄
3. 利息是否依照時間正確累計
4. 利息是否按設定週期計算
5. 還款是否正確扣除本金與利息
6. 抵押品價值是否正確計算
7. LTV 是否正確
8. margin ratio 是否正確
9. 清算線是否正確
10. 價格跌破清算線是否正確觸發清算
11. 價格剛好等於清算線是否符合設計
12. 價格跳空穿越清算線是否仍能清算
13. 清算後餘額是否正確
14. 清算手續費是否正確
15. 是否可能產生負餘額
16. 是否有防負餘額機制
17. 極端行情穿倉時系統如何處理

請建立手算案例：

案例 1：
- 抵押品：1 BTC
- BTC 初始價格：100
- 借款：50 USDT
- 利率：每日 1%
- 經過 1 天
- 預期利息：0.5 USDT
- 預期債務：50.5 USDT

案例 2：
- 抵押品：1 BTC
- 借款：70 USDT
- 清算 LTV：80%
- BTC 價格從 100 跌到 80
- 抵押價值：80
- LTV：70 / 80 = 87.5%
- 預期觸發清算

案例 3：
- 價格跳空：
  100 -> 30
- 檢查是否穿倉
- 檢查是否防止負餘額
- 檢查清算後帳戶狀態

請輸出：

evidence/lending/lending_result.json
evidence/liquidation/liquidation_result.json

------------------------------------------------------------
I. 手續費完整驗證
------------------------------------------------------------

請找出系統所有手續費設定，包括：

1. spot fee
2. maker fee
3. taker fee
4. grid fee
5. workflow fee
6. backtest fee
7. lending interest
8. liquidation fee
9. rounding rule
10. minimum fee
11. fee asset 是 base 還是 quote

請針對每種交易測試手續費是否正確。

請輸出：

evidence/fees/fee_result.json

必須列出：

{
  "module": "...",
  "trade": {},
  "expected_fee": "...",
  "actual_fee": "...",
  "match": true
}

------------------------------------------------------------
J. 極端行情壓測
------------------------------------------------------------

請創造各式極端行情考驗系統。

至少包含：

1. 快速暴跌：
   100, 95, 90, 80, 60, 40, 20

2. 快速暴漲：
   100, 120, 150, 200, 300

3. V 型反轉：
   100, 80, 50, 20, 60, 100, 150

4. 鋸齒震盪：
   100, 80, 120, 70, 130, 60, 140

5. 跳空：
   100, 10, 150

6. 價格歸零：
   100, 50, 10, 1, 0

7. 負價格或非法價格：
   100, -1, 100

8. NaN / null / missing tick

9. 重複 tick

10. 延遲 tick / out-of-order tick

11. 多交易所報價分歧：
    exchange A = 100
    exchange B = 10
    exchange C = 105

12. 流動性不足 / partial fill

13. worker 重啟中價格觸發

14. DB 寫入延遲

15. 多 bot 同時觸發

請針對每種行情驗證：

- workflow 是否正確觸發
- grid 是否正確成交與反向掛單
- DCA 是否正確執行
- backtest 是否正確計算
- lending 是否正確清算
- spot 掛單是否正確成交
- 手續費是否正確
- 餘額是否正確
- 是否產生負餘額
- 是否漏單
- 是否重複單
- 是否發生 race condition

請輸出：

evidence/extreme_market/extreme_market_result.json

------------------------------------------------------------
K. 混合加權交易所 / weighted exchange 測試
------------------------------------------------------------

若系統有混合加權交易所價格機制，請測試：

1. 多交易所價格平均
2. 權重是否正確
3. 極端離群值是否被排除或降低影響
4. 某交易所斷線是否正確處理
5. 某交易所價格延遲是否正確處理
6. 是否能減緩單一交易所極端波動
7. 是否會導致錯過清算或錯誤觸發

測試案例：

Case A:
- A = 100, weight = 0.5
- B = 110, weight = 0.3
- C = 90, weight = 0.2
- 預期價格 = 100*0.5 + 110*0.3 + 90*0.2 = 101

Case B:
- A = 100
- B = 10
- C = 102
- 檢查是否有 outlier filter

Case C:
- A = missing
- B = 100
- C = 102
- 檢查 missing exchange 是否正確處理

請輸出：

evidence/extreme_market/weighted_exchange_result.json

------------------------------------------------------------
L. 掃描間隔 / scheduler 是否足以應付極端行情
------------------------------------------------------------

請找出目前系統設定的：

1. bot scan interval
2. workflow scan interval
3. grid scan interval
4. liquidation scan interval
5. lending interest update interval
6. price fetch interval
7. order matching interval

請實測：

1. 在 scan interval 內價格快速穿越觸發點是否會漏觸發
2. 價格 100 -> 80 -> 120，如果 scan 只看到 100 和 120，是否漏掉 80 的清算或止損
3. liquidation interval 是否足以處理急跌
4. grid interval 是否導致重複掛單或漏掛單
5. workflow interval 是否導致條件觸發延遲
6. 多 bot 同時 scan 是否造成 race condition
7. 是否需要 event-driven price tick，而不是固定 interval

請輸出：

evidence/scan_interval/scan_interval_result.json

並在 report.md 中明確回答：

- 目前掃描間隔是否足以應付極端行情？
- 哪些情境會漏觸發？
- 建議 interval 是多少？
- 是否建議改成 tick-driven / event-driven？
- 是否需要補做 historical tick replay？

------------------------------------------------------------
M. 防負餘額 / 穿倉機制
------------------------------------------------------------

請特別檢查：

1. 現貨交易是否可能造成負 USDT
2. 現貨交易是否可能造成負 asset balance
3. 借貸清算是否可能造成負餘額
4. 價格跳空穿倉後是否有 insurance fund / bad debt / balance clamp
5. bot 是否會在負餘額狀態繼續交易
6. 系統是否有 invariant check

請建立 invariant 測試：

任何時候：

- USDT balance >= 0，除非系統明確允許 debt
- asset balance >= 0，除非系統明確允許 short
- debt >= 0
- fee >= 0
- executed quantity > 0
- executed price > 0
- order status 不得互相矛盾
- closed order 不得再次成交
- canceled order 不得成交

請輸出：

evidence/liquidation/negative_balance_result.json

------------------------------------------------------------
N. 最終報告格式
------------------------------------------------------------

請產生 report.md，格式如下：

# Trading System QA Report

## 1. 測試環境
- runtime path:
- report path:
- commit hash:
- branch:
- test started at:
- test ended at:

## 2. 測試摘要
| 模組 | 測試數 | 通過 | 失敗 | 阻塞 | 嚴重問題 |
|---|---:|---:|---:|---:|---:|

## 3. Workflow 12 Templates
對每個 template 列出：
- template name
- 設計預期
- 測試價格序列
- 預期成交紀錄
- 實際成交紀錄
- 是否通過
- evidence file

## 4. Grid Trading
列出：
- 初始掛單
- 每次成交
- 成交後反向掛單
- 手續費
- 餘額
- 是否通過

## 5. Backtest Bot
列出：
- 手算案例
- 系統結果
- 差異
- 是否通過

## 6. DCA Bot
列出觸發時間、成交紀錄、平均成本與手續費。

## 7. Spot Trading
列出市價單、限價單、部分成交、取消單、餘額不足等結果。

## 8. Lending / Margin / Liquidation
列出利息計算、LTV、清算觸發、穿倉、防負餘額結果。

## 9. Fees
列出所有手續費的 expected vs actual。

## 10. Extreme Market
列出所有極端行情下，各 bot、spot、lending、liquidation 的表現。

## 11. Weighted Exchange
說明混合加權交易所是否真的能減緩波動，以及是否會造成錯誤延遲。

## 12. Scan Interval Assessment
明確回答目前 scan interval 是否足以應付極端行情。

## 13. Issues Found
每個 issue 請包含：
- severity: critical / high / medium / low
- module
- description
- expected result
- actual result
- reproduction steps
- evidence file
- suggested fix

## 14. 結論
請明確回答：
- 系統是否可以安全處理極端行情？
- 是否存在穿倉風險？
- 是否存在負餘額風險？
- 是否存在漏觸發風險？
- 是否存在手續費錯算？
- 是否建議上線？
- 若不建議，上線前必修項目是什麼？

------------------------------------------------------------
O. 建立 GitHub issue
------------------------------------------------------------

測試完成後，請產生 issue_body.md。

GitHub issue title：

[QA] Trading system full isolation test: bots, fees, lending, liquidation, extreme market

issue body 必須包含：

1. 測試摘要
2. 所有 critical / high issues
3. report.md 內容摘要
4. evidence 檔案路徑
5. 重現方式
6. 建議修正順序

若 gh CLI 可用且已登入，請執行：

gh issue create \
  --title "[QA] Trading system full isolation test: bots, fees, lending, liquidation, extreme market" \
  --body-file /tmp/hackme_trading_qa_report_<timestamp>/issue_body.md

若 gh CLI 不可用或未登入，請不要跳過，請在最後輸出：
- issue_body.md 的完整路徑
- 建議手動建立 issue 的 title
- issue body 內容

------------------------------------------------------------
P. 最後輸出
------------------------------------------------------------

最後請直接回報：

1. report.md 路徑
2. issue_body.md 路徑
3. GitHub issue URL，如果成功建立
4. 測試總數
5. 通過數
6. 失敗數
7. critical issues 數量
8. high issues 數量
9. 是否建議上線：Yes / No
10. 最重要的三個風險

請開始執行。
