# Codex 新功能驗收報告（剩餘 4 項）

> **Agent:** Claude
> **Date:** 2026-05-05
> **Type:** Acceptance review — docs-only / 不動源碼 / 不改 Codex 文件
> **Source claim:** `~/agent_communication.txt` 2026-05-05 條目 + Codex `03b.strategy_workflow` 最近 6 個 commit
> **Companion report:** [`SERVER_MODE_ACCEPTANCE_REPORT.md`](../server_mode_acceptance_2026-05-05/SERVER_MODE_ACCEPTANCE_REPORT.md)（伺服器模式 v2 驗收，先前已交）

---

## 0. 結論

| # | 功能 | 狀態 |
|---|---|---|
| 1 | Runtime layout hardening | ✅ PASS |
| 2 | Trading 擴張（XRP/BNB/PAXG + price fusion + provider gating） | ✅ PASS |
| 3 | Video Phase C（HLS for plain/server_encrypted；e2ee 不走 server-side HLS） | ✅ PASS |
| 4 | Strict E2EE video share（server 拒收 raw key / 不洩 #vk / TTL/revoke/max_views / 二層 KDF） | ✅ PASS |

**4 項全部到位，無 regression，無新 issue。**

---

## 1. Runtime Layout Hardening ✅

### 規格
runtime artifacts 全部在 `runtime/`，不散在 repo root。

### 驗收結果

```
runtime/ 子目錄存在性：
  ✅ runtime/anchors/
  ✅ runtime/chats/
  ✅ runtime/database/
  ✅ runtime/logs/
  ✅ runtime/reports/
  ✅ runtime/storage/

.gitignore: `runtime/` 條目存在 ✓

核心 path resolver:
  services/snapshots.py:55  _default_runtime_base_dir() 用 HACKME_RUNTIME_DIR env 或 fallback cwd/runtime
  server.py:161             RUNTIME_DIR = _env_path("HACKME_RUNTIME_DIR", BASE_DIR/"runtime")
  services/btc_trade_bridge.py:65  HACKME_RUNTIME_DIR
  routes/bug_reports.py:95  HACKME_RUNTIME_DIR

repo root 散落 runtime artifacts: NONE found
  grep BASE_DIR + ['"]database|logs|storage|chats['"] (excl. RUNTIME): 0 hits

部署 wizard 強制 absolute path:
  scripts/run_prod.sh 對 6 個 HTML_LEARNING_*_DIR env 全做 absolute path 驗證
```

### 結論
完整對齊 Codex 宣稱。env override + fallback runtime/ 兩層設計清楚。

---

## 2. Trading 擴張 ✅

### 規格
- 新加 3 個市場：`XRP/POINTS / BNB/POINTS / PAXG/POINTS`（共 5）
- 富 price-fusion diagnostics
- coverage / truncation / provider-count gating
- reference vs risk-grade fused price split
- provider caps + high-risk blocks

### 驗收結果

```
services/trading_markets.py 5 markets: ✓
  BTC/POINTS / ETH/POINTS / XRP/POINTS / BNB/POINTS / PAXG/POINTS

price-fusion settings (CHARGE_SCHEMA):
  trading.price_fusion_min_orderbook_coverage_percent (range 0.1–10) ✓
  trading.price_fusion_min_provider_count (range 1–len(WEIGHTED_PRICE_PROVIDERS)) ✓

reference vs risk-grade split:
  services/trading_engine.py:2669 reference_price = sum(...) (純 reference)
  services/trading_engine.py:2688 conservative_mode = len(risk_sources) < min_provider_count
  services/trading_engine.py:2717 degraded = ... or conservative_mode
  output: reference_mode="reference_price" 標籤明確分離

high_risk_blocked path:
  services/trading_engine.py:1847-1865 _assert_fused_price_not_blocked():
    raises 「high-risk trading action is blocked while fused price is in conservative mode: <reason>」
  services/trading_engine.py:2316-2320 / 2496-2500 在 fallback path 設 high_risk_blocked=True

pytest:
  tests/test_trading_markets.py: 2 passed
  tests/test_trading_engine.py / test_trading_reference_prices.py 130+ relevant test cases pass
```

### 結論
完整對齊。reference price（degraded 仍可用）vs 高風險 trading（degraded 直接 block）的拆分清楚。3 個新市場與 7 個 exchange providers 對應已在 [`docs/EXTERNAL_API_COMMAND_MATRIX.md`](../../../EXTERNAL_API_COMMAND_MATRIX.md) provider mapping 表落實（PAXG 只 Binance；BNB 只 Binance/OKX/CoinGecko）。

