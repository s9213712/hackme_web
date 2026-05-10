# Multisig Wallets v1

> **狀態：設計已拍板（root, 2026-05-04），尚未實作完成。**
> 屬於 [POINTSCHAIN_ENGINEERING.md](POINTSCHAIN_ENGINEERING.md) Phase 4 規格。

---

## 1. 設計目的

讓平台高風險動作（增發、總庫支出、解封系統、修改 supply cap）**永遠不可由單一人執行**：

- 即使 root 帳號被盜，攻擊者也無法獨自增發
- root 自己也不可繞過多簽
- internal_test 模式可降門檻但**永遠不可降到 1-of-1**

---

## 2. 五個 Signer 角色

拍板：

| Role | 職責 | 預期帳號類型 |
|---|---|---|
| `root_owner` | 平台所有人 | 真人（root 帳號） |
| `security_admin` | 安全管理 | 真人 |
| `finance_admin` | 財務管理 | 真人 |
| `qa_release_admin` | QA / Release 管理 | 真人 |
| `emergency_recovery_admin` | 緊急復原管理 | 真人（建議離線冷錢包） |

> Phase 4 啟用初期可用 placeholder 帳號（如 `qa_signer_1` 等）測試流程；正式上線前必須由 root 透過 `signer_rotation` proposal 換成真實 signer，並公告於 explorer。

---

## 3. 門檻矩陣（拍板）

| Action | mainnet | dev_ready / preprod | internal_test |
|---|---|---|---|
| `mint` | **3-of-5** | 3-of-5 | 2-of-3 |
| `burn`（系統發起燒毀，非用戶 burn） | **3-of-5** | 3-of-5 | 2-of-3 |
| `treasury_transfer` | **3-of-5** | 3-of-5 | 2-of-3 |
| `reserve_transfer` | 2-of-3 | 2-of-3 | 2-of-3 |
| `reward_payout` | 2-of-3 | 2-of-3 | 2-of-3 |
| `dispute_payout` | 2-of-3 | 2-of-3 | 2-of-3 |
| `airdrop` | 2-of-3 | 2-of-3 | 2-of-3 |
| `incident_lockdown_release` | **3-of-5** | 3-of-5 | 2-of-3 |
| `supply_cap_change` | **3-of-5** | **不允許**（必須回 mainnet） | **不允許** |
| `signer_rotation` | **3-of-5** | **不允許** | **不允許** |

**永遠 ≥ 2，永不 1-of-1。** 違反此規則的 schema migration 直接拒絕。

---

## 4. Schema

```sql
CREATE TABLE points_multisig_wallets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    address TEXT UNIQUE NOT NULL REFERENCES points_wallet_addresses(address),
    name TEXT NOT NULL,
    threshold INTEGER NOT NULL CHECK (threshold >= 2),
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL
);

CREATE TABLE points_multisig_signers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT NOT NULL REFERENCES points_multisig_wallets(address),
    signer_user_id INTEGER REFERENCES users(id),
    signer_address TEXT NOT NULL REFERENCES points_wallet_addresses(address),
    signer_public_key TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN (
      'root_owner','security_admin','finance_admin',
      'qa_release_admin','emergency_recovery_admin'
    )),
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    UNIQUE(wallet_address, role)        -- 同一錢包每 role 只能有 1 名 signer
);

CREATE TABLE points_multisig_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT UNIQUE NOT NULL,
    wallet_address TEXT NOT NULL REFERENCES points_multisig_wallets(address),
    action_type TEXT NOT NULL CHECK (action_type IN (
      'mint','burn','treasury_transfer','reserve_transfer',
      'reward_payout','dispute_payout','airdrop',
      'incident_lockdown_release','supply_cap_change','signer_rotation'
    )),
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','approved','executed','rejected','expired')),
    created_by INTEGER NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL,
    execution_event_id TEXT,
    created_at TEXT NOT NULL,
    executed_at TEXT
);

CREATE TABLE points_multisig_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT NOT NULL REFERENCES points_multisig_proposals(proposal_id),
    signer_user_id INTEGER REFERENCES users(id),
    signer_address TEXT NOT NULL,
    approval_payload_hash TEXT NOT NULL,
    signature TEXT NOT NULL,                      -- ed25519 hex (64 bytes = 128 hex chars)
    approved_at TEXT NOT NULL,
    UNIQUE(proposal_id, signer_address)            -- 同一 signer 不可對同一 proposal approve 兩次
);

CREATE INDEX idx_multisig_proposals_status_expires
    ON points_multisig_proposals(status, expires_at);
```

