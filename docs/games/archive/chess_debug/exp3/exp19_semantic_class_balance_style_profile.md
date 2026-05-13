# EXP19 - Semantic Class Balance 與 Style Profile 分離

## 前一個實驗暴露的問題
Exp18 semantic embedding separation 仍不足，需要檢查 semantic class balance 與 style 分離。

## 實驗目標與要求
目標要求：

- 檢查 train/validation/held-out 各 semantic class 數量。
- 防止 kingside_aggression 樣本或 bias 壓過 central break。
- centroid separation loss 聚焦最混淆 pair。
- 保留 style profile，但 promotion gate 固定 balanced，attacking/defensive 只做 audit。

結果：

- 報告加入 semantic class distribution、centroid distance before/after、confusion matrix。
- 確立 style preference 不得參與 promotion gate。
- 攻擊/防守人格只能在合理候選步中改排序，不能覆蓋基本棋力。

經驗：

- 可以有 style layer，但不能讓 style 凌駕棋力。
- Promotion gate 測的是基礎正確性，不是偏好。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp19_semantic_class_balance
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root <chess_results>/exp19_semantic_class_balance
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp19_semantic_class_balance | - | HIGH_RISK | - | 32.549 | - | - | 365.447 | true | - | - | - |

最後一次 run 原始結果目錄：`<chess_results>/exp19_semantic_class_balance`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
