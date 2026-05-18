# Exp6 Handover — chess neural-network engine (v6.2 S2 era)

**Status**: runtime champion = **v6.2 S2** (locked, untouched). All
subsequent candidates (v7.x, v8.x, v9.x) failed promotion gates and
are preserved as diagnostic checkpoints only.

**Generated**: 2026-05-18 for handover to next AI agent.

---

## 0. TL;DR

| | |
|---|---|
| **Runtime model** | `/runtime/games/models/chess_experiment_6_neural.npz` (chmod 444, md5 `1c27627a...`) |
| **Champion identity** | v6.2 curriculum stage 2 (S2) — staged-10 vs Stockfish 1-5 = -25/40 (0W/5D/5L) |
| **Lock** | `/runtime/games/models/CHAMPION_LOCK.md` |
| **Promotion gates** | Dual: (1) ≥55% in ≥30-game match vs champion AND (2) staged-10 ≥ -25 |
| **Last attempt outcome** | v10 opening-principles search overlay improved v6.2 S2 staged-10 to -19/40 with H2H neutral vs baseline; now default-on, opt out with EXP6_OPENING_PRINCIPLES=0 |
| **Open problem** | Distribution shift — supervised training improves dev metrics but doesn't translate to better Stockfish-staged play |

---

## 1. Architecture

### NN evaluator (`/services/games/chess_neural.py`)
- **Input dim**: 774 (768 piece-square one-hots + 6 state bits: side-to-move, 4× castling rights, en-passant flag)
- **Hidden**: 256 → 32 (clipped-ReLU [0, 127])
- **Output**: scalar cp residual (white-perspective)
- **Total params**: ~200K
- **Eval composition**: `cp(board) = material_balance + piece_square_table + NN_residual` — material+PST baseline + NN residual (v6.2 design)
- **PIECE_VALUES_CP**: P=100, N=320, B=330, R=500, Q=900, K=0
- **PSTs**: Sunfish-style piece-square tables for each piece type

### Search (`/services/games/chess_search.py` + `chess_exp6.py`)
- Alpha-beta + quiescence with TT, PVS, LMR, futility pruning
- Production profile = `balanced` (depth 2 + quiescence 2)
- Profiles: `fast` (d1q1), `balanced` (d2q2), `strong` (d3q3), `fixed_depth_d2`, `fixed_depth_d3`
- **v9.4 hybrid feature**: `EXP6_HYBRID_ENDGAME_D3=1` env var → use d3 when piece_count ≤ 10. Code is in `_resolve_search_profile`. **A/B showed zero effect on staged-10** (games end in middlegame before reaching endgame trigger). Left in place for runtime user-side endgame.

### Datasets

| Asset | Size | Path | Purpose |
|---|---|---|---|
| 1000 quality games | 1K games | `quality_1000_games.jsonl` | v1-v8 source |
| 1K labels (depth 4) | 97,592 positions | `curriculum_labels.jsonl` | v3-v7 training |
| 1K played moves | 98,690 pairs | `played_moves.jsonl` | v7.3 ranking |
| 10K quality games | 10K games | `quality_10k_games.jsonl` | v9 source |
| 10K labels (depth 4) | 905,068 positions | `curriculum_labels_10k.jsonl` | v9 training |
| 10K played moves | 915,953 pairs | `played_moves_10k.jsonl` | v9 ranking |
| Failure dataset | 112 positions (depth 6 relabeled) | `v9_5_failure_positions.jsonl` | v9.5 active-learning attempt |

All labels include `cp_white`, `outcome_white`, `label_depth`. Stockfish at depth 4 was used for v3-v9.3. Failure positions re-labeled at depth 6 with multipv=1 (so `stockfish_best_move` field is available per row).

Game-id shuffle seed = `20260516` (must match between extract_played_moves and curriculum scripts; this was a v9 debug landmine — see chess_exp6_extract_played_moves.py).

---

## 2. Experiment history (chronological)

### v1-v5: cp regression hyperparameter tuning
- v1 (depth-10 labels): regressed below baseline
- v2-v5: depth-4 + outcome blend; all converged at **+6/40 ceiling** (best staged-10 = -28 / 0W/4D/6L)
- See `~/exp6_output/v{1,2,3,4,5}_curriculum_report.{md,json}`

**Diagnosis**: 1K supervised plateaued. Audit identified 5 issues: mate outliers, missing state bits, ranking vs cp regression, cumulative warm-start drift, latter-50% bias.

### v6.0-v6.2: residual eval breakthrough
- v6.0/v6.1: material baseline + NN residual + cp regression → regressed (random NN noise hurt search)
- **v6.2**: material + PST baseline + NN residual + cp regression with PST positional differentiation → first stable runtime model
- v6.2 S2 (cumulative 200 games) hit -25/40 (5 draws) — promoted to runtime

