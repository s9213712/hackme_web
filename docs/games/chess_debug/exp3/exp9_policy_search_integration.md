# EXP9 - Policy-Search Integration

## 前一個實驗暴露的問題
Exp8 顯示 raw policy 有局部學習，但 final decision 仍可能被 search/static eval 擋住。

## 實驗目標與要求
目標要求：

- 新增 adaptive policy override。
- 比較 strict_search、balanced_fusion、policy_preferred。
- 報告 policy_search_disagreement_rate、override_success_rate、override_regression_rate、fusion_mode_comparison。
- tactic/blunder 不得因 override 退步。

結果：

- fusion/override 沒有造成明顯 tactic/blunder regression。
- 但 unseen variants 失敗主因仍是 raw policy 本身沒有把 expected move 排上來。

經驗：

- Search-policy fusion 不是當前主要 blocker。
- 不能用 override 彌補 raw policy generalization 不足，否則只是把錯誤決策包裝成 learned decision。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp9_exp3_quick_gate_20260510
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root /home/s92137/chess_results/exp9_exp3_quick_gate_20260510
```
### exp9_exp3_quick_gate_20260510_r2
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root /home/s92137/chess_results/exp9_exp3_quick_gate_20260510_r2
```
### exp9_exp3_quick_gate_20260510_r3
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root /home/s92137/chess_results/exp9_exp3_quick_gate_20260510_r3
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp9_exp3_quick_gate_20260510 | - | HIGH_RISK | - | 36.097 | - | - | 160.818 | true | - | - | - |
| exp9_exp3_quick_gate_20260510_r2 | - | - | - | - | - | - | - | - | - | - | - |
| exp9_exp3_quick_gate_20260510_r3 | - | HIGH_RISK | - | 33.17 | - | - | 134.672 | true | - | - | - |

最後一次 run 原始結果目錄：`/home/s92137/chess_results/exp9_exp3_quick_gate_20260510_r3`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
