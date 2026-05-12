# What exp3's replay format gets right (and where exp5 reproduces its mistakes)

Date: 2026-05-11
Source artefacts:
- `docs/games/chess_debug/chess_replays_exp3_example.jsonl` (one full game record)
- `services/games/chess_replay_buffer.py:62-287` (how a replay row gets its
  `confidence_score`, `collection_tier`, `quarantine_reasons`)
- `scripts/games/chess_replay_prepare.py:88-155` (how a replay row becomes a
  per-move training sample)
- `scripts/games/chess_exp5_teacher_distill.py` (the exp5 distill pipeline)

## The exp3 example in one paragraph

The example file is **one game** where exp3 (white) lost to a human (black)
in 26 moves by checkmate. exp3 (white) played `Bxc6` early, then trotted
its king up the board (`Ke1→e2→d3→c4→b3`) into mate. The record carries
`confidence_score=0.42`, `collection_tier=trusted`,
`adjudicated_or_natural=natural`, `move_count=26`, `winner_color=black`,
`source=user_games` (implicit via the 0.42 base), with the full 26-move
history attached.

What we are going to extract from this file is **not** "exp3 plays badly"
(it does; the king walk is a textbook failure). The interesting part is
**how the record was structured** — because the structure encodes which
samples will be trusted, which will be quarantined, and how each sample
will be weighted at training time. That structure is what exp5 currently
lacks and is the root cause of why exp5_04 trained on label noise.

## What exp3 records per game (and exp5 does not)

| field in `chess_replays_exp3_example.jsonl` | meaning | exp5 distill row equivalent |
|---|---|---|
| `replay_id` (sha256 fingerprint) | stable id for dedup + deterministic train/eval split | **missing** |
| `collection_tier` ∈ {`trusted`, `quarantine`, `rejected`} | which ledger this row belongs to | **missing** |
| `confidence_score` ∈ [0, 1] | per-record trust scalar; flows into per-sample `weight` | **missing** (all rows hard-coded `weight=1.4`) |
| `source` ∈ {`benchmark`, `teacher_guidance`, `self_play`, `imported_dataset`, `external`, `user_games`} | provenance category, used to scale weight | only a free-form `"source"` string (`"exp18_train"` in our case) |
| `suspicious_flag` (bool) + `quarantine_reasons` (list) | per-record audit of why it might be bad | **missing** (suspicious rows are silently dropped) |
| `winner_color` + `result_reason` | outcome anchor used to derive `target` | **missing** (no game outcome — distill is from isolated positions) |
| `adjudicated_or_natural` | whether result came from a real game-over or a max-ply cutoff | **missing** |
| `move_history` (full ordered list) | gives `source_move_index`, lets prepare-step regenerate FEN deterministically | **missing**; exp5 distill rows are isolated positions with no causal context |
| `opening_seed` | so split bucket is reproducible | **missing** |
| `duplicate_signature` / `duplicate_flag` | global dedup across runs | partial; exp5 distill has `duplicate_ratio` in the summary but not a row-level fingerprint |

## What exp3 does at sample-generation time

`scripts/games/chess_replay_prepare.py:99-104` derives a per-move target:

```python
def _move_target(move_side, winner_color, *, include_losing_moves):
    if winner_color in {"white", "black"}:
        if move_side == winner_color: return 1.0
        return -0.2 if include_losing_moves else None
    return 0.15  # draw
```

And `_source_weight` (line 88-96) maps:

```python
weight = clip(confidence_score
              × (0.35 if from_quarantine else 1.0)
              × (0.8  if adjudicated else 1.0)
              × (1.2  if source in {"teacher_guidance","benchmark"} else 1.0),
              [0.1, 2.5])
```

So one game with `confidence_score=0.42` produces:
- **only winning-side moves** become positive samples (target=+1.0)
- **each positive sample has weight ≈ 0.42 × 0.8 = 0.34** (low — because this
  is `user_games` which exp3 already distrusts)
- losing-side moves are **dropped unless** `--include-losing-moves` is passed
  (then target=−0.2 with the same low weight)
- whole game goes to **train or eval** by hashing `replay_id` modulo
  `eval_mod` — no row leaks across the split

## What exp3 does AT INGEST time (and exp5 still doesn't)

`chess_replay_buffer.py:255-287` runs every incoming game through a
tiered classifier:

```
tier = trusted (default)
if move_count <= 0                     → rejected (empty_history)
if user_games and move_count < 2       → rejected (too_short)
if user_games and (duplicate OR resign_abuse OR suspicious OR move_count<6)
                                       → quarantine
if external/imported and suspicious    → quarantine
```

Quarantine rows go to a **parallel file** (`chess_replays_quarantine.jsonl`)
— they are not discarded. The `chess_replay_prepare` step can opt-in to mix
quarantine back at 35% weight (`--include-quarantine`), and the quarantine
ledger remains as an audit trail.

