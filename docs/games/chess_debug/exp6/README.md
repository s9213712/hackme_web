# Exp6 Debug Docs

Status: paused for development. The runtime champion remains locked.

Start here:

1. `frontend_backend_pause_handover.md` - production wiring status and restart checklist.
2. `evaluator_search_path_audit.md` - runtime and official staged-gate call path.
3. `evaluator_search_experiment.md` - HalfKP v1 candidate result.
4. `halfkp_v1_failure_taxonomy.md` - redacted failure taxonomy.
5. `search_ablation_report.md` - search-only ablation result.
6. `next_evaluator_candidate_plan.md` - value-only restart direction.

Rules while paused:

- Do not modify or promote the locked champion.
- Do not enable policy-rerank or root policy bonus.
- Do not persist raw staged FENs or moves.
- Use `chess_exp6_curriculum.play_staged_test()` for any future promotion gate.
