# exp5_10 production-readiness validation

Date: 2026-05-12

## Why this round was needed

`exp5_09` unlocked the first exp5 shadow candidate, but production was held by policy until:

- expanded held-out >= 120 cases with >= 60 true held-out cases
- comprehensive smoke >= 16 cases
- 5-7 seed repeatability
- no quiet/opening/special-rule production regressions

This round validates the same `exp5_08` Cell B candidate. It does not retrain, does not swap candidate, and does not mutate the runtime production model.

## Models

- baseline: `/home/s92137/hackme_web/services/games/models/chess_experiment_5_nnue.json`
- baseline sha256: `6fbafae703b94c173e10079aae09763a547719b410895332cbbfdf990ca487ec`
- candidate: `/home/s92137/chess_results/exp5_08_stage_candidate/chess_experiment_5_nnue_stage_candidate.json`
- candidate sha256: `c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc`
- search profile: `fixed_depth_strong`

## Runner fix before official result

The first exp5_10 run was treated as provisional because `train_vs_benchmark_overlap_count` and `position_id_overlap_count` were hardcoded to `0`.

The runner now computes overlap with:

- `_train_row_signature(...)`
- exp5 position_id v2: board_fen, turn, castling_xfen, ep_square, side

The official run records:

- `provisional_run=false`
- `overlap_counts_hardcoded=false`
- `do_not_use_for_production_readiness=false`
- `supersedes_previous_provisional_hardcoded_overlap_run=true`

## Retest fix before final data

The first official exp5_10 run exposed two invalid rook mate smoke fixtures:

- `exp5_10_smoke_mate_in_1_rook_white`
- `exp5_10_smoke_mate_in_1_rook_black`

Both old FENs started from invalid positions where the opposite side was already in check, which polluted `suspicious_rate` with stalemate-after-move artifacts. The fixtures were replaced with valid K+R mate-in-1 positions:

- white: `7k/8/6K1/8/8/8/8/R7 w - - 0 1`, expected mate move `a1a8`
- black: `r7/8/8/8/8/6k1/8/7K b - - 0 1`, expected mate move `a8a1`

Both positions validate as legal initial boards and the expected move produces checkmate, not stalemate. exp5_10 was then rerun from scratch.

## Expanded held-out

- cases: `135`
- true held-out cases: `70`
- train rows position ids: `116`
- benchmark position ids: `135`
- skipped train overlap before final set: `4`
- skipped duplicate cases: `21`
- train_vs_benchmark_overlap_count: `0`
- train_vs_heldout_overlap_count: `0`
- position_id_overlap_count: `0`
- benchmark_duplicate_position_id_count: `0`
- pass: `true`

Cluster distribution:

| cluster | cases |
|---|---:|
| endgame | 66 |
| opening | 27 |
| smoke | 18 |
| tactic | 10 |
| quiet_positional | 8 |
| special_rule | 4 |
| blunder_avoid | 2 |

Label distribution:

| label | cases |
|---|---:|
| clean | 85 |
| questionable | 48 |
| review | 1 |
| unspecified | 1 |

## Expanded benchmark

| metric | baseline | candidate | delta |
|---|---:|---:|---:|
| overall | 103/135 = 0.762963 | 104/135 = 0.770370 | +0.007407 |
| endgame | 54/66 = 0.818182 | 59/66 = 0.893939 | +0.075758 |
| tactic | 10/10 = 1.0 | 10/10 = 1.0 | 0.0 |
| special_rule | 4/4 = 1.0 | 4/4 = 1.0 | 0.0 |
| blunder_avoid | 2/2 = 1.0 | 2/2 = 1.0 | 0.0 |
| smoke | 8/18 = 0.444444 | 8/18 = 0.444444 | 0.0 |
| quiet_positional | 7/8 = 0.875 | 6/8 = 0.75 | -0.125 |
| opening | 18/27 = 0.666667 | 15/27 = 0.555556 | -0.111111 |

Safety:

- legal_rate: `1.0`
- illegal_rate: `0.0`
- suspicious_rate: `0.0`
- suspicious matches: `[]`

## Regression audit

Candidate regressions:

