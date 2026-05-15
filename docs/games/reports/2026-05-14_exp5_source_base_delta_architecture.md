# Exp5 Source Base And Experience Delta Architecture

## Summary

Exp5's previous bundled main JSON has been folded into source code. The engine
now treats the static base payload as immutable code and writes only small
experience/adapter delta JSON files during retrain.

## Files Changed

- `services/games/chess_exp5_base_model.py`: source-embedded static base model.
- `services/games/chess_nnue.py`: loads source base by default and composes
  experience deltas when a runtime/candidate model file exists.
- `services/games/models/chess_experiment_5_nnue.json`: removed; this is no
  longer a required bundled artifact.
- `services/games/chess_promotion.py`: warm-start no longer creates an exp5
  runtime main JSON; inventory reports the source base and optional experience
  delta path.
- `services/games/chess_pipeline.py`: exp5 candidate outputs now use
  `chess_experiment_5_nnue_experience.json`.
- `scripts/games/chess_exp5_dataset_train.py`: training output is an experience
  delta over the source base.

## Artifact Policy

- Static base role: `static_base_eval_parameters`.
- Generated artifact role: `adapter_or_experience_table`.
- Delta format: `exp5_source_base_delta_v1`.
- Runtime delta path: `runtime/games/models/chess_experiment_5_nnue_experience.json`.
- Runtime replay path:
  `runtime/games/models/chess_experiment_5_nnue_experience_replay.jsonl`.
- Source base SHA-256:
  `88464dba7e3497e7be7474e0aae4272801fb2e98838985740e530f592f2ff992`.

## Compatibility

The loader still accepts older full exp5 JSON candidates. New saves emit only
deltas containing changed sparse weights, scalar deltas, and optional overlay
positions. If no delta file exists, exp5 uses the source base directly.

## Verification

- `python3 -m py_compile` on changed exp5 source/scripts: passed.
- Source base re-serialization hash matches the previous main JSON hash.
- One-sample train smoke wrote a delta with one changed piece-square weight and
  no full opening overlay copy.
- `test_chess_exp5_architecture.py`: 41 passed.
- `test_chess_exp5_dataset_train_script.py` and
  `test_chess_exp5_strength_gate_script.py`: 4 passed.
- exp5 opening candidate / overlay tests: 6 passed.
- dashboard/self-play focused tests: 2 passed.
- train pipeline script tests: 2 passed.
- exp5 seed train safety focused tests: 2 passed.
- seed train CLI dry-run mutation sentinel: 1 passed.
