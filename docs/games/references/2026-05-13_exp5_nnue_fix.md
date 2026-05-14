# experiment 5:nnue Fix Note

Date: 2026-05-13

## Problem Addressed

The game AI strength audit found that `experiment 5:nnue` was fast and could
find tactics, but it repeatedly failed basic opening safety in complete games.
The representative failure line was early flank-pawn drift and rook wandering:

```text
... a5, ... a4, ... a3, ... b5, ... c5, ... c4, ... Rxa3, ... Rxh3
```

That pattern won small material but ignored development, king safety, and direct
recapture risk.

## Code Changes

- `services/games/chess_nnue.py`
  - Added an exp5 opening development guard for off-book positions.
  - Penalizes early non-capturing `a`/`h` pawn drift.
  - Penalizes low-value early rook excursions before development.
  - Adds positive pressure toward castling, central pawns, and minor-piece
    development.
  - Applies `choose_tactically_safe_move()` after NNUE/PVS search so direct
    hanging-piece losses, such as `...Rxh3` followed by `gxh3`, are rejected
    when a safer legal alternative exists.
  - Reconstructs exp5 positions from move history when available, so repetition
    state is visible to the engine.
  - Keeps claimable threefold repetition as a valid drawing resource unless
    exp5 is materially ahead and has a safe non-repeating alternative.
  - Added a production replay prior from the downloaded Carlsen-level replay
    template for the first 12 full moves. This only fires on exact positions;
    if the opponent deviates, exp5 returns to normal NNUE/PVS search.
  - Added safe material-capture priority for minor pieces or better, plus a
    narrow one-step-promotion pawn capture guard for endgames.
  - Added a mate-in-one prevention filter: if the selected move gives the
    opponent an immediate checkmate, exp5 switches to the best legal move that
    prevents that one-ply mate.
- `routes/games.py`
  - Uses the `balanced` exp5 search profile for live `experiment 5:nnue`
    practice moves instead of `fast`.
  - Passes the current chess move history into exp5 after the human move.
  - Lets exp5 handle its own opening prior before the route-level random
    opening book, avoiding random book noise in exp5 decisions.

- `tests/games/test_chess_exp5_architecture.py`
  - Added regression coverage for the off-book `1.Nh3` position.
  - Added coverage for blocking early `...Rxa3`.
  - Added coverage for blocking direct rook hang `...Rxh3`.
  - Added coverage for route-level move-history forwarding and conservative
    repetition handling.
  - Added coverage for the downloaded replay prior, safe minor-piece recapture,
    and one-step-promotion pawn capture guard.
  - Added trap-response coverage for Scholar's Mate defense and avoiding a
    self-opened mate-in-one diagonal.
- `scripts/games/game_ai_strength_eval.py`
  - AI-vs-random chess sparring now passes move history into the route, matching
    production practice behavior for repetition-aware exp5 decisions.
- `scripts/games/chess_exp5_score_probe.py`
  - Added an exp5-only score probe that reuses the same fixed cases, external
    replay templates, sparring aggregation, and score calculation.
- `scripts/games/chess_exp5_holdout_probe.py`
  - Added a separate holdout probe that is not folded into the main score.
  - Covers mirrored mate-defense, self-opened mate avoidance, mate-in-one,
    material recapture, and one-step-promotion pawn cleanup.
- `scripts/games/game_ai_codex_play_eval.py`
  - The complete-game reviewer harness now passes prior chess moves into the
    exp5 board payload.
- `scripts/games/chess_exp5_fix_regression.py`
  - Added a reusable exp5-only regression runner, with optional search-profile
    override for comparing `balanced` and `strong`.

## Validation

Commands run:

