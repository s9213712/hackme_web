# EXP10 - Raw Policy Unseen Generalization 與 Hard Negatives

## 前一個實驗暴露的問題
Exp9 確認 fusion 不是主因；unseen 失敗主要來自 raw policy 沒把 expected move 排上來。

## 實驗目標與要求
目標要求：

- 擴大 supervised variant dataset，但不增加 self-play。
- 明確 train/validation/held-out split。
- 加入 hard-negative training：`a7a5`、`f8a3`、`b8c6` 等常見錯誤。
- 報告 expected vs hard-negative margin、failed_unseen_cases。

結果：

- Hard negatives 有幫助，但不足以讓 held-out 泛化過 gate。
- failed_unseen_cases 顯示 expected rank 常掉到 6-12。
- blocking_features 開始指向 board representation 問題。

經驗：

- 問題不是盤數，而是 supervised policy generalization。
- 只壓 hard negatives 不能替代 board semantics representation。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp10_exp3_quick_gate_20260510
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root /home/s92137/chess_results/exp10_exp3_quick_gate_20260510
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp10_exp3_quick_gate_20260510 | - | PARTIAL | - | 28.392 | - | - | 122.723 | true | - | - | - |

最後一次 run 原始結果目錄：`/home/s92137/chess_results/exp10_exp3_quick_gate_20260510`。

## 結果判讀
最後一次 run verdict=`PARTIAL`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
