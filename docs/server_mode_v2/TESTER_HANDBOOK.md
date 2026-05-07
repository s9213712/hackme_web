# Tester 教戰手冊 — Server Mode v2 兩 Tokens

> **這份是寫給 tester 看的**（不是 root，不是 dev）。從 tester 拿到 token 開始 →
> 跑功能測試 → 跑滲透測試 → 寫回報，全程一頁讀完。
>
> Root 視角請看 `01_internal_test_login_token.sh` / `02_tester_token_shadow_api.sh`
> 開頭的 ROOT 段。

---

## 0. 一句話：你拿到的是哪一個 token？

| 你拿到的東西 | 是哪個 token | 怎麼帶 | 用在哪 |
|---|---|---|---|
| 一條長字串 + 「請用這個登入 internal_test mode」 | **internal_test login token**（門禁卡） | `POST /api/login` body 的 `internal_test_token` 欄位 | `/api/login` |
| 一條長字串 + 「請用這個呼叫 /api/tester/* 自動化」 | **Server Mode v2 tester token**（API key） | HTTP header `X-Tester-Token` 或 `Authorization: Bearer …` | `/api/tester/*` |
| 兩條都拿到 | 兩個都是 | 各走各的通道，**不互通** | 上面兩格都用 |

> 看不出哪個？問核發給你 token 的 root，**不要猜**。猜錯送錯通道 → 401，但你會以為是
> 自己帳號錯。

完整對照表：[`docs/server_mode_v2/SERVER_MODE_V2_PROFILE_MATRIX.md` §Token Types](../../server_mode_v2/SERVER_MODE_V2_PROFILE_MATRIX.md#token-types)

---

## 1. Tester 的權力邊界（你不能做的事）

讀完這段再動手。違反任一條 → 你做的事**會留下 audit trail**，且操作會 401/403 失敗。

### 你**不能**：

1. 用 tester token 呼叫 `/api/admin/*`、`/api/root/*`、`/api/admin/server-mode`、
   `/api/admin/snapshots`、`/api/admin/integrity-guard`、`/api/admin/audit/*` —
   無論 server 在什麼 mode。設計上一定 **401/403**。
2. 用 internal_test login token 在 `production` / `dev_ready` mode 登入 —
   server 不會檢查它，也不會接受它。它只在 `internal_test` mode 有效。
3. 把 raw token 貼到 issue / Slack / git commit / log file。
   永遠用 fingerprint（前 8 + 後 4 char of sha256）。
4. 在 `production` mode 跑任何 `04_pentest_smv2.sh` / `07_privilege_escalation_smv2.sh`。
   這些腳本會 fail-fast 拒絕，但你不應該嘗試。
5. 把 tester token 拿來測「真實使用者體驗」 — tester token 走 **shadow** layer，動的是
   `test_shadow_*` table，不是 `users / points_wallets / points_ledger`。
   要測真實 UX 用 internal_test login token 登入後走 UI（見 §3）。
6. 把 internal_test login token 用作 API key — 它**只**在 `/api/login` body 出現一次，
   server 拿來換 session cookie，之後通通靠 cookie。把它當 header bear token → 401。
7. 共用 token。每個 tester 拿到的 token 綁該 tester 的 user id（login token）或 token id
   （tester token），別人用會被檢測（fingerprint mismatch + audit）。

### 你**可以**：

- 在 `test` 或 `internal_test` mode 跑 `02_tester_token_shadow_api.sh` 內所有 `/api/tester/*` 操作
- 在 `internal_test` mode 用 login token 登入後，走 UI 跑功能測試（涵蓋 chat、storage、video、trading 預覽等）
- 跑 `04_pentest_smv2.sh` / `07_privilege_escalation_smv2.sh` 對 SMv2 邊界做負面測試
- 看自己的 shadow state、改自己的 shadow role、加減自己 shadow wallet
- 報任何你發現的 bug / 行為不合規範事項到 `docs/AGENTS/QA_MISSION_FOR_AGENTS.md` 指定流程

---

## 2. 第一次拿到 token 要先做什麼（Quick Start）

### 2.1 預檢

```bash
# 1) 確認你拿到的是哪個 token（問 root）
# 2) 確認 server 在哪個 mode
curl -sk -H "User-Agent: Mozilla/5.0 (X11; Linux) HackmeWebTester/1.0" \
     "$BASE_URL/api/root/server-mode" | jq .

# 預期：current_mode = "internal_test" 或 "test"
# 若是 "production" / "dev_ready" — 你拿到的兩種 token 都不會生效，停。
```

### 2.2 先跑無破壞 smoke 確定通道沒壞

```bash
python3 scripts/security/server_mode/server_mode_v2_token_smoke.py
```

這個腳本會：
- 開一個 isolated runtime 在 `/tmp/hackme_token_smoke_<random>/`
- 自己 bootstrap root + tester
- 自己跑 `01_internal_test_login_token.sh` 與 `02_tester_token_shadow_api.sh`
- 自己 assert shadow vs prod 隔離有效
- 跑完保留 runtime + log 給你看

如果這個 smoke 連 PASS 都做不到 → 不是你的 token 問題，是環境問題。停下找 root。

### 2.3 環境與工具

需要：`bash`、`curl`、`jq`、`python3`。腳本都 self-contained。

`internal_test` mode 開了 `browser_only_mode_enabled=true` → plain curl 沒帶 UA marker
會被 middleware 401 擋。**所有腳本和你自己的探針都要帶**：

```bash
-H "User-Agent: Mozilla/5.0 (X11; Linux) HackmeWebTester/1.0"
```

（任何含 `Mozilla` 的 UA marker 都行；見 `services/security/access_controls.py:BROWSER_UA_MARKERS`。）

---

## 3. 功能測試 — 用既有腳本走過一輪

### 3.1 只測 internal_test login（你只拿到 login token）

```bash
BASE_URL=https://127.0.0.1:5000 \
ROOT_USER=root \
ROOT_NEW_PW='RootStrongP@ssw0rd' \
TESTER_USER=test \
TESTER_PW=testpw \
  bash docs/server_mode_v2/01_internal_test_login_token.sh
```

腳本流程（你只負責跑 + 看結果）：

1. ROOT 視角段：腳本自動處理 root login + 切到 `internal_test` mode +
   產 internal_test login token。**你不需要記住 root 步驟，腳本會做。**
2. TESTER 視角段：用 tester 帳號 + 平常密碼 + login token 登入；確認 `/api/me`
   能看到自己 session；走 `/api/logout`。
3. 退出後腳本自己清理 mode（切回原 mode）。

PASS 條件：腳本 rc=0、最後一行印 `[PASS]`。

> **注意**：`test` 帳號預設 `must_change_password=1`。第一次登入 server 會強制改密。
> 若 `01_*` 腳本顯示「forced password change required」就照提示處理；之後再跑就 OK。

跑完後你**有了登入態**（一個 cookie session）。可以開 browser 連 `BASE_URL` 用同個
cookie 走 UI 測：

- chat
- community
- video upload + playback + share
- cloud drive
- trading 預覽（不能下單，因為 `internal_test` 通常 trading_enabled=false）
- 設定頁所有可見項目

每個你動的功能，**故意製造例外**：

- 上傳超過 quota 的檔
- 上傳 .exe（應被擋）
- 影音密碼分享，輸錯密碼 3 次（應 lockout）
- 影音密碼分享，輸對密碼，撈 metadata，re-encode、download、revoke
- chat 房名塞 `\n` 換行字元（issue #179 — 看是否會偽造 audit）
- 註冊頁送錯欄位看是否保留 username / email（issue #172）

---

### 3.2 只測 tester shadow API（你只拿到 tester token）

```bash
BASE_URL=https://127.0.0.1:5000 \
ROOT_USER=root \
ROOT_PW='RootStrongP@ssw0rd' \
TESTER_USER_ID=3 \
  bash docs/server_mode_v2/02_tester_token_shadow_api.sh
```

腳本流程：

1. ROOT 段：root 切 mode + create scoped tester token（`POST /api/root/tester-token/create`，
   要帶 `expires_at` ISO 8601 **naive 本地時間**）
2. TESTER 段：
   - `GET /api/tester/shadow-state` — 讀自己 shadow
   - `POST /api/tester/shadow-role` — 改 shadow role（manager / user）
   - `POST /api/tester/shadow-wallet` — 加減 shadow points
   - 試圖呼叫 `/api/admin/*` 應 **全 401/403**
3. ROOT 段：revoke token，再試應失敗

PASS 條件：rc=0、最後印 `[PASS]`、且**負面測試行（admin/root 都被擋）為 PASS**。

腳本跑完後你拿到的能力：可以對 `/api/tester/shadow-*` 做任何讀寫探測。
**不要**用它去打 `/api/files/*`、`/api/videos/*` 等 user API — 設計上 tester token
只解鎖 `/api/tester/*` namespace。

---

### 3.3 兩 token 都拿到（完整 SMv2 walkthrough）

```bash
PYTHONPATH=. python3 scripts/security/server_mode/server_mode_v2_full_smoke.py
```

或手動：

```bash
BASE_URL=https://127.0.0.1:5000 \
ROOT_USER=root ROOT_PW='RootStrongP@ssw0rd' \
TESTER_USER_ID=3 \
  bash docs/server_mode_v2/06_full_feature_smv2.sh
```

`06_*` 是 end-to-end：mode switch、checkpoint、tester-token issue/use/revoke、isolation
check 全跑一輪。預期 30+ 個 sub-check 全 PASS。

---

## 4. 深度滲透測試（pentest）

> 滲透測試的目標**不是**把 server 弄壞，是**證明** SMv2 邊界在面對主動攻擊時仍然守住。
> 任何你發現的繞過路徑要寫進 issue + 附 reproduce script。

### 4.1 SMv2 專用攻擊面（用 04_pentest_smv2.sh）

```bash
BASE_URL=https://127.0.0.1:5000 \
ROOT_USER=root ROOT_PW='RootStrongP@ssw0rd' \
TESTER_USER_ID=3 \
  bash docs/server_mode_v2/04_pentest_smv2.sh
```

腳本內的 6 個 probe（你看到 `[FAIL]` 就是發現 bug，要回報）：

| Probe | 攻擊面 | 期望結果 |
|---|---|---|
| 1 | `/api/tester/*` 沒帶 `X-Tester-Token` | 401 |
| 2 | `/api/tester/*` 帶 revoked token | 401（不是 200，不是 500） |
| 3 | internal_test login token 旋轉後再用舊的 | 401 |
| 4 | 在 `dev_ready` mode 送 `internal_test_token` field 給 `/api/login` | server 必須**忽略**這個欄位（不能當 back door） |
| 5 | `POST /api/root/server-mode/switch` 不帶 confirm phrase | 400 |
| 6 | tester token 試呼叫 `/api/root/*` 或 `/api/admin/server-mode` | 401/403 |

每個 probe 印 PASS/FAIL + HTTP status。**FAIL 才是發現** — 立刻停手，記錄 status code +
response body，去寫 issue。

### 4.2 Privilege escalation negatives（用 07_privilege_escalation_smv2.sh）

```bash
BASE_URL=https://127.0.0.1:5000 \
ROOT_USER=root ROOT_PW='RootStrongP@ssw0rd' \
TESTER_USER_ID=3 \
  bash docs/server_mode_v2/07_privilege_escalation_smv2.sh
```

證明：

- shadow role 改成 `manager` / `admin` / `root` **不會**讓 tester 真的拿到 manager/admin/root 對 production 表的權限
- shadow wallet `+999999` **不會**寫到 `points_wallets`
- shadow chain block **不會**寫到 `points_chain_blocks`
- 任何把 tester token 偷塞給 admin / root API 的招式都被擋

### 4.3 自己加 probe（不在現成腳本內的探測）

當你跑完 `04_*` / `07_*` 全 PASS，要加自己的負面測試。建議方向：

#### A. Tester token confused-deputy

```bash
# 嘗試把 tester token 塞到 cookie / query string / form field 看 server 是否接受
curl -sk "${CURL_OPTS[@]}" \
  -X POST "$BASE_URL/api/tester/shadow-state?token=$TESTER_TOKEN" \
  -d "tester_token=$TESTER_TOKEN"
# 期望 401（必須只認 X-Tester-Token / Authorization）
```

#### B. Mode race

```bash
# root 切 mode 的瞬間發 /api/tester/*
# 期望：要嘛 200（mode 還在 internal_test），要嘛 401（mode 已切離）
# 不該出現：500、cached state mismatch、shadow-write 跨 mode 殘留
```

#### C. Login token 跨 mode

```bash
# 1) root 在 internal_test 產 login token
# 2) root 切到 test mode
# 3) tester 試用該 login token 登入 → 期望 401（不是 internal_test 就不該認）
# 4) root 切回 internal_test
# 5) tester 用同 token → 仍應 401（一旦切走過就無效）
```

#### D. Token 過期邊界

```bash
# 製造 expires_at = now + 1 second
# sleep 2
# 用 token 呼 /api/tester/shadow-state → 期望 401
# 不期望：200（漏判過期）、500（時區處理崩）
```

> 已知坑：腳本 02 章踩過 `expires_at` 用 UTC `Z` 結尾在 TW（+8）下被視為已過期 →
> server 比較用 **naive local time**。你寫自定義 probe **必須**用
> `datetime.now() + timedelta(...)` 不帶 timezone。

#### E. CSRF + tester token 並用

State-changing tester API（`POST /api/tester/shadow-role` / `shadow-wallet`）仍需 CSRF。
試：

```bash
# 1) 帶 X-Tester-Token，但漏 X-CSRF-Token → 期望 403
# 2) 帶錯 CSRF token → 期望 403
# 3) 兩個都正確 → 期望 200
```

#### F. Audit completeness

每次跑完一組 probe 後撈 `mode_switch_logs` / `audit_log`：

```bash
# 用 root token（出腳本流程）
curl -sk -H "User-Agent: ..." -b "$ROOT_COOKIE" \
  "$BASE_URL/api/root/server-mode/logs?limit=20" | jq .
```

確認你做的每個事件**都有對應 audit row**。沒 audit 的事件 → 重大發現。

---

## 5. 故障排查（按頻率排）

| 症狀 | 機會大的原因 | 解法 |
|---|---|---|
| 401 對 `/api/*` 立刻發生 | UA 不帶 Mozilla marker | 加 `-H "User-Agent: Mozilla/..."` |
| 腳本說 token format error | 你貼到 env var 時換行 / 多空格 | 用 `tr -d '\n '` 清乾淨再貼 |
| `/api/tester/*` 401 但 token 看起來對 | server mode 不在 `test` / `internal_test` | `GET /api/root/server-mode` 確認 mode |
| `/api/tester/*` 全 PASS 但 `/api/admin/*` 也 200 | **你發現 bug 了**：tester token 越權 | 立即停手 → 寫 issue |
| login token 在 `internal_test` 401 | token 過期 / 已 revoke / 對應 user 已停用 | 找 root 重新核發 |
| `must_change_password` 卡死 tester | 預設 `test` 帳號首次登入要強制改密 | 走 forced-change flow，或請 root 在 DB 清 flag |
| 401 然後 audit 沒紀錄 | **可能是 silent 401**（規範是要 audit） | 寫 issue（這是 bug） |
| Token 看起來對但 expires 已過 | TZ confusion（見 §4.3-D） | naive local time 重發 |
| Shadow wallet 加 `+100` 但 `points_wallets` 也跟著 +100 | **你發現嚴重 bug 了**：shadow 隔離破 | 立即停手 → P0 issue |

---

## 6. 不可繞過的禁忌

1. **不要**用 `--no-verify` 跳過 `pre_push_checks` — pre-push hook 跑 pytest，
   testers 改腳本前確認 tests 過。
2. **不要**在 production runtime 跑任何 `0X_*.sh` 或 `04_*` / `07_*`。
3. **不要**把 raw token 印到 stdout / log / commit message。腳本已經幫你印 fingerprint，
   不要自己加 raw echo。
4. **不要**把 tester token 拿去開 SSH / 登 admin UI / 連 jupyter — 那不是它的範圍。
5. **不要**在發現 bug 後繼續挖掘其他問題 — 一個 PoC 就夠寫 issue。多挖只會混淆 root 處理優先序。

---

## 7. 寫 bug report 模板

當任一 probe `[FAIL]`，或你自己的探測發現異常：

```markdown
**[security][HIGH/MEDIUM/LOW] <一句話標題>**

**Reproduce**:
- BASE_URL: <which deployment>
- mode: <internal_test / test / dev_ready>
- script: <path/to/script>:<line> 或 <自定義 probe 命令>
- token type: <internal_test login | tester>
- token fingerprint: <前8...後4 of sha256>

**Expected**: <按文件 / matrix 應該的行為>
**Actual**: HTTP <status>, body=<one-liner of response>

**Why this matters**:
- 一兩句話說明這個行為違反 docs/server_mode_v2/SERVER_MODE_V2_PROFILE_MATRIX.md §<section> 的哪條
- 如果可被 chained 成更高權限：寫攻擊鏈

**Suggested test addition**:
- 應該補在 `tests/<existing_file>.py::test_<new_name>`
- 或 `docs/server_mode_v2/04_pentest_smv2.sh` 加第 7 個 probe
```

寫好交給 root（或開 GH issue 直接 tag root）。

---

## 8. 一定要看的相關檔

| 檔 | 為什麼要看 |
|---|---|
| [`README.md`](README.md) | 兩 token 的對照圖 + 6 個腳本索引 |
| [`docs/server_mode_v2/SERVER_MODE_V2_PROFILE_MATRIX.md`](../../server_mode_v2/SERVER_MODE_V2_PROFILE_MATRIX.md) | 唯一權威的「哪個 mode 開哪個 feature」表 |
| [`docs/AGENTS/QA_MISSION_FOR_AGENTS.md`](../../AGENTS/QA_MISSION_FOR_AGENTS.md) | QA 心態與底線 |
| [`docs/AGENTS/RULES_FOR_AGENTS.md`](../../AGENTS/RULES_FOR_AGENTS.md) | 跨 agent 規則 |
| [`01_internal_test_login_token.sh`](01_internal_test_login_token.sh) | login token 完整生命週期 |
| [`02_tester_token_shadow_api.sh`](02_tester_token_shadow_api.sh) | tester token 完整生命週期 |
| [`03_production_gate_playbook.md`](03_production_gate_playbook.md) | production 入口的 gate 報告（你不會直接動，但要懂） |
| [`04_pentest_smv2.sh`](04_pentest_smv2.sh) | SMv2 6 個 pentest probe |
| [`05_stress_smv2.sh`](05_stress_smv2.sh) | rate-limit / 壓測 |
| [`06_full_feature_smv2.sh`](06_full_feature_smv2.sh) | end-to-end walkthrough |
| [`07_privilege_escalation_smv2.sh`](07_privilege_escalation_smv2.sh) | 權限升級負面測試 |
| `scripts/security/server_mode/server_mode_v2_token_smoke.py` | 自己起 isolated runtime + 跑 01/02 的 smoke 工具 |
| `scripts/security/server_mode/server_mode_v2_full_smoke.py` | 6 個腳本的 bundle 跑法 |

---

## 9. 你跑完一輪該回報什麼

每個 tester session 結束時產出：

1. 跑了哪幾個腳本 + 結果（PASS/FAIL）
2. UI 操作測了哪些功能 + 是否符合預期
3. 自定義 probe 跑了幾個 + 結果
4. 發現的 bug list（每個一個 issue 連結）
5. 你**沒能**測到的功能（mode 限制 / 權限不足 / 環境問題）— 寫清楚，不要假裝測過

回報格式建議：

```markdown
## Tester Session — <date> — <你是誰>

- BASE_URL: <…>
- mode at start: <…>
- token types received: <login | tester | both>
- duration: <…>

### Scripts run
- `01_*.sh` rc=<0/1>, notes=<…>
- `02_*.sh` rc=<0/1>, notes=<…>
- `04_*.sh` 6/6 PASS
- `07_*.sh` 12/12 PASS

### UI flows tested
- chat: …
- video share unlock x3 modes: …
- cloud drive upload at quota: …

### Custom probes
- (A) Confused-deputy: PASS（401 as expected）
- (B) Mode race: PASS
- ...

### Findings
- issue #200: ...
- issue #201: ...

### Did not cover
- trading（mode trading_enabled=false in internal_test）
- root snapshot UI（不是我的權限範圍）
```

---

## End — 記住一句話

> 你的工作不是「讓系統 PASS」。是「**證明邊界守得住**」。
> 一個 PASS 的 tester session 是「我打了所有應該打的探針，**全部都正確被擋**」。

Tester 腳本完整索引在 [`README.md`](README.md)。深度問題去看 [`docs/AGENTS/`](../../AGENTS/)。
