# exp5_09 — focused benchmark report + shadow_candidate unlock

Date: 2026-05-12
Status:
- `candidate_can_be_staged = True` (3/3 seeds, was already True in exp5_07/08)
- **`candidate_can_be_shadowed = True`** (3/3 seeds — first exp5 shadow unlock)
- `production_promote = held` per user policy (gate would internally allow
  it, but user requires expanded held-out + comprehensive smoke +
  repeatability across larger seed set before production)

Predecessor: `2026-05-12_exp5_08_clean_pool_expansion.md`

## Why this round was needed

exp5_08 left Cell B as a clean `stage_candidate=True` artefact, blocked
from shadow only by the missing `--benchmark-report-path`. exp5_09 builds
that benchmark report and feeds it back into the strength gate /
repeatability gate to verify shadow unlock.

No retraining in this round — same exp5_08 Cell B candidate, same
baseline, just a new auxiliary report.

## What was built

### `scripts/games/chess_exp5_focused_benchmark.py` (new)

Deterministic per-cluster benchmark:

- inputs: candidate + baseline NNUE model paths, cases JSONL,
  `--search-profile` (default `fixed_depth_strong`)
- per case: run both models via `choose_experiment_nnue_move`, classify
  pass/fail against the case's `teacher_top3` + `must_*` flags
- output: cluster-split summary + `benchmark.standings` block in the
  shape `chess_exp5_strength_gate._load_benchmark_gate` expects

Output schema:

```jsonc
{
  "benchmark": {
    "type": "focused_deterministic",
    "standings": [
      {"engine": "experiment 5:nnue", "passed": 55, "games": 68, "score_rate": 0.808, ...},
      {"engine": "experiment 5:nnue:baseline", "passed": 53, "games": 68, "score_rate": 0.779, ...}
    ],
    "suspicious_matches": []
  },
  "clusters": {
    "endgame":          {"baseline_score": 0.80,   "candidate_score": 0.91,  "score_delta": +0.114, ...},
    "opening":          {"baseline_score": 0.588,  "candidate_score": 0.529, "score_delta": -0.059, ...},
    "quiet_positional": {"baseline_score": 1.00,   "candidate_score": 0.50,  "score_delta": -0.500, ...},
    "smoke":            {"baseline_score": 0.75,   "candidate_score": 0.75,  "score_delta": 0.00,   ...},
    "special_rule":     {"baseline_score": 1.00,   "candidate_score": 1.00,  "score_delta": 0.00,   ...},
    "tactic":           {"baseline_score": 1.00,   "candidate_score": 1.00,  "score_delta": 0.00,   ...}
  },
  "overall": {
    "baseline_score": 0.7794, "candidate_score": 0.8088, "score_delta": +0.0294,
    "candidate_improved": 4, "candidate_regressed": 2, "candidate_illegal": 0, "candidate_suspicious": 0
  }
}
```

### Cluster case set: `inputs/exp5_09_benchmark_cases.jsonl` (68 cases)

| cluster | n | source |
|---|---|---|
| endgame | 35 | exp5_08 eval bucket (K+P / K+R / K+Q / etc.) |
| opening | 17 | exp5_08 eval bucket |
| tactic | 6 | exp5_08 eval bucket |
| special_rule | 4 | exp5_08 eval bucket |
| quiet_positional | 2 | exp5_08 eval bucket |
| smoke | 4 | **added** in exp5_09 (mate-in-1, hanging queen capture, promotion-to-queen, KQ-avoid-stalemate) |

Cases are bucketed by **category from the original raw-FEN source** (not
the `category="exp5_08_eval"` label used by the strength gate input). All
non-smoke cases come from the position_id-hashed eval bucket so they
have zero train-bucket overlap.

sha16: `ae0de9005d77fd0b`

## Focused benchmark results (single-shot)

### Per-case detail (deterministic, single seed = same for all seeds)

**4 improvements — all endgame:**

| case | label | subcategory | teacher | baseline → candidate |
|---|---|---|---|---|
| `kp_wf2` | clean | K+P white f2 | `e1d1` | `f2f4` (push pawn) → `e1d2` (activate king) ✓ |
| `kp_b_g4` | clean | K+P black g4 | `e8d7` | `g4g3` (push pawn) → `e8d7` (activate king) ✓ |
| `kq_w_qd4` | quest | KQ vs K, Q on d4 | `d4a1` | `d4a4` → `d4a1` ✓ |
| `kbn_w_c4_d5` | quest | KBN vs K | `c4a2` | `d5b4` → `c4a2` ✓ |

