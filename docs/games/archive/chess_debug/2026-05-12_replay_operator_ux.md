# Replay operator UX — W5 (2026-05-12)

## What W5 is — and is not

W5 ships a single CLI (`scripts/games/chess_replay_operator.py`) that wraps
the W4.2-hardened replay pipeline in operator-friendly subcommands. It
**does not** add new training logic, **does not** mutate models, **does not**
open the main DB read-write, **does not** install a finish-hook or cron. The
existing `services/games/external_replay_safety` contract is the single
source of truth for safety — W5 just removes the long flag strings.

Non-goals (carried over from W4.2 / [[feedback-pvp-replay-discipline]]):

- ❌ No new training logic.
- ❌ No PvP finish-hook.
- ❌ No cron / startup auto-train.
- ❌ No raw-PvP-as-positive-training-data shortcut.
- ❌ No production runtime mutation outside an explicitly typed staging path.

## Subcommands

```
python3 scripts/games/chess_replay_operator.py <subcommand> [flags]
```

| Subcommand | Purpose | State touched |
|---|---|---|
| `detect` | Resolve runtime / DB paths exactly like `chess_pvp_history_to_replay`. Reports whether `game_matches` exists. | Read-only DB introspection. |
| `export` | Run the converter; pretty-print `summary.json` counts + `reject_reasons` + "next" hints. | Same as the underlying converter (writes JSONL only under `~/chess_results/pvp_replay_<ts>/`). |
| `dry-run` | Run `chess_seed_train --dry-run` on a converter run dir; emit PASS / FAIL with rows, normalize counts, artifact path. | Same as `chess_seed_train --dry-run` (no model writes, see W4.1b). |
| `review` | Bucket `pvp_replay_rejected.jsonl` by `rejection_reason`, render a human-readable explanation per category. | Read-only file. |
| `generate-staging-command` | Emit (NOT execute) the safe non-dry-run command with `--skip-exp5` default and an explicit candidate path under a caller-supplied dir. | Prints a string to stdout. |
| `wizard` | Interactive menu chaining all of the above. | Calls the same subcommand handlers. |

## PASS / FAIL contract for `dry-run`

`dry-run` returns exit code `0` (and prints `PASS`) iff **all** of the
following hold in the dry-run payload:

1. `dry_run == True`.
2. `external_replay.load_stats.rows_kept > 0`.
3. `external_replay.cap_stats.total_kept > 0`.
4. `external_replay.normalize_validation.exp4_failed == 0`.
5. `external_replay.normalize_validation.exp5_failed == 0`.
6. `external_replay.train_result.skipped_reason == "dry_run"`.
7. `dry_run_artifact` exists on disk.

Any other state ⇒ exit code `1` + `FAIL` + a "do not run staging warm-up
until normalize failures are 0" hint.

## Rejection reason explanations

`review` maps converter reason codes to one-line explanations:

| Reason code (prefix) | Human-readable explanation |
|---|---|
| `no_player_quality:<side>` | `<side>` player has no top-30% leaderboard signal in the last 4 weeks. |
| `non_normal_end:<sub>` | Game ended abnormally via `<sub>` (timeout / abandoned / disconnect / resign_too_early / cancelled). |
| `no_winner_or_drawn` | Draw or no winner recorded; no winner-side moves to collect. |
| `too_short:<N>` | Game had only `<N>` plies (below `--min-plies`). |
| `non_target_engine:<engine>` | Computer opponent was `<engine>`, not in `--hve-difficulties` whitelist. |
| `move_history_json_invalid:<exc>` | move_history_json could not be parsed; data may be corrupted. |
| `reconstruction_error:<details>` | move_history failed to replay legally via python-chess; investigate corrupted moves. |
| `missing_player_id` | white_user_id or black_user_id is NULL. |
| `winner_user_id_not_in_match_players` | winner_user_id does not match either player. |
| `missing_human_id_in_computer_mode` | `mode='computer'` but white_user_id is NULL. |
| `computer_won_or_not_human_winner` | `mode='computer'` but winner is not the human player. |

`review` does **not** allow the operator to "accept" rejected matches into
training. v2 may add a teacher-audit-backed override; v1 is read-only.

## Wizard flow

```text
=== Chess Replay Pipeline Operator Wizard ===
[1] Detect runtime / DB
[2] Export PvP / human-vs-engine replay
[3] Dry-run validation on an existing run dir
[4] Review rejected matches
[5] Generate staging warm-up command
[6] Exit
Choose:
```

Each option invokes the same handler the matching subcommand uses. The
wizard adds prompts for the most common parameters (Since date, run dir,
candidate dir, "also train exp5?" defaulting to "n") but never exposes
flags that would bypass the W4.2 safety contract.

## Recommended end-to-end recipe

```bash
# 0. (one-off) launch an isolated dev runtime via test_for_develop.sh
./test_for_develop.sh --port 5099   # creates $HACKME_RUNTIME_DIR with database.db

# 1. confirm DB is reachable + has game_matches
python3 scripts/games/chess_replay_operator.py detect

# 2. export PvP + human-vs-engine replay
python3 scripts/games/chess_replay_operator.py export --since 2026-04-01

# 3. dry-run validation on the latest run
python3 scripts/games/chess_replay_operator.py dry-run \
    --run-dir ~/chess_results/pvp_replay_<latest-timestamp>

# 4. (optional) review which matches got dropped + why
python3 scripts/games/chess_replay_operator.py review \
    --run-dir ~/chess_results/pvp_replay_<latest-timestamp>

# 5. when dry-run says PASS: generate the staging command (NOT executed)
python3 scripts/games/chess_replay_operator.py generate-staging-command \
    --run-dir ~/chess_results/pvp_replay_<latest-timestamp> \
    --candidate-dir ~/chess_results/pvp_replay_warmup_<UTC-stamp>
```

Then the operator **manually** pastes the printed staging command into a
new shell after a final review. The non-dry-run training step never runs
automatically.

## Tests

`tests/scripts/games/test_chess_replay_operator.py` covers:

- runtime detection with / without env, with / without DB, with / without
  `game_matches` table.
- `parse_converter_summary` extracts the counts the operator needs.
- `parse_dry_run_payload` PASS / FAIL contract across the 5 failure modes
  (normalize fail, missing artifact, zero rows, not dry-run, wrong
  skipped_reason).
- `group_rejected_by_reason` skips blank + malformed lines.
- `explain_rejection_reason` round-trips every reason-code prefix used by
  the converter.
- `generate_staging_command` always emits `--skip-exp5` unless explicitly
  opted out and never points at `services/games/models/`.
- One subprocess smoke verifies `--help` lists every subcommand.

The deeper safety contract is still validated by
`tests/services/games/test_external_replay_safety.py` and
`tests/scripts/games/test_chess_seed_train_cli_contract.py` (W4.2). W5 is
intentionally a thin layer above them.