The exp5 distill pipeline before exp5_05b had **no tier**. Suspicious
teacher moves were dropped silently via `return None`. That meant we lost
the chance to audit *why* a row was dropped and how many were dropped.

## The structural failure pattern visible in the exp3 example

The exp3 game itself looks like a feedback-loop failure:

1. The exp3:dl model was trained predominantly on `user_games` (base
   `confidence_score=0.42`). Per-sample weights end up around 0.34.
2. The winner-takes-all label policy (`target=+1.0` for every winner move,
   skip the loser) reinforces *all* moves a winner made — including moves
   that were tactically bad but went unpunished.
3. When the same model later plays as white, it reproduces the kind of
   weak moves that previous winners punished — because the loser's
   moves were never seen as negatives.
4. The king-walks-out behaviour (`Ke1→e2→d3→c4→b3` ending in mate) is
   the visible symptom: there is no per-position labelling of "king
   safety violated", only "winner won, so all winner moves were good".

The mitigation in exp3 is **per-source weight scaling + outcome-grounded
labels**. The trust scalar (0.42 for user_games vs 0.95 for
teacher_guidance vs 0.98 for benchmark) keeps the model from being
dragged too far by weak data. But the weakness of the supervision signal
(winner-takes-all) remains.

## How exp5 reproduces (or avoids) the same mistakes

### Mistakes exp5 has *already* fallen into (and the fix already shipped)

| exp3 lesson | exp5_04 state | exp5_05b state (now) |
|---|---|---|
| Per-record confidence_score gates how much a row is trusted | Every distill row had hard-coded `weight=1.4` regardless of evidence | Distill row now carries `label_quality ∈ {clean, review, questionable}`, `label_quality_reason`, `baseline_policy_gap_cp` |
| Quarantine ledger preserves suspicious rows | Suspicious teacher rows dropped silently via `return None` | `--audit-jsonl` writes every row including dropped ones, with `included_in_output=false` and `drop_reason` |
| Tier classification gates ingestion | No tier system | Three-tier clean/review/questionable with thresholds (`--label-quality-far-above-cp`, `--label-quality-review-cp`) |
| Suspicious flag for self-repeating play (`_suspicious_flag` 6-move loops) | None — exp5 just trusts the teacher | `questionable_by_baseline_policy_gap` flag based on baseline policy gap |

### Mistakes exp5 is *still* making after exp5_05b

| exp3 lesson | exp5 status (after 05b) | What still needs to be done |
|---|---|---|
| `weight` derived from `confidence_score × source_multiplier`, clipped to [0.1, 2.5] | Distill rows still emit hard-coded `weight=1.4`. `label_quality` is recorded but not yet flowed into the trainer's per-sample weight. | Make `chess_exp5_dataset_train.py` honour `label_quality` (`clean`→1.0×, `review`→0.4×, `questionable`→0× if `--drop-questionable` not used). |
| Game-outcome anchor on every sample | exp5 distill is from isolated FENs; there is no game outcome. The teacher used (`choose_teacher_move`, depth=3 static eval) is itself a weak signal. | Either (a) play self-play from each distill position to outcome and use outcome as a secondary target, or (b) explicitly downgrade `confidence` for rows whose `baseline_policy_gap_cp` is large (already done as `label_quality`) and **stop calling them ground truth**. |
| `replay_id` (sha256 fingerprint) per record + deterministic train/eval split via `hash(replay_id) % eval_mod` | exp5 has no replay_id, and the train/eval split in exp5_03 was done by **side-flipping the strength cases** to manufacture held-out rows — that is not a true held-out split. | Add `position_id = sha256(normalized_fen + side)` per distill row. Use `hash(position_id) % eval_mod` to split. Side-flip held-out is fine as an *additional* synthetic eval, but should not be the primary held-out. |
| Source provenance: `benchmark`/`teacher_guidance`/`self_play`/`imported_dataset`/`external`/`user_games` with calibrated trust floors | exp5 distill rows carry free-form `source="exp18_train"`; the trainer treats every source identically | Categorise upstream FEN files into the exp3 categories and propagate `source_category` + a default `confidence_score` per category. |
| Per-move sample carries `replay_id`, `source_game_id`, `source_move_index`, `source_stage` | exp5 distill samples have none of these | Add the same provenance fields so any post-hoc audit can trace a sample back to its origin file/line/round. |
| Quarantine ledger written to a parallel jsonl file | exp5_05b only writes a combined audit jsonl; quarantine rows are not in a separately-named file | Add `--quarantine-jsonl` output so future `chess_replay_prepare`-style steps can opt-in to mix quarantine back at reduced weight, instead of either taking everything or dropping everything. |
| `_suspicious_flag` catches self-repeating move patterns (6-move loops of ≤2 unique moves) | exp5 doesn't check for any pattern-level pathology in its training data | Not directly applicable (distill is per-position, not per-game), but the equivalent for distill is: **flag rows whose teacher_move appears in `teacher_top3` 0 times** — exp5_05b records this as `teacher_top3_does_not_contain_teacher_move_count = 40/60`, but does not yet act on it. Promote that to a hard exclusion or weight-zero rule. |

