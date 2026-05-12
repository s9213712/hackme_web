# Exp4：Policy/Value + MCTS

本資料夾保存 exp4 後續演進文件。

## 定位

exp4 是後續主要神經網路棋力路線之一，方向是：

- board representation
- policy head
- value head
- MCTS / PUCT decision
- deterministic strength gate

目前 exp4 已有 `services/games/chess_pv.py`，並新增 `decision_mode="mcts"` 的 deterministic root MCTS/PUCT 入口。現階段仍保留 alpha-beta fallback。

## Difficulty

- `experiment 4:pv`

## 模型位置

- runtime model：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_4_pv.json`
- env override：`HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH`
- bundled seed：`services/games/models/chess_experiment_4_pv.json`
- full pipeline candidate：`$HACKME_RUNTIME_DIR/games/models/candidates/runs/<run_id>/chess_experiment_4_pv.json`
- staged candidate：`$HACKME_RUNTIME_DIR/games/models/candidates/experiment_4_pv`
- quick gate checkpoint：`<output_root>/exp4/checkpoints/<trusted>/exp4_quick_candidate_model.json`

模型生命週期：

- bundled seed 只作首次 warm-start，不會被 auto-retrain 改寫。
- 前台 exp4 對局讀取 runtime model。
- quick gate checkpoint 與 full pipeline candidate 都不是 production。
- promotion gate 通過後才把 staged candidate 複製到 runtime model。

完整路徑對照：

- [`../model_artifact_paths.md`](../model_artifact_paths.md)

## 使用方式

前台選擇：

- `實驗 4：Policy/Value + MCTS`

程式呼叫：

```python
from services.games.chess_pv import choose_experiment_pv_move