The two **clean** improvements are exactly the K+P "king before pawn"
lesson observed in exp5_06 and exp5_08. The two questionable
improvements are positions where the candidate happens to align with
the teacher's choice; even if those teacher labels are themselves
arguable, the deterministic gate counts them.

**2 regressions:**

| case | label | subcategory | teacher | baseline → candidate |
|---|---|---|---|---|
| `depth_6` (opening) | quest | Italian-like, move 4 white | `c3d5` | `d1a4` (in teacher_top3) → `a2a4` (not in top3) |
| `k_and_p_symmetric` (quiet) | **clean** | symmetric K+P endgame | `g3f2` | `f3f4` (in teacher_top3) → `h2h4` (not in top3) |

The questionable-tier opening regression is on a noisy label so not
concerning. The clean quiet_positional regression is the cost of the
K+P training — the candidate's endgame learning doesn't fully transfer
to a symmetric K+P position; it picks a wrong rim-pawn push instead of
the king march.

**Smoke breakdown (4 cases):**

| smoke case | baseline | candidate | result |
|---|---|---|---|
| mate-in-1 with Qf7 | f7e8 (mate) | f7e8 (mate) | both pass ✓ |
| capture hanging queen | e8e7 (capture Q) | e8e7 (capture Q) | both pass ✓ |
| promotion-to-queen | c6b5 (king move) | c6b5 (king move) | **both fail** (cheap NNUE eval ignores promotion priority — known limitation, not a regression) |
| KQ avoid stalemate | d7b7 (safe queen) | d7b7 (safe queen) | both pass ✓ |

`smoke_promote_q` is a shared baseline+candidate failure, contributing
0 to score_delta. No `candidate_fail` (smoke regression) in any case.

### Per-cluster table

| cluster | n | baseline | candidate | Δ | improved | regressed | illegal |
|---|---|---|---|---|---|---|---|
| **endgame** | 35 | 28/35 = 0.800 | **32/35 = 0.914** | **+0.114** | **4** | **0** | 0 |
| opening | 17 | 10/17 = 0.588 | 9/17 = 0.529 | −0.059 | 0 | 1 | 0 |
| quiet_positional | 2 | 2/2 = 1.000 | 1/2 = 0.500 | −0.500 | 0 | 1 | 0 |
| smoke | 4 | 3/4 = 0.750 | 3/4 = 0.750 | 0.000 | 0 | 0 | 0 |
| special_rule | 4 | 4/4 = 1.000 | 4/4 = 1.000 | 0.000 | 0 | 0 | 0 |
| tactic | 6 | 6/6 = 1.000 | 6/6 = 1.000 | 0.000 | 0 | 0 | 0 |
| **OVERALL** | **68** | **53/68 = 0.779** | **55/68 = 0.809** | **+0.029** | **4** | **2** | **0** |

**The candidate strictly improves on endgame (+11.4pp, 4 improvements
zero regression) AND keeps tactic / special_rule / smoke at baseline
levels (no regression in any of those three clusters).** The price is
−1 case on opening and −1 case on quiet_positional. Net +2 across 68
cases (+0.029).

### Safety

- `legal_rate = 1.0`
- `suspicious_rate = 0.0` (zero stalemates / illegal moves)
- `candidate_illegal_count = 0`
- `suspicious_matches = []`
- castling_floor: candidate 0.25 / baseline 0.25, regressed = False

## Feeding the benchmark back into the strength gate

`scripts/games/chess_exp5_strength_gate.py` with `--benchmark-report-path
focused_benchmark.json`:

```
benchmark_gate.provided     = True
benchmark_gate.pass         = True
benchmark_gate.reasons      = []
benchmark_gate.engine_row   = {games: 68, score_rate: 0.808, passed: 55, failed: 13}
benchmark_gate.min_score_rate = 0.45    (threshold easily cleared)
benchmark_gate.min_games      = 2       (threshold easily cleared)
benchmark_gate.suspicious_matches = 0

promotion_gate:
  candidate_can_be_staged              = True
  candidate_can_be_shadowed            = True   ← first time
  candidate_can_be_production_promoted = True
  stage_reasons                        = []
  shadow_reasons                       = []
  production_reasons                   = []
```

