# 2026-05-24 09:12 :5000 Import-Mode Background Worker QA

## Findings

- No open blocker after this pass.
- Fix verification: gunicorn `server:app` import mode now starts server-owned background workers. Before the fix, `trading_background_jobs.run_count` stayed unchanged unless root triggered run-once; after reload, `price_refresh`, `order_matching`, `take_profit_stop_loss_scan`, `bot_trigger_scan`, `margin_liquidation_scan`, and `interest_accrual` advanced automatically without an active browser session.

## Changes Verified

- `server.py` now starts import-mode workers under WSGI/gunicorn with a runtime file lock and a delayed leadership retry, so HUP reloads can hand off background-worker ownership after old workers release the lock.
- `services/server/startup.py` now has a small import-mode start gate: direct `python server.py` still uses the `__main__` path, plain test imports stay side-effect-light, and gunicorn/uWSGI imports can start background workers.
- `services/trading/background_engine.py` now mirrors recurring trading background jobs into Job Center as root-visible system jobs with `source_module=trading_background`.
- `scripts/testing/playwright_trading_background_correctness.py` now supports `--trigger-mode auto`; this path closes member sessions and the root session, then waits for the server scheduler instead of calling `/root/trading/background/run-once`.

## Live :5000 Evidence

- Reloaded gunicorn master `1182501` after syncing repo into `/tmp/hackme_web_dev_20260523_231210_3869876/hackme_web`.
- `/api/version` returned OK after reload with `started_at=2026-05-24T01:05:48Z`.
- DB after reload showed background jobs advancing automatically:
  - `price_refresh` run_count `22`
  - `order_matching` run_count `19`
  - `take_profit_stop_loss_scan` run_count `21`
  - `bot_trigger_scan` run_count `19`
  - `margin_liquidation_scan` run_count `16`
  - `interest_accrual` run_count `18`
- Auto-mode Playwright evidence: `/tmp/hackme_5000_trading_background_auto_import_worker/trading_background_correctness.json`
  - No root run-once calls.
  - Member sessions and root session closed before scheduler stages.
  - Background worker matched limit orders, triggered spot stop-loss/take-profit, triggered Workflow/conditional bot, DCA bot, and Grid bot, accrued margin interest, liquidated a weak margin position, and passed trading + PointsChain verification.
- Job Center/cloud probe: `/tmp/hackme_job_center_cloud_trading_probe.py https://127.0.0.1:5000 root`
  - root admin Job Center returned 51 jobs.
  - `trading_background_count=6`, all required trading background jobs present and marked `server_background`.
  - `cloud_remote_download_job_count=6`.
  - cloud-drive remote task API returned OK with 2 root-visible remote tasks.

## Regression Checks

- `python3 -m py_compile server.py services/server/startup.py services/trading/background_engine.py scripts/testing/playwright_trading_background_correctness.py`
- `pytest -q tests/trading/core/test_trading_background_engine.py tests/platform/test_startup_worker_feature_gates.py tests/platform/test_job_center.py tests/storage/test_cloud_drive_attachments.py::test_remote_download_task_reports_progress_and_completion tests/storage/test_cloud_drive_attachments.py::test_remote_download_task_status_falls_back_to_persisted_job tests/storage/test_cloud_drive_attachments.py::test_remote_download_task_list_restores_refresh_state tests/frontend/test_platform_centers_frontend.py`
- `python3 scripts/testing/playwright_trading_background_correctness.py --base-url https://127.0.0.1:5000 --runtime-dir /tmp/hackme_web_dev_20260523_231210_3869876/hackme_web/runtime --root-password root --trigger-mode auto --stress-orders 12 --out /tmp/hackme_5000_trading_background_auto_import_worker`

## Residual Risk

- Existing old cloud remote-download rows on :5000 include several `running/downloading` tasks from earlier live testing. They are still visible in Job Center and the cloud task API; this pass did not cancel or mutate them.
