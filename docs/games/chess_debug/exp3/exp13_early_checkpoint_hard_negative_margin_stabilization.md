# EXP13 - Early Checkpoint 與 Hard-negative Margin Stabilization

## 前一個實驗暴露的問題
Exp12 的 checkpoint@10 不穩且 hard-negative margin 偏負，需穩定 early checkpoint。

## 實驗目標與要求
目標要求：

- checkpoint@10 前避免混入太難的 hard-held-out 類型。
- hard negatives 漸進加入。
- 對 `a7a5`、`h7h5`、`f8a3`、`b8a6`、`b8c6` 做 margin loss。
- 報告 hard_negative_margin_table、early_checkpoint_failure_analysis、embedding_similarity_delta_by_group。

結果：

- cp10 仍未穩定達到 unseen/hard-held-out 門檻。
- hard-negative margin 部分改善，但仍可為負。
- early checkpoint failure 顯示不是只要多訓練到 cp20 就可信。

經驗：

- Gate 不應因 cp20 偶然通過而放行。
- cp10/cp20 都要達最低泛化與 retention 門檻。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp13_exp3_quick_gate_20260510T_exp13
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root /home/s92137/chess_results/exp13_exp3_quick_gate_20260510T_exp13
```
### exp13_exp3_quick_gate_20260510T_exp13_r2
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root /home/s92137/chess_results/exp13_exp3_quick_gate_20260510T_exp13_r2
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp13_exp3_quick_gate_20260510T_exp13 | - | HIGH_RISK | - | 32.622 | - | - | 144.932 | true | - | - | - |
| exp13_exp3_quick_gate_20260510T_exp13_r2 | - | HIGH_RISK | - | 31.807 | - | - | 140.993 | true | - | - | - |

最後一次 run 原始結果目錄：`/home/s92137/chess_results/exp13_exp3_quick_gate_20260510T_exp13_r2`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
