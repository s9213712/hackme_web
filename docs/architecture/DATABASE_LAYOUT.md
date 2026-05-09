# Database Layout

本文件描述 **目前實作中** 的資料庫切分，而不是未來理想狀態。

## 現況總覽

目前 runtime 內有 5 類主要 DB / DB-like 持久化：

1. `runtime/database/database.db`
2. `runtime/database/auth.db`
3. `runtime/database/audit.db`
4. `runtime/database/control.db`
5. `runtime/games/models/chess_experiment.db`

## 1. `runtime/database/database.db`

主業務 DB，負責大多數網站功能。

目前放在這裡的資料大致包含：

- `users`
- `user_passwords`
- 一般站台設定與 feature flags
- 論壇 / 聊天 / 通知 / 申覆
- Cloud Drive / 影片 / 分享 / E2EE metadata
- ComfyUI workflow / 一般 AI 功能資料
- Trading / Points / Snapshot / Server Mode 等尚未拆出的主資料

### 角色

- 預設主資料庫
- 目前仍承載最多業務表
- 尚未拆出的模組都在這裡

### 風險

- 容易成為 SQLite 寫入熱點
- 若背景 worker、交易、snapshot、server mode、聊天室同時寫入，最容易互鎖

## 2. `runtime/database/auth.db`

Auth hot-path 專用 DB。

目前已拆出的表：

- `csrf_tokens`
- `captcha_challenges`
- `login_attempts`
- `sessions`

### 角色

- 專門承接登入 / session / CSRF / captcha 這些高頻、短生命週期資料
- 降低登入與 `/api/me` 被主業務 DB 鎖住的機率

### 為什麼先拆它

這些資料具備共同特徵：

- 高寫入頻率
- 生命周期短
- 和主業務內容弱耦合
- 一旦被鎖，使用者會直接感知成「登入失敗 / 500 / 沒反應」

### 目前已搬走的熱路徑

- `/api/csrf-token`
- `/api/login`
- `/api/logout`
- `/api/session/idle-timeout`
- `/api/account/sessions*`
- captcha challenge / verify

## 3. `runtime/database/audit.db`

Audit 專用 DB。

目前已拆出的主表：

- `secure_audit`

### 角色

- 保存安全稽核鏈
- 避免一般業務寫入拖慢 audit append
- 降低 root 後台 / 安全中心 / 審計鏈查詢與主業務熱寫入互鎖

### 資料生命週期

- 長期保留
- 屬於 append-heavy / read-forensic 的資料
- 不應與短生命週期 session/captcha 混在一起

## 4. `runtime/database/control.db`

Control-plane 專用 DB。

目前已拆出的主表：

- `server_modes`
- `server_checkpoints`
- `mode_switch_logs`
- `security_keys`
- `production_entry_reports`
- `incident_reports`
- `security_profiles`

### 角色

- 保存 server mode / production gate / incident / security key 這類高風險控制面資料
- 降低 root 後台、launch-check、production gate 與主業務 DB 熱寫入互鎖
- 保持模式切換、production report 驗證、incident lock 這類控制流與一般論壇/聊天/交易寫入解耦

### 為什麼現在要拆它

這些資料具備共同特徵：

- 高風險控制面
- rollback 邊界和一般業務資料不同
- live root 後台會頻繁讀取
- 一旦被鎖，使用者會直接感知成「上線前檢查讀取失敗 / 模式切換 500 / 無法進 production」

### 注意

- `control.db` 目前是 production gate 與 server mode 的權威來源
- 為了相容舊讀取路徑，部分 mode state 仍會 best-effort mirror 回 `database.db`
- 實際判定應以 `control.db` 內容為準
- `control.db` 的 schema ensure 現在在啟動期與首次開檔時完成，不應再在
  `production gate` / `server mode` request path 內反覆做 DDL；這是 2026-05-09
  live 驗證用來消除 `launch-check` / `production enter` 自鎖的重要修正

## 5. `runtime/games/models/chess_experiment.db`

西洋棋 `exp1` 的學習 DB。

### 角色

- 不是整站通用 DB
- 只服務西洋棋 `experiment` / `exp1`
- 保存搜尋器的 learning bias / 經驗記憶

### 特性

- 與主網站登入、交易、論壇完全不同生命週期
- 應視為遊戲模型資產，而不是網站主資料

## 為什麼沒有一次拆很多 DB

目前採取的是 **風險導向、逐步拆分**：

先拆：

- 最常互鎖
- rollback 邊界清楚
- 對使用者體感影響最大的熱區

所以順序先是：

1. `audit.db`
2. `auth.db`
3. `control.db`

而不是一開始就把所有模組一次拆散。

## 下一個最值得拆的熱區

依目前觀察，下一個最值得拆的是 **trading / points / storage-media / forum-social** 這類仍在主 DB 內的熱區。

其中優先順序大致是：

1. trading / liquidation / bots
2. points ledger / chain
3. storage / media / share metadata
4. forum / social / notification

原因：

- 這些模組仍和主 DB 其他熱寫入共用同一把 SQLite writer lock
- 其中 trading / points 對安全與金流邊界影響最高
- storage / media / social 則較偏容量與 I/O 壓力問題

## 不要誤解成已經完全拆完

目前 **還沒有** 完成 trading / pointschain / forum / storage / AI workflow 的全面獨立 DB。

目前只是先把最常造成體感故障與控制面互鎖的三塊熱區拆開：

- `auth`
- `audit`
- `control`

其餘 DB split 仍會依：

- 功能耦合
- 風險等級
- rollback 邊界
- 資料生命週期

逐步往下做。

## 2026-05-09 live production gate 驗證結果

這次 `server mode / production gate` live 驗證已確認：

- `auth.db` 與 `control.db` 拆分後，`/api/csrf-token`、`/api/login`、
  `/api/me`、`/api/root/server-mode/requirements`、`/api/root/production/enter`
  可在隔離 `/tmp` runtime 下連續執行，不再因 request-path schema ensure 而自鎖。
- `control.db` 內的 verified production reports 才是 gate 權威來源；
  filesystem auto-detect 只輔助顯示，不可單獨放行。
- verified 但 `target_commit=old/fake` 的 13 份報告，live server 會回
  `target_commit_mismatch` 並拒絕進入 production。
- 只有 13 份 verified 且 `target_commit / target_branch / server_mode` 全匹配時，
  live `production enter` 才會成功。

完整流程與證據請看：

- [docs/server_mode_v2/03_production_gate_playbook.md](../server_mode_v2/03_production_gate_playbook.md)
- [docs/server_mode_v2/04_production_gate_validation_report.md](../server_mode_v2/04_production_gate_validation_report.md)
