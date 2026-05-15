# Exp5 Failure Taxonomy

- Generated: `2026-05-15T07:37:10+00:00`
- Input: `redacted_private_detail_jsonl`
- Focus statuses: `rejected`
- Positions: `4624`
- Focus rows: `712`
- Focus rate: `0.154`

公開報告只含 aggregate taxonomy，不含 FEN、走法、PV、source/chosen move 或逐題答案。

## By Section

| Section | Positions | Focus rows | Focus rate | Top taxonomy | Actionability |
|---|---:|---:|---:|---|---|
| `complete_game` | 2563 | 397 | 0.1549 | candidate_generation_or_search_miss:349, quiet_positional_ordering:329, endgame_conversion:179, king_safety_open_file:126 | candidate_generation_or_search_miss:349, top5_present_rerank_issue:48 |
| `tail10pct` | 261 | 33 | 0.1264 | quiet_positional_ordering:26, candidate_generation_or_search_miss:25, endgame_conversion:25, king_safety_open_file:21 | candidate_generation_or_search_miss:25, top5_present_rerank_issue:8 |
| `tail25pct` | 630 | 100 | 0.1587 | candidate_generation_or_search_miss:78, quiet_positional_ordering:68, endgame_conversion:62, king_safety_open_file:40 | candidate_generation_or_search_miss:78, top5_present_rerank_issue:22 |
| `tail50pct` | 1170 | 182 | 0.1556 | candidate_generation_or_search_miss:172, quiet_positional_ordering:143, endgame_conversion:115, pawn_structure_or_pawn_push:63 | candidate_generation_or_search_miss:172, top5_present_rerank_issue:10 |
