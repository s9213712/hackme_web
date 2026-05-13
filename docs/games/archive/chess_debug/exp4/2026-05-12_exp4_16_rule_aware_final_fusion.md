# exp4_16：rule-aware final fusion for special moves

## 上一輪問題

exp4_15 已確認 `rule_type` 被 trainer 消費後，raw policy 其實已經學到部分 special-rule move：

- `targeted_castle_short_white_italian`：`e1g1` expected rank 從 35 進步到 1，但 final decision 仍可能被 `d2d4` 這類 opening pawn push 蓋掉。
- `targeted_en_passant_white_take`：`d5e6` raw policy 已是 rank 1，但 final path 仍可能被普通 opening prior / policy override 取代。
- `king_safety` isolated probe 仍 0/2，表示這不是 curriculum 或 weight 問題，而是 feature / decision-path gap。

因此 exp4_16 不再增加 anchors、weight 或 FEN，而是修 final decision / fusion path。

## 實驗命令

完整 quick gate（未跳過 heavy sanity）：

```bash
python3 <repo>/scripts/games/chess_live_learning_validation.py \
  --engines exp4 \
  --quick-retrain-gate \
  --quick-retrain-max-samples 64 \
  --output-root <chess_results>/exp4_16_rule_aware_final_fusion_locked
```

測試：

```bash
python3 -m py_compile services/games/chess_pv.py scripts/games/chess_live_learning_validation.py tests/games/test_games.py
pytest tests/games/test_games.py::test_experiment_pv_rule_aware_fusion_adopts_learned_special_moves tests/games/test_games.py::test_experiment_pv_rule_aware_fusion_locks_policy_override -q
pytest tests/scripts/games/test_chess_live_learning_validation_script.py -q
pytest tests/games/test_games.py -q
git diff --check
```

## 修改項目

1. `services/games/chess_pv.py`
   - 新增 rule-aware final fusion，支援 castling / en-passant / promotion / underpromotion。
   - special-rule move 必須 legal、raw policy rank <= 3、real alpha-beta guard 不反對，才可拿到 rule bonus。
   - 在 rule context 下，如果 raw rank=1 的 special move 被普通 central pawn push 蓋掉，會啟用 `opening_push_suppressed_by_rule_context`。
   - rule-aware fusion 成功後鎖住 final move，普通 `high_confidence_policy_override` 不可再覆蓋。
   - `_candidate_alpha_beta_score` 改為 fixed-depth deterministic search，移除 `time_budget_ms=100`。
   - `normalize_experiment_pv_replay_sample` / `build_experiment_pv_sample_from_position` 保留 `rule_type`，避免 fen/move row 遺失 special-rule metadata。

2. `scripts/games/chess_live_learning_validation.py`
   - `_rule_targeted_probe` 增加 score breakdown：`alpha_beta_score_*`、`opening_principle_score_*`、`rule_bonus_before/after`、`rule_bonus_guard_passed`、`opening_push_suppressed_by_rule_context`。
   - 新增 `rule_aware_final_fusion` summary block。
   - 詳細 per-case 輸出到 `audits/rule_fusion_breakdown.jsonl`。
   - `SUMMARY.md` 顯示 exp4 rule-aware final fusion 摘要。

3. `tests/games/test_games.py`
   - 補 explain path 測試：special-rule final 必須選 expected，且 `chosen_reason == rule_aware_final_fusion_bonus`。
   - 補 choose path 測試：實戰用 `choose_experiment_pv_move` 也必須採用 rule-aware move。
   - 補 lock 測試：rule-aware final fusion 成功後，即使 ordinary policy override 想選 `d2d4`，也必須被標成 `rule_aware_fusion_locked_final_move`。

## exp3 replay 反省與 exp4 防線

參考：

- `docs/games/chess_debug/chess_replays_exp3_example.jsonl`
- `docs/games/chess_debug/chess_replays_exp3_example2.jsonl`

觀察到的 exp3 失敗型態：

- `example`：1 盤、engine 輸、checkmate；engine 13 手中有 4 次王移動，其中 2 次走向中央，且有 6 次中央兵推進。
- `example2`：5 盤、engine 輸 4 盤；engine 66 手中有 15 次王移動、3 次王走向中央、2 次早后出動、9 次側翼兵推進、17 次中央兵推進。
- 常見問題是：失子後 king-safety 崩、早后或側翼兵亂動、opening/central pawn prior 過強、trusted replay 若不過濾會把壞棋餵回模型。

