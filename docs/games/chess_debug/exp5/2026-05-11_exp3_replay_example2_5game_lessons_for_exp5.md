# Five exp3 games: a reproducible pattern of structural failure

Date: 2026-05-11
Source: `docs/games/chess_debug/chess_replays_exp3_example2.jsonl` (5 records)
Companion: `2026-05-11_exp3_replay_format_lessons_for_exp5.md` (1-record analysis)

## What's new vs the 1-game example

The first example showed a single king-walk loss. Example2 shows the same
failure mode across **5 independent games** — so the failure is structural,
not accidental. All 5 games are recorded as `confidence_score=0.42`,
`collection_tier=trusted`, `source=user_games`, `suspicious_flag=false`,
`quarantine_reasons=[]`. The ingest pipeline catches **none** of the
patterns visible by inspection.

## Per-game extracted facts

| g | mc | result | exp3_side | exp3_castled | first_K_move_ply (exp3) | rim_N_ply (exp3) | user_castled | suspicious_flag |
|---|----|--------|-----------|--------------|--------------------------|------------------|--------------|------------------|
| 1 | 39 | checkmate | black | **No** | **8**  | – | No | False |
| 2 | 23 | checkmate | black | **No** | **14** | – | No | False |
| 3 | 27 | resign    | white | **No** | **21** | – | No | False |
| 4 | 24 | checkmate | white | **No** | **19** | – | No | False |
| 5 | 20 | checkmate | white | **No** | **15** | **7** (Ng1-h3) | No | False |

`mc` = move_count (plies). `first_K_move_ply` is the half-move number at which exp3
moved its king from its starting square (e1 or e8) by a non-castling move.

Two failure invariants jump out immediately:

- **exp3 never castles in any of the 5 games** (0 / 5).
- **exp3 moves its king from e1/e8 in the first 21 plies of every game**, four of
  five times within plies 8-19 — well before any king-safety concern would
  justify it.

The pattern from example1 (one game ended `Ke1→e2→d3→c4→b3` mate) is
reproduced in example2 as a generalised tendency: exp3 has no internal
incentive to either castle or keep the king on the back rank.

## Game 3 — silent resign abuse the existing flag misses

Game 3 ended in **resign at move 27** with `winner=white`. Re-applying the
moves and computing material:

```
Position after 27 plies (black to move, then resigned):

r . . . k b n r
. . . . . . p p
p . . . . . . .
. . . . N . . .
. . P . . . . .
. . . . . . . .
P . . P K P P P
n N B . . . . R

White material (pawn=1, N=B=3, R=5, Q=9): 20
Black material:                            22
```

