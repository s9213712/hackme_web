# CLI Admin Playbook

一句話說明：這份文件專門給開發者、SRE、root / admin 使用 `curl` 與 shell 指令管理 `hackme_web`。

## 設計目的

網頁後台適合日常操作，但有些工作需要：

- 在隔離 runtime 做 API 驗證
- 用 shell 自動化管理站台
- 快速檢查 root-only 設定與交易診斷
- 在 QA / CI / 部署前做可重現操作

這份文件提供 **正式、可直接複製的 curl/cmd 範本**，避免每次都去翻測試腳本或聊天紀錄。

## 使用方法

### 1. 啟動隔離環境

不要直接污染 repo 根目錄 runtime。建議：

```bash
TS="$(date -u +%Y%m%dT%H%M%SZ)"
export HACKME_RUNTIME_DIR="/tmp/hackme_web_cli_$TS/runtime"
mkdir -p "$HACKME_RUNTIME_DIR"
python3 server.py
```

若是另一個 port：

```bash
python3 server.py --host 127.0.0.1 --port 5012
```

### 2. 共用變數

```bash
export BASE="https://127.0.0.1:5000"
export JAR="/tmp/hackme_web_cli.cookie"
```

### 3. 取 CSRF token

```bash
export CSRF="$(
  curl -k -sS -c "$JAR" "$BASE/api/csrf-token" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["csrf_token"])'
)"
```

### 4. root 登入

```bash
curl -k -sS -b "$JAR" -c "$JAR" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{"username":"root","password":"root"}' \
  "$BASE/api/login"
```

### 5. 重新取登入後 token

```bash
export CSRF="$(
  curl -k -sS -b "$JAR" -c "$JAR" "$BASE/api/csrf-token" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["csrf_token"])'
)"
```

## 常用指令

### 版本 / 站點資訊

```bash
curl -k -sS "$BASE/api/version"
curl -k -sS "$BASE/api/site-config"
curl -k -sS -b "$JAR" "$BASE/api/me"
```

### root 離線密碼補救

`root` 不走一般 web 忘記密碼流程。若 root 忘記密碼，請直接在實體 runtime / repo 上執行：

```bash
python3 scripts/admin/root_recovery.py --json
```

互動式自訂臨時密碼：

```bash
python3 scripts/admin/root_recovery.py --prompt-password
```

直接指定 DB 路徑：

```bash
python3 scripts/admin/root_recovery.py --db-path /path/to/runtime/database/database.db --json
```

這會：

- 重設 root 臨時密碼
- 撤銷 root 既有 session
- 清掉 root 的 CSRF token
- 強制下次登入立刻改密碼

不要把 `--password ...` 寫進 shell history；除非是臨時測試，否則建議使用 `--prompt-password`。

### 功能開關

讀：

```bash
curl -k -sS -b "$JAR" "$BASE/api/admin/features"
```

寫：

```bash
curl -k -sS -b "$JAR" -H "Content-Type: application/json" -H "X-CSRF-Token: $TOKEN" \
  -X PUT \
  -d '{
    "feature_economy_enabled": true,
    "feature_trading_enabled": true
  }' \
  "$BASE/api/admin/features"
```

### 系統設定

讀：

```bash
curl -k -sS -b "$JAR" "$BASE/api/admin/settings"
```

寫：

```bash
curl -k -sS -b "$JAR" -H "Content-Type: application/json" -H "X-CSRF-Token: $TOKEN" \
  -X PUT \
  -d '{
    "integrity_guard_enabled": true,
    "audit_chain_enabled": true
  }' \
  "$BASE/api/admin/settings"
```

### Access Controls / IP Whitelist

讀：

```bash
curl -k -sS -b "$JAR" "$BASE/api/admin/access-controls"
```

寫：

```bash
curl -k -sS -b "$JAR" -H "Content-Type: application/json" -H "X-CSRF-Token: $TOKEN" \
  -X PUT \
  -d '{
    "root_ip_whitelist": ["127.0.0.1/32"],
    "incident_lockdown_enabled": false
  }' \
  "$BASE/api/admin/access-controls"
```

### 使用者管理

列表：

```bash
curl -k -sS -b "$JAR" "$BASE/api/admin/users"
```

讀單一使用者：

```bash
curl -k -sS -b "$JAR" "$BASE/api/admin/users/2"
```

封鎖：

```bash
curl -k -sS -b "$JAR" -H "Content-Type: application/json" -H "X-CSRF-Token: $TOKEN" \
  -d '{"reason":"manual review","hours":24}' \
  "$BASE/api/admin/users/2/block"
```

### Snapshots / Restore

列快照：

```bash
curl -k -sS -b "$JAR" "$BASE/api/admin/snapshots"
```

建立快照：

```bash
curl -k -sS -b "$JAR" -H "Content-Type: application/json" -H "X-CSRF-Token: $TOKEN" \
  -d '{"type":"manual","reason":"cli smoke"}' \
  "$BASE/api/admin/snapshots"
```

恢復快照：

```bash
curl -k -sS -b "$JAR" -H "Content-Type: application/json" -H "X-CSRF-Token: $TOKEN" \
  -d '{"confirm":"RESTORE","reason":"cli restore check"}' \
  "$BASE/api/admin/snapshots/<snapshot_id>/restore"
```

### Server Mode

讀 manager/root 相容入口：

```bash
curl -k -sS -b "$JAR" "$BASE/api/admin/server-mode"
```

讀 root 狀態：

