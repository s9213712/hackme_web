# Standard Realtime Proxy Phase 1

日期：2026-05-27

## 完成項目

Standard 即時轉封裝服務已補上 Phase 1 後端實作，預設由 feature flag 關閉。

新增能力：

- 一般影音：`GET /api/videos/<video_id>/realtime-proxy`
- 分享影音：`GET /api/videos/shared/<token>/realtime-proxy`
- Cloud Drive 預覽：`GET /api/cloud-drive/files/<file_id>/realtime-proxy`
- 檔案分享預覽：`GET /api/storage/shared/<token>/realtime-proxy`

控制參數：

- `HACKME_MEDIA_REALTIME_PROXY_ENABLED=1` 才開放。
- `HACKME_MEDIA_REALTIME_PROXY_MAX_CONCURRENT` 控制同機同 runtime 的同時轉封裝數，預設 2。
- `HACKME_MEDIA_REALTIME_PROXY_LIMIT_SCOPE` 可設 `global` / `process`；預設 `auto`，有 `HACKME_RUNTIME_DIR` 或指定 lock dir 時使用 host-global file slots，否則退回 process-local。
- `HACKME_MEDIA_REALTIME_PROXY_LOCK_DIR` 可指定 host-global slot lock 目錄。
- `HACKME_MEDIA_REALTIME_PROXY_TIMEOUT_SECONDS` 控制單一 ffmpeg streaming 程序壽命，預設 4 小時。
- `HACKME_MEDIA_REALTIME_PROXY_AUDIO_BITRATE` 控制即時音訊轉碼 bitrate，預設 `160k`。

播放參數：

- `audio` / `audio_track` / `track` 可選音軌，例如 `audio_02_eng`、stream index、語言或序號。
- `start` 可指定近似起播秒數。

## 實作策略

ffmpeg 命令策略和 Scarlet 5 分鐘 benchmark 一致：

- video：`copy`，避免重編 H.264 影像。
- audio：只轉選定音軌到 AAC stereo。
- output：fragmented MP4 pipe。
- 明確移除 metadata、chapters、subtitle、data tracks，避免 MKV 的 `bin_data` 或字幕子資源混入 MP4。
- generator 結束、client disconnect、timeout 都會 terminate / kill ffmpeg 並釋放併發 slot。

## 權限邊界

所有 route 都沿用既有授權：

- 一般影音走 `get_video(..., for_stream=True)`。
- 分享影音走 share token / password / share session / max views。
- Cloud Drive 預覽走 `can_download_file(..., action="preview")` 和 security policy。
- 檔案分享預覽走 share token / password / preview permission / security policy。

明確不支援：

- strict E2EE：不可伺服器端解密轉封裝。
- `server_encrypted`：Phase 1 不在主請求路徑解密給每位觀看者；仍建議走 Premium HLS。

## Payload 狀態

`stream_playback_payload()` 現在會回：

- `realtime_proxy_url`
- `realtime_proxy.available`
- `realtime_proxy.implementation_status`
- `service_policy.realtime_proxy_enabled`
- `service_policy.realtime_proxy_max_concurrent`
- Standard `streaming_options[*].implementation_status`

feature flag 關閉時 Standard 是 `disabled`；開啟且來源可用時是 `ready`。

## 驗證

- `python3 -m py_compile services/media/streaming.py routes/videos.py routes/files.py routes/file_sections/share_preview_routes.py tests/video/streaming/test_video_streaming.py`
- `pytest -q tests/video/streaming/test_video_streaming.py`
  - 53 tests passed
- `git diff --check`

新增測試覆蓋：

- 即時轉封裝 ffmpeg command 會選指定音軌、strip metadata/chapters/subtitle/data tracks。
- playback payload 在 feature flag 開啟時回傳 Standard route 與 ready 狀態。
- `/api/videos/<video_id>/realtime-proxy` route 會把 audio/start 參數傳入 streaming service，並回傳 fragmented MP4 stream。

## Phase 1.1 前端補完

已補上正式產品入口，不只後端 route 可用：

