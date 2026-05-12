# exp5_17 opening overlay staging validation

## Scope

exp5_17 validates the exp5_16 opening overlay candidate as a staging/readiness
candidate. It does not train, stage, promote, or mutate runtime production.

Candidate:

- path: `/home/s92137/chess_results/exp5_16_opening_overlay_candidate/chess_experiment_5_nnue_opening_overlay_candidate.json`
- sha256: `d35c04707fd7c10e8b6efe07740e69da533dea524d31aa63308afea891d006c9`

Baseline:

- current production sha expected: `c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc`
- current production sha actual: `c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc`
- current model source: `promoted_stage_candidate_fallback`

## Tool

Added:

- `scripts/games/chess_exp5_opening_overlay_staging_validation.py`

The validator checks:

- exp5_14b clean opening pool
- exp5_13 retention/rule-smoke screen
- exact overlay activation
- fresh non-overlay opening fallback
- model-without-overlay identity behavior
- adversarial runtime-priority safety
- 5-seed case-order repeatability

## Results

Output directory:

- `/home/s92137/chess_results/exp5_17_opening_overlay_staging_validation/`

Artifacts:

- summary: `/home/s92137/chess_results/exp5_17_opening_overlay_staging_validation/summary.json`
- summary md: `/home/s92137/chess_results/exp5_17_opening_overlay_staging_validation/SUMMARY.md`
- opening evaluation: `/home/s92137/chess_results/exp5_17_opening_overlay_staging_validation/opening_evaluation.json`
- retention evaluation: `/home/s92137/chess_results/exp5_17_opening_overlay_staging_validation/retention_evaluation.json`
- overlay activation audit: `/home/s92137/chess_results/exp5_17_opening_overlay_staging_validation/overlay_activation_audit.json`
- fresh non-overlay opening audit: `/home/s92137/chess_results/exp5_17_opening_overlay_staging_validation/fresh_non_overlay_opening_audit.json`
- runtime priority safety audit: `/home/s92137/chess_results/exp5_17_opening_overlay_staging_validation/runtime_priority_safety_audit.json`
- repeatability: `/home/s92137/chess_results/exp5_17_opening_overlay_staging_validation/repeatability_5_seed.json`

## Opening Pool

| model | clean opening score |
|---|---:|
| current production-equivalent | 1/31 = 0.032258 |
| exp5_16 overlay candidate | 31/31 = 1.000000 |
| delta | +0.967742 |

Details:

- improved cases: `30`
- regressed cases: `0`

## Retention

Against exp5_13 retention rows:

| cluster | current | candidate | delta | clean regressions |
|---|---:|---:|---:|---:|
| overall | 115/137 = 0.839416 | 115/137 = 0.839416 | 0.0 | 0 |
| endgame | 60/66 = 0.909091 | 60/66 = 0.909091 | 0.0 | 0 |
| smoke | 18/18 = 1.000000 | 18/18 = 1.000000 | 0.0 | 0 |
| special_rule | 6/6 = 1.000000 | 6/6 = 1.000000 | 0.0 | 0 |
| tactic | 10/10 = 1.000000 | 10/10 = 1.000000 | 0.0 | 0 |
| quiet_positional | 7/8 = 0.875000 | 7/8 = 0.875000 | 0.0 | 0 |
| legacy opening | 12/27 = 0.444444 | 12/27 = 0.444444 | 0.0 | 0 |

Safety:

- `illegal_rate=0.0`
- `suspicious_rate=0.0`
- `clean_regressed_count=0`

## Overlay Activation Audit

The 31 exp5_14b clean opening rows all have exact overlay positions.

| metric | value |
|---|---:|
| cases | 31 |
| overlay position present | 31 |
| candidate in expected | 31 |
| candidate matches preferred overlay move | 31 |
| candidate regressions | 0 |
| pass | true |

## Fresh Non-Overlay Opening Audit

This audit uses 12 fresh opening probes that are not in the overlay table.

| metric | value |
|---|---:|
| fresh probes | 12 |
| overlay overlap count | 0 |
| fallback unchanged count | 12 |
| pass | true |

This confirms the overlay is exact-position gated and does not change broader
opening positions that are not explicitly curated.

## Runtime Priority Safety

The validator builds an adversarial overlay model that tries to override hard
rule/tactic positions. The runtime must ignore those bad overlay rows for hard
priorities, while still allowing exact opening overlay to override only the
broad early-castling heuristic.

| metric | value |
|---|---:|
| cases | 5 |
| hard priority cases | 4 |
| bad overlay blocked | 5 |
| expectation satisfied | 5 |
| pass | true |

Covered:

- forced mate
- promotion
- en-passant
- high-value capture
- exact opening overlay may override broad early-castling heuristic

## Model Without Overlay

Explicitly removing `opening_overlay` from the model keeps behavior identical:

- cases checked: `43`
- unchanged: `43`
- pass: `true`

## Repeatability

5-seed case-order repeatability:

- seeds: `[11, 12, 13, 14, 15]`
- pass_count: `5/5`
- retention_score_delta: `0.0` for every seed
- endgame_delta: `0.0` for every seed
- smoke_delta: `0.0` for every seed
- special_rule_delta: `0.0` for every seed
- tactic_delta: `0.0` for every seed
- illegal_rate: `0.0` for every seed
- suspicious_rate: `0.0` for every seed

## W6 Dry-Run Note

The exp5_17 validator did not run the W6 dry-run pipeline smoke. The local
`scripts/games/chess_pipeline_dryrun.py` currently has unrelated uncommitted WIP
outside this exp5 change, so this round keeps the validation artifact-only and
does not mix W6 WIP state into the exp5 staging verdict.

## Decision

- `ready_for_exp5_18_promotion_review=true`
- `verdict=ready_for_exp5_18_promotion_review`
- `block_reasons=[]`
- `runtime_mutated=false`
- `stage_promote_attempted=false`

exp5_17 passes staging/readiness validation. The candidate is ready for exp5_18
promotion review, but exp5_17 itself does not promote production.

## Tests

- `python3 -m py_compile scripts/games/chess_exp5_opening_overlay_staging_validation.py tests/scripts/games/test_chess_exp5_opening_overlay_staging_validation_script.py`
- `python3 -m pytest tests/scripts/games/test_chess_exp5_opening_overlay_staging_validation_script.py`
- real exp5_17 staging validation run

## Next

Recommended next step:

- exp5_18 promotion review, with an explicit final decision on whether to
  copy the overlay candidate into runtime production.
