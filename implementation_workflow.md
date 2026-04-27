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
- [x] 每次功能批次完成後更新本文件勾選狀態
- [x] 功能分支推送到遠端
- [ ] 建立 PR，等待 CI 與 review

## Phase 1：基礎安全地基

- [x] DB schema migration 系統已存在，版本升級到 v7
- [x] 補齊 `users` 身份治理欄位：`member_level`、`trust_score`、`points`、`reputation`、security flags
- [x] 新增身份/角色 helper：`services/identity.py`
- [x] 管理 API payload 帶出 `member_level` 與治理分數欄位
- [x] `member_level` 建立/修改受 `feature_identity_governance_enabled` 控制
- [x] 補 legacy users schema repair 測試
- [x] 跑完整 pytest：`33 passed`
- [x] 權限 middleware 統一化：role / member_level / status 三層檢查
- [x] Security events event_type 覆蓋盤點與缺口補齊
- [x] CSRF 覆蓋盤點：失敗事件寫入 `security_events`
- [x] Rate limit 覆蓋盤點：阻擋事件寫入 `security_events`
- [x] Session 管理安全盤點：登出 / revoke / idle timeout 寫入 `security_events`

## Phase 2：帳號安全強化

- [x] 密碼強度評分 `password_strength_score` 0-4
- [x] 同帳號暴力破解鎖定：`failed_login_attempts` + `locked_until`
- [x] 登入裝置管理：session device info / UA / IP
- [x] 帳號 session API：列出裝置、遠端登出、全部登出
- [x] 更換密碼後 invalidate 舊 session 驗證補強
- [x] bootstrap 預設帳號首次登入強制變更密碼
- [x] IP 登入異常記錄與通知事件
- [x] 對應後端測試

## Phase 3：會員治理與管理員制衡

- [x] `member_level_rules` schema + API
- [x] `member_level_rules` 接入聊天、主題、留言權限檢查（受 `feature_member_governance_enabled` 控制）
- [x] `moderation_proposals` schema + API
- [x] `moderation_votes` schema + API
- [x] admin 高風險操作 proposal + vote 後可執行
- [x] root override
- [x] 基本處分執行：warn / mute / restrict / suspend / delete / downgrade_level / force_password_reset
- [x] 版主動作日誌 `moderation_actions`
- [x] Mod Note `user_mod_notes`
- [x] 威望明細 `reputation_events`
- [x] 會員等級規則對應測試：`37 passed`
- [x] moderation proposal / vote 對應測試：`39 passed`
- [x] governance records / Mod Note / reputation 對應測試：`40 passed`
- [x] Phase 3 UI 與細部整合測試：治理頁籤、提案建立/投票/執行/root override、會員規則摘要；JS syntax + 完整 pytest `93 passed`

## Phase 4：伺服器模式

- [x] `server_modes` schema 整理
- [x] root IP whitelist API
- [x] `browser_only_mode` middleware
- [x] maintenance bypass token
- [x] root 可設定下一次啟動的 listen IP / port，並在 UI 顯示是否需重啟生效
- [x] test mode
- [x] pre-production 條件檢查
- [x] superweak sandbox 前置條件確認
- [x] superweak 進入前自動建立 `before_superweak` snapshot
- [x] superweak 離開時可 restore 或保留 dirty state
- [x] 對應測試：完整 pytest `79 passed`

## Phase 5：Snapshot / Restore / Reset

- [x] snapshot schema
- [x] 手動 snapshot API
- [x] restore API
- [x] reset API：root-only runtime reset，先建立 `pre_reset` snapshot，再清空可重建 runtime 資料
- [x] daily auto snapshot：DB 設定控制，背景 worker 每日最多建立一次 `scheduled` snapshot
- [x] Danger Zone 後端安全檢查
- [x] tar restore path traversal 防護
- [x] restore 前自動 pre_restore snapshot
- [x] 對應測試：完整 pytest `89 passed`

## Phase 6：健康監控與安全中心

- [x] readiness light API
- [x] anomaly light API
- [x] hash chain 完整性檢查 API
- [x] DB integrity check dashboard API
- [x] 對應測試：完整 pytest `72 passed`

## Phase 7：論壇核心功能

