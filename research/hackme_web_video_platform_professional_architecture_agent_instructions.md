# hackme_web 影片分享平台（YouTube-like）專業級架構 Agent 指令檔 v2.0

> 目標：在 hackme_web 建立一個類似 YouTube 的站內影片分享平台。  
> 使用者可從自己的雲端硬碟選擇影片發布到影片平台，其他使用者可觀看、按讚、留言、分享、投幣。  
> 創作者可因互動與投幣獲得積分，平台可從投幣抽成。  
> 系統必須整合：雲端硬碟、積分經濟、私有鏈 ledger、AI 審核、風控、防刷、推薦、排行榜、後台管理與未來 CDN/串流擴展。

---

# 0. 最高設計原則

請為 hackme_web 建立「影片分享 + 創作者經濟」系統。

必須遵守：

```text
1. 影片來源必須來自使用者自己的 Cloud Drive。
2. 影片平台只引用 cloud_file_id，不允許繞過雲端硬碟權限。
3. 影片發布後產生 video record，但原始檔仍由 Cloud Drive / Object Storage 管理。
4. 投幣、收益、抽成都必須走 PointsLedgerService。
5. 創作者收益與平台抽成必須可審計。
6. 排行、推薦、收益都必須防刷。
7. 觀看、按讚、留言、分享不得被簡單濫用來洗積分。
8. 影片內容需支援審核與下架。
9. 一般用戶不可看到其他用戶未公開影片。
10. admin/root 可依權限管理影片、檢舉、收益與風控。
11. 未來可擴展 CDN、HLS 串流、多清晰度轉碼。
```

---

# Part A — 系統定位

## A1. 功能定位

此功能是：

```text
站內影片分享平台
+
創作者積分收益系統
+
內容互動系統
+
內容審核系統
+
推薦與排行系統
```

不是：

```text
外部影片網站爬取器
盜版影片分發平台
無審核內容平台
真實貨幣支付平台
匿名洗積分系統
```

---

## A2. 使用者流程

```text
1. 使用者上傳影片到自己的雲端硬碟。
2. 使用者進入 /videos/upload。
3. 從自己的雲端硬碟選擇影片檔。
4. 填寫標題、描述、分類、標籤、可見性。
5. 系統驗證該檔案屬於該使用者。
6. 系統建立 video record。
7. 背景任務產生縮圖、metadata、可選轉碼。
8. admin/AI 審核通過後公開，或先進 pending_review。
9. 其他用戶觀看影片、按讚、留言、分享、投幣。
10. 創作者依規則獲得積分。
11. 平台從投幣中抽成。
12. 排行榜、推薦系統依互動與品質排序。
```

---

# Part B — 路由與頁面

## B1. Public/User Routes

```text
/videos
/videos/:video_uuid
/videos/upload
/videos/my
/videos/history
/videos/liked
/videos/trending
/videos/categories/:category_slug
/videos/tags/:tag
```

---

## B2. Creator Routes

```text
/creator
/creator/videos
/creator/analytics
/creator/earnings
/creator/comments
```

---

## B3. Admin/Root Routes

```text
/admin/videos
/admin/videos/reports
/admin/videos/moderation
/admin/videos/monetization
/admin/videos/risk
/root/videos/system
/root/videos/revenue
/root/videos/storage
/root/videos/worker-status
```

---

# Part C — UI/UX 要求

## C1. /videos 影片首頁

顯示：

```text
1. 推薦影片 feed
2. 熱門影片
3. 最新影片
4. 分類入口
5. 搜尋列
6. 篩選：最新 / 熱門 / 最多投幣 / 最多留言
```

影片卡片顯示：

```text
縮圖
標題
作者匿名/暱稱設定
觀看數
按讚數
投幣數
發布時間
影片長度
審核狀態標記，僅作者/admin 可見
```

---

## C2. /videos/:video_uuid 詳細頁

顯示：

