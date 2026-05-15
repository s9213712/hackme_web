# Exp5 V27h Current Strongest Baseline

This report is redacted. It contains no FENs, moves, teacher PVs, source game
identifiers, chosen moves, source moves, or per-position answers.

## Decision

The strongest validation baseline is now:

`fixed_depth_fianchetto_tail_castle_guard_v27h_depth3_no_null_mate_net30`

`EXP5_PRODUCTION_SEARCH_PROFILE` has been updated to this profile.

V27h keeps the V26e depth-3/PVS/LMR/futility search structure with null-move
disabled, then widens the bounded mate-net helper to 30 pieces with node and
root-check caps. This repaired a small number of forced-mate conversion misses
without using exact validation-position memory or a live Stockfish oracle.

## Deterministic Teacher

Stockfish/Blockfish teacher audit now fixes `Threads=1`, `Hash=32`, enables
analysis mode, and clears hash before each analysis call. This reduced gate
noise near the 2-6 rejected-row margin.

## Percent-Tail 100 Gate

Baseline: `fixed_depth_fianchetto_tail_castle_guard`

Candidate: `fixed_depth_fianchetto_tail_castle_guard_v27h_depth3_no_null_mate_net30`

| Metric | V24 deterministic | V27h deterministic |
|---|---:|---:|
| Positions | 4,624 | 4,624 |
| Clean rate | 65.72% | 69.27% |
| Review+ rate | 82.12% | 84.43% |
| Top5 rate | 51.49% | 55.79% |
| Total rejected | 827 | 720 |
| Complete rejected | 453 | 402 |
| Tail50 rejected | 205 | 183 |
| Tail25 rejected | 126 | 101 |

Gate result: accepted.

| Gate | Required max | V27h | Result |
|---|---:|---:|---|
| Complete-game rejected | 407 | 402 | Pass |
| Tail50 rejected | 184 | 183 | Pass |
| Tail25 rejected | 113 | 101 | Pass |

## Blockfish Staged Match

Staged opponent schedule: depth 2, 3, 4, 5, 6.

| Metric | Result |
|---|---:|
| Games | 5 |
| Exp5 wins | 0 |
| Draws | 0 |
| Blockfish wins | 5 |
| Exp5 score rate | 0.00% |
| Complete games | 5 |

This means V27h is the strongest current Exp5 validation baseline, but it is
not a Stockfish-class engine. The next structural target should be defensive
forced-mate detection and broader candidate generation, not more validation-set
patches.

## Evidence

- `docs/games/evidence/exp5/v24_percent_tail_100_deterministic_evaluation.json`
- `docs/games/evidence/exp5/v27h_depth3_no_null_mate_net30_percent_tail_100_deterministic_evaluation.json`
- `docs/games/evidence/exp5/v27h_depth3_no_null_mate_net30_deterministic_gate.json`
- `docs/games/evidence/exp5/v27h_depth3_no_null_mate_net30_blockfish_staged_5_summary.json`

Private replay/detail files remain under `runtime/private/games/exp5/`.
