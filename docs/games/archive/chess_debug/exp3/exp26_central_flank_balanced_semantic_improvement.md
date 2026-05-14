# EXP26 - Central / Flank Balanced Semantic Improvement

## 前一個實驗暴露的問題
Exp25 讓 gate 公平後，主要 blocker 轉為 central/flank semantic generalization。

## 實驗目標與要求
目標要求：

- 在 exp25 公平 gate 基礎上，專攻 `e_pawn_central_break`、`d_pawn_central_break`、`flank_pawn_push` 三類的泛化能力。
- 不再調整 `kingside_aggression` / `development_move` 的 gate 定義；development 保留 multi-good credit，且不可 regression。
- 分析 e/d/flank failed cases：failed top3、expected rank、static/search score、semantic confusion target、raw policy fail vs final decision fail。
- 建立 targeted curriculum：明確對比 e-pawn vs d-pawn、central break vs flank push、flank push 何時合理。
- 加入 semantic pair contrast：e positive 時 d/flank 作 negatives；d positive 時 e/flank 作 negatives；flank positive 時 central pawn pushes 作 negatives。
- Gate 條件維持：balanced clean pass rate >= 0.5、e/d/flank 每類 pass > 0、development 不退步、illegal_rate=0、blunder_avoid=1、tactic 不退步、retention 不退步。

目前實作：

- 新增 `CENTRAL_FLANK_FOCUS_SEMANTICS`，明確限定 exp26 focus 為 e/d/flank。
- `_central_flank_targeted_supervised_variants()` 只從 clean semantic templates 產生 e/d/flank targeted train/validation variants，不碰 kingside/development。
- `_semantic_negative_moves()` 對 e/d/flank 改成優先使用互相對比的 semantic negatives，kingside 只排在後面。
- `_sanity_seen_variant_training_rows()` 會把 targeted curriculum rows 標為 `central_flank_targeted_curriculum_replay`，提高權重並記錄 `semantic_pair_contrast`。
- `_central_flank_failed_case_analysis()` 會輸出 e/d/flank failed cases 的 raw/final failure type、expected rank、top3、static/search score、confusion target、decision path。
- `SUMMARY.md` 新增 `Central / Flank Semantic Improvement` 區塊。

結果：

- 實跑目錄：`<chess_results>/exp26_central_flank_balanced_semantic_improvement_v2`。
- 整體 verdict：`HIGH_RISK`，promotion 維持 false。
- `timing_breakdown.total_wall_seconds=1328.984`，其中 `retrain_seconds=45.236`、`deterministic_eval_seconds=46.485`、`report_write_seconds=1.153`。
- central/flank targeted curriculum 已啟用，focus semantics 為 `e_pawn_central_break`、`d_pawn_central_break`、`flank_pawn_push`。
- targeted curriculum 新增 train rows：76；train offsets：`[2, 4, 8]`；validation offsets：`[7]`。
- `semantic_pair_contrast`：e/d/flank positive 會使用其他 central/flank semantics 作 hard negatives。
- development strategy：保留 exp25 的 multi-good credit，不把 development 作為 exp26 主攻方向。

Balanced clean held-out 結果：

- cp10 overall balanced clean pass rate：`0.3714`。
- cp10 by semantic：`e_pawn_central_break=3/9`、`d_pawn_central_break=2/9`、`flank_pawn_push=0/8`、`development_move=8/9`。
- cp20 overall balanced clean pass rate：`0.4286`。
- cp20 by semantic：`e_pawn_central_break=3/9`、`d_pawn_central_break=3/9`、`flank_pawn_push=1/8`、`development_move=8/9`。
- 相比 exp25 cp20 的 `0.3333`，exp26 提升到 `0.4286`；但仍低於 gate 門檻 `>=0.5`。
- `development_move` retention 維持 `8/9`，沒有被 exp26 的 e/d/flank targeted curriculum 破壞。

Central/flank failed case analysis：

