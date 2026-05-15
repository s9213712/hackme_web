# Exp5 Failure Taxonomy

- Generated: `2026-05-14T16:38:45+00:00`
- Input: `redacted_private_detail_jsonl`
- Focus statuses: `rejected`
- Positions: `4624`
- Focus rows: `854`
- Focus rate: `0.1847`

公開報告只含 aggregate taxonomy，不含 FEN、走法、PV、source/chosen move 或逐題答案。

## By Section

| Section | Positions | Focus rows | Focus rate | Top taxonomy | Actionability |
|---|---:|---:|---:|---|---|
| `complete_game` | 2563 | 465 | 0.1814 | candidate_generation_or_search_miss:428, quiet_positional_ordering:381, endgame_conversion:219, pawn_structure_or_pawn_push:176 | candidate_generation_or_search_miss:428, top5_present_rerank_issue:37 |
| `tail10pct` | 261 | 44 | 0.1686 | quiet_positional_ordering:37, candidate_generation_or_search_miss:37, endgame_conversion:32, king_safety_open_file:29 | candidate_generation_or_search_miss:37, top5_present_rerank_issue:7 |
| `tail25pct` | 630 | 128 | 0.2032 | candidate_generation_or_search_miss:110, quiet_positional_ordering:95, endgame_conversion:85, king_safety_open_file:58 | candidate_generation_or_search_miss:110, top5_present_rerank_issue:18 |
| `tail50pct` | 1170 | 217 | 0.1855 | candidate_generation_or_search_miss:202, quiet_positional_ordering:165, endgame_conversion:132, pawn_structure_or_pawn_push:77 | candidate_generation_or_search_miss:202, top5_present_rerank_issue:15 |
