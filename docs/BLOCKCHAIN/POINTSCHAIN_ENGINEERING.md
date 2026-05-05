# PointsChain Engineering v1

> **狀態：設計已拍板（root, 2026-05-04），尚未實作完成。**
> 本文件是 dev / qa 用的工程設計書；user-facing 版本見 [POINTSCHAIN_WHITEPAPER.md](POINTSCHAIN_WHITEPAPER.md)。

---

## 0. 拍板過的核心取捨

| 取捨 | 拍板結果 |
|---|---|
| 升級策略 | **漸進 v2 dual-write**，不另起 fork |
| 鏈化前提 | **Phase 0 清債** 已完成；進入 Phase 1 前仍需 root 對 `docs/BLOCKCHAIN/` 正式動工另行批准 |
| 託管模型 | **Hybrid Custody**，預設 custodial，self-custody opt-in |
| 官方錢包 | **永遠多簽**，禁止 root 一鍵 mint，連 internal_test 都不能 1-of-1 |
| Supply | **Hybrid hard cap**：Core Points 有 cap，Reward Pool 不在 cap 內；改 cap 須 3-of-5 multisig |
| Invariant | **boot-time gate + 每次 seal 區塊前 gate**；不過拒啟動 + 進 incident_lockdown |
| Incident Lockdown | **同時擋 trading / transfer / mint / multisig execute** |
| 地址格式 | `PNT1` + base58check（4-byte checksum） |
| 密鑰演算法 | **ed25519**（保留未來 secp256k1 擴充） |
| Nonce | **client UUID + per-address unique 約束 + timestamp window** |
| Transfer fee | 第一版 fee_rate=0；fee_pool / preview / event 路徑必須打通 |
| 既有 user wallet | **migration 自動建立 custodial primary address**，不需要手動 claim |
| Snapshot/Restore | **Chain 不 rollback**；restore 寫 `restore_marker` event；後續強制 reconcile |

---

## 1. 8-Phase 工程地圖

```
Phase 0  清債       ~1 週    blocker issues 收斂、isolated live API 驗證、runtime cleanup、full pytest
Phase 1  地址化     ~2 週    wallet_addresses + 9 official + supply_state
Phase 2  Ledger v2  ~3 週    address-centric + dual-write + state/supply root
Phase 3  Transfer   ~2 週    custodial only + UUID nonce + preview + fee path
Phase 4  Multisig   ~2.5 週  5-role signer + 3-of-5 mainnet / 2-of-3 internal_test
Phase 5  Self-cust  ~3 週    opt-in + 前端 ed25519 + 私鑰絕不上 server
Phase 6  Explorer   ~2 週    公開 + merkle proof + 手機版
Phase 7  QA Mining  ~3-4 週  公式 reward + multisig + signer 排除 + trust score
                   ~19-20 週 (~4.5-5 個月)
```

> Phase 0 cleanup closed. Phase 7 implementation blocked until Phase 1 / 2 / 4 / 6 complete and root separately authorizes Phase 7. 前置未完前只允許 DRAFT / mock / dry-run。
> 完整 Phase 7 設計見 [POINTS_MINING_REWARDS.md](POINTS_MINING_REWARDS.md)。

每個 phase 完成都必須過 [POINTSCHAIN_QA.md](POINTSCHAIN_QA.md) 的對應 gate 才能進下一個。

---

## 2. Phase 0：鏈化前清債