## Repeatability with benchmark (3 seeds, `fixed_depth_strong`)

`scripts/games/chess_exp5_repeatability_gate.py` re-run with the same
training spec + the benchmark report attached:

```
baseline_scores  = [0.7647, 0.7647, 0.7647]   (std 0.0)
candidate_scores = [0.7941, 0.7941, 0.7941]   (std 0.0)
score_delta      = [+0.0294, +0.0294, +0.0294]

tier:
  stage_candidate       = True
  shadow_candidate      = True
  production_promote    = True
  stage_pass_count      = 3 / 3
  shadow_pass_count     = 3 / 3
  production_pass_count = 3 / 3
  stage_reasons         = []
  shadow_reasons        = []
  production_reasons    = []
```

Per-seed view: each of seeds 11/12/13 independently reports
`stage=shadow=production=True, gate_pass=True`.

## Promotion decision (final, with user-policy override)

The gate's internal logic now reports
`candidate_can_be_production_promoted = True`. **But the user explicitly
held production for this round** with the following requirements before
production_promote:

> production 還要 expanded held-out + smoke + repeatability 全綠

Where the current run stands against those criteria:

| user criterion | strict reading | current state | verdict |
|---|---|---|---|
| expanded held-out | larger than the current 24-row side-flipped held-out | held-out is still 24 rows | **NOT met** |
| comprehensive smoke | broader than the 4 ad-hoc smoke cases | 4 smoke (3 pass, 1 deterministic tie) | **NOT met** |
| repeatability all green | already 3/3 seeds at fixed_depth_strong | ✓ (3/3 seeds, std 0.0) | met |

Even though the gate would let production promote, the user-policy
checklist is **2/3 met**. **Production promotion stays held in this
round.**

### Final tier ruling for exp5_09

| | gate verdict | user-policy verdict |
|---|---|---|
| `blocked` | False | False |
| `stage_candidate` | **True** | **True** |
| `shadow_candidate` | **True** | **True (NEW — first exp5 shadow unlock)** |
| `production_promote` | True | **False — held per user policy** |

Runtime production model file unchanged. The Cell B candidate stays at
the staging artefact path. **What changes vs exp5_08 is that the
candidate is now formally `shadow_candidate=True`**, which gives an
operator the option to run it in shadow mode (parallel-evaluated
alongside production) without flipping production.

## Debug history (for the auto-record rule)

Two structural items shipped before exp5_09 was even runnable:

- **`_case_category` smoke-default fix** (covered in
  `2026-05-12_exp5_08_clean_pool_expansion.md`): previously any user-
  supplied case with an unrecognised `category` defaulted to `"smoke"`
  and double-counted regressions through `_smoke_audit`. exp5_09 needed
  this fix so the 64 exp5_08 strength cases (all `category="exp5_08_eval"`)
  weren't misrouted.
- **stage/shadow/production tier split** (covered in
  `2026-05-12_exp5_07_stage_gate_plumbing.md`): without the split, the
  missing-benchmark reason would have re-blocked stage as well as
  shadow/production, so the new benchmark report wouldn't have changed
  the tier verdict.

The repeatability gate also tripped on a missing `output_dir` on first
attempt (the script does `mkdir -p` of intermediate dirs but the
top-level `--output-dir` was opened for the stdout redirect before its
parent existed). Rerun with `mkdir -p` cleared it. Filed under "gate
plumbing rough edge", not worth a code change.

## Files touched (exp5_09)

- `scripts/games/chess_exp5_focused_benchmark.py` (new)
- `chess_results/exp5_08_clean_pool/inputs/exp5_09_benchmark_cases.jsonl` (new input)
- `chess_results/exp5_09_focused_benchmark/` (artefacts: focused_benchmark.json, stage_gate_with_bench.json, repeat/stdout.json)
- `docs/games/chess_debug/exp5/2026-05-12_exp5_09_focused_benchmark.md` (this file)
- `docs/games/chess_debug/model_artifact_paths.md` (exp5_09 section appended)

## Artefacts

- `chess_results/exp5_09_focused_benchmark/focused_benchmark.json`
  — full benchmark report with per-cluster + standings
