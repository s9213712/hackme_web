# Exp5 Failure Taxonomy

- Generated: `2026-05-15T02:07:33+00:00`
- Input: `redacted_private_detail_jsonl`
- Focus statuses: `rejected`
- Positions: `4624`
- Focus rows: `720`
- Focus rate: `0.1557`

公開報告只含 aggregate taxonomy，不含 FEN、走法、PV、source/chosen move 或逐題答案。

## By Section

| Section | Positions | Focus rows | Focus rate | Top taxonomy | Actionability |
|---|---:|---:|---:|---|---|
| `complete_game` | 2563 | 402 | 0.1568 | candidate_generation_or_search_miss:352, quiet_positional_ordering:333, endgame_conversion:181, king_safety_open_file:128 | candidate_generation_or_search_miss:352, top5_present_rerank_issue:50 |
| `tail10pct` | 261 | 34 | 0.1303 | candidate_generation_or_search_miss:26, quiet_positional_ordering:26, endgame_conversion:25, king_safety_open_file:21 | candidate_generation_or_search_miss:26, top5_present_rerank_issue:8 |
| `tail25pct` | 630 | 101 | 0.1603 | candidate_generation_or_search_miss:78, quiet_positional_ordering:69, endgame_conversion:63, king_safety_open_file:41 | candidate_generation_or_search_miss:78, top5_present_rerank_issue:23 |
| `tail50pct` | 1170 | 183 | 0.1564 | candidate_generation_or_search_miss:172, quiet_positional_ordering:144, endgame_conversion:116, pawn_structure_or_pawn_push:64 | candidate_generation_or_search_miss:172, top5_present_rerank_issue:11 |
