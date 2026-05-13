# 2026-05-13 Exp5 Advanced Score Optimization Log

## Scope

This stage raised the exp5 score ceiling beyond the saturated `40/40` probe.
No default model file was replaced. The active work changed engine heuristics,
tests, and evaluation scripts only. If a future model file replaces
`services/games/models/chess_experiment_5_nnue.json`, snapshot the existing
default first.

## New Scoring Ceiling

The old exp5 score probe is now a stability gate, not the main strength
measure. The higher ceiling is built by:

- legacy fixed/sparring probe: max `20`;
- 300-case tactical/human probe suite: max `30`;
- 30 complete-game gauntlet across 15 openings: max `50`;
- runtime efficiency: max `10`;
- total max `110`, normalized to `100`.

Script:

- `scripts/games/chess_exp5_advanced_score.py`

## Script Call Map

| Purpose | Script | Typical output |
|---|---|---|
| legacy exp5 fixed + sparring probe | `scripts/games/chess_exp5_score_probe.py` | `docs/games/2026-05-13_exp5_score_probe_*.json` |
| large tactical/human probe suite | `scripts/games/chess_exp5_tactical_suite.py` | `docs/games/2026-05-13_exp5_tactical_suite_300_*.json` |
| complete-game multi-opening gauntlet | `scripts/games/chess_exp5_gauntlet.py` | `docs/games/2026-05-13_exp5_gauntlet_*.json` and `.jsonl` |
| advanced non-saturated score | `scripts/games/chess_exp5_advanced_score.py` | `docs/games/2026-05-13_exp5_advanced_score_*.json` |

The tactical suite uses the downloaded replay file:

- `docs/games/2026-05-13_exp5_download_script_probe_replay.jsonl`

## Optimization History

| Version | Change | Advanced /100 | 30-game result | Threefold | Decision |
|---|---|---:|---:|---:|---|
| v1 baseline | SEE/search-extension baseline with expanded 30-game gauntlet | `80.5560` | `14W/15D/1L` | `50.00%` | superseded |
| v2 | broad opening king-walk guard | `75.4820` | `9W/19D/2L` | `63.33%` | rejected; too broad |
| v3 | narrowed king-walk guard to e1/e8 check evasions | `78.6605` | `12W/18D/0L` | `60.00%` | safer but lower score |
| v4 | avoid giving opponent claimable repetition when ahead | `79.7593` | `13W/17D/0L` | `56.67%` | partial improvement |
| v5 | more ambitious draw policy, only force draws when behind | `81.6491` | `16W/14D/0L` | `46.67%` | high score, but random sparring regressed |
| v6 | broad immediate-promotion guard | `83.4153` | `17W/11D/2L` | `36.67%` | rejected; two complete-game losses |
| v7 | narrowed promotion guard to checking promotions | `83.5503` | `17W/13D/0L` | `43.33%` | current best clean candidate |
| v8 | king-capture move-order experiment | `81.5769` | `15W/15D/0L` | `50.00%` | rejected; focused gain did not generalize |
| v9 | reversible checking-cycle experiment | focused only | focused `4W/4D/0L` | `50.00%` | rejected; no focused gain over v7 |
| v10 | advantage-side repetition progress rule | `84.1482` | `18W/12D/0L` | `40.00%` | accepted; beats v7, no fixed/tactical regression |

## Current Best Evidence

Current best clean candidate is v10:

- advanced score: `84.1482/100`;
- legacy score probe: `40.00/40`;
- fixed probes: `14.40/14.40`;
- legacy sparring: `6W/0D/0L`;
- large tactical suite: `300/300`;
- downloaded PGN human probes: `240/240`;
- PGN exact reference matches: `40/240 = 16.67%`;
- complete gauntlet: `18W/12D/0L`;
- gauntlet score rate: `0.8000`;
- threefold rate: `40.00%`;
- complete-game rate: `93.33%` (`2` wins reached the 220-ply material cap);
- complete-game replay file:
  `docs/games/2026-05-13_exp5_gauntlet_repetition_progress_v10.jsonl`.

