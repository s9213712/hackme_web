# exp5_13 rule smoke and stalemate fix

## Scope

This round continued exp5 after production promotion. It did not retrain, replace the promoted runtime model, change exp4, or use sparring evidence.

The goal was to fix real production behavior gaps exposed by post-promote validation:

- shared smoke limitations in promotion / en-passant / capture / castling fixtures
- invalid or too-narrow smoke fixtures
- a newly exposed stalemate selection risk in shallow endgame search

## Code changes

- `services/games/chess_nnue.py`
  - added conservative special-rule priority before NNUE/PVS search:
    - forced mate remains first
    - promotion is preferred when legal and non-stalemating
    - legal en-passant is selected when available and non-stalemating
    - high-value captures are selected when non-stalemating
    - early castling is selected when no higher-priority tactical rule fires
  - added stalemate avoidance after search:
    - if the selected move stalemates and any non-stalemate legal alternative exists, choose the best non-stalemate alternative
  - forced mate tie-break now prefers promotion mates, so valid underpromotion-mate fixtures are not hidden by another mate-in-1

- `scripts/games/chess_exp5_production_readiness.py`
  - replaced invalid / overly broad smoke fixtures:
    - underpromotion fixtures now use valid knight-promotion mate positions
    - castling fixtures no longer include free enemy-rook captures
    - blunder-avoid fixtures are valid boards and accept both king/queen capture equivalents

- `tests/games/test_chess_exp5_architecture.py`
  - added exp5 special-rule priority coverage for queen promotion, en-passant, rook capture, castling, and underpromotion mate

## Validation

Output directory:

- `<chess_results>/exp5_13_rule_smoke_stalemate_fix_check/`

Key artifacts:

- summary: `<chess_results>/exp5_13_rule_smoke_stalemate_fix_check/summary.json`
- benchmark: `<chess_results>/exp5_13_rule_smoke_stalemate_fix_check/focused_benchmark_expanded.json`
- strength gate: `<chess_results>/exp5_13_rule_smoke_stalemate_fix_check/strength_gate_expanded.json`
- repeatability: `<chess_results>/exp5_13_rule_smoke_stalemate_fix_check/repeatability_5_seed.json`

## Expanded benchmark

| metric | baseline | runtime candidate |
|---|---:|---:|
| passed / cases | 112 / 137 | 115 / 137 |
| score | 0.817518 | 0.839416 |
| score_delta | n/a | +0.021898 |
| clean_regressed_count | n/a | 0 |
| illegal_rate | n/a | 0.0 |
| suspicious_rate | n/a | 0.0 |

## Cluster result

| cluster | baseline | runtime candidate | delta | clean regressions |
|---|---:|---:|---:|---:|
| endgame | 54/66 = 0.818182 | 60/66 = 0.909091 | +0.090909 | 0 |
| smoke | 18/18 = 1.0 | 18/18 = 1.0 | 0.0 | 0 |
| special_rule | 6/6 = 1.0 | 6/6 = 1.0 | 0.0 | 0 |
| tactic | 10/10 = 1.0 | 10/10 = 1.0 | 0.0 | 0 |
| blunder_avoid | 2/2 = 1.0 | 2/2 = 1.0 | 0.0 | 0 |
| quiet_positional | 7/8 = 0.875 | 7/8 = 0.875 | 0.0 | 0 |
| opening | 15/27 = 0.555556 | 12/27 = 0.444444 | -0.111111 | 0 |

Opening remains negative, but all opening rows in this benchmark are `questionable`; it remains a label-quality task, not a production blocker.

## Repeatability

- repeatability type: `case_order_repeatability`
- model_training_repeated: `false`
- score_delta_per_seed: `[0.021898, 0.021898, 0.021898, 0.021898, 0.021898]`
- mean_delta: `0.021898`
- std_delta: `0.0`
- stage_pass_count: `5/5`
- shadow_pass_count: `5/5`
- production_pass_count: `5/5`
- pass: `true`

## Strength gate

- strength gate ok: `true`
- strength gate pass: `true`
- candidate_can_be_staged: `true`
- candidate_can_be_shadowed: `true`
- candidate_can_be_production_promoted: `true`
- stage_reasons: `[]`
- shadow_reasons: `[]`
- production_reasons: `[]`

## Final state

- runtime model sha remains: `c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc`
- production runtime model was not replaced in this round
- production behavior is improved by engine code and fixture/gate correctness
- smoke score improved from `8/18` to `18/18`
- suspicious rate returned to `0.0`
- production_promote remains already completed from exp5_12

## Tests

- `python3 -m py_compile services/games/chess_nnue.py scripts/games/chess_exp5_production_readiness.py tests/games/test_chess_exp5_architecture.py`
- `python3 -m pytest tests/games/test_chess_exp5_architecture.py tests/scripts/games/test_chess_exp5_strength_gate_script.py`
- exp5_13 production-readiness rerun on 137 cases
- post-fix strength gate pass
- 5-seed case-order repeatability pass

## Next

The remaining weak area is opening label quality:

- all current opening regressions are `questionable`
- current depth-3 static teacher is too weak for production-grade opening labels
- next improvement should add curated opening-book / stronger-teacher labels before using opening rows as promotion evidence
