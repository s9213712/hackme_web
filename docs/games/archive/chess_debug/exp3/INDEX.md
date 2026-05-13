# Exp3 Debug Reports

本資料夾保留 exp3 暫停前的完整 debug 歷程。原本的 `reports/` 已改名為 `exp3/`，原本上一層的 `chess_debug.md` 也已併入本資料夾。

每份報告包含：上一個 exp 的問題、實驗命令全文、分析與修改項目、實際結果、結果判讀、未來修正方向、exp3/exp4 適用性。

| Exp | 報告 | 合併 run 數 |
| --- | --- | ---: |
| EXP1 | [Live Learning Validation Baseline](exp1_live_learning_validation_baseline.md) | 1 |
| EXP2 | [30-game Full Validation 與 Deprecated Heavy Benchmark](exp2_30_game_full_validation_deprecated_heavy_benchmark.md) | 5 |
| EXP3 | [Quick Retrain Gate](exp3_quick_retrain_gate.md) | 3 |
| EXP4 | [Replay Fixture Diversity 與 Mistake Retention Probe](exp4_replay_fixture_diversity_mistake_retention_probe.md) | 2 |
| EXP5 | [Sanity Learning Probe Failure Diagnosis](exp5_sanity_learning_probe_failure_diagnosis.md) | 0 |
| EXP6 | [Contrastive Trainer 與 Raw/Final Decision Learning 拆分](exp6_contrastive_trainer_raw_final_decision_learning.md) | 4 |
| EXP7 | [Exact FEN 到 Seen/Unseen Variants](exp7_exact_fen_seen_unseen_variants.md) | 1 |
| EXP8 | [Unseen Variant Generalization](exp8_unseen_variant_generalization.md) | 2 |
| EXP9 | [Policy-Search Integration](exp9_policy_search_integration.md) | 3 |
| EXP10 | [Raw Policy Unseen Generalization 與 Hard Negatives](exp10_raw_policy_unseen_generalization_hard_negatives.md) | 1 |
| EXP11 | [Board Representation Invariance](exp11_board_representation_invariance.md) | 2 |
| EXP12 | [Stability Curriculum 與 Checkpoint Consistency](exp12_stability_curriculum_checkpoint_consistency.md) | 5 |
| EXP13 | [Early Checkpoint 與 Hard-negative Margin Stabilization](exp13_early_checkpoint_hard_negative_margin_stabilization.md) | 2 |
| EXP14 | [Ablation 找出泛化失敗主因](exp14_ablation.md) | 5 |
| EXP15 | [Held-out Label Quality Gate](exp15_held_out_label_quality_gate.md) | 1 |
| EXP16 | [Rebuild Clean Held-out Pool](exp16_rebuild_clean_held_out_pool.md) | 1 |
| EXP17 | [Central Pawn Structure 與 Move Semantics Disentanglement](exp17_central_pawn_structure_move_semantics_disentanglement.md) | 1 |
| EXP18 | [Semantic Embedding Separation](exp18_semantic_embedding_separation.md) | 2 |
| EXP19 | [Semantic Class Balance 與 Style Profile 分離](exp19_semantic_class_balance_style_profile.md) | 1 |
| EXP20 | [Semantic-balanced Clean Gate Set](exp20_semantic_balanced_clean_gate_set.md) | 1 |
| EXP21 | [Semantic-balanced Training Set](exp21_semantic_balanced_training_set.md) | 2 |
| EXP22 | [Semantic Class-balanced Sampling](exp22_semantic_class_balanced_sampling.md) | 1 |
| EXP23 | [Per-semantic Specialist Learning Probe](exp23_per_semantic_specialist_learning_probe.md) | 1 |
| EXP24 | [Kingside / Development Specialist Audit](exp24_kingside_development_specialist_audit.md) | 1 |
| EXP25 | [Balanced Gate Semantic Cleanup](exp25_balanced_gate_semantic_cleanup.md) | 2 |
| EXP26 | [Central / Flank Balanced Semantic Improvement](exp26_central_flank_balanced_semantic_improvement.md) | 2 |
| EXP27 | [Flank Pawn Push Specialist Repair](exp27_flank_pawn_push_specialist_repair.md) | 1 |
| EXP28 | [Context-Conditioned Flank Semantic Learning](exp28_context_conditioned_flank_semantic_learning.md) | 1 |
| EXP28.5 | [Distilled Replay Preprocessing](exp28_5_distilled_replay_preprocessing.md) | 1 |
| EXP29 | [Flank Context Feature Injection](exp29_flank_context_feature_injection.md) | 1 |
| EXP30 | [Distilled Replay Hygiene + Semantic Interference Isolation](exp30_distilled_replay_hygiene_semantic_interference_isolation.md) | 2 |
| EXP31 | [Semantic Loss Budget Scheduler](exp31_semantic_loss_budget_scheduler.md) | 1 |
| EXP32 | [Smoke Anchor Calibration and Mistake Retention Repair](exp32_smoke_anchor_calibration_and_mistake_retention_repair.md) | 1 |
| EXP33 | [Failed Smoke Anchor Microdiagnosis + Safe Checkpoint Retention](exp33_failed_smoke_anchor_microdiagnosis_safe_checkpoint_retention.md) | 1 |
| EXP34 | [Mixed Scheduler Repair + Hard Case Decision Audit](exp34_mixed_scheduler_repair_hard_case_decision_audit.md) | 2 |
| Architecture | [exp3 / exp4 / exp5 路線分流](architecture_exp3_exp4_exp5_route_split.md) | 1 |
| Pause | [Exp3 暫停開發結論](exp3_pause_conclusion.md) | 1 |
| Closeout | [Exp3 預設模型替換與 auto-retrain 串接驗證](exp3_closeout_model_autoretrain_verification.md) | 1 |

維護規則：exp3 目前暫停開發；若未來只做 exp3 baseline 回歸，更新本資料夾。exp4 後續文件放 `../exp4/`，exp5 後續文件放 `../exp5/`。