move = choose_experiment_pv_move(
    board,
    "black",
    search_profile="fast",
    decision_mode="mcts",
)
```

## 後續文件規則

- exp4 的每次架構調整、gate 實跑、benchmark 設計、promotion decision 都寫在本資料夾。
- 不要把 exp3 的 semantic replay success/failure 直接複製成 exp4 結論。
- 每份報告必須標明：
  - model path
  - decision mode
  - deterministic case set
  - policy/value/MCTS evidence
  - promotion verdict

## 目前 exp4 推進狀態

目前 exp4 已接到和 exp3 exp34 同等級的驗收框架：

- quick retrain gate 產生 checkpoint@10 / checkpoint@20。
- smoke gate 通過後會跑 full sanity seen/unseen variants。
- mistake retention probe 會檢查「舊錯修正」與「已學會舊題保留」。
- safe checkpoint selection 不允許 retention-failed checkpoint 成為 promotion final candidate。
- validation artifacts 不會直接覆蓋前台 production model。

已修正的 exp4 專屬問題：

- validation decision path 改為 `decision_mode="mcts"`，避免測試走 alpha-beta 而前台走 MCTS。
- balanced opening 多好棋使用 top3 / multi-good credit，避免同一 starting FEN 中 `e2e4`、`d2d4`、`c2c4`、`g1f3` 被互相誤判。
- quick fixture 後續 filler moves 改成 `fixture_continuation`，不可再污染 mistake retention。
- mistake retention probe 只允許使用 `category=mistake_retention` 樣本，不可退回 fixture continuation。

最新實跑目錄：

- `/home/s92137/chess_results/exp4_02_mcts_opening_multigood`
- `/home/s92137/chess_results/exp4_03_retention_fixture_clean`
- `/home/s92137/chess_results/exp4_04_probe_policy_fixed`
- `/home/s92137/chess_results/exp4_06_full_sanity_sample64_final`（baseline reference）
- `/home/s92137/chess_results/exp4_07_full_evidence_cleanup`（exp4_07 evidence cleanup）
- `/home/s92137/chess_results/exp4_08_e_pawn_repair`（exp4_08 e_pawn equivalence audit + artifact size split）
- `/home/s92137/chess_results/exp4_09_label_audit`（exp4_09 opening label audit + specialist gate cleanup）
- `/home/s92137/chess_results/exp4_10_anti_poison`（exp4_10 anti-poison + special-rule + king-safety + override-search guard diagnostics）
- `/home/s92137/chess_results/exp4_11_hardening`（exp4_11 quarantine wiring + chess_pv search guard + multi-good revoke）
- `/home/s92137/chess_results/exp4_12_resign_draw_special`（exp4_12 求和 + 認輸 + 特殊走法擴充 + chess label features）
- `/home/s92137/chess_results/exp4_12_audit_consistency`（exp4_12 audit/guard score-source 一致性）
- `/home/s92137/chess_results/exp4_13_special_rule_curriculum`（exp4_13 special-rule + king-safety curriculum + 修 draw fixture）
- `/home/s92137/chess_results/exp4_14_balanced_curriculum`（exp4_14 降權 + retention rehearsal + curriculum budget + rollback guard）
- `/home/s92137/chess_results/exp4_15_rule_feature_consumption`（exp4_15 修 retention guard 假警報 + trainer 消費 rule_type + king-safety isolated probe + targeted rule before/after）
- `/home/s92137/chess_results/exp4_16_rule_aware_final_fusion_locked`（exp4_16 rule-aware final fusion 鎖住 special-rule final move）
- `/home/s92137/chess_results/exp4_vs_exp5_smoke_20260512_032501`（exp4_16 vs exp5_08 diagnostic sparring，非 promotion evidence）
- `/home/s92137/chess_results/exp4_17_special_rule_subtype_consistency`（exp4_17 special-rule subtype + choose/explain consistency）
- `/home/s92137/chess_results/exp4_17_gate_accounting_cleanup`（exp4_17 gate accounting cleanup）
- `/home/s92137/chess_results/exp4_18_full_broad_learning_diagnostic`（exp4_18 full heavy sanity；確認 broad generalization 仍未通過）
- `/home/s92137/chess_results/exp4_18_e_pawn_gate_accounting_fix`（exp4_18 e_pawn opening-book equivalence gate accounting fix）
- `/home/s92137/chess_results/exp4_19_guarded_overlay_attribution`（exp4_19 baseline-default guarded overlay attribution）
- `/home/s92137/chess_results/exp4_20_runtime_guarded_overlay`（exp4_20 no-label runtime guarded overlay simulator）
- exp4_21 runtime guarded overlay integration draft（預設關閉，尚未 promotion）

其中 `exp4_04_probe_policy_fixed` 是目前用來驗證「probe policy 修正後」的正式 quick gate artifact。

## exp4_18 broad learning diagnostic（2026-05-12）

exp4_18 不再修 special-rule，而是跑不跳過 heavy sanity 的 broad learning diagnostic。

主要結論：

- special-rule gate 保持 `7/7`，不再是主 blocker。
- deterministic final `0.8693`，與 baseline `0.8693` 打平，不能 promotion。
- mistake retention 有改善，但只是 targeted evidence。
- sanity unseen 約 `0.39`，仍偏 exact-FEN memorization，沒有 broad generalization。
- full sanity 成本高：`total_wall_seconds=2438.614`、`total_checkpoint_seconds=2264.592`。
- e_pawn false blocker 已修：`1.Nf3` / `1.c3` 後黑方 `d7d5` 不再被誤判為 e7e5 learning failure，而是 opening multi-good tie。

目前 exp4 的下一個真 blocker：

- broad learning / generalization
- endgame retention
- full sanity 評估成本
- hard flank general-model gap

詳細報告：

- [`2026-05-12_exp4_18_full_broad_learning_diagnostic.md`](2026-05-12_exp4_18_full_broad_learning_diagnostic.md)

## exp4_19 guarded overlay attribution（2026-05-12）

詳細報告：[`2026-05-12_exp4_19_guarded_overlay_attribution.md`](2026-05-12_exp4_19_guarded_overlay_attribution.md)

exp4_18 證明 full final replacement 仍等於 baseline：`0.8693 -> 0.8693`。exp4_19 不再盲目加訓練資料，而是評估「baseline 預設 + 只接受 deterministic 正向 / 不退步覆蓋」是否值得做成 runtime guard。

實跑結果：

| 指標 | 數值 |
|---|---:|
| baseline_score | `0.8693` |
| final_score | `0.8693` |
| guarded_overlay_score | `0.9231` |
| delta_vs_baseline | `+0.0538` |
| positive_override_count | `1` |
| prevented_regression_count | `1` |
| unsafe_override_count | `0` |
| candidate_worth_runtime_overlay | `true` |

判讀：

- full replacement 會讓「final 修正 mistake_retention」與「final 在 promotion_white 退步」互相抵消。
- guarded overlay 會採用 `mistake_retention_game_900002_ply_1: d7d5`，但在 `promotion_white` 回退 baseline `e7e8q`。
- 這是 label-based attribution upper-bound，不能直接當 production evidence；下一步要把它改成不依賴 expected label 的 runtime guarded overlay。
- promotion 仍 false，因為本輪是 `--quick-retrain-skip-heavy-sanity` 且 broad generalization 未證明。

## exp4_20 runtime guarded overlay simulator（2026-05-12）

詳細報告：[`2026-05-12_exp4_20_runtime_guarded_overlay.md`](2026-05-12_exp4_20_runtime_guarded_overlay.md)

exp4_19 還是 label-based attribution。exp4_20 把同一思路改成 no-label runtime simulator：決策時不讀 expected label，只用合法性、static-like score window 與 promotion subtype oracle 決定是否採用 final。

實跑結果：

| 指標 | 數值 |
|---|---:|
| baseline_score | `0.8693` |
| final_score | `0.8693` |
| runtime_guarded_score | `0.9231` |
| delta_vs_baseline | `+0.0538` |
| runtime_guard_allowed | `2` |
| runtime_guard_fallback | `1` |
| positive_override_after_scoring | `1` |
| prevented_regression_after_scoring | `1` |
| unsafe_override_after_scoring | `0` |
| diagnostic_uses_expected_labels_for_decision | `false` |

判讀：

- `mistake_retention_game_900002_ply_1`：runtime guard 採用 final `d7d5`。
- `promotion_white`：runtime guard 擋住 final `e7e8n`，回退 baseline `e7e8q`。
- guarded simulator 不偷看 label 也重現 exp4_19 的 `0.9231` 上界。
- 仍不能 promotion：production choose path 尚未接入、heavy sanity skipped、broad generalization 未證明。

## exp4_21 runtime guarded overlay integration draft（2026-05-12）

詳細報告：[`2026-05-12_exp4_21_runtime_guarded_overlay_integration.md`](2026-05-12_exp4_21_runtime_guarded_overlay_integration.md)

exp4_21 把 exp4_20 的 no-label guard 抽成共用 runtime helper，並接到前台 exp4 choose path，但預設關閉：

```bash
HTML_LEARNING_CHESS_EXP4_GUARDED_OVERLAY=1
HTML_LEARNING_CHESS_EXP4_OVERLAY_CANDIDATE_MODEL_PATH=/path/to/exp4_candidate.json
```

重點：

- `services/games/chess_pv_guarded_overlay.py` 是 runtime 與 validation 共用 guard。
- guard input 已 sanitized，不吃完整 deterministic row，不可接觸 expected label / top1_correct / pass-fail outcome。
- `routes/games.py` 只有在 env flag 開啟時才走 `choose_experiment_pv_guarded_overlay_move(...)`。
- production 預設仍是原本 exp4 runtime model，不改行為。
- quick targeted gate 已跑：
  - result dir：`/home/s92137/chess_results/exp4_21_runtime_guarded_overlay_integration`
  - runtime guarded score：`0.9231`，delta vs baseline `+0.0538`
  - full replacement score：`0.8693`，等於 baseline
  - `runtime_guard_allowed=2`
  - `runtime_guard_fallback=1`
  - `positive_override_after_scoring=1`
  - `prevented_regression_after_scoring=1`
  - `unsafe_override_after_scoring=0`
  - `special_rule=7/7`
- 關鍵 case：
  - `mistake_retention_game_900002_ply_1`：baseline `e7e5`，candidate `d7d5`，guard 採用 final。
  - `promotion_white`：baseline `e7e8q`，candidate `e7e8n`，guard fallback baseline。
- 仍不能 promotion；原因是 heavy sanity skipped、production flag 預設關閉、broad unseen generalization 尚未用 full diagnostic 證明。

## exp4_07 evidence accounting cleanup（2026-05-11）

exp4_06 deterministic score 從 0.8693 提升到 0.9231（delta +0.0538），mistake retention 過關，但仍卡在 opening final decision alignment、low-margin override 帳目、e_pawn clean held-out=0、hard flank scope 混淆、unseen generalization 不足。 exp4_07 沒有直接追 promotion，只重整 evidence accounting 與 blocker scope。

主要報告欄位變更：

- `opening_target_margin_audit`：
  - `audit_table`：6 個 opening case 的完整逐 case 表（teacher_top3 / static_best / search_best / mcts_best / raw_policy_rank / margin / multi_good_tie / override flags / failure_type）。
  - `override_applied_for_move_selection_count`：允許做 move 選擇時用 override。
  - `override_counted_as_learning_success_count`：只在非 low-margin、非 multi_good_tie、且 chosen==expected 時為 true。
  - `low_margin_override_counted_success_count`：固定為 0；low-margin override 不可作 learning success。
  - `opening_final_decision_alignment_passed`：只看 failure_type 是否在 `{passed, multi_good_tie_not_failure}`。
  - `opening_specific_learning_evidence_passed`：opening cases 內有非 low-margin、非 multi_good 的真學習證據。
  - `targeted_mistake_retention_success`：mistake retention probe 是否通過（獨立記錄）。
  - `opening_learning_evidence_passed`：允許用 mistake retention 作 fallback，但 audit_table 明確標示來源。
- `stability.catastrophic_regression_source`：拆出 `deterministic_score_regression`、`checkpoint_retention_instability`、`clean_heldout_retention_failure`、`semantic_margin_failure`、`final_decision_generalization_failure` 等獨立欄位。deterministic score 上升時 `deterministic_score_regression=false`。
- `e_pawn_clean_held_out_diagnosis`：對每個 e_pawn case 給 classification（`raw_policy_fail` / `final_decision_blocked` / `multi_good_tie` / `undertrained_opening_pattern`）。equivalent move 集合命名為 `opening_equivalent_central_moves`，動態加入 case 的 `teacher_top3`/`teacher_top5`。
- `hard_flank_scope_isolation`：emit `hard_flank_used_in_opening_specialist_gate=false`、`hard_flank_general_model_blocker=bool`，把 contextual flank hard clean=0 放在 general-model scope。
- `sanity_learning_summary`：每個 trusted checkpoint 給 verdict（`GENERALIZED` / `PARTIAL_SEEN_VARIANTS_ONLY` / `PARTIAL_EXACT_OR_LOW_MARGIN_ONLY` / `FAILED_TO_LEARN`），不再讓 exact-FEN 假裝成 broad generalization。
- `promotion_gate.opening_specialist_gate` / `promotion_gate.general_model_promotion_gate`：兩個 scope 各自有 `passed` / `reasons`。歷史 reference 不再進 opening specialist gate。
- `promotion_gate.current_exp4_measured_blockers`：本輪實測。`promotion_gate.historical_cross_experiment_risk_references`：純歷史風險引用。

注意：

- `low_margin_override_counted_success_count` 必須為 0 by design；artifact 中如出現非 0，視為 evidence accounting bug。
- opening specialist gate 不被 hard flank、historical exp3/exp31/exp33 reference 阻擋；general model gate 仍會列出這些。
- `final_decision_alignment_passed = opening_final_decision_alignment_passed AND opening_learning_evidence_passed`，與 exp4_06 行為相容但語意拆得更清楚。

## exp4_08 e_pawn opening specialist repair（2026-05-11）

延續 exp4_07 evidence accounting：把 e_pawn=0/9 拆成「真失敗」vs「opening 多好棋等價」vs「final decision blocker」vs「teacher 標註不足」。重點是只修真錯誤，不放行多好棋以外的失敗。

主要報告欄位：

- `e_pawn_clean_held_out_diagnosis`：
  - per-checkpoint：`e_pawn_strict_pass_rate`、`e_pawn_equivalent_credit_pass_rate`、`central_opening_equivalent_pass_rate`、`true_e_pawn_raw_policy_fail_count`、`true_e_pawn_final_decision_blocked_count`、`opening_multi_good_tie_count`、`rehearsal_case_count`（= `true_e_pawn_raw_policy_fail_count`）、`excluded_multi_good_negative_count`、`teacher_annotation_supported_count` / `teacher_annotation_missing_count` / `teacher_top3_empty_count` / `teacher_top5_empty_count`。
  - per-case：`classification ∈ {strict_pass, equivalent_credit_pass, central_opening_equivalent_credit, opening_multi_good_tie, true_e_pawn_raw_policy_fail, true_e_pawn_final_decision_blocked, label_questionable, undertrained_opening_pattern}` + `black_e7e5_subclass` / `white_e2e4_subclass`。
  - equivalent credit 要求 **正面證據**：chosen ∈ teacher_top3/top5 或 static_cp_delta ≤ `OPENING_MULTI_GOOD_CP_THRESHOLD`。沒有證據時保留為 true raw_policy_fail / final_decision_blocked。
- `audit_artifacts`：summary.json 不再內嵌完整逐 case 表，改寫入 `audits/opening_target_margin_audit.jsonl` 與 `audits/e_pawn_clean_held_out_diagnosis.jsonl`。summary 內保留 `audit_table_full_row_count`、`audit_table_artifact_path`、totals、per-checkpoint counts、inline_sample。
- `promotion_gate`：
  - 新增 reason `true_e_pawn_raw_policy_fail_count_nonzero (N)` 與 `true_e_pawn_final_decision_blocked_count_nonzero (N)` 當這兩個 true-failure 計數 > 0 時。
  - `e_pawn_strict_pass_zero_but_equivalent_credit_present` 屬於 informational，放在 `non_blocking_notes` / `e_pawn_scoring_notes`，**不**進 `reasons`。
  - opening specialist gate 不再被 "semantic class e_pawn_central_break clean held-out pass count is zero" 擋住，前提是 equivalent-credit pass rate > 0。general model gate 仍保留。
- `_write_audit_artifacts` 在 `_promotion_gate_summary` 之後才執行，保證 gate 計算讀得到完整 cases。

## exp4_11 anti-poison quarantine + chess_pv override search guard + multi-good revoke（2026-05-11）

exp4_10 把 anti-poison / special-rule / king-safety / override-against-search 變成 diagnostics；exp4_11 把它們接成實際 filter / engine guard。回應 `chess_replays_exp3_example.jsonl` + `_example2.jsonl` 的 Ruy `Bxc6+Nh3` 失敗模式、王行軍、低信心 trusted。

主要報告欄位（新）：

- `low_confidence_trusted_audit`：`confidence_score < 0.5 AND collection_tier=trusted` 的 replay 全列出。example2 全 5 場 0.42 都會被抓。
- `misclassified_resign_audit`：`result_reason=resign` 但 resigning side 最後 3 ply 內有吃子的 case。example2 Game 3（"resign" 卻在 Nxe5 / Nxf7）會被抓。
- `replay_quarantine_index`：合併三個 audit (replay_blunder_screen / low_confidence_trusted_audit / misclassified_resign_audit) 的 quarantine 設定：
  - `quarantine_replay_ids`：replay-level（同一 replay 至少 2 ply blunder、或被 low_conf/resign 標記）
  - `quarantine_ply_keys`：ply-level（單一 ply see-after-recap 損失）
  - `by_source_count`：分來源計數
- `quarantine_summary`：`trusted_replay_count_before/after`, `quarantined_replay_count`, `quarantined_ply_count`, `quarantine_artifact_path`, `poison_filter_applied=True`。
- `audits/replay_blunder_quarantine.jsonl`：每行 `{scope, source, replay_id, ply, side, move, material_delta_cp, after_best_recapture_cp, confidence_score, collection_tier, quarantine_reason}`。summary 不再內嵌 row。

`_extract_engine_move_samples_from_records` 新增 `quarantine_replay_ids` / `quarantine_ply_keys` 參數；evaluation samples 與訓練樣本都使用 filtered records。

`_run_quick_retrain_gate_validation` 流程：
1. `records = _quick_retrain_fixture_records(...)` 原始 replays
2. 跑 `_replay_blunder_screen` / `_low_confidence_trusted_audit` / `_misclassified_resign_audit`
3. `_build_replay_quarantine_index` 合併 quarantine 集合
4. `filtered_records = records - quarantined`
5. `_write_quick_replay_fixture(filtered_records)` 寫 fixture
6. `_extract_engine_move_samples_from_records(filtered_records, quarantine_*)` 給 evaluation samples
7. retraining loop 跑在 filtered_records 上

### chess_pv policy_override search guard（engine-side hard guard）

`services/games/chess_pv.py` 新增 `_override_search_guard(model, board, override_move)`：
- 跑 depth=2 alpha-beta + quiescence=1 alpha-beta 取得 search_best 與 chosen_search_score
- 若 search_best == override → 不擋
- 若 `abs(chosen_search_score) >= 100_000`（mate-like）→ 擋
- 否則跑 depth=1 alpha-beta on `board.push(override)` → 取 `override_search_score = -sub.score`
- 若 `chosen_search_score - override_search_score > 200cp` → 擋
- 回傳 `{rejected, reason, search_best_move, chosen_search_score, override_search_score, disagreement_cp, threshold_cp, mate_like_cp_threshold}`

`_policy_override_info` 結尾呼叫 guard；rejected 時：
- `info["used"] = False`
- `info["reason"] = "rejected_by_search_guard:<sub_reason>"`
- `info["search_guard"] = guard_result`

引擎側因此**真實阻擋**了 c2c4 蓋 e2e4（exp4_10 中 disagreement 1,005,230cp 的 case），不再只是 diagnostic。

### opening multi-good revoke

`_opening_target_margin_audit`：每個 case 額外計算 `chosen_search_score` 與 `best_other_search_score`；若 `best_other - chosen > 200cp`，`multi_good_tie=False`、`multi_good_revoked_by_search_guard=True`、`multi_good_revocation_reason="search_decisive_disagreement"`。

aggregate 新增 `multi_good_revoked_by_search_guard_count`。

## exp4 歷程總表（exp4_01 → exp4_17）

| 輪次 | 主題 | deterministic | special_rule | 關鍵發現 |
|---|---|---|---|---|
| exp4_01-05 | 基礎 quick gate + opening multi-good + MCTS alignment | — | — | 建構驗收框架 |
| exp4_06 | full sanity sample64 baseline | 0.8693 → 0.9231 (+0.0538) | 1/5 | exp4 第一個有正向 deterministic 訊號，但 promotion 因 generalization + low-margin override + e_pawn=0 + hard flank 擋下 |
| exp4_07 | evidence accounting cleanup | 維持 0.9231 | — | catastrophic_regression_source 拆出、`low_margin_override_counted_success_count=0`、historical_cross_experiment_risk_references 分離、`opening_specialist_gate` vs `general_model_promotion_gate` 拆開 |
| exp4_08 | e_pawn equivalence audit | 維持 | — | 證明 e_pawn=0/9 中 16/18 是 opening multi-good scoring issue，不是模型錯 |
| exp4_09 | opening label audit | 維持 | — | `gate_e_pawn_hard_001` (e7e5 棄 d5 兵) 判為 `questionable_label`；`e_pawn_true_raw_policy_fail_count_clean=0` |
| exp4_10 | anti-poison + special-rule + king-safety + override-search 診斷 | 維持 | 1/5 | 5/20 fixture replay 有 see-after-recap blunder；override 1/10 蓋過 search 1M cp；special-rule 1/5；king-safety 0/2 |
| exp4_11 | hardening：quarantine wiring + chess_pv search guard + multi-good revoke | 維持 | 1/5 | 2/10 override 真被 hard reject；5 ply quarantine 寫入 jsonl；但暴露 audit/guard score-source 不一致 |
| exp4_12 | audit/guard score-source consistency + post-filter semantics | 維持 | 2/7 | real alpha-beta vs MCTS artifact 拆開，opening_develop_white false alarm 清除；raw blunder flag 不再 block gate；resignation/draw/special-rule deterministic gate 加入 |
| exp4_13 | special-rule + king-safety curriculum + 修 draw fixture | **0.8154 (−0.0539)** ⚠ | **5/7** ✅ | curriculum 有效但太重 — catastrophic forgetting：sanity exact FEN 全失、d_pawn 歸零、deterministic 退 |
| exp4_14 | balanced curriculum + retention rehearsal + budget + rollback guard | **0.9231 (+0.0538)** ✅ | **5/7** ✅ | 降權 + retention echoes 18 row 翻盤 catastrophic forgetting；special_rule_mass_ratio=0.214 < 0.30 budget；rollback guard 抓到 `mistake_retention_regressed` 新問題 |
| exp4_15 | retention guard bug fix + chess_pv 消費 rule_type + king-safety isolated probe + targeted rule probe | TBD | TBD | exp4_14 `mistake_retention_regressed` 確認是 retention_guard 讀錯來源的 false alarm；trainer 新增 `RULE_FEATURE_BOOST_TYPES` 在 castling/e.p./underpromotion rows 加 extra repeat；king-safety isolated probe 真訓練單獨 model 確認 feature/decision-path gap |
| exp4_16 | rule-aware final fusion for special moves | **0.9231 (+0.0538)** ✅ | **6/7** ⚠ | short castle final 從 `d2d4` 改為 `e1g1`；en-passant 保持 `d5e6`；rule-aware 成功後鎖住 final move，不再被 ordinary policy override 蓋掉；但 knight mate promotion 退成 rook promotion，promotion 仍 false |
| exp4_17 | special-rule subtype + choose/explain consistency + gate accounting cleanup | **0.8693 (=baseline)** ⚠ | **7/7** ✅ | promotion subtype 修正，`e7e8n` 不再被 `e7e8r` 蓋掉；新增 `fixed_depth_*` profile；low-margin override 不再因 move selection 被錯列 blocker；opening alignment 排除 mistake_retention rows；promotion 仍 false，因 broad learning / heavy sanity / deterministic improvement 未過 |
| exp4_18 | full broad learning diagnostic + e_pawn gate accounting fix | **0.8693 (=baseline)** ⚠ | **7/7** ✅ | full heavy sanity 確認 broad generalization 仍未過；`d7d5` 等 opening-book 等價回應修正 e_pawn 假 blocker |
| exp4_19 | guarded overlay attribution | **overlay 0.9231 (+0.0538)** ✅ | **7/7** ✅ | full replacement 仍等於 baseline，但 baseline-default guarded overlay 上界可提升；目前是 label-based diagnostic，下一步要實作 runtime guard |
| exp4_20 | no-label runtime guarded overlay simulator | **runtime overlay 0.9231 (+0.0538)** ✅ | **7/7** ✅ | 不讀 expected label 也能採用 `d7d5` 並擋住 `e7e8n` promotion regression；production choose path 尚未接入 |
| exp4_21 | runtime guarded overlay integration draft | **runtime overlay 0.9231 (+0.0538)** ✅ | **7/7** ✅ | 共用 no-label guard 已接入前台 exp4 choose path；env flag 預設關閉；quick targeted gate 重現 exp4_20 分數，unsafe override=0；heavy sanity skipped，promotion false |

## exp4_17 special-rule subtype + gate accounting cleanup（2026-05-12）

詳細報告：[`2026-05-12_exp4_17_special_rule_subtype_consistency.md`](2026-05-12_exp4_17_special_rule_subtype_consistency.md)

exp4_17 處理 exp4_16 後剩下的 special-rule subtype 問題：

- `castling_short` / `castling_long` 分開。
- `promotion_queen` / `promotion_knight_mate` / `underpromotion_*` 分開。
- rule-aware fusion 在 guard 通過後優先尊重 raw policy rank，避免 generic underpromotion bonus 把 `e7e8n` 轉成 `e7e8r`。
- 新增 `fixed_depth_fast` / `fixed_depth_balanced` / `fixed_depth_strong`，供 deterministic diagnostic / sparring 使用。

實跑：

- `/home/s92137/chess_results/exp4_17_special_rule_subtype_consistency`
- `/home/s92137/chess_results/exp4_17_gate_accounting_cleanup`

結果：

- special-rule deterministic gate：`7/7`
- `promotion_white_knight_mate`：`e7e8n` pass
- opening_final_decision_alignment_passed：`true`
- low_margin_override_counted_success_count：`0`
- promotion：`false`

剩餘 blocker：

- deterministic final 沒高於 baseline。
- heavy sanity skipped，不能證明 broad learning。
- balanced_fusion final decision generalization below threshold。
- hard flank capability gap remains unresolved。

## exp4_16 vs exp5_08 diagnostic sparring（2026-05-12）

詳細報告：[`2026-05-12_exp4_16_vs_exp5_08_sparring.md`](2026-05-12_exp4_16_vs_exp5_08_sparring.md)

本輪不是 promotion benchmark，也不是正式棋力排名。目的只是確認 exp4_16 的 final decision path 是否真的在實戰式對局中採用已學會的 special-rule move，並與 exp5_08 stage candidate 做 diagnostic 對照。

實跑結果：

- result dir：`/home/s92137/chess_results/exp4_vs_exp5_smoke_20260512_032501`
- mode：6-game smoke，`diagnostic_only=true`
- exp4 model：`/home/s92137/chess_results/exp4_16_rule_aware_final_fusion_locked/exp4/checkpoints/20/exp4_quick_candidate_model.json`
- exp5 model：`/home/s92137/chess_results/exp5_08_stage_candidate/chess_experiment_5_nnue_stage_candidate.json`
- WDL：exp4 3 wins / exp5 0 wins / draws 3
- illegal：0
- exp4 audit coverage：65/65
- exp5 audit coverage：60/60

判讀：

- exp4_16 rule-aware final fusion 在真 choose path 中確實會採用 castling / promotion 類 special move。
- 但 subtype selection 尚未完成：expected kingside castling 的 fixture 可能選 queenside castling；promotion fixture 也暴露 queen/rook/knight piece selection 不穩。
- 因此 exp4_17 應聚焦 `castling_short vs castling_long` 與 `promotion_piece_subtype`，不是再增加 generic special-rule anchors。
- exp4 對外 sparring 需要 deterministic / fixed-depth profile；目前 `balanced` profile 仍可能引入 choose/explain 差異與 time-budget variance。

## exp4_16 rule-aware final fusion for special moves（2026-05-12）

詳細報告：[`2026-05-12_exp4_16_rule_aware_final_fusion.md`](2026-05-12_exp4_16_rule_aware_final_fusion.md)

上一輪 exp4_15 已證明 raw policy 能把 `e1g1` / `d5e6` 排到 rank 1，但 final decision path 仍可能採用 `d2d4` / `e2e4` 這類普通 opening pawn push。exp4_16 修的是 final fusion，不再增加 anchors 或提高 special-rule weight。

主要變更：

1. `chess_pv` 新增 rule-aware final fusion：
   - legal special move
   - raw policy rank <= 3
   - real alpha-beta guard 不反對
   - castling / en-passant / promotion / underpromotion 依 rule type 加 guarded bonus
   - raw rank=1 的 special move 可 suppress ordinary opening pawn push

2. rule-aware final fusion 成功後鎖住 final move：
   - `choose_experiment_pv_move` 不再執行普通 policy override。
   - `explain_experiment_pv_decision` 將 ordinary override 標成 `rule_aware_fusion_locked_final_move`。

3. `_candidate_alpha_beta_score` 改為 deterministic fixed-depth path：
   - `time_budget_ms=None`
   - 避免 rule-aware guard 重新引入 time-budget variance。

4. 報告新增 `rule_aware_final_fusion` 與 `audits/rule_fusion_breakdown.jsonl`：
   - `rule_bonus_before/after`
   - `rule_bonus_guard_passed`
   - `opening_push_suppressed_by_rule_context`
   - `alpha_beta_score_expected/selected`
   - `final_score_margin_expected_vs_selected`

實跑結果：

- result dir：`/home/s92137/chess_results/exp4_16_rule_aware_final_fusion_locked`
- verdict：`HIGH_RISK`
- promotion：`false`
- deterministic：baseline `0.8693` → final `0.9231`
- total wall seconds：`1295.989`
- total checkpoint seconds：`1192.641`
- retrain seconds：`85.9`
- special-rule deterministic gate：`6/7`
- failed special rule：`promotion_white_knight_mate`，expected `e7e8n`，final `e7e8r`
- `override_against_search_count_after_fix=0`

Targeted rule result：

- short castle：before final `d2d4` → after final `e1g1`，`rule_bonus_after=420`，guard pass，opening pawn push suppressed。
- en-passant：before/after final 都是 `d5e6`，`rule_bonus_after=420`，guard pass。

exp3 replay 教訓同步套用：

- `chess_replays_exp3_example.jsonl` / `example2.jsonl` 顯示 exp3 主要死因是 king-safety 崩、早后出動、中央兵/側翼兵 prior 過強，以及 engine-lost trusted replay 污染。
- exp4_16 保留 replay quarantine、real alpha-beta search guard、quarantined ply 不進 training；但 king-safety feature gap 仍留給 exp4_17。

下一步：

- exp4_17 不應再堆 anchors。先處理 `promotion_knight_mate` 的 mate-aware promotion scoring，再做 king-safety feature engineering。

## exp4_15 retention guard bug fix + rule_type trainer consumption + king-safety isolated probe（2026-05-12）

exp4_14 報告 `mistake_retention_regressed`，但實際 probe 是 `matched_expected=True` 兩個 checkpoint。發現 retention guard bug：guard 讀 top-level `mistake_retention_probe_results`（由 `_root_engine_row` 後填）→ 永遠是空 list → `mistake_retention_passed=False` 假警報。本輪修好。

主要變更：

1. **bug fix**: `_run_quick_retrain_gate_validation` 內 retention guard 改讀 `before_after_eval.checkpoints[*].mistake_retention_probe`，並用 `None` 而非 `False` 當缺資料訊號，避免假警報。

2. **chess_pv trainer 消費 rule_type**:
   - 新增 `RULE_FEATURE_BOOST_TYPES`: castling_short/long ×2.5、en_passant ×2.5、underpromotion_rook ×2.0、promotion_knight_mate ×2.0、promotion_queen ×1.0
   - `_rule_feature_repeat_bonus(rule_type)` 對應每個 rule_type 給 bonus multiplier
   - `train_experiment_pv_from_replay_samples` 對 rule_type 匹配的 row 加 `bonus_repeats = round(multiplier * max(1, weight))` 多 round 訓練
   - trainer return 新欄位：`rule_feature_rows_consumed`、`rule_feature_bonus_updates`、`rule_feature_breakdown`
   - `normalize_experiment_pv_replay_sample` 保留 `rule_type` 欄位
   - summary 內 `rule_feature_metadata_only=False`（之前是 True，現在 trainer 真的吃 rule_type）

3. **`_king_safety_isolated_probe_run`**（real training）：
   - 複製 baseline model 到 `engine_dir/king_safety_isolated_probe/`
   - 只用 `_king_safety_recovery_curriculum_anchors`（4 row）× 3.0 isolated weight
   - 跑 `train_experiment_pv_from_replay_samples` 訓練單獨 model
   - 用 `_king_safety_after_material_loss_audit` 評估訓練後 pass_rate
   - emit `king_safety_isolated_pass_rate_before/after`、`king_safety_feature_or_decision_path_gap`
   - 若 isolated 仍 0/2 → 確認是 feature/decision-path gap，不是 curriculum weight

4. **`_rule_targeted_probe`**：
   - 對 `targeted_castle_short_white_italian` 與 `targeted_en_passant_white_take` 跑 before vs after
   - 報告每個 case 的 `raw_policy_top1/top3/expected_rank`、`final_top1`、`rank_improved`、`final_move_changed`、`passes_after`
   - `rank_improved_count` 才是真正的 curriculum 進步訊號（不是 final_top1 == expected）

注意：
- 本輪不改 budget 或 curriculum row 數量（exp4_14 已達 0.214 ratio）
- isolated probe 多訓練一個小 model，runtime 預計多 30-90s
- targeted probe 也多 2-4 個 deep `_engine_decision_breakdown` 評估

## exp4_14 balanced curriculum + retention rehearsal + budget + rollback guard（2026-05-12）

exp4_13 把 special-rule 從 1/7 升到 5/7，但 deterministic strength 退步 −0.0539，sanity exact FEN 全部不過，d_pawn_central_break 歸零。判定：curriculum 太強導致 catastrophic forgetting。exp4_14 不擴 curriculum，反過來**降權 + 加 retention**。

主要變更：

- **降低 special-rule weight**:
  - castling_short / castling_long: 3.0 → **1.5**
  - en_passant: 3.0 → **1.5**
  - en_passant_window_closed: 2.0 → **1.0**
  - promotion_queen: 1.0 → **0.75**
  - promotion_knight_mate: 4.0 → **2.0**
  - underpromotion_rook: 4.0 → **2.0**
- **短易位 3 個新變體**：Italian / Open Sicilian / Queen's Gambit 開局後 `e1g1` （weight 1.5 each），讓 short castle prior 從不同位置學起，不依賴單一 FEN
- **`_retention_rehearsal_anchors`（新）**：~16 row 涵蓋
  - 白方開局 multi-good：e2e4 / d2d4 / c2c4 / g1f3 各 weight 1.5
  - 黑方對應 e2e4/d2d4/c2c4/g1f3 後的 multi-good 回應（e7e5/c7c5/d7d5/g8f6）
  - d_pawn / e_pawn easy templates 的 retention echoes (weight 1.5)
  - mistake_retention echoes (e7e5 / d7d5, weight 2.0)
- **`_curriculum_budget_summary`**：summary 內 `curriculum_budget` 報告
  - special_rule_row_count / king_safety_row_count / retention_rehearsal_row_count
  - 各自的 effective_weight_mass
  - special_rule_mass_ratio = special_rule_total_weight / (base + curriculum_total_weight)
  - special_rule_to_retention_mass_ratio
  - **special_rule_mass_budget_passed** = ratio ≤ 0.30
- **`_checkpoint_retention_guard`**：summary 內 `checkpoint_retention_guard` 報告
  - rollback_recommended = True 當任一觸發：
    - deterministic delta < −0.02
    - sanity_exact_fen_pass=False
    - d_pawn_clean_pass_count = 0
    - mistake_retention regressed
  - 不真的 rollback model file（safe_checkpoint_selection 已負責），只 emit reason
- **`rule_feature_metadata_only=True`**：明確告知 trainer 目前只用 fen+move_uci+weight，`is_castling_move` / `is_en_passant` 等 chess_label_features flags 為 diagnostic-only，still 未進 loss
- **`king_safety_isolated_probe`**：本輪不真跑 isolated 訓練（runtime 預算限制），但記錄 `king_safety_feature_or_decision_path_gap`，建議 exp4_15 跑 isolated 確認是 feature 還是 weight 問題
- **artifact path 修正**：curriculum jsonl 從 `engine_dir/checkpoints/audits/` 改為 `engine_dir/audits/`

新 promotion_gate reasons：
- `special_rule_curriculum_budget_exceeded (ratio=X > 0.30)`
- `checkpoint_retention_guard: <reason>`（每個觸發條件一個）

gate 目標（非門檻）：
- special_rule 至少維持 4/7（不追 5/7）
- deterministic 不可低於 baseline
- d_pawn clean held-out 不可歸零
- sanity exact FEN 必須回來

### exp4_14 實跑結果

| 目標 | exp4_13 | exp4_14 | 是否達標 |
|---|---|---|---|
| special_rule pass_rate after | 5/7 (0.714) | **5/7 (0.714)** | ✅ 保住 |
| deterministic vs baseline | −0.0539 ⚠ | **+0.0538** ✅ | 翻盤 |
| sanity_exact_fen_pass | False ❌ | **True** ✅ | 修好 |
| d_pawn_central_break clean pass | 0/9 ⚠ | 5/9 cp10, 3/9 cp20 ✅ | 從歸零回來 |
| sanity_learning verdict | FAILED | PARTIAL_EXACT_OR_LOW_MARGIN_ONLY | 回到 exp4_12 水準 |
| special_rule_mass_ratio | 未量化 | **0.2145 ≤ 0.30** | budget 過 |
| opening_specialist_gate.reasons | 33 | **21**（−12） | 大幅縮減 |
| general_model_promotion_gate.reasons | 36 | **24**（−12） | 大幅縮減 |

**curriculum budget**:
- special_rule_row_count=10、retention_rehearsal_row_count=18、king_safety_row_count=4
- special_rule_effective_weight_mass=14.75 vs retention_rehearsal=28.0 → retention 約 2× special-rule mass
- `special_rule_mass_budget_passed=True`

**checkpoint_retention_guard**:
- rollback_recommended=True，**唯一觸發**: `mistake_retention_regressed`
- deterministic delta=+0.0538（>−0.02 ✓）、sanity_exact_fen_pass=True ✓、d_pawn=3 ✓
- → 下一輪只需處理 mistake_retention，其餘 forgetting 已防住

**未進步項目**:
- castling_short：3 個變體 anchor 仍救不回（chosen=d2d4），確認是 feature/trainer 問題，不是 anchor 覆蓋
- en_passant：chosen=e2e4，`rule_feature_metadata_only=True` 已標示，trainer 沒消費 `is_en_passant` flag
- king_safety：0/2，`king_safety_feature_or_decision_path_gap=True`，isolated probe 留 exp4_15

**下一輪 (exp4_15) 候選**:
1. mistake_retention echo 改成從實際 mistake_retention probe case 拷貝（不要用合成 echoes）
2. king-safety isolated probe — 用 `_run_semantic_specialist_probes` 模式跑單獨訓練
3. trainer side 改造 — 把 `is_en_passant` / `is_castling_move` / `is_promotion` 加進 model feature plane 或 loss
4. en-passant 在 trainer 改造前無法靠 curriculum 修

## exp4 棋力小結（exp4_06 → exp4_13，2026-05-12）

### 能力矩陣

| 能力 | 狀態 | 證據 |
|---|---|---|
| 合法走子 | ✅ 100% | `illegal_rate=0` 全程 |
| 基本戰術 (mate-in-1, free queen) | ✅ 100% | deterministic `tactic`、`blunder_avoid` 均 1.0 |
| 開局多好棋 | ✅ 已分類正確 | e2e4/d2d4/c2c4/Nf3 互為 multi-good tie |
| Mistake retention | ✅ 過 | trusted=10/20 `matched_expected` |
| 特殊走法 | ⚠ 5/7 (curriculum 後) | long castle / promotion / knight-mate / underpromote ✅；short castle / en-passant take ❌ |
| 求和規則 | ✅ 3/3 | avoid stalemate / 50-move / lone king legal |
| 認輸邏輯 | ✅ 4/4 helper diagnostic | early/forced-mate/drawable invariants 都對 |
| 失子後王安全 | ❌ 0/2 | curriculum × 2-3 weight 還不夠 |
| Unseen generalization | ⚠ Partial | `PARTIAL_EXACT_OR_LOW_MARGIN_ONLY`，unseen 0.35-0.39 |
| e_pawn 真學習 | ✅ 是 scoring 問題 | 16/18 multi-good ties；2/18 label_questionable |
| Hard flank | ❌ 0% | general_model blocker 仍在；opening_specialist 已隔離 |
| Replay 毒樣本防護 | ✅ 已防 | 5/20 fixture replay quarantined；example2 5 場 0.42 confidence trusted 都會被抓 |
| Policy override 蓋 search | ✅ 已 hard guard | 2/10 overrides 在 chess_pv 真 alpha-beta 後 reject |

### 量化指標進程

| 指標 | exp4_06 baseline | exp4_07-12 cleanup | exp4_13 +curriculum |
|---|---|---|---|
| deterministic_strength | 0.8693 → 0.9231 | 維持 0.9231 | **0.8154 (−0.0539)** ⚠ |
| special_rule pass_rate | 1/5 (0.2) | 2/7 (0.286) | **5/7 (0.714)** ✅ |
| king_safety pass_rate | 0/2 | 0/2 | 0/2 ❌ |
| draw_handling pass_rate | — | 2/3 (fixture bug) | **3/3** ✅ |
| sanity unseen variant | 0.3889 / 0.3492 | 維持 | 退步（exact FEN 都不過） |
| post_filter_poison_rows | — | 0 ✓ | 0 ✓ |
| promotion_gate.passed | False | False | False |

### 整體判讀

**會的**:
- 走合法棋、看得到 mate-in-1、避免吊子
- 開局基本 (e2e4 / d2d4 / c2c4 / Nf3 都會)
- queen promote、long castle、underpromote
- 不投降亂打（helper 邏輯穩）
- 不送 stalemate when winning

**不會的**:
- short castle（fixture 一拉到開發位置就忘了）
- en-passant take（時機判斷沒概念）
- 失子後王安全（永遠選不相關中央兵推）
- broad generalization（換 FEN 就掉到 raw 0.35）

**致命弱點（與 exp3 example/example2 同類失敗模式）**:
- ply 5 `Bxc6` 主教換兵（policy override 在 mate-like 之外的中等 disagreement 仍會通過）
- 失子後王走中央（exp3 game 4: Ke2→Ke3 被殺）
- engine-lost 的 replay 進訓練（quarantine 機制可擋，trainer 側 label weight 還沒調）

**Elo 對標粗估**：~1100-1400 業餘初級
- 比純隨機強很多（illegal=0、戰術看得到）
- 比業餘人類弱（缺王安全感、特殊走法只會一半、無策略深度）
- 對標 stockfish level 1-3 級

### 下一步真實能力 blocker（exp4_14 候選）

1. 平衡 curriculum weight vs sanity retention — exp4_13 顯示 ×4 weight 造成 catastrophic forgetting
2. King-safety 需要更多 anchor + 更高 weight 但同時保 sanity — 4 個 row × 3 weight 不夠
3. Castle short / en-passant 仍需強化
4. Hard flank capability gap — general_model promotion 必過
5. Engine-lost replay 改為負樣本或低 weight — trainer side 改造

距離 production-quality opening specialist 估計還要 2-3 輪 curriculum + retention guard iteration。距離 general model 還要 5+ 輪。

## exp4_13 special-rule curriculum + king-safety recovery curriculum + draw fixture（2026-05-12）

exp4_12 把 audit/guard 對齊；exp4_13 開始補真實能力缺陷。本輪不調整 evidence accounting，專注：

1. **修 draw fixture**：`draw_lone_king_must_play_legal.good_moves` 加 `e1c1`（白方在該 FEN 仍保有 queenside castling rights，castle 是合法且常選的走法）。
2. **special-rule curriculum anchors**（`_special_rule_curriculum_anchors`）：8 個 clean training rows，覆蓋 castling_short/long、en_passant、promotion_queen/knight_mate、underpromotion_rook、en_passant_window_closed。weights:
   - castling × 3.0
   - en_passant × 3.0
   - underpromotion × 4.0
   - knight_mate × 4.0
   - queen promotion × 1.0
   - en_passant_window_closed × 2.0
3. **king-safety recovery curriculum**（`_king_safety_recovery_curriculum_anchors`）：4 個 clean training rows，覆蓋失子後 castle / retreat / develop bishop / 避免推中央兵。weight × 2.0–3.0。
4. **before/after gate**：summary 新增 `special_rule_pass_rate_before/after`、`special_rule_pass_by_rule_type_before/after`、`king_safety_pass_rate_before/after`、`king_safety_walked_to_center_before/after`，跑 baseline_model_path 和 final after_model_path 各一次。
5. **gate scope policy**:
   - `castling_short/long` fail → opening_specialist + general_model 都 block（castling 是開局行為）
   - `en_passant / underpromotion / promotion_knight_mate / draw_handling_*` fail → 只 block general_model（不屬於 opening 範疇）
   - `king_safety_after_material_loss_walked_to_center` → general_model only
6. **artifact**:
   - `audits/special_rule_curriculum.jsonl`：8 row
   - `audits/king_safety_curriculum.jsonl`：4 row
   - summary 不放完整 row，只放 count + path

注意:
- 本輪 quick gate 跑了**兩次** deterministic 評估（baseline + final），會多 ~30s
- curriculum rows 在每個 checkpoint 都注入（trusted=10 / trusted=20 都加）
- curriculum 不可與 quarantine ply 重疊（FEN 是 template，從不從 replay history 衍生）

## exp4_12 audit/guard score-source 一致性 + quarantine post-filter semantics（2026-05-11）

exp4_11 暴露的問題：validation `policy_override_audit` 用 MCTS final_combined_score 算 disagreement，未探訪的 move 預設值是 -999996，造成 `opening_develop_white` 看似 1,005,230cp disagreement，但 chess_pv engine guard 用真 alpha-beta 只看到 76cp。兩個系統不一致。exp4_12 統一 source-of-truth。

主要報告欄位變更：

- `policy_override_audit` 內每個 case 新增：
  - `real_disagreement_cp` / `real_search_best_move` / `real_chosen_search_score` / `real_override_search_score`：取自 `policy_override.search_guard`（chess_pv 真實 alpha-beta）
  - `search_guard_rejected` / `search_guard_reason` / `search_guard_threshold_cp` / `mate_like_search_score`
  - `mcts_disagreement_cp` / `mcts_best_move` / `mcts_best_score`：原 MCTS 計算，現在標 `mcts_score_diagnostic_only=True`
  - `mcts_unvisited_default_detected`：當 chosen_fused_score ≤ -900,000 或 best_mcts ≥ 900,000 時為 True
  - `is_mcts_artifact_false_alarm`：當 legacy MCTS rule 會 fire 但 real alpha-beta 不會 reject
- `policy_override_audit` 內 aggregate 新增：
  - `override_against_search_count_before_fix`（legacy MCTS rule 觸發數）
  - `override_against_search_count_after_fix`（real alpha-beta rule 觸發數，gate 用這個）
  - `override_rejected_by_engine_guard_count`
  - `mcts_artifact_false_alarm_count`
  - `max_real_disagreement_cp` / `max_mcts_artifact_disagreement_cp`
- `_opening_target_margin_audit` 內 multi_good_revoke 改用 `policy_override.search_guard` 而非 MCTS chosen_breakdown.search_score 差距：
  - `multi_good_revoked_by_real_search_guard_count`：real alpha-beta > 200cp 或 mate-like 觸發
  - `multi_good_revoked_by_mcts_artifact_count`：legacy MCTS 觸發但 real 不觸發（false alarm 計數）
  - per-case 新增 `real_disagreement_cp`、`mate_like_guard`、`search_guard_rejected` 欄位

`quarantine_summary` 拆 raw vs post-filter：
- `raw_trusted_replay_blunder_flagged_count`：原 flag 數（5）
- `poison_filter_applied`：True
- `post_filter_poison_training_rows`：filter 後仍漏進訓練的 row 數（預期 0）
- `post_filter_poison_eval_rows`：同上 for evaluation samples

promotion_gate 變更：
- 原 `trusted_replay_blunder_screen_flagged_count_nonzero (5)` 不再是 blocker（filter 已成功應用）
- 新 reasons:
  - `poison_filter_not_applied`（raw_flag > 0 且 poison_filter_applied=False）— 不該發生
  - `post_filter_poison_training_rows_nonzero (N)`
  - `post_filter_poison_eval_rows_nonzero (N)`
- raw_blunder_flagged > 0 但 post_filter=0 時改進 `e_pawn_scoring_notes` (non-blocking)

## exp4_12（延後）求和 + 認輸 + 特殊走法擴充 + chess label features（2026-05-11）

延續 exp4_10/11 anti-poison + override guard 後，補上**chess rule completeness**：求和、認輸、特殊走法在 deterministic gate 與 label schema 內都有可量化的驗收。

新增報告欄位：

- `resignation_deterministic_gate`：對 `services.games.chess_pv.should_resign` 做 4 case 驗收：
  - `resign_must_not_resign_early_game`（ply<30 即使 eval=-1500 也不可 resign）
  - `resign_must_not_resign_mid_game_minor_loss`（eval=-300 不可 resign）
  - `resign_may_resign_forced_mate_in_3`（mate_distance ≤ 5 可 resign）
  - `resign_must_not_resign_drawable_losing`（eval=-800 但無 mate 不可 resign）
  - rule: `forced_mate within forced_mate_distance_limit → resign_allowed=True`，其它情況預設 `should_resign=False`
- `draw_handling_deterministic_gate`：3 case 驗收 — `avoid_stalemate_when_winning` (K+Q vs K)、`50move_reset_when_winning` (halfmove_clock=98)、`legal_move_when_lone_king`。bad_moves 列表會抓「白棋一手送 stalemate」這類錯誤。
- `_special_rule_deterministic_gate` 擴充：新增 `underpromotion_rook_avoid_stalemate`、`en_passant_window_closed`，從 5 case 擴展到 7 case
- `_chess_label_features(fen, side, move_uci)` helper：emit `is_castling_move / is_en_passant / is_promotion / promotion_piece / can_castle_{kingside,queenside} / can_claim_threefold / can_claim_threefold_after_move / passed_pawn_rank / halfmove_clock_{before,after} / draw_escape_available / mate_distance / resign_allowed / resign_forbidden`。training row 可消費這些做 weight × 2~4 的 special-rule anchor

`services/games/chess_pv.py` 新增 `should_resign(board, search_score, ply_count, mate_distance)` 函式：
- `RESIGN_GUARD_MIN_PLY = 30`：30 ply 內 `resign_forbidden=True`
- `RESIGN_GUARD_FORCED_MATE_DISTANCE_LIMIT = 5`：5 步內被將死 `resign_allowed=True`
- `RESIGN_GUARD_SEARCH_SCORE_THRESHOLD_CP = -900`：未達 -900cp 不認輸
- 引擎本身**不會自動投降**，這個 helper 只給 deterministic gate 跑驗收用；engine_pv 主 inference 路徑仍走完整 search → move。

promotion_gate 新增 3 個 blocker reasons（只在新 gate < 1.0 時觸發）：
- `resignation_deterministic_gate_pass_rate_below_one (N)`
- `draw_handling_deterministic_gate_pass_rate_below_one (N)`
- `special_rule_deterministic_gate_pass_rate_below_one (N)` (sequel of exp4_10)

注意：

- chess_label_features 是 audit/training-side 工具，本輪只暴露 API；train pipeline 接消費後再啟用 weight。
- should_resign helper 為 diagnostic-only；engine 不會因 resign_allowed=True 自動投降，避免 production regression。
- 三個新 gate 的 case 都選了**真正能在 engine inference 內測**的 FEN，不是 mock，所以 pass rate 反映模型實際能力。

### 限制與遞延

- replay-level engine-lost 不作正樣本（需要 trainer row weight 改造）→ exp4_13
- 重複失敗模式偵測（first-N-plies hash + 統計）→ exp4_12
- replay 內王行軍偵測（需要 walk 整盤）→ exp4_12
- special-rule curriculum / king-safety curriculum（補訓練資料、需動 trainer）→ exp4_12

## 歷史 exp4_09 → exp4_08 下一步建議參考

下一步建議（exp4_09 候選）：

- 對 `true_e_pawn_raw_policy_fail_count` 的 case 跑 targeted rehearsal（positive=expected e_pawn move；negative 只用明確劣於 teacher 的競爭 move，排除 c7c5 / d7d5 / c2c4 / d2d4 等多好棋）。
- 對 `true_e_pawn_final_decision_blocked_count` 的 case 做 final decision / MCTS / fusion calibration（不可造成 tactic/blunder regression）。
- 在 rehearsal 跑完後比較 `e_pawn_rank_before_after` 與 `e_pawn_margin_before_after`。

## exp4_09 opening label audit + specialist gate cleanup（2026-05-11）

exp4_08 顯示 e_pawn 真失敗只剩 1 個 case (`gate_e_pawn_hard_001` × cp10/cp20)；該 case 的 expected `e7e5` 在 FEN `1.Nf3 d5 2.c4` 後會棄 d5 兵（teacher_top3 是 `d5c4 / a7a5 / a7a6`），可能是 label 問題。exp4_09 在做任何 rehearsal 前，先把 label 審乾淨。

主要報告欄位：

- `opening_label_audit`（新）：對所有 `true_e_pawn_raw_policy_fail` / `true_e_pawn_final_decision_blocked` / opening_target_margin_audit 的 `raw_policy_fail` case 逐題輸出 `case_id` / `fen` / `side` / `expected_move` / `raw_top1` / `raw_top3` / `final_top1` / `final_top3` / `teacher_top3` / `teacher_top5` / `static_best_move` / `static_cp_delta` / `expected_rank` / `label_quality` / `clean_true_failure` 等欄位。
- `label_quality` 分類（由 `_classify_label_quality` 統一決定）：
  - `clean_label`：`static_cp_delta` > -50 或 expected 在 teacher_top3 內
  - `questionable_label`：-150 ≤ cp ≤ -50 且 expected 不在 teacher_top3
  - `relabel_recommended`：-300 < cp ≤ -150
  - `quarantine_recommended`：cp ≤ -300
  - `label_unverified`：無 cp 資料且 teacher 不支持 expected
- `clean_true_failure`：必須是 `clean_label` 且 final_top1 不是 teacher 支持的多好棋替代。
- `*_clean` aggregate：`e_pawn_true_raw_policy_fail_count_clean`、`e_pawn_true_final_decision_blocked_count_clean` 把 questionable / relabel / quarantine 排除後重算。
- `previous_e_pawn_failure_was_label_or_multigood_issue=true` 當且僅當：原本 raw/final-blocked count > 0 但 clean 後均歸零。
- `opening_specific_learning_evidence_status`：`insufficient_clean_true_fail_cases` 表示剩下 true failure 都是 label noise，不是學習缺陷；反之為 `clean_true_failure_present`。

`promotion_gate` 變化：

- opening specialist gate 使用 `*_clean` count 判定。若所有 raw failure 都被 reclassify，opening specialist 不再因該 case 被擋。
- `opening final decision alignment failed` reason 若對應 label audit row 全部都是 questionable，移入 `e_pawn_scoring_notes`（non-blocking），否則保留為 blocker。
- 新增非 blocker note：`previous_e_pawn_failure_was_label_or_multigood_issue=true` / `opening_specific_learning_evidence_status=insufficient_clean_true_fail_cases`。
- `engine_verdict_extension = PARTIAL_LABEL_AUDIT_CLEANUP_NO_BROAD_GENERALIZATION` 當 label cleanup 結束但 gate 仍未通過。

`summary_size_top_contributors`（新）：列出 summary.json 內 top-8 最大 key（依序列化 JSON bytes 排序），方便後續做 artifact slimming v2。本輪不會主動拆 `before_after_eval` / `retrain_result` / `checkpoint_consistency`，但提供量化依據。

注意：

- 本輪不做 targeted rehearsal。Rehearsal 只能在 `clean_true_failure=True` 的 case 上做。
- mistake_retention probe 仍保留 strict mode；mistake-retention fallback 仍獨立記錄在 `targeted_mistake_retention_success`，不可被 label audit 改成 broad opening generalization。
- audits/*.jsonl 已包含 exp4_08 的 opening_target_margin_audit + e_pawn_clean_held_out_diagnosis；本輪 `opening_label_audit` 的 case rows 仍留在 summary（總筆數 ~6 不大）。

## 歷程報告

- [2026-05-12 Exp4_19 guarded overlay attribution](2026-05-12_exp4_19_guarded_overlay_attribution.md)
- [2026-05-12 Exp4_20 runtime guarded overlay simulator](2026-05-12_exp4_20_runtime_guarded_overlay.md)
- [2026-05-12 Exp4_21 runtime guarded overlay integration draft](2026-05-12_exp4_21_runtime_guarded_overlay_integration.md)
- [2026-05-12 Exp4_18 full broad learning diagnostic](2026-05-12_exp4_18_full_broad_learning_diagnostic.md)
- [2026-05-12 Exp4_17 special-rule subtype consistency](2026-05-12_exp4_17_special_rule_subtype_consistency.md)
- [2026-05-12 Exp4_16 vs Exp5_08 diagnostic sparring](2026-05-12_exp4_16_vs_exp5_08_sparring.md)
- [2026-05-12 Exp4_16 rule-aware final fusion](2026-05-12_exp4_16_rule_aware_final_fusion.md)
- [2026-05-11 Exp4 對齊 Exp3 Exp34 驗收鏈](2026-05-11_exp4_exp34_gate_alignment.md)
- [2026-05-11 Exp4_05 暫存工作紀錄：opening margin / MCTS 對齊](2026-05-11_exp4_05_working_state_tmp.md)
