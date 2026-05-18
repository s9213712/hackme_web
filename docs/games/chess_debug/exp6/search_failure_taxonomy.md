# Exp6 Search Failure Taxonomy

This taxonomy is based on HalfKP v1 staged-prefix decision points, with exact FENs and moves redacted.

- Analysed decision points: `64`
- Mean Stockfish eval delta: `240.86cp`
- Max Stockfish eval delta: `750cp`
- Rows from drawn games: `44`
- Rows from lost games: `20`

Dominant failure modes:

- `positional_or_small_delta`: 34
- `horizon_effect`: 25
- `hanging_piece`: 5
- `king_safety`: 3

Interpretation: these are consequence-evaluation failures, not policy top-N failures.
The search ablation did not identify a patch strong enough to justify staged
testing.
