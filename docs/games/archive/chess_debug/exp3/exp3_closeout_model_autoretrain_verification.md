# Exp3 Closeout：預設模型替換與線上 auto-retrain 串接驗證

日期：2026-05-11

## 背景

exp3 已在 exp34 後暫停作為主要棋力開發路線，但仍需要完成收尾：

- 把 exp3 目前最佳模型固定到 runtime production model。
- 保持 bundled seed 不隨 autoretrain 改變；bundled seed 只負責首次 warm-start。
- 確認前台選擇 `experiment 3:dl` 時，後端確實讀取 exp3 模型。
- 確認有效棋局會被收集到 replay ledger。
- 確認 auto-retrain 達門檻時會啟動 candidate retrain。
- 確認 retrain 完成前 production model 不被覆蓋，仍用舊模型服務。
- 確認 replay 會繼續累積，retrain 使用 candidate path，promotion 才能替換 production path。

## 來源模型

採用 exp34 的 checkpoint@20 作為 exp3 runtime production final baseline。

- 來源 summary：`<chess_results>/exp34_mixed_scheduler_repair_hard_case_decision_audit_fixed/exp3/summary.json`
- 來源模型：`<chess_results>/exp34_mixed_scheduler_repair_hard_case_decision_audit_fixed/exp3/checkpoints/20/exp3_quick_candidate_model.json`
- 來源 hash：`333ed8e72524836d39851b74f4c209c6e08f2652720cacf36a13aa2ac8448dee`
- deterministic score：`0.9462`

注意：exp34 的 promotion gate 仍是 `false / HIGH_RISK`。這次替換的語義是「把目前最佳 exp3 baseline 固定為 exp3 停止開發前的 runtime production model」，不是宣稱 exp3 已通過 production promotion。

## 修改項目

替換目前 repo runtime production model；不改 bundled seed：

```bash
mkdir -p <repo>/runtime/games/models
cp <chess_results>/exp34_mixed_scheduler_repair_hard_case_decision_audit_fixed/exp3/checkpoints/20/exp3_quick_candidate_model.json \
  <repo>/runtime/games/models/chess_experiment_3_dl.json
```

替換後驗證：

- bundled seed：`services/games/models/chess_experiment_3_dl.json`
- bundled seed hash：`025d2a8899d6c96d2d51d8843398b3f2fef83a27b72679ab138351b7c20e2ca7`
- runtime production：`runtime/games/models/chess_experiment_3_dl.json`
- runtime production hash：`333ed8e72524836d39851b74f4c209c6e08f2652720cacf36a13aa2ac8448dee`
- runtime production size：`909690`

## 前後端串接檢查

前台選項：

- `public/index.html`
- `public/js/38-games.js`

後端流程：

- `routes/games.py::create_chess_practice()` 儲存 `computer_difficulty=experiment 3:dl`
- `routes/games.py::choose_computer_move()` 遇到 `experiment 3:dl` 時呼叫 `choose_experiment_dl_move(...)`
- `services/games/chess_dl.py::default_chess_dl_model_path()` 經由 `runtime_model_path(...)` 讀取：
  - production runtime：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_3_dl.json`
  - env override：`HTML_LEARNING_CHESS_ENGINE_DL_MODEL_PATH`
  - bundled seed：`services/games/models/chess_experiment_3_dl.json`
- `routes/games.py::register_games_routes()` 會呼叫 `ensure_warm_start_chess_environment()`
- `ensure_warm_start_chess_environment()` 會在 runtime 模型不存在時從 bundled seed 複製。

## 隔離環境實測

使用 `test_for_develop.sh` 建立 isolated runtime：

```bash
cd <repo>
./test_for_develop.sh \
  --port 50732 \
  --run-root /tmp/hackme_web_exp3_closeout_20260511_b \
  --skip-install \
  --root-password RootExp3Close123! \
  --manager-password ManagerExp3Close123! \
  --test-password TestExp3Close123!
```

隔離 server：

- URL：`https://127.0.0.1:50732`
- runtime：`/tmp/hackme_web_exp3_closeout_20260511_b/hackme_web/runtime`

warm-start 結果：

- bundled model hash：`333ed8e72524836d39851b74f4c209c6e08f2652720cacf36a13aa2ac8448dee`
- runtime model hash：`333ed8e72524836d39851b74f4c209c6e08f2652720cacf36a13aa2ac8448dee`
- 結論：新 runtime 會使用替換後的 exp3 seed。

## API 對局與 replay 收集

建立 practice：

```json
{"side":"black","difficulty":"experiment 3:dl"}
```

結果：

- `match_id=1`
- `computer_difficulty=experiment 3:dl`
- 初始電腦白方走法：`e2 -> e4`
- 代表前台/後端 difficulty 已串到 exp3 move path。

完成一局短測並 resign 後，replay ledger：

- path：`runtime/reports/games/chess_replays.jsonl`
- total rows：`1`
- engine_name：`experiment 3:dl`
- collection_tier：`trusted`
- move_count：`9`
- source：`user_games`
- result_reason：`resign`

replay summary：

