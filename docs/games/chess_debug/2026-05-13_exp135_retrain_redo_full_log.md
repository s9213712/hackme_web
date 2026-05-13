# 2026-05-13 exp1/3/4/5 retrain redo full log

## Scope

User request recap:

- Re-do the interrupted 2026-05-12 chess retrain task.
- Use `docs/games/chess_debug/chess_replays_exp3_example.jsonl` plus 25 downloaded high-quality games.
- Run threshold-based retrain for exp1/3/4/5, producing 4 comparison intervals.
- Do not truncate training/eval unless a dead loop is proven.
- Investigate `docs/games/chess_replays.jsonl` exp4/5 bad play.
- Fix obvious piece-hanging / pawn-gifting behavior first.
- Replace default initial models where a candidate is actually suitable.
- Record process, timing, script invocation map, strength metrics, and final Codex-vs-bot full-game replays.

Run root:

- `<chess-results>/retrain_redo_20260512T224634Z`

## What Happened Yesterday

No trustworthy resumable state was found for the crashed run, so the work was redone.

The replay file `docs/games/chess_replays.jsonl` contained 1 legal chess game, not a corrupt illegal-move replay. It was an exp4 black-game loss ending in white checkmate. The main failure was strategic/decision quality:

- exp4 was legal but shallow: many moves came from fallback / policy-value search without enough full-game danger awareness.
- Special-rule and promotion/castling priors were not enough to form a whole-game plan.
- The runtime guarded overlay path for exp4 was still parked/disabled by default, so learned special-rule behavior was not reliably protected by tactical safety.
- The observed "looks like it wants promotion and keeps feeding pawns" problem is consistent with one-ply material blindness plus rule-feature over-bias.

## Tactical Safety Fix

Added deterministic tactical safety guard to block obvious one-ply hanging-piece moves unless there is immediate compensation.

Changed files:

- `services/games/chess_tactical_safety.py`
- `services/games/chess_nnue.py`
- `scripts/games/game_ai_codex_play_eval.py`

Current worktree note: `services/games/chess_nnue.py` also contains exp5 full-game conversion/mate-priority heuristics in this fix surface, including late/low-material king activity, passed-pawn advancement, and forced mate search helpers. These are related to the "does not know how to finish a game" problem exposed by full-game play, but exp5 still failed the deterministic strength gate and should not be treated as production-promoted.

Existing tests run after model replacement:

```bash
PYTHONPATH=. pytest -q \
  tests/games/test_chess_exp5_architecture.py::test_exp5_tactical_safety_blocks_direct_rook_hang \
  tests/games/test_chess_exp5_architecture.py::test_exp5_rule_priority_handles_core_special_moves \
  tests/games/test_games.py::test_experiment_pv_rule_aware_fusion_adopts_learned_special_moves \
  tests/games/test_games.py::test_experiment_pv_choose_and_explain_special_rule_consistency
```

Result: 4 passed.

## Dataset

Downloaded PGN source:

- `https://www.pgnmentor.com/players/Carlsen.zip`

Strict/elite import was attempted first, but all games were skipped because PGN time-control metadata did not satisfy the strict filter. Re-ran with `--valid-game-filter basic`.

Import command:

```bash
PYTHONPATH=. python3 scripts/games/chess_pgn_to_replay.py \
  --source-url https://www.pgnmentor.com/players/Carlsen.zip \
  --download-dir "$RUN_ROOT/downloads" \
  --output-jsonl "$RUN_ROOT/replays/carlsen_25_game_level.jsonl" \
  --replace-output --max-games 25 --sample-size 25 --seed 20260513 \
  --min-elo 2500 --min-ply 30 --result decisive \
  --valid-game-filter basic --skip-nonstandard-start --position-scope complete \
  --source imported_dataset --collection-tier trusted \
  --source-label pgnmentor_carlsen_20260513 --no-progress
```

Import result:

- 25 games written.
- 7484 scanned.
- 4901 eligible.
- Includes castling, promotion, and one en-passant game.

Per-ply expansion:

```bash
PYTHONPATH=. python3 -c \
  "from pathlib import Path; from scripts.games.chess_pipeline_dryrun import _expand_game_level_to_per_ply; ..."
```

Expansion result:

- 25 games processed.
- 1047 per-ply samples emitted.

Teacher audit:

```bash
PYTHONPATH=. python3 scripts/games/chess_imported_replay_teacher_audit.py \
  --input-jsonl "$RUN_ROOT/replays/carlsen_25_per_ply_replay.jsonl" \
  --output-dir "$RUN_ROOT/audit/pgn_teacher_audit" \
  --audit-profile strict --top-k 3 \
  --exp4-model-path services/games/models/chess_experiment_4_pv.json \
  --exp5-model-path services/games/models/chess_experiment_5_nnue.json
```

