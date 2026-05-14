# Exp5 V26 Gate

This report is redacted: it contains no FENs, moves, teacher PVs, source game identifiers, or per-position answers.

- Baseline: `fixed_depth_fianchetto_tail_castle_guard`
- Candidate: `fixed_depth_fianchetto_tail_castle_guard_v26_endgame_safety`
- Primary objective: `weak_slice_rejected_reduction`
- Accepted: `False`

## Rejected Gates

| Section | Baseline rejected | Candidate rejected | Delta | Required max | Passed |
|---|---:|---:|---:|---:|---|
| complete_game | 475 | 485 | 10 | 427 | False |
| tail50pct | 209 | 205 | -4 | 188 | False |
| tail25pct | 127 | 131 | 4 | 114 | False |

## Secondary Metrics

- Total rejected baseline/candidate: `853` / `863`
- Clean rate baseline/candidate: `0.6458` / `0.6466`
- Review+ rate baseline/candidate: `0.8155` / `0.8134`
- Top5 rate baseline/candidate: `0.5324` / `0.532`

## Anti-Leakage

- `no_fen`: `True`
- `no_moves`: `True`
- `no_teacher_pv`: `True`
- `no_source_game_ids`: `True`
- `no_exact_memory_or_position_lookup`: `True`
- `public_outputs_are_aggregate_only`: `True`

## Candidate/Search Miss

- `complete_game`: baseline `429`, candidate `425`, delta `-4`
- `tail10pct`: baseline `35`, candidate `34`, delta `-1`
- `tail25pct`: baseline `111`, candidate `108`, delta `-3`
- `tail50pct`: baseline `196`, candidate `189`, delta `-7`
