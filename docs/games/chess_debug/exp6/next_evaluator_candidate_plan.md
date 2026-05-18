# Next Evaluator Candidate Plan

Policy-rerank remains paused. The next candidate should improve value/search consequence judgement.

Recommended order:

1. Add a stronger private after-board regression suite using redacted position IDs, not exact staged FENs in docs.
2. Do not stage the current search-only patches from `search_ablation_report.md`; none reduced failure deltas enough.
3. Only if fixed-FEN sanity passes, run the staged 4-game early gate.
4. If search-only ablations do not reduce failure deltas, do not train a new model from staged FENs. Instead train on generic curriculum/Stockfish-labelled positions with value-only targets.

Allowed value-only additions:

- mate-distance target
- tactical swing target
- SEE/material swing features
- king exposure features
- passed-pawn / promotion-race features

Still forbidden:

- policy target
- root policy bonus
- top-N rerank workaround
- champion modification
- storing exact staged FENs/moves in docs or handover
