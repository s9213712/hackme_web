# 系統評測 P1–P6 修補摘要

**日期**: 2026-05-13
**分支**: `03b.Comfyui`
**範圍**: 對 hackme_web 全站做系統級評測後，按優先順序執行 P1–P6 修補
**測試環境**: 全程 `/tmp/hackme_web_pytest_*` 隔離，repo 工作樹未被執行時 runtime 污染
**棋力相關**: 嚴格採用「**僅加法**」策略，未修改任何 `services/games/chess_*.py` 既有檔，未修改 `services/games/models/*`，未與用戶尚未提交的 chess_pv / chess_nnue / chess_tactical_safety 等改動衝突

---

## 一覽

| 優先 | 主題 | 狀態 | 涉及檔案 | 新增測試 |
|---|---|---|---|---|
| P1 | 設定分群 + 依賴 + 二次確認 | ✅ 完成 | `services/platform/settings.py`、新檔 `settings_metadata.py`、`routes/system_admin_sections/settings_routes.py` | 10 例 |
| P2 | 棋力 opening book（純加法） | ✅ 完成 | 新檔 `services/games/chess_opening_book.py`、`routes/games.py` | 9 例 |
| P3 | APR 顯示 quantize（去掉 9.9999999） | ✅ 完成 | `services/trading/accounting/funding_pool.py` | 4 例 |
| P4 | 論壇 thread/post 計數 N+1 消除 | ✅ 完成 | `routes/community.py` | 3 例 |
| P5 | UI 動畫擴充（容量水波 / 熱度光暈 / 卡片 tilt 等） | ✅ 完成 | `public/styles.css`、`public/index.html`、`public/js/35-drive.js` | — (純樣式) |
| P6 | 腳本互動 UX（進度條 / 引導 / 抗死循環） | ✅ 完成 | 新檔 `scripts/_progress.py` | 9 例 |

**測試結果**：每項修補的新增測試 + 受影響領域既有測試 (`tests/platform/`、`tests/trading/`、`tests/community/`、`tests/games/test_chess_opening_book.py`、`tests/snapshots/test_snapshots.py`、`tests/security/auth/test_access_controls.py`) 全綠。

棋力套件中已存在的 2 例失敗 (`test_experiment_resign_collects_replay_without_online_learning`、`test_experiment_pv_rule_aware_fusion_preserves_special_rule_subtype`) **在我修補前後一致存在**，已驗證屬於 ongoing 的 chess_pv 研究分支未提交改動，與本次修補無關。

---

## P1 — 設定分群 + 依賴 + 二次確認

### 問題
`/api/admin/settings` 回傳 120 個 key，UI 是平面平鋪，缺：
- 分群與每群一句白話說明
- 哪些是「危險設定」（關掉會降低系統安全性）
- 對危險變更的二次確認

repo 本來就有 `FEATURE_DEPENDENCY_RULES` 與 `find_feature_dependency_violations`，但只覆蓋 `feature_*` 子集，且沒有顯示元資料 API、也沒有對 `audit_chain_enabled` 等高敏感 toggle 做 confirm gate。

### 修補

1. **`services/platform/settings_metadata.py`（新檔）**
   - `SETTING_GROUPS`: 14 個分群（安全與稽核、會話與帳號復原、維護模式、Server 綁定 / SSL、雲端硬碟、Snapshot、外觀、模組存取最低角色、功能總開關使用者端、功能總開關管理端、ComfyUI、影音 / 打賞、安全告警門檻、聊天規則）+ 自動 fallback 群 `other` 確保**所有** `DEFAULT_SETTINGS` 都會出現在元資料中
   - `SETTING_DETAILS`: 每個 key 的 label + 一句說明
   - `DANGEROUS_SETTINGS`: 11 個高敏感 key，標 `side: enable|disable|either|value` 與 warning 句
   - `setting_groups_payload()`: 序列化整份元資料供前端
   - `find_dangerous_changes()`: 找出 ``updates`` 中需要確認的變更

