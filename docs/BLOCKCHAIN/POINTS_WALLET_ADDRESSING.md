# PointsChain Wallet Addressing v1

> **狀態：設計已拍板（root, 2026-05-04），尚未實作完成。**
> 屬於 [POINTSCHAIN_ENGINEERING.md](POINTSCHAIN_ENGINEERING.md) Phase 1 規格。

---

## 1. 設計目的

讓每個積分流向有「明確地址」可追蹤，而不是隱形的 user_id：

- 用戶之間互轉、官方獎勵、平台抽成都有明確 from→to
- 官方地址有顯性 badge，避免被冒充
- 支援未來 self-custody 與多簽錢包

---

## 2. 地址格式

```
PNT1 + base58check(version_byte || pubkey_hash || checksum)
```

具體：

| 欄位 | 長度 | 內容 |
|---|---|---|
| `PNT1` | 4 chars | human prefix |
| `version_byte` | 1 byte | `0x00` for v1 mainnet；保留 `0x01` 做未來 testnet |
| `pubkey_hash` | 20 bytes | RIPEMD160(SHA256(public_key)) |
| `checksum` | 4 bytes | SHA256(SHA256(version_byte ‖ pubkey_hash))[:4] |

整體 base58 編碼後約 **32–34 字元**（含 PNT1 prefix）。

範例：

```
PNT1ab8K9XBpL3xRsAFc4eYqZ2NvgC5W7DPmTk
```

### 2.1 為什麼 base58check 不用 hex / bech32

- base58 易讀（去掉 `0OIl` 易混淆字元）
- check 機制讓「打錯一個字」必拒絕
- 對齊一般用戶對加密資產的視覺直覺

### 2.2 為什麼 ed25519

- 簽章快、實作簡潔，適合 permissioned chain
- 前端 `crypto.subtle` 支援
- 保留未來支援 secp256k1（version_byte 0x02 留給 secp256k1 mainnet）

---

## 3. 地址不可暴露 user_id

絕對禁止：
- `address = "PNT1user_" + user_id`
- `address = "PNT1" + base58(user_id)`

地址必須由 random ed25519 keypair 衍生；user_id ↔ address 對映只在後台 DB 中存在，不從地址本身可逆推。

---

## 4. Schema

```sql
CREATE TABLE points_wallet_addresses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,  -- NULL = 官方/系統地址
    address TEXT UNIQUE NOT NULL,
    wallet_type TEXT NOT NULL CHECK (wallet_type IN (
      'custodial','self_custody','official','multisig',
      'burn','mint','reserve','fee_pool','reward_pool',
      'dispute_escrow','trading_settlement','airdrop'
    )),
    public_key TEXT NOT NULL,                                  -- ed25519 hex (64 chars)
    encrypted_wallet_secret TEXT,                              -- AES-GCM；burn/mint=NULL
    is_primary INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','frozen','revoked')),
    address_checksum TEXT NOT NULL,                            -- 4-byte hex (重複存供快查)
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_wallet_addresses_user_primary
    ON points_wallet_addresses(user_id, is_primary);
CREATE INDEX idx_wallet_addresses_type
    ON points_wallet_addresses(wallet_type, status);
```

---

## 5. 10 個官方地址

啟用 Phase 1 時，由 root 透過官方 multisig signer 流程公開生成 10 組 keypair，並在啟用前公告於 explorer 與 README。地址產生後寫入 immutable 文件，不再變更。

