# W6 — chess pipeline dry-run orchestrator (2026-05-12)

> **Looking for an operator walkthrough instead of design notes?** See
> [`2026-05-12_pipeline_operator_tutorial.md`](./2026-05-12_pipeline_operator_tutorial.md).
>
> **2026-05-12 W7 update**: stage 00 PGN / prepared replay input is now
> wired into the orchestrator. See the "W7 — PGN input lane" section
> below; the rest of W6 is unchanged.
>
> **2026-05-12 W8 update**: stage 00b PGN teacher-audit gate is now
> wired between stage 00 and stage 4. Raw PGN-derived rows are
> diagnostic only; only audit-accepted rows reach
> `seed_train --dry-run`. Full details in
> [`2026-05-12_w8_pgn_teacher_audit_lane.md`](./2026-05-12_w8_pgn_teacher_audit_lane.md).
> A new aggregator invariant
> `unaudited_imported_dataset_used_for_seed_train` flips True if the
> operator passes `--include-unaudited-pgn-in-dryrun-diagnostic`.
>
> **2026-05-12 W9 update**: stage 00 grows a `--pgn-source-url` lane
> (downloads via `chess_pgn_to_replay --source-url`). Downloaded PGN
> still flows through stage 00b audit; the new aggregator invariant
> `any_network_pgn_download` flips True whenever a URL was used so
> network provenance is visible at a glance.

## What W6 ships

Three new scripts + one doc + tests, wiring the previously stand-alone
replay-pipeline tools into one safe orchestrator:

| File | Role |
|---|---|
| `scripts/games/chess_sparring_to_replay.py` | Harvest sparring artefacts → canonical replay JSONL. Only the **first ply** of games with `objective_counted=True AND objective_hit=True AND forced_fixture_win=False AND first_ply.legal=True`. `trusted_source='sparring_objective_hit'`, weight 0.10 cap 0.15. |
| `scripts/games/chess_pipeline_report.py` | Pure aggregator. Reads N stage summaries, normalises each into a slim view, computes cross-stage invariants (`all_stages_diagnostic_only`, `any_production_runtime_mutation`, `any_model_mutation`), emits `pipeline_summary.json` + `PIPELINE_SUMMARY.md`. Never executes any stage. |
| `scripts/games/chess_pipeline_dryrun.py` | End-to-end orchestrator. Chains five stages as separate subprocesses with safe defaults. |

## Stage map

```text
                              ┌─── 00_pgn_input/             (W7) ┐
chess_pgn_to_replay   ────────┤   (needs --pgn-path or             │
                              │    --prepared-replay-jsonl)        │
                              └─── per_ply.jsonl                   │
                                                                   │
                              ┌─── 01_pvp_export/                  │
chess_pvp_history_to_replay ──┤   (needs HACKME_RUNTIME_DIR)       │
                              └─── pvp_replay_<ts>/                │
                                                                   │
                              ┌─── 02_sparring/                    │
chess_exp4_vs_exp5_sparring ──┤   (needs --exp4/5 model paths)     │
                              └─── exp4_vs_exp5_smoke_<ts>/        │
                                                          │        │
                              ┌─── 03_sparring_to_replay/ ↓        │
chess_sparring_to_replay ─────┤   (consumes sparring run dir)      ▼
                              └─── sparring_replay_<ts>/      04_seed_train_dryrun/
                                                          │  (consumes ALL JSONLs)
                                                          ▼
                              ┌─── 06_aggregate/             ◄────────┘
chess_pipeline_report ────────┤   pipeline_summary.json
                              └─── PIPELINE_SUMMARY.md
                                                          │
                                                          ▼
                              suggested staging warm-up command
                              (printed, NOT executed)
```

Stages skip cleanly when their prerequisites are absent. The
orchestrator's exit code is non-zero only if a stage that did run
failed; missing prerequisites are recorded as `skipped` in the report.

## Safety invariants (what the orchestrator guarantees)

Re-checked in the aggregator's invariants block on every run:

| Invariant | Guarantee |
|---|---|
| `all_stages_diagnostic_only` | True for every stage included so far. |
| `any_production_runtime_mutation` | False — no stage writes the production runtime model. |
| `any_model_mutation` | False — the orchestrator hard-codes `--dry-run` on stage 4. The aggregator flags True only if a non-dry-run seed_train somehow ran. |
| `aggregator_executes_no_stage` | True — stage 5 is a pure reader. |
| `aggregator_writes_no_models` | True. |
| `aggregator_writes_no_db` | True. |

