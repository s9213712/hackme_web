# 2026-05-13 Exp5 v15 Endgame Progress Attempt

## Scope

This stage followed the "do not train replay directly into the main model"
rule. The default model bytes were not changed.

Implemented code-only v15 heuristics:

- endgame conversion progress scoring for low-material and bare-king cases;
- recent non-progress shuffle filtering;
- passed/advanced-pawn race handling;
- a narrow opening guard that prefers normal minor-piece development over a
  low-value early pawn capture when the development move is materially safe.

## Evidence

| Check | Artifact | Result |
|---|---|---:|
| Exp5 architecture tests | `tests/games/test_chess_exp5_architecture.py` | `37/37` passed |
| Legacy internal score gate | `docs/games/evidence/exp5/v15/2026-05-13_exp5_score_probe_v15_internal_only.json` | `40/40` |
| Current downloaded PGN exact score probe | `docs/games/evidence/exp5/v15/2026-05-13_exp5_score_probe_v15_endgame_progress.json` | `28.43/40` |
| Tactical/human suite | `docs/games/evidence/exp5/v15/2026-05-13_exp5_tactical_suite_300_v15_endgame_progress.json` | `300/300`, PGN pass `240/240`, exact `40/240` |
| First broad v15 gauntlet | `docs/games/evidence/exp5/v15/2026-05-13_exp5_gauntlet_v15_endgame_progress.json` | `14W/14D/2L`, rejected |
| Narrowed focused French/Reti gate | `docs/games/evidence/exp5/v15/2026-05-13_exp5_gauntlet_v15_narrow4_french_reti.json` | `1W/3D/0L` |
| Narrowed full gauntlet | `docs/games/evidence/exp5/v15/2026-05-13_exp5_gauntlet_v15_narrow4_full.json` | `14W/16D/0L` |
| Advanced score | `docs/games/evidence/exp5/v15/2026-05-13_exp5_advanced_score_v15_narrow4.json` | `80.5769/100` |

## Comparison

| Version | Advanced | 30-game result | Threefold | Complete-game | Decision |
|---|---:|---:|---:|---:|---|
| v14 current context | `80.0813` | `14W/16D/0L` | `53.33%` | `93.33%` | baseline context |
| v15 broad | not promoted | `14W/14D/2L` | `46.67%` | `100.00%` | rejected; introduced losses |
| v15 narrow4 | `80.5769` | `14W/16D/0L` | `53.33%` | `100.00%` | safe local improvement, below promotion gate |
| v10 historical high-water | `84.1482` | `18W/12D/0L` | `40.00%` | `93.33%` | still stronger by this score |

## Findings

v15 improved specific local behaviors:

- low-material passed pawn race: the engine now pushes a near-promotion pawn
  instead of wandering with the king in simple K/P positions;
- bare-king conversion: K+R versus K positions prefer cutting the king off
  instead of retreating the rook to a harmless square;
- recent rook/king shuffling: a direct recent cycle can be replaced by a safe
  progress move;
- current full gauntlet no longer reaches material-cap adjudication.

The first broad attempt was unsafe. Applying progress scoring too broadly in
complex fullmove-20+ positions introduced two complete-game losses, so the
heuristic was narrowed to low-material, bare-king, or explicit pawn-progress
cases.

The final v15 narrow4 result is not a real 90+ attempt:

- win count did not increase over v14 context (`14W` remains `14W`);
- threefold rate remains high at `53.33%`;
- several draws are actually defensive saves where Exp5 is materially behind,
  so forcing play-on blindly would reduce strength;
- score is still below the v10 historical high-water (`80.5769` vs `84.1482`).

## Decision

Do not replace the default model and do not call this a promoted engine.

Keep the code changes only if the goal is to preserve local endgame behavior
improvements and better complete-game accounting. For a true 90+ push, the
next work should not add broader hand-written filters. It should restore or
explain the v10 18-win behavior under a deterministic gauntlet, then improve
search depth/time management or introduce a proper endgame solver/tablebase-like
module for KQK/KRK/KPK rather than expanding replay or special-case memory.