| 常數名 | wallet_type | 用途 | 私鑰 |
|---|---|---|---|
| `OFFICIAL_TREASURY` | `official` | 平台總庫 | multisig |
| `OFFICIAL_REWARD_POOL` | `reward_pool` | 任務 / 活動獎勵發放來源 | multisig |
| `OFFICIAL_FEE_POOL` | `fee_pool` | 平台抽成累計 | multisig（出帳時） |
| `OFFICIAL_RESERVE_POOL` | `reserve` | 市場儲備 / 做市 | multisig |
| `OFFICIAL_EXCHANGE_FUND` | `exchange_fund` | 交易所基金（CFD 對坐 / PVP 做市現貨；見 WHITEPAPER §3.6） | multisig 2-of-3 |
| `OFFICIAL_MINT` | `mint` | 增發發行端 | **NULL**（無私鑰） |
| `OFFICIAL_BURN` | `burn` | 燒毀終點 | **NULL**（無私鑰） |
| `OFFICIAL_AIRDROP` | `airdrop` | 活動 / 空投發放 | multisig |
| `OFFICIAL_DISPUTE_ESCROW` | `dispute_escrow` | 商城糾紛暫管 | multisig 釋放 |
| `OFFICIAL_TRADING_SETTLEMENT` | `trading_settlement` | 撮合過程清算 | system 內部簽 |

### 5.1 雙保險：burn / mint 不可寫入私鑰路徑

不論 schema 怎麼演化，以下硬規則：

- 任何 `INSERT INTO points_wallet_addresses` 對 `wallet_type IN ('burn','mint')` 的 row，`encrypted wallet secret` 必須為 NULL；違反直接 `IntegrityError`
- 任何 `points_ledger_v2` 寫入 `from_address = OFFICIAL_BURN` 直接 `ValueError`（即使 service 層 bug 也擋住）

### 5.2 boot-time 自動建立

server bootstrap 時：

```python
for const_name, address in OFFICIAL_ADDRESSES.items():
    cur = conn.execute("SELECT 1 FROM points_wallet_addresses WHERE address=?", (address,))
    if not cur.fetchone():
        conn.execute("INSERT INTO points_wallet_addresses (...)")
```

不允許 root 在 runtime 改動官方地址 row（schema-level CHECK 或 trigger）。

---

## 6. 既有 user 的 migration

Phase 1 啟用時：

1. 對所有現有 user 跑 batch migration script
2. 為每個 user 產 ed25519 keypair → 存 `wallet_type='custodial', is_primary=1`
3. private key 用 AES-GCM(server_master_key, per_user_salt) 加密存
4. migration 失敗的 user 進報告，不影響其他 user
5. 完成後 `points_wallets.user_id` 與 `points_wallet_addresses.user_id` 一一對應

migration 可重跑（idempotent）：已有 primary address 的 user 跳過。

---

## 7. Address Checksum 與 Frontend Preview

任何接受 `to_address` 的 API 與前端表單都必須：

1. 解 base58 → 取 version_byte / pubkey_hash / checksum
2. 重算 SHA256(SHA256(...))[:4]
3. 不符就 reject 並提示「地址 checksum 錯誤」
4. 即使 API 沒拒絕，前端 preview 也必須再查一次

對齊 root §I：「前端轉帳 preview 必須顯示地址類型」。

### 7.1 地址類型 badge（前端必須）

| `wallet_type` | badge | 顏色提示 |
|---|---|---|
| custodial | （無 badge） | 一般 |
| self_custody | 「自主錢包」 | 灰 |
| official | 「官方地址」 | 藍 |
| multisig | 「多簽」 | 紫 |
| burn | 「⚠ 燒毀地址 ⚠」 | 紅 + 二次確認 |
| mint | 「不可轉入」 | 紅（直接拒絕轉入）|
| reward_pool / fee_pool / reserve / airdrop / dispute_escrow / trading_settlement | 對應人類可讀名稱 | 藍 |

---

## 8. API（Phase 1）

| Method | Path | Notes |
|---|---|---|
| GET | `/api/points/wallet` | 既有 endpoint 升級；回 `primary_address`、`addresses[]`、`balances` |
| GET | `/api/points/address/<address>` | 自己 address 看完整餘額；別人 address 看是否 active 與類型（不看餘額） |
| GET | `/api/points/explorer/summary` | 匿名可呼叫；回 supply_state |
| GET | `/api/admin/points/official-addresses` | admin 看 9 官方地址狀態 |
| POST | `/api/points/address/create` | self-custody 進階用戶建第二地址（Phase 5 才啟用，Phase 1 預留路徑） |

