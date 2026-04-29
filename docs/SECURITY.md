# Security Measures — hackme_web

## 目的與邊界
本文件記錄目前已啟用的保護，並保留仍需持續改善的項目。

## 密碼與 Session
- **Argon2id**：`time_cost=3`、`memory_cost=65536KB`、`parallelism=4`，密碼雜湊不儲存明文。
- **Fernet**：加密並簽章 session token（`session_token` 僅存於 HttpOnly cookie）。
- **Session TTL**：預設 4 小時。
- **登出**：刪除 session 與 csrf cookie。

## CSRF 與請求保護
- 登入採一次性 token（DB 驗證 + 消費）。
- 一般 `GET` 採 `@require_csrf_safe`，保留短期可用 token。
- 登出與所有修改操作需 `POST` + CSRF。

## 速率與封鎖
- 註冊：60 秒 10 次
- 登入：60 秒 30 次
- 過多登入失敗會寫入 `security_events`，可觸發封鎖。
- 環境變數 `IP_BLOCKING_ENABLED=true` 時啟用封鎖。

## 反列舉與時序對策
- `USER` 與 `bad password` 回應保持一致訊息。
- `fake hash` + 固定延遲抖動，降低 timing oracle。

## 審計與完整性
- 審計日誌以 `secure_audit` 寫入 hash-chain。
- 違規計次也維持 hash-chain，支援 integrity 驗證。
- 兼容 `logs/audit.log` fallback（舊資料可視）
- Integrity Guard 會以簽章 `integrity_manifest.json` 監控受保護程式檔。
  啟動與 root rescan 會比對 modified / added / deleted，建立
  `integrity_findings`，不會自動更新 manifest。
- root approve 必須輸入 `APPROVE INTEGRITY UPDATE`；approve / reject /
  ignore 都寫入 audit log。
- `ROOT_INTEGRITY_SIGNING_KEY` 應保存於部署 secret，不可提交到 git。
  若 manifest 簽章錯誤，系統會建立 high risk finding。
- Integrity Guard 可偵測未授權修改，但不能取代 git、CI/CD、備份或主機
  安全；已完全取得主機 root 的攻擊者仍可能干擾 runtime。

## 輸入驗證
- 帳號：3–32 字元，`[a-zA-Z0-9_-]`
- 密碼：8–128 字元，需含大小寫與符號
- 個人欄位有對應格式驗證（`real_name`、`id_number`、`birthdate`、`phone`）

## HTTP 安全
- Flask-Talisman：CSP, HSTS, referrer policy 等
- 限制 `X-Frame-Options`, `nosniff`, `nosniff`, `X-Permitted-Cross-Domain-Policies`

## 已知限制與待做
- 管理帳號行為仍未完整模組化，後端程式集中於 `server.py`。
- 建議再進一步加入「自動化 pre-push 架構掃描」與「程式拆分」流程。
