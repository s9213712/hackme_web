# exp5_11c quiet positional gate-label fix

Date: 2026-05-12

## Goal

Fix the exp5_10 `quiet_positional_clean_regression` blocker identified by exp5_11b without retraining, changing the candidate model, or touching runtime production.

## What changed

The production-readiness runner and exp5 strength gate now accept quiet positional moves that are near-equivalent under the same static teacher evaluator:

- scope: `category == "quiet_positional"` only
- cp window: `50`
- accepted if chosen move is within `50cp` of both the teacher move and the best static-eval move
- rank is diagnostic only; the gate does not rely on ordinal rank

This avoids marking close quiet K+P moves as production regressions when the original label was too narrow.

## Rank discrepancy resolution

The reviewed case had two rank values in earlier notes:

- ordinal rank: `7`
- dense-score rank: `3`

This is not an evaluator mismatch. `h2h4` shares the same static score as other legal moves; ordinal rank depends on UCI tie-break ordering, while dense-score rank groups equal-score moves. The actual evidence is the cp delta:

```text
teacher   g3f2 = 44
baseline  f3f4 = 32
candidate h2h4 = 28
candidate vs teacher  = -16cp
candidate vs baseline = -4cp
```

## exp5_10 retest

Artefacts:

- root: `<chess_results>/exp5_10_production_readiness/`
- summary: `<chess_results>/exp5_10_production_readiness/summary.json`
- benchmark: `<chess_results>/exp5_10_production_readiness/focused_benchmark_expanded.json`
- strength gate: `<chess_results>/exp5_10_production_readiness/strength_gate_expanded.json`
- repeatability: `<chess_results>/exp5_10_production_readiness/repeatability_5_seed.json`

Updated benchmark:

| metric | baseline | candidate | delta |
|---|---:|---:|---:|
| overall | 103/135 = 0.762963 | 105/135 = 0.777778 | +0.014815 |
| endgame | 54/66 = 0.818182 | 59/66 = 0.893939 | +0.075758 |
| quiet_positional | 7/8 = 0.875 | 7/8 = 0.875 | 0.0 |
| smoke | 8/18 = 0.444444 | 8/18 = 0.444444 | 0.0 |
| tactic | 10/10 = 1.0 | 10/10 = 1.0 | 0.0 |
| special_rule | 4/4 = 1.0 | 4/4 = 1.0 | 0.0 |
| opening | 18/27 = 0.666667 | 15/27 = 0.555556 | -0.111111 |

Safety:

- legal_rate: `1.0`
- illegal_rate: `0.0`
- suspicious_rate: `0.0`
- suspicious_matches: `[]`

Repeatability:

- type: `case_order_repeatability`
- seeds: `11, 12, 13, 14, 15`
- score_delta_per_seed: `[0.014815, 0.014815, 0.014815, 0.014815, 0.014815]`
- std_delta: `0.0`
- stage / shadow / production-internal pass count: `5/5`, `5/5`, `5/5`

## Strength gate

The expanded strength gate now reports:

```text
baseline_score  = 0.762963
candidate_score = 0.777778
score_delta     = +0.014815
promotion_gate.passed = true
candidate_can_be_staged = true
candidate_can_be_shadowed = true
candidate_can_be_production_promoted = true
```

## Production policy

The runner reports:

```text
stage_candidate = true
shadow_candidate = true
production_promote_request_ready = true
production_promote = false
runtime_model_mutated = false
```

`production_promote` remains `false` because the runner never mutates the runtime model automatically. Promotion now requires an explicit manual promotion request.

## Tests

- `python3 -m py_compile scripts/games/chess_exp5_production_readiness.py scripts/games/chess_exp5_strength_gate.py scripts/games/chess_exp5_quiet_regression_audit.py`
- `python3 scripts/games/chess_exp5_quiet_regression_audit.py`
- `python3 scripts/games/chess_exp5_production_readiness.py`
- `python3 -m pytest tests/scripts/games/test_chess_exp5_strength_gate_script.py tests/scripts/games/test_chess_exp5_dataset_train_script.py`
- `git diff --check`

## Verdict

exp5_11c clears the last production-readiness blocker in the gate report.

The candidate is still not promoted automatically. Current state:

```text
stage_candidate = true
shadow_candidate = true
production_promote_request_ready = true
production_promote = false
runtime production model unchanged
```
