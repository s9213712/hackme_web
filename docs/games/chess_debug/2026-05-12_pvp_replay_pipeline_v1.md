# PvP / human-vs-engine replay pipeline v1 (2026-05-12)

## Operator UX (W5)

For day-to-day use, prefer the operator CLI over the raw scripts:

```bash
python3 scripts/games/chess_replay_operator.py detect
python3 scripts/games/chess_replay_operator.py export --since 2026-04-01
python3 scripts/games/chess_replay_operator.py dry-run --run-dir <pvp_replay_*>
python3 scripts/games/chess_replay_operator.py review  --run-dir <pvp_replay_*>
python3 scripts/games/chess_replay_operator.py generate-staging-command \
    --run-dir <pvp_replay_*> --candidate-dir <staging-dir>
python3 scripts/games/chess_replay_operator.py wizard   # interactive menu
```

Same safety contract as below — no new training logic, no production
mutation, no auto-train. Details + rejection-reason explanations + tests
are in [`2026-05-12_replay_operator_ux.md`](./2026-05-12_replay_operator_ux.md).

## Safety contract (W4.2)

The safety surface for every external-replay-aware CLI lives in one
module:

- **`services/games/external_replay_safety.py`**
  - `serialize_json_payload(payload)` — canonical JSON serializer used
    by stdout, dry-run artifacts, and future ledger writers.
    `sort_keys=True`, `ensure_ascii=False`, `indent=2`, trailing
    newline. Locked so disk / stdout / future writers are
    byte-identical, not merely "same dict".
  - `is_default_model_path(...)` — three-layer detector (bundled,
    runtime-default, anywhere under `services/games/models/`).
  - `EngineMutationSpec` + `MutationPolicy` + `validate_mutation_policy(...)`
    — CLI-agnostic policy validator returning the list of blocking
    problems. Every external-replay-aware CLI builds a
    `MutationPolicy` from its argparse.Namespace and asks one question
    instead of re-implementing the guard.

`chess_seed_train.py` is now a thin wrapper that translates
`argparse.Namespace → MutationPolicy → validate_mutation_policy` and
uses `serialize_json_payload` for stdout AND the dry-run artifact.

### CLI mode matrix (enforced by `validate_mutation_policy`)

| Mode | external_replay | dry-run | path | result |
|---|---|---|---|---|
| A | no | — | — | allowed (pre-W4 baseline) |
| B | yes | yes | — | allowed (no mutation, writes dry-run artifact) |
| C | yes | no | none | **rejected** |
| D | yes | no | bundled artifact | **rejected** |
| E | yes | no | runtime-default artifact | **rejected** |
| F | yes | no | sibling under `services/games/models/` | **rejected** |
| G | yes | no | explicit staging / candidate path | allowed |
| H | yes | no | default + `--allow-default-model-paths` | allowed (logged opt-out) |

Tests live in `tests/services/games/test_external_replay_safety.py`
(validator-level, all 8 modes) and
`tests/scripts/games/test_chess_seed_train_cli_contract.py`
(subprocess-level for modes B / C / D plus a bundled-mtime mutation
sentinel and a stdout==artifact byte-identity check).

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
- ❌ **No production runtime mutation outside an explicit non-dry-run
  warm-up call**: the converter writes only under
  `~/chess_results/pvp_replay_<ts>/`. `chess_seed_train.py --dry-run`
  skips every state-mutating call (run_training_session, smoke,
  benchmark, write_training_report, external-replay trainer). Only a
  non-dry-run warm-up touches model files at the paths you pass via
  `--experiment-4-model-path` / `--experiment-5-model-path`.
- ❌ **No silent default-path mutation from external replay**:
  non-dry-run `--include-replay-jsonl` refuses to start unless the
  caller passes explicit `--experiment-4-model-path` /
  `--experiment-5-model-path` (or `--skip-exp4` / `--skip-exp5` for
  whichever engine should sit this run out). Explicit paths that
  resolve to the bundled artifact, the runtime default artifact, or
  anywhere under `services/games/models/` are also rejected so the
  guard cannot be bypassed by typing the default path verbatim.
  `--allow-default-model-paths` is the opt-in escape hatch for one-off
  recovery runs.
- ❌ **No raw-PvP-as-positive-training-data**: every accepted sample passes
  through the filter and is tagged `label_quality` ∈ {clean, review} with
  weight ≤ 0.20.
