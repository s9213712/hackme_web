# Chess pipeline — operator tutorial (2026-05-12)

End-to-end walkthrough of the W4–W9 chess replay / training pipeline.
**Safe by default**: every command in this tutorial runs in dry-run mode
and never mutates the production runtime model. The "real training"
section at the end requires explicit operator opt-in.

## TL;DR

```bash
# Build a tiny PGN fixture
cat > /tmp/sample.pgn <<'PGN'
[Event "Tutorial"]
[White "Master_A"]
[Black "Master_B"]
[Result "1-0"]
[WhiteElo "2400"]
[BlackElo "2300"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5
7. Bb3 d6 8. c3 O-O 9. h3 Nb8 10. d4 Nbd7 11. c4 c6 12. Nc3 Bb7 1-0
PGN

# One command runs the whole pipeline in dry-run mode
python3 scripts/games/chess_pipeline_dryrun.py \
  --pgn-path /tmp/sample.pgn \
  --pgn-audit-exp4-model-path services/games/models/chess_experiment_4_pv.json \
  --pgn-audit-exp5-model-path services/games/models/chess_experiment_5_nnue.json \
  --output-root /tmp/pipeline_demo

# Read the aggregated report
cat /tmp/pipeline_demo/pipeline_run_*/06_aggregate/PIPELINE_SUMMARY.md
```

That's it. Inspect the report; the suggested-staging-command at the
bottom is the safe non-dry-run invocation if you want to actually
train a staging candidate later. **The orchestrator never executes
it for you.**

## What this pipeline does

| Stage | What it does | Skipped when |
|---|---|---|
| **00 — pgn_input** | Convert local PGN (`--pgn-path`) or download remote PGN (`--pgn-source-url`, W9) into raw per-ply replay rows. Pre-prepared JSONL passes straight through. | None of the three input flags given. |
| **00b — pgn_teacher_audit** | Apply legal-move check + exp4/exp5 top-K teacher agreement to every raw row. Splits into `accepted_replay.jsonl` / `review_replay.jsonl` / `rejected_replay.jsonl`. Only accepted rows are training-safe. | `--pgn-skip-audit` is passed. |
| **01 — pvp_export** | Read finished `game_matches` in the main app DB and produce PvP / human-vs-engine replay JSONL. | `--runtime-dir` not given. |
| **02 — sparring** | Run `chess_exp4_vs_exp5_sparring` in the chosen mode (smoke / opening / endgame / castling / promotion / en_passant / special_rule / smoke / custom). | Either model path missing. |
| **03 — sparring_to_replay** | Harvest only `objective_hit=true` first plies from stage 02. | Stage 02 didn't produce a run dir. |
| **04 — seed_train_dryrun** | `chess_seed_train.py --dry-run` with every audit-accepted + PvP + sparring JSONL. **Hard-coded `--dry-run`; never trains.** | No replay JSONLs reached stage 4. |
| **05** *(reserved)* | Suggested staging candidate path placeholder; the report references it but no files are written here unless the operator runs the suggested command manually. | always — no operator-facing step. |
| **06 — aggregate** | Combine every stage summary into `pipeline_summary.json` + `PIPELINE_SUMMARY.md`, with cross-stage invariants. | Always runs (no skip path). |

## Prerequisites

- Python 3.10+ with the minimal runtime dependencies
  (`pip install -r requirements-minimal.txt`).
- `chess` module (python-chess).
- A bundled or staging copy of exp4 / exp5 model JSONs you can read
  (`services/games/models/chess_experiment_4_pv.json` &
  `chess_experiment_5_nnue.json` ship with the repo; or use exp4_16 /
  exp5_08 staging candidates under `~/chess_results/`).