Audit result:

- Input rows: 1047.
- Accepted: 379.
- Review: 643.
- Rejected: 25.
- Duplicates: 25.

Official interval replay buffers:

| interval | replay rows | composition |
|---|---:|---|
| interval_0 | 0 | baseline only |
| interval_1 | 14 | 6 exp3 examples + 8 downloaded games |
| interval_2 | 22 | 6 exp3 examples + 16 downloaded games |
| interval_3 | 31 | 6 exp3 examples + 25 downloaded games |

Note: interval_1/2 used `--min-usable-replays 8` to force the expected threshold cutpoints. The normal production recommendation remains 25 usable replays.

## Candidate Warm-Start Correction

An exploratory interval_1 run completed first, but it revealed an orchestration problem: exp3/4/5 candidate paths do not automatically warm-start from `services/games/models` when the candidate path does not exist. They start from template defaults.

Action taken:

- Recorded the first interval_1 as exploratory only.
- Re-ran official interval_1/2/3 after copying the intended default model into each candidate path before `chess_train_pipeline.py`.
- Official interval comparisons below use only preseeded candidate runs.

## Script Invocation Map

| phase | script / API | purpose |
|---|---|---|
| PGN download/import | `scripts/games/chess_pgn_to_replay.py` | Download PGN ZIP and emit game-level replay JSONL |
| Game-to-ply expansion | `scripts.games.chess_pipeline_dryrun._expand_game_level_to_per_ply` | Convert game replay records to per-ply replay samples |
| Teacher audit | `scripts/games/chess_imported_replay_teacher_audit.py` | Accept/review/reject imported per-ply samples using legal oracle + exp4/exp5 top-k |
| Interval train | `scripts/games/chess_train_pipeline.py` | Prepare replay dataset, run seed train, exp1/3/4/5 refine, benchmark, exp5 gate |
| Seed train child | `scripts/games/chess_seed_train.py` | 76-game standard preset self-play seed training |
| Dataset refine children | `chess_exp1_dataset_train.py`, `chess_exp3_dataset_train.py`, `chess_exp4_dataset_train.py`, `chess_exp5_dataset_train.py` | Train/refine each experiment from prepared replay rows |
| Benchmark child | `scripts/games/chess_self_play_train.py` | 84-game round-robin benchmark with smoke/endgame probes |
| Exp5 gate child | `scripts/games/chess_exp5_strength_gate.py` | Deterministic exp5 safety/tactic/endgame gate |
| Full Codex games | `scripts/games/game_ai_codex_play_eval.py` | Full games against exp1/3/4/5; JSON + JSONL replay output |

## Official Interval Metrics

All benchmark rows used 84 games, `benchmark_rounds=2`, `smoke_games_per_pair=1`.

| interval | usable replay | train/eval | exp1 Elo / SR | exp3 Elo / SR | exp4 Elo / SR | exp5 Elo / SR | exp5 gate |
|---|---:|---:|---:|---:|---:|---:|---|
| 0 baseline | 0 | 0 / 0 | 1439.07 / 0.3333 | 1547.94 / 0.6042 | 1613.68 / 0.8125 | 1497.48 / 0.5000 | n/a |
| 1 official | 14 | 303 / 113 | 1463.16 / 0.3958 | 1573.52 / 0.7292 | 1499.96 / 0.5000 | 1503.15 / 0.5000 | fail |
| 2 official | 22 | 625 / 113 | 1455.20 / 0.3958 | 1540.23 / 0.6042 | 1504.76 / 0.5000 | 1512.38 / 0.5417 | fail |
| 3 official | 31 | 985 / 143 | 1462.27 / 0.3750 | 1530.73 / 0.5833 | 1480.65 / 0.4375 | 1559.95 / 0.6667 | fail |

Exp5 gate failure reason in all official retrain intervals:

- `deterministic_case_pass_rate_too_low`
- `candidate_score_not_above_baseline`

Important interpretation:

- exp5 interval_3 clearly improved in benchmark games: 8 wins, 16 draws, 0 losses, score_rate 0.6667.
- exp5 still did not pass deterministic tactical/castling/mate-case gate, so this is not a production promotion-quality model.
- exp4 retrained models all regressed against the current default exp4 baseline; do not blindly replace exp4 with these replay-trained candidates.

Approximate interval wall-clock:

