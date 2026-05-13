# 2026-05-13 Exp5 90+ Research Plan

## Current Answer

v7 is not the current best playing-strength result.

- The model bytes in the v7 snapshot are still the current default model bytes.
- The best measured engine result is the v10 search/heuristic code path:
  `84.1482/100`.
- In practical terms, the current best is "v10 code + unchanged v7/default
  model bytes", not a newer model file.

## 90+ Feasibility

The advanced score is normalized from `110` raw points. Reaching `90/100`
requires about `99/110` raw points.

With legacy fixed probes already saturated and PGN exact-match still around
`16.67%`, the quickest path is complete-game conversion:

- v10: `18W/12D/0L`, score rate `0.8000`, advanced `84.1482`.
- Approximate 90+ target at current PGN exact-match level:
  around `24W/6D/0L`, with materially fewer repetition draws and no complete
  losses.

So 90+ is possible under this scoring system, but not by small retrain alone.
It requires converting six or more current draws into wins without introducing
losses or fixed-probe regressions.

## Open-Source Research Notes

Sources checked:

- Stockfish project page:
  https://stockfishchess.org/use/
- Stockfish search source:
  https://github.com/official-stockfish/Stockfish/blob/master/src/search.cpp
- Stockfish NNUE documentation:
  https://official-stockfish.github.io/docs/nnue-pytorch-wiki/docs/nnue.html
- Stockfish fishtest framework:
  https://github.com/official-stockfish/fishtest

Useful ideas, adapted conceptually only:

- Stockfish treats repetition and shuffling as first-class search concerns.
  Exp5 already added anti-repetition filters, but the remaining gap is
  repeated non-progress in winning endgames.
- Stockfish dives into quiescence when regular search depth reaches zero.
  Exp5 already has quiescence, but the qmove filter can be made more selective
  around checking conversions and passed-pawn races.
- Stockfish NNUE documentation emphasizes efficient accumulators and
  side-to-move perspective. Exp5 is JSON/Python and much smaller, but the same
  principle suggests adding a real incremental feature accumulator only if
  deeper deterministic search becomes the bottleneck.
- Fishtest's core lesson is not a single heuristic. It is disciplined A/B
  testing until a change is statistically reliable. For this repo, that means
  focused probes first, then 30-game gauntlet, then larger gauntlet before any
  promotion.

License note: Stockfish is GPLv3. Do not copy code into this project unless
license compatibility is intentionally handled. Use high-level ideas and write
repo-native implementations.

## Best Next Candidates

1. Endgame conversion layer.
   - Add deterministic low-piece conversion policies for KQ/KR/K+passed-pawn
     style positions.
   - Goal: reduce material-cap wins and repetition draws.
   - Gate: must not create stalemates or allow mate-in-one.

2. Progress-aware non-shuffling filter.
   - Extend current reversible-cycle handling to penalize repeated checking or
     king/rook shuffling when ahead.
   - Require a material-safe alternative that improves king distance, pawn
     advancement, or legal-move restriction.

3. Passed-pawn race resolver.
   - For low-material positions, prefer moves that queen a passer fastest or
     stop the opponent passer.
   - Gate with immediate tactical safety.

4. Deterministic gauntlet mode.
   - Use fixed-depth profiles for promotion decisions so timed-search jitter
     does not masquerade as strength.
   - Keep timed runs as secondary runtime evidence.

5. Adapter notebook mining.
   - Keep v11 replay rows as notes.
   - Extract only endgame/repetition positions where main model repeatedly
     fails and teacher/main/gauntlet evidence agree.
   - Continue notes-only by default.

## Proposed 90+ Gate

A candidate can be considered a real 90+ attempt only if it passes:

- legacy score probe: `40/40`;
- tactical suite: `300/300`;
- PGN human probes: no pass-rate regression;
- 30-game gauntlet: no losses;
- target gauntlet: at least `24W/6D/0L` or equivalent score contribution;
- threefold rate: below `20%`;
- current v10 high-water score `84.1482` beaten before larger runs;
- larger follow-up gauntlet before replacing defaults.

## Immediate Recommendation

Try for 90+, but do it as a focused engine phase, not as model retrain.
The highest expected-value patch is a v15 endgame-conversion/progress layer
with focused replay probes before a full gauntlet.
