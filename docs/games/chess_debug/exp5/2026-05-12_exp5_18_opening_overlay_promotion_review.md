# exp5_18 opening overlay promotion review

## Scope

This round is a promotion review only. It does not copy the candidate into
runtime production, does not stage, and does not mutate runtime model artifacts.

The actual production copy must be a separate step after explicit approval.

## Inputs

Candidate:

- path: `/home/s92137/chess_results/exp5_16_opening_overlay_candidate/chess_experiment_5_nnue_opening_overlay_candidate.json`
- expected sha256: `d35c04707fd7c10e8b6efe07740e69da533dea524d31aa63308afea891d006c9`
- actual sha256: `d35c04707fd7c10e8b6efe07740e69da533dea524d31aa63308afea891d006c9`

Validated by:

- exp5_17 summary: `/home/s92137/chess_results/exp5_17_opening_overlay_staging_validation/summary.json`
- exp5_17 verdict: `ready_for_exp5_18_promotion_review`

Current production-equivalent baseline:

- runtime path: `/home/s92137/hackme_web/runtime/games/models/chess_experiment_5_nnue.json`
- runtime exists at review time: `false`
- fallback path: `/home/s92137/chess_results/exp5_08_stage_candidate/chess_experiment_5_nnue_stage_candidate.json`
- fallback sha256: `c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc`

The local runtime override file is absent, so current behavior is still the
promoted fallback artifact with sha `c47ef752...`.

## Review Artifact

Generated review artifact:

- summary JSON: `/home/s92137/chess_results/exp5_18_opening_overlay_promotion_review/summary.json`
- summary md: `/home/s92137/chess_results/exp5_18_opening_overlay_promotion_review/SUMMARY.md`

## Gate Confirmation

All required exp5_17 gates are still satisfied.

| gate | result |
|---|---:|
| clean opening pool | 31/31 = 1.000000 |
| current clean opening baseline | 1/31 = 0.032258 |
| opening delta | +0.967742 |
| opening regressions | 0 |
| retention | 115/137 = 0.839416 |
| retention delta | 0.0 |
| clean_regressed_count | 0 |
| illegal_rate | 0.0 |
| suspicious_rate | 0.0 |
| endgame | 60/66 unchanged |
| smoke | 18/18 unchanged |
| special_rule | 6/6 unchanged |
| tactic | 10/10 unchanged |
| overlay activation | 31/31 exact hit |
| fresh non-overlay opening fallback | 12/12 unchanged |
| model without overlay | 43/43 unchanged |
| runtime priority safety | 5/5 |
| repeatability | 5/5 |

## W6/W7 Dry-Run Smoke

Because the main worktree has unrelated WIP, the W7 dry-run smoke was run from
a clean detached worktree:

- clean worktree: `/tmp/hackme_exp5_18_review_clean`
- output root: `/home/s92137/chess_results/exp5_18_w7_dryrun_smoke/pipeline_run_20260512T130122_069288Z`
- exp5 model path: `/home/s92137/chess_results/exp5_16_opening_overlay_candidate/chess_experiment_5_nnue_opening_overlay_candidate.json`
- aggregate summary: `/home/s92137/chess_results/exp5_18_w7_dryrun_smoke/pipeline_run_20260512T130122_069288Z/06_aggregate/pipeline_summary.json`
- aggregate md: `/home/s92137/chess_results/exp5_18_w7_dryrun_smoke/pipeline_run_20260512T130122_069288Z/06_aggregate/PIPELINE_SUMMARY.md`

Stage result:

| stage | status |
|---|---|
| pgn_to_replay | skipped, no input |
| pvp_export | skipped, no runtime dir |
| sparring | ok |
| sparring_to_replay | ok |
| seed_train_dry_run | ok |
| aggregate | ok |

Aggregate invariants:

- `all_stages_diagnostic_only=true`
- `any_production_runtime_mutation=false`
- `any_model_mutation=false`

Seed-train dry-run accepted the generated replay rows for both exp4 and exp5:

- rows kept: `2`
- exp4_ok: `2`
- exp4_failed: `0`
- exp5_ok: `2`
- exp5_failed: `0`
- trained_exp4: `false`
- trained_exp5: `false`

The clean worktree was removed after the smoke run.

## Promotion Recommendation

Recommendation:

- `approve_separate_promotion_step_after_explicit_user_approval`

Rationale:

- candidate identity matches exp5_16 / exp5_17
- current production-equivalent baseline identity is unchanged
- exp5_17 staging validation passes every required gate
- W7 dry-run smoke completed without model or DB mutation
- no runtime production copy was attempted in this review

This review approves moving to a separate promotion step. It is not itself a
production promotion.

## Rollback Plan

Promotion should first inspect the runtime path at promotion time:

- runtime path: `/home/s92137/hackme_web/runtime/games/models/chess_experiment_5_nnue.json`

If the runtime file is still absent:

1. Copy the candidate into the runtime path.
2. Record that `previous_runtime_exists=false`.
3. Rollback by deleting `/home/s92137/hackme_web/runtime/games/models/chess_experiment_5_nnue.json`, restoring fallback behavior to sha `c47ef752...`.

If the runtime file exists at promotion time:

1. Copy the current runtime file to `/home/s92137/chess_results/exp5_18_promotion_backup/`.
2. Record backup path and backup sha.
3. Copy the candidate into the runtime path.
4. Rollback by restoring the backup file to the runtime path.

Post-promotion must verify:

- runtime file exists
- runtime sha is `d35c04707fd7c10e8b6efe07740e69da533dea524d31aa63308afea891d006c9`
- opening overlay still scores 31/31
- exp5_13 retention remains 115/137 with 0 clean regression
- runtime priority safety remains 5/5

## Final State

- `production_mutation_attempted=false`
- `runtime_mutated=false`
- `promotion_performed=false`
- `promotion_review_passed=true`
- `ready_for_separate_promotion_step=true`

Do not treat this document as a production copy record. The production copy
must be a separate command/commit after approval.
