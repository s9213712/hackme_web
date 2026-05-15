# Exp5 Failure Taxonomy

- Generated: `2026-05-14T16:42:00+00:00`
- Input: `redacted_private_detail_jsonl`
- Focus statuses: `rejected`
- Positions: `4624`
- Focus rows: `863`
- Focus rate: `0.1866`

公開報告只含 aggregate taxonomy，不含 FEN、走法、PV、source/chosen move 或逐題答案。

## By Section

| Section | Positions | Focus rows | Focus rate | Top taxonomy | Actionability |
|---|---:|---:|---:|---|---|
| `complete_game` | 2563 | 485 | 0.1892 | candidate_generation_or_search_miss:425, quiet_positional_ordering:393, endgame_conversion:229, pawn_structure_or_pawn_push:191 | candidate_generation_or_search_miss:425, top5_present_rerank_issue:60 |
| `tail10pct` | 261 | 42 | 0.1609 | candidate_generation_or_search_miss:34, endgame_conversion:32, quiet_positional_ordering:31, king_safety_open_file:27 | candidate_generation_or_search_miss:34, top5_present_rerank_issue:8 |
| `tail25pct` | 630 | 131 | 0.2079 | candidate_generation_or_search_miss:108, quiet_positional_ordering:96, endgame_conversion:94, king_safety_open_file:66 | candidate_generation_or_search_miss:108, top5_present_rerank_issue:23 |
| `tail50pct` | 1170 | 205 | 0.1752 | candidate_generation_or_search_miss:189, quiet_positional_ordering:153, endgame_conversion:123, pawn_structure_or_pawn_push:69 | candidate_generation_or_search_miss:189, top5_present_rerank_issue:16 |