---

## 5. Proposal 流程

```
1. propose ─→ pending
2. approve（多人） ─→ pending
3. 達 threshold ─→ approved（自動切換）
4. execute（手動）─→ executed
                    ─→ 寫 ledger_v2 multisig_execute event
                    ─→ 進 chain block
5. expires_at 到 ─→ expired（不可再 approve / execute）
6. propose 後可被 rejected（reject 動作也是一個 multisig action 但門檻較低）
```

關鍵設計：

- **達門檻不自動 execute**：避免最後 signer 同時也擔負執行責任。proposer 或任一 signer 可呼叫 `/execute`。
- **expired 後不可復活**：必須重新 propose。
- **同一 signer 只能 approve 一次**：DB UNIQUE 約束強制。
- **payload_hash 永遠不變**：proposal 建立後 payload 不可改；要改 → 拒絕現 proposal、重新 propose。

---

## 6. API

| Method | Path | 用途 | 角色 |
|---|---|---|---|
| GET | `/api/admin/points/multisig/proposals` | 列 proposals | admin / root |
| POST | `/api/admin/points/multisig/proposals` | 新建 proposal | admin / root |
| GET | `/api/admin/points/multisig/proposals/<id>` | 看 proposal 詳情 + approval status | admin / root |
| POST | `/api/admin/points/multisig/proposals/<id>/approve` | 簽章 approve | signer only |
| POST | `/api/admin/points/multisig/proposals/<id>/execute` | 達門檻後執行 | proposer / signer |
| POST | `/api/admin/points/multisig/proposals/<id>/reject` | 撤銷（也是一個 multisig action）| 視 action_type |
| GET | `/api/points/explorer/multisig/<id>` | 公開查 proposal status（不顯 signature 內容）| 匿名 |

### 6.1 Propose Request

```json
{
  "wallet_address": "PNT1TREASURY...",
  "action_type": "treasury_transfer",
  "payload": {
    "to_address": "PNT1xyz...",
    "amount": "10000",
    "currency_type": "points",
    "memo_hash": "...",
    "reason": "Phase 4 啟用測試"
  },
  "expires_in_seconds": 259200
}
```

server 自動補：`proposal_id = uuid`、`payload_hash = sha256(canonical(payload))`、`expires_at = now + expires_in_seconds`、`status = 'pending'`。

### 6.2 Approve Request

```json
{
  "approval_payload_hash": "<必須等於 proposal.payload_hash>",
  "signature": "<ed25519(payload_hash) 由 signer private key 簽>"
}
```

server 驗：

1. caller 是 signer
2. caller 尚未對此 proposal approve
3. `approval_payload_hash == proposal.payload_hash`
4. signature verify 成功（ed25519 with `signer_public_key`）
5. proposal 仍 pending 且未 expired

驗 OK 後寫入 `points_multisig_approvals`；計目前 approval count；若達 threshold 把 proposal status 自動切 `approved`。

### 6.3 Execute Request

```json
{}
```

server 驗：

1. proposal status `approved`
2. 未 expired
3. 系統不在 incident_lockdown（除非 action_type = `incident_lockdown_release`）
4. wallet status `active`

執行：依 action_type 真實寫入 `points_ledger_v2` 一筆 `multisig_execute` event + 連帶必要 events（如 mint 寫 mint event）。

執行成功後 proposal status → `executed`，執行 event_id 寫入 `execution_event_id`。

---

## 7. Incident Lockdown 互動（拍板）

進入 `incident_lockdown` 後：

| 動作 | 是否允許 |
|---|---|
| 新建 proposal | ✅ |
| approve 既有 proposal | ✅ |
| **execute 既有 proposal**（除 `incident_lockdown_release`）| ❌ |
| 一般 transfer | ❌ |
| 一般 trade | ❌ |
| 一般 mint（必經 multisig）| ❌（execute 被擋）|

