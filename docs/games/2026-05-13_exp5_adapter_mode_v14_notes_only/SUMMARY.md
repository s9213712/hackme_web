# Exp5 Adapter Mode Evaluation

- generated_at: `2026-05-13T14:05:30+00:00`
- main_model_path: `services/games/models/chess_experiment_5_nnue.json`
- adapter_model_path: `docs/games/2026-05-13_exp5_normal_retrain_smoke_v11/repeatability_gate/run_1_seed_31/candidate/chess_experiment_5_nnue.json`
- adapter_rows_path: `docs/games/2026-05-13_exp5_normal_retrain_smoke_v11/normal_train_rows.jsonl`
- adapter_mode: `guarded`
- adapter_allow_exact_adoption: `False`
- adapter_allow_general_adapter: `False`

## Result
- advanced score: `81.0343`
- grade: `strong_club_candidate`
- gauntlet: `15`W/`12`D/`3`L
- gauntlet score rate: `0.7`
- threefold rate: `0.4`
- tactical suite: `300`/`300`
- adapter decisions: `1492`, adoptions `0`
- adoption source counts: `{'none': 1461, 'exact_memory': 31}`
- rejection reason counts: `{'no_exact_memory': 1461, 'exact_memory_shadow_only': 31}`

## Conclusion

This run validates the conservative adapter architecture, not a strength gain.
The retrained v11 candidate and its replay rows were loaded as an experience
notebook, but `guarded` mode made `0` move overrides. Exact replay hits were
kept as shadow notes until a future gate explicitly enables adoption.

This is the safe default requested by the "寧缺勿濫" rule: experience is not
wasted, but unproven small-model advice cannot damage the main model.

## Artifacts
- score_probe: `docs/games/2026-05-13_exp5_adapter_mode_v14_notes_only/adapter_score_probe.json`
- tactical_suite: `docs/games/2026-05-13_exp5_adapter_mode_v14_notes_only/adapter_tactical_suite_300.json`
- gauntlet: `docs/games/2026-05-13_exp5_adapter_mode_v14_notes_only/adapter_gauntlet_30.json`
- gauntlet_jsonl: `docs/games/2026-05-13_exp5_adapter_mode_v14_notes_only/adapter_gauntlet_30.jsonl`
- advanced_score: `docs/games/2026-05-13_exp5_adapter_mode_v14_notes_only/adapter_advanced_score.json`
- summary_json: `docs/games/2026-05-13_exp5_adapter_mode_v14_notes_only/summary.json`
