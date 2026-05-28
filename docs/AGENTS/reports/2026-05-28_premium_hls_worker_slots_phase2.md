# Premium HLS Worker Slots Phase 2

日期：2026-05-28

## 目標

Standard realtime proxy 已有 host-global slot 與 gunicorn multi-worker 驗證後，下一個資源尖峰會轉到 Premium prepared HLS。這次把 HLS worker 從單一大型檔案 lock 改成可配置的 host-global slot pool，並把排隊 / 取得 slot 狀態寫回 Job Center。

## 完成項目

- `scripts/media/hls_prepare_worker.py` 新增 Premium HLS slot pool：
  - `HACKME_MEDIA_HLS_MAX_CONCURRENT`：同機大型 HLS worker slot 數，預設 `1`。
  - `HACKME_MEDIA_HLS_LOCK_DIR`：指定 host-global lock 目錄。
  - `HACKME_MEDIA_HLS_SERIALIZE_ALL=1`：所有 HLS 工作都進 slot pool。
  - `HACKME_MEDIA_HLS_SERIALIZE_MIN_BYTES`：只限制大檔的門檻，保留既有小檔 bypass 策略。
- Worker 等待資源時更新 Job Center：
  - stage：`waiting_worker_slot`
  - detail：顯示目前 `active/limit`。
  - metadata：`service_tier=premium_hls`、`worker_slot.scope/active/limit/free/lock_dir`。
- 取得資源後更新：
  - stage：`worker_slot_acquired`
  - result metadata：成功結果包含 `worker_slot`，方便事後估算 Premium queue 成本與容量。

## 驗證

- `python3 -m py_compile scripts/media/hls_prepare_worker.py scripts/testing/hls_worker_slot_probe.py scripts/testing/hls_premium_sizing_probe.py tests/video/streaming/test_video_streaming.py`
- `pytest -q tests/video/streaming/test_video_streaming.py -k "hls_prepare_worker_updates_job_center_until_ready or configurable_global_slot_pool or serializes_only_large_jobs"`
  - 3 tests passed
- `pytest -q tests/video/streaming/test_video_streaming.py`
  - 61 tests passed
- `pytest -q tests/frontend/video/test_frontend_videos.py tests/frontend/storage/test_frontend_drive_preview.py tests/storage/test_cloud_drive_attachments.py -k "realtime_proxy_routes or server_encrypted_mkv_share_preview or service_tier or realtime or prepare_stream"`
  - 2 tests passed
- `python3 scripts/testing/hls_worker_slot_probe.py --runtime-root /tmp/hackme_web_hls_worker_slot_phase3 --duration 3 --hold-seconds 4`
  - OK: True
- `python3 scripts/testing/hls_premium_sizing_probe.py --runtime-root /tmp/hackme_web_hls_premium_sizing_phase4_heavy --jobs 2 --max-concurrent 1 --duration 12 --fixture-size 1280x720 --video-bitrate 4M --hls-quality-heights 480,720 --worker-timeout 240`
  - OK: True
- `python3 scripts/testing/hls_premium_sizing_probe.py --runtime-root /tmp/hackme_web_hls_premium_sizing_phase4_scarlet20 --jobs 1 --max-concurrent 1 --source-video /mnt/d/Scarlet.2025.1080p.NF.WEB-DL.DUAL.DDP5.1.H.264.MSubs-ToonsHub.mkv --source-trim-seconds 20 --hls-quality-heights 480,720 --worker-timeout 300`
  - OK: True
- `python3 scripts/testing/hls_premium_sizing_probe.py --runtime-root /tmp/hackme_web_hls_premium_phase5_scarlet60_c2 --jobs 2 --max-concurrent 2 --source-video /mnt/d/Scarlet.2025.1080p.NF.WEB-DL.DUAL.DDP5.1.H.264.MSubs-ToonsHub.mkv --source-trim-seconds 60 --hls-quality-heights 480,720 --worker-timeout 600`
  - OK: True
- `python3 scripts/testing/hls_premium_sizing_probe.py --runtime-root /tmp/hackme_web_hls_premium_phase5_scarlet180_c2 --jobs 2 --max-concurrent 2 --source-video /mnt/d/Scarlet.2025.1080p.NF.WEB-DL.DUAL.DDP5.1.H.264.MSubs-ToonsHub.mkv --source-trim-seconds 180 --hls-quality-heights 480,720 --worker-timeout 900`
  - OK: True
