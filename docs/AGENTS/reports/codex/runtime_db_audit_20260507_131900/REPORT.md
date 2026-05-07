# Runtime / DB Audit Report

## Verdict

- `0` 文件整理與 `integrity_guard` 驗收：`PASS`
- `1` `docs/SYSTEM_DEPENDENCIES.md`：`PASS`
- `2` 西洋棋 `experiment` 引擎與自學習：`PASS`
- `3` `attachments/ avatars/ media/ uploads` runtime 污染修正：`PASS`
- `4` 分享影音頁真實 smoke（含 E2EE）：`PASS`
- `5` trading warm-up 安全性驗收：`PASS`
- `6` 主站資料庫完全拆分：`PARTIAL`

## Scope

本輪重點不是加功能，而是驗證與修補：

- runtime 檔案不得污染 repo root
- `integrity_guard` 不得把正常 deploy / 未 rebaseline 誤報成 `critical`
- 交易市場從 seed/default 價切到真實 live quote 時，不能直接釋放高風險路徑
- 西洋棋 `experiment` 難度的自學習資料不得混進主站 `database.db`

## What Was Verified

### 0. 文件整理與 integrity_guard

- 文件入口整理已落地到 `03.Points`
- `integrity_guard` 已把「正常 deploy 後 source drift 但 checkout 乾淨」降成 `degraded`
- 真正 manifest / signature / integrity 異常仍是 `critical`

證據：

- `tests/test_integrity_guard.py::test_clean_checkout_source_drift_is_health_degraded_not_critical`
- `tests/test_health_center.py::test_health_integrity_guard_clean_deploy_drift_is_degraded_not_critical`

### 1. System dependencies 文件

- 已新增 [docs/SYSTEM_DEPENDENCIES.md](../../../../SYSTEM_DEPENDENCIES.md)
- 已集中列出：
  - pip 套件
  - 系統 binary
  - 外部服務 / API key
  - runtime 生成物路徑
  - fail-closed / degraded semantics

### 2. Chess `experiment` self-learning

- `experiment` 成為正式難度值
- 引擎學習資料已移到獨立 runtime DB：
  - `runtime/database/chess_experiment.db`
- 主站 `database.db` 不再建立 `game_chess_engine_memory`
- 對局結果仍留在主站遊戲表；學習模型不混進主站 DB

證據：

- `tests/test_games.py::test_chess_practice_difficulty_is_persisted_and_rejects_invalid_value`
- `tests/test_games.py::test_experiment_learning_store_uses_separate_runtime_db`
- `tests/test_games.py::test_experiment_move_reads_learning_bias_from_store`
- `tests/test_games.py::test_experiment_resign_persists_learning_to_runtime_store`

### 3. Runtime 污染修正

#### Root cause

repo root `attachments/ avatars/ media/ uploads` 不是目前正式 runtime home。

這批目錄被重新生成的主要原因是：

- `server.py` 先前仍把 legacy root 當成 snapshot `file_roots`
- `SnapshotService._clear_file_roots()` 在 reset/restore 時會把所有 file roots 重新建立

#### Fix

- `server.py` 的 snapshot `file_roots` 現在只保留 canonical runtime roots：
  - `CHAT_DIR`
  - `STORAGE_DIR`
- 不再把 repo root `uploads/ avatars/ attachments/ media` 當作 runtime roots
- 額外修掉一個真 bug：
  - restore 若 snapshot 存在 `storage_root/snapshots/`，不能先清 `storage_root` 把自己正在 restore 的 archive 一起刪掉
  - 現在 restore 會先 stage snapshot bundle 到 file roots 外，再清 runtime roots

證據：

- `tests/test_security_defaults.py::test_runtime_artifacts_default_to_runtime_subdir_and_not_repo_root`
- `tests/test_snapshots.py::test_restore_with_runtime_storage_roots_does_not_recreate_legacy_repo_dirs`

實查結果：

- `attachments/ avatars/ media/ uploads` 都不是 git tracked
- 本輪已把這四個空目錄從 repo root 清掉

### 4. Shared video smoke

- 嚴格 E2EE share/unlock/playback/revoke flow 已整合進既有：
  - `security/run_functional_smoke.sh`
- 沒有另開一份重複定位的 smoke 腳本

證據：

- `tests/test_functional_smoke_script.py`
- `docs/security/FUNCTIONAL_SMOKE.md`

### 5. Trading warm-up safety

- 第一筆 live quote 只會進入 warm-up，不會立刻 `boot_ready`
- 第二筆穩定 quote 才能解除 boot gate
- `manual_root` / cached fallback / degraded reference price 仍不能穿透高風險路徑

證據：

- `tests/test_trading_boot_ready_gate.py`
- `tests/test_trading_engine.py`

## 6. Main DB Split Status

這一項目前只能誠實給 `PARTIAL`。

### Already Separated

- bootstrap sidecar DB
- chess experiment learning DB
- points chain backups（backup catalog / files）走 runtime sidecar path

### Still Mixed In Main `database.db`

目前主站 `database.db` 仍然混著多個 domain：

- users / auth / sessions / csrf / login security
- forum / community / reports
- chat / invites / friends
- storage / albums / share links / quota
- video / media stream / E2EE share metadata
- games core tables
- trading core tables
- snapshots / server mode / tester tokens / shadow data
- integrity guard findings / scan runs
- notifications / governance / moderation

這不是「忘了做」，而是完整拆分需要 migration strategy，不能在這輪直接硬切。

### Recommended Next Split Order

1. games core tables -> `runtime/database/games.db`
2. media/video share tables -> `runtime/database/media.db`
3. storage / quota / share tables -> `runtime/database/storage.db`
4. integrity / snapshot / server_mode 管理域 -> `runtime/database/control_plane.db`

Trading / users / sessions / auth 暫時不建議在沒有專門 migration plan 下直接拆。

## Refactor Slice / Orphan Audit

- 在 `03.Points` 當前工作樹中，沒有發現之前 refactor branch 才出現的 section-module orphan 檔
- `routes/` 目前仍是單檔為主
- `public/js/` 目前仍是單檔為主
- 沒有偵測到「切出新檔但無任何引用」的殘件

## Tests Run

- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest -q /home/s92137/hackme_web/tests/test_games.py`
  - `21 passed`
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest -q /home/s92137/hackme_web/tests/test_security_defaults.py -k runtime_artifacts_default_to_runtime_subdir_and_not_repo_root`
  - `1 passed`
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest -q /home/s92137/hackme_web/tests/test_snapshots.py::test_restore_with_runtime_storage_roots_does_not_recreate_legacy_repo_dirs`
  - `1 passed`
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest -q /home/s92137/hackme_web/tests/test_functional_smoke_script.py /home/s92137/hackme_web/tests/test_security_defaults.py /home/s92137/hackme_web/tests/test_snapshots.py -k "functional_smoke or runtime_artifacts_default_to_runtime_subdir_and_not_repo_root or restore_with_runtime_storage_roots_does_not_recreate_legacy_repo_dirs"`
  - `6 passed`
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest -q /home/s92137/hackme_web/tests/test_trading_boot_ready_gate.py /home/s92137/hackme_web/tests/test_trading_engine.py -k "warmup or boot_ready or manual_root or fallback"`
  - `28 passed`
- `python3 scripts/pre_push_checks.py --ci`
  - `12 PASS / 0 FAIL`
- `git diff --check`
  - `pass`

## Follow-up

- 若要把 `6` 從 `PARTIAL` 變成 `PASS`，下一輪要開專門 migration slice，不是繼續在同一個 `database.db` 上堆功能。
