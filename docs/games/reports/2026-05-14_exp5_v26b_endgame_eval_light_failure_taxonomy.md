# Exp5 Failure Taxonomy

- Generated: `2026-05-14T17:26:11+00:00`
- Input: `redacted_private_detail_jsonl`
- Focus statuses: `rejected`
- Positions: `4624`
- Focus rows: `853`
- Focus rate: `0.1845`

公開報告只含 aggregate taxonomy，不含 FEN、走法、PV、source/chosen move 或逐題答案。

## By Section

| Section | Positions | Focus rows | Focus rate | Top taxonomy | Actionability |
|---|---:|---:|---:|---|---|
| `complete_game` | 2563 | 469 | 0.183 | candidate_generation_or_search_miss:423, quiet_positional_ordering:375, endgame_conversion:214, pawn_structure_or_pawn_push:197 | candidate_generation_or_search_miss:423, top5_present_rerank_issue:46 |
| `tail10pct` | 261 | 41 | 0.1571 | candidate_generation_or_search_miss:35, endgame_conversion:31, quiet_positional_ordering:31, king_safety_open_file:25 | candidate_generation_or_search_miss:35, top5_present_rerank_issue:6 |
| `tail25pct` | 630 | 127 | 0.2016 | candidate_generation_or_search_miss:106, quiet_positional_ordering:88, endgame_conversion:78, king_safety_open_file:53 | candidate_generation_or_search_miss:106, top5_present_rerank_issue:21 |
| `tail50pct` | 1170 | 216 | 0.1846 | candidate_generation_or_search_miss:199, quiet_positional_ordering:153, endgame_conversion:128, pawn_structure_or_pawn_push:81 | candidate_generation_or_search_miss:199, top5_present_rerank_issue:17 |
