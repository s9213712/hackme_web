# Exp5 V26 Rejected-Centric Gate

This report is redacted. It contains no FENs, moves, teacher PVs, source game
identifiers, chosen moves, source moves, or per-position answers.

## Fixed Baseline

V26 is compared only against the V24 percent-tail 100-scenario validation
baseline:

| Metric | V24 percent-tail baseline |
|---|---:|
| Total positions | 4,624 |
| Clean rate | 64.58% |
| Review+ rate | 81.55% |
| Total rejected | 853 |
| Complete-game rejected | 475 |
| Tail 50% rejected | 209 |
| Tail 25% rejected | 127 |

The older 3,659-position expanded validation run is retained as historical
evidence only and is not mixed into V26 gate arithmetic.

## Primary Objective

V26 targets weak-slice rejected reduction. The current failure taxonomy shows
that rejected rows are dominated by candidate/search miss rather than simple
top-5 reranking, so V26 is split into isolated phases:

| Phase | Scope |
|---|---|
| V26a | Candidate/search repair only: selective depth and candidate ordering coverage. |
| V26b | Generic endgame conversion evaluator safety. |
| V26c | Quiet safety and tactical exposure mitigation. |
| V26d | Quiet positional ordering, only after rejected-count repair is stable. |

## Acceptance Thresholds

| Gate | V24 baseline | V26 acceptance threshold |
|---|---:|---:|
| Complete-game rejected | 475 | <= 427 |
| Tail 50% rejected | 209 | <= 188 |
| Tail 25% rejected | 127 | <= 114 |
| Human/trap guardrail | Saturated historical slice | Clean rate >= 96% when run |
| Complete-game gauntlet | V24 had no losses | Losses = 0 |

The total rejected count is tracked as a secondary metric, but it is not the
single promotion criterion. A candidate must improve the weak slices without
using exact-memory lookup or writing validation-set priors.

## Evidence Rules

All full validation details stay under `runtime/private/`. Public evidence in
`docs/games/evidence/exp5/` must remain aggregate-only. The V26 gate is produced
by `scripts/games/chess_exp5_v26_gate.py`.
