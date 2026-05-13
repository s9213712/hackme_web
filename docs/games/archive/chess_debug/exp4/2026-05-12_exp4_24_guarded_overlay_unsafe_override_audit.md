# exp4_24：Guarded Overlay Unsafe Override Audit（2026-05-12）

## 結論

promotion=false；retrain_attempted=false；runtime_mutated=false。

本輪只讀 exp4_23 full diagnostic artifact，沒有重新訓練，也沒有改 production runtime。

## 輸入

- result_dir: `<repo>/runtime/chess_results/exp4_23_guarded_overlay_broad_sanity_gate_full`
- summary: `<repo>/runtime/chess_results/exp4_23_guarded_overlay_broad_sanity_gate_full/exp4/summary.json`

## exp4_23 Guarded Overlay 狀態

- baseline score: `0.8693`
- final replacement score: `0.8693`
- actual runtime guarded score: `0.9231`
- delta vs baseline: `0.0538`
- deterministic unsafe override: `0`
- simulator mismatch: `0`
- guarded_overlay_broad_sanity_gate.passed: `False`
- gate reasons: `['guarded overlay sanity unsafe override at trusted=10', 'guarded overlay unseen variant pass rate regressed at trusted=20', 'guarded overlay sanity unsafe override at trusted=20']`

## Unsafe Override Summary

| checkpoint | rows | unsafe | regression_rows | unsafe_by_split |
| --- | --- | --- | --- | --- |
| 10 | 270 | 14 | 14 | {'seen': 8, 'unseen': 6} |
| 20 | 267 | 12 | 12 | {'seen': 8, 'unseen': 4} |

- total unsafe_override_count: `26`
- total regression_row_count: `26`
- unsafe_by_split: `{'seen': 16, 'unseen': 10}`
- unsafe_by_guard_reason: `{'runtime_static_and_rule_guard_passed': 26}`
- unsafe_by_semantic: `{'d_pawn_central_break': 12, 'e_pawn_central_break': 12, 'flank_pawn_push': 2}`

## Root Cause Clusters

| root_cause | count |
| --- | --- |
| baseline_already_correct_but_overlay_replaced_it | 26 |
| broad_ordinary_opening_override | 24 |
| final_move_correct_only_on_exact_training_fen_but_unsafe_on_variant | 5 |
| missing_or_weak_score_margin | 24 |
| multi_good_opening_label_false_negative_or_topk_conflict | 26 |
| promotion_en_passant_capture_priority_interaction | 2 |

## Unsafe Rows（摘要）