### 8.1 Response 範例

```json
GET /api/points/wallet
{
  "ok": true,
  "primary_address": "PNT1ab8K...",
  "addresses": [
    {
      "address": "PNT1ab8K...",
      "wallet_type": "custodial",
      "is_primary": true,
      "status": "active",
      "balances": {"points": 5010, "points_frozen": 0}
    }
  ],
  "supply_state": {
    "total_supply": 1000000,
    "circulating_supply": 500000,
    "burned_supply": 0,
    "minted_supply": 0
  }
}
```

---

## 9. Supply State 與 Invariant

詳 [POINTSCHAIN_ENGINEERING.md §3.1](POINTSCHAIN_ENGINEERING.md)。

```
total_supply == initial_supply + minted_supply − burned_supply
total_supply == Σ user balances + Σ official balances + Σ frozen + burned_supply
```

server 啟動時、每次 seal 區塊前驗。失敗 → 進 incident_lockdown。

---

## 10. UI 對應（Phase 1）

| 元件 | 內容 |
|---|---|
| 個人頁「我的錢包地址」欄 | 顯示 primary_address + 「複製」按鈕 + QR code（可選） |
| 官方地址 badge | 在所有 ledger 顯示處（影片投幣紀錄、商城紀錄、交易紀錄）出現官方地址都顯示 badge |
| 後台 supply 狀態燈 | 綠（invariant 過）/ 黃（diff 但 < 容忍）/ 紅（diff 超容忍 → 進 incident_lockdown）|
| 手機版 | 所有上述頁面 RWD |

---

## 11. QA Gate（細項見 [POINTSCHAIN_QA.md §1](POINTSCHAIN_QA.md)）

- [ ] 每個既有 user 都有 1 筆 primary custodial address
- [ ] 9 官方地址全 active；burn/mint 的 `encrypted wallet secret IS NULL`
- [ ] address checksum：1 萬筆隨機 mutate 1 byte 必拒絕
- [ ] address 不可重複（migration 100k user 0 衝突）
- [ ] supply invariant boot-time pass
- [ ] 嘗試 INSERT burn/mint 加 private key 必觸發 IntegrityError
- [ ] 嘗試寫 `from_address=OFFICIAL_BURN` 的 ledger event 必 ValueError
- [ ] 前端 preview 顯示官方 badge 與類型
- [ ] mobile RWD 通過

---

## 12. 失敗情境與提示

| 情境 | 提示 |
|---|---|
| 用戶輸入錯誤 address checksum | 「地址 checksum 錯誤，請檢查是否打錯字」|
| 用戶轉到不存在地址 | 「目標地址不存在，請確認後再試」|
| 用戶轉到 burn 地址 | 紅色警告：「這是燒毀地址，POINTS 將永久銷毀，無法找回。請使用「燒毀」功能而非一般轉帳。」|
| 用戶轉到 mint 地址 | 直接 reject「不可轉入此地址」|
| migration 對既有 user 失敗 | admin 後台顯示失敗清單 + 重跑按鈕 |
| supply invariant 不過 | 系統進 incident_lockdown；admin 收到通知；root 必須走 multisig 解除 |

---

## 13. 相關文件

- [POINTSCHAIN_WHITEPAPER.md](POINTSCHAIN_WHITEPAPER.md) — user-facing 概念
- [POINTSCHAIN_ENGINEERING.md](POINTSCHAIN_ENGINEERING.md) — 整體 7-phase 設計
- [POINTS_TRANSFER_API.md](POINTS_TRANSFER_API.md) — 轉帳 API（Phase 3）
- [MULTISIG_WALLETS.md](MULTISIG_WALLETS.md) — 多簽（Phase 4）
- [POINTSCHAIN_QA.md](POINTSCHAIN_QA.md) — QA / Release Gate
- [07_POINTSCHAIN.md](../07_POINTSCHAIN.md) — v1 既有概念
