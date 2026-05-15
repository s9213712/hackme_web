# Exp5 V27k Current Strongest Baseline

## Scope

V27k promotes the strongest current Exp5 profile:

`fixed_depth_fianchetto_tail_castle_guard_v27k_depth3_no_null_mate_net30_defense_book`

The change is structural and generic: V27k keeps V27i's depth-3 no-null
mate-net defense and enables the deterministic static opening book. It does
not use validation-position memory, per-question priors, FEN lookup, teacher PV
lookup, or bundled Stockfish.

## Percent-Tail 100 Gate

Compared with V27i on the fixed redacted percent-tail 100 validation set:

| Metric | V27i | V27k | Delta |
|---|---:|---:|---:|
| Positions | 4,624 | 4,624 | 0 |
| Clean rate | 69.40% | 69.46% | +0.06pp |
| Review+ rate | 84.56% | 84.60% | +0.04pp |
| Top5 rate | 55.86% | 56.34% | +0.48pp |
| Total rejected | 714 | 712 | -2 |
| Complete-game rejected | 399 | 397 | -2 |
| Tail50 rejected | 182 | 182 | 0 |
| Tail25 rejected | 100 | 100 | 0 |
| Tail10 rejected | 33 | 33 | 0 |

This is a small deterministic validation gain, but it is not a regression in
the weak tail slices and it improves complete-game rejected count.

## Staged Blockfish Match

V27k materially improves the staged local Blockfish/Stockfish match:

| Profile | Depth schedule | W/D/L | Exp5 score |
|---|---|---:|---:|
| V27i | 2,3,4,5,6 | 0/1/4 | 10% |
| V27k | 2,3,4,5,6 | 0/3/2 | 30% |

The staged result suggests V27i was not only losing because Stockfish is
stronger; it also had an opening/coherence blind spot that caused middle-game
collapse. The static book does not make Exp5 Stockfish-class, but it prevents
two staged losses from turning into immediate checkmate losses.

## Current Judgment

V27k is the current strongest Exp5 baseline because it improves both the fixed
aggregate validation and the independent staged Blockfish match. Remaining
weaknesses are still concentrated in candidate/search misses, quiet positional
ordering, king-safety exposure, and conversion under long complete-game
pressure.

## Rejected Probe

Before V27k, a V27j-style final forced-mate defense was tested against the
private staged replay. It repaired two late mate-collapse points locally, but
the staged W/D/L stayed at 0/1/4 and complete-game validation became too slow
for the gain. That path was not promoted into the production profile.

## Evidence

- `docs/games/evidence/exp5/v27k_depth3_no_null_mate_net30_defense_book_percent_tail_100_deterministic_evaluation.json`
- `docs/games/evidence/exp5/v27k_depth3_no_null_mate_net30_defense_book_percent_tail_100_deterministic_failure_taxonomy.json`
- `docs/games/evidence/exp5/v27k_depth3_no_null_mate_net30_defense_book_blockfish_staged_5_summary.json`
- `docs/games/evidence/exp5/v27k_depth3_no_null_mate_net30_defense_book_current_strongest_comparison.json`

Private replay/detail files remain outside the repo under
`/home/s92137/hackme_web_private/runtime/private/games/exp5/`.
