# EXP15 - Held-out Label Quality Gate

## 前一個實驗暴露的問題
Exp14 發現 held-out 有多個 questionable labels，promotion gate 可能被錯標污染。

## 實驗目標與要求
目標要求：

- 每個 held-out case 輸出 expected_move、legal、static_best_move、static_cp_delta、expected_rank、label_quality。
- static_cp_delta 落後超過 -150cp 標 questionable，超過 -300cp 不可作為 promotion hard label。
- clean/questionable/invalid 分流，questionable 不參與 gate。

結果：

- questionable labels 被排除後，gate 更可信。
- clean held-out 數量太少，cp20 clean cases 只有 4 題，hard clean 也只有 4 題。
- cp20 clean pass rate 只有 0.25。

經驗：

- exp15 證明 gate 不是壞了，而是題庫還不夠當正式 promotion 證據。
- 下一步必須建立足夠數量、標籤可信、難度分級清楚的 clean held-out set。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp15_label_quality_gate
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root /home/s92137/chess_results/exp15_label_quality_gate
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp15_label_quality_gate | - | HIGH_RISK | - | 33.001 | - | - | 143.295 | true | - | - | - |

最後一次 run 原始結果目錄：`/home/s92137/chess_results/exp15_label_quality_gate`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
