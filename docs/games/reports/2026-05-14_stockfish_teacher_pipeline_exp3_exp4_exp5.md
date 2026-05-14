# 2026-05-14 Stockfish Teacher Pipeline For Exp3 / Exp4 / Exp5

## Scope

本次工作把本機外部 Stockfish 從「可手動 audit」擴充成可被 PGN 下載/轉檔、
pipeline dry-run、exp3/exp4/exp5 訓練入口共同使用的 teacher/filter。

不提交、不下載、不打包 Stockfish binary 或 NNUE 檔；本地測試使用：

- `/home/s92137/reference_repos/Stockfish/src/stockfish`
- Stockfish reference: `dd321af5dfc0789de07c4e5c64915073995eb818`

## Stage Summaries

1. 入口盤點

   - 確認既有 `chess_stockfish_teacher_audit.py` 可輸出
     `stockfish_teacher_train_rows.jsonl`、`stockfish_teacher_eval_rows.jsonl`、
     `stockfish_played_clean_rows.jsonl`。
   - 需求重點：下載棋局腳本也必須能直接調用 Stockfish 篩選。

2. PGN 下載/轉檔加入 Stockfish filter

   - `chess_pgn_to_replay.py` 新增 `--stockfish-filter` 與 Stockfish 參數。
   - 轉出 replay JSONL 後自動呼叫 `chess_stockfish_teacher_audit.py`。
   - filter artifact 預設落在 `<replay_stem>_stockfish_filter/`，也可用
     `--stockfish-output-dir` 指定。

3. Seed training 接入 exp3

   - `chess_seed_train.py` 允許 `stockfish_teacher_audited` 與
     `stockfish_played_move_clean` trusted source。
   - 加入 `--train-exp3-external-replay`。預設仍不把外部 replay 寫入 exp3，
     避免舊流程意外污染模型。
   - 啟用後，同一批 audit rows 可以同時 staging 到 exp3 DL、exp4 PV、
     exp5 NNUE/experience candidate paths。

4. Exp3 / Exp4 teacher distillation

   - `chess_exp3_dataset_train.py` 支援 `--teacher-backend stockfish`。
   - `chess_exp4_dataset_train.py` 支援 `--teacher-distill-jsonl` 與
     `--teacher-backend stockfish`。
   - 用 MultiPV top-K 產生 teacher top moves、centipawn context、hard-negative
     source move。

5. Exp5 teacher row 品質提升

   - `chess_exp5_teacher_distill.py` 對 Stockfish/deeper/book backend 產生
     cp-gap-based `teacher_top_weights`。
   - 來源走法若明顯落出 teacher top-K，會保留成 hard negative，而不是只丟掉。

6. Pipeline / report 可追溯

   - `chess_pipeline_dryrun.py --pgn-audit-backend stockfish` 可切換成
     Stockfish audit backend。
   - `chess_pipeline_report.py` 可辨識 `stockfish_teacher_audit` summary，並正規化
     accepted/eval/review/rejected/played-clean 指標。
   - `scripts/CALL_MAP.md`、`scripts/INDEX.md`、`chess_model_files.md` 已更新。

## Smoke Evidence

本機實跑 `chess_pgn_to_replay.py --stockfish-filter`，只寫入 `/tmp`：

```text
input PGN: /tmp/hackme_stockfish_filter_smoke.pgn
output replay: /tmp/hackme_stockfish_filter_smoke_replay.jsonl
stockfish output: /tmp/hackme_stockfish_filter_smoke_audit
depth: 4
MultiPV: 3
max_positions: 8
```

結果：

```text
written_records: 1
extracted_positions: 16
selected_positions: 8
teacher_rows: 8
teacher_train_rows: 8
teacher_eval_rows: 0
played_clean_rows: 8
review_rows: 0
rejected_rows: 0
```

代表下載/轉檔腳本已能一路呼叫外部 Stockfish filter，並產生可交給
`chess_seed_train.py --include-replay-jsonl` 的 teacher rows。

接著用同一批 teacher rows 跑 `chess_seed_train.py --dry-run`：

```text
include_replay_jsonl: /tmp/hackme_stockfish_filter_smoke_audit/stockfish_teacher_train_rows.jsonl
train_exp3_external_replay: true
rows_total: 8
rows_kept: 8
normalize_exp3: 8/8
normalize_exp4: 8/8
normalize_exp5: 8/8
trained_exp3: false
trained_exp4: false
trained_exp5: false
reason: dry_run
```

這證明 Stockfish filter 輸出的 rows 不只會產生檔案，也能通過 exp3/4/5 的
staged training normalize gate。這次沒有寫入任何預設模型。

## Script Call Map

```text
chess_pgn_to_replay.py
  -> optional --source-url download
  -> replay JSONL
  -> optional --stockfish-filter
    -> chess_stockfish_teacher_audit.py
      -> stockfish_teacher_train_rows.jsonl
      -> stockfish_teacher_eval_rows.jsonl
      -> stockfish_played_clean_rows.jsonl
  -> chess_seed_train.py --include-replay-jsonl ... --train-exp3-external-replay
    -> exp3 candidate model/replay
    -> exp4 candidate model
    -> exp5 candidate/experience artifact
```

Direct engine-specific distillation:

```text
FEN/replay rows
  -> chess_exp3_dataset_train.py --teacher-backend stockfish
  -> chess_exp4_dataset_train.py --teacher-backend stockfish
  -> chess_exp5_teacher_distill.py --teacher-backend stockfish
```

## Verification

Passed:

```text
python3 -m py_compile \
  scripts/games/chess_seed_train.py \
  scripts/games/chess_pgn_to_replay.py \
  scripts/games/chess_pipeline_dryrun.py \
  scripts/games/chess_pipeline_report.py \
  scripts/games/chess_exp3_dataset_train.py \
  scripts/games/chess_exp4_dataset_train.py \
  scripts/games/chess_exp5_teacher_distill.py

python3 -m pytest -q \
  tests/scripts/games/test_chess_pgn_to_replay_script.py \
  tests/scripts/games/test_chess_exp3_dataset_train_script.py \
  tests/scripts/games/test_chess_exp5_teacher_distill_script.py \
  tests/scripts/games/test_chess_seed_train_external_replay.py \
  tests/scripts/games/test_chess_seed_train_cli_contract.py \
  tests/scripts/games/test_chess_pipeline_dryrun.py \
  tests/scripts/games/test_chess_pipeline_report.py
```

Targeted pytest result:

```text
102 passed
```

## Objective Assessment

這次不是直接宣稱 exp5 棋力上升，而是補齊「高品質 teacher 資料進入模型候選」的
工程閉環。Stockfish 可以：

- 篩掉下載棋局中的低價值/疑似錯誤走法。
- 將好棋轉成 teacher top move 訓練 rows。
- 將來源走法與 teacher 差距過大的局面保留成 hard negative 或 review。
- 同一套資料同時餵給 exp3/exp4/exp5 candidate，不直接污染預設模型。

下一階段應用這批資料時，仍需用獨立 held-out 題、gauntlet、Stockfish 對局或 UCI
harness 檢查是否真的提升棋力。
