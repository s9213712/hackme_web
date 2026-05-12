# exp5 final promotion（2026-05-12）

## 結論

- exp5_status: `promoted_and_frozen`
- runtime_sha: `d35c04707fd7c10e8b6efe07740e69da533dea524d31aa63308afea891d006c9`
- rollback_ready: `true`
- further_exp5_experiments_disabled: `true`
- retrain_attempted: `false`
- new_candidate_built: `false`

## Promotion

Promoted candidate:

- `/home/s92137/chess_results/exp5_16_opening_overlay_candidate/chess_experiment_5_nnue_opening_overlay_candidate.json`
- candidate sha256: `d35c04707fd7c10e8b6efe07740e69da533dea524d31aa63308afea891d006c9`

Runtime target:

- `/home/s92137/hackme_web/runtime/games/models/chess_experiment_5_nnue.json`
- runtime sha256 after promotion: `d35c04707fd7c10e8b6efe07740e69da533dea524d31aa63308afea891d006c9`

The runtime file did not exist before promotion, so no previous runtime snapshot was copied. Rollback is deleting the runtime file to restore fallback behavior. Absence marker:

- `/home/s92137/chess_results/exp5_final_promotion_backup/previous_runtime_absent.json`

The bundled warm-up seed was also synchronized to the promoted payload:

- `services/games/models/chess_experiment_5_nnue.json`

## Post-Promotion Gate

Focused post-promotion validation:

- output root: `/home/s92137/chess_results/exp5_final_promotion_postverify/`
- summary: `/home/s92137/chess_results/exp5_final_promotion_postverify/summary.json`

Required results:

- clean opening pool: `31/31`
- exp5_13 retention: `115/137` unchanged
- clean_regressed_count: `0`
- illegal_rate: `0.0`
- suspicious_rate: `0.0`
- endgame: `60/66` unchanged
- smoke: `18/18` unchanged
- special_rule: `6/6` unchanged
- tactic: `10/10` unchanged
- runtime priority safety: `5/5`
- model without overlay behavior: `43/43` unchanged when overlay absent
- repeatability: `5/5`

W7/W8 dry-run smoke was not rerun in this final promotion step because the repo worktree already had unrelated dirty WIP. The previous exp5_18 W7 smoke remains recorded at `/home/s92137/chess_results/exp5_18_w7_dryrun_smoke/`.

## Freeze Rule

exp5 stops here. Do not create exp5_19+ unless a real production regression appears. Future exp5 learning should come through normal real-game replay, W8 audit, and operator-approved warm-up/retrain flow, not manual benchmark chasing.
