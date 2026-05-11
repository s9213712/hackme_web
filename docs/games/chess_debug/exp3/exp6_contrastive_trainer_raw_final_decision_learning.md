# EXP6 - Contrastive Trainer 與 Raw/Final Decision Learning 拆分

## 前一個實驗暴露的問題
Exp5 抓到根因：positive-only replay loss 與 final decision 語義不一致。

## 實驗目標與要求
目標要求：

- trainer 從 positive-only replay loss 改為 contrastive/ranking loss。
- expected move 作 positive，其他 legal moves 或 hard negatives 作 negative。
- sanity probe 拆成 `raw_policy_learning` 與 `final_decision_learning`。
- final decision path 輸出 raw_policy_score、static_eval_score、search_score、final_combined_score、chosen_reason。

結果：

- raw policy 可以更明確提高 expected move rank/margin。
- 報告能區分 raw policy 有學到但 final decision 被 search/static eval 擋住。
- Gate 語義修正：promotion 必須 final decision learning 成立；raw policy learned 只能算 partial。

經驗：

- 「先讓 policy 真的學會，再讓 search/static eval 不要蓋掉它」是後續架構原則。
- final decision unchanged 時必須 promotion false，並輸出 `blocked_by_search_or_static_eval`。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp6_exp3_quick_gate_20260510
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root /home/s92137/chess_results/exp6_exp3_quick_gate_20260510
```
### exp6_quick_gate_20260510_092501
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root /home/s92137/chess_results/exp6_quick_gate_20260510_092501
```
### exp6_quick_gate_20260510_092501_final
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root /home/s92137/chess_results/exp6_quick_gate_20260510_092501_final
```
### exp6_quick_gate_20260510_092501_rerun
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root /home/s92137/chess_results/exp6_quick_gate_20260510_092501_rerun
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp6_exp3_quick_gate_20260510 | - | PARTIAL | - | 20.579 | - | - | 46.172 | true | - | - | - |
| exp6_quick_gate_20260510_092501 | - | PARTIAL | - | 38.262 | - | - | 54.931 | true | - | - | - |
| exp6_quick_gate_20260510_092501_final | - | PARTIAL | - | 39.257 | - | - | 54.105 | true | - | - | - |
| exp6_quick_gate_20260510_092501_rerun | - | PARTIAL | - | 39.589 | - | - | 54.477 | true | - | - | - |

最後一次 run 原始結果目錄：`/home/s92137/chess_results/exp6_quick_gate_20260510_092501_rerun`。

## 結果判讀
最後一次 run verdict=`PARTIAL`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