| cluster | case | label | baseline | candidate | reason |
|---|---|---|---|---|---|
| quiet_positional | `exp5_09_bench_d400404a65f3` | clean | `f3f4` | `h2h4` | unexpected_move |
| endgame | `exp5_10_teacher_012` | clean | `e5d6` | `c6a6` | unexpected_move |
| opening | `exp5_09_bench_657bfa8d74cc` | questionable | `d1a4` | `a2a4` | unexpected_move |
| opening | `exp5_10_teacher_016_mirror` | questionable | `a2a3` | `a2a4` | unexpected_move |
| opening | `exp5_10_teacher_017_mirror` | questionable | `a2a3` | `a2a4` | unexpected_move |

The quiet positional regression is clean and blocks production. Opening regressions remain questionable labels, so they are diagnostic but not the primary blocker.

## Smoke

- smoke cases: `18`
- baseline smoke score: `0.444444`
- candidate smoke score: `0.444444`
- smoke delta: `0.0`
- candidate regressions: `0`
- shared limitations remain in promotion, underpromotion, castling, en-passant, hanging-rook, and blunder-avoid probes.
- smoke pass under current policy: `true` because there is no candidate-only smoke regression.

## Repeatability

This is deterministic case-order repeatability, not repeated model training.

- repeatability_type: `case_order_repeatability`
- model_training_repeated: `false`
- search_profile: `fixed_depth_strong`
- seeds: `11, 12, 13, 14, 15`
- score_delta_per_seed: `[0.007407, 0.007407, 0.007407, 0.007407, 0.007407]`
- mean_delta: `0.007407`
- std_delta: `0.0`
- min_delta: `0.007407`
- max_delta: `0.007407`
- stage_pass_count: `5/5`
- shadow_pass_count: `5/5`
- production_pass_count: `5/5`
- pass: `true`

The deterministic delta is stable under case-order repeatability. This is not repeated training; it only proves the fixed model pair and fixed case set are order-independent.

## Runtime model check

- bundled baseline unchanged: `true`
- production runtime path: `/home/s92137/hackme_web/runtime/games/models/chess_experiment_5_nnue.json`
- production_runtime_exists_before: `false`
- production_runtime_exists_after: `false`
- production_runtime_model_checked: `false`
- production_runtime_unchanged: `true`
- production_runtime_unchanged_reason: `true_by_no_write_only`

Because the runtime file did not exist in this checkout, this round proves the runner did not write one; it does not prove a live deployed runtime model hash stayed equal.

## Production policy

- expanded_heldout_pass: `true`
- comprehensive_smoke_pass: `true`
- repeatability_pass: `true`
- shadow_candidate: `true`
- production_promote_request_ready: `false`
- production_promote: `false`
- runtime_model_mutated: `false`

Blocking reasons:

- `quiet_positional_clean_regression`

## Artefacts

- cases: `/home/s92137/chess_results/exp5_10_production_readiness/exp5_10_benchmark_cases.jsonl`
- expanded benchmark: `/home/s92137/chess_results/exp5_10_production_readiness/focused_benchmark_expanded.json`
- strength gate: `/home/s92137/chess_results/exp5_10_production_readiness/strength_gate_expanded.json`
- repeatability: `/home/s92137/chess_results/exp5_10_production_readiness/repeatability_5_seed.json`
- summary: `/home/s92137/chess_results/exp5_10_production_readiness/summary.json`
- markdown summary: `/home/s92137/chess_results/exp5_10_production_readiness/SUMMARY.md`

## Tests

- `python3 -m py_compile scripts/games/chess_exp5_production_readiness.py`
- `python3 -m py_compile scripts/games/chess_exp5_suspicious_audit.py`
- valid K+R rook mate fixture check with python-chess
- `python3 scripts/games/chess_exp5_production_readiness.py --help`
- retested official exp5_10 run completed and wrote all artefacts above
- `python3 scripts/games/chess_exp5_suspicious_audit.py`

## Verdict

`exp5_10` keeps `shadow_candidate=true` but does not make the candidate production-ready.

The invalid rook mate smoke fixtures were fixed and `suspicious_rate` is now `0.0`; repeatability is now 5/5. The endgame improvement survives the expanded set, but the overall score delta remains thin at `+0.007407` and the clean quiet positional regression repeats. Runtime production model remains unmodified, so production remains held by `quiet_positional_clean_regression`.
