# Exp5 V26 Gate

This report is redacted: it contains no FENs, moves, teacher PVs, source game identifiers, or per-position answers.

- Baseline: `fixed_depth_fianchetto_tail_castle_guard`
- Candidate: `fixed_depth_fianchetto_tail_castle_guard_v27h_depth3_no_null_mate_net30`
- Primary objective: `weak_slice_rejected_reduction`
- Accepted: `True`

## Rejected Gates

| Section | Baseline rejected | Candidate rejected | Delta | Required max | Passed |
|---|---:|---:|---:|---:|---|
| complete_game | 453 | 402 | -51 | 407 | True |
| tail50pct | 205 | 183 | -22 | 184 | True |
| tail25pct | 126 | 101 | -25 | 113 | True |

## Secondary Metrics

- Total rejected baseline/candidate: `827` / `720`
- Clean rate baseline/candidate: `0.6572` / `0.6927`
- Review+ rate baseline/candidate: `0.8212` / `0.8443`
- Top5 rate baseline/candidate: `0.5149` / `0.5579`

## Anti-Leakage

- `no_fen`: `True`
- `no_moves`: `True`
- `no_teacher_pv`: `True`
- `no_source_game_ids`: `True`
- `no_exact_memory_or_position_lookup`: `True`
- `public_outputs_are_aggregate_only`: `True`

## Candidate/Search Miss

- `complete_game`: baseline `402`, candidate `352`, delta `-50`
- `tail10pct`: baseline `34`, candidate `26`, delta `-8`
- `tail25pct`: baseline `104`, candidate `78`, delta `-26`
- `tail50pct`: baseline `198`, candidate `172`, delta `-26`
