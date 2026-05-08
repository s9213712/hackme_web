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

## External training guidance

If you want an external program to train a compatible `exp2` or `exp3` model:

1. Reproduce the same `49`-dimension feature extractor contract used by the app.
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