### v7.x: 1K + improved supervised losses (all REJECTED)
- v7.1: cp Huber + tanh(cp/600) value target, game-id 900/100 split
- v7.2: + 0.04 ply-weighted outcome aux
- v7.3: + 0.15 logistic afterstate ranking
- **All three: 0W/27D/3L = 45% in 30-game match vs v6.2 S2** (identical numbers)
- 1K labels insufficient for supervised+ranking to break the v6.2 ceiling

### v8.x: TDLeaf self-play — ABANDONED
- depth-2 NN-only self-play deadlocks at all-draws (W0/D20/L0)
- Even with ε-greedy 0.15, random-FEN start (60% prob), imbalanced |cp|>100 starts
- Cause: two identical engines + depth-2 search → repetition equilibrium
- Without decisive games, TD targets are all ~0 → degenerate training

### v9.x: 10K supervised — first breakthrough, then regression
- **v9.3** (10K + same v7.3 ranking pipeline):
  - Dev metrics improved significantly (huber 0.0108, sign 77%, rank_acc 68%)
  - 30-game match vs v6.2 S2: **2W/28D/0L = 53.33%** — first wins, no losses
  - BUT staged-10 vs Stockfish: -31/40 (3D, 7L) — regression from v6.2 S2's -25
  - Failed Gate 2 → not promoted, archived as breakthrough checkpoint
  - **Snapshot**: `~/exp6_output/v7_3_snapshots/v9_3_best.npz`
- **v9.4 search-hybrid**: endgame-d3 hybrid had ZERO effect (games end in middlegame). Trigger never fires.
- **v9.5a active-failure**: 112 v9.3-vs-Stockfish failure positions, re-labeled at SF d6, 5x oversample + ranking weight 0.30 → **staged-10 collapsed to -40/40 (0%)**. Failure data over-training broke broad eval.
  - Snapshot renamed to `v9_5a_FAILED_staged0.npz` as warning
- **v9.5b conservative failure-only** (post-handover 2026-05-18): seeded from v9.3, trained only the 112 failure rows, lr=1e-4, epochs=6/7, oversample=1, failure ranking weight=0.15 → **staged-10 = -28/40 (0W/4D/6L)**. This partially repairs v9.3 (+3 score) but still misses Gate 2 by 3 points.
  - Snapshot: `~/exp6_output/v9_5_snapshots/v9_5b_failure_only_best_staged_minus28.npz`
  - Report: `~/exp6_output/v9_5b_failure_only_best_report.json`
- **v9.5b mixed base+failure probe** (post-handover 2026-05-18): seeded from v9.3, full 10K base + 112 failure rows, lr=1e-4, 1 epoch, failure ranking weight=0.15 → **staged-10 = -37/40 (0W/1D/9L)**. Full-base continuation from v9.3 is still unsafe even with conservative failure weighting.
  - Report: `~/exp6_output/v9_5b_mixed_v93_lr1e4_e1_FAILED_staged_minus37_report.json`

### v10: search-side opening principles — PROMISING, env-gated
- **Diagnosis**: v6.2 S2 staged traces show repeated early flank-pawn/rook/queen/king moves (`a2a4`, `b2b4`, `h2h4`, `b7b5`) before development. The loss pattern is an opening-policy gap, not an endgame-depth issue.
- **Implementation**: `services/games/chess_exp6.py` now enables opening principles by default (`EXP6_OPENING_PRINCIPLES=0` disables it). Exp6 adds a small early-opening principle score to move ordering and applies a conservative post-search filter only for non-tactical bad early moves (not in check, no capture/check/promotion/castle).
- **Gate 2 result**: v6.2 S2 + `EXP6_OPENING_PRINCIPLES=1` staged-10 = **0W/7D/3L = -19/40**, beating champion baseline -25 by +6.
- **Routes-level exp5 comparison**: via `routes.games.choose_computer_move`, exp5 = **0W/4D/6L = -28/40**, exp6 default = **0W/6D/4L = -22/40**. This confirms default Exp6 now surpasses Exp5 on the app dispatcher path too.
- **H2H sanity**: principles overlay vs baseline search, same v6.2 weights, 30 games = **0W/30D/0L = 50%**. Neutral vs baseline; not a model promotion candidate by Gate 1, but no direct self-play regression seen.
- **Reports**:
  - `~/exp6_output/v10_opening_principles_staged_s2.json`
  - `~/exp6_output/v10_opening_principles_vs_baseline_match.json`
  - `~/exp6_output/v10_exp6_default_vs_exp5_routes_staged.json`

---

## 3. Hard-won lessons

1. **Loss decrease ≠ play improvement**. dev_huber went down all the way from 0.0169 (v6.2 S2) to 0.0107 (v9.5a) but staged-10 hit BOTTOM at -40. Dev set is elite-game distribution; play distribution is different.

2. **Match-gating is essential**. Without it we would have promoted v7.x or v9.5a and silently regressed. Lock file + chmod 444 was a useful guardrail.