| trusted | split | case_id | expected | baseline | final | guard | semantic | difficulty | root_causes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | seen | gate_e_pawn_easy_002:train | e7e5 | e7e5 | d7d5 | runtime_static_and_rule_guard_passed | e_pawn_central_break | easy | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 10 | seen | gate_e_pawn_easy_003:train | e7e5 | e7e5 | d7d5 | runtime_static_and_rule_guard_passed | e_pawn_central_break | easy | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 10 | seen | gate_flank_hard_003:train | c7c5 | c7c5 | f8b4 | runtime_static_and_rule_guard_passed | flank_pawn_push | hard | baseline_already_correct_but_overlay_replaced_it, multi_good_opening_label_false_negative_or_topk_conflict, promotion_en_passant_capture_priority_interaction |
| 10 | seen | gate_e_pawn_easy_002:central_flank_train:1 | e7e5 | e7e5 | d7d5 | runtime_static_and_rule_guard_passed | e_pawn_central_break | easy | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 10 | seen | gate_e_pawn_easy_002:central_flank_train:2 | e7e5 | e7e5 | d7d5 | runtime_static_and_rule_guard_passed | e_pawn_central_break | easy | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 10 | seen | gate_e_pawn_easy_003:central_flank_train:1 | e7e5 | e7e5 | d7d5 | runtime_static_and_rule_guard_passed | e_pawn_central_break | easy | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 10 | seen | gate_e_pawn_easy_003:central_flank_train:2 | e7e5 | e7e5 | d7d5 | runtime_static_and_rule_guard_passed | e_pawn_central_break | easy | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 10 | seen | gate_flank_hard_003:central_flank_train:1 | c7c5 | c7c5 | f8b4 | runtime_static_and_rule_guard_passed | flank_pawn_push | hard | baseline_already_correct_but_overlay_replaced_it, multi_good_opening_label_false_negative_or_topk_conflict, promotion_en_passant_capture_priority_interaction |
| 10 | unseen | gate_e_pawn_easy_002:validation | e7e5 | e7e5 | d7d5 | runtime_static_and_rule_guard_passed | e_pawn_central_break | easy | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, final_move_correct_only_on_exact_training_fen_but_unsafe_on_variant, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 10 | unseen | gate_e_pawn_easy_003:validation | e7e5 | e7e5 | d7d5 | runtime_static_and_rule_guard_passed | e_pawn_central_break | easy | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, final_move_correct_only_on_exact_training_fen_but_unsafe_on_variant, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 10 | unseen | gate_e_pawn_easy_003:central_flank_validation:1 | e7e5 | e7e5 | d7d5 | runtime_static_and_rule_guard_passed | e_pawn_central_break | easy | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, final_move_correct_only_on_exact_training_fen_but_unsafe_on_variant, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 10 | unseen | gate_e_pawn_easy_001 | e2e4 | e2e4 | c2c4 | runtime_static_and_rule_guard_passed | e_pawn_central_break | easy | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 10 | unseen | gate_e_pawn_easy_002 | e7e5 | e7e5 | d7d5 | runtime_static_and_rule_guard_passed | e_pawn_central_break | easy | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 10 | unseen | gate_e_pawn_easy_003 | e7e5 | e7e5 | d7d5 | runtime_static_and_rule_guard_passed | e_pawn_central_break | easy | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 20 | seen | gate_d_pawn_easy_002:train | d7d5 | d7d5 | e7e5 | runtime_static_and_rule_guard_passed | d_pawn_central_break | easy | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 20 | seen | gate_d_pawn_easy_003:train | d7d5 | d7d5 | e7e5 | runtime_static_and_rule_guard_passed | d_pawn_central_break | easy | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 20 | seen | gate_d_pawn_medium_002:train | d7d5 | d7d5 | e7e5 | runtime_static_and_rule_guard_passed | d_pawn_central_break | medium | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 20 | seen | gate_d_pawn_easy_002:central_flank_train:1 | d7d5 | d7d5 | e7e5 | runtime_static_and_rule_guard_passed | d_pawn_central_break | easy | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 20 | seen | gate_d_pawn_easy_002:central_flank_train:2 | d7d5 | d7d5 | e7e5 | runtime_static_and_rule_guard_passed | d_pawn_central_break | easy | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 20 | seen | gate_d_pawn_easy_003:central_flank_train:1 | d7d5 | d7d5 | e7e5 | runtime_static_and_rule_guard_passed | d_pawn_central_break | easy | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 20 | seen | gate_d_pawn_easy_003:central_flank_train:2 | d7d5 | d7d5 | e7e5 | runtime_static_and_rule_guard_passed | d_pawn_central_break | easy | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 20 | seen | gate_d_pawn_medium_001:central_flank_train:1 | d7d5 | d7d5 | e7e5 | runtime_static_and_rule_guard_passed | d_pawn_central_break | medium | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 20 | unseen | gate_d_pawn_easy_002:validation | d7d5 | d7d5 | e7e5 | runtime_static_and_rule_guard_passed | d_pawn_central_break | easy | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, final_move_correct_only_on_exact_training_fen_but_unsafe_on_variant, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 20 | unseen | gate_d_pawn_easy_002:central_flank_validation:1 | d7d5 | d7d5 | e7e5 | runtime_static_and_rule_guard_passed | d_pawn_central_break | easy | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, final_move_correct_only_on_exact_training_fen_but_unsafe_on_variant, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 20 | unseen | gate_d_pawn_medium_001 | d7d5 | d7d5 | e7e5 | runtime_static_and_rule_guard_passed | d_pawn_central_break | medium | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |
| 20 | unseen | gate_d_pawn_medium_002 | d7d5 | d7d5 | e7e5 | runtime_static_and_rule_guard_passed | d_pawn_central_break | medium | baseline_already_correct_but_overlay_replaced_it, broad_ordinary_opening_override, missing_or_weak_score_margin, multi_good_opening_label_false_negative_or_topk_conflict |

## 建議

- No-score or zero-margin ordinary rows must not pass guarded overlay unless a special-rule oracle strongly supports the move.
- Require stricter static/top-k margin for ordinary non-special moves.
- Add a second-check or blacklist for guard reasons that produced unsafe overrides, especially runtime_static_and_rule_guard_passed on broad variants.
- Avoid overriding baseline when baseline is already correct/safe in broad sanity variants.
- Preserve deterministic +0.0538 only after broad unsafe_override_count reaches 0.

## 下一步

exp4_25 應收緊 guarded runtime guard，先用這批 unsafe rows 做 targeted replay，unsafe_override_count 必須降到 0 才值得重跑 full broad sanity。