2. **`services/platform/settings.py`（修改）**
   - 新增 `class DangerousChangeBlocked` 例外（內含 ``risky`` 結構化資料）
   - 新增 `enforce_dangerous_confirm(current, data)` 由 HTTP 層呼叫
   - **刻意不在 `save_settings()` 內部 enforce** — 內部呼叫者（`test_for_develop.sh`、`server_mode` 自動化、`security_runtime` 自動 reseal、snapshot 自動日期戳）走自家路徑，HTTP 路由才走 gate

3. **`routes/system_admin_sections/settings_routes.py`（修改）**
   - 在 `PUT /api/admin/settings` 與 `PUT /api/admin/features` 進入 `save_settings` 前呼叫 `enforce_dangerous_confirm`，攔下後回 400：
     ```json
     {"ok": false, "error": "dangerous_change_blocked",
      "msg": "以下設定屬於高敏感變更，需在請求中加上 dangerous_confirm 才會生效：…",
      "dangerous_changes": [{"key": "...", "label": "...", "transition": "disable", "warning": "..."}]}
     ```
   - 新增 `GET /api/admin/settings/metadata` 端點，回 `{groups: [...], dangerous_keys: [...]}` 供前端整版重畫
   - `admin_features` 路由刻意只把 `feature_*` 子集送進 gate（其他無關 key 不影響 gate 邏輯）

4. **既有測試調整**
   - `tests/security/auth/test_access_controls.py::test_root_can_configure_server_ssl_setting_with_restart_hint` 改寫成驗證「先被 gate 擋下、補 `dangerous_confirm` 後通過」的兩段流程

### Dangerous toggle 清單

| Key | Side | Why |
|---|---|---|
| `audit_chain_enabled` | disable | Audit log 失去可竄改偵測 |
| `integrity_guard_enabled` | disable | 檔案竄改不再自動偵測 |
| `ip_blocking_enabled` | disable | 暴力嘗試不會被自動封 |
| `login_violation_enabled` | disable | 重複失敗不再累積違規分數 |
| `production_single_account_ip_lock_enabled` | disable | 帳號可被異地登入 |
| `production_single_ip_account_lock_enabled` | disable | 多帳號可同 IP 上線 |
| `server_ssl_enabled` | disable | 流量改走明文 HTTP |
| `allow_register` | enable | 任何訪客可註冊 |
| `maintenance_mode` | enable | 立即擋下所有非 bypass 流量 |
| `root_ip_whitelist_enabled` | enable | 白名單若不含目前 IP，root 會被鎖在外面 |
| `browser_only_mode_enabled` | enable | curl/wget/監控腳本全擋 |

### 客戶端使用方式
```http
PUT /api/admin/settings
{
  "server_ssl_enabled": false,
  "dangerous_confirm": "server_ssl_enabled"
}
```
也接受 list 或 dict 形式：`"dangerous_confirm": ["audit_chain_enabled", "ip_blocking_enabled"]`。

---

## P2 — 棋力 opening book（純加法）

### 問題
原評測時看到 `experiment 5:NNUE` 對 `1.e4` 回 `a5`，因為棋引擎沒有 opening book，全靠淺深度 NNUE eval。

### 「不影響其他人」設計
- `services/games/chess_*.py` **任何檔都沒動**（chess_engine / chess_nn / chess_dl / chess_pv / chess_pv_guarded_overlay / chess_nnue / chess_search / chess_tactical_safety 全部 untouched）
- `services/games/models/*` **未動**
- `docs/games/chess_debug/*` **未動**
- 只新增 `services/games/chess_opening_book.py` 與 `tests/games/test_chess_opening_book.py`
- 在 `routes/games.py` `choose_computer_move()` 第一行**前置**呼叫 book；book 命中就用，未命中走原本邏輯

### 實作要點
- **Keyed by EPD**（FEN 前 4 欄位）— 對 halfmove / fullmove 計數穩定
- ~60 個 position：1.e4 的主要應對 (e5, c5, e6, c6, d5, d6, g6, Nf6) × 接下來 1-3 ply、1.d4 (d5, Nf6 + Indian variations, f5)、1.c4 / 1.Nf3 / 1.b3
- 每行附 weight，random 加權挑選 → 開局有變化但都是主流
- `easy` 難度 **不**走 book（保留新手練習的弱開局練習價值）
- defensive：dict / 非法 / unknown side 全回 `None` 不會 crash

