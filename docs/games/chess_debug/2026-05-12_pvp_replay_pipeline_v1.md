# PvP / human-vs-engine replay pipeline v1 (2026-05-12)

## Scope

`pvp_replay v1` lands four pieces that let real-player game history feed into
exp4 / exp5 warm-up **offline**:

| Step | Artifact |
|---|---|
| **W6** | `bootstrap.schema.sql` baseline now allows `computer_difficulty='experiment 5:nnue'` (runtime ensure-schema migration was already wired by the prior commit; this aligns the fresh-install baseline). Drift-check test prevents future desync. |
| **W1+W3** | `scripts/games/chess_pvp_history_to_replay.py` — offline converter with built-in filter; emits canonical replay JSONL under `~/chess_results/pvp_replay_<timestamp>/`. |
| **W4** | `scripts/games/chess_seed_train.py --include-replay-jsonl PATH` + `--dry-run` + per-source caps + new trusted_source whitelist. |
| **docs** | This file. |

## What v1 explicitly does NOT do

- ❌ **No PvP finish-hook**: nothing in `routes/games.py` triggers a converter
  / trainer when a match transitions to `status='finished'`. Conversion is
  strictly a human-invoked offline job.
- ❌ **No cron / startup auto-train**: warm-up only runs when you call
  `chess_seed_train.py` yourself.
- ❌ **No production runtime mutation outside the manual warm-up call**: the
  converter writes only under `~/chess_results/pvp_replay_<ts>/`. The warm-up
  call writes to model paths you pass via `--experiment-4-model-path` /
  `--experiment-5-model-path` (or bundled paths if you omit them — same as
  before this PR).
- ❌ **No raw-PvP-as-positive-training-data**: every accepted sample passes
  through the filter and is tagged `label_quality` ∈ {clean, review} with
  weight ≤ 0.20.
- ❌ **No teacher-audit gate**: v1 trusts winner-side moves at face value once
  the match passes filter. v2 will add `teacher_audit_status` enforcement.
- ❌ **No hard-negative mining**: loser-side moves are dropped (not collected
  as target=0.0 examples). Without teacher audit, loser moves cannot be
  reliably labelled as bad.

This is the v1 contract because raw human game history is a real-distribution
signal but not naturally teacher-quality data. See
[[feedback-pvp-replay-discipline]] in memory for the discipline rationale.

## Pipeline

```text
game_matches  (DB, written by routes/games.py during normal play)
    │  mode IN ('pvp','computer'), status='finished'
    ▼
chess_pvp_history_to_replay.py  (W1+W3, offline, manual invocation)
    │
    ├─ pvp_replay_candidates.jsonl       (every parsed match + filter outcome)
    ├─ pvp_replay_training_eligible.jsonl (per-ply samples passing all gates)
    ├─ pvp_replay_rejected.jsonl         (matches dropped + rejection_reason)
    ├─ summary.json
    └─ SUMMARY.md
    │
    ▼  human review of candidates / rejected to validate filter behaviour
    │
chess_seed_train.py
  --preset warmup10
  --include-replay-jsonl <pvp_replay_training_eligible.jsonl>
  --include-replay-jsonl <imported_pgn_prepared.jsonl>      (optional)
  --include-replay-jsonl <sparring_objective_hit.jsonl>     (optional)
  [--dry-run]
    │  loads, validates trusted_source whitelist, downsamples
    │  per-source + total cap, then trains exp4 PV + exp5 NNUE.
    ▼
exp4 PV model  +  exp5 NNUE model  (updated in place at the paths you passed)
```

## Two harvest paths (W1+W3)

The converter recognises two filter outcomes:

### pvp_filtered

| Field | Value |
|---|---|
| trusted_source | `pvp_filtered` |
| source | `pvp` |
| label_quality | `review` |
| weight default | 0.15 (cap 0.20) |
| Gate | mode='pvp', both players in last 4 weeks leaderboard top 30% |

### human_beat_engine

