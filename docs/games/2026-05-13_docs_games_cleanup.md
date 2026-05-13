# 2026-05-13 Docs/Games Cleanup

## Scope

Cleaned obsolete raw Exp5 experiment artifacts from `docs/games` after their
results were consolidated into summary reports.

## Kept

- Human-readable reports and score summaries.
- `2026-05-13_game_ai_eval_run_log.md`
- `2026-05-13_exp5_advanced_score_optimization.md`
- `2026-05-13_exp5_retrain_adapter_comparison.md`
- `model_snapshots/`
- v7 comparison artifacts.
- v10 high-water artifacts.
- current baseline and v14 adapter-context artifacts.
- downloaded replay probe:
  `2026-05-13_exp5_download_script_probe_replay.jsonl`
- v11 retrain rows/model artifacts needed for adapter replay-memory analysis.

## Removed

- `76` obsolete root-level Exp5 raw `.json` / `.jsonl` files for rejected or
  superseded intermediate runs.
- Large raw probe/gauntlet/tactical files from rejected adapter prototypes:
  - `2026-05-13_exp5_adapter_mode_v12/adapter_gauntlet_30.json`
  - `2026-05-13_exp5_adapter_mode_v12/adapter_gauntlet_30.jsonl`
  - `2026-05-13_exp5_adapter_mode_v12/adapter_score_probe.json`
  - `2026-05-13_exp5_adapter_mode_v12/adapter_tactical_suite_300.json`
  - `2026-05-13_exp5_adapter_mode_v13_strict_memory/adapter_gauntlet_30.json`
  - `2026-05-13_exp5_adapter_mode_v13_strict_memory/adapter_gauntlet_30.jsonl`
  - `2026-05-13_exp5_adapter_mode_v13_strict_memory/adapter_score_probe.json`
  - `2026-05-13_exp5_adapter_mode_v13_strict_memory/adapter_tactical_suite_300.json`

## Size Change

- Before cleanup: about `58M`.
- After root raw cleanup: about `35M`.
- After rejected-adapter raw cleanup: about `27M`.

## Rationale

The removed files were no longer the source of truth. Their conclusions are
kept in:

- `2026-05-13_exp5_advanced_score_optimization.md`
- `2026-05-13_exp5_retrain_adapter_comparison.md`
- `2026-05-13_game_ai_eval_run_log.md`

This preserves auditability while keeping `docs/games` usable.
