# EXP18 - Semantic Embedding Separation

## 前一個實驗暴露的問題
Exp17 顯示 e/d pawn break、kingside aggression、flank push semantic boundary 太模糊。

## 實驗目標與要求
目標要求：

- 加入 semantic contrastive loss。
- 同 semantic 類別 embedding 拉近，不同 semantic 類別拉遠。
- 建立 semantic centroid analysis，輸出 centroid distance、overlap score、nearest-confused semantic。
- 對 confusion matrix 中最常混淆 pair 增加 targeted replay pairs。

結果：

- semantic margin 與 centroid distance 開始被報告。
- 仍可看到 e-pawn/d-pawn/kingside/flank 之間邊界不夠 sharp。
- promotion gate 仍維持 false。

經驗：

- Move-level hard negatives 有幫助但不夠。
- 真正需要的是 semantic embedding separation，而不是只把某幾個錯步壓低。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp18_semantic_embedding_separation
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root <chess_results>/exp18_semantic_embedding_separation
```
### exp18_semantic_embedding_separation_r2
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root <chess_results>/exp18_semantic_embedding_separation_r2
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp18_semantic_embedding_separation | - | HIGH_RISK | - | 32.007 | - | - | 356.686 | true | - | - | - |
| exp18_semantic_embedding_separation_r2 | - | HIGH_RISK | - | 31.728 | - | - | 355.489 | true | - | - | - |

最後一次 run 原始結果目錄：`<chess_results>/exp18_semantic_embedding_separation_r2`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