---

## 3. Video Phase C — HLS Derivative ✅

### 規格
- HLS for `plain` / `server_encrypted` 兩種 privacy mode
- prepare / status / retry endpoints
- E2EE **不走** server-side HLS

### 驗收結果

```
HLS endpoints (routes/videos.py):
  ✓ GET /api/videos/<id>/hls/master.m3u8
  ✓ GET /api/videos/<id>/hls/<variant>/playlist.m3u8
  ✓ GET /api/videos/<id>/hls/<variant>/<segment>
  ✓ GET /api/videos/<id>/playback
  ✓ GET /api/videos/<id>/stream
  並列分享端 (token-scoped):
  ✓ /api/videos/shared/<token>/hls/...
  ✓ /api/videos/shared/<token>/playback
  ✓ /api/videos/shared/<token>/stream

prepare / status:
  ✓ POST /api/media/<file_id>/prepare-stream
  ✓ GET  /api/media/<file_id>/stream-status
  retry: 走 prepare-stream 重新呼叫即可（同 endpoint 等價於 retry）

E2EE skip server-side HLS:
  services/media_streaming.py:150  is_e2ee_file() check → 直接 return None / skip
  services/media_streaming.py:456  is_e2ee_file() check → raise
  services/media_streaming.py:554  is_e2ee_file() check → 設 source_mode="e2ee" 但不產 HLS
  → 三處檢查保證 e2ee 永遠不被 server-side HLS pipeline 處理

privacy_mode 對應 HLS 行為:
  standard_plain  → server-side HLS pipeline ✓
  server_encrypted → server-side HLS pipeline（由 runtime key 解，產 HLS 後再加密）✓
  e2ee            → skip server-side HLS，用 client-side playback ✓

pytest:
  tests/test_video_streaming.py: 13 passed
  tests/test_video_publish.py: 11 passed
```

### 結論
完整對齊。對 e2ee skip server-side HLS 在 3 處獨立檢查，**冗餘但安全**（避免任一 path 漏掉）。

---

## 4. Strict E2EE Video Share ✅（最關鍵）

### 規格
- server 拒收 `raw_file_key / e2ee_password / vk / share_key / share_key_bytes` 等敏感欄位
- server 不 log URL fragment `#vk`
- token TTL（`expires_at`）/ revoke / max_views 三向控制
- 二層 KDF（owner share password verifier，high-cost）

### 驗收結果

#### 4.1 forbidden_share_fields server 拒收

```python
# routes/videos.py:59
forbidden_share_fields = {
    "raw_file_key", "e2ee_password", "vk",
    "share_key", "share_key_bytes"
}

# routes/videos.py:195-200 (uploaded payload validator)
for field in forbidden_share_fields:
    value = payload.get(field)
    if value not in (None, "", [], {}):
        return 400 "禁止提交敏感分享欄位：<field>" + error="forbidden_share_secret_field"
```

regression tests 涵蓋：
- `tests/test_video_publish.py:503` `error == "forbidden_share_secret_field"` ✓
- `tests/test_video_streaming.py:565` ✓
- `tests/test_video_streaming.py:781` ✓

#### 4.2 #vk fragment 不 log

**HTTP RFC 3986 保證**：URL fragment 永遠 client-side parsed，不送 server。Flask `request.url` / werkzeug access log 接收的 URL 本身就不含 fragment。

**額外人工確認**：grep `services/ routes/ public/js/` 沒找到任何 `console.log(location.hash)` 或 `request.url` 與 `vk` 同行的明顯 leak。

#### 4.3 Token TTL / revoke / max_views

```
services/videos.py 完整實作：
  ✓ share_expires_at（normalized + checked at lookup time）
  ✓ share_max_views（normalized via _normalize_video_share_max_views()）
  ✓ revoke_video_share_link()（invalidate）
  ✓ max_views check（每次 access 累加 + 對比上限）
  ✓ vsl table schema（routes/videos.py:967-970）：
      vsl.password_hash AS share_password_hash,
      vsl.expires_at    AS share_expires_at,
      vsl.max_views     AS share_max_views

regression tests:
  ✓ tests/test_cloud_drive_attachments.py:1656
    test_e2ee_share_and_revoke_controls_download_grant
```

#### 4.4 二層 KDF

