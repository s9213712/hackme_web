# HalfKP v1 Failure Taxonomy

Exact FENs and moves are redacted to avoid leaking staged content. Use `position_id` only to correlate private diagnostic rows.

- JSONL: `/home/s92137/hackme_web/runtime/private/games/exp6/halfkp_v1_failure_taxonomy.jsonl`
- Analysed positions: `64`
- Games covered: `{'g01': 12, 'g02': 20, 'g03': 16, 'g04': 16}`

## Category Counts

- `positional_or_small_delta`: 34
- `horizon_effect`: 25
- `hanging_piece`: 5
- `king_safety`: 3

## Largest Deltas

- `246f161d581c603d` g03 ply 26: delta `750cp`, tags `horizon_effect`
- `06ff4a59d5a364ce` g02 ply 39: delta `564cp`, tags `horizon_effect`
- `1dfb58e026fec11c` g03 ply 6: delta `545cp`, tags `horizon_effect`
- `3b2f9bedad5e436f` g04 ply 9: delta `507cp`, tags `horizon_effect`
- `82af99f7a33310d5` g01 ply 16: delta `500cp`, tags `horizon_effect`
- `00a3ff9aa9c80f5c` g01 ply 34: delta `449cp`, tags `horizon_effect`
- `c2657719d69a40b5` g02 ply 3: delta `445cp`, tags `horizon_effect`
- `ffd68763f6c6a36a` g03 ply 34: delta `423cp`, tags `hanging_piece`
- `641022dc09dd10ed` g04 ply 35: delta `401cp`, tags `horizon_effect`
- `5daee1c373c99581` g04 ply 39: delta `401cp`, tags `horizon_effect`
- `0187382b8f9f9af3` g03 ply 4: delta `387cp`, tags `horizon_effect`
- `ffee8715b40a68ff` g03 ply 28: delta `384cp`, tags `horizon_effect`
