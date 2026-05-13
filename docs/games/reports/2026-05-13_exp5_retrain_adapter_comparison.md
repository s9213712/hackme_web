# 2026-05-13 Exp5 Retrain vs Adapter Comparison

## Bottom Line

Retrain is not the wrong direction. Directly replacing the main model with a
small, noisy normal-game retrain is the wrong deployment path for the current
data quality.

The stronger architecture is:

- keep `services/games/models/chess_experiment_5_nnue.json` as the stable main
  model;
- treat retrain outputs as versioned experience notebooks / small adapters;
- default to main-model play unless an adapter has passed separate shadow,
  holdout, gauntlet, and no-regression gates;
- keep each adapter analyzable by source rows and replay provenance.

The code now follows the conservative default: `guarded` adapter mode records
exact replay-memory hits, but does not adopt them unless explicit adoption flags
are enabled.

## Same-Scenario Results

All rows below use the same score stack:

- legacy exp5 fixed + sparring score probe;
- 300-case tactical suite, including 240 downloaded PGN human probes;
- 30 complete games across 15 openings;
- advanced non-saturated score.

| Run | Architecture | Advanced /100 | Gauntlet | Score rate | Threefold | Fixed | Tactical | Adapter adoption | Decision |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| historical v10 reference | main model + accepted search heuristics | `84.1482` | `18W/12D/0L` | `0.8000` | `40.00%` | `40/40` | `300/300` | n/a | still target |
| current baseline v14 context | current main model, adapter env off | `80.0813` | `14W/16D/0L` | `0.7333` | `53.33%` | `40/40` | `300/300` | n/a | production baseline for this run |
| v11 direct retrain | candidate model replaces main in eval only | `78.4954` | `12W/17D/1L` | `0.6833` | `56.67%` | `40/40` | `300/300` | n/a | rejected |
| v12 loose adapter | general adapter may override main | `72.4156` | `11W/18D/1L` | `0.6667` | `60.00%` | `34.83/40` | `300/300` | `36/1406` | rejected |
| v13 exact-memory adoption | only exact replay memory may override main | `74.2151` | `8W/20D/2L` | `0.6000` | `66.67%` | `40/40` | `300/300` | `6/1451` | rejected |
| v14 notes-only guarded | exact replay memory is audit-only by default | `81.0343` | `15W/12D/3L` | `0.7000` | `40.00%` | `40/40` | `300/300` | `0/1492` | safe default, not a strength gain |

Interpretation:

- Direct retrain learned local rows but did not generalize. It lost `5.6528`
  points against the historical v10 reference and introduced one complete-game
  loss.
- Loose adapter was worse than direct retrain because the adapter model
  overrode curated main-model opening and fixed-probe behavior.
- Exact-memory adoption was still too permissive. Six exact replay adoptions
  were enough to lower complete-game performance.
- Notes-only guarded mode is the correct safe default. It preserves the
  experience notebook and records `31` exact-memory hits, but made `0`
  automatic move overrides.
- The current gauntlet uses timed search, so small W/D/L differences between
  current baseline and notes-only guarded are treated as run variance unless an
  adopted adapter move is present. v14 had no adopted adapter moves.

## Why Direct Retrain Regressed

The v11 normal-game retrain used 10 complete games:

- AI result during data collection: `6W/4D/0L`, score rate `80.00%`;
- extracted positions: `433`;
- selected positions: `180`;
- teacher accepted rows: `45/180`;
- quarantined rows: `133/180`;
- suspicious teacher rows: `2`;
- train/eval split: `31/14`.

The candidate improved local train agreement, but the accepted sample count was
too small and the label confidence was too weak. The teacher metadata also used
one-ply static top-K, so it should not be treated as deep search certainty.

Conclusion: more experience can make a model worse when the labels are noisy,
the teacher is shallow, and the update changes broad policy weights instead of
targeting the measured failure mode.

## Architecture Changes

Files changed for this phase:

