# Video Streaming Service Tiers

這份文件用來對客戶說明影音播放的三種服務路線，以及服務費為什麼不同。
工程實作細節仍以 [VIDEO_STREAMING_ARCHITECTURE.md](VIDEO_STREAMING_ARCHITECTURE.md)
為準。

## 客戶版短說明

同一支影片可以選三種播放服務。差異不是畫面上多一個按鈕而已，而是伺服器
是否要即時處理影片、是否要預先產生串流檔、是否要額外保存多音軌與多字幕
版本。

| 方案 | 費率層級 | 適合對象 | 優點 | 限制 |
|---|---|---|---|---|
| 直接串流 | Basic / 最低 | 小檔案、標準 MP4、單音軌、少量觀看 | 上傳後幾乎可立即播放；不需預處理；服務成本最低 | 取決於瀏覽器原生支援；MKV、E-AC-3、多音軌、多字幕相容性較差；大量觀看時比較難快取與調度 |
| 即時轉封裝 | Standard / 中 | 不想等預處理、但需要處理 MKV 或特殊音軌的影片 | 不必先產生整套衍生檔；可在播放時選音軌並把音訊轉成瀏覽器較好播的格式 | 每位觀看者都會吃即時 CPU；跳轉時間較近似；不適合很多人同時看同一支片 |
| 預處理 HLS | Premium / 最高 | 大檔案、公開影片、多人觀看、多音軌、多字幕、需要穩定分享 | 可快取、可分段、可多畫質；多音軌與多字幕有明確選單；分享影音與 Cloud Drive 分享都能套用授權檢查 | 上傳後需要等待處理；伺服器要付出轉檔 CPU、衍生檔儲存、清理與監控成本 |

## 為什麼服務費不同

直接串流的成本主要是檔案讀取與網路流量。伺服器不主動拆影片、不轉音訊、
不保存額外版本，所以費率最低。但這也代表播放能力完全受原始檔與瀏覽器限制。
例如某些 MKV、E-AC-3 音軌、內嵌字幕或多國語音在不同瀏覽器上的行為不一致。

即時轉封裝的成本來自播放當下的運算。伺服器會用類似低階硬體可承受的策略：
能複製影像就複製影像，只把必要音訊轉成 AAC，再以瀏覽器較好接收的格式送出。
這讓客戶不必等完整預處理，但每一個觀看者都會產生一條即時處理工作，所以
併發越高成本越高，也比較不適合 CDN 或長期快取。

預處理 HLS 的成本最高，因為系統會先分析影片，抽出可用字幕，為多國音軌建立
獨立音訊 playlist，並產生可分段播放的 HLS 影音檔。這會消耗背景 worker CPU、
磁碟空間、資料庫索引、快取失效與清理作業，但換來的是大量觀看時更穩定、
更容易跳轉、也更適合分享頁與公開影音頁。

Premium 的成本不是只發生在「播放」那一刻。上傳或發布後，平台會把 HLS 準備
工作放到外部 worker，並用 host-global file slots 控制同機轉檔併發，避免多位
客戶同時選 Premium 時把 CPU、RSS、磁碟 IO 全部打滿。任務中心會顯示
`waiting_worker_slot`、`worker_slot_acquired`、`transcoding` 等階段，讓客服可以
說明目前是在排隊等轉檔資源，還是在實際處理影片。

## 多音軌 / 多字幕影片的處理原則

多音軌、多字幕影片不能只當成單一影片檔直接丟給瀏覽器。正式服務規則是：

- 直接串流只保證瀏覽器能播放原始檔時可用，不承諾所有音軌和字幕都能被選到。
- 即時轉封裝可讓觀看者選一條音軌，伺服器即時轉成相容音訊輸出；字幕仍以可用
  的外掛字幕或瀏覽器能力為主。
- 預處理 HLS 會建立獨立音訊 tracks 與 WebVTT 字幕 tracks，播放器顯示音軌、
  字幕、畫質選單。
- 分享影音也套用同一套規則；HLS manifest、音軌 playlist、字幕 URL 都必須帶著
  分享授權或分享 session，不能因為音軌或字幕是子資源就繞過權限。