- 一般影音播放頁提供 Basic / Standard / Premium 方案選擇。
- 分享影音頁提供同一套方案選擇，並把 `share_session` 套到 Standard 子資源。
- Cloud Drive 預覽提供同一套方案選擇，含全螢幕預覽。
- 檔案分享預覽提供同一套方案選擇，含分享密碼 URL 參數。
- 多音軌影片在 Standard 模式會以 `audio=<track>` 重新開啟即時轉封裝；HLS 模式維持原本的 HLS audio track 切換。

## 最新驗證

- `node --check public/js/39-videos.js public/js/shared-video.js public/js/shared-file.js public/js/35-drive.js`
- `python3 -m py_compile services/media/streaming.py routes/videos.py routes/files.py routes/file_sections/share_preview_routes.py tests/video/streaming/test_video_streaming.py tests/frontend/video/test_frontend_videos.py tests/frontend/storage/test_frontend_drive_preview.py`
- `pytest -q tests/video/streaming/test_video_streaming.py tests/frontend/video/test_frontend_videos.py tests/frontend/storage/test_frontend_drive_preview.py`
  - 73 tests passed
- `git diff --check`

## Phase 1.2 Runtime Guardrails

新增回歸測試，覆蓋 Standard 即時轉封裝最容易出事的 runtime 行為：

- `open_realtime_proxy_stream()` 在 client 關閉 generator 時會 close stdout、terminate ffmpeg，並釋放併發 slot。
- `HACKME_MEDIA_REALTIME_PROXY_MAX_CONCURRENT=1` 時第二條即時轉封裝會被拒絕為 `realtime_proxy_busy`。
- 一般影音 route 在 busy 時回 `429`，且錯誤分類維持 `realtime_proxy_busy`。
- 分享影音 playback 會把 `realtime_proxy_url` 改成 `/api/videos/shared/<token>/realtime-proxy`，並帶 `share_session`。
- 分享影音 realtime proxy route 會保留分享 session、音軌與 `start` 參數。
- Cloud Drive 預覽 realtime proxy route 會走預覽授權，並傳入音軌與 `start` 參數。
- 檔案分享 realtime proxy route 會要求分享密碼，解鎖後才允許 Standard 即時轉封裝。

驗證命令：

- `pytest -q tests/video/streaming/test_video_streaming.py -k "realtime_proxy or shared_standard_video_playback"`
  - 6 tests passed
- `pytest -q tests/storage/test_cloud_drive_attachments.py -k "realtime_proxy_routes or server_encrypted_mkv_share_preview"`
  - 2 tests passed

## Phase 1.3 Real ffmpeg Smoke

新增真實 ffmpeg / ffprobe integration，不再只靠 mock 驗證 Standard 路徑：

- 測試會用 ffmpeg 產生 3 秒 MKV fixture：
  - H.264 video
  - `audio_01_jpn`
  - `audio_02_eng`
  - 內嵌 SRT 字幕
- 呼叫 `open_realtime_proxy_stream(..., audio_track="audio_02_eng")` 走真實 ffmpeg pipe。
- 產出的 fragmented MP4 會再用 ffprobe 驗證：
  - container 是 MP4 / MOV family
  - video 仍為 H.264 copy 路線
  - 只剩一條 audio stream
  - audio codec 是 AAC
  - audio channels 是 stereo
  - subtitle/data tracks 沒有進入 Standard MP4
  - stream 結束後 realtime proxy active slot 歸零

驗證命令：

- `pytest -q tests/video/streaming/test_video_streaming.py -k "real_ffmpeg_outputs_single_aac_audio_track"`
  - 1 test passed

## Phase 1.4 Browser Smoke

Playwright browser compatibility probe 已補上 Standard 即時轉封裝驗證：

- 測試 fixture 改為真實多音軌 MKV：
  - H.264 video
  - `audio_01_jpn`
  - `audio_02_eng`
  - 內嵌 SRT 字幕
