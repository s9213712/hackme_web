# hackme_web UI/UX 重整 Agent 指令書 v1.1

> 目標：整理目前過於擁擠、混亂的 hackme_web UI。  
> 核心方向：把公告、討論、表單、管理功能、未開放服務拆分成清楚的區塊與頁面，不要全部塞在同一個畫面。  
> 新增要求：**未開放的服務不要刪除介面入口，改成 disabled / coming soon 狀態，保留未來擴充感。**

---

## 0. 最高指令

目前 UI 太擠、太亂，請重新整理資訊架構。

最高原則：

```text
1. 不要把所有東西放在同一個畫面。
2. 公告歸公告欄。
3. 討論歸討論區。
4. 討論區用列表呈現。
5. 點進討論串後才顯示內文與留言。
6. 發文表單不要常駐，按「發表討論」後才出現。
7. 公告表單不要常駐，admin/root 按「新增公告」後才出現。
8. 子分頁改成側邊分頁 / 側邊欄導覽。
9. 選項不要一行一個全部堆在主畫面。
10. 未開放服務不要刪除入口，改成 disabled / coming soon。
```

---

# Part A — 主版面 Layout

## A1. 整體版面

請改成：

```text
Top Bar
├─ Logo / 站名
├─ 搜尋
├─ 使用者資訊
├─ 通知
├─ 積分錢包摘要
└─ 登出 / 登入

Main Layout
├─ Left Sidebar 側邊導覽
└─ Main Content 主要內容區
```

---

## A2. Sidebar 側邊導覽

將目前子分頁改成側邊欄。

建議分類：

```text
內容
- 首頁
- 公告欄
- 討論區
- 我的貼文

服務
- 雲端硬碟
- AI 生圖
- Server 租用
- 網頁遊戲

經濟
- 積分錢包
- 商城

系統
- 系統設定
- 管理後台
- Root 控制台
```

要求：

```text
1. 側邊欄可收合。
2. 手機版變成 hamburger drawer。
3. 目前所在頁面要有 active 狀態。
4. admin/root 才能看到管理入口。
5. 未開放服務保留入口，但要 disabled 或 coming soon。
6. 不要把所有功能按鈕堆在首頁。
```

---

# Part B — 未開放服務入口規則

## B1. 未開放服務不要刪除

若以下服務尚未完成或尚未開放，不要從 UI 移除：

```text
商城
AI 生圖
Server 租用
雲端硬碟
網頁遊戲
串流平台
積分任務
Bug bounty
私有鏈交易證明
```

請保留入口，但改成：

```text
disabled
coming soon
beta locked
admin preview only
requires permission
```

---

## B2. Disabled / Coming Soon 顯示規則

未開放服務顯示方式：

```text
Sidebar item 保留
按鈕不可點或點擊後顯示提示
文字顯示 Coming soon / 尚未開放
圖示降低透明度
不可導向不存在頁面造成 404
```

建議 UI：

```text
[AI 生圖] Coming soon
[Server 租用] Coming soon
[商城] Beta
[網頁遊戲] 尚未開放
```

---

## B3. 點擊未開放項目的行為

不可：

```text
1. 直接 404
2. 直接白畫面
3. 直接刪掉入口
4. 讓使用者以為壞掉
```

應該：

```text
1. 若 disabled：不可點擊。
2. 若可點擊：開啟 Coming Soon modal。
3. modal 說明服務尚未開放。
4. 可顯示預計功能描述。
5. admin/root 可看到「管理預覽」或「開發中」標記。
```

Coming Soon modal 內容範例：

```text
此服務尚未開放

功能：AI 生圖服務
狀態：開發中
未來用途：使用積分呼叫 ComfyUI 生成圖片
目前：僅保留入口，尚不可使用
```

---

## B4. Feature Flag

請使用 feature flag 控制服務狀態。

建議狀態：

```text
hidden：完全隱藏，只用於極敏感 root-only 功能
disabled：顯示但不能點
coming_soon：顯示，點擊後出提示
beta：部分使用者可用
enabled：正式開放
```

建議設定：

```yaml
features:
  marketplace:
    status: "coming_soon"
  ai_image:
    status: "coming_soon"
  server_rental:
    status: "coming_soon"
  cloud_drive:
    status: "beta"
  web_games:
    status: "coming_soon"
  streaming:
    status: "disabled"
```

UI 必須依 feature status 顯示狀態。

---

# Part C — 首頁重整

## C1. 首頁只放摘要

首頁不要塞全部內容，只放摘要卡片：

```text
最新公告 3 則
熱門討論 5 則
我的積分摘要
快捷入口
系統狀態
未開放服務預告
```