Important v10 artifacts:

- `docs/games/2026-05-13_exp5_score_probe_repetition_progress_v10.json`
- `docs/games/2026-05-13_exp5_tactical_suite_300_repetition_progress_v10.json`
- `docs/games/2026-05-13_exp5_gauntlet_repetition_progress_v10.json`
- `docs/games/2026-05-13_exp5_gauntlet_repetition_progress_v10.jsonl`
- `docs/games/2026-05-13_exp5_advanced_score_repetition_progress_v10_fullrerun.json`

Comparison against v7:

| Metric | v7 | v10 |
|---|---:|---:|
| advanced score | `83.5503/100` | `84.1482/100` |
| complete gauntlet | `17W/13D/0L` | `18W/12D/0L` |
| score rate | `0.7833` | `0.8000` |
| win rate | `56.67%` | `60.00%` |
| threefold rate | `43.33%` | `40.00%` |
| complete-game rate | `100.00%` | `93.33%` |
| avg elapsed/game | `9799.36ms` | `10259.37ms` |

## Adopted Engine Changes

- Opening king-walk guard: avoids non-castling king walks from e1/e8 while in
  opening check when safe non-king evasions exist.
- Opponent-repetition guard: when ahead, avoids moves that allow the opponent
  to claim threefold on the next reply.
- Draw policy: immediate threefold is preserved as a resource only when the AI
  is behind; equal or leading positions prefer safe play-on alternatives.
- Promotion guard: avoids allowing immediate checking promotion if a safe move
  can prevent it.
- v10 repetition progress rule: if the AI is at least `300cp` ahead and the
  selected move gives itself or the opponent a claimable threefold, the engine
  may accept a lower-scored alternative when that alternative preserves material
  within `180cp`, avoids mate-in-one, and avoids a new claimable repetition.

## Rejected Experiments

- Broad king-walk guard: stopped the French loss but created open-game and
  Queen's Gambit losses.
- Broad immediate-promotion guard: raised raw gauntlet score but introduced two
  complete-game losses, so it is not acceptable.
- King-capture move-order rewrite: fixed one Scandinavian focused line but
  reduced full-gauntlet score.
- Checking-cycle reversal guard: did not convert the target King's Indian draw
  and worsened the resulting material profile.

## Retrain / Adapter Follow-up

Later same-day retrain experiments confirmed that direct model replacement is
not yet safe:

- v11 normal-game direct retrain: `78.4954/100`, rejected.
- v12 loose general adapter: `72.4156/100`, rejected.
- v13 exact-memory adoption adapter: `74.2151/100`, rejected.
- v14 guarded notes-only adapter: `81.0343/100`, `0` adopted moves, safe as an
  experience notebook but not a proven strength gain.

Detailed report:

- `docs/games/2026-05-13_exp5_retrain_adapter_comparison.md`

## Remaining Bottlenecks

- Several draws are still real or near-real defensive resources for the
  reviewer policy, especially `start`, `flank_probe`, `reti`, and some black
  side positions where material is not clearly favorable.
- Positive-material draws are reduced but not eliminated. v10 converted the
  French and Sicilian-style safe-progress cases, but two wins now reach the
  220-ply material cap, showing that conversion speed is the next bottleneck.
- PGN exact reference agreement remains low (`16.67%`), so the engine is safe
  on probes but not especially human-like.

## Next Candidate Work

1. Build endgame-specific probes from the v7 draw replays before changing code.
2. Add a small KQ/KR/K minor-piece conversion solver or tablebase-like rules
   for low-piece positions.
3. Improve scoring with a stronger "won but still checking forever" detector
   using history and legal alternatives, but only after focused probes prove
   it avoids the v9 regression.
4. Use v10 `84.1482/100` as the new promotion gate. A future candidate should
   beat it without fixed/tactical/sparring regressions, complete-game losses,
   or additional material-cap wins.