- 測試 runtime 會開啟 `HACKME_MEDIA_REALTIME_PROXY_ENABLED=1` 與 `HACKME_MEDIA_REALTIME_PROXY_MAX_CONCURRENT=2`。
- 分享影音頁會先確認 Basic / Standard / Premium selector 存在。
- 切到 Standard 後，player source 必須改成 `/realtime-proxy`。
- 多音軌 selector 必須至少列出日文與英文兩條音軌。
- 切換第二音軌後，Standard URL 必須帶 `audio=audio_02_eng`。
- Probe 會直接 fetch realtime proxy URL，確認 HTTP `200`、`Content-Type: video/mp4`，且第一個 chunk 有資料。

這次也修正一個產品缺口：如果 HLS 尚未 ready，但 Standard 即時轉封裝可用，`stream_playback_payload()` 現在會用 ffprobe 輕量探測來源檔音軌，讓前端在 Standard 模式仍能顯示多音軌選單，不必等 Premium HLS 衍生檔完成。

驗證命令：

- `python3 scripts/testing/playwright_browser_video_compat.py --browsers chromium --skip-mobile --runtime-root /tmp/hackme_web_browser_standard_phase14b`
  - `[PASS] chromium desktop`
  - artifact: `/tmp/hackme_web_browser_standard_phase14b/reports/qa/browser_video_compat.md`

## Phase 1.5 Concurrency / Disconnect Probe

Standard realtime proxy 已補上更接近生產風險的資源壓測與 instrumentation：

- `open_realtime_proxy_stream()` 現在會先取得 concurrency slot，再做 ffprobe / ffmpeg setup。
  - 達到 `HACKME_MEDIA_REALTIME_PROXY_MAX_CONCURRENT` 時直接回 `realtime_proxy_busy`，不再先掃來源檔。
- 每條 realtime proxy stream 會保留 per-stream metrics：
  - `first_chunk_latency_ms`
  - `bytes_sent`
  - `chunks_sent`
  - `duration_ms`
  - `rss_peak_bytes`
  - `cpu_time_seconds`
  - `closed_by_client`
  - `terminated` / `killed` / `returncode`
- 新增 `scripts/testing/realtime_proxy_stress_probe.py`，會產生多音軌 MKV，驗證：
  - concurrency limit 觸發 `realtime_proxy_busy:1/1`
  - 讀第一個 chunk 後模擬 client disconnect
  - disconnect 後 active slot 回到 0
  - 斷線後可重新開啟第二音軌 `audio_02_eng`
  - metrics 有首 chunk latency 與 ffmpeg 資源樣本

本次實測：

- `pytest -q tests/video/streaming/test_video_streaming.py -k "realtime_proxy_real_ffmpeg or releases_slot_on_client_close"`
  - 2 tests passed
- `pytest -q tests/video/streaming/test_video_streaming.py`
  - 58 tests passed
- `python3 scripts/testing/realtime_proxy_stress_probe.py --runtime-root /tmp/hackme_web_realtime_proxy_stress_phase15`
  - `[pass] realtime proxy stress probe`
  - artifact: `/tmp/hackme_web_realtime_proxy_stress_phase15/reports/qa/realtime_proxy_stress_probe.md`
  - first stream：`first_chunk_latency_ms=31.936ms`，`release_ms=7.404ms`，`rss_peak_bytes=51175424`
  - reopen stream：`first_chunk_latency_ms=31.861ms`，`output_bytes=13726`，`selected_audio=audio_02_eng`
- `python3 scripts/testing/playwright_browser_video_compat.py --browsers chromium --skip-mobile --runtime-root /tmp/hackme_web_browser_standard_phase15b`
  - `[PASS] chromium desktop`
  - artifact: `/tmp/hackme_web_browser_standard_phase15b/reports/qa/browser_video_compat.md`
  - Standard selector / audio switch / realtime proxy MP4 first chunk all passed.

## Phase 1.6 Live HTTP Concurrency Probe

補上 route 層真 HTTP 併發壓測，不再只靠 service generator：

