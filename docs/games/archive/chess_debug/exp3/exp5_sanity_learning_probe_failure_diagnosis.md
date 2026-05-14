# EXP5 - Sanity Learning Probe Failure Diagnosis

## 前一個實驗暴露的問題
Exp4 仍無法證明模型會修正指定錯誤，需診斷 expected move 為何餵進 replay 後 final top1 不變。

## 實驗目標與要求
目標要求：

- 診斷為什麼明確餵入 `expected=e7e5` 後，after top1 仍是 `a7a5`。
- 驗證 replay FEN、expected move、encoded move id、legal mask、target policy index。
- 驗證 move encode/decode、checkpoint load、overfit-one-position、policy logits。

結果：

- 確認 expected move 進入 dataset，legal mask 合法，encode/decode 沒有明顯映射錯誤。
- overfit-one-position 顯示 raw policy 可以被推動，但 final decision 不一定改變。
- 根因轉向：訓練目標與最終決策語義不一致。

經驗：

- 如果單一 FEN 高強度 overfit 都不能改 raw top1，才是資料/label/optimizer/load bug。
- 本輪更像 final decision path 把 raw policy 學到的訊號蓋掉。

## 實驗命令完整全文
```text
沒有獨立實跑 artifact；此輪為設計/診斷節點。
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
無獨立 run table；結果由後續實驗承接。

## 結果判讀
本輪是診斷或設計節點，主要價值是建立下一輪實驗假設。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
早期驗證節點；後續由 exp3/exp4 共用 gate surface 承接。
