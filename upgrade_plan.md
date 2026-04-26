# Flask 安全與資料層遷移計劃（待後續執行）

> 需求：先保存規劃到檔案，並按照優先順序逐步落地。

## 進度（2026-04-26）

- 已完成：短期上線前清單 (1) 安全環境變數、(2) 服務啟動模式、(3) 已有保護保留機制、(4) 權限邏輯回查。
- 本輪已啟動：第2階段「資料層轉型」—`system_settings` 轉入 `system_settings` table、legacy JSON 寫盤自動匯入、匯入腳本建立。
- 本輪已完成：SQL schema 版本化（`schema_migrations`、版本追蹤、啟動時依版本自動套用）。
- 待進行：自動告警與治理報表模組（監控儀表板）。

## 一、目前結論

1. Flask 本身可用，但需要以「應用安全實作」補齊（Session/CSRF/輸入驗證/授權/安全標頭/部署方式）。
2. 目前若使用檔案（JSON + log）存放使用者/封鎖/速率資料，長期不建議；建議先保留為 fallback，逐步遷移到 DB。

---

## 二、短期上線前清單（立即可執行）

1. 安全環境變數
   - `IP_BLOCKING_ENABLED=true`
   - `SESSION_COOKIE_SECURE=true`
   - `SESSION_COOKIE_HTTPONLY=true`
   - `SESSION_COOKIE_SAMESITE=Strict`
   - `SECRET_KEY` 使用高熵值且固定於環境
2. 服務啟動模式
   - 生產環境禁用 debug
   - 使用反向代理 + HTTPS
   - 建議使用 WSGI（如 gunicorn）取代 Flask 開發 server
3. 既有保護維持
   - CSRF double-submit / token
   - 登入失敗鎖定、IP 封鎖與時間常數化回應
   - 參數化 SQL 查詢、輸入白名單驗證
4. 權限核對
   - `/api/me`、`/api/login`、`/api/logout`、`/api/admin/*` 權限與角色邏輯再抽檢一次

---

## 三、資料層轉型（暫存為下階段）

目標：從「以檔案為主」遷移到「資料庫為主」，先保留兼容接口再切換。

1. 新增 DB 架構（先採用 SQLite）
   - `users`：使用者資料（帳號/暱稱/真實姓名/身分證/生日/電話/角色/狀態/封鎖時間）
   - `user_passwords`：密碼雜湊與建立時間
   - `audit_logs`：操作/登入/封鎖/變更紀錄
   - `login_failures`：IP 失敗次數快取
   - `rate_limits`：IP 時段計數
   - `settings`：系統參數（allow_register、max_fail 等）
2. 遷移策略
   - 提供一次性匯入腳本：`fail_log.json`、`blocked_ips.json`、`rate_limit.json`、`audit.log` → DB
   - 匯入前後做筆數對帳（成功/失敗分別記錄）
3. 過渡期
   - API 保持既有行為
   - 讀寫先「DB 主、JSON 備援」或反過來（視可回滾要求）

---

## 四、後續強化（中長期）

1. 監控與可觀測性
   - 統一 request id
   - 管理操作紀錄補上操作人、結果、時間、來源 IP
2. 權限治理
  - 角色 `super_admin`/`manager`/`user` 明確測試案例
  - 權限變更要求稽核
3. 測試與上線流程
  - 設計自動化 smoke test（登入/註冊/封鎖/管理員新增）
  - 上線前安全回歸測試腳本
4. 正式環境升級路徑
   - 規模擴展時改用 PostgreSQL
   - 加入 migration 工具（例如 Alembic）

---

## 五、後續執行順序（你可直接照做）

1. 先完成上線前安全變數開關與啟動方式（今晚可做）。
2. 再做 DB schema + 匯入腳本（下一個工作週）。
3. 最後做 API 切 DB、補齊測試與部署腳本。

---

## 六、備註

- 目前不會在這個步驟直接改動業務流程，先作為「待執行任務清單」。
- 之後要我接續時，我可直接以此文件為依據，按「第 2 階段」逐項實作並提交 commit。

## 七、上線前重要提醒（強制）

1. 開機前先恢復 IP 封鎖設定：
   - 設定 `IP_BLOCKING_ENABLED=true`
   - 確認若有代理，`USE_XFF=true` 且 `TRUSTED_PROXY_IPS` 設定正確
2. 確認登出機制與 session 銷毀行為一致：
   - 登出後即時轉回登入畫面
   - 刷新頁面不應自動恢復登入
3. 上線前再做一次最小驗證：
   - 一般帳號登入/登出
   - 管理者封鎖與解除封鎖
   - 管理員新增帳號（含密碼再次確認）