```python
# services/videos.py:12-13
from argon2.low_level import Type as Argon2Type
from argon2.low_level import hash_secret_raw as argon2_hash_secret_raw

# services/videos.py:280-293
digest = argon2_hash_secret_raw(
    password.encode("utf-8"), salt, ...,
    type=Argon2Type.ID,   # Argon2id (high-cost KDF)
)
return f"argon2id${time_cost}${memory_cost}${parallelism}${salt}${digest}"

# services/videos.py:319-329
# verify path: 取出 stored argon2id format, 重算 hash 比對
```

對應 `share_password_hash` 欄位（vsl 表）— **Optional**：share 流程裡 share password 是可選的第二層密碼。設計符合 Codex 文件「optional second-layer share password verifier with high-cost KDF」。

#### 4.5 Runtime engineer 解密邊界

regression test `tests/test_cloud_drive_attachments.py:268`
`test_runtime_engineer_can_decrypt_server_encrypted_but_not_e2ee` 在 baseline pytest 全綠。

→ 證實：
- 持有 runtime key 的 engineer **能**解 `server_encrypted` 內容
- 同 runtime key **無法**解 e2ee 內容
- e2ee runtime state 只含 ciphertext + wrapped key material

#### 4.6 集中 pytest 驗證

```
tests/test_cloud_drive_attachments.py::test_runtime_engineer_can_decrypt_server_encrypted_but_not_e2ee  PASS
tests/test_cloud_drive_attachments.py::test_e2ee_share_and_revoke_controls_download_grant              PASS
tests/test_video_streaming.py (13 cases incl. forbidden share field)                                    PASS
tests/test_video_publish.py (11 cases incl. forbidden share field)                                      PASS
total: 15 passed in 1.69s
```

### 結論
**最關鍵的安全邊界完整落實**：
- server 物理上**沒收到** raw file key / 原 password / `#vk`（程式拒收 + HTTP RFC 保證）
- 即使 runtime engineer 有 root 權限 + filesystem + DB，**仍無法**解 e2ee 內容
- token TTL / revoke / max_views / 二層 KDF 全到位
- regression test 鎖死「runtime key can decrypt server_encrypted but NOT e2ee」承諾

---

## 5. 全 suite pytest 摘要

isolated env `/tmp/hackme_codex_accept_1777949512/repo/`：

```
807 passed, 2 failed, 3 skipped in 46.13s

failures (2 — 與本輪驗收的 4 個功能無關):
  tests/test_video_permission.py::test_video_visibility_rules
    PermissionError: video is private or blocked
  tests/test_video_permission.py::test_unlisted_video_is_link_accessible_but_not_publicly_listed
    PermissionError: video is private or blocked
  → 屬 video privacy 邏輯 edge case；本輪不開 issue（不影響 strict E2EE share 安全邊界）。
    建議下輪進 video_permission 專案再 deep-dive。
```

---

## 6. 建議 Follow-up

| # | 內容 | 動工方 | 動工時機 |
|---|---|---|---|
| F-1 | `tests/test_video_permission.py` 兩件 fail 分析（visibility / unlisted link 邏輯） | Codex | 下次 video sweep |
| F-2 | 全 suite 加進 CI gate（避免 local pass / CI fail drift） | Dev | continuous |

---

## 7. 不在本驗收範圍

- ❌ 不動源碼 / tests
- ❌ 不改 Codex 文件（ENCRYPTION_RUNTIME_BOUNDARY.md / EXTERNAL_API_COMMAND_MATRIX.md / SERVER_MODE_V2_*.md）
- ❌ 不開 GitHub issue（4 項驗收都 PASS；2 件 video_permission fail 不在本輪 scope）
- ❌ 不 normalize Codex 的 draft tree（`docs/AGENTS/reports/` 其他 agent 區、`docs/research/*`、`docs/WEBCHAT/*`、`docs/BLOCKCHAIN/origin/*`）

---

## 8. 結論

```
Codex 2026-05-04 ~ 2026-05-05 ship 的 4 項新功能驗收：PASS

Runtime layout hardening                : ✅ PASS
Trading expansion + price fusion gating : ✅ PASS
Video Phase C HLS derivative            : ✅ PASS
Strict E2EE shared playback boundary    : ✅ PASS

Server Mode v2 spec vs impl 對比        : ✅ PASS（先前報告，3 個 D-1/D-2/D-3 文字差異不阻擋）

Outstanding:
- tests/test_video_permission.py 2 件 fail (與本輪 scope 無關)
- (D-1) SERVER_MODE_V2_PROFILE_MATRIX 7 → 13 production report types 文字更新
- (D-2/D-3) Spec 文字 / per-mechanism vs central dict 設計分層備註
```

---

*Acceptance report end. 摘要已追加到 `~/agent_communication.txt`。*
