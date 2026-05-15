# Exp5 V28e Current Strongest Baseline

Date: 2026-05-15

V28e is promoted as the current strongest Exp5 search profile:

`fixed_depth_fianchetto_tail_castle_guard_v28e_depth3_no_null_mate_net30_fast_king_mobility4`

The previous baseline was V27k:

`fixed_depth_fianchetto_tail_castle_guard_v27k_depth3_no_null_mate_net30_defense_book`

## Change

V28e keeps the V27k search/eval balance and adds a narrow final low-legal check-evasion guard. The guard only activates in check with very few legal moves. Its fast king-mobility branch handles the observed failure mode where Exp5 chooses an edge-trapped king move while another legal king move preserves drawing resources.

V28e does not add broad king-pressure eval, broad pawn-structure eval, global search deepening, qdepth 3, runtime Stockfish use, validation-memory lookup, or validation answer priors.

## Evidence

Staged Blockfish 5-game screen:

| Profile | Result | Score |
| --- | ---: | ---: |
| V27k | 0W/3D/2L | 30% |
| V28e | 0W/4D/1L | 40% |

Percent-tail quick4 screen, same 4-question / 123-position subset:

| Profile | Clean | Review+ | Rejected | Top1 |
| --- | ---: | ---: | ---: | ---: |
| V27k | 65.04% | 80.49% | 24 | 17.89% |
| V28e | 65.04% | 80.49% | 24 | 18.70% |

Full percent-tail 100 was not run for this fast screen. The promotion is based on a better staged Blockfish result with no quick4 regression. Evidence is redacted in `docs/games/evidence/exp5/v28e_fast_king_mobility4_quick_gate_summary.json`.

## Decision

Promote V28e as the current strongest profile and keep V27k available for rollback.
