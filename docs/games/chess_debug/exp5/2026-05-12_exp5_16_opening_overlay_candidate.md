# exp5_16 opening overlay candidate

## Scope

exp5_16 follows exp5_15's blocked sparse-NNUE retrain attempt. This round does
not retrain. It builds an isolated exact-position opening overlay / book-prior
candidate on top of the current exp5 production model.

It does not stage, promote, or mutate runtime production.

Production baseline:

- expected sha256: `c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc`
- actual sha256: `c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc`
- model source: `promoted_stage_candidate_fallback`

## Why

exp5_15 proved that replay-style sparse NNUE training was too blunt for opening
repair:

- clean opening pool stayed at `1/31`
- endgame retention regressed
- no candidate was stageable

The safer design is an opening-only overlay that activates only on exact curated
clean opening positions. This preserves the production NNUE endgame behavior.

## Runtime Support

`services/games/chess_nnue.py` now supports an optional model field:

- `opening_overlay`

Existing production models without this field behave as before.

The overlay:

- uses exact `position_id` matches
- requires legal book moves
- is limited by `max_fullmove`
- can override the broad early-castling heuristic only for exact curated
  opening positions
- does not override forced mate, promotion, en-passant, or high-value capture
  priority paths

## Tool

Added:

- `scripts/games/chess_exp5_opening_overlay_candidate.py`

The tool:

- reads exp5_14b clean opening curriculum
- copies the current production-equivalent model into an isolated candidate
- injects exact-position opening overlay data
- evaluates clean opening improvement
- evaluates exp5_13 retention/rule smoke regression
- runs 5-seed case-order repeatability
- writes artifacts under `~/chess_results`

## Results

Output directory:

- `/home/s92137/chess_results/exp5_16_opening_overlay_candidate/`

Artifacts:

- summary: `/home/s92137/chess_results/exp5_16_opening_overlay_candidate/summary.json`
- summary md: `/home/s92137/chess_results/exp5_16_opening_overlay_candidate/SUMMARY.md`
- candidate model: `/home/s92137/chess_results/exp5_16_opening_overlay_candidate/chess_experiment_5_nnue_opening_overlay_candidate.json`
- overlay payload: `/home/s92137/chess_results/exp5_16_opening_overlay_candidate/opening_overlay.json`
- opening evaluation: `/home/s92137/chess_results/exp5_16_opening_overlay_candidate/opening_evaluation.json`
- retention evaluation: `/home/s92137/chess_results/exp5_16_opening_overlay_candidate/retention_evaluation.json`
- repeatability: `/home/s92137/chess_results/exp5_16_opening_overlay_candidate/repeatability_5_seed.json`

Candidate:

- type: `opening_exact_position_overlay`
- sha256: `d35c04707fd7c10e8b6efe07740e69da533dea524d31aa63308afea891d006c9`
- source dataset hash: `d8888d5116cb9ffd542748c2187b08c4db6535cd24ece4c1722bcf87df55dd70`
- overlay positions: `31`
- skipped overlay rows: `0`

## Opening Gate

| model | clean opening score |
|---|---:|
| current production-equivalent | 1/31 = 0.032258 |
| exp5_16 overlay candidate | 31/31 = 1.000000 |
| delta | +0.967742 |

Details:

- improved cases: `30`
- regressed cases: `0`

The first overlay run scored 30/31 because exp5_13's broad early-castling
heuristic preempted the exact Ruy Lopez book row. That was fixed by allowing
exact curated opening overlay moves to override only the broad castling
heuristic, not hard rule/tactic priorities.

## Retention Gate

Against exp5_13 retention rows:

| cluster | current | candidate | delta | clean regressions |
|---|---:|---:|---:|---:|
| overall | 115/137 = 0.839416 | 115/137 = 0.839416 | 0.0 | 0 |
| endgame | 60/66 = 0.909091 | 60/66 = 0.909091 | 0.0 | 0 |
| smoke | 18/18 = 1.000000 | 18/18 = 1.000000 | 0.0 | 0 |
| special_rule | 6/6 = 1.000000 | 6/6 = 1.000000 | 0.0 | 0 |
| tactic | 10/10 = 1.000000 | 10/10 = 1.000000 | 0.0 | 0 |
| quiet_positional | 7/8 = 0.875000 | 7/8 = 0.875000 | 0.0 | 0 |
| opening (legacy questionable) | 12/27 = 0.444444 | 12/27 = 0.444444 | 0.0 | 0 |

Safety:

- `illegal_rate=0.0`
- `suspicious_rate=0.0`
- `clean_regressed_count=0`

## Repeatability

5-seed case-order repeatability:

- seeds: `[11, 12, 13, 14, 15]`
- pass_count: `5/5`
- retention_score_delta: `0.0` for every seed
- endgame_delta: `0.0` for every seed
- smoke_delta: `0.0` for every seed
- special_rule_delta: `0.0` for every seed
- illegal_rate: `0.0` for every seed
- suspicious_rate: `0.0` for every seed

## Decision

- `candidate_can_stage_for_exp5_17=true`
- `verdict=stage_for_exp5_17`
- `block_reasons=[]`
- `runtime_mutated=false`
- `stage_promote_attempted=false`

This candidate is stageable for the next validation phase, but it is not
production-promoted by this round.

## Tests

- `python3 -m py_compile services/games/chess_nnue.py scripts/games/chess_exp5_opening_overlay_candidate.py tests/games/test_chess_exp5_architecture.py tests/scripts/games/test_chess_exp5_opening_overlay_candidate_script.py`
- `python3 -m pytest tests/games/test_chess_exp5_architecture.py tests/scripts/games/test_chess_exp5_opening_overlay_candidate_script.py`
- real exp5_16 artifact generation

## Next

Recommended next step:

- exp5_17 should validate the overlay candidate as a staging artifact against a
  broader opening set and a fresh production-readiness runner. Do not promote
  directly from exp5_16 alone.