| Field | Value |
|---|---|
| trusted_source | `human_beat_engine` |
| source | `human_vs_engine` |
| label_quality | `clean` (higher than pvp_filtered) |
| weight default | 0.20 (cap 0.25) |
| Gate | mode='computer', `winner_user_id == white_user_id` (human won), human in quality set |

Both paths collect only **winner-side moves** as `target=1.0` (loser side is
discarded). Both require:
- `status='finished'`
- `winner_user_id` not null
- `result_reason ∉ {timeout, abandoned, disconnect, resign_too_early, cancelled}`
- `plies >= 20`
- `move_history_json` reconstructs legally via python-chess

## Trusted-source whitelist (W4)

`chess_seed_train.TRUSTED_SOURCE_WHITELIST`:

| trusted_source | default cap | typical use |
|---|---|---|
| imported_dataset | 200 | `chess_pgn_to_replay.py` PGN master/elite import |
| teacher_guidance | 200 | teacher-distilled samples |
| benchmark | 100 | benchmark-derived clean samples |
| external | 100 | catch-all external dataset |
| **pvp_filtered** | 100 | W1 output, PvP path |
| **human_beat_engine** | 100 | W1 output, human-beat-engine path |
| **sparring_objective_hit** | 50 | future: sparring artifacts filtered by `objective_hit=true` |

Total cap: 300 samples per warm-up run. Down-sampling is deterministic via
`args.seed` so reruns are reproducible.

These caps are **absolute counts** in v1, not fractions of self-play. v2 will
switch to fractions once `run_training_session` exposes a sample count.

## Acceptance gates that v1 enforces

W6:
- bootstrap.schema.sql + routes/games.py `game_schema_sql()` keep enum in
  sync (drift-check test).

W1+W3:
- Normal finished pvp with two top-30% players + winner → samples emitted
  with `trusted_source='pvp_filtered'`.
- Human-vs-engine win with quality signal → samples emitted with
  `trusted_source='human_beat_engine'`.
- Timeout / abandoned / disconnect → rejected.
- Plies < 20 → rejected.
- Draw or computer-win → rejected (no winner-side label).
- Either player missing quality signal → rejected (PvP) or "no_player_quality:human" (HvE).
- Illegal reconstruction (corrupted move_history_json) → rejected.

W4:
- `--include-replay-jsonl` reads JSONL, rejects rows lacking required fields
  or with non-whitelisted trusted_source.
- Per-source + total caps enforced; deterministic via seed.
- `--dry-run` reports what would be trained without touching models.
- Final payload includes `external_replay` block with full breakdown.

## What v2 should add

| | Rationale |
|---|---|
| teacher-audit `teacher_audit_status` enforcement | filter only counts samples where teacher concurs (avoids learning winner's blunders that happened to coincide with overall win) |
| Loser-side hard negatives (`target<0`, where teacher disagreed) | richer signal, but needs reliable teacher to avoid mis-labelling |
| Fraction-based caps once `run_training_session` exposes sample count | matches the intent stated in the v1 spec |
| Optional Elo / leaderboard quality enrichment column | improves the player-quality signal beyond rank-based proxy |
| Sparring-objective_hit harvester (consumes `moves.jsonl` from exp4-vs-exp5 sparring artifacts filtered by `objective_hit=true`) | closes the loop from B fair smoke into warm-up |

## Quick recipes

```bash
# Offline export PvP + human-vs-engine replay (interactive review then run)
HACKME_RUNTIME_DIR=/path/to/runtime python3 scripts/games/chess_pvp_history_to_replay.py \
  --since 2026-04-01 \
  --output-root ~/chess_results \
  --min-plies 20 \
  --quality-top-pct 30 \
  --quality-weeks 4

# Warm-up with PvP + PGN external replay (dry-run first to inspect)
python3 scripts/games/chess_seed_train.py \
  --preset warmup10 \
  --include-replay-jsonl ~/chess_results/pvp_replay_20260512_010101/pvp_replay_training_eligible.jsonl \
  --include-replay-jsonl ~/chess_results/imported_pgn_prepared.jsonl \
  --dry-run

# When dry-run report looks healthy, drop --dry-run to actually train.
```