- 新增 `scripts/testing/realtime_proxy_http_concurrency_probe.py`。
- Probe 會啟動 isolated server、上傳 10MB 級 lossless 多音軌 MKV、建立密碼分享並解鎖 share session。
- `HACKME_MEDIA_REALTIME_PROXY_MAX_CONCURRENT=1` 下先 hold 一條 Standard `/realtime-proxy` HTTP stream。
- 同時打：
  - 第二條 Standard `/realtime-proxy?audio=audio_02_eng`
  - Basic direct shared stream
  - Premium HLS master / playlist / first segment
- 驗收：
  - 第一條 Standard：`200 video/mp4`
  - 第二條 Standard：`429 realtime_proxy_busy`
  - Basic direct：`200` 且能取 first chunk
  - Premium HLS：master、playlist、segment 都能讀

本次實測：

- `python3 scripts/testing/realtime_proxy_http_concurrency_probe.py --runtime-root /tmp/hackme_web_realtime_proxy_http_phase16d --max-concurrent 1`
  - `OK: True`
  - artifact: `/tmp/hackme_web_realtime_proxy_http_phase16d/reports/qa/realtime_proxy_http_concurrency_probe.md`
  - fixture：`10298714 bytes`
  - held Standard：`200 video/mp4`，header `1300.687ms`
  - busy Standard：`429 application/json`，body error `realtime_proxy_busy`
  - Basic direct：`200`，first chunk `4096 bytes`，`1022.773ms`
  - Premium HLS segment：`200 video/mp4`，first chunk `4096 bytes`，`518.501ms`
- `python3 scripts/testing/playwright_browser_video_compat.py --browsers chromium --skip-mobile --runtime-root /tmp/hackme_web_browser_standard_phase16`
  - `[PASS] chromium desktop`
  - artifact: `/tmp/hackme_web_browser_standard_phase16/reports/qa/browser_video_compat.md`

## Phase 1.7 Server-Side Metrics Artifact

把 realtime proxy final metrics 從 service generator 往 route 層落盤，讓 live HTTP probe 可以驗 server-side 狀態，而不是只看 client-side header / first chunk latency。

新增行為：

- 每條 `/realtime-proxy` stream 都會寫入 `reports/qa/realtime_proxy_stream_metrics.jsonl`。
- JSONL row 包含 request id、route kind、audio selector、selected audio、runtime scope / active / limit、source size、以及 final stream metrics。
- Route 回應加上 `X-Hackme-Realtime-Proxy-Request-Id`，方便把 client probe 與 server JSONL 對上。
- HTTP concurrency probe 現在會等待並驗證 metrics JSONL：
  - `finished`
  - `bytes_sent`
  - `rss_peak_bytes`
  - `cpu_time_seconds`
  - `closed_by_client`
  - host-global runtime scope

本次實測：

- `pytest -q tests/video/streaming/test_video_streaming.py -k "realtime_proxy_route_writes_server_metrics_jsonl or video_realtime_proxy_route_streams"`
  - 2 tests passed
- `python3 scripts/testing/realtime_proxy_http_concurrency_probe.py --runtime-root /tmp/hackme_web_realtime_proxy_http_phase17 --max-concurrent 1`
  - `OK: True`
  - artifact: `/tmp/hackme_web_realtime_proxy_http_phase17/reports/qa/realtime_proxy_http_concurrency_probe.md`
  - server metrics: `/tmp/hackme_web_realtime_proxy_http_phase17/reports/qa/realtime_proxy_stream_metrics.jsonl`
  - held Standard：`200 video/mp4`，header `1017.506ms`
  - busy Standard：`429 realtime_proxy_busy`，header `1357.456ms`
  - Basic direct：`200`，first chunk `4096 bytes`，`794.335ms`
  - Premium HLS segment：`200`，first chunk `4096 bytes`，`653.47ms`
  - server metrics latest：`bytes_sent=656616`，`chunks_sent=11`，`first_chunk_latency_ms=70.746`，`duration_ms=2936.106`，`rss_peak_bytes=63324160`，`cpu_time_seconds=0.22`，`closed_by_client=True`

## Phase 1.8 Host-Global Slot Semantics

