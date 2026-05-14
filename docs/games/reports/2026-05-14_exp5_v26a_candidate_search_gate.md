# Exp5 V26 Gate

This report is redacted: it contains no FENs, moves, teacher PVs, source game identifiers, or per-position answers.

- Baseline: `fixed_depth_fianchetto_tail_castle_guard`
- Candidate: `fixed_depth_fianchetto_tail_castle_guard_v26a_candidate_search`
- Primary objective: `weak_slice_rejected_reduction`
- Accepted: `False`

## Rejected Gates

| Section | Baseline rejected | Candidate rejected | Delta | Required max | Passed |
|---|---:|---:|---:|---:|---|
| complete_game | 475 | 465 | -10 | 427 | False |
| tail50pct | 209 | 217 | 8 | 188 | False |
| tail25pct | 127 | 128 | 1 | 114 | False |

## Secondary Metrics

- Total rejected baseline/candidate: `853` / `854`
- Clean rate baseline/candidate: `0.6458` / `0.6492`
- Review+ rate baseline/candidate: `0.8155` / `0.8153`
- Top5 rate baseline/candidate: `0.5324` / `0.5305`

## Anti-Leakage

- `no_fen`: `True`
- `no_moves`: `True`
- `no_teacher_pv`: `True`
- `no_source_game_ids`: `True`
- `no_exact_memory_or_position_lookup`: `True`
- `public_outputs_are_aggregate_only`: `True`

## Candidate/Search Miss

- `complete_game`: baseline `429`, candidate `428`, delta `-1`
- `tail10pct`: baseline `35`, candidate `37`, delta `2`
- `tail25pct`: baseline `111`, candidate `110`, delta `-1`
- `tail50pct`: baseline `196`, candidate `202`, delta `6`