- `services/games/chess_nnue.py`
  - Added opt-in adapter environment variables.
  - Added reentry guard so adapter evaluation cannot recursively call itself.
  - Added exact replay-memory loading with source/audit metadata.
  - Added `HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_ALLOW_EXACT`.
  - Added `HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_ALLOW_GENERAL`.
  - `guarded` mode now defaults to notes-only. It records exact-memory hits but
    does not adopt them unless explicitly allowed.
- `scripts/games/chess_exp5_adapter_mode_eval.py`
  - Runs the same score probe, 300-case tactical suite, 30-game gauntlet, and
    advanced score under adapter env.
  - Stores command logs in each output directory.
  - Adds `--allow-exact-adoption` and `--allow-general-adapter` flags.
- `tests/games/test_chess_exp5_architecture.py`
  - Covers exact adapter opt-in.
  - Covers fallback when no exact memory exists.
  - Covers guarded notes-only behavior for exact replay hits.

Verification:

- `python3 -m py_compile services/games/chess_nnue.py scripts/games/chess_exp5_adapter_mode_eval.py tests/games/test_chess_exp5_architecture.py`: pass.
- `PYTHONPATH=. python3 -m pytest -q tests/games/test_chess_exp5_architecture.py`: `31 passed`.

## Script Call Map

| Purpose | Script / artifact | Notes |
|---|---|---|
| 10 normal games + direct candidate retrain | `scripts/games/chess_exp5_normal_retrain_smoke.py` | output `docs/games/2026-05-13_exp5_normal_retrain_smoke_v11/` |
| teacher distill from collected positions | `scripts/games/chess_exp5_teacher_distill.py` via smoke script | accepted `45`, quarantine `133` |
| repeatability gate | smoke script calls repeatability gate under `repeatability_gate/` | candidate was not stageable |
| adapter-mode evaluation | `scripts/games/chess_exp5_adapter_mode_eval.py` | output v12/v13/v14 directories |
| legacy fixed + sparring score | `scripts/games/chess_exp5_score_probe.py` | uses external replay probes by default |
| tactical + human probes | `scripts/games/chess_exp5_tactical_suite.py` | uses downloaded PGN replay cases |
| complete-game replay gauntlet | `scripts/games/chess_exp5_gauntlet.py` | writes `.jsonl` replay files |
| advanced non-saturated score | `scripts/games/chess_exp5_advanced_score.py` | combines probe/tactical/gauntlet/runtime |
| downloaded replay artifact | `docs/games/2026-05-13_exp5_download_script_probe_replay.jsonl` | produced by the earlier chess-game download pipeline and reused as PGN human probes |
| default score-probe replay source | `<chess-results>/retrain_redo_20260512T224634Z/replays/carlsen_25_game_level.jsonl` | loaded by `chess_exp5_score_probe.py` unless overridden |

## Key Artifacts

- v11 direct retrain report:
  `docs/games/2026-05-13_exp5_normal_retrain_smoke_v11/SUMMARY.md`
- v11 candidate model:
  `docs/games/2026-05-13_exp5_normal_retrain_smoke_v11/repeatability_gate/run_1_seed_31/candidate/chess_experiment_5_nnue.json`
- v12 loose adapter:
  `docs/games/2026-05-13_exp5_adapter_mode_v12/summary.json`
- v13 exact-memory adoption:
  `docs/games/2026-05-13_exp5_adapter_mode_v13_strict_memory/summary.json`
- v14 notes-only guarded:
  `docs/games/2026-05-13_exp5_adapter_mode_v14_notes_only/summary.json`
- current no-adapter baseline:
  `docs/games/2026-05-13_exp5_current_baseline_v14_context/`

## Next Improvement Direction

To make retrain genuinely raise playing strength:

1. Keep all replays as searchable notes, not direct weight updates.
2. Promote only the rare rows where a stronger teacher, main-model search, and
   replay result agree.
3. Cluster adapters by failure mode: opening trap, anti-repetition, endgame
   conversion, human-probe, and tactical trap.
4. Run adapters in shadow mode first and record where advice would differ.
5. Adopt only if the adapter beats current baseline by margin, keeps fixed and
   tactical probes perfect, and has no complete-game losses.
6. Merge into the main model only after repeated independent holdout wins.

This keeps experience from being wasted while preventing low-confidence replay
data from damaging the stable engine.
