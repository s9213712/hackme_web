# Exp5 Failure Taxonomy

- Generated: `2026-05-15T02:07:33+00:00`
- Input: `redacted_private_detail_jsonl`
- Focus statuses: `rejected`
- Positions: `4624`
- Focus rows: `827`
- Focus rate: `0.1788`

公開報告只含 aggregate taxonomy，不含 FEN、走法、PV、source/chosen move 或逐題答案。

## By Section

| Section | Positions | Focus rows | Focus rate | Top taxonomy | Actionability |
|---|---:|---:|---:|---|---|
| `complete_game` | 2563 | 453 | 0.1767 | candidate_generation_or_search_miss:402, quiet_positional_ordering:367, endgame_conversion:207, pawn_structure_or_pawn_push:193 | candidate_generation_or_search_miss:402, top5_present_rerank_issue:51 |
| `tail10pct` | 261 | 43 | 0.1648 | candidate_generation_or_search_miss:34, quiet_positional_ordering:32, endgame_conversion:31, king_safety_open_file:26 | candidate_generation_or_search_miss:34, top5_present_rerank_issue:9 |
| `tail25pct` | 630 | 126 | 0.2 | candidate_generation_or_search_miss:104, quiet_positional_ordering:86, endgame_conversion:79, king_safety_open_file:50 | candidate_generation_or_search_miss:104, top5_present_rerank_issue:22 |
| `tail50pct` | 1170 | 205 | 0.1752 | candidate_generation_or_search_miss:198, quiet_positional_ordering:152, endgame_conversion:117, pawn_structure_or_pawn_push:77 | candidate_generation_or_search_miss:198, top5_present_rerank_issue:7 |