- strict E2EE 影片不走伺服器端轉檔。若要多畫質或分段播放，必須由瀏覽器或受信任
  客戶端本地產生加密衍生檔，再上傳密文 bundle。

## 對客戶的建議話術

如果客戶只要內部少量觀看、影片格式又很標準，可以選直接串流，費率最低。

如果客戶有 MKV 或多國語音影片，想要快速上線又不想先等完整處理，可以選即時
轉封裝；它比直接串流可靠，但成本會跟同時觀看人數一起上升。

如果客戶要對外分享、多人觀看、需要穩定跳轉，或影片有多音軌、多字幕，建議選
預處理 HLS。費率較高是因為平台會先替影片建立可快取、可授權、可分段播放的服務
版本，這部分是額外的運算、儲存與維運成本。

## 目前實作狀態

- 直接串流是既有 fallback 路線。
- 預處理 HLS 已支援多畫質、外掛字幕、內嵌文字字幕抽取、多音軌 HLS playlist，
  並已套用到一般影音、共享影音、Cloud Drive 預覽與儲存分享預覽。
- 前端已在一般影音、分享影音、Cloud Drive 預覽與儲存分享預覽提供
  Basic / Standard / Premium 方案選擇；多音軌影片在 Standard 模式會重新開啟
  即時轉封裝來套用指定音軌。
- 播放 API 會回傳 `service_policy` 和 `streaming_options`，其中包含三種方案的
  `service_tier`、`fee_level`、`billing_basis`、`cost_drivers`、優點、限制、
  適用情境與多音軌 / 多字幕支援等級，前端或客服文件可以直接引用。
- 即時轉封裝是 Standard 服務層的正式產品路線；其低成本策略參考 `lcd_OS` 的
  ffmpeg pipe 做法：影像可 copy 時不重編，必要時只轉音訊。Route 已補上並預設
  由 `HACKME_MEDIA_REALTIME_PROXY_ENABLED=0` 關閉；開放時需搭配
  `HACKME_MEDIA_REALTIME_PROXY_MAX_CONCURRENT`、`HACKME_MEDIA_REALTIME_PROXY_TIMEOUT_SECONDS`
  控制每機併發與程序壽命。若有 `HACKME_RUNTIME_DIR` 或指定
  `HACKME_MEDIA_REALTIME_PROXY_LOCK_DIR`，併發上限會用 host-global file slots
  套到同機多 worker；沒有 runtime context 時才退回單 process 限制。
- Premium HLS worker 對大型工作使用 host-global slot pool，預設
  `HACKME_MEDIA_HLS_MAX_CONCURRENT=1`，可用 `HACKME_MEDIA_HLS_LOCK_DIR` 指定 lock
  目錄；`HACKME_MEDIA_HLS_SERIALIZE_ALL=1` 可讓所有 HLS 工作都進同一組 slot，
  `HACKME_MEDIA_HLS_SERIALIZE_MIN_BYTES` 可調整只限制大檔的門檻。Worker 成功結果
  會寫入 `worker_metrics`，`scripts/testing/hls_premium_sizing_probe.py` 可用合成
  fixture 或真實影片切片測 CPU/RSS/衍生檔倍率，再決定是否把 Premium slot 從 1
  調高。Scarlet 60 秒與 180 秒真實樣本已在本機驗證 `jobs=2 / max=2` 可完成；
  `jobs=3 / max=2` 會讓第三個 Premium job 排隊而不是啟動第三個 ffmpeg。
- Premium 可再細分儲存策略：預設 `HACKME_MEDIA_HLS_ORIGINAL_VARIANT_MODE=always`
  會保留 original HLS rendition，適合高相容 / 原畫質需求；若客戶重視服務費與
  儲存成本，可用 `never` / `storage_saver` 跳過 original rendition，只保留設定的
  q480/q720 等畫質、多音軌與字幕。Scarlet 60 秒樣本在本機從 2.917x 降到 1.334x。
