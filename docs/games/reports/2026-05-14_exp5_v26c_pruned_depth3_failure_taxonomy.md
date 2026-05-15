# Exp5 Failure Taxonomy

- Generated: `2026-05-14T18:47:00+00:00`
- Input: `redacted_private_detail_jsonl`
- Focus statuses: `rejected`
- Positions: `4624`
- Focus rows: `755`
- Focus rate: `0.1633`

公開報告只含 aggregate taxonomy，不含 FEN、走法、PV、source/chosen move 或逐題答案。

## By Section

| Section | Positions | Focus rows | Focus rate | Top taxonomy | Actionability |
|---|---:|---:|---:|---|---|
| `complete_game` | 2563 | 420 | 0.1639 | candidate_generation_or_search_miss:380, quiet_positional_ordering:349, endgame_conversion:194, pawn_structure_or_pawn_push:127 | candidate_generation_or_search_miss:380, top5_present_rerank_issue:40 |
| `tail10pct` | 261 | 35 | 0.1341 | candidate_generation_or_search_miss:32, quiet_positional_ordering:27, endgame_conversion:26, king_safety_open_file:20 | candidate_generation_or_search_miss:32, top5_present_rerank_issue:3 |
| `tail25pct` | 630 | 100 | 0.1587 | candidate_generation_or_search_miss:81, quiet_positional_ordering:69, endgame_conversion:58, king_safety_open_file:44 | candidate_generation_or_search_miss:81, top5_present_rerank_issue:19 |
| `tail50pct` | 1170 | 200 | 0.1709 | candidate_generation_or_search_miss:186, quiet_positional_ordering:156, endgame_conversion:131, pawn_structure_or_pawn_push:70 | candidate_generation_or_search_miss:186, top5_present_rerank_issue:14 |