Stage 4 is hard-coded `--dry-run`. There is no orchestrator flag that
turns it off — the operator must manually invoke `chess_seed_train.py`
or `chess_replay_operator.py generate-staging-command` for a real
warm-up.

## Sparring harvester filter (W6 commit 1)

Only one ply per accepted game (the ply where `objective_hit` was
judged):

| Gate | Acceptance |
|---|---|
| `objective_counted` | True |
| `objective_hit` | True |
| `forced_fixture_win` | False |
| game `outcome` | not `illegal_*` |
| first ply `legal` | True with non-empty `move` + `fen_before` |

Sample row uses the canonical replay schema with
`trusted_source='sparring_objective_hit'`, `source='sparring_objective_hit'`,
`label_quality='review'`, default weight `0.10` (cap `0.15`).

## Aggregator stage detection (W6 commit 2, extended in W7)

Detection first honours a self-stamped ``stage`` field (W7 convention),
then falls back to structural fingerprint:

| Stage | Recognised by |
|---|---|
| `pgn_to_replay` | `stage == "pgn_to_replay"` (self-stamped, W7) |
| `pvp_export` | `counts.matches_accepted_pvp_filtered` |
| `sparring_run` | `meta` + `objective_summary` + (`wdl` or `raw_outcome`) |
| `seed_train_dry_run` | `external_replay` + `dry_run` keys |
| `sparring_to_replay` | `counts.games_accepted` + `counts.samples_emitted` |
| `unknown` | everything else (a note is recorded in the stage block) |

## W7 — PGN input lane

W7 adds stage 00 to the orchestrator with two parallel input lanes:

| Flag | Behaviour |
|---|---|
| `--pgn-path PATH` (repeatable) | Subprocesses `chess_pgn_to_replay` on the local PGN, then **expands** each decisive game's `move_history` into canonical per-ply replay samples via python-chess. Winner-side moves only; stamps `trusted_source='imported_dataset'`, `label_quality='clean'`, `target=1.0`, default `weight=0.5`. Draws / illegal-reconstruction games are dropped. |
| `--prepared-replay-jsonl PATH` (repeatable) | Already-canonical per-ply JSONL. Passed straight through to stage 4 (`seed_train --dry-run`); no re-conversion here, no re-stamping of `trusted_source`. The `normalize_validation` step in seed_train is the bouncer. |

Sample shape emitted by the PGN-derived path:

```json
{
  "fen": "<FEN before the move>",
  "move_uci": "e2e4",
  "side": "white",
  "target": 1.0,
  "weight": 0.5,
  "source": "imported_dataset",
  "trusted_source": "imported_dataset",
  "label_quality": "clean",
  "training_eligible": true,
  "source_id": "pgn:<replay_id>:ply:<n>",
  "result_backed": true,
  "teacher_audit_status": "not_run",
  "winner_color": "white"
}
```

`trusted_source='imported_dataset'` is already on the W4 whitelist with a
per-source cap of 200 inside `chess_seed_train.DEFAULT_EXTERNAL_CAPS`, so
the PGN-derived rows survive the cap step alongside any
`pvp_filtered` / `human_beat_engine` / `sparring_objective_hit` inputs.

### W7 non-goals (carried over)

- ❌ No network auto-download. `policy.raw_internet_download` is
  hard-coded `False` in the stage's summary.
- ❌ No `--execute-staging-train`. Stage 4 stays hard-coded `--dry-run`.
- ❌ No loser-side moves emitted. Without a teacher audit, only
  winner-side moves earn `target=1.0`.

### W7 verification

A 12-ply Ruy Lopez fixture (1-0 result, 2400 / 2300 Elo headers) drives
end-to-end:

```text
stages_seen            : ['pgn_to_replay', 'seed_train_dry_run']
all_diagnostic_only    : True
any_production_runtime_mutation : False
any_model_mutation     : False

pgn_to_replay          games_imported=1 samples_emitted=12 raw_internet_download=False
seed_train_dry_run     rows_kept=12 total_kept=12 exp4 12/0 exp5 12/0 skipped=dry_run
```

