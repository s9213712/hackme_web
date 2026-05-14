# exp5_14 opening label audit

## Scope

This round starts the post-production exp5 improvement track. It does not train,
replace the runtime model, touch promotion plumbing, or modify exp4.

The goal is to audit the negative opening cluster from exp5_13 before any
opening-focused curriculum is used for exp5_15. Opening rows should not become
training or promotion evidence until label quality is known.

## Input

- source summary: `<chess_results>/exp5_13_rule_smoke_stalemate_fix_check/summary.json`
- production runtime model sha remains: `c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc`
- exp5_13 baseline result: `112/137 = 0.817518`
- exp5_13 runtime candidate result: `115/137 = 0.839416`
- exp5_13 opening cluster: baseline `15/27`, runtime candidate `12/27`, delta `-0.111111`

## Tool

Added read-only audit script:

- `scripts/games/chess_exp5_opening_label_audit.py`

The script classifies opening rows with static top-k evidence:

- `true_opening_regression`
- `multi_good_opening_equivalent`
- `teacher_label_too_narrow`
- `questionable_label_do_not_gate`
- `fixture_issue`
- `needs_stronger_teacher`

It intentionally writes artifacts only under `~/chess_results` and does not
mutate model/runtime paths.

## Results

Output directory:

- `<chess_results>/exp5_14_opening_label_audit/`

Artifacts:

- summary: `<chess_results>/exp5_14_opening_label_audit/summary.json`
- summary md: `<chess_results>/exp5_14_opening_label_audit/SUMMARY.md`
- opening audit rows: `<chess_results>/exp5_14_opening_label_audit/opening_label_audit.jsonl`
- failed opening rows: `<chess_results>/exp5_14_opening_label_audit/opening_fail_rows.jsonl`
- clean opening curriculum: `<chess_results>/exp5_14_opening_label_audit/clean_opening_curriculum.jsonl`

| metric | value |
|---|---:|
| opening rows | 27 |
| opening failed rows | 15 |
| candidate regressed rows | 3 |
| clean opening rows | 0 |
| questionable opening rows | 27 |
| clean true opening regressions | 0 |
| exp5_15 clean opening curriculum rows | 0 |

Classification:

| classification | count |
|---|---:|
| teacher_label_too_narrow | 17 |
| multi_good_opening_equivalent | 6 |
| questionable_label_do_not_gate | 4 |

## Decision

- production_blocker: `false`
- questionable_rows_block_production: `false`
- clean_true_opening_regressions: `0`

The exp5_13 opening weakness is not currently production-blocking because every
opening row is `questionable`. It is also not a safe training source yet because
there are zero clean opening curriculum rows.

## Interpretation

The negative opening delta is mostly a label-quality problem:

- many teacher labels are too narrow under the same static evaluator
- several failed rows are plausible multi-good openings rather than clear model
  regressions
- no clean opening true regression was found

Therefore, exp5_15 should not train directly on these opening rows. The next
step is to build curated opening-book or stronger-teacher labels, then expand
the clean held-out benchmark before candidate search.

## Tests

- `python3 -m py_compile scripts/games/chess_exp5_opening_label_audit.py tests/scripts/games/test_chess_exp5_opening_label_audit_script.py`
- `python3 -m pytest tests/scripts/games/test_chess_exp5_opening_label_audit_script.py`
- real audit run on exp5_13 summary

## Next

Recommended next step:

- exp5_14b clean held-out expansion with curated opening labels

Do not start exp5_15 retraining until there are clean opening labels or a
stronger opening teacher.
