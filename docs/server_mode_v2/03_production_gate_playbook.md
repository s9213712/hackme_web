# Production Gate Playbook — 13 份必過 Reports

> **目的**：要把 server 切到 `production`，必須先有 13 份「最新通過」的 report 上傳並通過驗證。
> 本檔給操作者一張 step-by-step 對照表：每份 report 是什麼、怎麼產、怎麼上傳、怎麼驗 status、失敗怎麼辦。
>
> **依據**：[`docs/server_mode_v2/SERVER_MODE_V2_PROFILE_MATRIX.md §Production Gate Reports`](../../server_mode_v2/SERVER_MODE_V2_PROFILE_MATRIX.md#production-gate-reports) + `services/snapshots/schema.py:35-49 PRODUCTION_REQUIRED_REPORT_TYPES`。

---

## 0. 前置認知

每份 report 必須符合 `services/snapshots/server_mode.py:upload_production_report` 的所有檢查，否則 reject：

| 必填欄位 | 規則 |
|---|---|
| `report_type` | 必須 ∈ §1 13 個白名單 |
| `raw_report` | 原始報告 JSON；伺服器會對它做 canonical JSON 後重算 hash |
| `report_hash` | 格式 `sha256:<64 hex>`，且必須等於 `sha256(canonical_json(raw_report))` |
| `target_commit` | 受測 commit hash（git log 得） |
| `target_branch` | 受測 branch 名 |
| `server_mode` | 受測時 server 在哪個 mode（多數 = `dev_ready` 或 `test`） |
| `test_result` | 必須是 `pass` 或 `passed` |
| `passed` | 必須 `true`（boolean）|
| `critical_findings_count` | 必須 `0` |
| `high_findings_count` | 必須 `0` |
| `unresolved_findings` | 必須空陣列 |
| `tester` | 跑測試的人員 / 系統 ID |
| `signature` | 必須是 `hmac_sha256:<hex>`，伺服器會用 production report key 驗簽 |
| `key_version` | 對應簽章用的 key version |

**Replay 防護**：同 `(report_type, report_hash, target_commit)` 三元組已存在 → reject，避免複用過期 artifact。
**可信驗證**：缺少 `raw_report`、`report_hash` 與 `raw_report` 不一致、`signature` 驗證失敗、`key_version` 不符，任何一項都不會被 production gate 接受。

**Commit 對齊**：13 份 report 的 `target_commit` 必須**全部相同**才算「對同一個 commit 都通過」。任一份 commit hash 不一致 → 視為過期，重跑該份。

---

## 1. 13 份 Report 對照表

| # | report_type | 用途 | Generator | 預期 artifact |
|---|---|---|---|---|
| 1 | `clean_smoke` | Server Mode v2 乾淨 smoke：boot path / state-machine / 基線 endpoints | `scripts/security/server_mode/server_mode_v2_clean_smoke.py` | JSON 結果檔 |
| 2 | `adversarial` | Mode v2 對抗測試：injection / bypass / mode-spoof | `scripts/security/server_mode/server_mode_v2_adversarial.py` | JSON 結果檔 |
| 3 | `redteam_l2` | Mode v2 red-team Level 2 攻擊樹 | `scripts/security/server_mode/server_mode_v2_redteam_l2.py` | JSON 結果檔 |
| 4 | `pytest` | 全專案 pytest pass | `scripts/testing/pytest_in_tmp.sh -q tests` | pytest junit XML 或 stdout log |
| 5 | `log_chain_verify` | `mode_switch_logs` + audit chain hash 完整性 | 走 `/api/admin/health/audit-chain` 驗 + `services/server_mode_v2_log_chain_verify` 自寫 | JSON 結果檔 |
| 6 | `integrity_guard` | IntegrityGuard 自檢、無 high-risk finding | `python -c "from server import integrity_guard; print(integrity_guard.run_self_check())"` 或 `/api/admin/integrity/repair?dry_run=true` | JSON 結果檔 |
| 7 | `stress` | 流量 / trading 壓測 | `scripts/security/pentest/stress_test.py` + `scripts/security/pentest/trading_stress_pentest.py` | JSON 結果檔 |
| 8 | `permission` | role / permission pentest | `scripts/security/pentest/functional_permission_pentest.py` | JSON 結果檔 |
| 9 | `functional` | 全功能 smoke | `scripts/security/pentest/run_functional_smoke.sh` 或 `tests/security/smoke/smoke_suite.py` | JSON 結果檔 |
| 10 | `pentest` | 安全滲透測試 | `scripts/security/pentest/run_pentest.sh` + `scripts/security/pentest/session_security_pentest.py` | JSON 結果檔 |
| 11 | `snapshot_restore` | snapshot/restore regression | `tests/snapshots/test_snapshots.py` 全綠 + 手動跑 1 次 create→restore→verify | JSON 結果檔 |
| 12 | `points_chain_consistency` | PointsChain 一致性 | `tests/points/test_points_chain.py` + `services/points_chain.verify_chain()` | JSON 結果檔 |
| 13 | `cloud_drive_quota_permission` | Cloud Drive quota & 權限 | `tests/storage/test_cloud_drive_attachments.py` + `tests/storage/test_storage_albums_schema.py` | JSON 結果檔 |

> **附註**：1–6 號是 Server Mode v2 phase 2 cut 才加的「平台層」報告；7–13 號是更早的 functional / security domain 報告。

---

## 2. 產 report 的標準流程

每份 report artifact 應該是個 JSON 檔，至少含：

```json
{
  "report_id": "<uuid 或 timestamp+hex>",
  "report_type": "clean_smoke",
  "generated_at": "2026-05-05T11:00:00Z",
  "target_commit": "9273da5a...",
  "target_branch": "03b.strategy_workflow",
  "server_mode": "dev_ready",
  "test_result": "pass",
  "passed": true,
  "critical_findings_count": 0,
  "high_findings_count": 0,
  "unresolved_findings": [],
  "tester": "claude-acc-2026-05-05",
  "signature": "hmac_sha256:..."
}
```

**簽章**用內部 HMAC key（root 持有）對 JSON canonical form 計算。範例（pseudo）：

```bash
artifact_path=/tmp/report.json
hash=$(sha256sum "$artifact_path" | awk '{print $1}')
signature=$(openssl dgst -sha256 -hmac "$REPORT_SIGN_KEY" "$artifact_path" | awk '{print $2}')
```

`report_hash` 上傳時填 `sha256:$hash`；`signature` 填 `hmac_sha256:$signature`。

---

## 3. 上傳流程

### 3.1 確認 server 不在 production / incident_lockdown

upload report 不需要 server 已經在 production；通常是在 `dev_ready` 或 `test` 跑出 report，再上傳。但 `incident_lockdown` 期間禁止上傳（會被 mode policy 擋）。

### 3.2 用 root 帳號 + CSRF + POST

```bash
csrf=$(curl -sk -c jar -b jar "$BASE_URL/api/csrf-token" | jq -re '.csrf_token')

curl -sk -b jar -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/root/production-report/upload" \
  -d "$(jq -n \
    --arg rt clean_smoke \
    --arg rh "sha256:$hash" \
    --arg tc "$target_commit" \
    --arg tb "$target_branch" \
    --arg sm "dev_ready" \
    --arg tr "pass" \
    --arg ts "claude-acc-2026-05-05" \
    --arg sig "hmac_sha256:$signature" \
    --arg c "$csrf" \
    '{
      report_type: $rt, report_hash: $rh,
      target_commit: $tc, target_branch: $tb,
      server_mode: $sm, test_result: $tr, passed: true,
      critical_findings_count: 0, high_findings_count: 0,
      unresolved_findings: [],
      tester: $ts, signature: $sig,
      csrf_token: $c
    }')"
```

成功會回 `{"ok": true, "report_id": "prodrep_..."}`。

### 3.3 驗證 status

```bash
curl -sk -b jar "$BASE_URL/api/root/production-report/status" | jq
```

回傳會列出 13 個 type 中各自是否「最新通過」。任一 type `latest_passing == false` → 必須補。

```json
{
  "ok": true,
  "required": ["clean_smoke", "adversarial", ..., "cloud_drive_quota_permission"],
  "status": {
    "clean_smoke": {"latest_passing": true, "latest_report_id": "prodrep_..."},
    "adversarial": {"latest_passing": false, "reason": "no report uploaded yet"},
    ...
  },
  "ready_for_production": false
}
```

### 3.4 13 份全綠後才能 enter production

```bash
csrf=$(curl -sk -c jar -b jar "$BASE_URL/api/csrf-token" | jq -re '.csrf_token')
curl -sk -b jar -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/root/production/enter" \
  -d "{\"confirm\":\"GO_LIVE\",\"reason\":\"prod cut for 2026-05-05 release\",\"csrf_token\":\"$csrf\"}"
```

---

## 4. 失敗排錯

### 4.1 「report_type 不在 production gate 清單」
typo；確認名稱在 §1 13 個之一。

### 4.2 「report_hash 必須是 sha256:<64 hex>」
格式：`sha256:` + `64 hex chars`，缺一不可。

### 4.3 「production report 必須明確 pass」
- `test_result` 必須是 `pass` 或 `passed`（小寫）
- `passed` 必須 `true`（boolean，不是字串）

### 4.4 「不允許 critical/high finding」
report 內部如果還有 critical 或 high finding（`*_findings_count > 0` 或 `unresolved_findings` 非空），就先把 issue 處理掉再重跑、重產、重上傳。

### 4.5 「production report replay detected」
同 `(report_type, report_hash, target_commit)` 已上傳過。
- 改了東西 → `target_commit` 會變
- 沒改 → 直接複用既有 report；不需重上傳
- 想強制重新上傳 → 重新跑 generator 拿到新的 hash

### 4.6 13 份中部分 commit 不一致
全部 13 份的 `target_commit` 應該是同一個。最常見原因：commit 動了之後沒重跑全套；補跑該份就好。
查方法：

```bash
curl -sk -b jar "$BASE_URL/api/root/production-report/status" \
  | jq -r '.status | to_entries[] | "\(.key): \(.value.target_commit // "MISSING")"'
```

只挑跟主流不同的 commit 重跑。

### 4.7 server 在 incident_lockdown 不能 enter production
先解 incident：

```bash
curl -sk -b jar "$BASE_URL/api/root/incident/status" | jq
# 解決事故後
csrf=$(curl -sk -c jar -b jar "$BASE_URL/api/csrf-token" | jq -re '.csrf_token')
curl -sk -b jar -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/root/incident/resolve" \
  -d "{\"reason\":\"<post-incident summary>\",\"csrf_token\":\"$csrf\"}"
```

---

## 5. 完整 13-Report 跑表（範本 / 一鍵腳本骨架）

下面是給操作者抄的骨架。實際 generator 命令依各 script 的 CLI 而定；這裡只是一個 orchestrator 草稿（**不要視為現成腳本**，只是流程示意）：

```bash
#!/usr/bin/env bash
set -euo pipefail
BASE_URL="${BASE_URL:-https://127.0.0.1:5000}"
COMMIT="${COMMIT:?need git commit hash}"
BRANCH="${BRANCH:-03b.strategy_workflow}"
MODE="${MODE:-dev_ready}"
TESTER="${TESTER:-claude-acc-$(date +%Y%m%d)}"
ARTIFACTS=/tmp/prodrep_$COMMIT
mkdir -p "$ARTIFACTS"

step() {
  local rtype="$1"; shift
  local artifact="$ARTIFACTS/${rtype}.json"
  echo "=== $rtype ==="
  "$@" --out "$artifact"     # generator should accept --out
  hash=$(sha256sum "$artifact" | awk '{print $1}')
  sig=$(openssl dgst -sha256 -hmac "$REPORT_SIGN_KEY" "$artifact" | awk '{print $2}')
  csrf=$(curl -sk -c /tmp/_jar -b /tmp/_jar "$BASE_URL/api/csrf-token" | jq -re '.csrf_token')
  curl -sk -b /tmp/_jar -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
    -X POST "$BASE_URL/api/root/production-report/upload" \
    -d "$(jq -n \
      --arg rt "$rtype" --arg rh "sha256:$hash" \
      --arg tc "$COMMIT" --arg tb "$BRANCH" \
      --arg sm "$MODE" --arg ts "$TESTER" \
      --arg sig "hmac_sha256:$sig" --arg c "$csrf" \
      '{report_type:$rt, report_hash:$rh,
        target_commit:$tc, target_branch:$tb,
        server_mode:$sm, test_result:"pass", passed:true,
        critical_findings_count:0, high_findings_count:0,
        unresolved_findings:[],
        tester:$ts, signature:$sig, csrf_token:$c}')"
  echo
}

step clean_smoke    python3 scripts/security/server_mode/server_mode_v2_clean_smoke.py
step adversarial    python3 scripts/security/server_mode/server_mode_v2_adversarial.py
step redteam_l2     python3 scripts/security/server_mode/server_mode_v2_redteam_l2.py
step pytest         scripts/testing/pytest_in_tmp.sh -q tests
step log_chain_verify  GET /api/root/server-mode/logs/verify
step integrity_guard   POST /api/root/integrity/rescan + GET /api/root/integrity/report
step stress         python3 scripts/security/pentest/stress_test.py
step permission     python3 scripts/security/pentest/functional_permission_pentest.py
step functional     bash    scripts/security/pentest/run_functional_smoke.sh
step pentest        bash    scripts/security/pentest/run_pentest.sh
step snapshot_restore  scripts/testing/pytest_in_tmp.sh -q tests/snapshots/test_snapshots.py
step points_chain_consistency scripts/testing/pytest_in_tmp.sh -q tests/points/test_points_chain.py
step cloud_drive_quota_permission scripts/testing/pytest_in_tmp.sh -q tests/storage/test_cloud_drive_attachments.py tests/storage/test_storage_albums_schema.py

# Final verify
curl -sk -b /tmp/_jar "$BASE_URL/api/root/production-report/status" | jq
```

> **注意**：上面骨架引用的 `security/wrappers/*` **是建議命名**，目前**未必所有腳本都已存在**。有 4 份（log_chain_verify / integrity_guard / snapshot_restore / points_chain_consistency / cloud_drive_quota_permission / pytest）需要包成 generator wrapper（產符合 §2 schema 的 JSON）。建議下一輪 dev sprint 補完。

---

## 6. Status 表（你目前可以做什麼）

| 名稱 | Generator 是否就緒 | 你需要做的 |
|---|---|---|
| `clean_smoke` | ✅ `scripts/security/server_mode/server_mode_v2_clean_smoke.py` | 確認它的 `--out` flag 行為，產 JSON |
| `adversarial` | ✅ `scripts/security/server_mode/server_mode_v2_adversarial.py` | 同上 |
| `redteam_l2` | ✅ `scripts/security/server_mode/server_mode_v2_redteam_l2.py` | 同上 |
| `pytest` | 🟡 沒有 wrapper | 寫一個 wrapper 跑 `pytest --json-report` 或自己 parse junit XML，產 JSON 符合 §2 schema |
| `log_chain_verify` | 🟡 沒有 wrapper | 寫 wrapper 對 `mode_switch_logs` 跑 hash chain replay |
| `integrity_guard` | 🟡 沒有 wrapper | 寫 wrapper call IntegrityGuard.run_self_check |
| `stress` | ✅ `scripts/security/pentest/stress_test.py` | 確認其 output 符合 §2 schema |
| `permission` | ✅ `scripts/security/pentest/functional_permission_pentest.py` | 同上 |
| `functional` | ✅ `scripts/security/pentest/run_functional_smoke.sh` | 同上 |
| `pentest` | ✅ `scripts/security/pentest/run_pentest.sh` | 同上 |
| `snapshot_restore` | 🟡 沒有 wrapper | 寫 wrapper 跑 create → restore → verify |
| `points_chain_consistency` | 🟡 沒有 wrapper | 寫 wrapper call `points_chain.verify_chain()` |
| `cloud_drive_quota_permission` | 🟡 沒有 wrapper | 寫 wrapper 跑 quota + permission 對核 |

**目前缺 6 個 wrapper**（pytest / log_chain_verify / integrity_guard / snapshot_restore / points_chain_consistency / cloud_drive_quota_permission）。

**建議補法**（不阻擋日常 dev，但 production 上線前必補）：
1. 在 `security/wrappers/` 下放 6 個 small Python script，每個 ~30 行
2. 各 script 支援 `--out <path.json>` 並按 §2 schema 寫
3. 補完後跑一次本檔 §5 orchestrator 看 13 份是否全綠

---

## 7. 實際行動指南（你現在可以做）

如果你想**今天就嘗試**過 production gate，分三步：

1. **先看當前狀態**：
   ```bash
   curl -sk -b jar "$BASE_URL/api/root/production-report/status" | jq
   ```
   會列出 13 個 type 各自最新狀態。

2. **跑既有 7 個 generator**（已存在的 script）：
   - clean_smoke / adversarial / redteam_l2
   - stress / permission / functional / pentest
   逐一跑、產 JSON、上傳。

3. **補 6 個缺的 wrapper**（log_chain_verify / integrity_guard / pytest / snapshot_restore / points_chain_consistency / cloud_drive_quota_permission）：
   - 這些 reuse 既有 service code（IntegrityGuard、points_chain.verify_chain、ServerModeService.restore_snapshot 等），只是包成 CLI wrapper
   - 每個 ~30 行 Python，可以用 1 個 sprint 補完
   - 建議先跑一份 pytest → json，因為 pytest 必過是基線

完成後，13 份 status 全綠 + `ready_for_production = true`，再 `POST /api/root/production/enter`，confirm phrase = `GO_LIVE`。

---

*Playbook end. 對應 spec：[`docs/server_mode_v2/SERVER_MODE_V2_PROFILE_MATRIX.md §Production Gate Reports`](../../server_mode_v2/SERVER_MODE_V2_PROFILE_MATRIX.md#production-gate-reports). 配套腳本：本資料夾 `01_internal_test_login_token.sh` + `02_tester_token_shadow_api.sh`。*
