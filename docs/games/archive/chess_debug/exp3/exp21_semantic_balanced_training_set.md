# EXP21 - Semantic-balanced Training Set

## 前一個實驗暴露的問題
Exp20 證明考卷公平，但 train/validation semantic coverage 不完整。

## 實驗目標與要求
目標要求：

- train/validation replay 也要和 clean gate 一樣語義平衡。
- 五類 semantic classes 每類至少 N 題，且 easy/medium/hard 都有。
- 若 train 或 validation 任一 semantic class count=0，promotion false，reason=`train_validation_semantic_coverage_incomplete`。
- 報告 train_semantic_distribution、validation_semantic_distribution、train_to_gate_semantic_gap、pass_rate_by_semantic、failed_by_semantic_top3。

結果：

- train/validation semantic coverage 補齊。
- 但 sampling 仍失衡：cp10 e_pawn 過重，cp20 flank 過重。
- kingside/development 仍 0/9，retention 也失敗。

經驗：

- 「有教材」不等於「訓練時每類權重公平」。
- 下一步要做 class-balanced sampling / loss weighting。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp21_semantic_balanced_training_set
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp2 --output-root <chess_results>/exp21_semantic_balanced_training_set
```
### exp21_semantic_balanced_training_set_r2
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp2 --output-root <chess_results>/exp21_semantic_balanced_training_set_r2
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp21_semantic_balanced_training_set | - | HIGH_RISK | - | 43.542 | - | - | 895.195 | true | - | - | - |
| exp21_semantic_balanced_training_set_r2 | - | HIGH_RISK | - | 45.122 | - | - | 969.377 | true | - | - | - |

最後一次 run 原始結果目錄：`<chess_results>/exp21_semantic_balanced_training_set_r2`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