exp4_16 對應防線：

- 保留 `replay_blunder_quarantine` 與 quarantine post-filter，quarantined ply 不進 training。
- 不把 MCTS unvisited artifact 當 search disagreement evidence，仍以 real alpha-beta guard 為準。
- special-rule learned move 必須通過 search guard，避免無腦 override。
- ordinary opening pawn push 不可在 special-rule raw top1 且 guard safe 時蓋掉 special move。
- king-safety 仍未解，保留為 exp4_17 feature engineering，不在 exp4_16 用權重硬推。

## 實跑結果

結果目錄：

- `<chess_results>/exp4_16_rule_aware_final_fusion_locked`
- detailed audit：`<chess_results>/exp4_16_rule_aware_final_fusion_locked/exp4/audits/rule_fusion_breakdown.jsonl`

核心 verdict：

- `overall_verdict=HIGH_RISK`
- `promotion_gate.passed=false`
- deterministic score：baseline `0.8693` → final `0.9231`，delta `+0.0538`
- total wall seconds：`1295.989`
- total checkpoint seconds：`1192.641`
- retrain seconds：`85.9`
- deterministic eval seconds：`38.125`

Rule-aware targeted probe：

| case | before final | after raw top1 | after final | rule bonus | guard | 結論 |
|---|---:|---:|---:|---:|---:|---|
| `targeted_castle_short_white_italian` | `d2d4` | `e1g1` | `e1g1` | 420 | pass | final-decision blocker 修掉 |
| `targeted_en_passant_white_take` | `d5e6` | `d5e6` | `d5e6` | 420 | pass | 保持正確 |

Rule fusion aggregate：

- `targeted_case_count=2`
- `passes_after_count=2`
- `final_move_changed_count=1`
- `opening_push_suppressed_count=2`
- `guard_passed_count=2`

Special-rule deterministic gate：

- `6/7 = 0.8571`
- 通過：short castle、long castle、en-passant、en-passant window closed、queen promotion、rook underpromotion。
- 失敗：`promotion_white_knight_mate`，expected `e7e8n`，final 選 `e7e8r`。

Opening / override：

- `multi_good_tie_count=5/6`
- `multi_good_credit_applied_count=5`
- `low_margin_override_counted_success_count=0`
- `override_against_search_count_after_fix=0`
- `opening_final_decision_alignment_passed=false`
- `failure_type_counts={passed:4, multi_good_tie_not_failure:1, raw_policy_fail:1}`

主要 blocker：

- `special_rule_deterministic_gate_pass_rate_below_one (0.8571)`
- `true_e_pawn_final_decision_blocked_count_nonzero (4)`
- sanity probe 仍偏 exact FEN memorization，seen/unseen generalization 未達門檻。
- contextual flank hard clean pass rate 仍為 0。
- hard-negative margin / semantic hard-negative margin 仍為負。
- checkpoint retention instability 仍存在。

## 結果判讀

exp4_16 解掉的是 exp4_15 指出的「raw policy 已學會但 final decision 不採用」問題，尤其 short castle 從 `d2d4` 變成 `e1g1`，這是本輪最重要成果。

但 promotion 擋下合理。原因不是 rule-aware fusion 方向錯，而是修 final fusion 後暴露出另一個 special-rule gap：knight mate promotion 被 rook promotion 取代。此外，broad generalization、e_pawn final decision、hard flank、checkpoint retention 仍未過。

## 後續方向

建議 exp4_17 分兩段做，不要混在同一個大 patch：

1. **special promotion decision cleanup**
   - 針對 `promotion_knight_mate` 做 mate/stalemate-aware promotion scoring。
   - underpromotion 不能只看 material value，必須把 mate-in-one / stalemate avoid reason 納入 final fusion。

2. **king-safety feature engineering**
   - 加入 king exposure、castle availability、material-loss context、safe king zone、irrelevant central pawn push penalty。
   - 目標是解 exp3 replay 顯示的失子後王亂走、中央兵 prior 過強問題。

promotion gate 不應下修；下一輪仍需維持 deterministic >= baseline、override_against_search=0、quarantine clean、mistake retention pass、special-rule 不退步。
