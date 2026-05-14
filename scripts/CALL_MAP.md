# Scripts Call Map

本文件記錄 `scripts/` 主要入口的調用鏈。它不是完整登記表；完整維護清單見 [INDEX.md](INDEX.md)，放置規則見 [PLACEMENT_RULES.md](PLACEMENT_RULES.md)。

## 開發與測試入口

### `../test_for_develop.sh`

```text
test_for_develop.sh
  -> 建立 /tmp 隔離 repo copy
  -> 設定 HTML_LEARNING_* 開發環境變數
  -> python3 server.py
    -> server.py::create_app / route registration
    -> runtime 使用 /tmp run root
```

用途：日常開發伺服器，不污染 repo 工作樹。

### `testing/pytest_in_tmp.sh`

```text
scripts/testing/pytest_in_tmp.sh
  -> 建立 /tmp pytest repo copy
  -> pytest <selected tests>
  -> 測試 runtime / cache 留在 /tmp
```

用途：標準 pytest 入口。

### `prepush/pre_push_checks.py`

```text
scripts/prepush/pre_push_checks.py
  -> scripts/prepush/runner.py
    -> scripts/prepush/checks/*.py
      -> syntax / docs links / release sync / local path / secrets / quick tests
```

用途：push 前本機驗證。

## Production Gate / Security

### `security/gate/on_live_reports_make.py`

```text
scripts/security/gate/on_live_reports_make.py
  -> scripts/on_live_reports/*.py wrappers
  -> scripts/security/server_mode/*.py
  -> scripts/security/pentest/*.py
  -> runtime/reports/security/production_gate/*
```

用途：產生與驗證 production gate 報告組。

### `security/gate/whole_site_production_gate.py`

```text
scripts/security/gate/whole_site_production_gate.py
  -> release / git / runtime checks
  -> pytest or configured validation hooks
  -> security gate report aggregation
  -> runtime/reports/security/whole_site_production_gate_*
```

用途：整站上線前 gate 聚合。

### `security/pentest/run_functional_smoke.sh`

```text
scripts/security/pentest/run_functional_smoke.sh
  -> 建立隔離 runtime
  -> 啟動測試 server
  -> tests/security/smoke/smoke_suite.py
  -> runtime/reports/security/functional_<RUN_ID>/
```

用途：功能 smoke。`--core-only` 給 production gate；`--qa-full` 給較廣 QA。

### `security/pentest/run_pentest.sh`

```text
scripts/security/pentest/run_pentest.sh
  -> session_security_pentest.py
  -> functional_permission_pentest.py
  -> selected external/internal checks
  -> runtime/reports/security/<RUN_ID>/
```

用途：安全測試總入口。

## Admin / Recovery

### `admin/decrypt_server_files.py`

```text
scripts/admin/decrypt_server_files.py
  -> uploaded_files rows where privacy_mode=server_encrypted
  -> services/storage/paths.py::resolve_storage_path(...)
  -> SERVER_FILE_ENCRYPTION_KEY or runtime .filekey
  -> cryptography.fernet.Fernet.decrypt(...)
  -> plaintext output directory + manifest JSON
```

用途：在伺服器端檔案金鑰仍可用時，離線解密 server-side encrypted 檔案；不解 E2EE 檔案。腳本 help、stderr 與 manifest 會明確警告：解密可能破壞與網頁使用者間的信任或觸犯隱私相關法律，操作後果請自行負責。

## Frontend / Playwright

### `testing/playwright_platform_health_check.py`

```text
scripts/testing/playwright_platform_health_check.py
  -> 建立 /tmp 隔離 runtime
  -> 啟動 hackme_web server
  -> Playwright Chromium
    -> Job Center
    -> Notification Center
    -> Share Link Management
    -> Trading Asset Overview
    -> mobile viewport checks
  -> runtime/reports/qa/playwright_platform_health_check_*
```

用途：平台中心與手機版健康檢查。

### `testing/playwright_comfyui_workflow_builder_check.py`

```text
scripts/testing/playwright_comfyui_workflow_builder_check.py
  -> 啟動/使用測試 server
  -> Playwright Chromium
    -> ComfyUI workflow builder UI
    -> workflow import/export and layout checks
```

用途：ComfyUI 視覺工作流前端驗證。

## ComfyUI

### `comfyui/materialize_system_workflows.py`

```text
scripts/comfyui/materialize_system_workflows.py
  -> services/comfyui/workflow/builder.py
  -> workflows/comfyui/*/{workflow.json,manifest.json}
```

用途：把系統 workflow preset 物化到 repo 工作流目錄。

### `comfyui/local_connection_smoke.py`

```text
scripts/comfyui/local_connection_smoke.py
  -> services/comfyui/client.py
  -> local ComfyUI HTTP API
```

用途：確認本機 ComfyUI 連線與 API 基本相容性。

## Games / AI

### `games/board_ai_benchmark.py`

```text
scripts/games/board_ai_benchmark.py
  -> services/games/board_arena.py::run_board_ai_benchmark(...)
    -> services/games/board_ai.py::choose_board_game_ai_move(...)
  -> runtime/reports/games/board_ai_benchmark_*.json
```

用途：黑白棋、圍棋、五子棋 AI 強度與 skill suite benchmark。

### `games/setup_katago.py`

