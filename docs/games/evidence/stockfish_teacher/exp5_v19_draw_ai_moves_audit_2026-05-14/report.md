# Stockfish Teacher Audit

- Generated: `2026-05-14T07:12:56+00:00`
- Stockfish binary: `/home/s92137/reference_repos/Stockfish/src/stockfish`
- Stockfish commit/reference: `dd321af5dfc0789de07c4e5c64915073995eb818`
- Depth: `8`, movetime_ms: `0`, MultiPV: `5`
- Positions analyzed: `587`
- Teacher rows: `587`
- Played clean rows: `368`
- Review rows: `111`
- Rejected rows: `108`

## Outputs

- `teacher_train_jsonl`: `/home/s92137/hackme_web/docs/games/evidence/stockfish_teacher/exp5_v19_draw_ai_moves_audit_2026-05-14/stockfish_teacher_train_rows.jsonl`
- `teacher_eval_jsonl`: `/home/s92137/hackme_web/docs/games/evidence/stockfish_teacher/exp5_v19_draw_ai_moves_audit_2026-05-14/stockfish_teacher_eval_rows.jsonl`
- `teacher_all_jsonl`: `/home/s92137/hackme_web/docs/games/evidence/stockfish_teacher/exp5_v19_draw_ai_moves_audit_2026-05-14/stockfish_teacher_rows.jsonl`
- `played_clean_jsonl`: `/home/s92137/hackme_web/docs/games/evidence/stockfish_teacher/exp5_v19_draw_ai_moves_audit_2026-05-14/stockfish_played_clean_rows.jsonl`
- `review_jsonl`: `/home/s92137/hackme_web/docs/games/evidence/stockfish_teacher/exp5_v19_draw_ai_moves_audit_2026-05-14/stockfish_review_rows.jsonl`
- `rejected_jsonl`: `/home/s92137/hackme_web/docs/games/evidence/stockfish_teacher/exp5_v19_draw_ai_moves_audit_2026-05-14/stockfish_rejected_rows.jsonl`
- `audit_detail_jsonl`: `/home/s92137/hackme_web/docs/games/evidence/stockfish_teacher/exp5_v19_draw_ai_moves_audit_2026-05-14/stockfish_audit_detail.jsonl`
- `summary_json`: `/home/s92137/hackme_web/docs/games/evidence/stockfish_teacher/exp5_v19_draw_ai_moves_audit_2026-05-14/summary.json`

## Interpretation

Clean played rows mean the source move agreed with Stockfish top-K or had small centipawn loss.
Teacher rows always train Stockfish's selected top move and keep the source move only as audit context or a hard negative.
The Stockfish binary is external and must not be committed unless GPLv3 distribution obligations are intentionally accepted.