解除 incident_lockdown 本身就是 `incident_lockdown_release` 多簽 action。解除後累積的 approved proposals 才能 execute。

---

## 8. Signer Rotation（換 signer）

換 signer 也是一個多簽 action `signer_rotation`：

```json
{
  "wallet_address": "PNT1TREASURY...",
  "rotation": [
    {"role": "finance_admin", "old_signer_address": "...", "new_signer_address": "..."}
  ],
  "reason": "..."
}
```

執行後寫 `multisig_execute` event + 在 `points_multisig_signers` 把舊 signer status 改 `revoked`、新 signer 寫 `active`。

**Rotation 必須 mainnet 3-of-5**；dev_ready / internal_test 都不允許。

---

## 9. UI / UX

### 9.1 後台 proposal 頁

每筆 proposal 顯示：

- proposal_id（前 8 字元 + 完整可複製）
- action_type（badge）
- payload preview（reason、amount、to）
- approvals 進度（3/5 等）
- 各 signer 狀態（已簽章 ✓ / 待簽 / 已過期）
- expires_at 倒數
- 操作按鈕：approve / reject / execute（依 caller 角色與 status 顯示）

### 9.2 簽章 UI（custodial signer）

- 顯示完整 payload preview（不能只顯示 hash）
- 強制勾選「我已確認以上 payload 正確」
- 倒數 10s 後才能按「簽章」
- 簽章成功後顯示「已簽章」+ 簽章時間

### 9.3 執行 UI

- 顯示「目前進度 X/Y、達門檻 ✓」
- 二次確認「我要執行此 proposal，動作不可逆」
- 失敗訊息明確（系統 lockdown、wallet frozen、expired）

### 9.4 手機版

所有上述 UI mobile RWD 必過。

---

## 10. QA Gate（細項 [POINTSCHAIN_QA.md §4](POINTSCHAIN_QA.md)）

- [ ] threshold-1 簽章必拒絕 execute
- [ ] threshold = 1 的 proposal 直接拒絕（schema CHECK + service 雙保險）
- [ ] 同 signer 重複 approve 自動拒絕
- [ ] 過期 proposal 不可 approve / execute
- [ ] 假 signature（mutated 1 byte）必拒
- [ ] 不是 signer 的人 approve 必拒
- [ ] incident_lockdown 期間 execute 全拒（測 8 種 action_type 除 release）
- [ ] supply_cap_change / signer_rotation 在 dev_ready / internal_test 必拒
- [ ] 1000 並發 approve 0 race condition
- [ ] proposal.payload 改動後 hash 不符 → service reject

---

## 11. 失敗訊息

| 情境 | 訊息 |
|---|---|
| 不是 signer | 「你不是此錢包的多簽人，無法簽章」 |
| 已簽章 | 「你已對此 proposal 簽章過，不可重複」 |
| proposal 過期 | 「此 proposal 已過期（{expires_at}），請建立新 proposal」 |
| signature 錯 | 「簽章驗證失敗，請確認使用正確 signer 私鑰」 |
| 未達門檻 | 「目前 approval {n}/{threshold}，未達門檻不可執行」 |
| incident_lockdown 中 | 「系統處於事故鎖定，僅允許 incident_lockdown_release proposal 執行」 |
| supply cap 不足 | 「mint 達 hard cap，需先 supply_cap_change proposal」 |

---

## 12. 相關文件

- [POINTSCHAIN_WHITEPAPER.md](POINTSCHAIN_WHITEPAPER.md)
- [POINTSCHAIN_ENGINEERING.md](POINTSCHAIN_ENGINEERING.md) §6
- [POINTS_WALLET_ADDRESSING.md](POINTS_WALLET_ADDRESSING.md)
- [POINTS_TRANSFER_API.md](POINTS_TRANSFER_API.md)
- [POINTSCHAIN_QA.md](POINTSCHAIN_QA.md)
- [SERVER_MODE_V2_PROFILE_MATRIX.md](../../../server_mode_v2/SERVER_MODE_V2_PROFILE_MATRIX.md) — incident_lockdown 行為
