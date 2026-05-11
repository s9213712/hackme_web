# EXP28 - Context-Conditioned Flank Semantic Learning

## 前一個實驗暴露的問題
Exp27 顯示 flank 不只要學 move 類別，還要學什麼 context 下 flank 合理。

## 實驗目標與要求
目標：

- 不再只把 `flank_pawn_push` 當成 move 類別，而是要求模型與報告判斷「什麼局面條件下 flank push 才合理」。
- 新增 flank context features：`open/closed center`、`king castled side`、`wing space advantage`、`pawn chain direction`、`central tension`、`attack lane availability`、`opposite-side castling`、`side-to-move pressure`。
- 新增 flank reason tags：`space_gain`、`attack_prep`、`pawn_storm`、`prophylaxis`、`expansion`、`bad_random_flank_push`。
- 每個 flank case 必須進行 label audit v2，標出 reason tag；若是無理由亂推兵，不能進 balanced hard gate。
- 新增 `flank_only_contextual` specialist probe，區分「能選 flank move」和「能在正確 context 選正確 flank move」。
- 報告新增 `flank_reason_distribution`、`contextual_flank_pass_rate`、`bad_random_flank_push_confusion`、`non_flank_move_confusion`、`context_feature_importance`。
- Gate 要求 balanced clean >= 0.5、contextual flank hard clean > 0、不可 promotion bad random flank push、development/e/d retention 不退步、mistake retention 不退步。

實作：

- `scripts/games/chess_live_learning_validation.py` 新增 `FLANK_REASON_TAGS`、`_flank_context_features`、`_flank_reason_tag_for_move`、`_contextual_flank_performance_from_rows`、`_context_feature_importance`。
- Semantic balanced clean gate set、semantic balanced supervised variants、central/flank targeted variants、specialist training rows 都寫入 `flank_context_features` 與 `flank_reason_tag`。
- `_flank_label_audit_for_cases` 升級為 `exp28_flank_label_audit_v2`，新增 reason distribution、bad random count、excluded bad random cases，並讓 bad random flank 不具 balanced gate eligibility。
- Checkpoint consistency table 保留 `contextual_flank_performance`、`flank_reason_distribution`、`bad_random_flank_push_confusion`、`context_feature_importance`。
- Promotion gate 新增 contextual flank hard clean 0 時 blocking reason；bad random flank push 被真正 promotion 時也 blocking。
- 修正一個重要語義錯誤：非 flank move，例如 `e2e4`、`e7e5`、`d7d5`、`f8a3`，不再被誤報成 `bad_random_flank_push promoted`，而是歸類為 `non_flank_move_confusion`。只有實際選到無合理 flank context 的 flank move，才算 `bad_random_flank_push promoted`。
- `SUMMARY.md` 的 Central / Flank Semantic Improvement 區塊會列出 flank reason distribution、contextual flank pass、hard contextual hits、bad random promoted、feature importance。
- `tests/scripts/games/test_chess_live_learning_validation_script.py` 新增 exp28 fixture 測試，覆蓋 context features、reason tags、contextual flank performance、bad/random vs non-flank confusion、label audit v2 gate exclusion。

實跑：

- 結果目錄：`/home/s92137/chess_results/exp28_context_conditioned_flank_semantic_learning`。
- quick deterministic gate 使用 exp3、`--quick-retrain-gate`、`--semantic-specialist-probes`、seed `20260511`、`CHESS_EXP3_ABLATION_MODE=invariance_plus_hard_negative`。
- Root verdict：`HIGH_RISK`。
- Promotion gate：`false`。
- Deterministic strength snapshot：`passed=true`，但不能覆蓋 checkpoint instability 與 contextual flank failure。
- Timing breakdown：`total_wall_seconds=1562.966`、`retrain_seconds=45.539`、`deterministic_eval_seconds=48.695`、`semantic_specialist_probe_seconds=100.766`、`report_write_seconds` 約 1 秒級。

Checkpoint consistency：

- cp10 balanced clean retention：`0.3514`。
- cp10 by semantic：`e_pawn_central_break=4/9`、`d_pawn_central_break=0/9`、`flank_pawn_push=1/10`、`development_move=8/9`。
- cp10 contextual flank pass rate：`0.0`。
- cp10 contextual hard flank：`0/4`。
- cp10 bad_random_flank_push promoted：`0`。
- cp10 non_flank_move_confusion：`9`。
- cp20 balanced clean retention：`0.3784`。
- cp20 by semantic：`e_pawn_central_break=4/9`、`d_pawn_central_break=1/9`、`flank_pawn_push=1/10`、`development_move=8/9`。
- cp20 contextual flank pass rate：`0.0`。
- cp20 contextual hard flank：`0/4`。
- cp20 bad_random_flank_push promoted：`0`。
- cp20 non_flank_move_confusion：`8`。