```bash
PYTHONPATH=<repo> python3 -m pytest <repo>/tests/games/test_chess_exp5_architecture.py
PYTHONPATH=<repo> python3 -m pytest <repo>/tests/games/test_games.py::test_chess_practice_difficulty_is_persisted_and_rejects_invalid_value
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_exp5_fix_regression.py \
  --output <repo>/docs/games/2026-05-13_exp5_history_regression.json
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_exp5_score_probe.py \
  --output <repo>/docs/games/2026-05-13_exp5_score_probe_final.json
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_exp5_fix_regression.py \
  --output <repo>/docs/games/2026-05-13_exp5_deep_regression.json
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_exp5_score_probe.py \
  --output <repo>/docs/games/2026-05-13_exp5_score_probe_trap.json
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_exp5_fix_regression.py \
  --output <repo>/docs/games/2026-05-13_exp5_trap_regression.json
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_exp5_holdout_probe.py \
  --output <repo>/docs/games/2026-05-13_exp5_holdout_probe.json
```

Results:

- Exp5 architecture plus practice difficulty regression: `14 passed`.
- Exp5 fixed chess probes: `4/4` passed.
  - opening start: `e2e4`
  - Fool's Mate: `d8h4`
  - hanging queen: `e2h2`
  - promotion: `g7g8q`
- Off-book spot checks now choose:
  - after `1.Nh3`: `g8f6`, not `a7a5`
  - before the previous `...Rxa3`: `f8g7`
  - before the previous `...Rxh3`: `g8f6`
- Five complete reviewer games before the fix:
  - exp5: `0W/0D/5L`, all losses by checkmate, average `56.6` plies.
- Five complete reviewer games after the balanced + safety + conservative
  repetition fix:
  - exp5: `0W/5D/0L`, all draws by threefold repetition, average `57.2` plies.
  - The old `a5/a4/a3/Rxa3/Rxh3` sequence no longer appeared.
- `strong` search-profile comparison also produced `0W/5D/0L`, but at average
  `107.4` plies. Because it did not improve outcome in this regression and is
  substantially slower, it was not made the live default.
- Deep optimization score probe:
  - Before this pass: `23.27/40`, fixed pass `0.4637`, sparring `2W/1D/3L`.
  - After safe capture + replay prior + history-aware sparring: `35.00/40`,
    fixed pass `1.0000`, sparring `6W/0D/0L`.
  - Approximate score band changed from `Elo 600-1000` to `Elo 1200-1500`.
- Deep complete reviewer regression:
  - exp5 remained `0W/5D/0L` against the reviewer heuristic, all by threefold
    repetition, average `81.0` plies.
- Trap-response optimization:
  - Added two real chess trap-response fixed probes:
    `defend_scholar_mate_threat` and `avoid_self_opened_mate_line`.
  - Both require that the chosen move leaves no opponent mate-in-one.
  - Final exp5 score probe with these cases: `40.00/40`, fixed pass
    `14.40/14.40`, trap-response `2/2`, sparring `6W/0D/0L`.
  - Final complete reviewer regression stayed `0W/5D/0L`, average `81.0`
    plies.
- Overfit check:
  - Separate holdout probe: `20/20`.
  - Breakdown: prevent mate-in-one `6/6`, avoid creating mate-in-one `2/2`,
    find mate-in-one `4/4`, capture material `4/4`, capture dangerous pawn
    `4/4`.

## Optimization Notes

- A broad "avoid threefold" attempt was rejected because it converted five
  draws into five checkmate losses.
- A broad dangerous-pawn capture rule was narrowed after it changed one
  attacking win into a material-cap draw. The retained version only handles
  pawns one move from promotion.
- The replay prior is intentionally limited to exact downloaded-template
  positions and to the first 12 full moves; it is an opening prior, not a
  general engine override.
- The `40/40` score includes two new trap-response cases because the earlier
  chess suite had no trap-response coverage; this is a coverage expansion, not
  a pure same-denominator comparison against the previous `35/40`.
- The holdout probe is intentionally reported separately from the main score to
  reduce train/test leakage. Passing it is not proof of engine-level play, but
  it checks that the mate and capture rules generalize across mirrored and
  related positions.

## Remaining Risk

This is now a meaningful practical-strength upgrade for the tested surface, but
still not an engine-grade opponent. The next meaningful improvements should be:

- winning-plan conversion after reaching non-losing middlegames;
- deeper king-safety terms;
- larger tactical regression set with forks, pins, skewers, and mate nets.
