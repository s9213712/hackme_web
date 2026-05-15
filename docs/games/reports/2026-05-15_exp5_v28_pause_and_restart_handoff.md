# Exp5 V28 Pause And Restart Handoff

Date: 2026-05-15

Status: experiments paused. Use this document as the handoff point before
restarting any Exp5 chess-strength work.

## Current Accepted Baseline

| Item | Value |
|---|---|
| Branch | `03.Points` |
| Accepted commit | `5414b21` |
| Commit message | `games/chess: promote exp5 v28e king escape profile` |
| Production profile | `fixed_depth_fianchetto_tail_castle_guard_v28e_depth3_no_null_mate_net30_fast_king_mobility4` |
| Staged Blockfish 5 | `0W/4D/1L`, score `40%` |
| Previous baseline | V27k, `0W/3D/2L`, score `30%` |

V28e is the strongest accepted profile at the pause point. Do not restart from
V28f, V28g, V28h, V28i, V28j, or V28k unless the goal is to reproduce a rejected
experiment.

## Condensed Timeline

| Phase | Outcome |
|---|---|
| Early Exp5 scoring | Internal score reached the old 90+ range, but the score lost discrimination and was treated as insufficient proof of engine strength. |
| Replay retrain review | Directly training replay rows into the main model often regressed, so auto-retrain was disconnected while replay recording and filtering stayed enabled. |
| Stockfish/Blockfish teacher | Local Stockfish became an offline teacher, auditor, PGN filter, and sparring opponent. It is not bundled and is not used at runtime. |
| V24 expanded validation | Redacted 100-scenario validation became the stable held-out baseline. It showed tactical/rule strength but weaker long-tail and complete-game generalization. |
| V26/V27 search work | Multiple candidate/search and evaluator experiments were screened. V27k became the accepted baseline with staged Blockfish score `30%`. |
| V28e | Small generic king-escape mobility repair improved staged Blockfish score to `40%` without replacing the validation baseline. |
| V28f-V28k | Low-legal pressure and wider mate scans exposed a real mate-net blind spot, but the tested fixes either regressed or were too slow. |

## Accepted Evidence Summary

Public evidence must stay redacted. The accepted V28e evidence records only
aggregate outcomes and does not expose FEN, moves, teacher PV, source games,
chosen moves, or expected answers.

| Evidence | Summary |
|---|---|
| `docs/games/reports/2026-05-15_exp5_v28e_current_strongest_baseline.md` | Human-readable V28e baseline report |
| `docs/games/evidence/exp5/v28e_fast_king_mobility4_quick_gate_summary.json` | Redacted quick-gate summary |
| private staged replay | Complete replay JSONL retained outside public docs |

Private runtime material belongs outside the repo, currently under:

```text
/home/s92137/hackme_web_private/runtime/private/games/exp5/
```

Do not move that directory back into `runtime/` inside the repository.

## Rejected Post-V28e Attempts

| Version | Direction | Result | Decision |
|---|---|---|---|
| V28f | Low-legal pressure | Regressed a known open-game survival line | Rejected |
| V28g | Legal-3 pressure | No improvement over V28e | Rejected |
| V28h | Low-legal mate scan 12 | Improved one collapse line but increased runtime and did not improve staged score | Rejected for now |
| V28i | Low-legal mate scan 10 | Longer survival on one line, but far too slow | Rejected |
| V28j | Prefiltered mate scan 10 | Still too slow and incomplete in targeted screening | Rejected |
| V28k | Truncated mate scan 7 | Timed out before producing useful staged evidence | Rejected |

The useful signal from V28h-V28k is not the patch itself. The signal is that the
current forced-checking-mate helper can miss mate nets when the opponent has too
many root checking moves, while widening that search naively is too expensive.

## Technical Diagnosis

The most recent accepted improvement came from a small, generic king-escape
profile adjustment. Broad evaluator pressure terms, broad pawn-structure terms,
global qdepth increases, and heavier low-legal pressure rules have repeatedly
regressed or failed to improve the staged Blockfish score.

Current likely bottleneck:

- candidate/search miss in tactical collapse positions
- expensive mate-net verification when root checking moves exceed the current
  cheap helper's cap
- inability to cheaply preserve critical defensive/escape candidates without
  making the whole engine slower

Do not restart by adding another broad evaluator toggle. The next useful patch
should be a small, cached, root-only or near-root tactical verifier that targets
the known blind spot without changing V28e scoring balance.

## Restart Checklist

1. Confirm branch and baseline:

```bash
cd /home/s92137/hackme_web
git rev-parse --abbrev-ref HEAD
git log -1 --oneline
```

2. Confirm the production profile still points to V28e.

3. Confirm private data is outside the repo:

```text
/home/s92137/hackme_web_private/runtime/private/games/exp5/
```

4. Run static/smoke checks before editing:

```bash
PYTHONPATH=. python3 -m py_compile services/games/chess_nnue.py scripts/games/chess_exp5_blockfish_match.py scripts/games/chess_exp5_restart_smoke.py
PYTHONPATH=. pytest -q tests/games/test_chess_exp5_architecture.py
```

5. Use a fast targeted Blockfish screen before any full 100-question validation.

6. Run the staged five-game Blockfish comparison only after the fast screen does
   not regress.

7. Run percent-tail or expanded validation only after the candidate beats or
   matches V28e on staged play.

8. Publish only redacted aggregate evidence.

## Re-enable Criteria

A new candidate may replace V28e only if it satisfies all of these:

- No known V28e draw line becomes a loss.
- Staged Blockfish 5 is at least `0W/4D/1L`, preferably better.
- Quick percent-tail screening does not materially regress clean/review+
  metrics.
- Runtime remains acceptable; a single targeted game must not become a
  multi-minute blocker unless the user explicitly opts into a deep diagnostic.
- Public evidence remains redacted.
- The implementation is generic and does not memorize validation positions,
  exact move answers, source games, or teacher PV.

## Current Research Queue

Recommended next work, in order:

1. Build a faster bounded mate-net detector using caching and stricter root
   triggers.
2. Preserve critical king escape, block, and capture candidates only when the
   root position is tactically dangerous.
3. Add a fast-screen harness profile that prints progress every game and stops
   early on clear regression.
4. Revisit UCI/Stockfish teacher labeling only as offline training/evaluation
   support, not as runtime assistance.
5. Keep auto-retrain disconnected until replay learning has a promotion gate
   that proves it does not regress the accepted baseline.

## Explicit Pause Rules

- Do not run auto-retrain.
- Continue recording games and filtering useful replays.
- Do not feed validation answers into the model, opening book, or prior tables.
- Do not commit private replay/question/detail files.
- Do not publish FEN, moves, PV, source game ids, or per-question answers.
