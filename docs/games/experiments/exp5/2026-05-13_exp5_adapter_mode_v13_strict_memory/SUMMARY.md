# Exp5 Adapter Mode Evaluation

- generated_at: `2026-05-13T13:55:22+00:00`
- main_model_path: `services/games/models/chess_experiment_5_nnue.json`
- adapter_model_path: `docs/games/2026-05-13_exp5_normal_retrain_smoke_v11/repeatability_gate/run_1_seed_31/candidate/chess_experiment_5_nnue.json`
- adapter_rows_path: `docs/games/2026-05-13_exp5_normal_retrain_smoke_v11/normal_train_rows.jsonl`
- adapter_mode: `guarded`

## Result
- advanced score: `74.2151`
- grade: `club_level_candidate`
- gauntlet: `8`W/`20`D/`2`L
- gauntlet score rate: `0.6`
- threefold rate: `0.6667`
- tactical suite: `300`/`300`
- adapter decisions: `1451`, adoptions `6`
- adoption source counts: `{'none': 1435, 'exact_memory': 16}`
- rejection reason counts: `{'no_exact_memory': 1435, 'same_as_main': 5, 'adapter_material_floor_too_low': 5}`

## Artifacts
- Note: raw probe/gauntlet/tactical artifacts for this rejected prototype were
  pruned during `docs/games` cleanup. Summary files and advanced score were
  retained.
- score_probe: `docs/games/2026-05-13_exp5_adapter_mode_v13_strict_memory/adapter_score_probe.json`
- tactical_suite: `docs/games/2026-05-13_exp5_adapter_mode_v13_strict_memory/adapter_tactical_suite_300.json`
- gauntlet: `docs/games/2026-05-13_exp5_adapter_mode_v13_strict_memory/adapter_gauntlet_30.json`
- gauntlet_jsonl: `docs/games/2026-05-13_exp5_adapter_mode_v13_strict_memory/adapter_gauntlet_30.jsonl`
- advanced_score: `docs/games/2026-05-13_exp5_adapter_mode_v13_strict_memory/adapter_advanced_score.json`
- summary_json: `docs/games/2026-05-13_exp5_adapter_mode_v13_strict_memory/summary.json`