Black is **+2 in material** at the moment of resigning. (Black just lost a
queen to Nxe5xq, but still has R+R+B+N+3P+K vs. White's R+N+B+5P+K.)
Whether the position is actually losing for black depends on tactics
(black's a1-knight is trapped, white king on e2 is exposed) — but the
exp3 pipeline doesn't run any eval check before deciding the game is
trusted. The check it does run is:

```
resign_abuse_flag = (source == "user_games") AND (result_reason == "resign") AND (move_count < 8)
```

`move_count = 27 >= 8`, so the flag stays `False`. The game enters
`trusted` tier and contributes user-side moves at weight 0.34 to the
training set. This is exactly the kind of label noise we already saw
poisoning exp5_02 distill.

## Why suspicious_flag missed everything

`chess_replay_buffer._suspicious_flag` triggers on:

- `move_count < 4`
- `result_reason == "resign" AND move_count < 8`
- A 6-move loop of ≤ 2 unique moves

None of the 5 example2 games are short, none are early-resign by the
move-count rule, none are loops. The flag is a *thin* heuristic; it
cannot see "this side never castled" or "this side moved its king at
ply 8". The 5/5 false-negative rate here matches example1.

## The training-loop implication

`chess_replay_prepare._move_target` only takes **winner-side** moves as
positive samples (target=+1.0). Loser-side moves are skipped unless
`--include-losing-moves` is passed (then target=-0.2). Of the 5 games:

- 4 games: exp3 lost → exp3's own moves are skipped → exp3 NEVER receives
  a negative signal for "don't move king to e2 on move 14".
- 1 game (game 3): exp3 won by user resign. exp3's moves get target=+1.0
  weight ~0.34. The moves include `Pe2-e4 Pe4xd5 Pxc6 c3 b4 Bxa6 Pc4 Qa4 Qxd7 Nf3 Ke2`
  — including the **king move Ke2 at ply 21**. So Ke2 gets reinforced as
  a positive sample.

So under exp3's pipeline, the bad pattern is either invisible (loser
moves skipped, no negative signal) or actively reinforced (game 3
"winning" exp3 walked the king and got rewarded for it). This is a
**self-trapping training loop**: structural failures recur because
they're never penalised, and one accidental win cements them.

## Mapping the example2 lessons onto exp5

| exp3 example2 failure | exp3 has? | exp5 (current state after 05a/05b/05c) has? | gap |
|---|---|---|---|
| **Never castles** | No protection — model converges away from O-O | exp5_05c special-rule gate confirms baseline castles 1/4 cases. Same failure mode. | Gate now *detects* it; trainer has no castling-aware loss term. |
| **King moves out by ply 10-20** | Only checks check & post-castle squares | exp5 `_king_safety_score` only rewards king on g1/c1/g8/c8 + penalises is_check. Doesn't penalise an exposed e2 king. | Need a "king moved from starting square in plies ≤ N" feature/penalty. |
| **Knight to rim early** | Not flagged | `_move_order_score` actually penalises a `KNIGHT/BISHOP on rank 0/7 moving` by `score -= 500` — that's *encouraging* moves AWAY from back rank, not blocking moves TO the rim like `Ng1→h3`. | The existing exp5 move-order bonus does not deter `Ng1-h3`. |
| **Resign while material-up** | `_suspicious_flag` only checks `move_count < 8` | Not addressed at all in exp5 | Need eval-aware resign validator (`resign-policy audit`). |
| **5/5 games trusted, none flagged** | Heuristic is too thin (3 rules) | exp5_05b adds `label_quality` based on per-row baseline policy gap — but at the **POSITION** level for distill rows, not at the **GAME** level for replays | Need a game-level suspicious-pattern check for any future replay-based exp5 training data. |
| **Loser moves skipped, no negative signal** | exp3 has `--include-losing-moves` flag (off by default) | exp5 has auto-hard-negative-topk that targets the candidate's currently-preferred moves | exp5 is structurally better here — but it sources negatives from the candidate's policy at distill time, not from the loser's actual game choices |
| **Game-3 "winning by opponent's resign" reinforces bad moves** | `winner_color → target=+1.0` is unconditional | n/a (exp5 distill is per-position, no game outcome) | If exp5 ever ingests game replays, must require `eval(losing side) <= -300cp` at resign before treating winner moves as positive. |

## Concrete additions for exp5 (beyond the items already proposed)

These are **on top of** the items 1-6 in
`2026-05-11_exp3_replay_format_lessons_for_exp5.md`. The numbering
continues from there:

7. **Game-level pattern audit** (new module — applies whenever exp5 ingests
   replays in the future):

   - `pattern_never_castled` — if castling rights existed for ≥ 10 plies
     after the game started and the player never castled.
   - `pattern_early_king_move` — first non-castling king move from
     starting square occurred before ply 20.
   - `pattern_rim_knight_early` — `Ng1→h3 / Nb1→a3 / Ng8→h6 / Nb8→a6`
     within first 10 plies.
   - `pattern_queen_for_minor_early` — queen captured a minor piece
     before ply 12 without compensation.

   Any of these patterns → `quarantine_reasons.append(pattern_name)` →
   `collection_tier = "quarantine"`. Quarantine writes to a separate
   ledger (already implemented via `--quarantine-jsonl` in
   `chess_exp5_teacher_distill.py`).

8. **Eval-based resign validator** (in `chess_replay_buffer` for
   ingestion + as a standalone audit for any existing replay file):

   - When `result_reason == "resign"`, evaluate the position just before
     the resign with the deterministic `fixed_depth_strong` profile.
   - If `eval(resigning_side) >= -300cp` AND no mate-in-≤5 against
     resigning side, flag `resign_questionable` and quarantine the row.
   - This catches example2 game 3 (resign at ply 27 with black up
     +2 material).

9. **Negative-sample mining from loser moves with eval drop**:

   - Replay each loser's move with a fixed-depth eval before and after.
   - If `eval_after_loser_move - eval_before_loser_move <= -200cp` (a
     blunder), add the move as a **hard negative** in the position
     it was played from.
   - This is the exp5 equivalent of `--include-losing-moves` but
     targeted: only blunders, not every loser move.

10. **Add king-on-starting-square penalty after move 12** to the NNUE
    eval (`_king_safety_score`):

    - For king side: white K on e1 after move 12 → `score -= 0.5 *
      king_safety_weight`. Symmetric for black.
    - Reward growing not just for K on g1/c1 but for K on any of {g1,
      h1, g2, h2, c1, b1, c2, b2} (any post-castle haven).

11. **Bake castling-cluster into the standard strength gate**:

    - The `chess_exp5_special_rule_gate.py` shipped in exp5_05c is
      auxiliary. Promote `castling_cluster_score >= baseline_score`
      to a **hard requirement** of the regular `chess_exp5_strength_gate.py`.
    - Rationale: example2 shows zero castling across 5 games is a
      *consistent* failure mode of cheap evals, not noise. Letting a
      candidate ship without passing it perpetuates the loop.

## Connection to exp5_05c findings

exp5_05c showed that on the 12-row clean+review distill set, no
configuration could produce a positive `score_delta` under
`fixed_depth_strong`. The example2 analysis adds context: even if we
clean the distill labels perfectly, we have nothing in the training
target that teaches the model to castle or keep the king back.
Castling appears in distill rows only if the teacher *chose* castling
for that position, and our 1-ply static teacher has no horizon to
appreciate king safety. So future label cleanups can't fix castling.

For king safety we have to either:

- Add an explicit eval term (item 10 above), or
- Synthesise castling-pattern training data (item 11 of the
  exp5_06-and-beyond plan: e.g. positions where castling is the only
  move that avoids losing the king on the next ply).

Either way, the example2 evidence says: even a perfectly-supervised
exp5 on 60 / 120 / 500 isolated FENs will reproduce the exp3 failure
unless the eval surface itself penalises early king exposure.

## Bottom line

Example1 said: "a single weak supervision signal causes one game to
fail dramatically." Example2 says: "the same supervision signal,
applied across many games, produces a *reproducible* structural
failure that none of exp3's existing flags catch." The fix is not
data cleanup alone (exp5_05b/c already shows that's necessary but not
sufficient); the fix needs:

1. **Game-level pattern detection** at ingest (item 7).
2. **Eval-based resign validation** (item 8).
3. **Negative samples from loser blunders** (item 9).
4. **King-safety eval upgrade** (item 10).
5. **Castling cluster as a hard gate requirement** (item 11).

Items 7-9 protect future replay ingestion. Item 10 is a model-eval
change (touches `chess_nnue._king_safety_score`). Item 11 only edits
gate policy — cheapest to ship and the most defensible
"don't-make-the-exp3-mistake-publicly" guard for the next promotion
attempt.

Files: `docs/games/chess_debug/exp5/2026-05-11_exp3_replay_example2_5game_lessons_for_exp5.md` (this file).