- `python3 scripts/testing/hls_premium_sizing_probe.py --runtime-root /tmp/hackme_web_hls_premium_phase5_scarlet60_jobs3_c2 --jobs 3 --max-concurrent 2 --source-video /mnt/d/Scarlet.2025.1080p.NF.WEB-DL.DUAL.DDP5.1.H.264.MSubs-ToonsHub.mkv --source-trim-seconds 60 --hls-quality-heights 480,720 --worker-timeout 900`
  - OK: True
- `python3 scripts/testing/hls_premium_sizing_probe.py --runtime-root /tmp/hackme_web_hls_premium_phase5_queue_check --jobs 3 --max-concurrent 2 --duration 3 --fixture-size 320x180 --hold-seconds 2 --hls-quality-heights 480 --worker-timeout 180`
  - OK: True
- `pytest -q tests/video/streaming/test_video_streaming.py -k "storage_saver or original_variant_skip or hides_quality_derivative_larger_than_original or builds_hls_derivatives_for_plain_video"`
  - 4 tests passed
- `python3 scripts/testing/hls_premium_sizing_probe.py --runtime-root /tmp/hackme_web_hls_premium_phase6_scarlet60_no_original --jobs 1 --max-concurrent 1 --source-video /mnt/d/Scarlet.2025.1080p.NF.WEB-DL.DUAL.DDP5.1.H.264.MSubs-ToonsHub.mkv --source-trim-seconds 60 --hls-quality-heights 480,720 --hls-original-variant-mode never --worker-timeout 600`
  - OK: True
- `python3 scripts/testing/hls_premium_sizing_probe.py --runtime-root /tmp/hackme_web_hls_premium_phase6_scarlet60_c2_no_original --jobs 2 --max-concurrent 2 --source-video /mnt/d/Scarlet.2025.1080p.NF.WEB-DL.DUAL.DDP5.1.H.264.MSubs-ToonsHub.mkv --source-trim-seconds 60 --hls-quality-heights 480,720 --hls-original-variant-mode never --worker-timeout 600`
  - OK: True
- `pytest -q tests/video/streaming/test_video_streaming.py -k "mobile_saver or configured_audio_bitrate or storage_saver or original_variant_skip"`
  - 4 tests passed
- `python3 scripts/testing/hls_premium_sizing_probe.py --runtime-root /tmp/hackme_web_hls_premium_phase7_scarlet60_mobile --jobs 1 --max-concurrent 1 --source-video /mnt/d/Scarlet.2025.1080p.NF.WEB-DL.DUAL.DDP5.1.H.264.MSubs-ToonsHub.mkv --source-trim-seconds 60 --hls-profile mobile_saver --hls-quality-heights 480 --worker-timeout 600`
  - OK: True
- `python3 scripts/testing/hls_premium_sizing_probe.py --runtime-root /tmp/hackme_web_hls_premium_phase7_scarlet60_mobile_c2 --jobs 2 --max-concurrent 2 --source-video /mnt/d/Scarlet.2025.1080p.NF.WEB-DL.DUAL.DDP5.1.H.264.MSubs-ToonsHub.mkv --source-trim-seconds 60 --hls-profile mobile_saver --hls-quality-heights 480 --worker-timeout 600`
  - OK: True
- `pytest -q tests/video/streaming/test_video_streaming.py -k "preserves_multi_audio_and_many_subtitles or storage_saver or mobile_saver or configured_audio_bitrate"`
  - 4 tests passed
- `python3 scripts/testing/hls_premium_profile_matrix_probe.py --runtime-root /tmp/hackme_web_hls_profile_matrix_quick --jobs 1 --max-concurrent 1 --duration 3 --fixture-size 320x180 --worker-timeout 180`
  - OK: True
- `python3 scripts/testing/hls_premium_profile_matrix_probe.py --runtime-root /tmp/hackme_web_hls_profile_matrix_scarlet20 --jobs 1 --max-concurrent 1 --source-video /mnt/d/Scarlet.2025.1080p.NF.WEB-DL.DUAL.DDP5.1.H.264.MSubs-ToonsHub.mkv --source-trim-seconds 20 --worker-timeout 300`
  - OK: True