This is the W7 acceptance: a non-zero PGN sample flow lands cleanly in
`seed_train --dry-run` with normalize failures = 0 on both engines,
while the orchestrator never mutates a model and never touches the
production runtime.

## Acceptance criteria

W6 considers an end-to-end run healthy if all of the following hold in
the aggregator's `pipeline_summary.json`:

1. `invariants.all_stages_diagnostic_only == True`
2. `invariants.any_production_runtime_mutation == False`
3. `invariants.any_model_mutation == False`
4. `policy.aggregator_executes_no_stage == True`
5. Every stage with status `ok` has its `summary_path` in `stages`.
6. Every stage with status `skipped` has a stated `reason`.
7. The aggregated suggested next-step command uses an explicit
   candidate path and includes `--skip-exp5` (unless
   `--train-exp5-in-suggestion` was passed).

Verified end-to-end on 2026-05-12 against exp4_16 vs exp5_08 in
sparring opening mode (`--sparring-max-plies 20`):

- `pvp_export` → skipped (no `--runtime-dir`).
- `sparring` → 2 games, 0 objective hits, 0 illegal, 0 audit error.
- `sparring_to_replay` → 0 accepted (both `objective_miss`), 0 samples.
- `seed_train_dry_run` → `rows_kept=0`, `skipped_reason=no_samples`
  (correct: 0 sparring samples + no PvP source).
- `aggregate` → `stages_seen=['seed_train_dry_run', 'sparring_run',
  'sparring_to_replay']`, all invariants pass.

## Recommended invocations

```bash
# Full pipeline including PvP export (needs an isolated runtime with
# database.db and game_matches populated, e.g. from test_for_develop.sh):
python3 scripts/games/chess_pipeline_dryrun.py \
  --runtime-dir <hackme runtime root> \
  --since 2026-04-01 \
  --exp4-model-path </path/to/exp4_candidate.json> \
  --exp5-model-path </path/to/exp5_stage_candidate.json> \
  --sparring-mode smoke \
  --output-root ~/chess_results

# Sparring-only chain (no PvP, useful for quick W6 acceptance smoke):
python3 scripts/games/chess_pipeline_dryrun.py \
  --exp4-model-path </path/to/exp4.json> \
  --exp5-model-path </path/to/exp5.json> \
  --sparring-mode opening \
  --sparring-max-plies 20 \
  --output-root /tmp/hackme_pipeline_smoke

# Inspect the aggregated report:
cat <output-root>/pipeline_run_<ts>/06_aggregate/PIPELINE_SUMMARY.md
```

The "Suggested next step" block at the bottom of the aggregated report
is the safe staging warm-up command. **It is not executed.** Copy/paste
it into a separate shell after you have:

1. Read the PIPELINE_SUMMARY.md's per-stage detail.
2. Confirmed `normalize_validation.exp4_failed == 0` and
   `normalize_validation.exp5_failed == 0` in stage 4.
3. Picked an explicit candidate dir under `~/chess_results/`.

## Non-goals (still)

`feedback-pvp-replay-discipline` continues to apply. W6 is the
**dry-run orchestrator**, not a retrain loop:

- ❌ Auto-promote.
- ❌ Production runtime mutation.
- ❌ Cron / startup auto-train.
- ❌ Finish-hook on PvP completion.
- ❌ Raw engine-vs-engine moves → replay (only oracle-confirmed plies).
- ❌ Raw PvP → replay (only filtered).

## Tests

| File | Coverage |
|---|---|
| `tests/scripts/games/test_chess_sparring_to_replay.py` | 17 — filter contract (every reject path), sample shape, weight cap, --help. |
| `tests/scripts/games/test_chess_pipeline_report.py` | 20 — stage detection, normalisation, invariants, markdown render, --help, raw_outcome alias. |
| `tests/scripts/games/test_chess_pipeline_dryrun.py` | 11 — staging command builder, latest-subdir, every stage skip-path, --help. |

The deeper safety contract is still validated by
`tests/services/games/test_external_replay_safety.py` and
`tests/scripts/games/test_chess_seed_train_cli_contract.py` (W4.2).
W6 is intentionally additive — it does not change the safety surface,
only how operators reach it.
