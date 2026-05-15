# Exp5 Failure Taxonomy

- Generated: `2026-05-14T20:47:30+00:00`
- Input: `redacted_private_detail_jsonl`
- Focus statuses: `rejected`
- Positions: `4624`
- Focus rows: `744`
- Focus rate: `0.1609`

公開報告只含 aggregate taxonomy，不含 FEN、走法、PV、source/chosen move 或逐題答案。

## By Section

| Section | Positions | Focus rows | Focus rate | Top taxonomy | Actionability |
|---|---:|---:|---:|---|---|
| `complete_game` | 2563 | 408 | 0.1592 | candidate_generation_or_search_miss:371, quiet_positional_ordering:341, endgame_conversion:187, pawn_structure_or_pawn_push:127 | candidate_generation_or_search_miss:371, top5_present_rerank_issue:37 |
| `tail10pct` | 261 | 35 | 0.1341 | quiet_positional_ordering:28, candidate_generation_or_search_miss:27, endgame_conversion:26, king_safety_open_file:22 | candidate_generation_or_search_miss:27, top5_present_rerank_issue:8 |
| `tail25pct` | 630 | 107 | 0.1698 | candidate_generation_or_search_miss:86, quiet_positional_ordering:78, endgame_conversion:67, king_safety_open_file:48 | candidate_generation_or_search_miss:86, top5_present_rerank_issue:21 |
| `tail50pct` | 1170 | 194 | 0.1658 | candidate_generation_or_search_miss:184, quiet_positional_ordering:150, endgame_conversion:119, pawn_structure_or_pawn_push:63 | candidate_generation_or_search_miss:184, top5_present_rerank_issue:10 |