- `node --check public/js/39-videos.js`
- `node --check public/js/shared-video.js`
- `node --check public/js/shared-file.js`
- `node --check public/js/35-drive.js`
- `git diff --check`

新增測試覆蓋：

- 2-slot pool 可同時取得 slot 0/1，第三個 worker 會看到 `active=2/free=0`。
- 釋放 slot 0 後可重新取得 slot 0。
- 真正的 `hls_prepare_worker.main()` 在 `HACKME_MEDIA_HLS_SERIALIZE_ALL=1` 時會把 `premium_hls` 與 `worker_slot.scope=global` 寫入 Job Center metadata/result。
- 既有大檔門檻策略仍維持：小檔預設不序列化，大檔預設序列化，`SERIALIZE_MIN_BYTES=0` 可關閉，`SERIALIZE_ALL=1` 可強制全部進 slot。

## Phase 3 Live Dual-Worker Probe

新增 `scripts/testing/hls_worker_slot_probe.py`，用真實外部 worker 驗證 Premium HLS queue 行為：

- 建立隔離 DB / storage。
- 產生兩個多音軌 MKV fixture。
- 啟動第一個 `hls_prepare_worker.py`，讓它取得 host-global slot。
- 啟動第二個 `hls_prepare_worker.py`，確認它進入 `waiting_worker_slot`。
- 第一個 worker 完成並釋放 slot 後，第二個 worker 應進入 `worker_slot_acquired` / `worker_slot_hold` / `transcoding`，最後 `succeeded`。

為了讓 probe 可重現，worker 增加 QA 用環境變數：

- `HACKME_MEDIA_HLS_DEBUG_HOLD_SLOT_SECONDS`
  - 預設 `0`，正式環境不會延遲。
  - probe 設為 `4`，讓第一個 worker 穩定持有 slot，第二個 worker 必定能被觀察到排隊。

本次實測：

- `python3 scripts/testing/hls_worker_slot_probe.py --runtime-root /tmp/hackme_web_hls_worker_slot_phase3 --duration 3 --hold-seconds 4`
  - `OK: True`
  - artifact: `/tmp/hackme_web_hls_worker_slot_phase3/reports/qa/hls_worker_slot_probe.md`
  - checks：
    - `first_worker_succeeded=True`
    - `second_worker_succeeded=True`
    - `first_acquired_global_slot=True`
    - `second_waited_for_slot=True`
    - `second_acquired_after_wait=True`
    - `second_result_has_slot=True`
    - `slot_limit_one=True`
  - second waiting sample：`stage=waiting_worker_slot`，`worker_slot.scope=global`，`active=1`，`limit=1`，`free=0`
  - second acquired sample：`stage=worker_slot_hold`，`slot_index=0`，`wait_ms=4517.933`
  - second final：`status=succeeded`，`stage=ready`，result 帶 `worker_slot.scope=global`

Phase 3 完成後，下一段工作已推進到 Premium sizing。

## Phase 4 Premium Sizing

新增 `scripts/testing/hls_premium_sizing_probe.py`：

- 可用合成多音軌 MKV 或指定真實來源影片。
- 可對真實來源先用 `-c copy` 切短樣本，避免整部 4.9GB 影片進入測試。
- 啟動真實 `hls_prepare_worker.py`，並抽樣 worker/ffmpeg CPU、RSS、threads。
- 聚合 Job Center result 的 `worker_slot`、`worker_metrics`、HLS 衍生檔大小與 DB variant/subtitle metadata。
- 產出保守 `HACKME_MEDIA_HLS_MAX_CONCURRENT` 建議。

Worker result 也新增 `worker_metrics`：

- `wall_ms`
- `self_cpu_seconds`
- `child_cpu_seconds`
- `total_cpu_seconds`
- `self_max_rss_kb`
- `child_max_rss_kb`

較重合成樣本實測：

- source：12s、1280x720、4Mbps、雙音軌/字幕 fixture
- HLS：480p + 720p
- workers：2
- slot：1
- OK：True
- resource：
  - CPU peak：49.2%
  - RSS peak：191.29MB
  - ffmpeg peak：1 process
  - HLS worker peak：2 processes
- derivative：
  - source：6,484,703 bytes
  - derivatives total：17,090,260 bytes
  - multiplier：2.635x
- conservative suggestion：`HACKME_MEDIA_HLS_MAX_CONCURRENT=4`