- total_replays：`1`
- usable_replays：`1`
- trusted_replays：`1`
- train_split_size：`1`
- eval_split_size：`0`

預設門檻檢查：

- default min usable replays：`25`
- usable=1 時 recommendation：`ready=false`
- blocked reason：`usable_replays 1 < min_usable_replays 25`

## Auto-retrain 觸發測試

使用 isolated runtime 將門檻暫時降為 1，並限制只跑 exp3：

```bash
HTML_LEARNING_CHESS_RETRAIN_MIN_REPLAYS=1
HTML_LEARNING_CHESS_AUTORUN_SKIP_BENCHMARK=1
HTML_LEARNING_CHESS_AUTORUN_SKIP_PROMOTE=1
python3 - <<'PY'
from services.games.chess_pipeline import maybe_launch_chess_train_pipeline
print(maybe_launch_chess_train_pipeline(
    trigger="qa_exp3_closeout",
    actor_username="qa",
    target_engines=("experiment 3:dl",),
))
PY
```

產生的 pipeline command：

```bash
python3 scripts/games/chess_train_pipeline.py \
  --preset standard \
  --include-quarantine \
  --min-usable-replays 1 \
  --promote-engines 'experiment 3:dl' \
  --skip-exp1-refine \
  --skip-exp4 \
  --skip-exp5 \
  --skip-benchmark \
  --skip-promote
```

pipeline 實際進度：

- replay scan：usable `1` / required `1`
- replay prepare：trusted replay seen `1`
- train samples：`4`
- eval samples：`1`
- candidate model path：`runtime/games/models/candidates/runs/pipeline_20260511T055557Z/chess_experiment_3_dl.json`
- candidate model hash：`5174785e683b77b84ae6397c533d98507853bb685a932fa22a7f09f7f10ab9f0`
- production runtime hash before：`333ed8e72524836d39851b74f4c209c6e08f2652720cacf36a13aa2ac8448dee`
- production runtime hash after polling：`333ed8e72524836d39851b74f4c209c6e08f2652720cacf36a13aa2ac8448dee`
- production_unchanged：`true`

這證明 retrain 期間 candidate 與 production 是分離的；retrain 未 promotion 前，前台棋局仍讀取 production runtime model。

這次 isolated autorun 測試刻意使用 `--skip-promote`，因此沒有自動覆蓋 production。正式 exp3 收尾已另外手動固定 repo runtime production model；bundle 不應由 retrain 改寫。

## 結果判讀

已確認成立：

- exp3 bundled default model 未隨 retrain 改變；它只作首次 warm-start seed。
- exp3 目前 repo runtime production model 已替換成 exp34 checkpoint@20。
- 新 runtime 第一次啟動會從 bundled seed 複製；之後 autoretrain/promotion 應替換 runtime production model，而不是 bundle。
- 前台/後端 difficulty `experiment 3:dl` 會走 exp3 model path。
- 有效 user game 會寫入 trusted replay ledger。
- default retrain 門檻仍是 25，有效局數不足時不會誤觸發。
- 門檻達成時 auto-retrain 會啟動 candidate pipeline。
- candidate retrain path 與 production model path 分離。
- retrain 期間 production model hash 不變，既有棋局仍用舊模型。

尚未完全對齊 exp3 最新治理線：

- 線上 auto-retrain 目前走 `scripts/games/chess_train_pipeline.py` 的 full pipeline seed/train/stage/promotion 流程。
- 它不是 exp30a/exp34 的 quick deterministic gate。
- replay prepare 目前是 `chess_replay_prepare.py` 產生 train/eval samples；這不是 exp28.5 定義的完整 high-value distilled replay preprocessor。
- 若「棋力進步才替換」要嚴格等同 exp34 deterministic balanced gate，還需要把 deterministic gate / mistake retention / safe checkpoint selection 接進 production `chess_train_pipeline.py` 的 promotion decision。

## 收尾結論

exp3 的「模型檔替換、前後端 difficulty 串接、replay 收集、門檻觸發、candidate retrain 與 production model 隔離」已確認正常。

但如果以 exp34 的標準來看，production auto-retrain promotion gate 尚未完全收斂：目前線上 pipeline 仍是 full pipeline + benchmark/stage/promotion 語義，而非 deterministic balanced gate。建議在繼續 exp4 前，至少把這個差異視為已知風險；若要讓 exp3 完整收尾，下一步應把 exp30a/exp34 的 deterministic gate 接到 `chess_train_pipeline.py` 的 promotion 判定。

## 後續建議

- 保留目前 exp3 runtime production replacement。
- exp3 production/runtime model 固定為目前最佳 baseline，不再繼續 exp3 開發。
- 不再把 exp3 當主要棋力開發路線。
- 若只需要 exp3 作 baseline，現有前後端與 replay/autorun skeleton 可接受。
- 若要 production 自動替換模型，需補 deterministic gate promotion integration，避免 benchmark 或 seed-train artifact 單獨放行。
- exp4 後續可以共用這次確認過的 replay collection、candidate path、runtime warm-start 與 production/candidate 隔離設計。
