# Exp5 Failure Taxonomy

- Generated: `2026-05-14T14:17:14+00:00`
- Input: `redacted_private_detail_jsonl`
- Focus statuses: `rejected`
- Positions: `4624`
- Focus rows: `853`
- Focus rate: `0.1845`

公開報告只含 aggregate taxonomy，不含 FEN、走法、PV、source/chosen move 或逐題答案。

## By Section

| Section | Positions | Focus rows | Focus rate | Top taxonomy | Actionability |
|---|---:|---:|---:|---|---|
| `complete_game` | 2563 | 475 | 0.1853 | candidate_generation_or_search_miss:429, quiet_positional_ordering:378, endgame_conversion:213, pawn_structure_or_pawn_push:191 | candidate_generation_or_search_miss:429, top5_present_rerank_issue:46 |
| `tail10pct` | 261 | 42 | 0.1609 | candidate_generation_or_search_miss:35, endgame_conversion:33, quiet_positional_ordering:33, king_safety_open_file:28 | candidate_generation_or_search_miss:35, top5_present_rerank_issue:7 |
| `tail25pct` | 630 | 127 | 0.2016 | candidate_generation_or_search_miss:111, quiet_positional_ordering:89, endgame_conversion:83, king_safety_open_file:56 | candidate_generation_or_search_miss:111, top5_present_rerank_issue:16 |
| `tail50pct` | 1170 | 209 | 0.1786 | candidate_generation_or_search_miss:196, quiet_positional_ordering:156, endgame_conversion:126, pawn_structure_or_pawn_push:80 | candidate_generation_or_search_miss:196, top5_present_rerank_issue:13 |