### What the king-walk failure says about exp5

The exp3 game shows the cost of training on weak labels: the model
*looks* like it's learning (its weight file changes, the trainer reports
samples accepted) but it never internalises "do not walk the king into
the open." exp5 has the exact same risk pattern:

- exp5_04 saw `train_agreement_delta` rise to +0.0833 under `epochs=8`
  with the dirty `exp18_train` distill. We *can* make exp5 follow the
  teacher more closely. But under fixed_depth_strong, the candidate's
  actual `score_delta = −0.0167` — the model learned the labels but
  the labels weren't useful.
- The 60 distill rows had 48/60 `questionable_by_baseline_policy_gap`
  and 40/60 with `teacher_move ∉ teacher_top3` (teacher's own static
  eval doesn't rank its choice in top-3). That is exp5's equivalent of
  "winner's bad moves got target=+1.0" in exp3 — except exp5 has no
  outcome data even as a sanity check.

If exp5 keeps shipping the same shape of pipeline (hard-coded
`weight=1.4`, no tier, no outcome anchor, no replay_id), then any
"learning visible" result will be uninformative in the same way exp3's
king-walking model was uninformative: weights moved, but in a direction
that *cannot* generalise because the labels can't be cross-checked
against an independent oracle.

## Concrete next-step recommendations (priority order)

1. **Flow `label_quality` into the trainer's per-sample weight.**
   Smallest, safest change. In `chess_exp5_dataset_train.py`, multiply
   each sample's `weight` by:
   - 1.0× when `label_quality == "clean"`
   - 0.4× when `label_quality == "review"`
   - 0.0× when `label_quality == "questionable"` (i.e. positive update
     is skipped, but the row may still be used as a *hard-negative
     source* for *other* rows because the candidate's top-1 here is
     probably better than the teacher's choice).
   This costs nothing and stops exp5_04-style label-noise training.

2. **Add `position_id` + deterministic eval split.** Use
   `hashlib.sha256(normalized_fen + side).hexdigest()` as the per-row
   stable id. Add an `--eval-mod 5` flag to the distill step. Hold-out
   rows are then real held-out, not side-flipped synthesis.

3. **Categorise upstream FEN sources and propagate per-source
   `confidence_score`.** Mirror exp3's `_confidence_score` table:
   benchmark 0.98, teacher_guidance 0.95, self_play 0.9,
   imported_dataset 0.88, external 0.75, user_games 0.42. Right now
   `exp18_train` is treated identically to a benchmark-quality source;
   it almost certainly belongs in `external` (0.75) or even lower.

4. **Split quarantine to a separate file.** Easy follow-up to
   exp5_05b's audit-jsonl: add `--quarantine-jsonl` and write rows with
   `label_quality == "questionable"` there. Lets a future
   `chess_replay_prepare`-equivalent opt-in to a 35%-weight quarantine
   re-mix.

5. **Add an outcome anchor via self-play.** For each distill FEN, play
   N self-play games from that position. Use the outcome as a secondary
   target. Rows where self-play diverges (no stable outcome) get
   `label_quality_reason="self_play_inconclusive"` and are downweighted.
   This is the largest piece of work; it brings exp5 in line with exp3's
   game-outcome supervision.

6. **Stop calling the depth-3 static teacher "ground truth" in docs.**
   It is a label *proposal*, not a label *verdict*. The label-quality
   audit is the verdict. This is a wording change in the exp5 docs but
   it matters: every promotion report that says "teacher distill"
   should also say "with baseline-policy-gap quality filter applied."

## Bottom line

exp3 had a noisy supervision signal (winner-takes-all) but compensated
with a structural pipeline: confidence scalars, tier ledgers, quarantine
audit, deterministic splits, per-source weights. The king-walking
behaviour visible in the example game shows the failure mode you get
*even with* that pipeline if the teacher signal is too weak.

exp5 currently has a weaker supervision signal (depth-3 static teacher
on isolated FENs, no game outcome) AND fewer structural safeguards.
exp5_05b started fixing the structural side (label_quality, audit
jsonl, drop filter); items 1-6 above are what's still needed before
exp5 can avoid producing its own equivalent of the king walk.

If we ship exp5_05c with the same `epochs/topK` knobs but without
items 1, 2, 3, we will see exactly the same outcome: the model learns
the labels, the gate moves a little (in either direction depending on
search noise), and we will not be able to defend the result.
