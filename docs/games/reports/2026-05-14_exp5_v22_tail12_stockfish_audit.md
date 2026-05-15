# Stockfish Teacher Audit

- Generated: `2026-05-14T11:51:33+00:00`
- Stockfish binary: `/home/s92137/reference_repos/Stockfish/src/stockfish`
- Stockfish commit/reference: `dd321af5dfc0789de07c4e5c64915073995eb818`
- Depth: `8`, movetime_ms: `0`, MultiPV: `5`
- Positions analyzed: `50`
- Teacher rows: `50`
- Played clean rows: `34`
- Review rows: `9`
- Rejected rows: `7`

## No-Leak Policy

This report intentionally keeps only aggregate counts. Do not publish FENs,
question IDs, played moves, teacher moves, per-position CP losses, or rejected
row details from the held-out/tail validation material.

## Comparison

| Profile | Audited | Clean | Review | Rejected | Hard negatives |
|---|---:|---:|---:|---:|---:|
| v20 `fixed_depth_piece_activity_midgame` | 50 | 28 | 11 | 11 | 9 |
| v21b `fixed_depth_fianchetto_development` | 50 | 31 | 10 | 9 | 7 |
| v22 `fixed_depth_fianchetto_tail` | 50 | 34 | 9 | 7 | 8 |

v22 improves the tail-12 Stockfish audit aggregate versus v20/v21b, which
suggests better late-stage conversion and fewer obviously poor tail decisions.
It does not improve the fixed 30-game score, so it remains a candidate profile
rather than the production default.

## Score Context

| Profile | 30-game W-D-L | Score rate | Threefold | Normalized score |
|---|---:|---:|---:|---:|
| v20 | 23-7-0 | 0.8833 | 0.2333 | 90.1322 |
| v21b | 23-7-0 | 0.8833 | 0.2333 | 90.1322 |
| v22 | 23-7-0 | 0.8833 | 0.2333 | 90.1322 |

## Outputs

- `teacher_train_jsonl`: `/home/s92137/hackme_web/docs/games/evidence/exp5/v22_fianchetto_tail_tail12_stockfish_audit/stockfish_teacher_train_rows.jsonl`
- `teacher_eval_jsonl`: `/home/s92137/hackme_web/docs/games/evidence/exp5/v22_fianchetto_tail_tail12_stockfish_audit/stockfish_teacher_eval_rows.jsonl`
- `teacher_all_jsonl`: `/home/s92137/hackme_web/docs/games/evidence/exp5/v22_fianchetto_tail_tail12_stockfish_audit/stockfish_teacher_rows.jsonl`
- `played_clean_jsonl`: `/home/s92137/hackme_web/docs/games/evidence/exp5/v22_fianchetto_tail_tail12_stockfish_audit/stockfish_played_clean_rows.jsonl`
- `review_jsonl`: `/home/s92137/hackme_web/docs/games/evidence/exp5/v22_fianchetto_tail_tail12_stockfish_audit/stockfish_review_rows.jsonl`
- `rejected_jsonl`: `/home/s92137/hackme_web/docs/games/evidence/exp5/v22_fianchetto_tail_tail12_stockfish_audit/stockfish_rejected_rows.jsonl`
- `audit_detail_jsonl`: `/home/s92137/hackme_web/docs/games/evidence/exp5/v22_fianchetto_tail_tail12_stockfish_audit/stockfish_audit_detail.jsonl`
- `summary_json`: `/home/s92137/hackme_web/docs/games/evidence/exp5/v22_fianchetto_tail_tail12_stockfish_audit/summary.json`

## Interpretation

Clean played rows mean the source move agreed with Stockfish top-K or had small centipawn loss.
Teacher rows always train Stockfish's selected top move and keep the source move only as audit context or a hard negative.
The Stockfish binary is external and must not be committed unless GPLv3 distribution obligations are intentionally accepted.
