# Chess Experiment Model Files

## exp2: `experiment 2:nn`

Model path:

`exp1` 不是 JSON 模型，而是搜尋器的 learning DB：

- `services/games/models/chess_experiment.db`
- runtime 工作副本：`runtime/games/models/chess_experiment.db`

- `services/games/models/chess_experiment_2_nn.json`
- runtime 工作副本：`runtime/games/models/chess_experiment_2_nn.json`

Required JSON keys:

- `version`: must be `1`
- `architecture`: optional informational string, current value `mlp-49x16x1`
- `input_size`: must be `49`
- `hidden_size`: must be `16`
- `w1`: `16 x 49` float matrix
- `b1`: `16` float vector
- `w2`: `16` float vector
- `b2`: float
- `sample_count`: integer
- `updated_at`: ISO timestamp string

The loader rejects payloads whose shapes do not match the expected sizes.

## exp3: `experiment 3:dl`

Model path:

- `services/games/models/chess_experiment_3_dl.json`
- runtime 工作副本：`runtime/games/models/chess_experiment_3_dl.json`

Replay path:

- `runtime/games/models/chess_experiment_3_dl_replay.jsonl`

Required JSON keys:

- `version`: must be `1`
- `architecture`: optional informational string, current value `mlp-49x64x32x1`
- `input_size`: must be `49`
- `hidden1_size`: must be `64`
- `hidden2_size`: must be `32`
- `w1`: `64 x 49` float matrix
- `b1`: `64` float vector
- `w2`: `32 x 64` float matrix
- `b2`: `32` float vector
- `w3`: `32` float vector
- `b3`: float
- `sample_count`: integer
- `replay_size`: integer
- `updated_at`: ISO timestamp string

## exp5: `experiment 5:nnue`

Exp5 no longer stores its main/base JSON under `services/games/models/`.
The base payload is source-embedded in:

- `services/games/chess_exp5_base_model.py`

The source base SHA-256 is:

- `88464dba7e3497e7be7474e0aae4272801fb2e98838985740e530f592f2ff992`

Runtime training writes only an experience delta:

- `runtime/games/models/chess_experiment_5_nnue_experience.json`
- `runtime/games/models/chess_experiment_5_nnue_experience_replay.jsonl`

Experience delta JSON carries:

- `artifact_role`: `adapter_or_experience_table`
- `delta_format`: `exp5_source_base_delta_v1`
- `base_model_sha256`: the source base hash above
- sparse `feature_weights` and `piece_square_weights` deltas only
- optional `opening_overlay` delta positions
- `scalar_deltas` for tempo/mobility/king-safety shifts

When no experience delta exists, exp5 runs directly from the source-embedded
base model. Older full exp5 JSON candidate files remain readable for backwards
compatibility, but new training output should be delta-only.

## Local Stockfish Difficulty

`stockfish` is not a repo model artifact. It is a local-only external UCI engine
difficulty for chess practice.

The option is exposed in `/api/games/catalog` only when the server can resolve an
executable Stockfish binary from one of these locations:

- `HTML_LEARNING_CHESS_STOCKFISH_PATH`
- `STOCKFISH_PATH`
- `stockfish` on `PATH`
- `~/reference_repos/Stockfish/src/stockfish`

Runtime tuning knobs:

- `HTML_LEARNING_CHESS_STOCKFISH_DEPTH`: fixed search depth, default `10`.
- `HTML_LEARNING_CHESS_STOCKFISH_MOVETIME_MS`: optional UCI `movetime`; default
  `0`, so depth is used.

The repo does not commit or bundle a Stockfish binary, NNUE file, opening book,
or compiled asset. Local development can point at a personally built Stockfish
binary. If a deployment or package bundles Stockfish or its neural-network
assets, that distribution must keep the applicable GPL/copyright/source
obligations with the bundled artifact.

## Local Stockfish Teacher / Filter

Stockfish can also be used as an external offline teacher. This is separate from
the playable `stockfish` difficulty:

- `scripts/games/chess_pgn_to_replay.py --stockfish-filter` converts PGN games
  first, then calls `scripts/games/chess_stockfish_teacher_audit.py`.
- `scripts/games/chess_pipeline_dryrun.py --pgn-audit-backend stockfish` uses
  the same audit script in the orchestrated PGN pipeline.
- `scripts/games/chess_seed_train.py --include-replay-jsonl ... --train-exp3-external-replay`
  can stage Stockfish-audited rows into explicit exp3, exp4, and exp5 candidate
  artifacts.
- `scripts/games/chess_exp3_dataset_train.py --teacher-backend stockfish`,
  `scripts/games/chess_exp4_dataset_train.py --teacher-backend stockfish`, and
  `scripts/games/chess_exp5_teacher_distill.py --teacher-backend stockfish` are
  direct teacher-distillation entrypoints for engine-specific experiments.

The filter emits separate files so model training can stay strict:

- `stockfish_teacher_train_rows.jsonl`: Stockfish-selected training rows.
- `stockfish_teacher_eval_rows.jsonl`: deterministic holdout rows.
- `stockfish_played_clean_rows.jsonl`: source-game moves that agreed with
  Stockfish top-K or stayed within the centipawn-loss threshold.
- `stockfish_review_rows.jsonl` and `stockfish_rejected_rows.jsonl`: retained
  for audit, not automatic training input.

Downloaded PGN rows are not trusted by download alone. They become training
candidates only after a teacher/audit step and only when fed to explicit staged
model paths.

## External training guidance

If you want an external program to train a compatible `exp2` or `exp3` model:

1. Reproduce the same `49`-dimension feature extractor shape used by the app.
2. Train your weights offline in any framework you want.
3. Export the final weights into the exact JSON shape above.
4. Write the file into the corresponding runtime model path before starting the server, or replace it while the server is stopped.

The easiest safe workflow is:

1. Let the app generate an initial model file once.
2. Load that file from your external trainer as the schema template.
3. Replace only the numeric weight/bias arrays and metadata fields.

That avoids shape drift and keeps the file loader compatible with future checks.

## Offline pipeline

相關離線流程請看：

- [Chess Training Pipeline](./chess_training_pipeline.md)

常用腳本：

- `scripts/games/chess_replay_prepare.py`
- `scripts/games/chess_seed_train.py`
- `scripts/games/chess_exp3_dataset_train.py`
- `scripts/games/chess_model_import.py`
