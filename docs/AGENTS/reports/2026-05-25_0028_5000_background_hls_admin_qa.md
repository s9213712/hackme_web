# 2026-05-25 00:28 5000 Background / HLS / Admin QA

## Findings Fixed

- P1: `test_for_develop.sh` full-feature dev runtime disabled trading bot auto scan and margin liquidation on every boot.
  - Impact: server background jobs were running, but DCA/Workflow bot scanning returned `bot_auto_scan_disabled`, and liquidation scans were disabled despite the requirement that trading settlement/robots run without login.
  - Fix: dev full-feature bootstrap now writes `trading.bot_auto_scan_enabled=true`, `trading.margin_liquidation_enabled=true`, and `trading.bot_audit_enabled=true`.
  - Evidence: live DB after restart shows all three values true; recent background runs include `bot_trigger_scan` with `enabled=true` and `margin_liquidation_scan` scanning candidates.

- P1: large server-encrypted HLS jobs appeared stuck at `decrypting`.
  - Impact: a 3.79 GB MKV on `/mnt/d` stayed visually flat at 20% while the worker was doing p9 I/O, making the task center look frozen.
  - Fix: chunked server-encrypted decrypt now reports bytes written; HLS maps decrypt progress into task-center status detail.
  - Evidence: retried job `d1eeaef037e7420186420d6a5d55876d` advanced from `28.0 MB / 3.53 GB` to `904.0 MB / 3.53 GB` on :5000.

- P2: concurrent duplicate `/api/admin/users` creation could throw unhandled `sqlite3.IntegrityError`.
  - Impact: stress/attack traffic creating the same username could produce 500s instead of a deterministic conflict response.
  - Fix: admin user creation now catches username unique races and returns 409 `帳號已存在`.
  - Evidence: regression test simulates the race between existence check and insert.

## Verification

- `bash -n test_for_develop.sh`
- `python3 -m py_compile routes/users.py services/storage/cloud_drive.py services/media/streaming.py scripts/media/hls_prepare_worker.py`
- `pytest -q tests/scripts/deploy/test_deploy_script.py tests/trading/core/test_trading_background_engine.py::test_background_worker_thread_runs_without_any_login_session tests/trading/core/test_trading_engine.py::test_trading_bot_auto_scan_runs_due_bots_for_all_users tests/trading/core/test_trading_engine.py::test_margin_liquidation_scan_closes_underwater_position`
- `pytest -q tests/video/streaming/test_video_streaming.py::test_prepare_stream_asset_decrypts_server_encrypted_media_before_packaging tests/video/streaming/test_video_streaming.py::test_prepare_stream_asset_reports_chunked_decrypt_progress tests/video/streaming/test_video_streaming.py::test_ffmpeg_hls_falls_back_to_transcode_when_copy_fails tests/scripts/deploy/test_deploy_script.py`
- `pytest -q tests/users/test_profile_friends.py::test_admin_create_user_duplicate_race_returns_conflict tests/users/test_profile_friends.py::test_friend_request_accept_and_friend_code_direct_add tests/video/streaming/test_video_streaming.py::test_prepare_stream_asset_reports_chunked_decrypt_progress tests/scripts/deploy/test_deploy_script.py tests/trading/core/test_trading_background_engine.py::test_background_worker_thread_runs_without_any_login_session`

## Live State

- Active URL: `https://127.0.0.1:5000`
- Runtime: `/tmp/hackme_web_pc0_5000_wallet_ui/runtime`
- Cloud drive root: `/mnt/d/hackme_web_cloud_drive_test`
- Server health: `/api/version` returned `ok=true`
- HLS worker: PID `2783796`, job running in `decrypting`
- Background trading: latest settings confirmed true for bot scan, liquidation, and bot audit.

## Residual Risk

- HLS is still limited by `/mnt/d` p9 filesystem I/O; progress now exposes that work, but the transcode can still be slow on large files.
- The live HLS job is still running and should be checked again after it reaches ffprobe/ffmpeg to confirm the copy-fallback path handles the original MKV.
