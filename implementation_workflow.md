# hackme_web 大工程實作工作流程

最後更新：2026-04-27  
目前分支：`feature/forum-governance-security-modes`

## 進度規則

- `[x]` 已完成並通過測試
- `[ ]` 未完成
- 每批完成後先跑測試，再提交到功能分支
- 禁止直接推送到 `main`，最後用 PR 合併

## Phase 0：分支與追蹤基礎

- [x] 從 `main` 建立功能分支 `feature/forum-governance-security-modes`
- [x] 建立本工作流程 checklist
- [x] 建立 root 管理的 `feature_*` 功能開關基礎設施
- [x] 既有功能納入開關：chat / community / accounts / appeals / audit / violations / reports / health
- [x] 新工程功能納入開關：identity / account security / governance / modes / snapshot / storage 等
- [x] 後端集中式 feature gate，功能關閉時 API 回 `503`
- [x] 管理 UI 新增「功能」設定頁籤
- [ ] 每次功能批次完成後更新本文件勾選狀態
- [x] 功能分支推送到遠端
- [ ] 建立 PR，等待 CI 與 review

## Phase 1：基礎安全地基

- [x] DB schema migration 系統已存在，版本升級到 v7
- [x] 補齊 `users` 身份治理欄位：`member_level`、`trust_score`、`points`、`reputation`、security flags
- [x] 新增身份/角色 helper：`services/identity.py`
- [x] 管理 API payload 帶出 `member_level` 與治理分數欄位
- [x] `member_level` 建立/修改受 `feature_identity_governance_enabled` 控制
- [x] 補 legacy users schema repair 測試
- [x] 跑完整 pytest：`28 passed`
- [x] 權限 middleware 統一化：role / member_level / status 三層檢查
- [x] Security events event_type 覆蓋盤點與缺口補齊
- [x] CSRF 覆蓋盤點：失敗事件寫入 `security_events`
- [x] Rate limit 覆蓋盤點：阻擋事件寫入 `security_events`
- [x] Session 管理安全盤點：登出 / revoke / idle timeout 寫入 `security_events`

## Phase 2：帳號安全強化

- [x] 密碼強度評分 `password_strength_score` 0-4
- [x] 同帳號暴力破解鎖定：`failed_login_attempts` + `locked_until`
- [ ] 登入裝置管理：session device info / UA / IP
- [ ] 帳號 session API：列出裝置、遠端登出、全部登出
- [ ] 更換密碼後 invalidate 舊 session 驗證補強
- [ ] IP 登入異常記錄與通知事件
- [ ] 對應後端測試

## Phase 3：會員治理與管理員制衡

- [ ] `member_level_rules` schema + API
- [ ] `moderation_proposals` schema + API
- [ ] `moderation_votes` schema + API
- [ ] admin 高風險操作改 proposal + vote
- [ ] root override
- [ ] 版主動作日誌 `moderation_actions`
- [ ] Mod Note `user_mod_notes`
- [ ] 威望明細 `reputation_events`
- [ ] 對應測試

## Phase 4：伺服器模式

- [ ] `server_settings` schema 整理
- [ ] root IP whitelist API
- [ ] `browser_only_mode` middleware
- [ ] maintenance bypass token
- [ ] test mode
- [ ] pre-production 條件檢查
- [ ] superweak sandbox 前置條件確認
- [ ] 對應測試

## Phase 5：Snapshot / Restore / Reset

- [ ] snapshot schema
- [ ] 手動 snapshot API
- [ ] restore API
- [ ] reset API
- [ ] daily auto snapshot
- [ ] Danger Zone 後端安全檢查
- [ ] 對應測試

## Phase 6：健康監控與安全中心

- [ ] readiness light API
- [ ] anomaly light API
- [ ] hash chain 完整性檢查 API
- [ ] DB integrity check dashboard API
- [ ] 對應測試

## Phase 7：論壇核心功能

- [ ] forum_categories schema
- [ ] forum_boards schema 整理
- [ ] posts/comments CRUD 與 soft delete
- [ ] board_moderators 與版主權限
- [ ] newbie 發文 pending_review
- [ ] post_type
- [ ] 置頂 / 鎖文 / 精華
- [ ] view_count 15 分鐘去重
- [ ] 對應測試

## Phase 8：UI 架構重構

- [ ] MainLayout / AdminLayout / AuthLayout
- [ ] 通用 Component：Modal / Toast / LoadingSpinner / Pagination
- [ ] forum 頁面套 MainLayout
- [ ] admin/root 頁面套 AdminLayout
- [ ] services 分層，移除 component 直接 fetch
- [ ] 手機版適配
- [ ] 深色模式

## Phase 9：檢舉 / 申訴 / 通知

- [ ] reports schema + user report API
- [ ] appeals schema + user appeal API
- [ ] report claim 機制
- [ ] notifications schema
- [ ] 通知鈴與通知列表 UI
- [ ] WebSocket 即時通知
- [ ] Email 通知摘要
- [ ] 對應測試

## Phase 10：站內信

- [ ] direct_messages / dm_threads schema
- [ ] DM API：收發 / 已讀 / 軟刪除
- [ ] DM UI
- [ ] blocked_users 阻擋 DM
- [ ] 對應測試

## Phase 11：附件 / 頭像 / CAPTCHA

- [ ] attachments schema
- [ ] 上傳 API：MIME 白名單 + magic bytes
- [ ] 圖片 re-encode 去 EXIF
- [ ] 頭像上傳與裁切
- [ ] Markdown 富文字編輯器
- [ ] CAPTCHA：none / math / image / turnstile
- [ ] 對應測試

## Phase 12：Storage / 相簿

- [ ] user_storage / storage_files / storage_quota_log schema
- [ ] albums / album_files schema
- [ ] 上傳下載 API
- [ ] 回收筒 API
- [ ] 相簿 API
- [ ] 分享連結 API
- [ ] Storage Admin API
- [ ] FileManager UI
- [ ] AlbumManager UI
- [ ] 清理與配額同步 cron
- [ ] 對應測試

## Phase 13：個人化 / 互動 / 社交 / 搜尋

- [ ] 個人主頁
- [ ] 個人簽名檔
- [ ] 自訂稱號審核
- [ ] 成就徽章
- [ ] 在線名單
- [ ] 通知偏好
- [ ] reactions / quote reply / mention
- [ ] edit history / poll / wiki / bounty / accepted answer
- [ ] follow / block / subscriptions / bookmarks / unread states
- [ ] FTS5 全站搜尋
- [ ] tags
- [ ] hot score
- [ ] drafts autosave
- [ ] 對應測試

## Phase 14：進階安全與可選功能

- [ ] spam detection
- [ ] multi-account detection
- [ ] GDPR data export
- [ ] account deletion 30 天 grace period
- [ ] WebAuthn
- [ ] live chat
- [ ] browse history
- [ ] 對應測試