Scarlet 真實影片 20 秒樣本實測：

- source：`/mnt/d/Scarlet.2025.1080p.NF.WEB-DL.DUAL.DDP5.1.H.264.MSubs-ToonsHub.mkv`
- trim：20s
- source sample：12,691,386 bytes
- HLS：original + 480p + 720p，多字幕抽出
- OK：True
- resource：
  - CPU peak：344.0%
  - CPU avg：97.28%
  - RSS peak：231.9MB
  - max per-process RSS：171.54MB
  - ffmpeg peak：1 process
- worker result：
  - wall：5050.573ms
  - child CPU：8.9745s
  - child RSS peak：177736KB
  - slot wait：0.366ms
- derivative：
  - bytes：21,433,314
  - files：64
  - suffixes：6 m3u8、30 m4s、5 mp4、23 vtt
  - multiplier：1.689x
- conservative suggestion：`HACKME_MEDIA_HLS_MAX_CONCURRENT=2`

結論：

- 先保留 production default `HACKME_MEDIA_HLS_MAX_CONCURRENT=1`。
- 若部署機器與本機相近，Scarlet 類型影片可把 Premium HLS worker slot 提到 `2`，但應搭配監控 CPU peak、queue wait 與 derivative storage growth。
- 不建議直接採用合成樣本的 `4`，因為它沒有 Scarlet 類 DDP5.1/多字幕/1080p downscale 壓力。

## Phase 5 Premium Concurrency Calibration

目的：把 Phase 4 的 `HACKME_MEDIA_HLS_MAX_CONCURRENT=2` 建議拿真實 Scarlet 片段驗證，確認不是 20s 小樣本偏樂觀。

Probe 補強：

- `scripts/testing/hls_premium_sizing_probe.py` 新增 `queue_summary`。
- 當 `jobs > max_concurrent` 時，新增 check：`expected_queue_observed`。
- Markdown report 會列出 expected queue、waited workers、max wait ms。

Scarlet 60s，`jobs=2 / max=2`：

- OK：True
- source sample：46,118,707 bytes
- CPU peak：602.3%
- CPU avg：352.72%
- RSS peak：439.93MB
- ffmpeg peak：2 processes
- worker peak：2 processes
- derivative total：134,538,194 bytes
- derivative multiplier：2.917x
- per-slot CPU peak：約 301.15%
- per-slot RSS：約 219.97MB
- suggested：`HACKME_MEDIA_HLS_MAX_CONCURRENT=2`
- worker wall：兩個 worker 皆約 18.4s
- slot wait：兩個 worker 皆低於 1ms

Scarlet 180s，`jobs=2 / max=2`：

- OK：True
- source sample：130,046,009 bytes
- CPU peak：628.0%
- CPU avg：430.53%
- RSS peak：444.11MB
- ffmpeg peak：2 processes
- worker peak：2 processes
- derivative total：390,228,216 bytes
- derivative multiplier：3.001x
- per-slot CPU peak：約 314.0%
- per-slot RSS：約 222.06MB
- suggested：`HACKME_MEDIA_HLS_MAX_CONCURRENT=2`
- worker wall：兩個 worker 皆約 55s
- slot wait：兩個 worker 皆低於 1ms

Scarlet 60s queue，`jobs=3 / max=2`：

- OK：True
- ffmpeg peak：2 processes
- worker peak：3 processes
- CPU peak：568.0%
- RSS peak：470.25MB
- 第三個工作成功排隊，max observed wait：19,109.012ms
- 結論：host-global slot cap 有效，第三個 Premium job 不會讓 ffmpeg 併發超過 2。

短 fixture queue check，`jobs=3 / max=2 / hold=2s`：

- OK：True
- `expected_queue_observed=True`
- waited workers：1
- max wait：2542.281ms
- ffmpeg peak：2 processes

Phase 5 結論：

- 本機 12-core 環境下，Scarlet 類 DDP5.1 / 多字幕 / 1080p downscale 影片可把 Premium HLS slot 從 `1` 調到 `2`。
- 不建議調到 `3`：以 180s 樣本 per-slot CPU peak 約 314% 推估，3 slots 可能接近或超過保守 CPU budget，且會放大磁碟 IO 與 derivative storage growth。
- 服務費策略維持：Premium 高費率的理由不只是播放體驗，也包含 queue 管理、背景 CPU、RSS、字幕/音軌衍生檔、儲存與清理成本。