- cp10 central/flank failed count：21。
- cp10 `d_pawn_central_break`：failed 7，raw policy fail 7，final decision fail 0；confusion target 為 `development_move=2`、`e_pawn_central_break=2`、`kingside_aggression=3`。
- cp10 `e_pawn_central_break`：failed 6，raw policy fail 6，final decision fail 0；confusion target 為 `d_pawn_central_break=3`、`kingside_aggression=3`。
- cp10 `flank_pawn_push`：failed 8，raw policy fail 8，final decision fail 0；confusion target 為 `d_pawn_central_break=2`、`development_move=1`、`e_pawn_central_break=2`、`kingside_aggression=3`。
- cp20 central/flank failed count：19。
- cp20 `d_pawn_central_break`：failed 6，raw policy fail 6，final decision fail 0；confusion target 為 `development_move=1`、`e_pawn_central_break=2`、`flank_pawn_push=2`、`other=1`。
- cp20 `e_pawn_central_break`：failed 6，raw policy fail 5，final decision fail 1；confusion target 為 `d_pawn_central_break=4`、`other=2`。
- cp20 `flank_pawn_push`：failed 7，raw policy fail 7，final decision fail 0；confusion target 為 `d_pawn_central_break=2`、`e_pawn_central_break=3`、`flank_pawn_push=1`、`other=1`。

Fusion / deterministic 結果：

- `strict_search` final decision generalization rate：`0.5`，balanced variant cases：35，style excluded：9，tactic/blunder regression 都是 false。
- `balanced_fusion` final decision generalization rate：`0.5`，balanced variant cases：35，style excluded：9，tactic/blunder regression 都是 false。
- `policy_preferred` final decision generalization rate：`0.5`，balanced variant cases：35，style excluded：9，tactic/blunder regression 都是 false。
- 這表示 exp26 的主要 failure 仍是 raw policy semantic generalization，不是 search/fusion 壓掉已學會的 move。

Promotion gate 仍失敗的主要原因：

- catastrophic regression detected。
- cp10/cp20 seen retention below threshold。
- cp10/cp20 clean held-out retention below threshold。
- cp10 hard clean held-out retention is zero。
- cp10 `flank_pawn_push` clean held-out pass count is zero。
- cp10/cp20 hard-negative margin 與 semantic hard-negative margin 仍為負。
- `semantic_coverage_missing: flank_pawn_push:hard` 仍存在。
- cp10 central break to kingside semantic confusion exceeds threshold。
- cp20 policy margin drift left hard-negative margin negative。
- trusted=20 的 mistake retention probe 仍 repeated old mistake，未 match expected move。

驗證：

- `python3 -m py_compile scripts/games/chess_live_learning_validation.py services/games/chess_dl.py` 通過。
- `PYTHONPATH=<repo> python3 -m pytest tests/scripts/games/test_chess_live_learning_validation_script.py -q`：`29 passed in 473.41s`。
- `PYTHONPATH=<repo> python3 -m pytest tests/games -q`：`67 passed in 24.24s`。
- quick deterministic gate 實跑完成，artifact 寫入 `<chess_results>/exp26_central_flank_balanced_semantic_improvement_v2`。
- artifact consistency 自檢通過：root/engine JSON verdict 與 promotion gate 一致，root/engine Markdown 存在，engine SUMMARY 含 `Can This Model Be Promoted?` 與 `Central / Flank Semantic Improvement`。
- `git diff --check` 在本次程式與測試修改後通過；docs 追加後需再次檢查。

經驗：

- exp25 後主要 blocker 已轉為 central/flank semantic generalization，不再是 style gate 污染。
- exp26 targeted curriculum 有改善 d/e pawn 類與 overall balanced score，但 flank 仍是最弱類別；尤其 cp10 flank 0/8、cp20 flank 1/8。
- final decision path 不是主要 blocker；e/d/flank 失敗大多在 raw policy 階段已經沒有把 expected move 排上來。
- 下一步不應再調 gate，而應針對 flank hard coverage、central-vs-flank semantic boundary、hard-negative margin 轉正與 cp20 retention 做更細的資料/表徵設計。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp26_central_flank_balanced_semantic_improvement
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp2 --output-root <chess_results>/exp26_central_flank_balanced_semantic_improvement
```
### exp26_central_flank_balanced_semantic_improvement_v2
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp2 --output-root <chess_results>/exp26_central_flank_balanced_semantic_improvement_v2
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp26_central_flank_balanced_semantic_improvement | - | HIGH_RISK | - | 44.751 | - | - | 1296.982 | true | - | - | - |
| exp26_central_flank_balanced_semantic_improvement_v2 | - | HIGH_RISK | - | 45.236 | - | - | 1271.432 | true | - | - | - |

最後一次 run 原始結果目錄：`<chess_results>/exp26_central_flank_balanced_semantic_improvement_v2`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
