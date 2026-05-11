# EXP25 - Balanced Gate Semantic Cleanup

## 前一個實驗暴露的問題
Exp24 發現 kingside 是 style preference，不該混入 balanced promotion hard gate；development 需要 multi-good scoring。

## 實驗目標與要求
目標要求：

- promotion gate 改成真正的 balanced 棋力驗收，不再用 `kingside_aggression` 這類 style preference 當硬標籤。
- Balanced hard gate 保留：`e_pawn_central_break`、`d_pawn_central_break`、`flank_pawn_push`、`development_move`。
- `kingside_aggression` 移到 `attacking_style_audit`，只審計 unsafe override，不影響 balanced promotion pass/fail。
- `development_move` 改用 multi-good credit：expected top1 給 full credit；expected in top3 或 static/search 同等合理候選不可直接視為 fail。
- 報告必須新增：`balanced_gate_semantic_set`、`excluded_style_semantics`、`attacking_style_audit`、`development_multi_good_credit`、`balanced_clean_pass_rate_by_semantic`。
- Gate 條件維持：balanced clean held-out >= 0.5、每個 balanced semantic class 至少 pass > 0、illegal_rate=0、blunder_avoid=1、tactic 不退步。

目前實作：

- `_evaluate_sanity_learning_probe()` 會額外產出 balanced clean held-out performance，並排除 `kingside_aggression`。
- `_balanced_gate_performance_for_case_ids()` 只統計 balanced semantic set，style semantics 不進分母。
- `_development_multi_good_credit()` 對 development 類加入 top3/static-equivalent credit，並輸出 credit reason。
- `checkpoint_consistency` 與 `SUMMARY.md` 新增 balanced gate semantic cleanup 區塊。
- `_fusion_mode_comparison()` 的 variant generalization comparison 已限制在 balanced semantic set，避免 style audit 間接造成 balanced gate fail。

結果：

- 修正版實跑目錄：`/home/s92137/chess_results/exp25_balanced_gate_semantic_cleanup_v2`。
- 整體 verdict：`HIGH_RISK`，promotion 維持 false。
- `timing_breakdown.total_wall_seconds=973.428`，其中 `retrain_seconds=43.941`、`deterministic_eval_seconds=47.49`、`kingside_development_audit_seconds=34.513`、`report_write_seconds=4.235`。
- Balanced gate semantic set：`e_pawn_central_break`、`d_pawn_central_break`、`flank_pawn_push`、`development_move`。
- Excluded style semantics：`kingside_aggression`。
- `fusion_mode_comparison` 已改用 balanced variant cases：36 題；style excluded：9 題。
- `strict_search`、`balanced_fusion`、`policy_preferred` 三種 fusion mode 的 balanced final decision generalization 都是 `0.3333`，且 tactic/blunder regression 都是 false。

Balanced clean held-out 結果：

- cp10 overall balanced clean pass rate：`0.3333`。
- cp10 by semantic：`e_pawn_central_break=3/9`、`d_pawn_central_break=0/9`、`flank_pawn_push=1/9`、`development_move=8/9`。
- cp20 overall balanced clean pass rate：`0.3333`。
- cp20 by semantic：`e_pawn_central_break=2/9`、`d_pawn_central_break=1/9`、`flank_pawn_push=1/9`、`development_move=8/9`。
- cp10/cp20 都未達 `balanced clean held-out >= 0.5`，因此 promotion gate 必須 false。

Development multi-good credit：

- cp10 development cases：9；multi-good cases：8；credit applied：8。
- cp20 development cases：9；multi-good cases：8；credit applied：8。
- Development 不再因 `expected_move` 不是 final top1 就全部失敗；若 expected 在 top3 或 static-equivalent 範圍內，會明確記錄 `multi_good_credit_applied` 與 reason。

Attacking style audit：

- attacking style audit case count：9。
- cp10 strict final pass rate：`0.0`，raw policy pass rate：`0.1111`。
- cp20 strict final pass rate：`0.0`，raw policy pass rate：`0.0`。
- `kingside_aggression` 仍會作為 attacking style audit 觀察，但不再進 balanced hard gate 分母，也不再用來直接決定 balanced promotion pass/fail。

Promotion gate 仍失敗的主要原因：

- catastrophic regression detected。
- cp10/cp20 seen retention below threshold。
- cp10/cp20 balanced clean held-out retention below threshold。
- cp10 `d_pawn_central_break` pass count 仍為 0；cp20 雖變成 1/9，但 overall 仍不足。
- hard-negative margin 與 semantic hard-negative margin 仍為負。
- cp20 exact retention failed，mistake retention 在 trusted=20 仍 repeated old mistake。
- `balanced_fusion` final decision generalization 仍低於 threshold。

驗證：

- `python3 -m py_compile scripts/games/chess_live_learning_validation.py services/games/chess_dl.py` 通過。
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest tests/scripts/games/test_chess_live_learning_validation_script.py -q`：`27 passed in 279.82s`。
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest tests/games -q`：`67 passed in 24.08s`。
- `git diff --check` 通過。
- artifact consistency 自檢通過：root/engine JSON verdict 與 promotion gate 一致，root/engine Markdown 存在，engine SUMMARY 含 `Can This Model Be Promoted?` 與 `Balanced Gate Semantic Cleanup`。

經驗：

- Style preference 不等於 balanced promotion evidence。
- Development 類若存在多個同等好棋，promotion gate 不應用單一 top1 硬標籤懲罰模型；應報告 multi-good credit 的適用範圍與理由。
- exp25 清理後，模型看起來不再被 kingside hard label 直接懲罰，但 balanced clean pass rate 只有 0.3333，問題仍是 d_pawn/flank/generalization/retention 不足，而不是 gate 不公平。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp25_balanced_gate_semantic_cleanup
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp2 --output-root /home/s92137/chess_results/exp25_balanced_gate_semantic_cleanup
```
### exp25_balanced_gate_semantic_cleanup_v2
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp2 --output-root /home/s92137/chess_results/exp25_balanced_gate_semantic_cleanup_v2
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp25_balanced_gate_semantic_cleanup | - | HIGH_RISK | - | 43.587 | - | - | 886.005 | true | - | - | - |
| exp25_balanced_gate_semantic_cleanup_v2 | - | HIGH_RISK | - | 43.941 | - | - | 879.859 | true | - | - | - |

最後一次 run 原始結果目錄：`/home/s92137/chess_results/exp25_balanced_gate_semantic_cleanup_v2`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
