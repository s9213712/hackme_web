# Exp5 Adapter Mode Evaluation

- generated_at: `2026-05-13T13:44:26+00:00`
- main_model_path: `services/games/models/chess_experiment_5_nnue.json`
- adapter_model_path: `docs/games/2026-05-13_exp5_normal_retrain_smoke_v11/repeatability_gate/run_1_seed_31/candidate/chess_experiment_5_nnue.json`
- adapter_rows_path: `docs/games/2026-05-13_exp5_normal_retrain_smoke_v11/normal_train_rows.jsonl`
- adapter_mode: `guarded`

## Result
- advanced score: `72.4156`
- grade: `club_level_candidate`
- gauntlet: `11`W/`18`D/`1`L
- gauntlet score rate: `0.6667`
- threefold rate: `0.6`
- tactical suite: `300`/`300`
- adapter decisions: `1406`, adoptions `36`
- adoption source counts: `{'adapter_model': 1391, 'exact_memory': 15}`
- rejection reason counts: `{'insufficient_main_model_support': 61, 'same_as_main': 1303, 'adapter_material_floor_too_low': 6}`

## Artifacts
- Note: raw probe/gauntlet/tactical artifacts for this rejected prototype were
  pruned during `docs/games` cleanup. Summary files and advanced score were
  retained.
- score_probe: `docs/games/2026-05-13_exp5_adapter_mode_v12/adapter_score_probe.json`
- tactical_suite: `docs/games/2026-05-13_exp5_adapter_mode_v12/adapter_tactical_suite_300.json`
- gauntlet: `docs/games/2026-05-13_exp5_adapter_mode_v12/adapter_gauntlet_30.json`
- gauntlet_jsonl: `docs/games/2026-05-13_exp5_adapter_mode_v12/adapter_gauntlet_30.jsonl`
- advanced_score: `docs/games/2026-05-13_exp5_adapter_mode_v12/adapter_advanced_score.json`
- summary_json: `docs/games/2026-05-13_exp5_adapter_mode_v12/summary.json`