```text
scripts/games/setup_katago.py
  -> 下載 KataGo binary / model
  -> 產生 runtime/katago/analysis.cfg
  -> services/games/board_ai.py 在 Go katago 難度自動偵測
```

用途：安裝 Go 的 KataGo 難度依賴。

### Chess PGN / Stockfish Teacher / Exp3-5 訓練鏈

```text
chess_pgn_to_replay.py
  -> local PGN or --source-url download cache
  -> replay JSONL
  -> --stockfish-filter (optional)
    -> chess_stockfish_teacher_audit.py
      -> stockfish_teacher_train_rows.jsonl
      -> stockfish_teacher_eval_rows.jsonl
      -> stockfish_played_clean_rows.jsonl
  -> chess_pipeline_dryrun.py --pgn-audit-backend stockfish (optional orchestrated path)

chess_pvp_history_to_replay.py / chess_sparring_to_replay.py
  -> replay JSONL
  -> chess_stockfish_teacher_audit.py (optional local external Stockfish teacher/filter)
    -> stockfish_teacher_rows.jsonl
    -> stockfish_teacher_train_rows.jsonl / stockfish_teacher_eval_rows.jsonl

stockfish_teacher_train_rows.jsonl / stockfish_played_clean_rows.jsonl
  -> chess_seed_train.py --include-replay-jsonl ... --train-exp3-external-replay
    -> exp3 DL candidate model + adjacent replay ledger
    -> exp4 PV candidate model
    -> exp5 experience/candidate artifact
  -> chess_teacher_eval_probe.py
    -> baseline-vs-candidate teacher holdout rank report

FEN or replay rows
  -> chess_exp5_teacher_distill.py
    -> teacher-selected FEN/move rows
  -> chess_exp3_dataset_train.py --teacher-backend stockfish (optional)
  -> chess_exp4_dataset_train.py --teacher-backend stockfish (optional)
  -> chess_exp5_dataset_train.py

exp5 candidate artifacts
  -> chess_exp5_dataset_train.py / chess_exp5_retrain_pipeline.py
    -> candidate model
  -> chess_exp5_strength_gate.py
  -> chess_exp5_tactical_suite.py
  -> chess_exp5_gauntlet.py
    -> chess_redact_gauntlet_evidence.py
      -> raw replay JSON/JSONL copied to runtime/private
      -> docs evidence replaced with redacted aggregate JSON/JSONL
    -> chess_gauntlet_extract_positions.py --actor ai --result draw
      -> chess_stockfish_teacher_audit.py
      -> chess_stockfish_audit_summary.py
      -> chess_exp5_draw_summary.py
    -> chess_gauntlet_extract_positions.py --actor ai --tail-actor-moves 12
      -> chess_stockfish_teacher_audit.py
      -> chess_stockfish_audit_summary.py
      -> tail/endgame conversion audit for the final AI decisions in complete games
  -> chess_exp5_validation_probe.py --question-set runtime/private/... --questions 50
    -> services/games/chess_nnue.py::choose_experiment_nnue_move(...)
    -> services/games/chess_stockfish_teacher.py::UciStockfish MultiPV
    -> redacted docs/games/evidence/exp5/*heldout_validation_50_stockfish.{json,jsonl}
  -> chess_exp5_production_readiness.py
  -> chess_exp5_promote_candidate.py
```

`chess_stockfish_teacher_audit.py` and `chess_pgn_to_replay.py --stockfish-filter`
only run when the caller provides or the environment resolves a local Stockfish
UCI binary. The binary is not part of the repo and is intentionally outside the
maintained script assets. Downloaded PGN rows remain diagnostic until they pass a
teacher/audit filter and are explicitly fed to staged model paths.

Sensitive raw learning/replay JSONL policy:

- Keep FEN/move/teacher-PV JSONL under `runtime/private/` or another ignored
  local path.
- Docs evidence should contain redacted aggregate JSON/JSONL unless a caller
  explicitly opts into private sensitive output.
- Distilled weights or non-exact feature deltas may be committed after review;
  exact-memory tables, opening books, replay priors, and `FEN -> move` adapters
  are still sensitive and should stay private unless intentionally published.

主要輸出：

- `runtime/reports/games/chess_exp5_*`
- 明確指定的 model / replay / report path
- 歸檔報告位於 `docs/games/`

## Trading

### `trading/bridges/btc_signal_bridge.py`

```text
scripts/trading/bridges/btc_signal_bridge.py
  -> services/btc_trade_bridge.py
  -> services/trading/orders.py
  -> trading DB / simulated spot orders
```

用途：把外部 BTC_trade signal 接入站內模擬交易。

### `trading/competition/*.py`

```text
scripts/trading/competition/*.py
  -> services/trading/*
  -> workflow templates
  -> benchmark output
```

用途：現行 trading benchmark。舊 workflow template competition 證據已歸檔到 `docs/archive/competition_2026-05-06/`。

## 管理

### `admin/root_recovery.py`

```text
scripts/admin/root_recovery.py
  -> runtime database
  -> user/root credential repair
  -> audit side effects where supported
```

用途：離線 root 帳號修復。

## 更新規則

- 新增 operator-facing 腳本時，同步更新本文件與 [INDEX.md](INDEX.md)。
- 只記錄穩定入口與主要呼叫鏈；不要把每個 helper function 都列入。
- 一次性實驗腳本應搬出 repo 或進 archive，不要擴大本地圖。
