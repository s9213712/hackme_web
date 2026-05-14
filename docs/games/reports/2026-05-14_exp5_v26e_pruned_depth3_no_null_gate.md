# Exp5 V26 Gate

This report is redacted: it contains no FENs, moves, teacher PVs, source game identifiers, or per-position answers.

- Baseline: `fixed_depth_fianchetto_tail_castle_guard`
- Candidate: `fixed_depth_fianchetto_tail_castle_guard_v26e_pruned_depth3_no_null`
- Primary objective: `weak_slice_rejected_reduction`
- Accepted: `False`

## Rejected Gates

| Section | Baseline rejected | Candidate rejected | Delta | Required max | Passed |
|---|---:|---:|---:|---:|---|
| complete_game | 475 | 408 | -67 | 427 | True |
| tail50pct | 209 | 194 | -15 | 188 | False |
| tail25pct | 127 | 107 | -20 | 114 | True |

## Secondary Metrics

- Total rejected baseline/candidate: `853` / `744`
- Clean rate baseline/candidate: `0.6458` / `0.6771`
- Review+ rate baseline/candidate: `0.8155` / `0.8391`
- Top5 rate baseline/candidate: `0.5324` / `0.5653`

## Anti-Leakage

- `no_fen`: `True`
- `no_moves`: `True`
- `no_teacher_pv`: `True`
- `no_source_game_ids`: `True`
- `no_exact_memory_or_position_lookup`: `True`
- `public_outputs_are_aggregate_only`: `True`

## Candidate/Search Miss

- `complete_game`: baseline `429`, candidate `371`, delta `-58`
- `tail10pct`: baseline `35`, candidate `27`, delta `-8`
- `tail25pct`: baseline `111`, candidate `86`, delta `-25`
- `tail50pct`: baseline `196`, candidate `184`, delta `-12`