Flank reason distribution：

- `space_gain=6`。
- `prophylaxis=3`。
- `expansion=1`。
- `attack_prep=0`。
- `pawn_storm=0`。
- `bad_random_flank_push=0`。
- 這代表 gate 題庫本身沒有 bad random flank labels；失敗主因不是題庫混入亂推兵，而是模型沒有在這些 context 下選到對應 flank move。

Context feature importance：

- cp10/cp20 top failure features 都集中在 `open_closed_center=closed`、`king_castled_side own/opponent=uncastled`、`kingside_space=neutral`、`pawn_chain_direction=balanced`。
- 這些 feature 目前沒有幫模型分辨「該 c-pawn counterplay / b-pawn support / 其他 flank role」。
- `central_tension=positive` 與 `c_file_open_or_tension=True` 在部分 hard/medium cases 出現，但仍沒有轉化成 contextual flank pass。

Specialist probe：

- `flank_only` specialist：`passed=true` 仍只能代表至少有少量 clean case pass。
- `flank_only` clean held-out final pass rate：`0.1`。
- `flank_only` hard clean held-out final pass rate：`0.0`。
- `flank_only` contextual flank pass rate：`0.1`。
- `flank_only` hard contextual：`0/4`。
- `flank_only` bad_random_flank_push promoted：`0`。
- `flank_only` non_flank_move_confusion：`1`。
- `flank_only_contextual` specialist：`passed=true` 同樣不能解讀為 contextual flank 已學會。
- `flank_only_contextual` clean held-out final pass rate：`0.1`。
- `flank_only_contextual` hard clean held-out final pass rate：`0.0`。
- `flank_only_contextual` contextual flank pass rate：`0.1`。
- `flank_only_contextual` hard contextual：`0/4`。
- `flank_only_contextual` bad_random_flank_push promoted：`0`。
- `flank_only_contextual` non_flank_move_confusion：`1`。

Promotion gate 失敗原因：

- `catastrophic regression detected`。
- cp10/cp20 seen retention below threshold。
- cp10/cp20 clean held-out retention below threshold。
- cp10 `d_pawn_central_break` pass count 仍為 0。
- cp10/cp20 contextual flank hard clean pass rate is zero。
- cp10/cp20 hard-negative margin 仍為負。
- cp10/cp20 semantic hard-negative margin 仍為負。
- cp10/cp20 targeted semantic centroid distance below threshold。
- cp10/cp20 sanity probe 仍只證明 exact FEN memorization，沒有通過 seen/clean held-out 泛化門檻。

驗證：

- `python3 -m py_compile scripts/games/chess_live_learning_validation.py services/games/chess_dl.py` 通過。
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest tests/scripts/games/test_chess_live_learning_validation_script.py -q`：`34 passed in 492.33s`。
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest tests/games -q`：`67 passed in 24.76s`。
- `git diff --check` 通過。
- quick deterministic gate + semantic specialist probes 實跑完成，artifact 寫入 `/home/s92137/chess_results/exp28_context_conditioned_flank_semantic_learning`。

經驗：

- exp28 把 flank 失敗原因拆得更乾淨：目前不是 bad random flank push 被 promotion，而是 flank 題大量被選成 non-flank move；模型仍傾向 central/development/general move，而不是 context-appropriate flank move。
- `flank_only_contextual` 沒有比 `flank_only` 改善 hard clean，表示只把 context metadata 寫進 replay/report 還不足以讓 trainer 真正使用這些 feature。
- 下一步如果要修模型，應該讓 trainer 或 representation 明確學習 flank sub-semantics，而不是只在 artifact 中標註 context。
- 需要把 `flank_pawn_push` 再拆成更細的 sub-semantic，例如 `c_pawn_counterplay`、`b_pawn_fianchetto_support`、`a_pawn_space_gain`、`anti_center_tension_flank_break`，否則 `a7a5`、`c7c5`、`b2b3` 仍會被同一個粗類別混在一起。
- Context feature 目前是 audit evidence，不是 learning signal；若不進入 loss 或 policy feature，模型不會自然學到「closed center + c-file tension -> c-pawn counterplay」這類規則。
- Gate 維持 false 是正確結果；目前 evidence 證明模型會記 exact mistake retention，但還不能證明 balanced flank/central 泛化能力。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp28_context_conditioned_flank_semantic_learning
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp2 --output-root /home/s92137/chess_results/exp28_context_conditioned_flank_semantic_learning
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp28_context_conditioned_flank_semantic_learning | - | HIGH_RISK | - | 45.539 | - | - | 1402.704 | true | - | - | - |

最後一次 run 原始結果目錄：`/home/s92137/chess_results/exp28_context_conditioned_flank_semantic_learning`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