- For the PvP-export lane: a populated `database.db` (the easiest way to
  get one is the `./test_for_develop.sh` isolated runtime — see "Common
  workflows" below).

## Quick-start scenarios

### A. "I have a local PGN — what does the audit say?"

```bash
python3 scripts/games/chess_pipeline_dryrun.py \
  --pgn-path /path/to/my_games.pgn \
  --pgn-audit-exp4-model-path services/games/models/chess_experiment_4_pv.json \
  --pgn-audit-exp5-model-path services/games/models/chess_experiment_5_nnue.json \
  --pgn-audit-profile strict \
  --output-root ~/chess_results
```

Outputs:

```
~/chess_results/pipeline_run_<UTC-stamp>/
├── 00_pgn_input/           pgn_path_00/{pgn_game_level.jsonl, pgn_per_ply_replay.jsonl}
│                           summary.json
├── 00b_pgn_teacher_audit/  accepted_replay.jsonl
│                           review_replay.jsonl
│                           rejected_replay.jsonl
│                           audit_detail.jsonl   (per-row teacher info)
│                           summary.json
├── 04_seed_train_dryrun/   chess_seed_train_dryrun_<UTC>.json
├── 06_aggregate/           pipeline_summary.json
│                           PIPELINE_SUMMARY.md
└── logs/                   <per-stage subprocess logs>
```

Read `06_aggregate/PIPELINE_SUMMARY.md` for the verdict. The
"Suggested next step" block at the bottom shows the safe staging
command if the dry-run's normalize_validation passed cleanly.

### B. "I want to pull a PGN from a URL" (W9)

```bash
python3 scripts/games/chess_pipeline_dryrun.py \
  --pgn-source-url 'https://example.com/path/to/games.pgn' \
  --pgn-download-dir ~/chess_results/pgn_sources \
  --pgn-audit-exp4-model-path services/games/models/chess_experiment_4_pv.json \
  --pgn-audit-exp5-model-path services/games/models/chess_experiment_5_nnue.json \
  --output-root ~/chess_results
```

The download goes to `--pgn-download-dir` (or
`~/chess_results/pgn_sources/` by default). Repeated runs reuse the
cached copy unless `--pgn-refresh-downloads` is passed. Downloaded
content takes the **same audit gate** as local PGN — there is no
shortcut. The aggregator's `any_network_pgn_download` invariant
flips True so you can tell at a glance whether network content
reached the pipeline.

### C. "I have a populated runtime DB, run the whole thing"

```bash
# Spawn an isolated dev runtime (writes to /tmp/, leaves repo alone).
# Use Ctrl+C once the server says it is listening; the DB is on disk.
./test_for_develop.sh --port 5099

# Then drive the orchestrator at that runtime
python3 scripts/games/chess_pipeline_dryrun.py \
  --runtime-dir /tmp/hackme_web_dev_<RUN_ID>/hackme_web/runtime \
  --since 2026-04-01 \
  --pgn-path /path/to/master_games.pgn \
  --pgn-audit-exp4-model-path ~/chess_results/exp4_16_rule_aware_final_fusion_locked/exp4/checkpoints/20/exp4_quick_candidate_model.json \
  --pgn-audit-exp5-model-path ~/chess_results/exp5_08_stage_candidate/chess_experiment_5_nnue_stage_candidate.json \
  --exp4-model-path ~/chess_results/exp4_16_rule_aware_final_fusion_locked/exp4/checkpoints/20/exp4_quick_candidate_model.json \
  --exp5-model-path ~/chess_results/exp5_08_stage_candidate/chess_experiment_5_nnue_stage_candidate.json \
  --sparring-mode smoke \
  --output-root ~/chess_results
```

This exercises every stage in the diagram above. Skipped stages
appear with `status: skipped` and a stated reason; failed stages
print their log path so you can grep it.

### D. "I just want to inspect what the converter rejected"

```bash
# After running the orchestrator once
python3 scripts/games/chess_replay_operator.py review \
  --run-dir ~/chess_results/pvp_replay_<UTC-stamp>
```

The operator UX wrapper (W5) groups `pvp_replay_rejected.jsonl` by
reason code and prints a human-readable explanation per category
("white player has no top-30% leaderboard signal in last 4 weeks",
etc.).

## Reading the aggregated report

`pipeline_summary.json` + `PIPELINE_SUMMARY.md` always include the
following invariants block. Every safe run should match:

```json
{
  "all_stages_diagnostic_only": true,
  "any_production_runtime_mutation": false,
  "any_model_mutation": false,
  "unaudited_imported_dataset_used_for_seed_train": false,
  "any_network_pgn_download": <true if --pgn-source-url, else false>,
  "stage_count": ...,
  "stages_seen": ["pgn_to_replay", "pgn_teacher_audit", "seed_train_dry_run", ...]
}
```

If any of the first four lines flips True you should stop and
investigate; the orchestrator only flips them when an explicit
unsafe-override flag was used.

The per-stage detail blocks include `key_metrics` slices the
operator usually wants:

| Stage | Key field |
|---|---|
| `pgn_to_replay` | `games_imported`, `per_ply_samples_emitted`, `raw_internet_download` |
| `pgn_teacher_audit` | `accepted_rows`, `review_rows`, `rejected_rows`, `audit_profile` |
| `pvp_export` | `matches_accepted_pvp_filtered`, `matches_accepted_human_beat_engine`, `reject_reasons` |
| `sparring_run` | `wdl`, `objective_summary`, `strength_counted_outcome` |
| `sparring_to_replay` | `games_accepted`, `samples_emitted`, `reject_reasons` |
| `seed_train_dry_run` | `rows_kept`, `exp4_ok / exp4_failed`, `exp5_ok / exp5_failed`, `train_skipped_reason`, `dry_run_artifact` |

## Safety contract (TL;DR)

- The orchestrator **never** trains for real. Stage 4 is hard-coded
  `--dry-run`. There is no `--execute-staging-train` flag.
- The orchestrator **never** writes the production runtime model. The
  W4.2 safety guard in `chess_seed_train.py` refuses non-dry-run runs
  that target the bundled / runtime-default / `services/games/models/`
  paths unless `--allow-default-model-paths` is explicitly passed.
- Network download is allowed (W9) but the download still flows
  through stage 00b audit. Raw PGN-derived rows are never fed into
  stage 4 by default; the aggregator's
  `unaudited_imported_dataset_used_for_seed_train` invariant flips
  True iff the operator explicitly opted into
  `--include-unaudited-pgn-in-dryrun-diagnostic`.

Full details: see the per-W design docs:

- [`2026-05-12_pvp_replay_pipeline_v1.md`](./2026-05-12_pvp_replay_pipeline_v1.md) — W1+W3 PvP converter + W4 / W4.1 / W4.2 safety contract.
- [`2026-05-12_replay_operator_ux.md`](./2026-05-12_replay_operator_ux.md) — W5 operator UX wrapper.
- [`2026-05-12_w6_pipeline_dryrun.md`](./2026-05-12_w6_pipeline_dryrun.md) — W6 dry-run orchestrator + W7 PGN input lane.
- [`2026-05-12_w8_pgn_teacher_audit_lane.md`](./2026-05-12_w8_pgn_teacher_audit_lane.md) — W8 teacher-audit gate.

## Real training (manual, opt-in)

After a dry-run with `exp4_failed = 0` and `exp5_failed = 0`, the
report prints:

```
=== suggested next step (NOT executed) ===
/usr/bin/env python3 .../chess_seed_train.py \
  --preset warmup10 \
  --include-replay-jsonl .../00b_pgn_teacher_audit/accepted_replay.jsonl \
  --experiment-4-model-path .../05_staging_candidate_suggested/chess_experiment_4_pv_candidate.json \
  --skip-exp5
```

Notes before you run that by hand:

1. The path under `05_staging_candidate_suggested/` is intentionally
   a candidate path — it will be **created on first write**, so the
   bundled / runtime-default models stay untouched.
2. `--skip-exp5` is on by default because exp5 NNUE is the
   production-promoted artefact. Drop it (and pass an explicit
   `--experiment-5-model-path`) only when you genuinely want a new
   exp5 staging candidate. The W4.2 guard rejects default-path
   writes for exp5 even with `--skip-exp5` dropped.
3. If you re-run the orchestrator you'll get a fresh
   `pipeline_run_<UTC>` dir — the suggested command will reference
   that fresh dir, not the old one.

## Common troubleshooting

| Symptom | Likely cause | Where to look |
|---|---|---|
| `pgn_to_replay` shows `samples_emitted=0` | All games in the PGN were draws (winner-side-only filter) or move_history failed to replay. | `00_pgn_input/pgn_*/pgn_game_level.jsonl` |
| `pgn_teacher_audit` shows `accepted_rows=0` | Bundled engines don't recognize the master moves at top-K — try `--pgn-audit-top-k 5` or switch profile to `very_strict` if you want even stricter. | `00b_pgn_teacher_audit/audit_detail.jsonl` |
| `seed_train_dry_run` shows `rows_kept=0` | No replay JSONLs reached stage 4. Check earlier stages. | `04_seed_train_dryrun/` log |
| `unaudited_imported_dataset_used_for_seed_train: true` | You passed `--include-unaudited-pgn-in-dryrun-diagnostic`. **Never use the suggested staging command from such a run.** | aggregator invariants block |
| `any_network_pgn_download: true` | You passed `--pgn-source-url`. Expected if downloads were intended. | per-URL log under `logs/` |
| Subprocess failure in any stage | Re-read the per-stage log under `logs/`. | `logs/<stage_name>.log` |

## What's NOT covered yet

| Topic | Status |
|---|---|
| Real production training automation | Intentionally manual. See "Real training" above. |
| Cron / startup auto-train | Still disabled (per `feedback-pvp-replay-discipline`). |
| Human-in-the-loop accept override for review rows | Future work; today review rows are diagnostic only. |
| Multi-process orchestration / scheduling | Out of scope for v1 dry-run orchestrator. |
| Slack / dashboard notifications | Future. |

If any of these become important, file an entry under
`docs/games/chess_debug/` with `W<N>_<feature>.md` and follow the
same safety contract: never bypass stage 00b, never feed unaudited
rows into stage 4, never auto-execute a staging command.
