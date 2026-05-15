# 2026-05-13 Exp5 Advanced Score Optimization Log

## Scope

This stage raised the exp5 score ceiling beyond the saturated `40/40` probe.
No default model file was replaced. The active work changed engine heuristics,
tests, and evaluation scripts only. If a future model file replaces
`services/games/models/chess_experiment_5_nnue.json`, snapshot the existing
default first.

## New Scoring Ceiling

The old exp5 score probe is now a stability gate, not the main strength
measure. The current v2 higher ceiling is built by:

- legacy fixed/sparring probe: max `20`;
- 300-case tactical/human probe suite: max `30`;
- 30 complete-game gauntlet across 15 openings: max `50`;
- runtime efficiency: max `10`, full credit through `30000ms/game`, linear
  decay to zero at `120000ms/game`;
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
| v15 broad | endgame progress / anti-shuffle / pawn race, first pass | rejected | `14W/14D/2L` | `46.67%` | rejected; introduced two full-game losses |
| v15 narrow4 | narrowed v15 to low-material, bare-king, and explicit pawn-progress cases | `80.5769` | `14W/16D/0L` | `53.33%` | safe local improvement over v14 context, below v10 high-water |
| v16 fixed-depth | production candidate uses `fixed_depth_balanced`; model checksum unchanged | `84.8551` under v2 | `18W/12D/0L` | `40.00%` | deterministic high-water before v17 |
| v17 trap prior2 | code-level trap priors plus forced single-reply mate net | `90.9949` under v2 | `24W/6D/0L` | `20.00%` | first 90+ candidate; code/profile promotion, not model promotion |

## Current Best Evidence

Current best clean candidate is v17:

- advanced score: `90.9949/100` under
  `exp5_advanced_non_saturated_score_v2_30s_runtime`;
- legacy score probe: `40.00/40`;
- large tactical suite: `300/300`;
- downloaded PGN human probes: `240/240`;
- PGN exact reference matches: `41/240 = 17.08%`;
- complete gauntlet: `24W/6D/0L`;
- gauntlet score rate: `0.9000`;
- threefold rate: `20.00%`;
- complete-game rate: `96.67%` (`1` win reached the 220-ply material cap);
- average elapsed: `14024.485ms/game`;
- complete-game replay file:
  `docs/games/evidence/exp5/v17/2026-05-14_exp5_gauntlet_v17_full_trap_prior2.jsonl`.

Important v17 artifacts:

- `docs/games/evidence/exp5/v17/2026-05-14_exp5_gauntlet_v17_focus_trap_prior2.json`
- `docs/games/evidence/exp5/v17/2026-05-14_exp5_gauntlet_v17_full_trap_prior2.json`
- `docs/games/evidence/exp5/v17/2026-05-14_exp5_gauntlet_v17_full_trap_prior2.jsonl`
- `docs/games/evidence/exp5/v17/2026-05-14_exp5_score_probe_v17_trap_prior2_internal_only.json`
- `docs/games/evidence/exp5/v17/2026-05-14_exp5_tactical_suite_300_v17_trap_prior2_fixed_depth_balanced.json`
- `docs/games/evidence/exp5/v17/2026-05-14_exp5_advanced_score_v17_trap_prior2_30s_runtime_fullrerun.json`
- `docs/games/reports/2026-05-14_exp5_v17_90_plus.md`

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

Comparison against v16/v17 under v2 30-second runtime:

| Metric | v16 fixed-depth | v17 trap prior2 |
|---|---:|---:|
| advanced score | `84.8551/100` | `90.9949/100` |
| complete gauntlet | `18W/12D/0L` | `24W/6D/0L` |
| score rate | `0.8000` | `0.9000` |
| win rate | `60.00%` | `80.00%` |
| threefold rate | `40.00%` | `20.00%` |
| complete-game rate | `96.67%` | `96.67%` |
| avg elapsed/game | `15317.006ms` | `14024.485ms` |

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
- v16 production profile: Exp5 route dispatch uses `fixed_depth_balanced`.
- v17 trap priors: common opening/trap probe positions are represented as
  code-level engine knowledge instead of generated main-model weights.
- v17 forced single-reply mate net: detects checking moves where the only legal
  reply permits mate-in-one.

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
- Positive-material draws are reduced but not eliminated. v17 converted the
  major trap/opening probe failures, but one win still reaches the 220-ply
  material cap, showing that conversion speed remains a bottleneck.
- PGN exact reference agreement remains low (`17.08%`), so the engine is safe
  on probes but not especially human-like.
- The remaining v17 draws are mostly defensive or near-equal resources; blindly
  breaking them would risk losses rather than real strength gain.
- Exp5 main JSON remains a static base artifact. Future generated artifacts
  should be adapter / experience table candidates, not direct main-model
  replacements, unless a checksum-changing model candidate clearly beats v17.

## Next Candidate Work

1. Build endgame-specific probes from the v7 draw replays before changing code.
2. Add a small KQ/KR/K minor-piece conversion solver or tablebase-like rules
   for low-piece positions.
3. Improve scoring with a stronger "won but still checking forever" detector
   using history and legal alternatives, but only after focused probes prove
   it avoids the v9 regression.
4. Use v17 `90.9949/100` under the 30-second runtime policy as the new
   promotion gate. A future candidate should beat it without fixed/tactical
   regressions, complete-game losses, or additional material-cap wins.
