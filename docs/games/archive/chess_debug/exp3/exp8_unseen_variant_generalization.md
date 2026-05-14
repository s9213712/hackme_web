# EXP8 - Unseen Variant Generalization

## 前一個實驗暴露的問題
Exp7 顯示 seen variants 可過、unseen variants 失敗，問題轉為泛化。

## 實驗目標與要求
目標要求：

- 產生 easy/medium/hard unseen variants。
- 使用 curriculum：exact FEN、easy seen、medium seen、hard held-out。
- 增加 feature generalization debug：embedding similarity、expected rank、blocker reason。
- 修正 checkpoint@20 不能覆蓋 checkpoint@10 已學會能力。

結果：

- 更清楚看到 unseen failure 不是單純 search/static eval 壓掉。
- 部分 checkpoint 出現 learned policy 但 final decision 沒採納。
- checkpoint retention 開始成為 hard gate 條件。

經驗：

- 不增加 self-play 盤數也能定位泛化問題。
- 需要追蹤 checkpoint@10 到 checkpoint@20 的能力是否穩定保留。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp8_exp3_quick_gate_20260510
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root <chess_results>/exp8_exp3_quick_gate_20260510
```
### exp8_exp3_quick_gate_20260510_r2
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root <chess_results>/exp8_exp3_quick_gate_20260510_r2
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp8_exp3_quick_gate_20260510 | - | HIGH_RISK | - | 24.048 | - | - | 111.134 | true | - | - | - |
| exp8_exp3_quick_gate_20260510_r2 | - | PARTIAL | - | 23.734 | - | - | 119.238 | true | - | - | - |

最後一次 run 原始結果目錄：`<chess_results>/exp8_exp3_quick_gate_20260510_r2`。

## 結果判讀
最後一次 run verdict=`PARTIAL`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
