# EXP17 - Central Pawn Structure 與 Move Semantics Disentanglement

## 前一個實驗暴露的問題
Exp16 建好乾淨題庫後，模型在 central/flank 語義上的泛化仍不足。

## 實驗目標與要求
目標要求：

- 將 replay/held-out 分群：e-pawn central break、d-pawn central break、flank pawn push、kingside aggression、development move。
- 加入 semantic-negative training。
- 報告 board semantic features：central control、pawn structure、king safety、development state、open/closed center、side-to-move pressure。
- 輸出 semantic confusion matrix。

結果：

- 第一次量化「錯在哪種棋理」。
- cp10 大量把 e-pawn central break 錯到 kingside aggression。
- cp20 對 d-pawn central break 常錯到 kingside aggression、flank pawn push、少量 e-pawn break。

經驗：

- 模型不是隨機亂走，而是過度偏向攻擊性兵推進語義。
- 語義邊界太粗，必須讓 embedding 空間分離不同 move semantics。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp17_semantic_disentanglement
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root /home/s92137/chess_results/exp17_semantic_disentanglement
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp17_semantic_disentanglement | - | HIGH_RISK | - | 32.828 | - | - | 328.678 | true | - | - | - |

最後一次 run 原始結果目錄：`/home/s92137/chess_results/exp17_semantic_disentanglement`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