---

## C2. 首頁不得顯示

首頁不要顯示：

```text
所有公告全文
所有討論全文
所有留言
常駐發文表單
常駐公告表單
所有管理功能
```

---

# Part D — 公告欄重整

## D1. 公告欄列表頁

建議路徑：

```text
/announcements
```

列表顯示：

```text
公告標題
摘要
發布者
發布時間
重要 / 置頂標記
點擊進入詳細頁
```

---

## D2. 公告詳細頁

建議路徑：

```text
/announcements/:id
```

顯示：

```text
公告標題
公告內容
發布者
發布時間
更新時間
重要標記
返回公告列表
```

---

## D3. 撰寫公告

不要直接把公告輸入框放在主畫面。

改成：

```text
[新增公告] 按鈕
→ 點擊後開啟 modal / drawer / 獨立編輯頁
→ 填寫標題與內容
→ 預覽
→ 發布
```

權限：

```text
只有 admin/root 可看到新增公告按鈕。
一般用戶不可看到公告撰寫表單。
後端 API 也必須檢查權限，不能只靠前端隱藏。
```

---

# Part E — 討論區重整

## E1. 討論區列表頁

建議路徑：

```text
/forum
```

列表顯示：

```text
討論串標題
分類
作者
建立時間
最後回覆時間
回覆數
瀏覽數
按讚數
狀態：置頂 / 鎖定 / 精華
```

不要在列表頁顯示完整內文與所有留言。

---

## E2. 討論串詳細頁

建議路徑：

```text
/forum/threads/:id
```

顯示：

```text
討論標題
作者
發文時間
內文
按讚 / 收藏 / 檢舉
留言列表
回覆輸入框
```

留言區要求：

```text
1. 預設只載入前 N 則留言。
2. 支援分頁或載入更多。
3. 不要一次塞滿全部留言。
4. 管理員可刪除 / 隱藏 / 鎖定留言。
```

---

## E3. 撰寫貼文

不要直接顯示大型輸入框。

改成：

```text
[發表討論] 按鈕
→ 點擊後開啟 modal / drawer / 獨立發文頁
→ 選擇分類
→ 輸入標題
→ 輸入內容
→ 預覽
→ 發布
```

建議路徑：

```text
/forum/new
```

---

# Part F — 選項整理方式

如果目前選項是一行一個，請改成：

```text
1. 側邊分類
2. 卡片式分組
3. compact action menu
4. 下拉選單
5. tabs
6. command palette，若專案已有類似設計
```

範例：

不要：

```text
發文
公告
雲端
商城
AI
Server
遊戲
管理
設定
```

改成：

```text
內容
- 公告欄
- 討論區
- 我的貼文

服務
- 雲端硬碟
- AI 生圖
- Server 租用
- 網頁遊戲

經濟
- 積分錢包
- 商城

系統
- 設定
- 管理後台
```

---

# Part G — 元件設計

請建立或整理以下 UI 元件：

```text
AppLayout
TopBar
Sidebar
SidebarSection
SidebarItem
FeatureGate
ComingSoonModal
PageHeader
Card
ListView
EmptyState
LoadingState
ErrorState
Modal
Drawer
Button
Badge
Tabs
Pagination
ThreadList
ThreadCard
AnnouncementList
AnnouncementCard
CommentList
CommentItem
EditorModal
ConfirmDialog
```

---

# Part H — FeatureGate 元件要求

請新增 FeatureGate 或等效邏輯。

用途：

```text
依 feature status 控制顯示、點擊、提示與權限。
```

FeatureGate 必須支援：

```text
enabled：正常可點
beta：顯示 Beta badge，依權限可點
coming_soon：顯示 Coming soon badge，點擊彈提示
disabled：顯示灰階，不能點
hidden：不顯示
```

偽邏輯：

```text
if status == hidden:
  do not render

if status == disabled:
  render disabled item

if status == coming_soon:
  render item with Coming soon badge
  on click show ComingSoonModal

if status == beta:
  render item with Beta badge
  if user has permission allow access
  else show beta locked message

if status == enabled:
  render normal link
```

---

# Part I — 路由建議

請整理成清楚路由：

```text
/
 /announcements
 /announcements/:id
 /forum
 /forum/new
 /forum/threads/:id
 /cloud
 /wallet
 /marketplace
 /ai-image
 /server-rental
 /games
 /streaming
 /admin
 /admin/announcements
 /admin/users
 /admin/reports
 /root
 /settings
```

未開放服務路由處理：

