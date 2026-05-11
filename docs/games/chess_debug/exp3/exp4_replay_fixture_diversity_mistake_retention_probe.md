# EXP4 - Replay Fixture Diversity 與 Mistake Retention Probe

## 前一個實驗暴露的問題
Exp3 發現 loss 下降但 deterministic score 不提升，資料 fixture 與 mistake retention 不夠精準。

## 實驗目標與要求
目標要求：

- 固定 replay fixture 去重、提升多樣性。
- 覆蓋 opening、tactic、endgame、blunder_avoid、mistake_retention。
- mistake retention replay 必須和 probe 對齊。
- 區分 `matched_expected`、`avoided_old_but_not_expected`、`repeated_old_mistake`。

結果：

- 報告加入 fixture health：duplicate ratio、category distribution、unique FEN、unique target move、fixture hash。
- mistake probe 開始輸出 before_move、after_move、expected_move、avoided_old_mistake、matched_expected、learning_signal_reason。
- 仍出現「loss 下降但棋力/決策不變」。

經驗：

- fixture health 是資料品質門檻，但不是學習成功證據。
- mistake retention 必須以 `matched_expected` 作為成功條件；只避開舊錯但沒走正解只能算 partial。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp4_quick_gate_20260510_085157
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root /home/s92137/chess_results/exp4_quick_gate_20260510_085157
```
### exp4_sanity_probe_20260510_090138
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root /home/s92137/chess_results/exp4_sanity_probe_20260510_090138
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp4_quick_gate_20260510_085157 | - | PARTIAL | - | 3.457 | - | - | 12.335 | true | - | - | - |
| exp4_sanity_probe_20260510_090138 | - | PARTIAL | - | 3.506 | - | - | 16.773 | true | - | - | - |

最後一次 run 原始結果目錄：`/home/s92137/chess_results/exp4_sanity_probe_20260510_090138`。

## 結果判讀
最後一次 run verdict=`PARTIAL`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
直接適用該實驗線；exp3 是主要 quick deterministic gate，exp4 共用 replay/probe/gate surface。