```text
影片播放器
標題
作者資訊
發布時間
觀看數
按讚 / 取消讚
投幣按鈕
分享按鈕
收藏按鈕
描述
標籤
留言區
推薦相關影片
檢舉按鈕
```

留言區：

```text
1. 分頁載入。
2. 支援回覆。
3. 支援排序：最新 / 熱門。
4. admin 可隱藏 / 刪除 / 鎖定。
5. 作者可置頂留言，若允許。
```

---

## C3. /videos/upload 發布頁

流程：

```text
1. 從自己的 Cloud Drive 選擇影片。
2. 驗證檔案格式。
3. 填寫 metadata：
   - title
   - description
   - category
   - tags
   - visibility
   - allow_comments
   - allow_coins
4. 顯示使用規則與內容政策。
5. 發布。
6. 進入 processing / pending_review。
```

支援格式 MVP：

```text
mp4
webm
mov，可選
mkv，可選
```

---

## C4. /creator 創作者中心

顯示：

```text
我的影片
總觀看數
總按讚數
總投幣
平台抽成
實得積分
近期留言
被檢舉狀態
收益明細
熱門影片
```

---

# Part D — 資料表設計

## D1. videos

```sql
CREATE TABLE videos (
  id BIGSERIAL PRIMARY KEY,
  video_uuid UUID NOT NULL UNIQUE,

  user_id BIGINT NOT NULL,
  cloud_file_id BIGINT NOT NULL,

  title VARCHAR(255) NOT NULL,
  description TEXT,

  category VARCHAR(100),
  tags_json TEXT,

  visibility VARCHAR(30) NOT NULL DEFAULT 'public',

  status VARCHAR(40) NOT NULL DEFAULT 'processing',
  moderation_status VARCHAR(40) NOT NULL DEFAULT 'pending',

  thumbnail_path TEXT,
  poster_path TEXT,

  duration_seconds INT,
  width INT,
  height INT,
  file_size_bytes BIGINT,
  mime_type VARCHAR(120),

  hls_manifest_path TEXT,
  transcoding_status VARCHAR(40) DEFAULT 'not_required',

  view_count BIGINT NOT NULL DEFAULT 0,
  unique_view_count BIGINT NOT NULL DEFAULT 0,
  like_count BIGINT NOT NULL DEFAULT 0,
  comment_count BIGINT NOT NULL DEFAULT 0,
  share_count BIGINT NOT NULL DEFAULT 0,
  coin_count BIGINT NOT NULL DEFAULT 0,

  total_coin_received BIGINT NOT NULL DEFAULT 0,
  total_creator_earn BIGINT NOT NULL DEFAULT 0,
  total_platform_fee BIGINT NOT NULL DEFAULT 0,

  allow_comments BOOLEAN NOT NULL DEFAULT TRUE,
  allow_coins BOOLEAN NOT NULL DEFAULT TRUE,

  published_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CHECK (visibility IN ('public', 'unlisted', 'private')),
  CHECK (status IN ('processing', 'pending_review', 'published', 'blocked', 'deleted', 'failed')),
  CHECK (moderation_status IN ('pending', 'approved', 'rejected', 'flagged')),
  CHECK (transcoding_status IN ('not_required', 'queued', 'running', 'completed', 'failed'))
);
```

---

## D2. video_views

