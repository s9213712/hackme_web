# hackme_web

[English README](README.md)

![status](https://img.shields.io/badge/status-active-2ea043)
![backend](https://img.shields.io/badge/backend-Flask-000000)
![database](https://img.shields.io/badge/database-SQLite-0f6ab4)
![security](https://img.shields.io/badge/focus-auth%20%2B%20RBAC%20%2B%20audit-b31d28)

`hackme_web` 是一個以安全性為核心的 Flask Web 應用，專門用來研究
認證、RBAC、審計能力與實務部署中的防護收斂。

這個專案刻意設計在「教學系統」與「偏正式服務」之間：

- 它有真實的帳號、審核、聊天、違規與審計流程
- 它維持小型、單機、可直接理解的部署模型
- 它強調防護機制與失敗模式的可觀測性

## Fast Start

如果你想用最短路徑把本機服務跑起來：

```bash
python3 -m pip install -r requirements.txt
python3 server.py
```

然後打開：

```text
https://127.0.0.1:5000/
```

預設本機帳號：

- `root / root` — `super_admin`
- `admin / admin` — `manager`
- `test / test` — `user`

## 為什麼有這個專案

很多示範型登入系統只做到 login、logout 與少數保護路由。

這個 repo 的價值在於，它還包含：

- 基於角色的帳號管理
- 需要審核的新帳號註冊流程
- 違規計點與申覆流程
- 聊天與訊息檢舉審核流程
- 可驗證是否遭竄改的審計紀錄
- 可在攻防測試中實際操作的系統設定與運維控制面

## 專案定位

`hackme_web` 不是完整的大型產品平台。

它適合用在這些場景：

- 想要一個精簡但有真實安全邊界的 Flask 練習目標
- 想測 CSRF、session、RBAC、moderation、audit 等實戰流程
- 想有一個可本機自建、可逐步補強的防守方樣本
- 想研究小型服務在真實業務狀態機下的安全設計

## 核心能力

### 認證與 Session

- Argon2id 密碼雜湊
- 登入失敗追蹤與可選的 IP 封鎖
- 伺服器持久化的 CSRF token 驗證
- 加密 session token + DB 查驗
- logout 後 session 失效與 token 旋轉

### 授權模型

- `super_admin`、`manager`、`user` 三層角色
- 所有管理路由都做 server-side RBAC 檢查
- 使用者可自助修改個資，但受欄位白名單限制
- 新註冊帳號須經審核後才能正式登入

### Moderation 與狀態流程

- 違規點數追蹤
- 使用者申覆與管理審核
- 訊息檢舉與管理審核
- 帳號角色/狀態轉換的政策限制

### 審計與完整性

- SQLite 內的 tamper-evident audit chain
- 本機 `anchors/` 錨點快照
- 安全事件、登入失敗、審核動作的記錄能力

## 角色模型

| 角色 | 目的 | 目前權限 |
|---|---|---|
| `super_admin` | 完整控制面 | 帳號生命週期、設定、審核、審計、伺服器操作 |
| `manager` | 日常營運與 moderation | 查看帳號、審核註冊、處理一般用戶層級的管理動作 |
| `user` | 一般使用 | 登入、改個資、聊天、送檢舉、送申覆 |

## 安全控制

目前已有的防護包括：

- Argon2id 密碼雜湊
- 統一化的登入失敗訊息
- 公開敏感流程的 rate limit
- 寫入路由 CSRF 驗證
- authenticated write 的一次性 CSRF token 消耗
- 資料庫支援的 session 驗證
- Flask-Talisman 提供的 CSP
- audit chain 完整性驗證
- server-side 角色授權檢查

## 安全測試覆蓋

已做過的測試類型包括：

- CSRF：
  missing token、invalid token、wrong header name、cross-session token、replay
- Session：
  login rotate、logout invalidation、old cookie reuse、fixation、多重登入
- Authorization：
  一般使用者對 admin route、review route、settings route、moderation route 的越權測試
- Mass assignment：
  top-level 與 nested 權限欄位偷渡
- IDOR / BOLA：
  self、peer、admin、malformed id、large id
- State machine：
  register review、appeal、message report、duplicate submit、review replay
- Injection：
  SQLi 探測、log payload、管理頁顯示路徑檢查

目前結果摘要：

- 尚未確認可成功的一般使用者提權路徑
- 尚未確認成功的 logout 後 session replay
- 尚未確認成功的 session fixation
- 尚未確認成功的 SQL injection
- `self-update` 的 CSRF lifecycle 問題已被定位並對前端 token refresh 流程做穩定化修補

## API Surface

### 公開 API

- `GET /api/csrf-token`
- `POST /api/register`
- `POST /api/login`
- `POST /api/logout`
- `GET /api/me`

### `manager` 以上

- `GET /api/admin/users`
- `GET /api/admin/violations`
- `GET /api/admin/audit`

### `super_admin`

- `POST /api/admin/users`
- `GET/PUT/DELETE /api/admin/users/<id>`
- `POST /api/admin/users/<id>/promote`
- `POST /api/admin/users/<id>/demote`
- `POST /api/admin/users/<id>/violation`
- `POST /api/admin/users/<id>/reset-violations`
- `POST /api/admin/users/<id>/block`
- `GET/PUT /api/admin/settings`
- `GET /api/admin/environment`
- `GET /api/admin/health`
- `POST /api/admin/restart`
- `GET /api/admin/appeals`
- `POST /api/admin/appeals/<id>/review`
- `GET /api/admin/message-reports`
- `POST /api/admin/message-reports/<id>/review`

## Repository Layout

| 路徑 | 用途 |
|---|---|
| `server.py` | 主 Flask 後端與路由層 |
| `public/index.html` | 前端結構 |
| `public/app.js` | 前端應用邏輯 |
| `public/styles.css` | 前端樣式 |
| `scripts/run_prod.sh` | production 啟動腳本 |
| `scripts/pre_push_scan.sh` | 本機 pre-push 檢查腳本 |
| `scripts/migrate_legacy_json.py` | 舊 sidecar 資料匯入工具 |
| `database/` | 本機 SQLite 資料目錄 |
| `logs/` | runtime log 目錄 |
| `anchors/` | 本機 audit head 錨點快照 |

## 設定模型

目前設定來源分三層：

1. 環境變數
2. DB-backed `system_settings`
3. `server.py` 內的預設值

這表示舊式 JSON 設定檔不再是主要真相來源。

### Production 範本

使用內建範本：

```bash
cp .env.production.example .env
```

然後填入真實值：

- `SESSION_SECRET`
- `CSRF_SECRET_KEY`
- 若使用 reverse proxy，補上代理相關設定

## Production 啟動

```bash
cp .env.production.example .env
source .env
./scripts/run_prod.sh
```

範本預設已開啟較合理的 production 選項，例如：

- `FORCE_HTTPS=true`
- `SESSION_COOKIE_SECURE=true`
- `SESSION_COOKIE_HTTPONLY=true`
- `SESSION_COOKIE_SAMESITE=Strict`
- `IP_BLOCKING_ENABLED=true`

## 資料與遷移說明

專案早期曾使用多個 JSON sidecar 檔案保存部分狀態，現在主體已轉入
SQLite。

仍保留的手動工具：

```bash
python3 scripts/migrate_legacy_json.py
```

用途是：

- 受控的一次性 legacy 匯入
- 疑難排查
- 相容性補救

## 維運說明

- `server.py` 仍是目前主要集中點
- 下一步值得做的是把 routing、auth、moderation、audit 拆成較小模組
- 本機攻擊測試產物刻意不納入 Git 追蹤
- secret、seed、runtime state 檔案刻意不納入 Git 追蹤

## 建議的本機工作流程

日常開發：

```bash
python3 server.py
```

準備發布前：

```bash
./scripts/pre_push_scan.sh
```

## 目前最值得投入的工程方向

- 拆分 `server.py`
- 持續擴充 RBAC 與 workflow regression tests
- 持續補強 moderation 與 audit 的顯示路徑
- 在真實 reverse proxy 後再驗一次 deployment-layer 行為

## 授權與使用情境

本 repo 只適合用於經授權的本機開發、安全測試與防守工程研究。不要把
這裡的攻擊思路或測試方法用在非你擁有、或未明確授權的系統上。