## Phase 6 Premium Storage Policy

目的：Phase 5 已確認 CPU/RSS 與 slot cap 可控，下一個成本是衍生檔儲存。Scarlet 180s baseline 的 derivative multiplier 約 `3.001x`，主因之一是同時保留 `original` HLS variant、q480/q720、音軌與字幕。

新增設定：

- `HACKME_MEDIA_HLS_ORIGINAL_VARIANT_MODE`
  - `always`：預設，保留原有行為，輸出 original + quality ladder。
  - `never` / `storage_saver`：有降階畫質時跳過 original HLS variant。
  - `auto`：目前等同「有降階畫質就不輸出 original，沒有降階畫質才保留 original」。
- `HACKME_MEDIA_HLS_INCLUDE_ORIGINAL=0`：相容布林開關，等同 `never`。

安全規則：

- 若沒有任何可用降階畫質，即使設定 `never` 也會保留 `original`，避免 Premium HLS 沒有可播放 variant。
- 若跳過 original，後續 quality variant 會以原始檔大小作為「衍生檔過大」的比較基準；第一個可播放 variant 不會被刪到空集合。
- Playback payload 的 `quality_policy` 新增：
  - `original_variant_mode`
  - `original_variant_present`

Scarlet 60s storage-saver，`jobs=1 / max=1 / original=never`：

- OK：True
- source sample：46,118,707 bytes
- derivatives：30,771,285 bytes
- derivative multiplier：0.667x
- files：96
- variants：q480、q720
- suffixes：5 m3u8、64 m4s、4 mp4、23 vtt
- CPU peak：310.4%
- RSS peak：235.53MB
- worker wall：13.5s
- suggested：`HACKME_MEDIA_HLS_MAX_CONCURRENT=2`

Scarlet 60s storage-saver，`jobs=2 / max=2 / original=never`：

- OK：True
- derivative total：61,542,570 bytes
- derivative multiplier：1.334x
- baseline Phase 5 `jobs=2 / max=2 / original=always`：134,538,194 bytes，2.917x
- storage reduction：約 54.3%
- ffmpeg peak：2 processes
- RSS peak：440.25MB
- CPU peak：776.5%
- worker wall：兩個 worker 皆約 17.5s
- variants：q480、q720，無 original

Phase 6 結論：

- 對 Scarlet 類多字幕、多音軌長片，Premium 可提供「高相容 / 含原畫質」與「省儲存 / 不含 original HLS variant」兩種營運模式。
- 預設仍維持 `always`，避免改變既有客戶期待。
- 若客戶重視服務費與儲存成本，可對 Premium storage-saver 開 `HACKME_MEDIA_HLS_ORIGINAL_VARIANT_MODE=never`，仍保留 q480/q720、多音軌、多字幕與分享授權。

## Phase 7 Premium Profiles

Phase 6 後拆分 Scarlet 60s storage-saver derivative：

- q720：約 18.398MB
- q480：約 9.187MB
- audio_01_jpn：約 0.882MB
- audio_02_eng：約 0.878MB
- subtitles：約 0.0002MB

結論：audio 壓縮只會帶來小幅收益，真正高收益是控制 quality ladder。因此新增 Premium profile，而不是只做 audio bitrate。

新增設定：

- `HACKME_MEDIA_HLS_PROFILE`
  - `full`：預設，保留既有行為。
  - `storage_saver`：預設跳過 original HLS rendition，quality ladder 仍可用 q480/q720。
  - `mobile_saver`：預設跳過 original，預設 quality ladder 為 q480，HLS audio 預設 128k。
- `HACKME_MEDIA_HLS_AUDIO_BITRATE`
  - 覆蓋 HLS audio rendition bitrate，例如 `96k`、`128k`、`160k`。
- `scripts/testing/hls_premium_sizing_probe.py`
  - 新增 `--hls-profile`
  - 新增 `--hls-audio-bitrate`

Scarlet 60s，`mobile_saver / jobs=1 / max=1`：

- OK：True
- source sample：46,118,707 bytes
- derivatives：11,119,931 bytes
- derivative multiplier：0.241x
- variants：q480 only
- audio：兩條 128k AAC，合計約 1.42MB
- subtitles：23 VTT
- CPU peak：323.5%
- RSS peak：223.8MB
- worker wall：約 6.5s
- suggested：`HACKME_MEDIA_HLS_MAX_CONCURRENT=2`