```sql
CREATE TABLE video_views (
  id BIGSERIAL PRIMARY KEY,

  video_id BIGINT NOT NULL,
  viewer_user_id BIGINT,

  viewer_public_id CHAR(64),
  session_digest CHAR(64),
  ip_digest CHAR(64),
  user_agent_digest CHAR(64),

  watch_seconds INT NOT NULL DEFAULT 0,
  completed BOOLEAN NOT NULL DEFAULT FALSE,

  counted_as_view BOOLEAN NOT NULL DEFAULT FALSE,
  counted_as_unique BOOLEAN NOT NULL DEFAULT FALSE,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

觀看數計算規則：

```text
1. watch_seconds >= 10 才可計入 view。
2. 同一 user/session/IP 在短時間內重複觀看不重複計 unique。
3. 不得單純 page load 就加 view_count。
```

---

## D3. video_likes

```sql
CREATE TABLE video_likes (
  id BIGSERIAL PRIMARY KEY,

  video_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  UNIQUE (video_id, user_id)
);
```

---

## D4. video_comments

```sql
CREATE TABLE video_comments (
  id BIGSERIAL PRIMARY KEY,
  comment_uuid UUID NOT NULL UNIQUE,

  video_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,

  parent_id BIGINT,

  content TEXT NOT NULL,

  status VARCHAR(30) NOT NULL DEFAULT 'visible',

  like_count BIGINT NOT NULL DEFAULT 0,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CHECK (status IN ('visible', 'hidden', 'deleted', 'flagged'))
);
```

---

## D5. video_shares

```sql
CREATE TABLE video_shares (
  id BIGSERIAL PRIMARY KEY,

  video_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,

  share_target VARCHAR(80),
  share_token VARCHAR(120),

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

## D6. video_coins

```sql
CREATE TABLE video_coins (
  id BIGSERIAL PRIMARY KEY,
  coin_uuid UUID NOT NULL UNIQUE,

  video_id BIGINT NOT NULL,

  from_user_id BIGINT NOT NULL,
  to_user_id BIGINT NOT NULL,

  amount BIGINT NOT NULL,
  platform_fee BIGINT NOT NULL,
  creator_earn BIGINT NOT NULL,

  fee_rate NUMERIC(6,4) NOT NULL,

  spend_ledger_uuid UUID,
  creator_earn_ledger_uuid UUID,
  platform_fee_ledger_uuid UUID,

  status VARCHAR(30) NOT NULL DEFAULT 'completed',

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CHECK (amount > 0),
  CHECK (platform_fee >= 0),
  CHECK (creator_earn >= 0),
  CHECK (status IN ('completed', 'refunded', 'reversed', 'flagged'))
);
```

---

## D7. video_reports

```sql
CREATE TABLE video_reports (
  id BIGSERIAL PRIMARY KEY,
  report_uuid UUID NOT NULL UNIQUE,

  video_id BIGINT NOT NULL,
  reporter_user_id BIGINT NOT NULL,

  reason VARCHAR(100) NOT NULL,
  detail TEXT,

  status VARCHAR(30) NOT NULL DEFAULT 'open',

  reviewed_by BIGINT,
  resolution TEXT,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reviewed_at TIMESTAMP,

  CHECK (status IN ('open', 'reviewing', 'resolved', 'rejected', 'escalated'))
);
```

---

## D8. video_moderation_events

```sql
CREATE TABLE video_moderation_events (
  id BIGSERIAL PRIMARY KEY,

  video_id BIGINT NOT NULL,

  event_type VARCHAR(100) NOT NULL,
  actor_user_id BIGINT,
  actor_role VARCHAR(50),

  old_status VARCHAR(50),
  new_status VARCHAR(50),

  reason TEXT,
  metadata_json TEXT,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

## D9. video_creator_earnings_daily

```sql
CREATE TABLE video_creator_earnings_daily (
  id BIGSERIAL PRIMARY KEY,

  user_id BIGINT NOT NULL,
  stat_date DATE NOT NULL,

  views BIGINT NOT NULL DEFAULT 0,
  likes BIGINT NOT NULL DEFAULT 0,
  comments BIGINT NOT NULL DEFAULT 0,
  shares BIGINT NOT NULL DEFAULT 0,

  coin_received BIGINT NOT NULL DEFAULT 0,
  creator_earn BIGINT NOT NULL DEFAULT 0,
  platform_fee BIGINT NOT NULL DEFAULT 0,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  UNIQUE (user_id, stat_date)
);
```

---

## D10. video_recommendation_scores

```sql
CREATE TABLE video_recommendation_scores (
  id BIGSERIAL PRIMARY KEY,

  video_id BIGINT NOT NULL UNIQUE,

  score NUMERIC(20, 8) NOT NULL DEFAULT 0,

  view_score NUMERIC(20, 8) NOT NULL DEFAULT 0,
  like_score NUMERIC(20, 8) NOT NULL DEFAULT 0,
  comment_score NUMERIC(20, 8) NOT NULL DEFAULT 0,
  coin_score NUMERIC(20, 8) NOT NULL DEFAULT 0,
  freshness_score NUMERIC(20, 8) NOT NULL DEFAULT 0,
  safety_penalty NUMERIC(20, 8) NOT NULL DEFAULT 0,
  abuse_penalty NUMERIC(20, 8) NOT NULL DEFAULT 0,

  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

# Part E — 投幣與平台抽成

## E1. 投幣規則

流程：

```text
viewer 投幣 amount points
→ 平台扣 viewer points
→ 平台抽成 fee
→ 創作者獲得 creator_earn
→ 三筆 ledger 可審計
```

建議：

```text
platform_fee_rate = 20%
creator_earn_rate = 80%
```

範例：

```text
投幣 100 soft_points
平台抽成 20
創作者得 80
```

---

## E2. Ledger action_type

必須使用 PointsLedgerService。

```text
video_coin_spend
video_coin_creator_earn
video_coin_platform_fee
video_coin_refund
video_coin_reversal
```

reference：

```text
reference_type = video_coin
reference_id = coin_uuid
```

---

## E3. 禁止行為

```text
1. 不允許自己投幣給自己。
2. 不允許餘額不足投幣。
3. 不允許前端決定平台抽成。
4. 不允許繞過 ledger 直接改 wallet。
5. 不允許同一組帳號互相大量投幣洗收益。
```

---

## E4. 投幣風控

偵測：

```text
同 IP 多帳號投幣
同設備多帳號投幣
短時間大量小額投幣
固定帳號互相投幣
新帳號高額投幣
異常退款/反轉
```

處置：

```text
標記 video_coin 為 flagged
延遲結算創作者收益
凍結可疑收益
通知 admin/root
```

---

# Part F — 互動積分收益

## F1. 可獲得積分的互動

創作者可因以下互動獲得 soft_points：

```text
有效觀看
有效按讚
有效留言
有效分享
投幣
```

MVP 建議：

```text
投幣：直接收益
有效觀看：暫不給點，只計推薦
按讚：可給少量，但需防刷
留言：可給少量，但需品質門檻
分享：可給少量，但需有效點擊才算
```

---

## F2. 防刷收益規則

```text
1. 同一 viewer 對同一影片按讚只算一次。
2. 同一 viewer 對同一創作者每日收益有限。
3. 新帳號互動權重較低。
4. 被判定低品質留言不給點。
5. 觀看時間太短不算有效觀看。
6. 大量同 IP / 同裝置互動降低權重。
```

---

# Part G — 雲端硬碟整合

## G1. 發布影片來源

影片只能來自：

```text
使用者自己的 Cloud Drive
```

發布時必須檢查：

```text
1. cloud_file_id 存在。
2. cloud_file_id owner_id == current_user_id。
3. 檔案 mime_type 是允許影片格式。
4. 檔案未被刪除。
5. 檔案未被安全系統隔離。
6. 檔案大小不超過限制。
```

---

## G2. 權限關係

影片公開後：

```text
public video 可被其他用戶觀看。
private video 只有作者可看。
unlisted video 只有連結持有者可看。
```

但原始 cloud file 不應因此變成所有人可直接下載。

正確方式：

```text
影片播放走 VideoService 授權
不要直接暴露 Cloud Drive 原始檔案路徑
```

---

## G3. 影片刪除

若作者刪除雲端原始檔：

```text
影片 status 應標記 unavailable 或 failed。
```

若作者刪除影片：

```text
不一定刪除 Cloud Drive 原始檔，只刪 video record / publish state。
```

---

# Part H — 轉碼 / 縮圖 / 播放

## H1. MVP 播放策略

MVP 可先：

```text
直接播放 mp4/webm
後端授權後 streaming file
不做多清晰度轉碼
```

---

## H2. 專業版播放策略

後續加入：

```text
FFmpeg 轉 HLS
多清晰度 360p / 720p / 1080p
影片縮圖
影片預覽 GIF
音訊分析
字幕
CDN
```

---

## H3. Worker 任務

新增背景任務：

```text
video_extract_metadata
video_generate_thumbnail
video_transcode_hls
video_scan_content
video_update_recommendation_scores
video_update_creator_earnings
```

---

## H4. FFmpeg 依賴

宿主機建議安裝：

```bash
sudo apt update
sudo apt install -y ffmpeg mediainfo
```

用途：

```text
ffmpeg：轉碼、縮圖、HLS
mediainfo：讀取影片 metadata
```

---

# Part I — 內容審核

## I1. 審核狀態

```text
pending
approved
rejected
flagged
```

---

## I2. 審核來源

```text
1. 自動規則
2. AI moderation
3. 用戶檢舉
4. admin 人工審核
5. root 強制下架
```

---

## I3. 需要審核的內容

```text
影片標題
影片描述
標籤
縮圖
影片內容，MVP 可先不深度掃描
留言
```

---

## I4. 管理操作

admin/root 可：

```text
下架影片
恢復影片
鎖留言
刪留言
標記限制級
封鎖投幣
凍結收益
處理檢舉
```

所有操作必須寫入：

```text
video_moderation_events
audit log
```

---

# Part J — 推薦與排行

## J1. MVP 排序

/videos feed 初期可用：

```text
score =
  freshness_score * 0.30
+ like_score * 0.20
+ comment_score * 0.15
+ coin_score * 0.25
+ view_score * 0.10
- abuse_penalty
- safety_penalty
```

---

## J2. 排行榜

新增：

```text
熱門影片
最多投幣影片
最多按讚影片
最多留言影片
新片榜
創作者收益榜，可選
```

創作者收益榜若顯示，建議用匿名或可由創作者選擇公開。

---

## J3. 推薦防作弊

推薦分數應降低：

```text
同 IP 大量觀看
同帳號群互刷
新帳號大量按讚
觀看時間過短
留言重複
被大量檢舉
```

---

# Part K — API 設計

## K1. User API

```http
GET    /api/videos
GET    /api/videos/trending
GET    /api/videos/:video_uuid
POST   /api/videos
PUT    /api/videos/:video_uuid
DELETE /api/videos/:video_uuid

POST   /api/videos/:video_uuid/view-event
POST   /api/videos/:video_uuid/like
POST   /api/videos/:video_uuid/unlike
POST   /api/videos/:video_uuid/coin
POST   /api/videos/:video_uuid/share

GET    /api/videos/:video_uuid/comments
POST   /api/videos/:video_uuid/comments
DELETE /api/videos/comments/:comment_uuid

POST   /api/videos/:video_uuid/report

GET    /api/creator/videos
GET    /api/creator/analytics
GET    /api/creator/earnings
```

---

## K2. Cloud Drive 選檔 API

```http
GET /api/cloud-drive/my-video-files
```

回傳使用者自己的可發布影片。

---

## K3. Admin API

```http
GET  /api/admin/videos
GET  /api/admin/videos/reports
POST /api/admin/videos/:video_uuid/approve
POST /api/admin/videos/:video_uuid/reject
POST /api/admin/videos/:video_uuid/block
POST /api/admin/videos/:video_uuid/restore
POST /api/admin/videos/:video_uuid/freeze-earnings
POST /api/admin/videos/comments/:comment_uuid/hide
```

---

## K4. Root API

```http
GET  /api/root/videos/system
GET  /api/root/videos/revenue
GET  /api/root/videos/storage
POST /api/root/videos/rebuild-recommendations
POST /api/root/videos/recalculate-earnings
POST /api/root/videos/disable-monetization
```

---

# Part L — Service 設計

## L1. VideoService

```text
create_video_from_cloud_file()
update_video_metadata()
publish_video()
delete_video()
get_video()
list_videos()
check_video_permission()
```

---

## L2. VideoPlaybackService

```text
get_playback_url()
authorize_stream()
record_view_event()
calculate_effective_view()
```

---

## L3. VideoEngagementService

```text
like_video()
unlike_video()
comment_video()
share_video()
record_watch_progress()
```

---

## L4. VideoCoinService

```text
coin_video()
calculate_platform_fee()
credit_creator()
credit_platform_fee()
reverse_coin()
detect_coin_abuse()
```

---

## L5. VideoModerationService

```text
submit_report()
review_report()
approve_video()
reject_video()
block_video()
restore_video()
hide_comment()
freeze_video_earnings()
```

---

## L6. VideoRecommendationService

```text
calculate_video_score()
update_recommendation_scores()
get_home_feed()
get_trending_videos()
get_related_videos()
```

---

## L7. VideoProcessingService

```text
extract_metadata()
generate_thumbnail()
transcode_hls()
verify_video_file()
```

---

# Part M — 權限與隱私

## M1. Video visibility

```text
public：所有登入用戶可看
unlisted：知道連結者可看
private：只有作者可看
```

---

## M2. User 權限

使用者可：

```text
發布自己的影片
編輯自己的影片 metadata
刪除自己的影片發布狀態
查看自己的收益
管理自己影片留言，可選
```

不可：

```text
發布別人的 cloud file
修改別人的影片
看 private 影片
偽造觀看數
偽造投幣
繞過積分扣款
```

---

## M3. Admin/root 權限

admin 可：

```text
審核影片
處理檢舉
下架違規影片
隱藏留言
凍結可疑收益
```

root 可：

```text
全域停用影片平台
停用 monetization
重算收益
重建推薦
查看平台抽成報表
```

---

# Part N — 安全與防濫用

## N1. 必防風險

```text
1. 自己投幣給自己。
2. 多帳號互刷。
3. 刷觀看數。
4. 刷留言。
5. 刷分享。
6. 假檔案 / 非影片冒充。
7. 影片檔案路徑穿越。
8. 直接下載他人雲端原始檔。
9. 未審核違規內容公開。
10. 投幣抽成計算被前端操控。
11. 重複按讚。
12. 重複投幣惡意洗榜。
```

---

## N2. 安全要求

```text
1. 所有 video_uuid 使用 UUID，不使用連續 id。
2. 前端不得傳入創作者收益與平台抽成。
3. 投幣金額、抽成、收益由後端計算。
4. 檔案播放必須走授權 endpoint。
5. 不暴露本機儲存路徑。
6. 不允許 path traversal。
7. 所有高風險操作寫 audit log。
8. 可疑收益可以延遲結算。
```

---

# Part O — 積分與收益結算

## O1. 即時結算 vs 延遲結算

MVP 可採：

```text
投幣即時扣款
創作者收益即時入帳
平台抽成即時入帳
可疑交易後續 reverse/freeze
```

專業版建議：

```text
投幣即時扣款
創作者收益進 pending balance
通過風控後結算
```

---

## O2. 平台抽成設定

設定：

```yaml
video_platform:
  coin_fee_rate: 0.20
  min_coin_amount: 1
  max_coin_amount: 10000
  creator_settlement_mode: "instant"
```

---

# Part P — AI 整合

## P1. AI 可做

```text
1. 標題/描述分類建議。
2. 標籤建議。
3. 留言摘要。
4. 檢舉初步分類。
5. 可疑互動摘要。
6. 內容審核輔助。
```

---

## P2. AI 不可直接做

```text
1. 未經 admin/root 確認自動永久下架。
2. 自動永久封禁創作者。
3. 自動刪除影片原始檔。
4. 外傳使用者私有影片給不受控第三方。
```

---

# Part Q — 背景任務

新增 workers：

```text
video_process_new_uploads
video_generate_thumbnails
video_scan_pending_moderation
video_update_view_counts
video_update_recommendation_scores
video_detect_abuse
video_update_creator_earnings_daily
video_cleanup_deleted_records
```

頻率建議：

```text
thumbnail/metadata：即時或每分鐘
view count aggregation：每 1~5 分鐘
recommendation score：每 5~15 分鐘
abuse detection：每 5 分鐘
earnings daily：每天
```

---

# Part R — 測試要求

必測：

```text
1. 使用者只能發布自己的 cloud_file。
2. 非影片格式不能發布。
3. public/private/unlisted 權限正確。
4. 影片列表正常。
5. 影片詳細頁正常。
6. 按讚去重。
7. 取消按讚正常。
8. 留言正常。
9. 留言分頁正常。
10. 投幣扣點正確。
11. 平台抽成正確。
12. 創作者收益正確。
13. 自己不能投幣給自己。
14. 餘額不足不能投幣。
15. 投幣 ledger 完整。
16. 分享計數正常。
17. 觀看數不因刷新暴增。
18. 檢舉能建立 report。
19. admin 可下架影片。
20. 下架影片一般用戶不可觀看。
21. 不暴露 cloud 原始路徑。
22. path traversal 防護有效。
23. 可疑互刷可被標記。
24. creator analytics 正確。
```

---

# Part S — 交付項目

請交付：

```text
1. database migrations
2. VideoService
3. VideoPlaybackService
4. VideoEngagementService
5. VideoCoinService
6. VideoModerationService
7. VideoRecommendationService
8. VideoProcessingService
9. User video APIs
10. Creator APIs
11. Admin/root video APIs
12. /videos UI
13. /videos/:id UI
14. /videos/upload UI
15. /creator UI
16. admin moderation UI
17. thumbnail / metadata worker
18. recommendation worker
19. abuse detection worker
20. PointsLedgerService integration
21. CloudDrive integration
22. tests
23. docs/video_platform_design.md
24. docs/video_monetization_rules.md
25. docs/video_moderation_policy.md
26. docs/video_abuse_prevention.md
```

---

# Part T — MVP 分階段落地

## Phase 1 — 基礎影片發布

```text
/videos
/videos/:id
/videos/upload
cloud_file_id 選擇
影片播放
基本 metadata
```

---

## Phase 2 — 互動功能

```text
按讚
留言
分享
觀看數
收藏，可選
```

---

## Phase 3 — 投幣與收益

```text
投幣
平台抽成
創作者收益
ledger
creator earnings
```

---

## Phase 4 — 審核與檢舉

```text
檢舉
admin 審核
下架
留言管理
收益凍結
```

---

## Phase 5 — 推薦與排行

```text
推薦 feed
熱門榜
最多投幣榜
新片榜
防刷排序
```

---

## Phase 6 — 轉碼與 CDN

```text
FFmpeg metadata
縮圖
HLS
多清晰度
CDN / object storage
```

---

# Part U — 完成後回報格式

請用以下格式回報：

```text
# hackme_web 影片分享平台完成摘要

## 已完成
-

## 新增資料表
-

## 新增 Service
-

## 新增 API
-

## 新增 UI
-

## 雲端硬碟整合
-

## 投幣 / 抽成 / 創作者收益
-

## 審核 / 檢舉
-

## 推薦 / 排行
-

## 防濫用
-

## 測試結果
-

## 尚未完成
-

## 需要 root 人工確認
-

## 建議下一階段
-
```

---

# Part V — 最高提醒

此系統不是單純影片頁，而是 hackme_web 的內容經濟核心之一。

最高原則：

```text
影片來源可控
播放權限可控
互動收益可審計
投幣抽成可追溯
推薦排行防刷
內容審核可管理
用戶隱私不外洩
平台有能力下架、凍結、回溯
```
