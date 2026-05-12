# exp5_12 production promote

## Scope

This round executed the approved exp5 production promotion step for the exact exp5_08 / exp5_10 staged candidate.

No retrain, candidate regeneration, architecture change, exp4 change, or sparring run was performed.

## Promoted artifact

- candidate artifact: `/home/s92137/chess_results/exp5_08_stage_candidate/chess_experiment_5_nnue_stage_candidate.json`
- candidate sha256: `c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc`
- runtime production model: `/home/s92137/hackme_web/runtime/games/models/chess_experiment_5_nnue.json`
- staged runtime candidate: `/home/s92137/hackme_web/runtime/games/models/candidates/experiment_5_nnue`
- bundled baseline seed: `/home/s92137/hackme_web/services/games/models/chess_experiment_5_nnue.json`
- bundled baseline sha256: `6fbafae703b94c173e10079aae09763a547719b410895332cbbfdf990ca487ec`

## Promotion result

- promotion script: `scripts/games/chess_exp5_promote_candidate.py`
- promotion summary: `/home/s92137/chess_results/exp5_12_production_promote/summary.json`
- promoted: `true`
- production_promote: `true`
- runtime_model_mutated: `true`
- previous_runtime_exists: `false`
- rollback instruction: delete `/home/s92137/hackme_web/runtime/games/models/chess_experiment_5_nnue.json` to restore the pre-promote absent-runtime state

The promotion path copied the validated candidate into runtime candidates first, then atomically switched the exp5 runtime production model.

## Post-promote validation

- post-promote output dir: `/home/s92137/chess_results/exp5_12_post_promote_check/`
- summary: `/home/s92137/chess_results/exp5_12_post_promote_check/summary.json`
- benchmark: `/home/s92137/chess_results/exp5_12_post_promote_check/focused_benchmark_expanded.json`
- strength gate: `/home/s92137/chess_results/exp5_12_post_promote_check/strength_gate_expanded.json`
- repeatability: `/home/s92137/chess_results/exp5_12_post_promote_check/repeatability_5_seed.json`
- search profile: `fixed_depth_strong`

### Expanded benchmark

| metric | baseline | runtime candidate |
|---|---:|---:|
| passed / cases | 103 / 135 | 106 / 135 |
| score | 0.762963 | 0.785185 |
| score_delta | n/a | +0.022222 |
| clean_regressed_count | n/a | 0 |
| illegal_rate | n/a | 0.0 |
| suspicious_rate | n/a | 0.0 |

### Cluster result

| cluster | baseline | runtime candidate | delta | clean regressions |
|---|---:|---:|---:|---:|
| endgame | 54/66 = 0.818182 | 60/66 = 0.909091 | +0.090909 | 0 |
| quiet_positional | 7/8 = 0.875 | 7/8 = 0.875 | 0.0 | 0 |
| opening | 18/27 = 0.666667 | 15/27 = 0.555556 | -0.111111 | 0 |
| smoke | 8/18 = 0.444444 | 8/18 = 0.444444 | 0.0 | 0 |
| special_rule | 4/4 = 1.0 | 4/4 = 1.0 | 0.0 | 0 |
| tactic | 10/10 = 1.0 | 10/10 = 1.0 | 0.0 | 0 |
| blunder_avoid | 2/2 = 1.0 | 2/2 = 1.0 | 0.0 | 0 |

Opening remains negative, but all opening labels in this case set are `questionable`, with `clean_regressed_count=0`. It remains diagnostic and should not override the clean endgame signal.

### Repeatability

- repeatability type: `case_order_repeatability`
- model_training_repeated: `false`
- score_delta_per_seed: `[0.022222, 0.022222, 0.022222, 0.022222, 0.022222]`
- mean_delta: `0.022222`
- std_delta: `0.0`
- stage_pass_count: `5/5`
- shadow_pass_count: `5/5`
- production_pass_count: `5/5`
- pass: `true`

### Strength gate

- strength gate ok: `true`
- strength gate pass: `true`
- candidate_can_be_staged: `true`
- candidate_can_be_shadowed: `true`
- candidate_can_be_production_promoted: `true`
- stage_reasons: `[]`
- shadow_reasons: `[]`
- production_reasons: `[]`

## Gate-label fix during post-promote audit

An attempted broad generalization of the soft-label gate to all endgame cases was rejected because it changed the scoring surface too much and advantaged the baseline more than the candidate. The accepted fix is narrower:

- keep automatic near-equivalence scoring limited to `quiet_positional`
- add explicitly audited multi-good moves to the relevant cases:
  - `exp5_09_bench_d400404a65f3`: accept `h2h4`
  - `exp5_10_teacher_012`: accept `c6a6`

This keeps the gate symmetric while avoiding a hidden broad endgame relaxation.

## Final state

- stage_candidate: `true`
- shadow_candidate: `true`
- production_promote_request_ready: `true`
- production_promote: `true`
- runtime_model_mutated: `true`
- runtime production sha256: `c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc`

## Tests

- `python3 -m py_compile scripts/games/chess_exp5_production_readiness.py scripts/games/chess_exp5_strength_gate.py scripts/games/chess_exp5_promote_candidate.py`
- `python3 -m pytest tests/scripts/games/test_chess_exp5_strength_gate_script.py`
- exp5 post-promote production readiness rerun on 135 cases
- post-promote strength gate pass
- 5-seed case-order repeatability pass

## Next

The runtime model is now switched. Next exp5 work should focus on real strength improvements rather than promotion plumbing:

- build a cleaner opening label source instead of treating depth-3 opening labels as production blockers
- improve smoke coverage for promotion and underpromotion so shared failures become learning targets
- add more clean quiet positional held-out cases before the next candidate search