3. **The +6 ceiling is real at 1K scale**. v2/v3/v4/v5 all bounce around -25 to -31. 1K + supervised cannot break it regardless of loss shape (cp, cp+outcome, cp+rank).

4. **10K data DOES unlock the breakthrough** in H2H but **doesn't fix generalization**. v9.3 wins 2 vs champion but loses more to Stockfish.

5. **Self-play at depth-2 is structurally degenerate**. Same-weights opponents converge to threefold rep. Tried: random mid-game start, |cp|>100 imbalanced FEN start, ε-greedy 0.07/0.10/0.15 — none broke the deadlock.

6. **Active-failure mining is brittle**. 112 hard positions × 5x oversample + 0.30 rank weight → model over-fit those 560 cases at expense of broad ranking. A conservative failure-only fine-tune improved v9.3 from -31 to -28, but mixed full-base continuation regressed to -37. Small failure data can move lines, but it does not solve the distribution shift.

7. **Endgame-d3 hybrid is useless in production match** (games don't reach endgame). Theoretical max benefit is small; user-vs-engine endgame might still benefit, but not engineable to fix v9.3's regression.

8. **FEN-matching across data files is fragile**. v9.3 first run silently dropped 99% of labels because played_moves was extracted from raw `quality_*.jsonl` while labels used SHUFFLE_SEED-shuffled order. Always confirm the join key count!

9. **Opening policy matters more than extra qsearch right now**. qchecks/order/check-extension ablations all regressed or failed to beat baseline. The first clear search-side gain came from preventing obvious early opening-policy violations.

---

## 4. Promotion gate (current policy)

Per `CHAMPION_LOCK.md`:

**Gate 1 — Head-to-head**: candidate ≥55% win rate vs v6.2 S2 in
≥30 game match (`chess_exp6_match.py --search-profile fixed_depth_d2`,
mixed openings, color swap) AND wins ≥ losses.

**Gate 2 — Stockfish generalization**: candidate staged-10 vs
Stockfish 1-5 score ≥ -25/40 (v6.2 S2's baseline).

Both required. v9.3 = (53.33%, -31) → Gate 1 close, Gate 2 fail.

---

## 5. File map

### Source scripts (`/scripts/games/`)
| File | Purpose |
|---|---|
| `chess_exp6_curriculum.py` | v3-v6.2 training (1K, curriculum stages, baseline + Stockfish labelling) |
| `chess_exp6_download_quality.py` | Download + filter quality games (10K target supported via `--target`) |
| `chess_exp6_extract_played_moves.py` | Build (game_idx, fen)→played_move map. Use `--source` / `--out` for 10K. |
| `chess_exp6_v7_3_ranking.py` | v7.3/v9.3 — afterstate logistic ranking pipeline |
| `chess_exp6_v7_supervised.py` | v7.1/v7.2 — Huber+tanh cp + ply-outcome auxiliary |
| `chess_exp6_v8_tdleaf.py` | v8 self-play (ABANDONED, kept for reference) |
| `chess_exp6_v9_label_10k.py` | 10K Stockfish labelling (sharded, multi-worker safe) |
| `chess_exp6_v9_4_search_hybrid.py` | Endgame-d3 A/B (negative result) |
| `chess_exp6_v9_5_mine_failures.py` | v9.5 active-failure mining + depth-6 relabel |
| `chess_exp6_v9_5_train.py` | v9.5 failure-aware training; now has conservative tunables (`--failure-rank-weight`, `--failure-only`, output paths) |
| `chess_exp6_search_ablation.py` | v10 search-side A/B harness for qchecks, ordering, opening-principle overlays, and H2H diagnostics |
| `chess_exp6_v9_depth3_feasibility.py` | Per-position d2/d3 cost measurement |
| `chess_exp6_match.py` | 30-game match-gating between two .npz weights |
| `chess_exp6_selfplay_curriculum.py` | v8 self-play (deadlock; kept for reference) |
| `chess_exp6_depth3_comparison.py` | depth-2 vs depth-3 staged-comparison harness |

### Inference code (`/services/games/`)
| File | Notes |
|---|---|
| `chess_neural.py` | NN weights, material+PST baseline, eval helpers |
| `chess_exp6.py` | Search profile resolution, runtime entry point, env-var endgame-d3 hybrid, env-gated opening-principles overlay |
| `chess_stockfish_teacher.py` | UciStockfish wrapper for labelling |
| `chess_search.py` | Generic alpha-beta engine |

### Runtime data (`/runtime/private/games/exp6/`)
| Path | Contents |
|---|---|
| `quality_1000_games.jsonl` | Source 1K games (v1-v8) |
| `quality_10k_games.jsonl` | Source 10K games (v9) |
| `curriculum_labels.jsonl` | 1K Stockfish-d4 labels |
| `curriculum_labels_10k.jsonl` | 10K Stockfish-d4 labels |
| `played_moves.jsonl` | 1K played-move map |
| `played_moves_10k.jsonl` | 10K played-move map |
| `v9_5_failure_positions.jsonl` | 112 v9.3 failure positions (SF d6 relabeled) |
| `downloaded_replay.jsonl` | Pre-filter pool (44k candidates) |
| `quality_{1000,10k}_summary.json` | Per-source / per-tier stats |
| `v{2,3,4,5,6,6_2}_curriculum_report.{md,json}` | Historical training reports |

### Snapshots (`~/exp6_output/`)
| Path | Contents |
|---|---|
| `v6_2_snapshots/chess_experiment_6_neural_stage02.npz` | **Champion source** (md5 1c27627a) |
| `v7_3_snapshots/v9_3_best.npz` | v9.3 best (breakthrough but failed Gate 2) |
| `v9_5_snapshots/v9_5a_FAILED_staged0.npz` | v9.5a (failure data over-training) |
| `v9_5_snapshots/v9_5b_failure_only_best_staged_minus28.npz` | v9.5b conservative failure-only (partial repair; failed Gate 2) |
| `v{1,2,3,4,5,6,6_1,6_2}_snapshots/` | Historical stage snapshots |

### Memory (`/.claude/projects/-home-s92137-chess-exp5/memory/`)
| File | Topic |
|---|---|
| `exp6_champion_lock.md` | Lock policy + promotion gates |
| `exp6_curriculum_ceiling.md` | +6 ceiling diagnosis (v1-v5) |
| `exp6_self_play_design.md` | User-authored phased roadmap (v7-v9) |
| `exp6_v7_supervised_plateau.md` | Why v7.1-v7.3 all hit 45% reject |
| `exp6_depth3_feasibility.md` | d3 cost numbers |
| `exp6_v94_hybrid_negative.md` | Hybrid d3 never fires |
| `exp6_dataset_scaling.md` | 1K → 10K plan (executed) |
| `exp6_auto_fix_authority.md` | User's instruction on autonomous iteration |

---

## 6. Open problems for next agent

### 6A. v9.5 failure-data path is not enough by itself
Tried after handover:
- failure-only from v9.3, lr=1e-4, epochs=6/7, oversample=1, rank=0.15 → -28/40
- mixed full 10K base + failure rows from v9.3, lr=1e-4, 1 epoch, rank=0.15 → -37/40

Conclusion: conservative failure-only can recover one extra draw vs v9.3, but still does not pass Gate 2. Do **not** run longer mixed base+failure training from v9.3 without a new selection criterion tied to staged play.

### 6B. v9.3 generalization mystery
v9.3 wins H2H but loses to Stockfish. Possibly:
- Training data has implicit Stockfish-d4 cp distribution that doesn't match Stockfish-deep gameplay
- Engine plays SF-staged with FIXED openings — possible deterministic bad lines
- Model overfits to 10K elite-game positions that are RARELY seen in Stockfish-staged play
- Address via: SF-vs-SF gameplay data (engines we'll face) + careful loss weighting

### 6B2. v10 opening-principles overlay follow-up
`EXP6_OPENING_PRINCIPLES=1` is the best non-training improvement so far:
- staged-10: -25 → -19 on v6.2 S2
- routes-level exp5 comparison: exp5 -28 vs exp6 default -22
- H2H vs baseline search: 0W/30D/0L

This is now default-on for Exp6 search policy, while the `.npz` champion remains v6.2 S2. Use `EXP6_OPENING_PRINCIPLES=0` to reproduce the old baseline.

### 6C. Self-play unsolved
v8 deadlock means we can't easily generate gameplay-distribution training data. Options:
- Use Stockfish vs Stockfish at varying depths as "asymmetric self-play"
- Use random-starting-FEN games with deeper search (depth 3) — costs more but may decisive
- Use multi-pv training data instead of self-play

### 6D. Architecture-level diagnosis and next design
- **Current Exp6 is value-only**: search ranks root moves by depth-2
  afterstate value plus handcrafted ordering. The best runtime result is now
  mostly "survive/draw" behavior; no tested post-filter converts that into
  wins without turning draws into losses.
- **Exp4 PV policy has a structural limitation**: its current
  `_policy_from_hidden(model, hidden(board), move_features)` is additive:
  `policy_shared_w · hidden(board) + policy_move_w · move_features`. The board
  term is constant across all legal moves in the same position, so raw policy
  ranking is effectively move-feature-only unless exact memory is present.
  Do not copy this policy-head shape into Exp6.
- **Policy head that might be worth doing**: a real board×move interaction,
  e.g. `score(s,m)=dot(f_board(s), g_move(s,m)) + move_linear(s,m)`, trained
  jointly with value/search-aligned loss. This was prototyped in-memory only;
  see the 2026-05-18 notes below.
- **HalfKP / HalfKAv2 encoding** (king-aware) remains a plausible value-side
  architecture change. It should be trained/evaluated as a new candidate, not
  layered on top of v6.2 as a filter.
- **Search depth 3 default** remains infeasible for production (multi-second
  middlegame decisions), unless the evaluator/orderer is made much faster and
  the search tree is materially narrower.

### 6E. Things to NOT redo (saves cycles)
- ❌ More 1K-scale supervised tweaks (v7.1-7.3 proved 45% reject)
- ❌ v8 TDLeaf at depth 2 (deadlock is structural)
- ❌ Endgame-only depth-3 hybrid for fixing staged-10 (never fires)
- ❌ Aggressive failure oversampling without small-scale ablation first
- ❌ qchecks/check-extension/basic move-order tweaks as standalone fixes (v10 ablation did not beat baseline)
- ❌ Exact-FEN teacher books / memorized gate lines. User explicitly forbids
  target-specific design, memorizing test games, or leaking challenge content.
  A temporary teacher-trace probe was discarded and must not be revived.
- ❌ Generic post-search draw breaking as a route to wins. 2026-05-18 aggregate
  check showed the 7 drawn v10 games ended with Exp6 materially behind on
  average (~-1544cp); threefold draws are mostly defensive resources, not
  missed winning conversions. Aggressive contempt turned draws into losses.
- ❌ One-off generic tactical-safety and broad heuristic-eval wrappers were
  tested without storing move traces; both regressed hard (no wins).

### 2026-05-18 v10 follow-up after "no wins" feedback

Constraint now explicit: no special-casing of the staged gate, no memorized
positions/games, no exact-FEN lookup tables, and no persisted move traces that
could leak challenge content.

Accepted runtime-side change remains only the general opening-principles
overlay (`EXP6_OPENING_PRINCIPLES`, default on): v6.2 S2 improves from
`0W/5D/5L = -25/40` to `0W/7D/3L = -19/40`. This still has zero wins.

Rejected generic probes:
- Conservative repetition/conversion filters: no score change
  (`0W/7D/3L = -19/40`), now default off via `EXP6_CONVERSION_FILTERS=0`.
- Aggressive contempt / forced draw breaking: `0W/2D/8L = -34/40`.
- Search parameter variants: no-pruning and qcheck variants regressed
  (`-25` and `-28`); depth-3 lite was slower and losing early, aborted.
- Forced mate-in-2 net: no score change (`0W/7D/3L = -19/40`).
- Broad handcrafted eval wrapper (mobility/king/pawns): `0W/0D/10L = -40/40`.
- Root tactical-safety wrapper: `0W/2D/8L = -34/40`.
- Generic Stockfish-depth-4 move-policy prior trained on sampled 10K
  curriculum positions (not staged/failure rows): heldout top1 improved to
  ~20%, but staged probe opened `2D/4L` before abort and was slower. Do not
  wire a shallow linear policy prior into runtime.
- Opening "development discipline" overlay (avoid repeat minor moves / quiet
  flank pawns before development): aborted at `3D/6L`, worse than current
  default.
- Static material+PST-only evaluator with opening principles:
  `0W/3D/7L = -31/40`; the v6.2 residual should not be replaced by PST-only.
- Selective root depth-3 verification: lost the first d1 game and raised max
  decision latency to ~1.1s; stopped early.
- Adaptive depth-3 trigger (low material / low legal count / in-check): lost
  the first d1 game and hit ~3.2s max decision latency; stopped early.
- Existing exp4 PV model as direct reference: no win signal; opened
  `1D/2L` and was slower (~0.6-0.9s mean), so exp4 cannot be borrowed as the
  Exp6 breakthrough.
- Existing exp4 PV policy as Exp6 move ordering: opened `1D/2L`, slower
  (~0.56s mean), stopped early.
- Small MLP policy head trained from generic Stockfish-d4 best moves:
  49-dim move features reached only ~16% top1 / ~32% top3 heldout and opened
  badly (`1D/4L` before abort). Board-plane policy prototype had prohibitive
  feature cost in naive form and was stopped before staged use; if revived,
  implement sparse/incremental feature extraction first.
- Random-prefix Stockfish-vs-Stockfish gameplay distribution fine-tune
  (1.2k generic positions, SF d4 labels, seeded from v6.2 S2): full candidate
  `0W/4D/6L = -28/40`; small weight interpolation alpha=0.10 produced
  `0W/6D/4L = -22/40`. Direction is harmful even at small alpha.
- 2026-05-18 continued "actual breakthrough" probes after zero-win feedback:
  - Search eval perspective probe: wrapping Exp6 evaluator back to white-POV
    for `chess_search` produced `0W/3D/7L = -31/40`; do not change runtime
    evaluator/search contract based on this suspicion.
  - v6.2 later-stage retest with current opening overlay:
    S3 `-34`, S4 `-34`, S7 `-31`, S9 `-34`, S10 `-31`. S2 remains the best
    v6.2 runtime snapshot under the overlay.
  - v9.3 + current opening overlay: `0W/3D/7L = -31/40`; the old H2H
    breakthrough still does not generalize to Stockfish staged. v9.5b
    failure-only opened with multiple early losses and was stopped.
  - Opening-principle parameter scan: `current_clone` reproduced
    `0W/7D/3L = -19/40`; `mild_filter` matched it; stronger castling,
    central-development, and active-tactical weights all regressed early.
  - `king_safety` overlay finished `0W/4D/6L = -28/40`; do not promote.
  - Full-width root mate-in-3 proof search is too slow for runtime (30s with
    no first-game result). Only revisit as a narrow check-only tactical probe.
  - 10K played-move human opening linear ranker (49 exp2/exp3 move features,
    early positions only, no FEN lookup): heldout top1 17.2%, top3 37.0%;
    staged scale 15000 opened `0W/2D/2L = -10/16` and was stopped. Do not
    wire shallow human imitation policy into Exp6 opening order.
  - Existing exp3 DL policy as Exp6 move order opened `0W/1D/4L = -17/20`
    before stop, with ~600ms moves. Do not borrow exp3 ordering directly.
  - Board×move interaction policy prototype (PyTorch CPU, no persisted staged
    traces, no FEN lookup):
    - human played-move target from early 10K quality rows: train pair_acc
      0.839, heldout top1 25.5%, top3 52.2%, but root-order staged regressed
      immediately (`0W/2D/2L = -10/16` at scale 1200; worse at higher scale).
      Offline human-opening imitation is not aligned with beating Stockfish.
    - generic Stockfish-d4 best-move target from 5200 sampled curriculum
      positions: heldout top1 17.1%, top3 36.8%; staged scale 800 opened
      `0W/0D/4L = -16/16`. Too little data / wrong distribution / too shallow
      objective. Do not wire this prototype into runtime.
    - Architecture lesson: board×move interaction is the right policy shape,
      but the policy target must be search/value-aligned and selected by
      staged/H2H gates. Root policy bonus alone can destroy the draw-defence
      lines that make current Exp6 survive.
  - Joint policy/value conservative rerank harness
    (`scripts/games/chess_exp6_joint_policy_rerank.py`, 2026-05-18):
    trains a board×move interaction policy auxiliary head plus value /
    champion-preservation losses on generic sampled curriculum positions.
    Runtime experiment contract: current search first produces candidates,
    the joint model may only rerank inside top-N, and risk guards fall back to
    the current champion decision. There is no direct root policy bonus and no
    staged move/FEN trace persistence.
    - First probe (`--label-limit 420 --dev-size 80 --epochs 6`) had weak
      heldout sanity (top1 5.0%, top3 20.0%, top5 31.25%) and staged opened
      `0W/1D/3L = -13/16` with 26/75 rerank changes. It was stopped as below
      the current `0W/7D/3L = -19/40` defence. Do not promote.
    - After that failure, the harness default was tightened: top-N=2,
      no allowed search-score/material drop, min policy margin 2.0, and a
      mandatory pre-staged heldout gate (top3 >= 35%, top5 >= 50%).
    - Sanity-gate smoke (`--label-limit 80 --dev-size 24 --epochs 2`) failed
      before staged (top1 0.0%, top3 4.17%, top5 4.17%); staged games were
      correctly skipped. Scale labels/training only if this gate passes first.
    - Candidate-topN relabel mode (generic curriculum positions only):
      label each position by first generating champion/search top-N candidates,
      then asking Stockfish to evaluate only those root moves. Conservative
      target keeps champion unless a candidate improves by >=90cp. This better
      matches the intended top-N rerank contract but still did not promote.
      - 80/24 smoke: candidate target top1/top3/top5
        33.3%/62.5%/100%, staged skipped by sanity gate.
      - 240/60 policy-only: candidate target top1/top3/top5
        58.3%/86.7%/100%, safe-choice 96.7%; 4-game early gate was safe
        (`0W/4D/0L = -4/16`), but full 10-game gate regressed to
        `0W/5D/5L = -25/40`. Do not promote.
      - Same 240/60 with switch-time depth-2 verification and +80cp required
        verified improvement still ended `0W/5D/5L = -25/40`. Verification
        reduced switches but did not improve the defence.
      - Joint after-board value rerank (value head trained on candidate
        after-position evals, value weight 0.8) failed sanity at both 80/24
        and 240/60; staged correctly skipped.
      - Larger 600/120 policy-only improved offline candidate sanity
        (top1/top3/top5 63.3%/92.5%/100%, safe-choice 100%) but immediately
        broke staged defence: `0W/1D/3L = -13/16` early abort. Offline
        candidate-topN sanity is not predictive enough on its own.
    - Residual-scale value-side probes (temporary `/tmp` candidates, champion
      untouched): alpha 0.75 gave `0W/2D/8L = -34/40`; alpha 1.25 gave
      `0W/3D/7L = -31/40`. Do not scale the v6.2 residual away from 1.0.
    - Formal gate warning: `scripts/games/chess_exp6_search_ablation.py`
      `principles` clone produced `0W/5D/5L = -25/40` on the champion, while
      the official `chess_exp6_curriculum.play_staged_test()` reproduced the
      true current runtime gate `0W/7D/3L = -19/40`. Use the curriculum gate,
      not the ablation clone, for promotion decisions.

### 2026-05-18 evaluator/search architecture pivot

Policy-rerank is paused. The current bottleneck is evaluator/search consequence
judgement, not top-N policy guessing.

New docs:
- `docs/games/chess_debug/exp6/evaluator_search_path_audit.md`
  records the official runtime/gate function path. Promotion gates must use
  `chess_exp6_curriculum.play_staged_test()`.
- `docs/games/chess_debug/exp6/evaluator_search_experiment.md`
  records the first HalfKP-style value candidate.

HalfKP value candidate:
- Script: `scripts/games/chess_exp6_halfkp_value_candidate.py`
- Candidate artifact: `/tmp/exp6_halfkp_v1_600.pt`
- Report: `/tmp/exp6_halfkp_v1_600_report.json`
- Champion md5 before/after:
  `1c27627adb3c4597561bc7509438e25c` / `1c27627adb3c4597561bc7509438e25c`
- Champion modified: false; permissions remained `444`.
- Design: HalfKP/HalfKAv2-style king-conditioned sparse value evaluator,
  trained as a residual over Exp6 static material+PST. No policy head, no root
  policy bonus, supports after-board evaluation via the normal search
  evaluator call path.
- Training: 600 generic curriculum rows, 120 dev rows, 4 epochs, hidden=64.
  Final dev: compressed-value smooth L1 `0.022455`, cp corr `0.4474`,
  sign accuracy `0.7417`, avg abs cp error `99.94`.
- Verification: `py_compile` passed; deterministic evaluator sanity passed;
  fixed FEN mate-in-1 / promotion tactical suite passed; blunder avoidance
  suite passed; fixed-FEN ablation covered baseline current evaluator +
  current search, new evaluator + same search, depth-2 narrow, depth-3 narrow,
  quiescence off, and move ordering off.
- Staged early gate: `0W/2D/2L = -10/16`, below stop line `-4/16`. Full
  10-game gate skipped by stop policy. Do not promote.

Next direction: if HalfKP continues, scale and improve value training before
any staged spend, and add stronger after-board regression diagnostics. Another
plausible route is speeding the evaluator/search loop enough that depth-3 can
be tested under the official gate, rather than adding policy workarounds.

Follow-up failure taxonomy / search diagnosis:
- Script: `scripts/games/chess_exp6_search_failure_diagnostics.py`
- Redacted taxonomy JSONL:
  `runtime/private/games/exp6/halfkp_v1_failure_taxonomy.jsonl`
- Search ablation JSON:
  `runtime/private/games/exp6/search_failure_ablation.json`
- Docs:
  - `docs/games/chess_debug/exp6/halfkp_v1_failure_taxonomy.md`
  - `docs/games/chess_debug/exp6/search_failure_taxonomy.md`
  - `docs/games/chess_debug/exp6/search_ablation_report.md`
  - `docs/games/chess_debug/exp6/next_evaluator_candidate_plan.md`
- Exact staged FENs/moves were not persisted; rows use `position_id` and
  `move_id` digests only.
- Taxonomy: 64 redacted HalfKP v1 decision points, mean Stockfish eval delta
  `240.86cp`, max `750cp`. Dominant tags: positional/small-delta 34,
  horizon-effect 25, hanging-piece 5, king-safety 3.
- Current-evaluator search ablations on the same redacted failure-position
  set did not find an effective patch. Best mean delta was depth-3
  (`236.73cp` vs baseline `244.36cp`), but top3 rate only improved from
  `10.94%` to `12.50%`, mean latency rose to `1414.6ms`, and max delta got
  worse (`824cp`). No patch qualified for staged early-gate testing.
- Stop condition applied: search ablation did not fix the staged failure
  positions, so no new model was trained and no runtime patch was promoted.

Tooling note: `scripts/games/chess_exp6_search_ablation.py` now redacts move
lists and final FENs by default. Use `--include-traces` only for deliberate
private debugging; do not persist staged traces under the current user
constraint.

Current diagnosis: Exp6 lacks enough tactical/strategic strength before the
draw cycle; wins likely require a real value/search architecture or training
change, not more post-search filters. Policy-rerank and root policy bonus stay
paused. The most defensible next candidate is value-only evaluator v2 using
generic curriculum / Stockfish-labelled train-dev-heldout data plus
tactical-swing, mate-distance, SEE/material-swing, king-exposure, and
promotion-race signals.

### 2026-05-18 development pause / frontend-backend closeout

Exp6 active development is paused. Frontend/backend practice wiring is closed
out for restart:

- Frontend static fallback: `public/index.html` includes
  `experiment 6:neuralnet` in chess practice and root candidate controls.
- Frontend dynamic path: `public/js/games/chess.js` consumes
  `/api/games/catalog`, renders Exp6, and posts the selected difficulty to
  `/api/games/chess/practice`.
- Backend catalog/practice path: `routes/games.py` advertises, accepts,
  persists, serializes, and dispatches `experiment 6:neuralnet` to
  `services.games.chess_exp6.choose_experiment_neural_move()`.
- Fresh-install schema: `bootstrap.schema.sql` now matches runtime for
  renamed Exp0/Exp1 and Exp6 `computer_difficulty` values.
- Documentation index:
  `docs/games/chess_debug/exp6/frontend_backend_pause_handover.md` and
  `docs/games/chess_debug/exp6/README.md`.

No model file was modified, no candidate was promoted, and no staged raw FENs
or moves were persisted in docs.

---

## 7. Quick-start commands

### Inspect current runtime
```bash
md5sum /home/s92137/hackme_web/runtime/games/models/chess_experiment_6_neural.npz
# expect: 1c27627adb3c4597561bc7509438e25c
cat /home/s92137/hackme_web/runtime/games/models/CHAMPION_LOCK.md
```

### Match-gate v6.2 S2 vs a candidate
```bash
cd /home/s92137/hackme_web && python -u scripts/games/chess_exp6_match.py \
  --candidate <candidate.npz> \
  --baseline ~/exp6_output/v6_2_snapshots/chess_experiment_6_neural_stage02.npz \
  --games 60 --search-profile fixed_depth_d2 \
  --out ~/exp6_output/some_match.json
```

### Staged-10 vs Stockfish 1-5 for a candidate
```bash
cd /home/s92137/hackme_web && python3 -c "
import sys; sys.path.insert(0, 'scripts/games')
import chess_exp6_curriculum as cc
results = cc.play_staged_test('<candidate.npz>')
summ = cc.score_summary(results)
print(f'{summ[\"W\"]}W/{summ[\"D\"]}D/{summ[\"L\"]}L score={summ[\"total_score\"]:+d}/{summ[\"max_possible_score\"]}')"
```

### Staged-10 with v10 opening-principles overlay
```bash
cd /home/s92137/hackme_web && python3 -c "
import sys; sys.path.insert(0, 'scripts/games')
from pathlib import Path
import chess_exp6_curriculum as cc
results = cc.play_staged_test(Path('/home/s92137/exp6_output/v6_2_snapshots/chess_experiment_6_neural_stage02.npz'))
summ = cc.score_summary(results)
print(f'{summ[\"W\"]}W/{summ[\"D\"]}D/{summ[\"L\"]}L score={summ[\"total_score\"]:+d}/{summ[\"max_possible_score\"]}')"
# observed 2026-05-18: 0W/7D/3L score=-19/40
```

### Conservative joint policy/value rerank probe
```bash
cd /home/s92137/hackme_web && python3 -u scripts/games/chess_exp6_joint_policy_rerank.py \
  --label-limit 2000 --dev-size 300 --epochs 12 --games-limit 4 \
  --out /tmp/exp6_joint_policy_rerank_probe.json
```
The harness skips staged games unless heldout policy sanity passes top3/top5
minimums. It must never be used as a direct root policy bonus.

### Retrain v9.3 (if ranking pipeline + 10K dataset)
```bash
cd /home/s92137/hackme_web && python -u scripts/games/chess_exp6_v7_3_ranking.py \
  --epochs 40 --lr 0.0005 --patience 8 \
  --outcome-weight 0.04 --ranking-weight 0.15 --k-neg 3 --batch-size 64 \
  --labels-path runtime/private/games/exp6/curriculum_labels_10k.jsonl \
  --played-moves-path runtime/private/games/exp6/played_moves_10k.jsonl \
  --train-game-id-max 8999 --dev-game-id-max 9999 \
  --out-snapshot-name v9_3_replay.npz
```

### Tested-good label format
```jsonl
{"game_idx": 42, "fen": "...", "cp_white": -100.0, "outcome_white": -1.0, "blended_cp": -100.0, "label_depth": 4, "outcome_blend": 0.0}
```
`game_idx` MUST match `SHUFFLE_SEED=20260516` shuffle of the source `quality_*.jsonl`. Mismatch = labels join to wrong positions = silent training disaster.

---

## 8. Engine comparison reference (from `engine_comparison.json`, 10-game test)

| Engine | Total score | Notes |
|---|---|---|
| exp0 minimax2ply | -34 | 2-ply material minimax |
| exp1 search | -34 | Stockfish-search-based |
| exp2 nn | -25 | Earlier auto-train NN |
| exp3 dl | **-22** | Best of pre-v6 — uses 49 hand-engineered move features |
| exp4 pv | -22 | Policy/value + MCTS |
| exp5 nnue | -28 | Hand-tuned NNUE-inspired |
| **exp6 neuralnet (v6.2 S2)** | **-25** | Current runtime; material + PST + NN residual |

exp3/exp4 are ahead by using richer per-move feature engineering. A potential path forward: import their move-feature extractor to enrich exp6's input.
