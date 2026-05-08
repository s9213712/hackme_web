# Chess Training Pipeline

本專案的 chess AI 正式採用：

- small-engine-first
- offline-eval promotion
- stable-production-model

也就是：

1. 線上只收集 replay
2. 離線整理資料集
3. 離線訓練 candidate model
4. 跑 benchmark / smoke
5. 通過後才 stage / promote

## 1. 線上收集 replay

線上對局結束時不直接改 production model，而是把 replay 寫到：

- trusted: `runtime/reports/games/chess_replays.jsonl`
- quarantine: `runtime/reports/games/chess_replays_quarantine.jsonl`
- rejected: `runtime/reports/games/chess_replays_rejected.jsonl`

每筆資料至少包含：

- `source`
- `engine_name`
- `opening_seed`
- `result`
- `winner_color`
- `move_count`
- `confidence_score`
- `duplicate_flag`
- `resign_abuse_flag`
- `suspicious_flag`

## 2. 準備 train / eval dataset

用 replay prepare 腳本把 trusted / quarantine replay 轉成可重訓資料：

```bash
REPO_ROOT=/path/to/hackme_web
RUNTIME_DIR=/tmp/chess_runtime

cd "$REPO_ROOT"
HACKME_RUNTIME_DIR="$RUNTIME_DIR" \
PYTHONPATH="$REPO_ROOT" \
python3 scripts/games/chess_replay_prepare.py \
  --replace-output \
  --include-quarantine
```

預設輸出：

- train: `runtime/reports/games/chess_datasets/train.jsonl`
- eval: `runtime/reports/games/chess_datasets/eval.jsonl`

並額外產生報告：

- `runtime/reports/games/chess_replay_prepare_*.json`
- `runtime/reports/games/chess_replay_prepare_*.md`

### prepare 規則

- 太短的 replay 直接跳過
- quarantine 資料會自動降權
- 決勝局預設只保留勝方著法；輸方著法預設不進 dataset
- 和局著法會保留，但 target 較低
- train / eval split 依 `replay_id` 做 deterministic hash split
- 若資料太少導致 eval 空集合，腳本會自動挪一筆 train 到 eval

## 3. 先產 seed model

用 seed trainer 離線訓練可直接上線用的初始模型：

```bash
REPO_ROOT=/path/to/hackme_web
RUNTIME_DIR=/tmp/chess_runtime

cd "$REPO_ROOT"
HACKME_RUNTIME_DIR="$RUNTIME_DIR" \
PYTHONPATH="$REPO_ROOT" \
python3 scripts/games/chess_seed_train.py --preset standard
```

常用 preset：

- `micro`: 測試用，最小訓練
- `quick`: 快速產一版 seed
- `standard`: 建議一般離線訓練使用
- `strong`: 比較重，但適合正式 candidate

可選：

- `--include-exp2`
- `--skip-exp3`
- `--skip-exp4`
- `--with-smoke`
- `--with-benchmark`

預設輸出模型：

- `runtime/models/chess_experiment_2_nn.json`
- `runtime/models/chess_experiment_3_dl.json`
- `runtime/models/chess_experiment_4_pv.json`

並產生報告：

- `runtime/reports/games/chess_seed_train_*.json`
- `runtime/reports/games/chess_seed_train_*.md`

## 4. exp3 用 user dataset 再 refine

如果這一輪要用使用者棋局繼續補強 exp3，再跑：

```bash
REPO_ROOT=/path/to/hackme_web
RUNTIME_DIR=/tmp/chess_runtime

cd "$REPO_ROOT"
HACKME_RUNTIME_DIR="$RUNTIME_DIR" \
PYTHONPATH="$REPO_ROOT" \
python3 scripts/games/chess_exp3_dataset_train.py \
  --input-jsonl "$RUNTIME_DIR/reports/games/chess_datasets/train.jsonl"
```

這一步只針對 `exp3`。

## 5. 跑 benchmark / smoke

可以直接用 full trainer 只跑 smoke / benchmark：

```bash
REPO_ROOT=/path/to/hackme_web
RUNTIME_DIR=/tmp/chess_runtime

cd "$REPO_ROOT"
HACKME_RUNTIME_DIR="$RUNTIME_DIR" \
PYTHONPATH="$REPO_ROOT" \
python3 scripts/games/chess_self_play_train.py \
  --exp1-games 0 \
  --exp2-games 0 \
  --exp3-games 0 \
  --exp4-games 0 \
  --hard-exp1-games 0 \
  --hard-exp2-games 0 \
  --hard-exp3-games 0 \
  --hard-exp4-games 0 \
  --cross-games 0 \
  --cross-exp1-exp3-games 0 \
  --cross-exp2-exp3-games 0 \
  --cross-exp1-exp4-games 0 \
  --cross-exp2-exp4-games 0 \
  --cross-exp3-exp4-games 0 \
  --smoke-games-per-pair 1 \
  --benchmark-rounds 1
```

如果你已經在 repo 根目錄，也可以省略 `REPO_ROOT`：

```bash
HACKME_RUNTIME_DIR=/tmp/chess_runtime PYTHONPATH=. \
python3 scripts/games/chess_seed_train.py --preset standard
```

報告會落在：

- `runtime/reports/games/chess_self_play_train_*.json`
- `runtime/reports/games/chess_self_play_train_*.md`

## 6. Stage / Promote

root backend 只負責：

- 看 pipeline 狀態
- stage candidate
- promote candidate

相關 API：

- `GET /api/root/games/chess/engines/dashboard`
- `POST /api/root/games/chess/warm-start`
- `POST /api/root/games/chess/promotion/stage`
- `POST /api/root/games/chess/promotion/promote`

promotion gate 至少會檢查：

- benchmark report 存在
- `games >= 6`
- `score_rate >= 0.45`
- `win_rate >= 0.30`
- `draw_rate <= 0.85`
- `suspicious_matches == 0`
- smoke pass

## 7. 正式原則

禁止：

- startup 時重訓
- user game 即時覆蓋 production model
- 未經 benchmark 的 model 直接 promote

正式流程只應該是：

1. 收 replay
2. `chess_replay_prepare.py`
3. `chess_seed_train.py`
4. `chess_exp3_dataset_train.py`（只在需要 exp3 refine 時）
5. benchmark / smoke
6. stage / promote
