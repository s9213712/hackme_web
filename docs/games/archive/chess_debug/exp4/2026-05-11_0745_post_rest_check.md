# 2026-05-11：同事接手後暫停/恢復後的復盤檢查

## 檢查目的
- 你提到「我同事看你在休息時有動一些東西」，我先確認最近未提交變更是否有異常。
- 同步確認 exp4 validation 與 tests 還能正常跑完，並記錄這次檢查結果避免漏掉。

## 變更核對
`git status --short` 顯示目前有變更（含既有實驗大版本積累）：
- `scripts/games/chess_live_learning_validation.py`（實驗/報告邏輯）
- `services/games/chess_dl.py`
- `services/games/chess_pv.py`
- `services/games/self_play_training.py`
- `services/games/models/chess_experiment_3_dl.json`
- `tests/games/test_games.py`
- `tests/scripts/games/test_chess_live_learning_validation_script.py`
- 舊的 `docs/chess_debug*` 被刪除、已改放到 `docs/games/chess_debug/*`（含 `exp3/exp4/exp5`）
- 新增 `docs/games/chess_debug/README.md`、`docs/games/chess_debug/exp*/*` 系列報告文件。

## 驗證命令
- `python3 -m py_compile scripts/games/chess_live_learning_validation.py services/games/chess_dl.py services/games/chess_pv.py services/games/self_play_training.py` ✅
- `pytest tests/scripts/games/test_chess_live_learning_validation_script.py -q` ✅（56 passed）
- `pytest tests/games/test_games.py -q`（未設 PYTHONPATH）會失敗 ModuleNotFoundError: `routes`
- `PYTHONPATH=. pytest tests/games/test_games.py -q` ✅（58 passed）
- `git diff --check` ✅

## quick gate 真機驗證
執行：
`python3 scripts/games/chess_live_learning_validation.py --quick-retrain-gate --engines exp4 --quick-retrain-max-samples 128 --quick-retrain-max-seconds 90 --quick-retrain-skip-heavy-sanity --output-root /tmp/chess_results_exp4_check_2`

結果：
- 結束 verdict：`PARTIAL`（未過）
- `new_total_checkpoint_seconds`: `151.227`
- `previous_total_checkpoint_seconds`: `1300.53`（可見仍有優化且可回溯）
- `quick_retrain_gate.enabled`: `true`
- `stochastic_auxiliary` 為 `true`（本次重跑採 `--quick-retrain-skip-heavy-sanity`）
- `promotion_gate_passed`: `false`
- 主要 gate 阻擋原因包含：
  - opening low-margin override 安全機制
  - heavy sanity skipped（預期）
  - balanced_fusion final decision generalization 未達門檻
  - hard flank gap unresolved

## 結論
- 本次檢查未發現「異常未預期改壞」跡象，主要是既有實驗系統的門檻與結果沿用預期。
- 目前差異主要來自於：
  - 文件目錄已完成 `docs` 路徑遷移與報告整理
  - exp4 quick-retrain 的 `skip-heavy` 旗標造成 heavy sanity 未跑，故 verdict 不會是 `PASS`
- 可繼續用同一套流程接續下一步，不建議直接回退。
