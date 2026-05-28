# Scarlet 1080p 多音軌影片三種服務模式壓測

日期：2026-05-27
測試檔案：`/mnt/d/Scarlet.2025.1080p.NF.WEB-DL.DUAL.DDP5.1.H.264.MSubs-ToonsHub.mkv`
測試樣本：從 00:30:00 起取 300 秒，用來避免只測片頭低複雜度畫面。

## 來源媒體

- 檔案大小：5,206,972,407 bytes，約 4.85 GiB。
- 片長：6,677.713 秒，約 1:51:17。
- Container：Matroska/WebM。
- 影片：H.264 1920x1080。
- 音軌：2 條 E-AC-3 5.1，`jpn` 預設、`eng` 第二音軌。
- 字幕：23 條 SubRip，包含 `eng Forced`，另有繁中、簡中與多國語言。

## 結論

三種模式都能在伺服器端處理這支影片，但適用客戶情境不同：

| 模式 | 結論 | 5 分鐘處理時間 | Max RSS | 輸出/衍生檔 | 播放與跳轉 |
| --- | --- | ---: | ---: | ---: | --- |
| Basic 直接串流 | 成本最低，但這支 MKV + E-AC-3 + 多字幕不應保證瀏覽器可播 | 原檔 I/O 1GiB：11.11s；demux copy：3.33s | 18MB / 54MB | 不產生衍生檔 | 取決於瀏覽器原生支援；多音軌/多字幕不可控 |
| Standard 即時轉封裝 | 對本片很有效，因為 video copy、只轉選定音軌 | 4.46s | 60.9MB | 185MB fMP4/5min；實際服務不長期保存 | 10s decode 0.39s；seek decode 0.20s；每位觀看者消耗 CPU |
| Premium 預處理 HLS | 最適合多音軌/多字幕與分享，需背景工作與衍生檔成本 | 專案實作 55.55s | 188.5MB | HLS derivatives 約 338MB/5min | 10s decode 0.40s；120s seek decode 0.15s |

對客戶的費率說法可以維持三階：

- Basic：只收最低服務成本，主要是檔案 I/O 與流量；不保證特殊容器、E-AC-3、多音軌、多字幕體驗。
- Standard：中階費率，伺服器每次觀看開 ffmpeg 即時處理；適合少量觀看、需要快速上線、不想先存衍生檔的客戶。
- Premium：最高費率，平台預先建立 HLS 多畫質、多音軌、多字幕與可分享播放資產；費用差異來自 worker CPU、衍生檔儲存、分段索引、快取與清理。

## 測試結果

### Basic：直接串流

- `direct_io_read_1g`：11.11s，CPU 1%，Max RSS 18,048KB。
- `direct_demux_copy_null_5m`：3.33s，CPU 7%，Max RSS 54,380KB。

伺服器可以快速讀取與 demux，但這個來源不是標準瀏覽器友善格式。直接丟原 MKV 時，瀏覽器是否能播放、是否能選日/英音軌、是否能掛 23 條字幕，都不可保證。

### Standard：即時轉封裝

測試命令等價策略：

- `-map 0:v:0 -map 0:1`
- video `copy`
- audio `aac 160k stereo`
- `-map_metadata -1 -map_chapters -1 -sn -dn`
- fragmented MP4 output

結果：

- clean JPN proxy：4.46s，CPU 75%，Max RSS 60,952KB，輸出 185MB。
- 10 秒 decode：0.39s，Max RSS 194,896KB。
- seek decode：0.20s，成功。
- `ffprobe` 確認 clean output 只剩 H.264 video + AAC stereo audio，沒有 `bin_data`。

這條路的核心價值是「不用完整預處理，快速把選定音軌變成瀏覽器較友善的輸出」。限制是每位觀看者都會開即時轉封裝程序，音軌是 selected-track-only，不是一次把多音軌都交給播放器。

### Premium：預處理 HLS

手動拆步驟基準：