- [x] forum_categories schema
- [x] forum_boards schema 整理
- [x] posts/comments CRUD 與 soft delete
- [x] board_moderators 與版主權限
- [x] newbie 發文 pending_review
- [x] post_type
- [x] 置頂 / 鎖文 / 精華
- [x] view_count 15 分鐘去重
- [x] forum_categories 對應測試：社群測試 `8 passed`
- [x] forum_boards schema 對應測試：社群測試 `11 passed`
- [x] posts/comments CRUD 與 soft delete 測試：社群測試 `14 passed`
- [x] board_moderators 與版主權限測試：社群測試 `16 passed`
- [x] Phase 7 回補測試：社群/bootstrapping `20 passed`

## Phase 8：UI 架構重構

- [ ] MainLayout / AdminLayout / AuthLayout
- [ ] 通用 Component：Modal / Toast / LoadingSpinner / Pagination
- [ ] forum 頁面套 MainLayout
- [ ] admin/root 頁面套 AdminLayout
- [ ] services 分層，移除 component 直接 fetch
- [ ] 手機版適配
- [ ] 深色模式

## Phase 9：檢舉 / 申訴 / 通知

- [x] reports schema + user report API
- [x] appeals schema + user appeal API
- [x] report claim 機制
- [x] notifications schema + API：列表 / 單筆已讀 / 全部已讀
- [x] 通知鈴與通知列表 UI
- [ ] WebSocket 即時通知
- [ ] Email 通知摘要
- [x] Phase 9 後端測試：reports / claim / resolve / notifications `11 passed`
- [x] Phase 9 通知 UI 靜態測試
- [ ] Phase 9 realtime / email 對應測試

## Phase 10：站內信

- [x] direct_messages / dm_threads schema
- [x] DM API：收發 / 已讀 / 軟刪除
- [x] DM UI
- [x] blocked_users 阻擋 DM
- [x] Phase 10 後端測試：DM thread / send / read / soft delete / block
- [x] Phase 10 DM UI 靜態測試

## Phase 11：附件 / 頭像 / CAPTCHA

- [x] 隱私分級上傳 Phase 1：`uploaded_files` / `encrypted_file_keys` / `file_scan_results` / `file_access_logs`
- [x] 檔案類型政策 table：`file_type_policies`
- [x] 上傳模式政策：`public_attachment` / `private_scannable` / `e2ee_vault` / `e2ee_vault_with_client_scan`
- [x] 風險分級基礎：`low` / `medium` / `high` / `blocked` / `unknown_encrypted`
- [x] root 功能開關：`feature_privacy_uploads_enabled`
- [x] 雲端硬碟安全政策：scan-before-download / block unclean / high-risk warning / E2EE 不宣稱伺服器掃毒
- [x] storage root / relative path 防穿越 helper 與測試
- [x] 用戶容量 API：目前用量、剩餘容量、會員等級配額、單檔限制、每日上傳限制
- [x] 雲端硬碟 UI：用量條、剩餘容量、風險/掃描/隱私模式統計
- [x] Phase 1 對應測試：完整 pytest `86 passed`
- [x] 本地 ClamAV 掃描抽象層：magic-byte / zip safety / clamav result 寫入 `file_scan_results`
- [x] root 可配置掃描器：啟用、backend、命令路徑、逾時、fail-closed、quarantine、MIME 檢查
- [x] 本地掃描對應測試：upload security `15 passed`
- [x] 軟需求防毒補強：Office macro detection / ZIP 遞迴逐檔檢查 / 可選 YARA / 高風險下載二次確認
- [x] Cloud Drive 附件 schema：`cloud_file_refs` / `file_access_grants` / `announcement_attachment_requests`
- [x] Cloud Drive 上傳 / 既有檔案附加 / 下載權限 API
- [x] 公告附件 request + root approve/reject，核准後轉 root-owned 管理層文件
- [x] 相容 `/api/files/*` API：upload / status / download / E2EE share / revoke
- [x] Cloud Drive 附件 MVP 測試：cloud drive attachments `5 passed`
- [x] 上傳 API：quota / scan pipeline / MIME magic bytes
- [x] 圖片 re-encode 去 EXIF
- [x] 頭像上傳與裁切
- [x] Markdown 富文字編輯器
- [x] CAPTCHA：none / math / image / turnstile
- [x] 對應測試

## Phase 12：Storage / 相簿

- [x] user_storage / storage_files / storage_quota_log schema
- [x] albums / album_files schema
- [x] 上傳下載 API
- [x] 回收筒 API
- [x] 相簿 API
- [x] 分享連結 API
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
