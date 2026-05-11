# EXP12 - Stability Curriculum 與 Checkpoint Consistency

## 前一個實驗暴露的問題
Exp11 泛化只在部分 checkpoint 出現，整條 checkpoint evidence chain 不穩。

## 實驗目標與要求
目標要求：

- curriculum smoothing，避免 checkpoint@10 與 @20 replay 分布差太大。
- 新增 checkpoint stability metrics：exact/seen/unseen/hard-held-out retention、embedding drift、policy margin drift。
- instability detector：final unseen 下降、prior learned case 丟失、embedding drift 過大、hard-negative margin 轉負。

結果：

- 報告新增 checkpoint_consistency_table、embedding_drift_table、retention_chain、instability_reasons。
- 發現 generalized_to_variants 不一定能在 checkpoint@10、checkpoint@20、final 全鏈穩定成立。

經驗：

- 單一 final score 不足以 promotion。
- checkpoint evidence chain 必須穩定，否則代表 retrain pipeline 仍不可控。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp12_exp3_quick_gate_20260510T_exp12
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root /home/s92137/chess_results/exp12_exp3_quick_gate_20260510T_exp12
```
### exp12_exp3_quick_gate_20260510T_exp12_r2
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root /home/s92137/chess_results/exp12_exp3_quick_gate_20260510T_exp12_r2
```
### exp12_exp3_quick_gate_20260510T_exp12_r3
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root /home/s92137/chess_results/exp12_exp3_quick_gate_20260510T_exp12_r3
```
### exp12_exp3_quick_gate_20260510T_exp12_r4
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root /home/s92137/chess_results/exp12_exp3_quick_gate_20260510T_exp12_r4
```
### exp12_exp3_quick_gate_20260510T_exp12_r5
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root /home/s92137/chess_results/exp12_exp3_quick_gate_20260510T_exp12_r5
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp12_exp3_quick_gate_20260510T_exp12 | - | HIGH_RISK | - | 29.838 | - | - | 110.18 | true | - | - | - |
| exp12_exp3_quick_gate_20260510T_exp12_r2 | - | HIGH_RISK | - | 30.021 | - | - | 110.715 | true | - | - | - |
| exp12_exp3_quick_gate_20260510T_exp12_r3 | - | HIGH_RISK | - | 30.99 | - | - | 123.335 | true | - | - | - |
| exp12_exp3_quick_gate_20260510T_exp12_r4 | - | HIGH_RISK | - | 33.796 | - | - | 134.981 | true | - | - | - |
| exp12_exp3_quick_gate_20260510T_exp12_r5 | - | HIGH_RISK | - | 30.875 | - | - | 129.259 | true | - | - | - |

最後一次 run 原始結果目錄：`/home/s92137/chess_results/exp12_exp3_quick_gate_20260510T_exp12_r5`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