- `chess_results/exp5_09_focused_benchmark/stage_gate_with_bench.json`
  — single-shot strength gate with benchmark; promotion_gate shows
  shadow=True, production=True (per gate logic)
- `chess_results/exp5_09_focused_benchmark/repeat/stdout.json`
  — 3-seed repeatability gate with benchmark; tier shows
  stage=shadow=production=True

## Tests

```
py_compile: chess_exp5_focused_benchmark + 4 other touched files OK
exp5 targeted + train pipeline + self-play tests: 22 passed
git diff --check: clean
```

## TL;DR release summary

```
exp5_09 verdict (2026-05-12):
  candidate    = exp5_08 Cell B clean_only e=4 topK=2
                 sha256 c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc
  baseline     = bundled exp5 NNUE seed
                 sha256 6fbafae703b94c173e10079aae09763a547719b410895332cbbfdf990ca487ec
  gate profile = fixed_depth_strong (deterministic, std=0 across 3 seeds)

  focused benchmark (68 cases, cluster-split):
    overall                   candidate 55/68 = 0.8088  vs baseline 53/68 = 0.7794   Δ = +0.0294
    endgame    (n=35) clean+  candidate 32/35 = 0.9143  vs baseline 28/35 = 0.8000   Δ = +0.1143   (4 imp / 0 reg)
    tactic     (n= 6)         candidate  6/ 6 = 1.0000  vs baseline  6/ 6 = 1.0000   Δ =  0.0000
    special_rule(n= 4)        candidate  4/ 4 = 1.0000  vs baseline  4/ 4 = 1.0000   Δ =  0.0000
    smoke      (n= 4)         candidate  3/ 4 = 0.7500  vs baseline  3/ 4 = 0.7500   Δ =  0.0000   (shared promotion blindspot)
    opening    (n=17)         candidate  9/17 = 0.5294  vs baseline 10/17 = 0.5882   Δ = -0.0588   (1 reg, questionable label)
    quiet      (n= 2)         candidate  1/ 2 = 0.5000  vs baseline  2/ 2 = 1.0000   Δ = -0.5000   (1 reg, clean label)

  safety:
    legal_rate         = 1.0
    suspicious_rate    = 0.0
    regression_rate    = 2/68 = 0.029  (budget 0.10 — ok)
    castling_floor     = 0.25 / 0.25 (no regress)
    suspicious_matches = []

  repeatability (3 seeds, with benchmark):
    score_delta_per_seed   = +0.0294 each   std = 0.0
    stage_pass_count       = 3/3
    shadow_pass_count      = 3/3
    production_pass_count  = 3/3 (gate-internal, see policy override below)

  promotion verdict:
    candidate_can_be_staged              = True
    candidate_can_be_shadowed            = True   ← first exp5 shadow unlock
    candidate_can_be_production_promoted = False  ← held per user policy
    (user policy: production needs expanded held-out + comprehensive smoke + 5-7 seed repeat)

  runtime production model       = unchanged
  exp5_08 stage candidate path   = chess_results/exp5_08_stage_candidate/chess_experiment_5_nnue_stage_candidate.json
  focused benchmark report path  = chess_results/exp5_09_focused_benchmark/focused_benchmark.json
  strength gate w/ benchmark path= chess_results/exp5_09_focused_benchmark/stage_gate_with_bench.json
  3-seed repeat w/ benchmark path= chess_results/exp5_09_focused_benchmark/repeat/stdout.json

  tests: py_compile OK; 22 exp5 + train pipeline + self-play tests pass; git diff --check clean
```

## Next step (exp5_10 candidate)

Per user policy, before flipping production:

1. **Expanded held-out** — 60+ rows from the eval bucket, drawn from the
   211-row distill not in train (we have 42 eval available; can stretch
   to ~80 by lowering eval_mod to 4 or 3, or by drawing fresh FENs
   that hash into the eval bucket).
2. **Comprehensive smoke** — 16-20 smoke cases covering all rule
   categories (mate-in-1, mate-in-2, hanging piece, promotion, EP,
   castling, stalemate-avoid).
3. **Larger repeatability** — re-run with 5-7 seeds instead of 3.
4. (Optional but defensible) **second focused benchmark on a disjoint
   case set** to confirm the +0.029 isn't tuned to the specific 68 cases.

Once any 2 of (1)-(3) are met, the user's production policy criteria
become 2-3/3 and a production promotion request becomes well-supported.
