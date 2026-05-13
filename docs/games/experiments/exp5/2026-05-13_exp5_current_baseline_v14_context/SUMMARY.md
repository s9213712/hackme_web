# Exp5 Current Baseline, v14 Context

This is a no-adapter baseline rerun after the adapter architecture changes.
All adapter environment variables were unset.

## Result

- advanced score: `80.0813/100`
- grade: `strong_club_candidate`
- score probe: `40.00/40`, fixed `14.40/14.40`, sparring `6W/0D/0L`
- tactical suite: `300/300`
- PGN exact reference matches: `40/240 = 16.67%`
- gauntlet: `14W/16D/0L`
- gauntlet score rate: `0.7333`
- threefold rate: `53.33%`
- complete-game rate: `93.33%`
- average gauntlet runtime: `10300.024ms`

## Artifacts

- score probe: `docs/games/2026-05-13_exp5_current_baseline_v14_context/current_score_probe.json`
- tactical suite: `docs/games/2026-05-13_exp5_current_baseline_v14_context/current_tactical_suite_300.json`
- gauntlet: `docs/games/2026-05-13_exp5_current_baseline_v14_context/current_gauntlet_30.json`
- gauntlet replay: `docs/games/2026-05-13_exp5_current_baseline_v14_context/current_gauntlet_30.jsonl`
- advanced score: `docs/games/2026-05-13_exp5_current_baseline_v14_context/current_advanced_score.json`

## Note

The 30-game gauntlet uses timed search. Use this run as the same-code baseline
for v14 adapter-context comparisons, and use the historical v10 `84.1482/100`
artifact as the high-water target.
