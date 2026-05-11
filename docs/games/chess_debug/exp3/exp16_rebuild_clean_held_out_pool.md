# EXP16 - Rebuild Clean Held-out Pool

## 前一個實驗暴露的問題
Exp15 排除 questionable labels 後 clean held-out 太少，樣本數不足以當正式 gate。

## 實驗目標與要求
目標要求：

- 建立 clean held-out pool，easy/medium/hard 各至少 10 題。
- expected_move 必須合法，static_cp_delta 不得低於 -150cp。
- clean/questionable/invalid 分層，並防止 train/validation/held-out leakage。

結果：

- 題庫問題與模型問題被分開。
- leakage、label questionable、search override、tactic/blunder regression 不再是主要失敗原因。
- 乾淨 held-out 上仍失敗，cp20 比 cp10 更差，clean held-out 0.30 降到 0.20。

經驗：

- 失敗主因轉為模型 policy 泛化能力不足。
- 模型似乎學到「中央兵通常不錯」，但無法穩定分辨 `e7e5`、`d7d5`、`f5f4`、`h6g4` 的局面語義。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp16_clean_heldout_gate
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root /home/s92137/chess_results/exp16_clean_heldout_gate
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp16_clean_heldout_gate | - | HIGH_RISK | - | 31.774 | - | - | 297.402 | true | - | - | - |

最後一次 run 原始結果目錄：`/home/s92137/chess_results/exp16_clean_heldout_gate`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
