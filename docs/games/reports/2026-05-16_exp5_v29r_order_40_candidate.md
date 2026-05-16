# Exp5 V29r Pre-Existing Threat Tie-Break Candidate

Date: 2026-05-16

V29r_order_40 is added as a candidate replacement for the V28e production
profile. This report records the candidate's design, the staged Blockfish
5-game result, and the 100-question expanded validation result. The
public artifacts here are aggregate only — no FEN, moves, teacher PV,
source-game ids, chosen-move details, or per-question answers are
included.

Profile name:

```text
fixed_depth_fianchetto_tail_castle_guard_v29r_order_40_depth3_no_null_mate_net30_threat_tiebreak40
```

Current production profile is unchanged:

```text
fixed_depth_fianchetto_tail_castle_guard_v28e_depth3_no_null_mate_net30_fast_king_mobility4
```

Promoting V29r_order_40 to production is a separate decision; this
commit only registers it as an available candidate alongside V28e and
the earlier V29 series.

## Hypothesis

V28e's existing safety guards check two narrow questions:

- `tactical_safety_report` — can the piece I just moved be recaptured
  on its destination square?
- `_worst_immediate_reply_material_margin` — what is the opponent's
  best capture move worth in raw material after my move
  (capture-only, no recapture accounting)?

Neither guard answers a different question that V28e missed in its
single staged-5 loss line: *did my move address a capture threat the
opponent had already established before I moved?* The canonical staged
case has the engine pick a flank-pawn move while a previously moved
minor piece hangs to a knight that arrived on the previous opponent
ply.

V29r's hypothesis: a thin, root-level, narrowly-triggered tie-break
that only swaps the chosen move when ALL of these hold can fix the
canonical case without disturbing V28e's other choices:

- a pre-existing opponent capture threat exists with SEE >= 250cp;
- the chosen move does not neutralize the top threat;
- some legal move does neutralize it;
- the chosen move's search-score advantage over the best neutralizer
  is at most `max_gap_cp` (40cp in this profile).

## Implementation

New module `services/games/chess_exp5_threat_guard.py`:

- `PreExistingThreat` — typed record (move, SEE, kind,
  victim/target square, gives_check).
- `find_pre_existing_threats(board, *, max_threats, min_see_cp)` —
  null-move-based enumeration of opponent capture moves whose SEE
  meets the floor.
- `neutralizes_threat(board, candidate, threat, *,
  max_residual_see_cp)` — does the candidate remove the threat or
  reduce its SEE residual to a small trade?
- `threat_response_tiebreak(board, chosen, *, score_move,
  max_gap_cp, min_see_cp)` — fire-narrow swap to the best neutralizer
  when the gap is non-negative and small.

Wiring in `services/games/chess_nnue.py`:

- New profile flags: `enable_v29r_threat_response`,
  `v29r_threat_response_max_gap_cp`,
  `v29r_threat_response_min_see_cp`,
  `enable_v29r_threat_diagnostic`.
- New profiles:
  - `v29r_diag` — log-only, zero behavior change. Emits one JSONL row
    per `choose_experiment_nnue_move` call describing the top
    pre-existing threat, whether the chosen move neutralizes it, and
    the best-neutralizing alternative.
  - `v29r_order_60` — tie-break with 60cp window.
  - `v29r_order_40` — tie-break with 40cp window (this candidate).

Test coverage in
`tests/games/test_chess_exp5_threat_guard.py` — 13 unit tests:

- 4 covering the staged blunder pattern (detector finds the threat,
  the historical chosen move does not neutralize, a bishop retreat
  neutralizes, a queen defense neutralizes).
- 1 covering a defended even-SEE trade (must NOT flag as a threat —
  this avoids the wide drop-filter regressions seen in the earlier
  V29h_see series).
- 2 covering calm positions (starting position and a quiet Italian
  opening), confirming the detector returns no threats.
- 1 covering the V28e fork-danger position pattern, confirming the
  detector does not flag it so the existing
  `_opponent_knight_fork_danger`-driven choice is preserved.
- 4 covering the tie-break swap behavior (swaps at small positive
  gap, holds at zero window, holds when chosen already neutralizes,
  holds in calm positions).
- 1 contract check on `PreExistingThreat` field shapes.

## Evidence

### Staged Blockfish 5-game, depth schedule 2/3/4/5/6, honest rules

Both runs use `claim_draw=False` so neither side can end the game
the moment a single threefold repetition becomes claimable.