- Premium 也可用 `HACKME_MEDIA_HLS_PROFILE` 包成營運方案：
  `full` 保留最高相容與原畫質；`storage_saver` 保留 q480/q720 但跳過 original；
  `mobile_saver` 預設只保留 q480 並使用 128k HLS audio。Scarlet 60 秒樣本中，
  `mobile_saver` 的 `jobs=2 / max=2` 衍生檔倍率為 0.482x，比 full baseline
  下降約 83.5%，適合低費率 Premium 或主要手機觀看的客戶。
- 播放 API 會在 `service_policy.premium_hls_profile_policy` 與 prepared-HLS
  `streaming_options[].profile_policy` 回傳目前 profile 與可選 profile 的相對費率、
  儲存成本、畫質取捨與適合情境，客服和前端不需要另外硬編這些說明。
- 同一份 payload 也會回傳實際 HLS 資產推斷出的 `asset_profile`、
  `asset_profile_candidates`、`profile_drift` 與 `rebuild_recommended`。若營運
  從 full 改成 mobile_saver，舊影片仍是 full 衍生檔時，客服可直接看到需要排程
  重建，而不是只看目前環境設定。
- 費率或容量重新估算時，使用 `scripts/testing/hls_premium_profile_matrix_probe.py`
  對同一支真實影片切片一次比較 full / storage_saver / mobile_saver，避免用不同
  source sample 手動拼湊出誤導性的成本表。

## Standard 即時轉封裝端點

即時轉封裝端點共用同一套授權檢查：

- 一般影音：`GET /api/videos/<video_id>/realtime-proxy`
- 分享影音：`GET /api/videos/shared/<token>/realtime-proxy`
- Cloud Drive 預覽：`GET /api/cloud-drive/files/<file_id>/realtime-proxy`
- 檔案分享預覽：`GET /api/storage/shared/<token>/realtime-proxy`

查詢參數：

- `audio` / `audio_track` / `track`：可填 `audio_02_eng`、stream index、語言或序號。
- `start`：近似起播秒數，給需要跳轉時使用。

限制：

- strict E2EE 不允許伺服器端即時轉封裝。
- `server_encrypted` 目前仍建議走 Premium HLS，避免每位觀看者觸發主程序解密。
- 達到併發上限時回 `429 realtime_proxy_busy`，客戶端應提示稍後再試或改用 Premium HLS。

## Sendfile / X-Accel Offload

- 未加密檔案、E2EE 密文、direct video stream、HLS playlists / segments /
  subtitles 可選擇交給 Nginx `X-Accel-Redirect` 送檔，降低 Flask worker 被長下載
  佔住的時間。
- 啟用方式：設定 `HACKME_CLOUD_DRIVE_X_ACCEL_PREFIX`，例如
  `/_protected/storage`。Nginx 對應 location 必須是 `internal`，並 alias 到 app
  的 storage root。
- 若 Nginx alias root 與 app `STORAGE_DIR` 不同，再設定
  `HACKME_CLOUD_DRIVE_X_ACCEL_STORAGE_ROOT`。
- server-side encrypted 檔案不會走 X-Accel；它們仍由 app 走 range-aware chunked
  decrypt streaming，避免把明文暴露給 web server offload location。
- 回應會帶 `X-Hackme-Transfer-Mode`，壓測可用它區分 `x_accel`、
  `python_send_file`、`python_buffered_bytes`、`python_chunked_decrypt`、
  `python_e2ee_chunk`、`python_realtime_proxy` 等路徑。

## Upload / Download Load Notes

- Cloud Drive resumable uploads stream chunks to disk with bounded reads; large
  chunk uploads should use resumable mode instead of a single multipart body.
- Upload tier limits still reject disabled upload directions. Legacy app-side
  sleep shaping is opt-in via `HACKME_CLOUD_DRIVE_UPLOAD_SLEEP_SHAPER=1`; normal
  deployments should shape at Nginx/CDN/storage edge so Flask workers are not
  parked during uploads.
- For `server_encrypted` media, Premium prepared HLS remains the scalable
  customer path. Direct preview/download must stay in Python to decrypt chunks
  on demand, so it is intentionally billed/positioned differently from plain
  offloaded delivery.
- Legacy non-chunked `server_encrypted` files cannot be range-streamed without
  decrypting the full Fernet token first. Treat them as migration candidates to
  chunked server encryption or prepared HLS before offering heavy playback.
