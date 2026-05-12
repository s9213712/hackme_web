# exp5_14b clean opening held-out expansion

## Scope

This round follows exp5_14. It builds clean opening data for the next exp5
candidate search. It does not retrain, stage, promote, or modify runtime model
artifacts.

## Why

exp5_14 showed that the existing opening cluster was not a production blocker:
all 27 opening rows were `questionable`. It also showed those rows are not safe
training evidence. exp5_14b therefore creates a separate clean opening pool
with curated multi-good labels.

## Tool

Added:

- `scripts/games/chess_exp5_clean_opening_expansion.py`

The tool:

- builds opening FEN rows from curated SAN opening lines
- requires every row to be `label_quality=clean`
- requires multi-good `expected_uci_any`
- verifies expected moves are legal
- audits overlap against exp5_08 train rows and exp5_13 benchmark rows
- writes artifacts to `~/chess_results`

## Results

Output directory:

- `/home/s92137/chess_results/exp5_14b_clean_opening_heldout/`

Artifacts:

- summary: `/home/s92137/chess_results/exp5_14b_clean_opening_heldout/summary.json`
- summary md: `/home/s92137/chess_results/exp5_14b_clean_opening_heldout/SUMMARY.md`
- clean cases: `/home/s92137/chess_results/exp5_14b_clean_opening_heldout/clean_opening_cases.jsonl`
- held-out cases: `/home/s92137/chess_results/exp5_14b_clean_opening_heldout/clean_opening_heldout.jsonl`
- curriculum rows: `/home/s92137/chess_results/exp5_14b_clean_opening_heldout/clean_opening_curriculum.jsonl`
- evaluation: `/home/s92137/chess_results/exp5_14b_clean_opening_heldout/clean_opening_evaluation.json`

| metric | value |
|---|---:|
| raw curated rows | 40 |
| kept clean opening rows | 31 |
| minimum target | 30 |
| label_quality clean | 31 |
| multi-good rows | 31 |
| true held-out rows | 31 |
| dataset hash | `d8888d5116cb9ffd542748c2187b08c4db6535cd24ece4c1722bcf87df55dd70` |

## Overlap

The script skipped overlapping raw candidates and kept only disjoint rows.

| overlap audit | value |
|---|---:|
| kept train overlap | 0 |
| kept benchmark overlap | 0 |
| kept position_id overlap | 0 |
| raw train overlap skipped | 1 |
| raw benchmark overlap skipped | 8 |
| skipped rows | 9 |

## Current Production Opening Probe

The local repo runtime override path did not contain
`runtime/games/models/chess_experiment_5_nnue.json`, so the evaluation used the
already-promoted stage artifact as the current-production equivalent:

- evaluation model: `/home/s92137/chess_results/exp5_08_stage_candidate/chess_experiment_5_nnue_stage_candidate.json`
- evaluation source: `promoted_stage_candidate_fallback`

Result under `fixed_depth_strong`:

| model | score |
|---|---:|
| bundled baseline | 1/31 = 0.032258 |
| production-equivalent exp5 | 1/31 = 0.032258 |
| delta | 0.0 |

This confirms the next exp5 strength target: opening play is still very weak
against clean curated opening labels. Most misses are low-quality flank pawn or
rim-knight style moves such as `a2a3`, `a7a5`, `g1h3`.

## Decision

- exp5_14b pass: `true`
- clean opening curriculum is now available for exp5_15
- no runtime/model mutation occurred
- this is not promotion evidence

## Tests

- `python3 -m py_compile scripts/games/chess_exp5_clean_opening_expansion.py tests/scripts/games/test_chess_exp5_clean_opening_expansion_script.py`
- `python3 -m pytest tests/scripts/games/test_chess_exp5_clean_opening_expansion_script.py`
- real exp5_14b artifact generation

## Next

Recommended next step:

- exp5_15 candidate search using the clean opening curriculum as a bounded
  training slice

exp5_15 must compare against current production sha
`c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc`, not the
old bundled seed.
