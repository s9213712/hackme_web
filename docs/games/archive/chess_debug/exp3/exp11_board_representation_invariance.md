# EXP11 - Board Representation Invariance

## 前一個實驗暴露的問題
Exp10 hard-negative 有效但不足；low board embedding similarity 指向表徵不變性不足。

## 實驗目標與要求
目標要求：

- 加入 invariance / consistency loss。
- 同一棋理 variants 的 board embedding 應靠近。
- 加入 pairwise contrastive learning：positive pairs 同棋理/同 expected move，negative pairs 不同棋理/不同 expected move。
- 報告 embedding_similarity before/after、failed feature groups。

結果：

- low board embedding similarity 成為主要證據。
- 模型在 seen variants 可學，但 held-out 幾乎不泛化。
- 表徵層問題比單純 move margin 更明顯。

經驗：

- 泛化失敗不是只靠更大的 margin loss 能解決。
- 需要同時訓練 move target 與 board representation。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp11_exp3_quick_gate_20260510
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root <chess_results>/exp11_exp3_quick_gate_20260510
```
### exp11_exp3_quick_gate_20260510_r2
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root <chess_results>/exp11_exp3_quick_gate_20260510_r2
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp11_exp3_quick_gate_20260510 | - | PARTIAL | - | 28.232 | - | - | 124.348 | true | - | - | - |
| exp11_exp3_quick_gate_20260510_r2 | - | PARTIAL | - | 28.134 | - | - | 100.231 | true | - | - | - |

最後一次 run 原始結果目錄：`<chess_results>/exp11_exp3_quick_gate_20260510_r2`。

## 結果判讀
最後一次 run verdict=`PARTIAL`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