修正多 worker / gunicorn 部署風險：原本 `HACKME_MEDIA_REALTIME_PROXY_MAX_CONCURRENT` 只約束單一 Python process；多 worker 時實際上限會變成 `workers * limit`，會讓 Standard 服務費率與 CPU/RSS 成本邊界失真。

新增行為：

- `HACKME_MEDIA_REALTIME_PROXY_LIMIT_SCOPE=auto` 為預設。
- 有 `HACKME_RUNTIME_DIR` 或 `HACKME_MEDIA_REALTIME_PROXY_LOCK_DIR` 且平台支援 `fcntl` 時，使用 host-global file-slot semaphore。
- 沒有 runtime / 非 Unix 環境時，保留 process-local fallback。
- 達到 host-global slot 上限時，仍直接回 `realtime_proxy_busy`，且發生在 ffprobe / ffmpeg setup 之前。
- `realtime_proxy_runtime_status()` 與 final metrics 現在會帶：
  - `scope`
  - `active`
  - `local_active`
  - `global_active`
  - `slot_index`

新增回歸測試：

- 外部 process 已持有 `realtime_proxy_slot_00.lock` 時，本 process 會直接 `realtime_proxy_busy:1/1`。
- 測試確認不會呼叫 `build_realtime_proxy_command()`，也就是不會先掃檔或啟動 ffmpeg。

驗證命令：

- `python3 -m py_compile services/media/streaming.py routes/videos.py scripts/testing/realtime_proxy_stress_probe.py scripts/testing/realtime_proxy_http_concurrency_probe.py tests/video/streaming/test_video_streaming.py`
- `pytest -q tests/video/streaming/test_video_streaming.py -k "global_slot_rejects or route_writes_server_metrics_jsonl or releases_slot_on_client_close"`
  - 3 tests passed
- `python3 scripts/testing/realtime_proxy_stress_probe.py --runtime-root /tmp/hackme_web_realtime_proxy_stress_phase18 --duration 3`
  - `OK: True`
  - artifact: `/tmp/hackme_web_realtime_proxy_stress_phase18/reports/qa/realtime_proxy_stress_probe.md`
  - checks：`busy_limit=True`，`disconnect_release=True`，`reopen_after_disconnect=True`，`metrics_present=True`，`host_global_slot_scope=True`
  - first stream：`first_chunk_latency_ms=32.722ms`，`rss_peak_bytes=51568640`，`runtime_scope=global`，`runtime_slot_index=0`
  - reopen stream：`output_bytes=79835`，`selected_audio=audio_02_eng`，`rss_peak_bytes=51679232`，`runtime_scope=global`
- `python3 scripts/testing/realtime_proxy_http_concurrency_probe.py --runtime-root /tmp/hackme_web_realtime_proxy_http_phase18 --max-concurrent 1`
  - `OK: True`
  - artifact: `/tmp/hackme_web_realtime_proxy_http_phase18/reports/qa/realtime_proxy_http_concurrency_probe.md`
  - HTTP checks：`held_standard_200=True`，`busy_standard_429=True`，`basic_direct_ok=True`，`premium_hls_ok=True`
  - server metrics checks：`present=True`，`finished=True`，`bytes_sent=True`，`rss_peak_bytes=True`，`cpu_time_seconds=True`，`closed_by_client=True`，`host_global_scope=True`
  - held Standard：`200 video/mp4`，header `1052.552ms`
  - busy Standard：`429 realtime_proxy_busy`，header `908.371ms`，body status 顯示 `scope=global`、`global_active=1`、`global_free=0`
  - Basic direct：`200`，first chunk `4096 bytes`，`1382.621ms`
  - Premium HLS segment：`200`，first chunk `4096 bytes`，`841.578ms`
  - server metrics latest：`bytes_sent=656616`，`chunks_sent=11`，`first_chunk_latency_ms=98.18`，`duration_ms=3487.916`，`rss_peak_bytes=63225856`，`cpu_time_seconds=0.21`，`closed_by_client=True`，`runtime_scope=global`

## Phase 1.8 Final Validation

