# 2026-05-24 09:58 :5000 同事改動融合前後端 QA

## 結論

- 已把目前 repo 工作樹同步到 `https://127.0.0.1:5000` runtime，並對 gunicorn master `1182501` 執行 HUP reload。
- 同步後 `/api/version` 正常，`started_at=2026-05-24T01:50:21Z`。
- 新的前後端融合測試通過；沒有確認到仍未修正的融合回歸。

## 研究到的問題與修正

1. 雲端遠端下載的持久化任務列可能在 worker/HUP 後停留 `running`
   - 影響：任務列表可見，但舊的 BT/magnet 下載會永久顯示執行中，誤導使用者。
   - 修正：`services/job_center.py` 新增 `expire_stale_cloud_remote_download_jobs()`，依照任務 timeout 將 orphan active row 轉為 `failed`，並保留失敗事件與訊息。
   - 串接：`routes/jobs.py` 的 `/api/jobs`、`/api/admin/jobs`，以及 `routes/files.py` 的雲端遠端下載狀態/列表查詢前都會執行 stale cleanup。
   - 保護：paused 任務不會被自動標失敗；新建任務會記錄 `timeout_seconds` 到 Job Center metadata。

2. Job Center schema cache 對 in-memory SQLite 有 id 重用風險
   - 影響：測試/臨時 DB 可能被誤判 schema 已存在，造成 `no such table: job_center_jobs`。
   - 修正：`services/job_center.py` 對無檔案路徑的 DB 不使用全域 schema cache，直接確保 schema。

## 測試結果

- 語法檢查：通過
  - `python3 -m py_compile ...`
  - `node --check public/js/00-core.js public/js/01-root-quick-settings.js public/js/20-chat.js public/js/36-comfyui.js public/js/50-admin.js public/js/55-economy.js public/js/56-trading.js public/js/57-platform-centers.js public/js/90-bootstrap.js`
- 後端 targeted pytest：通過
  - `tests/platform/test_job_center.py`
  - 雲端遠端下載持久化/進度/恢復測試
  - `tests/frontend/test_platform_centers_frontend.py`
  - `tests/trading/core/test_trading_background_engine.py`
- Live 前後台雲端/影音/任務中心探針：通過
  - artifact: `/tmp/hackme_5000_fusion_fresh_cloud_video_job_probe_20260524/report.json`
  - 覆蓋：新 trusted 帳號、雲端上傳/預覽、E2EE 預覽拒絕、分享下載、影音密碼分享、雲端背景下載 task API、root/會員前台任務中心。
- Live 交易背景自動化 Playwright：通過
  - artifact: `/tmp/hackme_5000_fusion_trading_background_auto_20260524/trading_background_correctness.json`
  - 覆蓋：無登入狀態自動掛單成交、止盈止損、DCA/條件/網格機器人、借貸利息、強平、交易驗證、PointsChain verify、基金非負。
- Live 多功能壓測：通過
  - artifact: `/tmp/hackme_5000_fusion_system_stress_20260524.json`
  - 120 ops / concurrency 12；排除保護性 `server_busy` 503 後 hard failure rate = 0。
- 壓測後不變式：通過
  - artifact: `/tmp/hackme_5000_fusion_post_stress_invariants_after_multifeature_20260524/report.json`
  - 交易 verify 無錯、PointsChain verify OK、交易所基金非負、錢包/鎖倉非負、無超過一小時 stale active 背景任務。

## 注意事項

- `test` 共用帳號仍會因長期 QA 用量觸發每日上傳限制；這是配額行為，不是雲端/影音功能回歸。fresh trusted user 探針已排除這個假陽性。
- 壓測中的 `server_busy` 503 是 backpressure 保護行為，本輪以 `--allow-server-busy` 允許，且未出現非 503 hard failure。
