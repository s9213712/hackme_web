# EXP7 - Exact FEN 到 Seen/Unseen Variants

## 前一個實驗暴露的問題
Exp6 證明 exact FEN 可學，但仍可能只是記憶單一局面。

## 實驗目標與要求
目標要求：

- 把 sanity probe 的 6 個 variants 加入 training replay。
- 分開評估 exact FEN、seen variants、unseen variants。
- 新增泛化指標：exact_fen_pass、seen_variant_pass_rate、unseen_variant_pass_rate、raw/final generalization rate。
- high confidence policy override 必須受 margin threshold 限制。

結果：

- exact FEN 通過。
- seen variants pass rate 達 1.0。
- unseen variants pass rate 為 0.0。
- deterministic final score 可高於 baseline，但 promotion 仍正確 blocked。

經驗：

- exp6 證明會學，exp7 證明會背；但還不能證明泛化。
- Promotion 不可只靠 exact FEN 或 seen variants。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp7_exp3_quick_gate_20260510
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root /home/s92137/chess_results/exp7_exp3_quick_gate_20260510
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp7_exp3_quick_gate_20260510 | - | PARTIAL | - | 23.824 | - | - | 57.059 | true | - | - | - |

最後一次 run 原始結果目錄：`/home/s92137/chess_results/exp7_exp3_quick_gate_20260510`。

## 結果判讀
最後一次 run verdict=`PARTIAL`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