```text
如果 feature status 是 coming_soon / disabled，不應出現 404。
可以導向 /coming-soon?feature=ai-image 或顯示 modal。
```

---

# Part J — API 建議

若目前 API 混亂，請整理成：

```text
GET    /api/announcements
GET    /api/announcements/:id
POST   /api/announcements
PUT    /api/announcements/:id
DELETE /api/announcements/:id

GET    /api/forum/threads
GET    /api/forum/threads/:id
POST   /api/forum/threads
PUT    /api/forum/threads/:id
DELETE /api/forum/threads/:id

GET    /api/forum/threads/:id/comments
POST   /api/forum/threads/:id/comments
DELETE /api/forum/comments/:id

GET    /api/features
```

要求：

```text
1. 列表 API 不回傳完整留言。
2. 詳細 API 才回傳內文。
3. 留言獨立分頁載入。
4. 公告與討論不可混在同一 API。
5. /api/features 回傳每個功能的 status。
6. 後端也要檢查未開放服務，不可只靠前端 disabled。
```

---

# Part K — 權限顯示規則

## K1. 一般用戶

可看到：

```text
公告欄
討論區
我的貼文
錢包
服務入口
未開放服務 coming soon 入口
```

不可看到：

```text
新增公告
管理後台
root 工具
其他用戶敏感資料
```

---

## K2. Admin

可看到：

```text
公告管理
討論管理
用戶管理入口
檢舉處理
部分 beta 功能預覽
```

---

## K3. Root

可看到：

```text
系統狀態
安全設定
私有鏈驗證
伺服器模式
快照 / 備份
全部功能開關設定
```

---

# Part L — 響應式設計

## L1. 桌面

```text
左側 sidebar 固定
主內容最大寬度
列表不過度拉伸
```

## L2. 平板

```text
sidebar 可收合
卡片兩欄或單欄
```

## L3. 手機

```text
sidebar 變 hamburger drawer
列表單欄
表格改卡片
大型按鈕
避免橫向捲動
```

---

# Part M — UX 品質要求

必須做到：

```text
1. 首頁乾淨。
2. 公告與討論分開。
3. 列表與詳細頁分開。
4. 表單按需顯示。
5. 操作按鈕清楚。
6. 管理功能不干擾一般用戶。
7. 未開放服務保留入口但清楚標示。
8. 空資料時有 EmptyState。
9. 載入時有 LoadingState。
10. 錯誤時有 ErrorState。
11. 手機可用。
```

---

# Part N — 測試要求

請測試：

```text
1. 一般用戶看不到新增公告。
2. admin/root 看得到新增公告。
3. 討論區列表不顯示完整留言。
4. 點進討論串才載入留言。
5. 發文按鈕能開啟表單。
6. 公告按鈕能開啟表單。
7. 手機版 sidebar 可正常開關。
8. active menu 狀態正確。
9. 空公告 / 空討論區有提示。
10. 未登入狀態導向登入或唯讀模式。
11. API 權限不只靠前端隱藏，後端也要擋。
12. 未開放服務入口仍存在。
13. 未開放服務不能進入正式功能頁。
14. coming_soon 點擊會顯示提示，不會 404。
15. disabled 項目不可點擊。
16. beta 項目依權限顯示。
17. feature hidden 才會完全隱藏。
```

---

# Part O — 交付項目

請交付：

```text
1. 新 Layout / Sidebar / TopBar
2. FeatureGate / ComingSoonModal
3. 公告列表頁
4. 公告詳細頁
5. 公告新增 / 編輯 modal 或頁面
6. 討論區列表頁
7. 討論串詳細頁
8. 發文 modal 或頁面
9. 留言列表分頁 / 載入更多
10. 權限控制
11. 響應式 UI
12. /api/features 或等效功能開關
13. 測試
14. README 或 docs/ui_restructure.md
```

---

# Part P — 完成後回報格式

請用以下格式回報：

```text
# UI 重整完成摘要

## 已完成
-

## 新增 / 修改頁面
-

## 新增 / 修改元件
-

## Feature Flag / 未開放服務處理
-

## 路由整理
-

## API 調整
-

## 權限控制
-

## 手機版測試
-

## 尚未完成
-

## 需要人工確認
-

## 建議下一階段
-
```

---

# Part Q — 最終提醒

本次 UI 重整的核心不是換皮，而是重新整理資訊層級：

```text
公告歸公告。
討論歸討論。
列表歸列表。
詳細內容點進去才看。
表單按按鈕才出現。
側邊導覽取代雜亂子分頁。
未開放服務保留入口，但要清楚標示不可用。
管理功能不要干擾一般用戶。
```