| 子任務 | 對應 issue | 規模 | 狀態 |
|---|---|---|---|
| backtest API 不再靜默 fetch binance 真實行情 | [#129](https://github.com/s9213712/hackme_web/issues/129) | S | ✅ **RESOLVED 2026-05-04** — route 改成 opt-in `auto_fetch_reference_candles=true`；`test_backtest_does_not_silently_replace_isolated_single_candle` PASS |
| backtest engine 套用 max_price_jump_percent | [#130](https://github.com/s9213712/hackme_web/issues/130) | M | ✅ **RESOLVED 2026-05-04** — 主迴圈加 jump check + warning + skipped count；`test_backtest_skips_outlier_jump_candles_instead_of_booking_fake_profit` PASS |
| BB std=0 邊界修正 | [#131](https://github.com/s9213712/hackme_web/issues/131) | S | ✅ **RESOLVED 2026-05-04** — `bb_std=0` 不產生穿越訊號；`bb_position` 改嚴格 `>` / `<`；`test_workflow_backtest_does_not_false_trigger_bollinger_on_flat_sequence` PASS |
| 30s polling gap 緩解 | [#122](https://github.com/s9213712/hackme_web/issues/122) | M | ✅ **RESOLVED 2026-05-04** — scan window 改看 high/low、`last_scan_at` 只在成功 scan 後更新、full pytest + live API 驗證通過 |
| NaN qty 例外字串外洩 (PB-1) | TBD | XS | ✅ **RESOLVED 2026-05-04** — service 層擋 non-finite + route 端訊息白名單化；`test_trading_order_invalid_decimal_is_sanitized_for_user` PASS |
| Bot audit dashboard 落地 | follow-up | M | ✅ **RESOLVED 2026-05-04** — root-only 稽核 dashboard、scheduler、未稽核守門、bug-report 整合都已上線（[`docs/TRADING_BOT_AUDIT.md`](../TRADING_BOT_AUDIT.md) 「目前範圍」表升級）|

**Phase 0 出口 gate**：原先的 blocker / recommend / low issues 都已收斂，isolated live API 驗證與 full pytest 全綠。
目前狀態是 **ALLOW PHASE 1 CANDIDATE**；root 若批准動工，可依 `IMPLEMENTATION_GUIDE.md` 開 `04.blockchain` 分支。

**進 Phase 1 條件（拍板）**：
- `#129/#130/#131/PB-1` 全 close ✅
- 交易 follow-up 測試 58/58 PASS ✅
- root 對 `docs/BLOCKCHAIN/` 的 Phase 1 動工另行批准

---

## 3. Phase 1：地址化基礎建設

### 3.1 新增 schema

```sql
CREATE TABLE points_wallet_addresses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,  -- NULL = 官方/系統地址
    address TEXT UNIQUE NOT NULL,                             -- PNT1 + base58check(pubkey_hash + checksum)
    wallet_type TEXT NOT NULL CHECK (wallet_type IN (
      'custodial','self_custody','official','multisig',
      'burn','mint','reserve','fee_pool','reward_pool',
      'dispute_escrow','trading_settlement','airdrop'
    )),
    public_key TEXT NOT NULL,                                  -- ed25519 hex (32 bytes = 64 hex chars)
    encrypted_wallet_secret TEXT,                              -- AES-GCM(server_master_key, per_user_salt)；burn/mint=NULL
    is_primary INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','frozen','revoked')),
    address_checksum TEXT NOT NULL,                            -- 4-byte hex
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_wallet_addresses_user_primary
    ON points_wallet_addresses(user_id, is_primary);

CREATE TABLE points_supply_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    chain_id TEXT NOT NULL DEFAULT 'hackme_points_chain_v1',
    initial_supply INTEGER NOT NULL,
    minted_supply INTEGER NOT NULL DEFAULT 0,
    burned_supply INTEGER NOT NULL DEFAULT 0,
    supply_cap INTEGER,                                        -- core points cap (NULL = no cap)
    last_invariant_check_at TEXT NOT NULL,
    last_invariant_check_pass INTEGER NOT NULL DEFAULT 1,
    last_invariant_diff INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
```

### 3.2 10 個官方地址（boot 時 INSERT IF NOT EXISTS）

| 常數 | 地址（範例 placeholder，正式生成時改） | wallet_type | 私鑰 |
|---|---|---|---|
| `OFFICIAL_TREASURY` | PNT1TREASURY... | official | multisig 控管 |
| `OFFICIAL_REWARD_POOL` | PNT1REWARD... | reward_pool | multisig 控管 |
| `OFFICIAL_FEE_POOL` | PNT1FEEPOOL... | fee_pool | system 自動入帳 |
| `OFFICIAL_RESERVE_POOL` | PNT1RESERVE... | reserve | multisig 2-of-3 |
| `OFFICIAL_EXCHANGE_FUND` | PNT1EXCHFUND... | exchange_fund | multisig 2-of-3（CFD 對坐 / PVP 做市；見 WHITEPAPER §3.6） |
| `OFFICIAL_MINT` | PNT1MINT... | mint | **NULL** |
| `OFFICIAL_BURN` | PNT1BURN... | burn | **NULL** |
| `OFFICIAL_AIRDROP` | PNT1AIRDROP... | airdrop | multisig 2-of-3 |
| `OFFICIAL_DISPUTE_ESCROW` | PNT1ESCROW... | dispute_escrow | multisig 2-of-3 |
| `OFFICIAL_TRADING_SETTLEMENT` | PNT1SETTLE... | trading_settlement | system 內部 |

實際地址在啟用前由 root 透過官方 multisig signer 流程公開生成並寫入 immutable 文件。

### 3.3 新增 API（Phase 1 唯讀為主）

| Method | Path | 用途 | 角色 |
|---|---|---|---|
| GET | `/api/points/wallet` | 回 `primary_address` + `addresses[]`（既有 endpoint 升級） | logged-in |
| GET | `/api/points/address/<address>` | 用地址查餘額 | self / admin / root |
| GET | `/api/points/explorer/summary` | total / circulating / burned / minted / latest_block_height | 匿名 |
| GET | `/api/admin/points/official-addresses` | 列 10 個官方地址狀態（含 EXCHANGE_FUND） | admin / root |
| POST | `/api/points/address/create` | self-custody 進階用戶建第二地址（保留路徑，Phase 5 啟用） | logged-in |

### 3.4 對既有系統影響

| 系統 | 改動 |
|---|---|
| Trading engine | fee 寫入時 dual-write `to_address=fee_pool`（不改主流程）|
| Snapshot manifest | 新增 `supply_state` row hash + `wallet_addresses` schema check |
| Server bootstrap | 新增「10 官方地址 INSERT IF NOT EXISTS」、「supply_state 初始化」 |
| Server mode | incident_lockdown 自動 freeze 高風險 wallet_type；boot-time invariant 不過 → 進 incident_lockdown |

### 3.5 Phase 1 出口 gate（細項見 POINTSCHAIN_QA.md §1）

- [ ] 每個既有 user 都有 1 筆 primary custodial address
- [ ] 10 個官方地址全 active；burn/mint 的 `encrypted wallet secret IS NULL`
- [ ] `points_supply_state.last_invariant_check_pass=1` 且 `_diff=0`
- [ ] address checksum 正確：1 萬筆隨機 mutate 1 byte 後 verify 必失敗
- [ ] 既有 trading / video / shop regression 全綠

---

## 4. Phase 2：Ledger v2

### 4.1 新增 schema

```sql
CREATE TABLE points_ledger_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE NOT NULL,                       -- UUID
    block_id INTEGER REFERENCES points_chain_blocks_v2(block_id),
    event_type TEXT NOT NULL CHECK (event_type IN (
      'mint','burn','transfer','transfer_fee','trade_buy','trade_sell','trade_fee',
      'reward','refund','escrow_lock','escrow_release','admin_adjustment',
      'dispute_payout','bot_trade','restore_marker','incident_marker','multisig_execute'
    )),
    from_address TEXT,                                   -- NULL only for mint
    to_address TEXT,                                     -- NULL only for burn
    amount INTEGER NOT NULL CHECK (amount > 0),
    fee_amount INTEGER NOT NULL DEFAULT 0,
    currency_type TEXT NOT NULL CHECK (currency_type = 'points'),
    reference_type TEXT,
    reference_id TEXT,
    memo_hash TEXT,                                      -- sha256(memo)；memo 不直存
    nonce TEXT NOT NULL,                                 -- client UUID
    payload_hash TEXT NOT NULL,                          -- sha256(canonical JSON)
    signature TEXT,                                      -- self_custody / multisig 才有
    previous_event_hash TEXT,
    event_hash TEXT NOT NULL UNIQUE,
    metadata_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(from_address, nonce)                          -- 防 replay
);

CREATE INDEX idx_ledger_v2_address_to ON points_ledger_v2(to_address, created_at);
CREATE INDEX idx_ledger_v2_address_from ON points_ledger_v2(from_address, created_at);
CREATE INDEX idx_ledger_v2_block ON points_ledger_v2(block_id);

CREATE TABLE points_chain_blocks_v2 (
    block_id INTEGER PRIMARY KEY AUTOINCREMENT,
    prev_hash TEXT NOT NULL,
    events_root TEXT NOT NULL,                           -- merkle root of event_hash
    state_root TEXT NOT NULL,                            -- merkle root of (address sorted, balance) snapshot
    supply_root TEXT NOT NULL,                           -- sha256(canonical(supply_state))
    block_hash TEXT NOT NULL UNIQUE,
    signer_address TEXT,                                 -- 鏈節點簽章（不是 user signer）
    signature TEXT,
    sealed_at TEXT NOT NULL,
    UNIQUE(prev_hash, sealed_at)
);
```

### 4.2 Canonical Payload 規範

每筆 ledger event 的 `payload_hash` 計算：

```python
canonical = {
    "chain_id": "hackme_points_chain_v1",
    "event_type": ...,
    "from_address": ... or "",
    "to_address": ... or "",
    "amount": str(int(amount)),         # integer string
    "fee_amount": str(int(fee_amount)),
    "currency_type": "points",
    "memo_hash": ... or "",
    "nonce": ...,
    "timestamp": ISO8601 UTC Z,
    "reference_type": ... or "",
    "reference_id": ... or "",
}
payload_bytes = json.dumps(canonical, sort_keys=True, separators=(',',':'), ensure_ascii=False).encode('utf-8')
payload_hash = sha256(payload_bytes).hexdigest()
```

### 4.3 Block seal 規範

每 block：
- 累積至 1000 events **或** 60 秒（取先到者）seal
- `events_root` = merkle(event_hash list, 順序 = id ASC)
- `state_root` = merkle((address, balance, currency_type), 順序 = address ASC tie-break by currency)
- `supply_root` = sha256(canonical(supply_state row))
- seal 前再驗 supply invariant；不過進 incident_lockdown

### 4.4 Dual-write 期

Phase 2 結束到 Phase 5 結束之間，每筆寫入：
1. 寫 v1 (既有 `points_ledger`)
2. 寫 v2 (`points_ledger_v2`)
3. 在同一 transaction 內；任一失敗整筆 rollback
4. nightly job 跑 v1 ↔ v2 diff，差異 > 0 自動 incident_lockdown

Phase 5 結束後切 v1 為 read-only archive，再 6 個月後 cold storage。

### 4.5 Phase 2 出口 gate

- [ ] dual-write 100 萬筆 0 不一致
- [ ] `replay_v2(address)` 結果 == `points_wallets` 對應 balance
- [ ] merkle proof endpoint：`GET /api/points/tx/<event_id>/proof` 可重組成 events_root
- [ ] state_root 算法不依賴 row insert order（測試：相同 events 不同順序產生相同 root）
- [ ] block seal 前 supply invariant 失敗會直接 ValueError 並進 incident_lockdown

---

## 5. Phase 3：Transfer (Custodial Only)

### 5.1 API

```
POST /api/points/transfer/preview
POST /api/points/transfer
GET  /api/points/transfers
GET  /api/points/tx/<event_id>
```

### 5.2 Transfer Request

```json
{
  "to_address": "PNT1abc...",
  "amount": "100",
  "currency_type": "points",
  "memo": "thanks",
  "client_nonce": "uuid",
  "timestamp": "2026-05-04T00:00:00Z"
}
```

### 5.3 規則（拍板）

- `from_address` = caller primary address
- `to_address` 必須 active；不可為 `OFFICIAL_BURN`、`OFFICIAL_MINT`（這兩個走獨立 API）
- amount > 0 且 ≤ wallet free balance（不算 frozen）
- **不可轉給自己**（即使 root 也不行；管理用途走 admin_adjustment）
- nonce 必須 UUID；per-address unique；timestamp 偏離 server time > 5 分鐘拒絕
- payload_hash 不重複
- 一筆 transfer 在 ledger_v2 寫：`transfer_out` + `transfer_in`，若有 fee 加 `transfer_fee` + `fee_pool_income`
- 當前 `fee_rate=0`，但 fee 計算路徑 + fee_pool event + preview 必須完整

### 5.4 Invariant

```
Δ(from) + Δ(to) + Δ(fee_pool) == 0
```

每筆 transfer 後的 supply_state 不變。

### 5.5 Phase 3 出口 gate（POINTSCHAIN_QA.md §3）

- [ ] 自動 100 筆 nonce replay 全拒
- [ ] burn / mint / 自己 / 不存在地址 / disabled 地址全拒
- [ ] preview 與 final 計算結果一致
- [ ] 1000 並發 transfer 無 invariant 破壞
- [ ] 大額轉帳 / 轉到官方 / 轉到陌生地址 UI 警告皆觸發

---

## 6. Phase 4：Multisig

### 6.1 Schema（拍板：3-of-5 / 5 角色）

```sql
CREATE TABLE points_multisig_wallets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    address TEXT UNIQUE NOT NULL REFERENCES points_wallet_addresses(address),
    name TEXT NOT NULL,
    threshold INTEGER NOT NULL CHECK (threshold >= 2),    -- 永遠 ≥ 2
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
    created_at TEXT NOT NULL
);

CREATE TABLE points_multisig_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT UNIQUE NOT NULL,
    wallet_address TEXT NOT NULL,
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
    signature TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    UNIQUE(proposal_id, signer_address)
);
```

### 6.2 門檻矩陣

| Action | mainnet | internal_test |
|---|---|---|
| mint | 3-of-5 | 2-of-3 |
| burn | 3-of-5 | 2-of-3 |
| treasury_transfer | 3-of-5 | 2-of-3 |
| reserve_transfer | 2-of-3 | 2-of-3 |
| reward_payout | 2-of-3 | 2-of-3 |
| dispute_payout | 2-of-3 | 2-of-3 |
| airdrop | 2-of-3 | 2-of-3 |
| incident_lockdown_release | 3-of-5 | 2-of-3 |
| supply_cap_change | 3-of-5 | 不允許 |
| signer_rotation | 3-of-5 | 不允許 |

**永遠 ≥ 2，永不接受 1-of-1**。

### 6.3 流程

1. 提案：root / admin POST `/api/admin/points/multisig/proposals` 帶 action_type + payload
2. 系統算 payload_hash + 設 expires_at（建議 72h）
3. signer 各自 POST `.../approve` 帶 signature
4. 達門檻 → status 改 `approved`，但 **不自動 execute**
5. proposer 或 signer POST `.../execute` 真實寫入
6. 寫 `multisig_execute` 到 ledger_v2 + chain block
7. expired / rejected 不可再被 approve

### 6.4 incident_lockdown 互動

- 進入 incident_lockdown 後**不可 execute** 任何 multisig（只能 propose / approve）
- 解除 incident_lockdown 本身就是一個 multisig action（3-of-5 mainnet）
- 解除前所有累積的 approved proposals 仍維持 pending；解除後才能 execute

### 6.5 Phase 4 出口 gate

- [ ] threshold-1 簽章必拒絕 execute（自動測 N-1）
- [ ] 過期 approval 無法復活
- [ ] 同一 signer 重複 approve 自動拒絕（UNIQUE 約束）
- [ ] 假 signature 必拒
- [ ] incident_lockdown 期間 execute 全拒（測 8 種 action_type）

---

## 7. Phase 5：Self-Custody

### 7.1 流程

1. user 在前端按「啟用自主錢包」
2. UI 強制顯示 2 段警告（遺失不可恢復、不可逆操作），勾選 + 倒數 30s 才能繼續
3. 前端用 `crypto.subtle` 產生 ed25519 keypair
4. private key **永遠不離開** browser；可選擇匯出 keystore（AES-GCM 加密；用戶設密碼）
5. 平台只接收 public_key 與簽章請求
6. 後續轉帳 payload 用 ed25519 在前端簽，server 僅驗 signature + nonce + payload_hash

### 7.2 Canonical Payload (簽章用)

```json
{
  "chain_id": "hackme_points_chain_v1",
  "action": "transfer",
  "from": "PNT1...",
  "to": "PNT1...",
  "amount": "100",
  "currency_type": "points",
  "memo_hash": "...",
  "nonce": "uuid",
  "timestamp": "2026-05-04T00:00:00Z"
}
```

`json.dumps(payload, sort_keys=True, separators=(',',':'), ensure_ascii=False).encode('utf-8')`

### 7.3 私鑰安全紅線

- **禁止**：private key 出現在任何 log、stack trace、API response、`secure_audit` event、bug-report
- **禁止**：private key 寫進 `.env`、DB 任何欄位
- 前端匯出 keystore 必須二次確認 + 警告 + 倒數
- pentest 必須包含「故意觸發 ValueError 看是否帶 private key」

### 7.4 Custodial → Self-Custody 切換

- 不可逆（或設可逆但保留 audit + 二次確認）
- 切換時餘額不動，只改 `wallet_type` 與 `encrypted wallet secret`（後者改 NULL）

### 7.5 Phase 5 出口 gate

- [ ] 1000 筆 mutated payload 簽章必拒
- [ ] nonce replay 必拒
- [ ] grep 整個 server log 0 個 private key 字樣出現
- [ ] keystore 匯出 UI 含 2 警告 + 倒數
- [ ] custodial → self_custody 後 keystore 可在另一裝置匯入並轉帳成功

---

## 8. Phase 6：Explorer

### 8.1 頁面

| 路徑 | 內容 | 匿名 |
|---|---|---|
| `/points/explorer` | total / circulating / burned / minted / latest blocks | ✅ |
| `/points/address/<address>` | 餘額 + 進出歷史 | 自己或官方地址 ✅；別人 ❌ |
| `/points/tx/<event_id>` | event 詳情 + merkle proof | ✅ |
| `/points/block/<block_id>` | block header + events 列表 | ✅ |
| `/points/multisig` | proposal 佇列 | admin/root ✅ |

### 8.2 Performance gate

- 10k events 場景下 query p95 < 1s
- mobile RWD 通過（420/480/560/720/860/900/1100/1320 breakpoint）
- merkle proof endpoint 對任意 event_id 都能拼 events_root

### 8.3 顯示規則

- 數字直接顯示百分比 / 整數 POINTS，不用一般使用者看不懂的費率縮寫
- 官方地址有人類可讀 badge（例：「平台手續費池」）
- 大額 / 異常事件用顏色標示但不阻止顯示

---

## 8a. Phase 7：QA Mining / Contribution Rewards

**狀態：Design approved (root, 2026-05-04). Phase 0 cleanup closed. Phase 7 implementation blocked until Phase 1 / 2 / 4 / 6 complete and root separately authorizes Phase 7.**

完整設計與 schema / API / gate 見 [POINTS_MINING_REWARDS.md](POINTS_MINING_REWARDS.md)。本章只列工程整合要點。

### 8a.1 依賴

| 來自 phase | 提供 |
|---|---|
| Phase 0 | 清債讓錯誤計算不被永久寫入鏈 |
| Phase 1 | `OFFICIAL_REWARD_POOL` address |
| Phase 2 | address-centric ledger_v2 + chain_block_v2 |
| Phase 4 | reward ≥ 1000 / retroactive batch / burn 罰金的多簽路徑 + signer 自動排除自己 |
| Phase 6 | explorer 公開介面 |

### 8a.2 7 張新表 + bug_reports 升級

詳 [POINTS_MINING_REWARDS.md §16](POINTS_MINING_REWARDS.md)：

```
points_mining_tasks
points_mining_claims              -- 與 bug_reports 透過 reference_id 連
points_mining_claim_splits        -- reporter/verifier/fixer 分潤
points_mining_trust_state
points_mining_budget_state
points_mining_user_quota
points_reward_payouts

bug_reports.is_mining_eligible    -- ALTER 既有表
bug_reports.mining_claim_id
bug_reports.severity
```

### 8a.3 新 ledger_v2 event_type

補入 §4.1 的 CHECK list：

```
'mining_claim_submitted', 'mining_claim_approved', 'mining_claim_rejected',
'mining_payout', 'mining_pool_refill', 'mining_burn_penalty', 'mining_trust_adjusted'
```

### 8a.4 新 multisig action_type

補入 [MULTISIG_WALLETS.md §4](MULTISIG_WALLETS.md) action 列：

```
'mining_reward_payout'        # 大額單筆 ≥ 1000
'mining_retroactive_batch'    # 追溯獎勵
'mining_pool_refill'          # treasury → reward_pool
'mining_burn_penalty'         # 罰金（第一版仍要人工提案）
'mining_signer_quarantine'    # 違規 signer 暫停
```

### 8a.5 Multisig signer 自動排除

multisig service 對 mining 相關 proposal 做：

```python
def effective_signers_for_mining(proposal, all_signers):
    payee_ids = {split.payee_user_id for split in proposal.splits} | {proposal.reporter_user_id}
    return [s for s in all_signers if s.signer_user_id not in payee_ids]
```

若 effective signers 不夠 threshold → proposal status 進 `awaiting_independent_signer`。

### 8a.6 對既有路徑影響

| 系統 | 改動 |
|---|---|
| `routes/bug_reports.py` | review 流程加標註 mining 是否啟用、severity 欄位、雙人審核狀態機 |
| `services/trading_engine.py` 黃燈 audit | 提供「一鍵提 bug」自動帶入 bot_uuid/order_uuid/diff |
| `services/snapshots.py` | snapshot 含 mining tables；restore 後 mining_claim 不可被覆寫已 paid 狀態 |
| `services/server_mode` incident_lockdown | 期間擋 mining payout execute |

### 8a.7 Phase 7 出口 gate

詳 [POINTSCHAIN_QA.md §9 Phase 7 Gate](POINTSCHAIN_QA.md)。25 項涵蓋公式 / 紅線 / 雙人 / multisig signer 排除 / cap / trust / FP / retroactive / anti-Sybil / burn 限制 / explorer / mobile。

---

## 9. 與既有系統的相依

| 系統 | 改動 | 哪一 phase |
|---|---|---|
| `services/trading_engine.py` | fee dual-write 進 fee_pool；trade event 寫 ledger_v2 | Phase 2-3 |
| `services/points_chain.py` | invariant boot gate；block 加 state_root/supply_root | Phase 1-2 |
| `services/snapshots.py` | manifest 含 v2 ledger + supply_state hash；restore 寫 marker；reconcile gate | Phase 2 |
| `services/videos.py` | tip 寫 v2 transfer event | Phase 3 |
| `services/cloud_drive.py` 商城路徑 | 商城購買 / 糾紛 escrow_lock/release 寫 v2 | Phase 3-4 |
| 機器人 / DCA / Grid | bot_trade 寫 v2 | Phase 2 |
| `services/auth.py` 註冊送點 | mint / reward 寫 v2 | Phase 2 |
| `services/snapshots.py` server mode | incident_lockdown 自動 freeze multisig execute；production gate 加 supply invariant 必過 | Phase 1 / 4 |
| `routes/economy.py` `/api/points/*` | 加 address-aware endpoints；保留 user_id-based 為 dual-key 過渡 | Phase 1+ |

---

## 10. 風險與回滾

| 風險 | 緩解 |
|---|---|
| dual-write 失敗 → v1/v2 不一致 | 同 transaction 包裹；nightly diff job；diff>0 自動 incident_lockdown |
| ed25519 lib bug | 用 `cryptography` 套件（已在 requirements.txt）；不自己實作 |
| migration 給既有 user 建地址失敗 | 採批次 + 可重跑 + 失敗 user 不影響其他 user；migration 報告寫入 audit |
| supply invariant boot 失敗無法救回 | 提供「離線 reconcile + 手動覆蓋」CLI（root 動執行 + 多簽核可後寫 incident_marker）|
| Phase 2 dual-write 影響效能 | 寫入路徑 transaction 內 batch；測試 1000 TPS 場景 |
| 前端 ed25519 在舊瀏覽器不支援 | 啟用 self-custody 前先 capability check；不支援的瀏覽器禁啟用 |

回滾策略：每個 phase 都有「不啟用 v2 路徑」的 feature flag（沿用既有 `feature_*_enabled` 機制）。緊急時可關 flag 退到 dual-write 期前。

---

## 11. UI / UX 必做（Phase 對應）

對齊 root §I 要求：

| UI 元件 | Phase | 必須 |
|---|---|---|
| 使用者錢包頁（顯示地址 + 餘額 + 切換 primary） | 1 | mobile RWD |
| 轉帳頁 + preview + fee 顯示 | 3 | 大額 + burn + 官方地址 + 陌生地址警告 |
| 官方地址 badge | 1 | explorer + 轉帳 preview 都顯示 |
| Burn 高風險二次確認 | 3 | 倒數 + 勾選 |
| Self-custody 啟用警告 | 5 | 2 警告 + 倒數 30s |
| Explorer | 6 | 公開、手機版、p95 < 1s |
| Multisig proposal 後台 | 4 | 列 status / approvers / expires_at |
| Supply invariant 狀態燈 | 1 | admin 後台 dashboard 綠/黃/紅 |
| incident_lockdown 紅燈 | 1+ | 全站頂部 banner |
| 手機版 | all | 所有新頁面 |

---

## 12. 文件 / 測試 / 觀測同步矩陣

每個 phase 完成都需同步：

| Phase | README | pytest | smoke / pentest | 觀測 |
|---|---|---|---|---|
| 0 | TRADING.md / TRADING_BOT_AUDIT.md 章節 | tests/test_trading_engine 三件回歸 | 不適用 | 既有 audit chain |
| 1 | POINTS_WALLET_ADDRESSING.md | test_wallet_addresses, test_supply_invariant | smoke_official_addresses | supply_state dashboard |
| 2 | POINTSCHAIN_ENGINEERING.md (本文) §4 + 07_POINTSCHAIN.md 章節 | test_ledger_v2_replay, test_ledger_v2_dual_write | smoke_dual_write_consistency | per-block state_root delta |
| 3 | POINTS_TRANSFER_API.md | test_transfer_handcalc, test_nonce_replay | smoke_transfer_invariant | transfer rate / minute |
| 4 | MULTISIG_WALLETS.md | test_multisig_threshold, test_multisig_replay_attack | smoke_multisig_proposal | proposal queue depth |
| 5 | POINTS_SELF_CUSTODY.md | test_self_custody_signature, test_secret_redaction | pentest_signature_bypass | signature failure rate |
| 6 | （Explorer 內建說明） | test_explorer_endpoints, test_merkle_proof | smoke_explorer_query | explorer query p95 |

每個 phase 完成同步更新：README.md / 03_ADMIN_GUIDE.md / 08_TRADING_ENGINE.md / TRADING_BOT_AUDIT.md / 09_SNAPSHOT_RESET_RESTORE.md / SECURITY_MODES.md。

---

## 13. 時程

| Phase | 預估 |
|---|---|
| 0 | ~1 週 |
| 1 | ~2 週 |
| 2 | ~3 週 |
| 3 | ~2 週 |
| 4 | ~2.5 週 |
| 5 | ~3 週 |
| 6 | ~2 週 |
| **7 (QA Mining)** | **~3-4 週** |
| **Total** | **~18.5-19.5 週 (~4.5-5 個月)** |

單線推進，避免 race condition。

---

## 14. 不變的最終原則

> 不要把錯誤上鏈。不要把錯誤永久化。不要讓區塊鏈變成 bug 的永久保存器。

- 所有 phase 出口 gate 不過就不能進下個 phase
- supply invariant 永遠 boot-time + seal-time 雙守護
- multisig 永遠 ≥ 2，連 internal_test 也不破例
- private key 永遠不離 browser（self-custody）／永遠加密存（custodial）
- incident_lockdown 永遠擋 trading / transfer / mint / multisig execute

---

*Engineering v1 by Claude，root 拍板 2026-05-04。*