- ❌ **No human-beat-easy-engine harvest**: `--hve-difficulties` defaults to
  the target-engine whitelist (`experiment 4:pv` + `experiment 5:nnue`).
  Wins against the older / non-target engines are rejected with reason
  `non_target_engine:<difficulty>`.
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
| Gate | mode='computer', `winner_user_id == white_user_id` (human won), human in quality set, `computer_difficulty` in `--hve-difficulties` (default `experiment 4:pv,experiment 5:nnue`) |

The `--hve-difficulties` whitelist defaults to **just the target engines** so
wins against `easy`/`normal`/`hard`/`experiment`/`experiment 2:nn`/`experiment
3:dl` are rejected with reason `non_target_engine:<difficulty>`. Pass an
empty string to disable the filter (collect any computer win). See
[[feedback-pvp-replay-discipline]] for why we don't feed back wins against
non-target engines by default.

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
- `--dry-run` skips **everything that mutates state**: `run_training_session`,
  smoke, benchmark, `write_training_report`, and the external-replay
  trainer. It still loads + caps + normalize-validates the
  `--include-replay-jsonl` rows so schema bugs surface before the first
  real run.
- `external_replay.normalize_validation` (always populated when external
  replay is enabled, even on dry-run) exposes `exp4_ok / exp4_failed /
  exp5_ok / exp5_failed` plus up to 5 failing source_ids per engine.
- `--skip-exp5` mirrors `--skip-exp4` for the external-replay trainer
  (gate exp5 NNUE independently from exp4 PV — exp5 is closer to
  production / stage-candidate state).
- **Safety guard**: a non-dry-run run with `--include-replay-jsonl` must
  point at explicit candidate model paths (or use `--skip-exp4` /
  `--skip-exp5`). The guard also resolves the explicit path and rejects
  it if it equals the bundled / runtime-default artifact, or sits under
  `services/games/models/`. `--allow-default-model-paths` is the opt-out
  for intentional default-path writes.
- **Dry-run JSON artifact**: when `--dry-run` runs together with
  `--include-replay-jsonl`, the final payload is also written to
  `<report-dir>/chess_seed_train_dryrun_<UTC-timestamp>.json`. Stdout
  alone is too easy to lose, and the dry-run is precisely where you
  want a persistent record of `load_stats / cap_stats /
  normalize_validation / train_result.skipped_reason` for review.
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
# 1) Offline export PvP + human-beat-engine replay (target engines only by default).
HACKME_RUNTIME_DIR=/path/to/runtime python3 scripts/games/chess_pvp_history_to_replay.py \
  --since 2026-04-01 \
  --output-root ~/chess_results \
  --min-plies 20 \
  --quality-top-pct 30 \
  --quality-weeks 4 \
  --hve-difficulties "experiment 4:pv,experiment 5:nnue"

# Inspect SUMMARY.md; check matches_accepted_pvp_filtered /
# matches_accepted_human_beat_engine / reject_reasons distribution.

# 2) Dry-run warm-up: validates schema, caps, and normalize WITHOUT calling
#    run_training_session OR the external-replay trainer. Safe to run any time.
python3 scripts/games/chess_seed_train.py \
  --preset warmup10 \
  --include-replay-jsonl ~/chess_results/pvp_replay_20260512_010101/pvp_replay_training_eligible.jsonl \
  --include-replay-jsonl ~/chess_results/imported_pgn_prepared.jsonl \
  --dry-run

# Inspect the output JSON:
#   external_replay.load_stats               (whitelist hits, rejected rows)
#   external_replay.cap_stats                (per-source + total cap)
#   external_replay.normalize_validation     (exp4_ok/exp4_failed/exp5_ok/exp5_failed)
#   external_replay.train_result.skipped_reason == 'dry_run'

# 3) Real warm-up. Drop --dry-run only after the dry-run report looks healthy.
#    Safety guard refuses default-path writes for the external-replay step,
#    so you must point exp4 (and/or exp5) at explicit candidate artifacts
#    — or pass --skip-exp* to gate that engine out — or use
#    --allow-default-model-paths to bypass (NOT recommended).
python3 scripts/games/chess_seed_train.py \
  --preset warmup10 \
  --include-replay-jsonl ~/chess_results/pvp_replay_20260512_010101/pvp_replay_training_eligible.jsonl \
  --include-replay-jsonl ~/chess_results/imported_pgn_prepared.jsonl \
  --experiment-4-model-path ~/chess_results/pvp_replay_warmup_20260512/chess_experiment_4_pv_candidate.json \
  --skip-exp5
```
