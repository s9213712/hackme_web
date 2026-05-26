# 2026-05-24 21:40 :5000 /mnt/d Storage Live QA

## Findings

No confirmed product regressions in this pass.

## Verified

- Live server was healthy on `https://127.0.0.1:5000/api/version`.
- Gunicorn was running with 3 workers and 6 threads.
- `system_settings` contains:
  - `cloud_drive_storage_root=/mnt/d/hackme_web_cloud_drive_test`
  - `cloud_drive_global_capacity_limit_mb=1024`
- A root cloud-drive upload created `9dcee57e09df4880b78ece55e9efcefe` and the physical file exists at:
  `/mnt/d/hackme_web_cloud_drive_test/users/1/2d44cf5025bd4ed4869c5bbcdd994be7/hackme_mntd_upload_check.txt`
- The same uploaded filename was not found under:
  `/tmp/hackme_web_pc0_5000_wallet_ui/runtime/storage/users/1`
- `/api/files/quota` reports disk path `/mnt/d/hackme_web_cloud_drive_test` and uses the configured root capacity.
- `test_for_develop.sh --cli --dry-run --cloud-drive-root /mnt/d --cloud-drive-max-size 2G` resolves:
  - `cloud_drive_root: /mnt/d`
  - `cloud_drive_max_mb: 2048`

## Live Probes

- `python3 -m py_compile scripts/testing/playwright_trading_background_correctness.py` passed.
- Trading background probe passed after updating the probe for pc0 internal settlement:
  `/tmp/hackme_web_goal_qa_20260524/trading_background_after_mntd_rerun/trading_background_correctness.json`
- The trading probe verified:
  - governance treasury grants to pc0 settle as `internal_hot_wallet`, `chain_required=false`, `finality_status=internal_settled`
  - order matching, stop-loss, take-profit, DCA bot, conditional bot, grid bot, interest accrual, liquidation
  - concurrent order stress had 12 successful requests and no 5xx
  - trading verify and PointsChain verify both passed
- Chat/video share link probe passed as root:
  `/tmp/hackme_web_goal_qa_20260524/chat_video_share_after_mntd_root.json`

## Notes

- A `test` upload attempt was rejected by daily upload limit, so the path-write check used root.
- A CSRF alert for `/api/cloud-drive/upload` was caused by this QA run retrying an upload with an expired/invalid token. The request was correctly rejected.
- Earlier CSRF alerts for root/admin endpoints came from the security permission probe intentionally sending invalid CSRF samples. The server correctly logged and blocked them.
- The first trading background run failed because the QA script still expected `20 Proved` for governance treasury grants. Under the pc0 model, those grants are internal ledger settlements. The script now accepts `internal_settled` for internal rails and still requires `proved/sealed` for cold-chain rails.