### 驗證
```
$ pytest tests/games/test_chess_opening_book.py
.........  9 passed
```
包含「絕不對 e4 回 a5」、「out-of-book 時乾淨回 None」、「所有 book 移動都合法」三類測試。

---

## P3 — APR 顯示 quantize

### 問題
`base_apr=10.0`、utilization=0 時 `effective_interest_apr_percent` 顯示 `9.9999999` — 來自 `daily_from_apr(10) → 0.02739726 → apr_from_daily → 9.9999999` 的 Decimal quantize 漂移。

### 修補
`services/trading/accounting/funding_pool.py` 新增 `_effective_apr_display()`:
- 當 `scaled_rate == base_rate`（沒被 pressure 放大）→ 直接回傳 `base_apr_percent`，**完全跳過 round-trip**
- 否則用 round-trip，但結果 quantize 到 6 位（漂移在 1e-7 等級，6 位顯示綽綽有餘）

### 驗證
```
$ pytest tests/trading/test_funding_pool_payload.py
....  4 passed
```
新加 4 例：零利用率回基礎值、部分利用率高於基礎、零 pressure 等同基礎、零 base 仍為 0。
既有 244 例 trading 測試全綠。

---

## P4 — 論壇 thread/post 計數 N+1 消除

### 問題
`/api/community/boards` GET：先抓 N 個 board，再對每個 board 跑兩個 subquery (`COUNT(forum_threads)`、`COUNT(forum_posts)`) — 共 1 + 2N 個 query。

### 修補
`routes/community.py` `community_boards()` 改寫為單一 CTE：
```sql
WITH thread_stats AS (
    SELECT board_id, COUNT(*) AS thread_count
    FROM forum_threads WHERE is_deleted=0 GROUP BY board_id
),
post_stats AS (
    SELECT t.board_id, COUNT(*) AS post_count
    FROM forum_posts p JOIN forum_threads t ON t.id=p.thread_id AND t.is_deleted=0
    WHERE p.is_deleted=0 GROUP BY t.board_id
)
SELECT b.*, ..., COALESCE(ts.thread_count, 0), COALESCE(ps.post_count, 0)
FROM forum_boards b
LEFT JOIN forum_categories c ON c.id=b.category_id
LEFT JOIN thread_stats ts ON ts.board_id=b.id
LEFT JOIN post_stats ps ON ps.board_id=b.id ...
```
單一查詢取代 1 + 2N。無 schema 變更、無 migration。

### 驗證
```
$ pytest tests/community/test_community_board_counts.py
...  3 passed
```
3 例：seed 後計數正確、刪掉 thread/post 後計數歸零、5 個額外版面（各 1-5 主題、每主題 2 回覆）計數正確。
既有 66 例 community 測試全綠。

---

## P5 — UI 動畫擴充

### 修補
`public/styles.css` 末段新增 P5 區塊：

| Class | 用途 | Animation |
|---|---|---|
| `.fx-capacity-bar` + `.fx-capacity-fill` | 任何百分比進度條 | 滑動波光 `fx-capacity-wave 2.4s linear infinite` |
| `.fx-capacity-bar.warning` | ≥ 80% 用量 | 黃色 + `fx-capacity-pulse 1.6s` |
| `.fx-capacity-bar.critical` | ≥ 90% 用量 | 紅色 + `fx-capacity-pulse .9s`（更急） |
| `.fx-hot` | 論壇高熱度 thread | `fx-hot-glow 2.8s` 呼吸光暈 |
| `.fx-tilt` | 卡片 hover | `perspective(800px) rotateX/rotateY` 3D 微傾 |
| `.fx-counter` | 通知未讀數 | `fx-counter-flip .55s` 翻牌 |
| `.fx-pop` | 成功 toast | `fx-pop .42s` 彈出 |

`public/index.html`：雲端硬碟容量條加掛 `.fx-capacity-bar` / `.fx-capacity-fill` 兩個類別（不動 id，相容既有 JS）。

`public/js/35-drive.js`：在更新 percent 時同步：
- 設 CSS 變數 `--fx-capacity-percent`
- 視 percent 切換 `.warning` / `.critical` class

### 無障礙
新增的 `@media (prefers-reduced-motion: reduce)` 把所有 `fx-*` 動畫降為靜態。