| 步驟 | 5 分鐘時間 | CPU | Max RSS |
| --- | ---: | ---: | ---: |
| 原畫質 video-only HLS copy | 3.45s | 30% | 61,640KB |
| JPN audio HLS | 4.17s | 65% | 57,588KB |
| ENG audio HLS | 4.55s | 62% | 57,848KB |
| 480p HLS transcode | 25.15s | 215% | 178,560KB |
| 720p HLS transcode | 31.72s | 193% | 191,184KB |
| 23 條字幕抽取 | 53.06s | 3% | 55,164KB |

手動 HLS 總 measured wall：116.995s，derivatives 約 355,390,677 bytes，23 條字幕。

專案 `prepare_stream_asset()` 實測：

- wall：55.55s。
- CPU：228%。
- Max RSS：188,500KB。
- 狀態：ready。
- variants：`original`、`q480`、`q720`。
- audio tracks：2 條，`jpn`、`eng`。
- subtitles：23 條，`sub02_eng` forced subtitle 保留。
- derivative bytes：約 353,848,673 bytes，約 338MB。
- storage total：563MB，包含 225MB 的 5 分鐘 upload sample 與 derivatives。

HLS master manifest 已包含：

- `#EXT-X-MEDIA:TYPE=AUDIO` for JPN/ENG。
- `AUDIO="audio"` on each video variant。
- 1080p original、480p、720p variants。

## 這輪發現並已修正

Premium HLS 轉碼畫質原本在專案實作裡會產生約 10.4 秒切片，和設定的 4 秒切片不一致。原因是 q480/q720 transcode 沒有強制 keyframe，ffmpeg HLS 只能在 GOP/keyframe 邊界切片。

已修正：

- `/home/s92137/hackme_web/services/media/streaming.py`：非 copy video transcode 加上 `-force_key_frames expr:gte(t,n_forced*4)` 與 `-sc_threshold 0`。
- `/home/s92137/hackme_web/tests/video/streaming/test_video_streaming.py`：補測 ffmpeg command 必須帶上述參數。

修正後 playlist：

| variant | segments | duration | max segment |
| --- | ---: | ---: | ---: |
| original | 75 | 300.191s | 4.171s |
| q480 | 76 | 300.300s | 4.004s |
| q720 | 76 | 300.300s | 4.004s |

這使 Premium HLS 的 seek 粒度回到預期的 4 秒級。

## 全片粗估

以 300 秒樣本外推到 6,677.713 秒全片，倍率約 22.26。

- Standard 即時轉封裝：若不節流，完整跑完約 99 秒 CPU/wall，輸出流量約 4.0 GiB；但實際是 on-demand streaming，不會預先保存。
- Premium 專案 HLS：約 20.6 分鐘準備時間，derivatives 約 7.3 GiB，再加原始檔 4.85 GiB。
- 手動全步驟 HLS 基準：約 43.4 分鐘，主要被字幕批次抽取與轉碼畫質拖慢。

外推只能當容量規劃參考，實際全片受片段複雜度、字幕稀疏度、磁碟 cache、worker 並行策略影響。

## 下一步

1. 補 Standard route 原型，但預設關閉，用 feature flag 控制；必須加併發上限、程序清理、音軌選擇與 share 權限。
2. Premium subtitle extraction 應做批次化或快取化；現在產品邏輯正確，但多字幕影片會讓 worker 時間受字幕抽取拖累。
3. Premium HLS job 應在 UI 顯示 derivatives 預估大小，讓客戶在 Basic/Standard/Premium 間明確選成本。
4. 再跑一次瀏覽器端 HLS smoke，驗證前端 audio/subtitle control 在分享頁與影音頁都能切換。

## Artifact

- benchmark root：`/tmp/hackme_scarlet_stream_bench_20260527_5min`
- benchmark report：`/tmp/hackme_scarlet_stream_bench_20260527_5min/report.json`
- project prepare root：`/tmp/hackme_scarlet_project_prepare_5min`
- project report：`/tmp/hackme_scarlet_project_prepare_5min/project_prepare_report.json`
- after-keyframe time：`/tmp/hackme_scarlet_project_prepare_5min_after_keyframes.time.txt`
