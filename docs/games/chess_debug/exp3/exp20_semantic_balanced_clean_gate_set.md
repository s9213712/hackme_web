# EXP20 - Semantic-balanced Clean Gate Set

## 前一個實驗暴露的問題
Exp19 後 gate 仍偏向少數語義，需要建立語義平衡 clean gate set。

## 實驗目標與要求
目標要求：

- 建立語義平衡 gate 題庫，5 個 semantic classes：`e_pawn_central_break`、`d_pawn_central_break`、`flank_pawn_push`、`kingside_aggression`、`development_move`。
- 每類 easy/medium/hard 各 3 題，共 45 clean cases。
- 每題用 evaluator/static check 驗證：legal、static_cp_delta、label_quality、source_reason。
- 若任何 semantic class count=0，promotion false，reason=`semantic_coverage_missing`。

結果：

- clean gate 45 題，語義覆蓋完整。
- questionable/invalid = 0。
- cp20 結果顯示能力集中在少數 e-pawn 類型：e_pawn 2/9、d_pawn 0/9、flank 1/9、kingside 0/9、development 0/9。

經驗：

- Gate 成功把真相攤開：模型不是廣泛棋理能力，只是在少數 e-pawn 類型上有局部能力。
- 下一步不能再調 gate，必須改訓練資料本身。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp20_semantic_balanced_clean_gate
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp2 --output-root /home/s92137/chess_results/exp20_semantic_balanced_clean_gate
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp20_semantic_balanced_clean_gate | - | HIGH_RISK | - | 33.283 | - | - | 373.197 | true | - | - | - |

最後一次 run 原始結果目錄：`/home/s92137/chess_results/exp20_semantic_balanced_clean_gate`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
