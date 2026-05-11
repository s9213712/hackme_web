# EXP1 - Live Learning Validation Baseline

## 前一個實驗暴露的問題
起點問題：原始 chess live-learning 缺少可審計 promotion evidence chain。

## 實驗目標與要求
目標要求：

- 建立 exp1 live-learning validation。
- 每 10 盤有效 trusted game 觸發 retrain。
- 報告需包含 accepted/rejected、retrain checkpoint、model hash、benchmark、summary。

結果：

- 初版可以產出 live-learning validation report。
- 確認 retrain 觸發條件與 checkpoint artifact 可被記錄。
- 暴露報告太像 dashboard，缺少 promotion decision evidence chain。

經驗：

- 「有 retrain」不是證據，必須能追蹤 dataset hash、before/after model hash、benchmark skipped reason、gate decision。
- 報告要回答「Can This Model Be Promoted?」，不是只列指標。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### live_learning_20260509_235218
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --output-root /home/s92137/chess_results/live_learning_20260509_235218
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| live_learning_20260509_235218 | - | FAIL | - | 0 | - | - | 3375.045 | - | - | - | - |

最後一次 run 原始結果目錄：`/home/s92137/chess_results/live_learning_20260509_235218`。

## 結果判讀
最後一次 run verdict=`FAIL`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
早期驗證節點；後續由 exp3/exp4 共用 gate surface 承接。
