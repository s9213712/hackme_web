# Exp5 V26 Optimization Summary

This report is redacted. It contains no FENs, moves, teacher PVs, source game
identifiers, chosen moves, source moves, or per-position answers.

## Baseline

V26 uses `v24_percent_tail_100` as the only paired baseline.

| Metric | V24 |
|---|---:|
| Positions | 4,624 |
| Clean rate | 64.58% |
| Review+ rate | 81.55% |
| Rejected | 853 |
| Complete-game rejected | 475 |
| Tail 50% rejected | 209 |
| Tail 25% rejected | 127 |

## Candidate Results

| Candidate | Main change | Clean | Review+ | Rejected | Complete rejected | Tail50 rejected | Tail25 rejected | Gate |
|---|---|---:|---:|---:|---:|---:|---:|---|
| V26a | Selective depth + candidate ordering | 64.92% | 81.53% | 854 | 465 | 217 | 128 | Fail |
| V26b | Strict light endgame eval only | 65.01% | 81.55% | 853 | 469 | 216 | 127 | Fail |
| V26c | Depth 3 + PVS/LMR/null/futility | 68.88% | 83.67% | 755 | 420 | 200 | 100 | Fail: tail50 |
| V26e | Depth 3 + PVS/LMR/futility, null disabled | 67.71% | 83.91% | 744 | 408 | 194 | 107 | Fail: tail50 |

Rejected-count thresholds were complete <= 427, tail50 <= 188, and tail25 <=
114. V26e is the best candidate by total rejected and complete-game rejected,
but it still misses the tail50 gate by 6 rejected rows, so it was not promoted
to production.

## Failed Ablations

| Candidate | Reason rejected |
|---|---|
| V26d | Raising quiescence to 3 worsened tail50 and increased runtime. |
| V26f | Disabling futility worsened tail50 versus V26e and increased runtime. |
| V26g | Disabling LMR caused broad tail regression and was too slow. |

## Taxonomy Takeaway

V26e reduced candidate/search miss materially, but tail50 still has a
candidate/search-miss-heavy residual. The successful direction was structural
search repair, not a new hand-written evaluator, not top-5 reranking, and not
validation-set memorization.

## Guardrails

V26e redacted gauntlet summary:

| Metric | Result |
|---|---:|
| Games | 30 |
| AI wins | 24 |
| Draws | 6 |
| Losses | 0 |
| Score rate | 90.00% |
| Threefold rate | 20.00% |

V26e versus local Blockfish/Stockfish depth 6:

| Metric | Result |
|---|---:|
| Games | 5 |
| Exp5 wins | 0 |
| Draws | 1 |
| Blockfish wins | 4 |
| Exp5 score rate | 10.00% |
| Complete games | 5 |

## Decision

Do not replace the V24 production profile yet. V26e is a strong candidate for
the next search-profile branch, but the formal V26 rejected-centric gate remains
unmet because tail50 rejected is 194 rather than <= 188.

Recommended next step: keep V24 as production, preserve V26e as the best
candidate, then continue with a narrower tail50 repair that does not disable
LMR or futility globally.