Scarlet 60s，`mobile_saver / jobs=2 / max=2`：

- OK：True
- derivative total：22,239,862 bytes
- derivative multiplier：0.482x
- baseline `full / jobs=2 / max=2`：134,538,194 bytes，2.917x
- 相對 full baseline storage reduction：約 83.5%
- 相對 storage-saver q480/q720 baseline：61,542,570 bytes，1.334x，約 63.9% reduction
- ffmpeg peak：2 processes
- CPU peak：601.3%
- RSS peak：414.29MB
- worker wall：兩個 worker 皆約 7.5s

Phase 7 結論：

- Premium 可以明確拆成三個營運 profile：
  - `full`：最高相容與畫質，最高衍生檔成本。
  - `storage_saver`：保留 q480/q720，多數客戶仍有 720p，儲存降約 54%。
  - `mobile_saver`：只保留 q480，多音軌與字幕仍在，儲存降約 83.5%，適合低費率 Premium 或手機觀看客戶。
- 目前不建議把 audio bitrate 當主要優化槓桿；它應是 profile 的輔助設定。

## Phase 8 Premium Profile Payload

目的：Phase 7 的 profile 不能只存在於環境變數，前端與客服 API 也需要能讀到「目前 profile、可選 profile、費率相對差異、成本理由」。

新增 payload：

- `service_policy.premium_hls_profile_policy`
- `streaming_options[].profile_policy`，位於 `mode=prepared_hls`

Payload 內容：

- `current_profile`
- `quality_heights`
- `audio_bitrate`
- `original_variant_mode`
- `original_variant_present`
- `profiles`
  - `full`
  - `storage_saver`
  - `mobile_saver`
- 每個 profile 會列：
  - `relative_fee`
  - `quality_heights`
  - `includes_original_variant`
  - `audio_bitrate`
  - `storage_cost`
  - `best_for`
  - `tradeoffs`

這讓客戶說明可直接從播放 API 取得，不必把 full/storage_saver/mobile_saver 的差異寫死在前端。

## Phase 9 Premium Profile Matrix Probe

目的：Phase 7/8 讓 profile 可配置、可被 payload 描述，但成本比較仍是人工跑多組 sizing probe。新增 matrix probe，把同一個 source fixture 套到多個 Premium profile，產出公平比較表。

新增：

- `scripts/testing/hls_premium_profile_matrix_probe.py`

特性：

- 只切一次 source fixture。
- 依序跑：
  - `full`
  - `storage_saver`
  - `mobile_saver`
- 每個 profile 內部呼叫 `hls_premium_sizing_probe.py`。
- 最終輸出：
  - derivative bytes / multiplier
  - storage reduction vs full
  - CPU peak / avg
  - RSS peak
  - worker wall time
  - variants
  - fastest profile
  - smallest storage profile

Scarlet 20s matrix：

- source sample：12,691,386 bytes
- `full`
  - derivatives：21,433,314 bytes
  - multiplier：1.689x
  - variants：original、q480、q720
  - CPU peak：324.0%
  - RSS peak：201.18MB
  - avg wall：5081.767ms
- `storage_saver`
  - derivatives：11,954,711 bytes
  - multiplier：0.942x
  - storage reduction vs full：44.22%
  - variants：q480、q720
  - CPU peak：276.0%
  - RSS peak：201.29MB
  - avg wall：5031.431ms
- `mobile_saver`
  - derivatives：4,319,913 bytes
  - multiplier：0.340x
  - storage reduction vs full：79.84%
  - variants：q480
  - CPU peak：281.0%
  - RSS peak：188.88MB
  - avg wall：2972.979ms

Phase 9 結論：

- `hls_premium_profile_matrix_probe.py` 取代人工三跑整理，之後可直接給客服 / PM / infra 做費率與容量決策。
- Scarlet 20s 與 60s 結論一致：`mobile_saver` 是最低儲存與最快完成，`storage_saver` 是保留 720p 的中間方案，`full` 是最高相容與原畫質方案。

## Phase 10 Premium Asset/Profile Drift Detection

目的：Phase 8/9 已能說明「目前 Premium profile」與成本差異，但舊影片的 HLS 衍生檔可能是在 profile 切換前產生。客服、前端與營運不能只看目前環境變數，需要知道這支影片的實際 HLS asset profile 是否與現行 profile policy 一致。