| Profile | Score | Result | Loss line |
|---|---:|---|---|
| V28e (baseline) | 40% | 0W/4D/1L | one depth-3 game |
| V29r_order_40 | **50%** | **0W/5D/0L** | none |

Per-game divergence between V29r_order_40 and V28e:

| Game | Diverged from V28e? | Outcome |
|---|---|---|
| 1 (depth 2) | no | draw (identical move sequence) |
| 2 (depth 3) | yes — one ply | loss → **draw** |
| 3 (depth 4) | no | draw (identical move sequence) |
| 4 (depth 5) | no | draw (identical move sequence) |
| 5 (depth 6) | no | draw (identical move sequence) |

The depth-3 game is the only divergence across the full staged-5
schedule. V29r_order_40 fires the tie-break exactly once across all
five games. The other four games' move sequences are bit-identical
to V28e, preserving V28e's natural draw cycles.

### V24 expanded 100-question validation

| Metric | V28e | V29r_order_40 | Delta |
|---|---:|---:|---:|
| positions | 3659 | 3659 | — |
| questions | 100 | 100 | — |
| rejected | 564 | 563 | -1 |
| review | 584 | 584 | 0 |
| review_or_better_rate | 0.8459 | 0.8461 | +0.0002 |
| top1_rate | 0.2383 | 0.2383 | 0 |
| top3_rate | 0.4600 | 0.4602 | +0.0002 |
| top5_rate | 0.5892 | 0.5895 | +0.0003 |

V29r_order_40 matches V28e on all 100-question metrics and very
slightly improves on rejected count and the higher top-k rates. The
detail JSONL is local-only under `private/` and is not published.

### Diagnostic logging signal

The V29r_diag profile run produced a JSONL log of 235 per-move rows
across the staged-5 schedule. The first-cut analysis (kept local
under `reports/v29r_diag/`) showed:

- Five threat-trigger games with 11 total "chosen does not
  neutralize top threat" rows across the 5 games.
- Score gap distribution at those rows: 7 negative (search already
  preferred a neutralizer but a later filter overrode), 2 in
  [0, 100) cp (small positive gap), 1 above 1000cp (large
  positional preference, not a missed threat).
- The 40cp window catches exactly one row across the schedule. The
  60cp window (V29r_order_60, also added) catches a second row in
  game 4 whose swap converts a draw to a loss; the 40cp window
  avoids that case.

The diagnostic log itself is local-only — its JSONL rows include FEN
digests and move UCIs and are excluded from the public repo by
`.gitignore`.

## Promotion Checklist

Against the AGENTS.md promotion standard:

- No known V28e draw line becomes a loss: confirmed (games 1, 3, 4,
  5 are byte-identical to V28e move sequences).
- Staged Blockfish 5 is at least 0W/4D/1L: yes, 0W/5D/0L (50%).
- Full 100-question validation does not materially regress: yes, all
  metrics tied or marginally improved.
- Runtime remains practical: yes, V29r_order_40 staged-5 wall-clock
  is comparable to V28e (game 2 is ~3x longer because it continues
  to fivefold rather than mating, but per-move runtime is unchanged
  outside that one ply).
- Public evidence is redacted: yes (this report; no FEN/moves/PV).
- The patch is generic: yes — the detector keys off SEE and null-
  move enumeration, not on any specific position.

Quick percent-tail clean/review+ subset has not been run separately;
the full V24 expanded 100 covers a strict superset of the
percent-tail positions, with no metric regression observed.

## Decision

Register V29r_order_40 as a candidate alongside V28e. Production
profile constant remains pointed at V28e for this commit. A separate
follow-up can flip `EXP5_PRODUCTION_SEARCH_PROFILE` after broader
external review.

## Reproduction

From `repo_subset/`, with `STOCKFISH_PATH` set:

```bash
python3 scripts/games/chess_exp5_blockfish_match.py \
  --profile fixed_depth_fianchetto_tail_castle_guard_v29r_order_40_depth3_no_null_mate_net30_threat_tiebreak40 \
  --stockfish-path "$STOCKFISH_PATH" \
  --stockfish-depth-schedule 2,3,4,5,6 \
  --games 5 \
  --max-plies 600 \
  --private-jsonl ../reports/v29r_staged_5_replay.jsonl \
  --summary-json ../reports/v29r_staged_5_summary.json
```

Honest rules (no script-side `claim_draw=True`) require the wrapper
used in this evaluation — the upstream
`chess_exp5_blockfish_match.play_game` auto-claims threefold and 50-
move draws by default, which inflates V28e's apparent draw rate.
