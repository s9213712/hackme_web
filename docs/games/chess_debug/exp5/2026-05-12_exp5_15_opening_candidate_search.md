# exp5_15 opening curriculum candidate search

## Scope

This round starts from exp5_14b's clean opening curriculum and tries bounded
staging candidates against the current exp5 production model. It does not stage,
promote, or modify the runtime model.

Production baseline:

- expected sha256: `c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc`
- actual sha256: `c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc`
- model source: `promoted_stage_candidate_fallback`

## Tool

Added:

- `scripts/games/chess_exp5_opening_candidate_search.py`

The tool:

- reads the clean opening curriculum from exp5_14b
- expands multi-good `expected_uci_any` labels into weighted training samples
- injects hard negatives from the current production-equivalent model
- optionally mixes endgame retention rows from the exp5_08 clean pool
- evaluates each candidate against the clean opening pool
- screens each candidate against the exp5_13 expanded production validation set
- writes all artifacts under `~/chess_results`

## Trainer Fix Found During Search

The first exp5_15 probe exposed a real trainer sign bug for black samples. In
`services/games/chess_nnue.py::_train_position_move`, positive black samples
were previously multiplied by `side_sign`, which reduced the black piece-square
feature weight for a positive target.

This was corrected so piece-square / shared-center weights receive the positive
sample delta directly. The evaluator already applies piece color sign in
`_sparse_feature_score`. The tempo term remains side-signed because it is keyed
to side-to-move, not a piece-color feature.

Regression test added:

- `tests/games/test_chess_exp5_architecture.py::test_exp5_training_positive_black_sample_increases_black_piece_weight`

## Results

Output directory:

- `/home/s92137/chess_results/exp5_15_opening_candidate_search/`

Artifacts:

- summary: `/home/s92137/chess_results/exp5_15_opening_candidate_search/summary.json`
- summary md: `/home/s92137/chess_results/exp5_15_opening_candidate_search/SUMMARY.md`
- opening samples: `/home/s92137/chess_results/exp5_15_opening_candidate_search/opening_train_samples.jsonl`
- retention samples: `/home/s92137/chess_results/exp5_15_opening_candidate_search/retention_train_samples.jsonl`

Input counts:

| metric | value |
|---|---:|
| opening curriculum rows | 31 |
| opening train samples | 109 |
| retention train rows available | 116 |
| retention train samples used | 80 |
| hard negative topK | 4 |
| search profile | `fixed_depth_strong` |

Candidate summary:

| candidate | sha256 | opening score | opening delta | retention score | retention delta | clean regressions | verdict |
|---|---|---:|---:|---:|---:|---:|---|
| A_opening_only_e8_hn4 | `3acde277bb8b70219c59a3a0a954934315ab0deca38df0e62a860aa353bc75f5` | 1/31 = 0.032258 | 0.0 | 112/137 = 0.817518 | -0.021898 | 5 | blocked |
| B_opening_retention_e8_hn4 | `cf19fcd97b8f0803395c4080cc7c8c3fc0547170c023754522795dde52b9fc95` | 1/31 = 0.032258 | 0.0 | 111/137 = 0.810219 | -0.029197 | 4 | blocked |

Candidate artifacts:

- A model: `/home/s92137/chess_results/exp5_15_opening_candidate_search/A_opening_only_e8_hn4/chess_experiment_5_nnue_candidate.json`
- A replay: `/home/s92137/chess_results/exp5_15_opening_candidate_search/A_opening_only_e8_hn4/chess_experiment_5_nnue_candidate_replay.jsonl`
- B model: `/home/s92137/chess_results/exp5_15_opening_candidate_search/B_opening_retention_e8_hn4/chess_experiment_5_nnue_candidate.json`
- B replay: `/home/s92137/chess_results/exp5_15_opening_candidate_search/B_opening_retention_e8_hn4/chess_experiment_5_nnue_candidate_replay.jsonl`

## Retention Screen

Both candidates improved the old questionable opening cluster but failed the
clean opening pool and regressed endgame retention.

| cluster | current | A | B |
|---|---:|---:|---:|
| old opening cluster | 12/27 = 0.444444 | 15/27 = 0.555556 | 15/27 = 0.555556 |
| endgame | 60/66 = 0.909091 | 54/66 = 0.818182 | 53/66 = 0.803030 |
| quiet_positional | 7/8 = 0.875000 | 7/8 = 0.875000 | 7/8 = 0.875000 |
| smoke | 18/18 = 1.000000 | 18/18 = 1.000000 | 18/18 = 1.000000 |
| special_rule | 6/6 = 1.000000 | 6/6 = 1.000000 | 6/6 = 1.000000 |
| tactic | 10/10 = 1.000000 | 10/10 = 1.000000 | 10/10 = 1.000000 |

Safety stayed clean for both candidates:

- `illegal_rate=0.0`
- `suspicious_rate=0.0`
- no stage/promote attempt
- runtime model untouched

## Decision

- `best_candidate=""`
- `candidate_can_stage_for_exp5_16=false` for both candidates
- `runtime_mutated=false`
- `stage_promote_attempted=false`

No exp5_15 candidate is stageable. The current exp5 production model remains
the correct runtime.

## Interpretation

The black-sample sign fix is real and should remain. It makes the trainer
directionally correct for both colors and is now covered by regression test.

The opening candidates are not strong enough. They do not improve the 31-row
clean opening pool and they damage the endgame signal that made exp5 production
valuable. This suggests the current sparse NNUE-like update path is too blunt
for opening repair. The next attempt should investigate opening priors,
book-like features, or a narrower non-destructive opening overlay before trying
another promotion-grade candidate.

## Tests

- `python3 -m py_compile services/games/chess_nnue.py scripts/games/chess_exp5_opening_candidate_search.py tests/games/test_chess_exp5_architecture.py tests/scripts/games/test_chess_exp5_opening_candidate_search_script.py`
- `python3 -m pytest tests/games/test_chess_exp5_architecture.py tests/scripts/games/test_chess_exp5_opening_candidate_search_script.py`
- real exp5_15 artifact generation

## Next

Recommended next step:

- design an opening-specific candidate path that does not overwrite the
  promoted endgame behavior, likely via opening-prior / book-style move
  preference features or a separately gated opening overlay

Do not use exp5_15 A/B as exp5_16 candidates.