| interval | approximate wall time |
|---|---:|
| interval_0 baseline | about 1 hour |
| interval_1 official | about 1h21m |
| interval_2 official | about 1h30m |
| interval_3 official | about 1h45m |

## Model Replacement

Manifest:

- `<chess-results>/retrain_redo_20260512T224634Z/final_model_selection_manifest.json`

Backups:

- `<chess-results>/retrain_redo_20260512T224634Z/final_default_backup/`

Final decisions:

| engine | action | source interval | reason |
|---|---|---|---|
| exp1 `experiment` | replaced | interval_1 | Best trained exp1 benchmark among retrain intervals |
| exp3 `experiment 3:dl` | replaced | interval_1 | Best exp3 benchmark and promotion gate passed |
| exp4 `experiment 4:pv` | kept current | n/a | All retrained exp4 candidates regressed badly; runtime tactical guard handles direct hanging-piece issue |
| exp5 `experiment 5:nnue` | replaced with caveat | interval_3 | Best exp5 benchmark, 0 losses; deterministic gate still failed, so this is a manual initial-seed update, not a gate promotion |

Final hashes are recorded in the manifest.

## Full Codex-vs-Bot Replays

Command:

```bash
PYTHONPATH=. python3 scripts/games/game_ai_codex_play_eval.py \
  --games-per-ai 5 \
  --chess-only \
  --chess-complete-games \
  --chess-deadloop-guard-plies 2000 \
  --chess-difficulties 'experiment,experiment 3:dl,experiment 4:pv,experiment 5:nnue' \
  --seed 20260517 \
  --output "$RUN_ROOT/codex_full_chess_eval.json" \
  --jsonl-output "$RUN_ROOT/codex_full_chess_replays.jsonl"
```

Artifacts:

- JSON summary: `<chess-results>/retrain_redo_20260512T224634Z/codex_full_chess_eval.json`
- JSONL replay: `<chess-results>/retrain_redo_20260512T224634Z/codex_full_chess_replays.jsonl`
- Repo copy: `docs/games/chess_debug/2026-05-13_codex_full_chess_replays.jsonl`

All 20 games were terminal-complete. No game hit the dead-loop guard.

| engine | record from Codex side | terminal reasons | ply range | subjective note |
|---|---:|---|---:|---|
| exp1 | 5W-0D-0L | checkmate x5 | 28-59 | Still very weak; missed direct mating nets and allowed large material collapse |
| exp3 | 0W-5D-0L | threefold x5 | 49-61 | More stable, but repeats instead of converting or escaping repetition |
| exp4 | 0W-5D-0L | threefold x5 | 51-58 | Guard prevents some direct nonsense, but whole-game planning is still draw-loop heavy |
| exp5 | 0W-4D-1L | threefold x4, checkmate x1 | 59-113 | Strongest practical opponent in this run; still repetition-prone and gate-incomplete |

Subjective ranking from these 20 full games:

1. exp5: strongest practical play, actually checkmated Codex once and resisted longest.
2. exp3: stable enough to draw, but has no conversion plan.
3. exp4: similar drawish behavior to exp3 but less convincing in benchmark and retrain regressed.
4. exp1: still beginner-level; tactical and king-safety failures are obvious.

## Trap Learning Plan

The immediate fix is not "teach the model to sacrifice"; it is "stop confusing blunders with traps."

Use three labels:

- `trap_offer`: a move that appears to give material/tempo but is not losing under best defense.
- `trap_refutation`: the punish line after the opponent accepts the poisoned offer.
- `trap_avoidance`: refusal or prophylaxis against an opponent's poisoned offer.

Required proof fields before using a trap as positive training data:

- Best-defense line does not drop below an allowed centipawn floor.
- Common greedy reply leads to a forced gain or mate threat.
- The sacrificed material has compensation within a bounded PV depth.
- Add hard negatives for superficially similar moves that simply hang material.

Recommended next work:

- Add deterministic trap probes to `game_ai_strength_eval.py` / exp5 gate.
- Mine PGN positions where a capture is bad only because of a short tactical refutation.
- Add repetition-avoidance and conversion probes; exp3/4/5 all overuse threefold repetition.
- For exp5, repair fixed tactical gate cases before treating interval_3 as production-promotable.

## Final State

- Training and benchmark runs were allowed to complete.
- No training/eval process was killed or truncated.
- exp1/exp3/exp5 defaults were updated as described.
- exp4 default was intentionally not overwritten because every retrained exp4 candidate regressed.
- Full Codex-vs-bot JSONL replay is recorded.
- The remaining blocker is not data volume alone; it is deterministic tactical/trap/repetition reasoning.
