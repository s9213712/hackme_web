# Exp5 V27i Current Strongest Baseline

This report is redacted. It contains no FENs, moves, teacher PVs, source game
identifiers, chosen moves, source moves, or per-position answers.

## Decision

The strongest validation baseline is now:

`fixed_depth_fianchetto_tail_castle_guard_v27i_depth3_no_null_mate_net30_defense`

`EXP5_PRODUCTION_SEARCH_PROFILE` has been updated to this profile.

V27i keeps V27h's bounded mate-net30 search and adds a narrow defensive
forced-mate check: it first tests only the selected candidate, and only scans
alternatives when that candidate allows a bounded checking mate net. This keeps
the patch generic and avoids exact validation-position memory.

## Percent-Tail 100 Gate

Baseline: `fixed_depth_fianchetto_tail_castle_guard`

Candidate: `fixed_depth_fianchetto_tail_castle_guard_v27i_depth3_no_null_mate_net30_defense`

| Metric | V24 deterministic | V27h deterministic | V27i deterministic |
|---|---:|---:|---:|
| Positions | 4,624 | 4,624 | 4,624 |
| Clean rate | 65.72% | 69.27% | 69.40% |
| Review+ rate | 82.12% | 84.43% | 84.56% |
| Top5 rate | 51.49% | 55.79% | 55.86% |
| Total rejected | 827 | 720 | 714 |
| Complete rejected | 453 | 402 | 399 |
| Tail50 rejected | 205 | 183 | 182 |
| Tail25 rejected | 126 | 101 | 100 |

Gate result: accepted.

| Gate | Required max | V27i | Result |
|---|---:|---:|---|
| Complete-game rejected | 407 | 399 | Pass |
| Tail50 rejected | 184 | 182 | Pass |
| Tail25 rejected | 113 | 100 | Pass |

## Blockfish Staged Match

Staged opponent schedule: depth 2, 3, 4, 5, 6.

| Metric | V27h | V27i |
|---|---:|---:|
| Games | 5 | 5 |
| Exp5 wins | 0 | 0 |
| Draws | 0 | 1 |
| Blockfish wins | 5 | 4 |
| Exp5 score rate | 0.00% | 10.00% |
| Complete games | 5 | 5 |

V27i is still far below Stockfish-class play, but it is the first current
candidate to survive the staged depth-2 game without losing.

## Evidence

- `docs/games/evidence/exp5/v27i_depth3_no_null_mate_net30_defense_percent_tail_100_deterministic_evaluation.json`
- `docs/games/evidence/exp5/v27i_depth3_no_null_mate_net30_defense_deterministic_gate.json`
- `docs/games/evidence/exp5/v27i_depth3_no_null_mate_net30_defense_blockfish_staged_5_summary.json`

Private replay/detail files were moved outside the repo to
`$HACKME_WEB_PRIVATE_ROOT/games/exp5/`.