新增 payload 欄位：

- `service_policy.premium_hls_profile_policy`
  - `version`
  - `requested_profile`
  - `asset_status`
  - `asset_profile`
  - `asset_profile_candidates`
  - `asset_profile_confidence`
  - `asset_profile_ambiguous`
  - `asset_variant_names`
  - `asset_quality_heights`
  - `asset_audio_bitrate`
  - `profile_matches_asset`
  - `profile_drift`
  - `rebuild_recommended`
  - `rebuild_reason`
- prepared-HLS `quality_policy`
  - 同步 exposes `asset_profile` / `profile_drift` / `rebuild_recommended`
  - 讓一般影音、分享影音、Cloud Drive preview、storage share preview 都能從播放 payload 判斷是否需要重建 HLS。

推斷規則：

- 有 `original` HLS rendition：推斷為 `full`。
- 無 original 且有 q480/q720：推斷為 `storage_saver`。
- 無 original 且只有 q480：
  - 外部 HLS audio bitrate <= 128k：推斷為 `mobile_saver`。
  - 無外部 audio track 時標記為 ambiguous，候選為 `storage_saver` / `mobile_saver`，避免 720p source 因沒有 q720 衍生檔而被誤判為 drift。
- 其他 ladder：推斷為 `custom`。

驗證：

- `python3 -m py_compile services/media/streaming.py routes/files.py routes/file_sections/share_preview_routes.py routes/videos.py tests/video/streaming/test_video_streaming.py`
- `pytest -q tests/video/streaming/test_video_streaming.py -k "profile_policy or storage_saver or mobile_saver or configured_audio_bitrate or preserves_multi_audio"`
- `pytest -q tests/video/streaming/test_video_streaming.py`
- `node --check public/js/39-videos.js public/js/shared-video.js public/js/shared-file.js public/js/35-drive.js`
- `pytest -q tests/frontend/storage/test_frontend_drive_preview.py tests/frontend/video/test_frontend_videos.py tests/storage/test_cloud_drive_attachments.py`
- `pytest -q tests/platform/test_release_policy.py tests/scripts/prepush/test_prepush_v2.py`
- `git diff --check`

Phase 10 結論：

- 客戶可選三種 Premium 費率，但 payload 現在同時說明「目前選用方案」與「此影片實際已產生的方案」。
- profile policy 改動後，不需要同步掃全站；讀 playback payload 就能標記個別資產是否建議排程重建 HLS。

## Phase 11 Storage / Video Sendfile Offload

目的：影音、雲端硬碟、分享下載的下一個負載瓶頸不是轉檔，而是長時間下載把 Flask worker 佔住。新增可選 Nginx `X-Accel-Redirect` offload，讓不需要 Python 轉換 payload 的檔案交給 web server 送。

新增：

- `services/core/file_offload.py`
- `HACKME_CLOUD_DRIVE_X_ACCEL_PREFIX`
- `HACKME_CLOUD_DRIVE_X_ACCEL_STORAGE_ROOT`
- 相容 alias：
  - `HACKME_X_ACCEL_STORAGE_PREFIX`
  - `HACKME_X_ACCEL_STORAGE_ROOT`

套用路徑：

- Cloud Drive plain download / preview content
- Storage share download / preview content
- E2EE ciphertext delivery
- Normal/shared video direct stream
- Cloud Drive / video / share HLS playlist, segment, subtitle static delivery

保護：

- `server_encrypted` 檔案不走 X-Accel，仍使用 range-aware chunked decrypt streaming。
- realtime proxy、字幕 shift、share-session manifest rewrite、server-side decrypt 仍留在 Python，因為這些需要動態處理或授權改寫。

驗證：

- `python3 -m py_compile services/core/file_offload.py routes/files.py routes/videos.py routes/file_sections/share_preview_routes.py tests/storage/test_cloud_drive_attachments.py`
- `pytest -q tests/storage/test_cloud_drive_attachments.py -k "x_accel or server_encrypted_upload_always_uses_chunked_encryption or server_encrypted_media_preview_content_supports_range_requests or storage_share_link_download_and_revoke or storage_upload_creates_logical_file"`
- `pytest -q tests/video/streaming/test_video_streaming.py -k "hls_segment or video_playback_and_hls_routes_use_ready_stream_asset or shared_standard_video_playback_uses_shared_hls_and_stream_urls"`