- `python3 -m py_compile services/media/streaming.py routes/videos.py routes/files.py routes/file_sections/share_preview_routes.py scripts/testing/playwright_browser_video_compat.py scripts/testing/realtime_proxy_stress_probe.py scripts/testing/realtime_proxy_http_concurrency_probe.py tests/video/streaming/test_video_streaming.py tests/storage/test_cloud_drive_attachments.py tests/frontend/video/test_frontend_videos.py tests/frontend/storage/test_frontend_drive_preview.py`
- `node --check public/js/39-videos.js public/js/shared-video.js public/js/shared-file.js public/js/35-drive.js`
- `pytest -q tests/video/streaming/test_video_streaming.py`
  - 60 tests passed
- `pytest -q tests/frontend/video/test_frontend_videos.py tests/frontend/storage/test_frontend_drive_preview.py tests/storage/test_cloud_drive_attachments.py -k "realtime_proxy_routes or server_encrypted_mkv_share_preview or service_tier or realtime"`
  - 2 tests passed
- `pytest -q tests/video/streaming/test_video_streaming.py tests/frontend/video/test_frontend_videos.py tests/frontend/storage/test_frontend_drive_preview.py`
  - passed
- `git diff --check`
  - passed

## Phase 1.9 Gunicorn Multi-Worker Probe

把 live HTTP concurrency probe 擴充成可用 `--server-runner gunicorn` 啟動 `test_for_develop.sh --in-place --tmp-runtime`，直接用 2 個 gunicorn worker 驗 host-global slot，不只驗 Flask dev-server thread。

新增 probe 參數：

- `--server-runner flask|gunicorn`
- `--gunicorn-workers`
- `--gunicorn-threads`
- `--gunicorn-timeout`

本次實測：

- `python3 scripts/testing/realtime_proxy_http_concurrency_probe.py --runtime-root /tmp/hackme_web_realtime_proxy_gunicorn_phase19 --server-runner gunicorn --gunicorn-workers 2 --gunicorn-threads 1 --max-concurrent 1`
  - `OK: True`
  - artifact: `/tmp/hackme_web_realtime_proxy_gunicorn_phase19/runtime/reports/qa/realtime_proxy_http_concurrency_probe.md`
  - runner：`gunicorn`
  - workers / threads：`2 / 1`
  - HTTP checks：`held_standard_200=True`，`busy_standard_429=True`，`basic_direct_ok=True`，`premium_hls_ok=True`
  - server metrics checks：`present=True`，`finished=True`，`bytes_sent=True`，`rss_peak_bytes=True`，`cpu_time_seconds=True`，`closed_by_client=True`，`host_global_scope=True`
  - held Standard：`200 video/mp4`，header `136.596ms`
  - busy Standard：`429 realtime_proxy_busy`，header `32.455ms`
  - busy response status：`scope=global`，`global_active=1`，`global_free=0`，`local_active=0`
  - Basic direct：`200`，first chunk `4096 bytes`，`55.201ms`
  - Premium HLS segment：`200`，first chunk `4096 bytes`，`21.771ms`
  - server metrics latest：`bytes_sent=197864`，`chunks_sent=4`，`first_chunk_latency_ms=49.447`，`duration_ms=223.927`，`rss_peak_bytes=63275008`，`cpu_time_seconds=0.2`，`closed_by_client=True`，`runtime_scope=global`

結論：

- 兩個 gunicorn workers 共用同一組 runtime lock dir。
- 第二條 Standard request 在另一個 worker 上也會看到 `global_active=1/global_free=0`，因此回 `429 realtime_proxy_busy`。
- Basic direct 與 Premium HLS 在 Standard busy 時仍能快速回 first chunk，符合服務層隔離目標。

## 下一步

- 依 metrics 累積結果做 Standard service sizing：預設 max concurrent、per-stream RSS/CPU 上限、busy fallback UI 文案。
- 下一階段可做 Premium HLS queue / prepared derivative 成本控管，避免多客戶同時選 Premium 時轉檔 worker 形成新的資源尖峰。
