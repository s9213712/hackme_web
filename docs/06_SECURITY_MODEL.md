# 06 Security Model

一句話說明：這份文件用部署者與 root 能消化的層級，整理 `hackme_web` 目前的安全模型、保護邊界與已知限制。

## 設計目的

原本安全相關資訊散在 `SECURITY.md`、Server Mode v2 文件、pentest 文件與
`For_developer.md` 裡。這份文件把部署時需要先理解的安全原理集中起來，
讓人知道「哪些保護已存在、哪些是營運責任、哪些不能想當然」。

## 使用方法

部署或上線前，至少先確認以下主題：

1. 密碼 / session / CSRF
2. rate limit / IP blocking / XFF trust
3. audit chain / integrity guard
4. server modes / snapshot / restore 邊界
5. feature flags 是否讓高風險功能在錯誤模式下暴露
6. Cloud Drive / video 的 plaintext 與加密信任邊界

## 原理

### 認證與 session

- 密碼使用 Argon2id
- session token 透過 HttpOnly cookie 維持
- session 有 TTL，敏感時機會 rotate CSRF token

### CSRF 與寫入保護

- 所有寫入 API 預設要求 CSRF
- `apiFetch()` 會帶 `X-CSRF-Token`
- 缺 token 會回受控 `403`，不是 HTML traceback

### 權限與治理

- root / manager / user / anonymous 有明確 API 邊界
- member level 會進一步限制聊天、論壇、治理等模組
- 高風險操作還要 confirmation string，不只靠登入狀態

### Audit / Integrity

- audit chain 讓關鍵事件可追溯
- Integrity Guard 比對受保護檔案與 manifest，不自動接受未授權變更
- `ROOT_INTEGRITY_SIGNING_KEY` 屬部署 secret，不應進 Git

### Server Mode 與恢復邊界

- `test`、`internal_test`、`dev_ready`、`production`、`maintenance`、
  `incident_lockdown`、`superweak` 各自有不同保護層
- snapshot restore、PointsChain recovery、runtime reset 是不同工具，不可混用概念

### Cloud Drive / 影音加密邊界

不是所有「加密」模式都等於端到端加密。部署者與 root 需要先分清楚：

| Mode | Server/root 可讀明文 | 磁碟靜態資料 | 掃描 / 預覽 / 下載 | 信任假設 |
| --- | --- | --- | --- | --- |
| `standard_plain` | 可以 | 明文 | 最完整 | 信任 server 與 runtime |
| `server_encrypted` | 可以 | 密文 | 由 server 暫時解密處理 | 降低磁碟 / 備份暴露，但不是 zero-knowledge |
| `e2ee` | 不可以 | 密文 | 僅瀏覽器端解密 | 對 server / root / runtime engineer 也隱藏明文 |

- `server_encrypted` 的意思是「磁碟上盡量用密文保存」，不是「root 看不到明文」。
- strict `e2ee` 才是使用者明文不交給 server 的模式。
- `server_encrypted` 目前仍需要 server-side path 才能做掃描、預覽、plaintext download；因此它保護的是 at-rest exposure，不是 runtime zero-knowledge。
- 如果使用者需要「即使 root / runtime engineer 也看不到內容」，必須選 strict `e2ee`。
- 如果選 strict `e2ee`，也要接受遺失使用者密碼後 server 無法幫忙復原。

更完整的 runtime trust boundary 請看：

- [ENCRYPTION_RUNTIME_BOUNDARY.md](ops_boundaries/ENCRYPTION_RUNTIME_BOUNDARY.md)
- [WEB.md](WEB.md)
- [VIDEO_PLATFORM.md](video/VIDEO_PLATFORM.md)

## 失敗情境與提示

- `csrf_invalid`：
  先重新拿 `/api/csrf-token`，再檢查是不是登入/改密碼/權限變動後仍用舊分頁。
- 代理層開了 `X-Forwarded-For` 但 app 不該信任外來來源：
  請只設定自己的 `TRUSTED_PROXY_IPS`。
- 啟動時 Integrity Guard 發現 modified / added / deleted：
  先當成高風險 finding，不要直接更新 manifest。
- production gate 過不了：
  先看是 server mode 核心安全、QA evidence、還是整站模組驗收缺項。

## 測試方式

- [security/FUNCTIONAL_PERMISSION_PENTEST.md](security/FUNCTIONAL_PERMISSION_PENTEST.md)
- [security/PENTEST.md](security/PENTEST.md)
- [security/SERVER_MODE_V2_RED_TEAM_PLAYBOOK.md](security/SERVER_MODE_V2_RED_TEAM_PLAYBOOK.md)
- [SERVER_MODE_V2_TEST_PLAN.md](server_mode_v2/SERVER_MODE_V2_TEST_PLAN.md)
- [11_QA_TESTING.md](11_QA_TESTING.md)

## 相關文件連結

- [SECURITY.md](SECURITY.md)
- [security/PENTEST.md](security/PENTEST.md)
- [security/FUNCTIONAL_PERMISSION_PENTEST.md](security/FUNCTIONAL_PERMISSION_PENTEST.md)
- [SERVER_MODE_V2_PROFILE_MATRIX.md](server_mode_v2/SERVER_MODE_V2_PROFILE_MATRIX.md)
- [SERVER_MODE_V2_TEST_PLAN.md](server_mode_v2/SERVER_MODE_V2_TEST_PLAN.md)
- [09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md)