Phase 11 結論：

- 有 Nginx 時，長下載與 HLS 靜態片段可以從 Flask worker 移走。
- 沒設定 env 時維持原本 `send_file` 行為，不影響開發環境。

## Phase 12 Storage Upload / Transfer Path Bounded Load

目的：把上一階段的下載 offload 補成完整的上傳/下載可觀測與 bounded 行為，避免大檔 upload/download/preview 把 Flask worker 或 Python heap 撐爆。

新增：

- `X-Hackme-Transfer-Mode` / `X-Hackme-Transfer-Offload`：
  - `x_accel`
  - `python_send_file`
  - `python_buffered_bytes`
  - `python_throttled_stream`
  - `python_chunked_decrypt`
  - `python_e2ee_chunk`
  - `python_realtime_proxy`
- Cloud Drive resumable upload chunk 改為 bounded read -> `.part.tmp` -> atomic replace。
- chunk upload response 回傳 `chunk.storage_mode=streamed_to_disk`。
- `HACKME_CLOUD_DRIVE_UPLOAD_SLEEP_SHAPER=1` 才啟用舊的 app-side upload sleep shaping；預設只做停用上傳的硬拒絕，不讓 worker sleep。

套用路徑：

- Cloud Drive plain/E2EE download and preview ciphertext delivery.
- Cloud Drive server-encrypted preview/download retains range-aware chunked decrypt streaming.
- Normal/shared video bytes and E2EE chunk responses now expose transfer mode.
- Normal video, Cloud Drive, and storage-share realtime proxy responses now
  expose `python_realtime_proxy` so Standard tier streams do not get grouped
  with X-Accel/sendfile downloads in stress reports.
- Resumable upload chunks no longer materialize full chunk bytes in Python.

驗證：

- `python3 -m py_compile services/core/file_offload.py routes/files.py routes/videos.py routes/file_sections/share_preview_routes.py services/media/streaming.py services/platform/release_info.py tests/storage/test_cloud_drive_attachments.py tests/video/streaming/test_video_streaming.py`
- `pytest -q tests/storage/test_cloud_drive_attachments.py -k "resumable or x_accel or server_encrypted_download_ignores_x_accel or e2ee_preview_ciphertext_can_use_x_accel or server_encrypted_media_preview_content_supports_range_requests"`
- `pytest -q tests/storage/test_cloud_drive_attachments.py -k "realtime_proxy_routes or x_accel or resumable or server_encrypted_media_preview_content_supports_range_requests"`
- `pytest -q tests/video/streaming/test_video_streaming.py -k "video_realtime_proxy_route_streams or shared_standard_video_playback_uses_shared_hls_and_stream_urls or realtime_proxy_route_writes_server_metrics_jsonl"`
- `pytest -q tests/storage/test_cloud_drive_attachments.py`
- `pytest -q tests/video/streaming/test_video_streaming.py`
- `pytest -q tests/platform/test_release_policy.py tests/scripts/prepush/test_prepush_v2.py`
- `node --check public/js/35-drive.js`
- `node --check public/js/shared-file.js`
- `node --check public/js/39-videos.js`
- `node --check public/js/shared-video.js`
- `git diff --check`
- `pgrep -af "hls_prepare_worker.py|hls_premium_sizing_probe.py|hls_worker_slot_probe.py|hls_premium_profile_matrix_probe.py"` returned no matching process.

Phase 12 結論：

- 大檔下載/分享/HLS 靜態檔可由 Nginx 接手。
- E2EE 密文可以 offload；server-encrypted 明文永遠不交給 web server。
- 大檔上傳建議走 resumable，主程序只做 bounded chunk 寫入與 session 狀態更新。
- legacy non-chunked `server_encrypted` 檔案仍需 full Fernet decrypt 才能讀取；
  這是舊資料格式限制，應用層只能標記/隔離，真正優化是背景 migration 到
  chunked server encryption 或要求走 Premium prepared HLS。
- 本輪 app-local 低風險優化已收斂；剩餘負載治理屬部署或資料治理：
  Nginx internal alias、proxy/CDN upload shaping、legacy encryption migration、
  storage/object-store edge offload、以及 per-tier 服務費/併發額度政策。