---

## P6 — 腳本互動 UX

### 全 repo 審查結果
- `scripts/` 下所有 `*.py`：**0 個** `while True:` 無 break/return/raise/exit 的腳本（不會自行死循環）
- silent `except: pass`：集中在 `scripts/games/chess_*`（屬於別人正在做的研究分支，**不碰**），其他 scripts 模組均 OK

### 修補：新增 `scripts/_progress.py`
提供六個共用工具讓未來新腳本（與漸進改造既有腳本）都有一致的 UX 行為：

| 函式 | 用途 |
|---|---|
| `announce(msg)` | 帶時間戳的 stderr 一行訊息（不污染 stdout/JSON 輸出） |
| `step(n, total, label)` | 印 `[ 3/13] label` 風格的階段標題 |
| `heading(text)` | 帶分隔線的段落標題 |
| `ProgressBar(total)` | 純 ASCII `█████░░░░░ 50% (3/6) label 1.2s` 進度條，無外部依賴 |
| `confirm(prompt, default)` | 互動式 y/N，`HACKME_NONINTERACTIVE=1` 自動採用 default、`HACKME_ASSUME_YES=1` 一律 yes |
| `bounded_loop(seconds, label)` | 取代 `while True:` 的 context manager，自帶 deadline 與每 5s 倒數提示，**從根源防止死循環** |
| `assert_not_silent(returncode, label, stderr)` | 包 subprocess 結果，非 0 一律 raise 並附 stderr 末段 — **禁止靜默失敗** |

### 使用契約（docs 補充於 `docs/AGENTS/skills/` 後續）
1. 長時間工作（>5s）必須有 `announce()` 或 `ProgressBar`
2. 多階段腳本（n>1）用 `step(n, total, label)`
3. 不可寫 `while True:`，要用 `bounded_loop()` 或顯式 deadline
4. 不可吞 subprocess 失敗 — 用 `assert_not_silent()`
5. 對使用者互動點要支援 `HACKME_NONINTERACTIVE` / `HACKME_ASSUME_YES`

### 驗證
```
$ pytest tests/scripts/test_progress_helpers.py
.........  9 passed
```
覆蓋 step 編號、進度條 0% 邊界、confirm 三種模式、bounded_loop 過期、assert_not_silent 兩種路徑、heading 三行格式。

---

## 測試彙整

| 套件 | 例數 | 結果 |
|---|---|---|
| `tests/platform/test_settings_metadata.py` (P1 新) | 10 | ✅ |
| `tests/platform/test_settings_audit_reseal.py` (既有) | 1 | ✅ |
| `tests/platform/test_feature_flags.py` (既有) | 12 | ✅ |
| `tests/platform/` 整體 | 84 | ✅ |
| `tests/games/test_chess_opening_book.py` (P2 新) | 9 | ✅ |
| `tests/trading/test_funding_pool_payload.py` (P3 新) | 4 | ✅ |
| `tests/trading/core/` + `tests/trading/pricing/` (既有) | 244 | ✅ |
| `tests/community/test_community_board_counts.py` (P4 新) | 3 | ✅ |
| `tests/community/` 整體 | 66 | ✅ |
| `tests/scripts/test_progress_helpers.py` (P6 新) | 9 | ✅ |
| `tests/security/auth/test_access_controls.py` (P1 改) | 全套 | ✅ |
| `tests/snapshots/test_snapshots.py` (既有迴歸) | 全套 | ✅ |

棋力套件 2 例既有失敗（PV 研究分支） — **與本次修補無關**，移除我新增的程式碼後仍存在。

---

## 未涉及 / 留給後續

- **30 個 feature_* toggle 的前端視覺重整**：本次只完成後端元資料與 gate；`public/js/50-admin.js` 6400 行的全面分群顯示重畫為後續迭代
- **既有 scripts 改造**：本次只提供 `_progress.py` 與契約，把 13 個 `on_live_reports/*.py` 與其他長時間腳本逐一 migration 留給後續 commit
- **chess opening book 擴充**：目前 ~60 position 已足以避免「e4 → a5」；要進到「Sicilian Najdorf 主線 10 ply 內全在書」可在 `_LINES` 補