```bash
curl -k -sS -b "$JAR" "$BASE/api/root/server-mode"
```

切換：

```bash
curl -k -sS -b "$JAR" -H "Content-Type: application/json" -H "X-CSRF-Token: $TOKEN" \
  -d '{"target_mode":"dev_ready","confirm":"SWITCH"}' \
  "$BASE/api/root/server-mode/switch"
```

### Trading: live price / price fusion / bot audit

即時價格：

```bash
curl -k -sS -b "$JAR" "$BASE/api/trading/live-price?market_symbol=BTC/POINTS"
```

root 融合價格診斷：

```bash
curl -k -sS -b "$JAR" "$BASE/api/root/trading/price-fusion-status?market_symbol=BTC/POINTS"
```

bot audit dashboard：

```bash
curl -k -sS -b "$JAR" "$BASE/api/root/trading/bot-audit/dashboard"
```

立即執行 bot 稽核：

```bash
curl -k -sS -b "$JAR" -H "Content-Type: application/json" -H "X-CSRF-Token: $TOKEN" \
  -X POST \
  -d '{}' \
  "$BASE/api/root/trading/bot-audit/run"
```

Grid preview：

```bash
curl -k -sS -b "$JAR" -H "Content-Type: application/json" -H "X-CSRF-Token: $TOKEN" \
  -d '{
    "market_symbol":"BTC/POINTS",
    "lower_price":"80000",
    "upper_price":"100000",
    "grid_count":20,
    "investment_amount":"10000",
    "order_mode":"maker"
  }' \
  "$BASE/api/trading/grid/preview"
```

### BTC_trade

檢查：

```bash
curl -k -sS -b "$JAR" "$BASE/api/root/trading/btc-trade/check"
```

setup：

```bash
curl -k -sS -b "$JAR" -H "Content-Type: application/json" -H "X-CSRF-Token: $TOKEN" \
  -X POST -d '{}' \
  "$BASE/api/root/trading/btc-trade/setup"
```

一鍵啟動預測：

```bash
curl -k -sS -b "$JAR" -H "Content-Type: application/json" -H "X-CSRF-Token: $TOKEN" \
  -X POST -d '{}' \
  "$BASE/api/root/trading/btc-trade/start"
```

查背景 job：

```bash
curl -k -sS -b "$JAR" "$BASE/api/root/trading/btc-trade/start-status"
```

### ComfyUI

狀態：

```bash
curl -k -sS -b "$JAR" "$BASE/api/comfyui/status"
```

root 測試連線：

```bash
curl -k -sS -b "$JAR" -H "Content-Type: application/json" -H "X-CSRF-Token: $TOKEN" \
  -X POST -d '{}' \
  "$BASE/api/root/comfyui/test-connection"
```

### Security Test Jobs

功能 smoke：

```bash
curl -k -sS -b "$JAR" -H "Content-Type: application/json" -H "X-CSRF-Token: $TOKEN" \
  -X POST \
  -d '{"port":50741}' \
  "$BASE/api/root/security-tests/functional"
```

壓力測試：

```bash
curl -k -sS -b "$JAR" -H "Content-Type: application/json" -H "X-CSRF-Token: $TOKEN" \
  -X POST \
  -d '{
    "target":"https://127.0.0.1:5000",
    "mode":"duration",
    "duration_seconds":10,
    "max_requests":1000,
    "concurrency":20,
    "burst_size":5,
    "burst_interval_ms":100
  }' \
  "$BASE/api/root/security-tests/stress"
```

查 job：

```bash
curl -k -sS -b "$JAR" "$BASE/api/root/security-tests/<job_id>"
```

## 原理

- `curl -k` 是因為本地常用自簽 TLS。
- cookie jar + `/api/csrf-token` 是最穩定的 CLI 管理方式。
- 所有高風險 root/admin 操作都應走隔離 runtime，不要對 repo 根目錄 runtime 或 production host 直接試。

## 失敗情境與提示

- `403 csrf_invalid`
  - 先重新打一次 `/api/csrf-token`
  - 再確認是不是登入後還在用舊 token
- `401`
  - 檢查 cookie jar 是否被覆蓋，或 bootstrap 帳號是否被 `must_change_password` gate 擋住
- `400`
  - 多半是 schema validator 在擋 invalid bool / NaN / Infinity / 非法 IP whitelist
- `200` 但結果看起來不對
  - 對設定、ACL、交易與快照操作，請再讀一次對應 GET API；不要只信單次寫入 response

## 測試方式

最低限度：

```bash
curl -k -sS "$BASE/api/version"
curl -k -sS -c "$JAR" "$BASE/api/csrf-token"
curl -k -sS -b "$JAR" -c "$JAR" -H "Content-Type: application/json" -H "X-CSRF-Token: $TOKEN" \
  -d '{"username":"root","password":"root"}' \
  "$BASE/api/login"
curl -k -sS -b "$JAR" "$BASE/api/me"
```

深入驗證：

- 搭配 [API_REFERENCE.md](API_REFERENCE.md) 逐類測
- 搭配 [11_QA_TESTING.md](11_QA_TESTING.md) 的 smoke / pentest / trading validation

## 相關文件連結

- [API_REFERENCE.md](API_REFERENCE.md)
- [For_developer.md](For_developer.md)
- [11_QA_TESTING.md](11_QA_TESTING.md)
- [TRADING.md](trading/TRADING.md)
- [TRADING_BOT_AUDIT.md](trading/TRADING_BOT_AUDIT.md)
