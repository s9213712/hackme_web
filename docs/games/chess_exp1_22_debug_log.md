# Chess Exp1-22 Debug Log

This file records the debugging path that moved chess learning validation from ad hoc game outcomes toward auditable deterministic promotion evidence.

## Scope

- Engines: exp1 classic learning engine, exp3 DL engine, exp4 PV engine.
- Removed/deprecated engine: exp2 NN. Exp2 remains only for legacy artifact compatibility and old data references; it must not be exposed as a selectable frontend practice engine.
- Primary gate: deterministic strength snapshot plus checkpoint consistency, not stochastic full-game benchmark.
- Current status after exp22: promotion remains blocked. Semantic coverage and effective training weights are now balanced, but model capability still fails kingside/development classes and cp20 retention.

## Timeline

| Exp | Focus | Finding | Action / Result |
| --- | --- | --- | --- |
| exp1 | Baseline live-learning validation | Initial pipeline needed explicit replay / retrain evidence. | Added structured validation reports and checkpoint evidence. |
| exp2 | 30-game live retrain validation | Full games were slow, noisy, and not reproducible enough for promotion. | Deprecated heavy full-game benchmark as primary gate. |
| exp3 | Quick retrain gate | 30-game generation was a bottleneck. | Added quick gate using fixed trusted replay fixture and deterministic snapshots. |
| exp4 | Replay fixture diversity | Loss decreased but deterministic strength did not improve. | Added fixture health, dedupe, category distribution, and mistake-retention probe alignment. |
| exp5 | Sanity learning failure diagnosis | Expected move entered replay, but final decision did not change. | Verified encode/decode, legal mask, checkpoint load, and overfit-one-position path. |
| exp6 | Trainer / final decision semantics | Positive-only replay could raise expected policy without suppressing wrong legal moves; final decision was not raw argmax. | Added contrastive/ranking evidence and raw-policy vs final-decision learning split. |
| exp7 | Exact FEN vs variants | Exact and seen variants passed, unseen variants failed. | Added seen/unseen variant reporting and blocked promotion on lack of generalization. |
| exp8 | Unseen variant generalization | Search/static eval was not the only blocker. | Added curriculum variants and feature/generalization debug. |
| exp9 | Policy-search integration | Fusion did not create tactic/blunder regression, but raw policy still failed unseen cases. | Added fusion modes, override audit, and policy-search disagreement metrics. |
| exp10 | Raw policy unseen generalization | Hard negatives helped but did not solve held-out failures. | Added larger supervised variant split and failed-unseen case diagnostics. |
| exp11 | Board representation invariance | Low board embedding similarity indicated representation weakness. | Added invariance / consistency loss evidence and pairwise contrastive reporting. |
| exp12 | Checkpoint consistency | Some learning appeared only at later checkpoints. | Added checkpoint consistency table, embedding drift, retention chain, and instability detector. |
| exp13 | Early checkpoint stability | cp10 still failed minimum generalization and hard-negative margin. | Added early warmup, margin table, and context-scoped invariance examples. |
| exp14 | Ablation | Stronger hard-negative margin made results worse; labels looked questionable. | Ran fixed ablations and identified dataset label boundary as a risk. |
| exp15 | Label quality gate | Questionable labels polluted held-out evidence. | Split clean/questionable/invalid labels and excluded questionable labels from gate. |
| exp16 | Clean held-out set | Clean set became adequate enough to separate dataset issue from model issue. | Confirmed failure was model policy generalization, not leakage or label invalidity. |
| exp17 | Move semantics disentanglement | Model confused e-pawn, d-pawn, flank, and kingside pawn pushes. | Added semantic grouping, semantic hard negatives, board semantic features, and confusion matrix. |
| exp18 | Semantic embedding separation | Semantic boundary was still too soft. | Added semantic centroid analysis, inter/intra distances, confusion-driven sampling, and semantic margins. |
| exp19 | Semantic class balance | Kingside aggression bias could overpower central break classes. | Added semantic class distribution checks and style profile audit; promotion uses balanced profile only. |
| exp20 | Semantic-balanced clean gate set | Gate covered all semantic classes, revealing ability was localized mostly to e-pawn cases. | Added 45-case clean semantic gate with 5 classes x 3 difficulties x 3 cases. |
| exp21 | Semantic-balanced training set | Train/validation coverage was complete but sampling counts were still skewed. | Added semantic-balanced train/validation replay and train-to-gate gap reporting. |
| exp22 | Class-balanced sampling | Raw counts were still dominated by e-pawn at cp10 and flank at cp20. | Added inverse-frequency row weighting and effective semantic distribution gate. Sampling skew fixed; promotion still blocked by capability and retention failures. |

## Current Gate Evidence

- `deterministic_strength_snapshot` compares baseline, checkpoint@10, checkpoint@20, and final.
- `checkpoint_consistency` records exact retention, seen retention, clean held-out retention, hard held-out retention, embedding drift, policy margin drift, semantic confusion, semantic centroid distance, and semantic sampling skew.
- `semantic_sampling` records inverse-frequency sample weights and effective sample weight by semantic class.
- `mistake_retention_probe` distinguishes matched expected, repeated old mistake, and partial avoidance.
- `promotion_gate` must remain false if deterministic gate is skipped, retention regresses, poison/invalid gates fail, semantic coverage is missing, sampling is skewed, or any required semantic class has zero clean pass count.

## Exp22 Result Summary

- cp10 raw train distribution: e_pawn=28, d_pawn=9, flank=10, kingside=9, development=9.
- cp10 effective weight distribution: approximately 16.7-18.0 per semantic class; skew ratio 1.08.
- cp20 raw train distribution: e_pawn=10, d_pawn=9, flank=27, kingside=9, development=9.
- cp20 effective weight distribution: approximately 16.4-18.5 per semantic class; skew ratio 1.12.
- Sampling gate passed. `semantic_sampling_skew` is no longer the blocker.
- Clean gate still failed: kingside and development remained 0/9; cp20 exact / mistake retention regressed.
- Promotion remains blocked.

## Implementation Notes

- exp3 and exp4 share the validation pipeline, quick gate, semantic-balanced replay fixture, deterministic strength snapshot, checkpoint consistency, and reporting.
- exp3 trainer applies weighted contrastive replay with semantic memory / invariance support.
- exp4 trainer applies weighted PV policy/value replay with contrastive hard-negative training.
- Full-game benchmark is only `stochastic_auxiliary`; it cannot independently promote a model.
- Perft, runtime, replay loss, and hash change are diagnostics only; none are accepted as proof of learning success.

## Open Risks

- Semantic-balanced sampling fixed training weight skew but did not fix model generalization.
- Development and kingside classes need better representation or architecture-level support, not just more gate logic.
- cp20 can still lose cp10 exact/mistake retention, so retention stabilization remains a hard blocker.
- The quick gate is faster than 30-game validation but still heavy because sanity final-decision evaluation runs many clean held-out cases.
