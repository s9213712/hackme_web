# 提案：PointsChain On-Ramp（BSC USDT → Points）

> **狀態：DRAFT — pending root approval (drafted 2026-05-14)。**
> 提案位置依 [BLOCKCHAIN/IMPLEMENTATION_GUIDE.md §0.3](BLOCKCHAIN/IMPLEMENTATION_GUIDE.md) 規定，放在 `BLOCKCHAIN/` 資料夾**外**，root 拍板後再由指定 agent 升級進 canonical 規格。
> 動工授權須 root 個別簽核；本文件本身不構成動工授權。
> 規模定位：**小型社群正式營運**（依使用者明示）。

---

## 1. 問題 / 動機

目前 PointsChain v2（[BLOCKCHAIN/README.md](BLOCKCHAIN/README.md)）的設計範圍是「站內 permissioned 私鏈」，使用者沒有任何途徑可以用站外加密資產換取站內 points。實務上，營運站台希望讓使用者用 imToken / 其他 BEP-20 相容錢包，**單向把 BSC USDT 充值換成站內 points**，作為主要的點數獲取管道之一。

這條路徑是 PointsChain v2 設計裡沒有的功能：

- [POINTSCHAIN_WHITEPAPER.md §3.6](BLOCKCHAIN/POINTSCHAIN_WHITEPAPER.md) 的 `OFFICIAL_EXCHANGE_FUND` 只規範**站內 trading 的對坐 / 做市資金**，沒有規範**站外資產 → 站內 points 的入金路徑**。
- [POINTS_MONETARY_POLICY.md](BLOCKCHAIN/) 仍是 Draft / blocked，不能用「mint 新點」走這條入金。
- 既有 economy.py / points_chain/service.py 完全沒有外部鏈整合層。

本提案補上這個缺口，定義一條符合既有紅線（不自動 mint、不破壞 supply invariant、不單人濫權、不洩漏個資）的 USDT 入金路徑。

---

## 2. 名稱與 Phase 定位

- 暫名：**Phase 3B — On-Ramp (External Asset → Points)**
- 與既有 phase 的關係：依賴 Phase 1（地址化）、Phase 1A（observability）、Phase 2（ledger v2），與 Phase 3（站內 transfer）並行但 schema 獨立。建議 **Phase 1 + 1A + 2 完成且 root 個別授權後**才動工，**不晚於 Phase 4 multisig 完成**（因為 vault refill / sweep 都需要 multisig 路徑）。
- 不屬於 PointsChain MVP 核心；可在 root 授權下作為與 Phase 3 並行的獨立軌道。

---

## 3. 我建議的設計

### 3.1 資金與帳務模型（核心）

採用**全儲備穩定幣模型**：

```
站內 ONRAMP_VAULT.points_balance × 1 / exchange_rate
   ≤ 站外冷錢包 USDT 餘額 + pending sweep
```

任何時刻都要驗，類似 [POINTSCHAIN_ENGINEERING.md §2A.3](BLOCKCHAIN/POINTSCHAIN_ENGINEERING.md) 的 `exchange_fund_health` 守門。

整體流程：

```
[User in imToken]
   │ 1. 站台前端顯示「請傳 X USDT 到地址 0xABC…」（per-user 唯一地址 + QR code + 倒數）
   ▼
[BSC 鏈上 USDT (BEP-20) transfer event]
   │
   │ 2. ChainWatcher 服務輪詢 BSC RPC，匹配 transfer.to ∈ 我們的地址池
   ▼
[points_onramp_deposits row: status='detected']
   │
   │ 3. 達 confirmations_required (建議 15 blocks)
   ▼
[status='pending_credit'] → Sanctions / risk 篩查
   │
   │ 4a. 通過 → ledger_v2 寫入 (from=ONRAMP_VAULT, to=user_primary_address)
   │ 4b. 不通過 → status='manual_review'，等 root multisig 處理
   ▼
[status='credited' + ledger_event_id]
   │
   │ 5. 定期 sweep：USDT 從散戶地址歸集到冷錢包 (multisig 2-of-3)
   ▼
[Cold wallet USDT 累積]
   │
   │ 6. 對帳：ONRAMP_VAULT.points_balance × rate ?= 冷錢包 USDT 餘額（每日 reconcile job）
   ▼
[Reserve attestation — explorer 公開]
```

### 3.2 新增官方地址：`OFFICIAL_ONRAMP_VAULT`（需 root 核准）

> ⚠ 此項**修改既有設計取捨**：[POINTS_WALLET_ADDRESSING.md §5](BLOCKCHAIN/POINTS_WALLET_ADDRESSING.md) 規定 10 個官方地址固定。本提案請求**新增第 11 個官方地址**，故需 root 個別拍板。

| 屬性 | 值 |
|---|---|
| 常數名 | `OFFICIAL_ONRAMP_VAULT` |
| 地址範例 | `PNT1ONRAMP...` |
| `wallet_type` | `'onramp_vault'`（**新 wallet_type，需擴充 CHECK 約束**） |
| 私鑰 | multisig 2-of-3（finance_admin + emergency_recovery_admin + qa_release_admin）|
| 初始注入 | 從未分配的 5% 保留池（[WHITEPAPER §3.5](BLOCKCHAIN/POINTSCHAIN_WHITEPAPER.md)）撥出 X%，由 root 在 genesis block 公告 |
| 流出方式 | (a) 自動 credit 路徑（受 §3.4 守門）；(b) 多簽 2-of-3 手動移轉 |
| 流入方式 | 多簽 refill 提案（當 vault 餘額低於 threshold 時觸發）|

**為什麼不重用 EXCHFUND**：EXCHFUND 的會計語意已被 [WHITEPAPER §3.6](BLOCKCHAIN/POINTSCHAIN_WHITEPAPER.md) 鎖定為 CFD 對坐 / PVP 做市資金，混入 user-deposit-backed liability 會破壞 `exchange_fund_health` 計算（denominator 會變不可解釋）。新增專屬 vault 較乾淨。

**為什麼不 mint**：[BLOCKCHAIN/README.md §6](BLOCKCHAIN/README.md) 明定「獎勵不是印鈔 → 不允許自動 mint」。任何「USDT 入金 → 自動 mint points」的設計都直接踩紅線。

### 3.3 Schema 新增（鏈分支：`04.blockchain` 內子 phase）

```sql
-- 用戶的鏈上接收地址（HD wallet 衍生）
CREATE TABLE points_onramp_receive_addresses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chain TEXT NOT NULL CHECK (chain IN ('bsc')),       -- 預留 'tron','polygon'
    address TEXT UNIQUE NOT NULL,                        -- EIP-55 checksum 0x...
    derivation_path TEXT NOT NULL,                       -- m/44'/60'/0'/0/<idx>
    derivation_idx INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (
        status IN ('active','retired','frozen')
    ),
    created_at TEXT NOT NULL,
    UNIQUE(chain, derivation_idx)
);

-- 入金 tx 紀錄（idempotent，防 replay）
CREATE TABLE points_onramp_deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    chain TEXT NOT NULL,
    token_symbol TEXT NOT NULL,
    token_contract TEXT NOT NULL,                        -- USDT BSC: 0x55d398326f99059fF775485246999027B3197955
    receive_address TEXT NOT NULL,
    sender_address TEXT NOT NULL,
    tx_hash TEXT NOT NULL,
    block_number INTEGER,
    log_index INTEGER NOT NULL,
    amount_token TEXT NOT NULL,                          -- decimal string；USDT BSC 18 decimals
    amount_points INTEGER NOT NULL,
    exchange_rate TEXT NOT NULL,                         -- "100" = 1 USDT → 100 points
    fee_points INTEGER NOT NULL DEFAULT 0,               -- 平台抽成（如有）
    status TEXT NOT NULL CHECK (status IN (
        'detected','pending_confirmation','pending_risk_check',
        'pending_credit','credited',
        'reorged','manual_review','refunded','rejected'
    )),
    confirmations INTEGER NOT NULL DEFAULT 0,
    risk_score INTEGER,
    risk_flags_json TEXT,                                -- ["ofac_sanctions","mixer", ...]
    risk_provider TEXT,                                  -- 'chainalysis_free' / 'trm' / 'manual'
    ledger_event_id TEXT,                                -- → points_ledger_v2.event_id
    refund_tx_hash TEXT,                                 -- 退款時填
    first_seen_at TEXT NOT NULL,
    confirmed_at TEXT,
    risk_checked_at TEXT,
    credited_at TEXT,
    UNIQUE(chain, tx_hash, log_index)
);

CREATE INDEX idx_onramp_deposits_user ON points_onramp_deposits(user_id, status);
CREATE INDEX idx_onramp_deposits_status ON points_onramp_deposits(status, first_seen_at);
CREATE INDEX idx_onramp_deposits_address ON points_onramp_deposits(receive_address);

-- 鏈設定 / 匯率 / 限額
CREATE TABLE points_onramp_config (
    chain TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    rpc_url_encrypted TEXT NOT NULL,                     -- AES-GCM；不可寫純文字
    confirmations_required INTEGER NOT NULL DEFAULT 15,
    min_deposit_token TEXT NOT NULL,                     -- "1.0"
    max_deposit_per_tx_token TEXT,                       -- "500"
    daily_limit_per_user_token TEXT,                     -- "1000"
    monthly_limit_per_user_token TEXT,                   -- "5000"
    exchange_rate TEXT NOT NULL,                         -- "100"
    fee_basis_points INTEGER NOT NULL DEFAULT 0,         -- 抽成 basis points (0 = 不抽)
    kyc_threshold_token TEXT,                            -- 觸發強化 KYC 的累計門檻
    sanctions_provider TEXT NOT NULL DEFAULT 'chainalysis_free',
    cold_wallet_address TEXT NOT NULL,                   -- sweep 目的地
    sweep_threshold_token TEXT,                          -- 散戶地址超過此值即排程 sweep
    updated_at TEXT NOT NULL,
    updated_by INTEGER REFERENCES users(id)
);

-- Watcher state（避免重啟漏掃）
CREATE TABLE points_onramp_chain_state (
    chain TEXT PRIMARY KEY,
    last_scanned_block INTEGER NOT NULL,
    last_scan_at TEXT NOT NULL,
    rpc_health TEXT NOT NULL CHECK (rpc_health IN ('green','yellow','red')),
    backlog_blocks INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);

-- 對帳記錄（每日一筆）
CREATE TABLE points_onramp_reserve_attestations (
    attestation_date TEXT PRIMARY KEY,
    onramp_vault_points_balance INTEGER NOT NULL,
    onramp_vault_implied_usdt TEXT NOT NULL,             -- balance / rate
    cold_wallet_usdt_balance TEXT NOT NULL,
    pending_sweep_usdt TEXT NOT NULL,
    reserve_health REAL NOT NULL,                        -- (cold + pending) / implied
    status TEXT NOT NULL CHECK (status IN ('green','yellow','red')),
    generated_at TEXT NOT NULL,
    notes TEXT
);
```

新增 wallet_type：在 [POINTS_WALLET_ADDRESSING.md §4](BLOCKCHAIN/POINTS_WALLET_ADDRESSING.md) 的 CHECK 約束加 `'onramp_vault'`。

新增 ledger event_type：在 [POINTSCHAIN_ENGINEERING.md §4.1](BLOCKCHAIN/POINTSCHAIN_ENGINEERING.md) 的 event_type CHECK 加 `'onramp_purchase'`、`'onramp_refund'`、`'onramp_vault_refill'`。

### 3.4 寫入 ledger_v2 的規則

每筆 credited 入金產生**一筆** ledger 事件：

```
event_type     = 'onramp_purchase'
from_address   = OFFICIAL_ONRAMP_VAULT
to_address     = user.primary_address  (custodial)
amount         = amount_points
reference_type = 'bsc_onramp_tx'
reference_id   = "<chain>:<tx_hash>:<log_index>"
nonce          = sha256("onramp:" || chain || tx_hash || log_index)
memo_hash      = sha256("BSC USDT on-ramp")  -- 不存原文
```

**雙重 idempotency**：
- DB 層：`points_onramp_deposits.UNIQUE(chain, tx_hash, log_index)`
- Ledger 層：`points_ledger_v2.UNIQUE(from_address, nonce)`（既有 §4.1）

### 3.5 自動 credit 守門（Service 層 invariant，違反直接 ValueError）

寫 credit ledger 前**必須**全部通過：

1. `deposit.status == 'pending_credit'`（不能跳 risk_check 階段）
2. `deposit.confirmations ≥ config.confirmations_required`
3. `deposit.amount_token >= config.min_deposit_token`
4. user 24h / 30d 累計 ≤ `daily_limit` / `monthly_limit`
5. `deposit.risk_score < red_threshold` 且 risk_flags 不含 OFAC sanctions
6. credit 後 `ONRAMP_VAULT.balance_points ≥ 0`（不可負，pool 不足直接 manual_review）
7. boot-time `supply invariant` 必須在最近一次檢查通過（[POINTS_WALLET_ADDRESSING.md §9](BLOCKCHAIN/POINTS_WALLET_ADDRESSING.md)）
8. `incident_lockdown` 未啟用
9. `reserve_health ≥ 1.0`（最後一筆 attestation）

### 3.6 API 新增

| Method | Path | 角色 | 用途 |
|---|---|---|---|
| GET  | `/api/points/onramp/chains` | logged-in | 列可用鏈、匯率、限額、最低充值 |
| POST | `/api/points/onramp/address` | logged-in | 取得 / 建立 user 的接收地址（idempotent；同鏈一個 user 一個地址） |
| GET  | `/api/points/onramp/deposits` | logged-in | 列自己的入金紀錄（含 status / confirmations / risk） |
| GET  | `/api/points/onramp/deposit/<id>` | logged-in | 入金細節 |
| GET  | `/api/admin/onramp/dashboard` | admin / root | watcher 狀態 / pending / manual_review / reserve health |
| POST | `/api/admin/onramp/manual-review/<id>` | root | approve / reject / refund（必走 2-of-3 multisig）|
| POST | `/api/admin/onramp/sweep/<chain>` | root | 觸發 sweep（multisig 2-of-3）|
| POST | `/api/admin/onramp/config/<chain>` | root | 改 enabled / rate / limit（multisig 2-of-3 + audit） |
| GET  | `/api/points/explorer/onramp/attestations` | 匿名 | 公開最近 N 天的 reserve attestation |

所有 admin endpoint 必須 CSRF + role check + audit log（[RULES_FOR_AGENTS.md](BLOCKCHAIN/) 既有規範）。

### 3.7 對既有系統影響

| 系統 | 改動 |
|---|---|
| `services/points_chain/schema.py` | 加 4 張 onramp 表 + ALTER `points_wallet_addresses` CHECK 約束 + ALTER `points_ledger_v2` CHECK 約束 |
| `services/points_chain/service.py` | `OnRampService` 子模組：credit / refund / reconcile，全部走既有 ledger_v2 寫入路徑 |
| 新增 `services/points_chain/onramp_watcher.py` | BSC RPC 輪詢，獨立 thread 或 supervisor process（**不可阻塞主 server thread**）|
| 新增 `services/points_chain/onramp_hd_wallet.py` | HD 衍生（BIP32 / BIP44），master seed 用 `ENCRYPTION_KEY` 同源 KMS 加密 |
| 新增 `services/points_chain/onramp_risk.py` | Chainalysis Sanctions API client + manual override |
| `routes/economy.py` | 加 9 個 endpoint（§3.6） |
| `public/js/55-economy.js` | 「購買 points」頁面（鏈選 + 地址 + QR + 倒數 + 狀態輪詢） |
| `routes/system_admin_sections/` | 新 `onramp_routes.py` 給 root dashboard |
| `bootstrap.schema.sql` | 加新表的 DDL |
| `requirements.txt` | 加 `web3==6.x` 或 `eth-utils` + `mnemonic` + `eciespy`（如需） |
| Snapshot manifest | 加 `points_onramp_*` 表 hash |
| Server mode | `incident_lockdown` 自動 freeze `OFFICIAL_ONRAMP_VAULT` 與 `points_onramp_config.enabled` |
| Boot doctor (`server.py --doctor`) | 加 onramp_watcher 自我檢查 + RPC 探測 |

### 3.8 前端 UX（imToken 友善）

關鍵設計：**user 在 imToken 端的動作就是「scan QR → send USDT」，沒有 DApp 交互**。

頁面流程：
1. user 點「購買 points」按鈕
2. 站台呼叫 `POST /api/points/onramp/address`，後端回該 user 的 BSC 收款地址
3. UI 顯示：
   - 收款地址（0x… 帶 EIP-55 checksum + 一鍵複製 + QR code）
   - 「請務必只傳 BEP-20 USDT，傳錯鏈或錯幣種無法退回」紅色警告
   - 建議金額 / 匯率 / 限額
   - 即時狀態：detected → pending_confirmation (N/15 blocks) → credited
   - 倒數 30 分鐘提示「逾時請聯絡客服」（但 deposit 仍會被處理，因為地址永久持有）
4. user 用 imToken 掃 QR、貼地址、輸入金額、簽名、送出
5. 約 5–30 秒後 detected，約 1 分鐘後 credited
6. credited 通知透過 notification center 推給 user

Mobile RWD 必須過 8 breakpoint（[RULES_FOR_AGENTS.md](BLOCKCHAIN/) 既有規範）。

---

## 4. 合規 / 法遵章節（小型社群正式營運定位）

> **本章節不是法律意見**。實際營運前必須諮詢律師，特別是 2025/2026 立法狀態變動快。

### 4.1 台灣相關法源（截至 2026-05-14 的公開資訊）

| 法源 | 對本提案的影響 |
|---|---|
| 《洗錢防制法》(2018 修) + FSC 函令（2021/07/01 起） | 虛擬通貨平台事業應建立 KYC、可疑交易申報 (STR)、紀錄保存 5 年 |
| FSC「虛擬資產平台及交易業務事業 (VASP) 指導原則」(2023-09) | 自律規範、客戶資料保管、平台資產與客戶資產分離 |
| 《虛擬資產服務法》(草案推進中) | VASP 應向 FSC 申請許可才能營運（**最新立法狀態請於動工前再驗證**） |
| 反洗錢「臨時性交易」門檻 | 累計 30,000 美元以上應加強客戶身分識別 |
| 「可疑交易」門檻 | 累計 50 萬新台幣 (~$15,000) 以上應申報 |
| Travel Rule | 跨境/跨平台 ≥ $3,000 USD 需附完整收付雙方資料 |

> ⚠ 在台灣，**對外接受 USDT 換取站內「可交易資產」（本平台 points 可進 trading engine）幾乎肯定屬於 VASP 業務範圍**。「小型社群」的界線是模糊的。

### 4.2 「小型社群」操作建議

為了在「正式營運」與「不誤觸 VASP 全套登記義務」之間取得平衡，建議：

| 措施 | 數值（建議起始值） | 理由 |
|---|---|---|
| 對外公開廣告 | **不主動 advertise on-ramp** | 降低被認定為「對公眾經營」之風險 |
| 受眾範圍 | 僅限**已 KYC 過的既有用戶** | 不收陌生人 USDT |
| 單筆上限 | $300 USDT | 遠低於 STR 門檻 |
| 單人 24h 上限 | $500 USDT | 遠低於臨時性交易門檻 |
| 單人 30d 上限 | $3,000 USDT | 遠低於 STR + 強化 KYC 門檻 |
| 全站日總量上限 | $20,000 USDT | 控制平台累計暴露 |
| Travel Rule | **不接受跨平台轉入**（要求 sender 為個人錢包，非交易所地址） | 避開 Travel Rule 義務 |
| KYC 等級 | L0：手機/Email；L1：身分證 + 自拍（單月 > $1,000 自動觸發） | 對應 FSC 指導原則 |
| 紀錄保存 | 所有 `points_onramp_deposits` row + 鏈上 tx_hash 永久保存 ≥ 5 年 | 對應反洗錢法 |
| 制裁名單篩查 | 每筆 sender_address 過 Chainalysis Sanctions free endpoint | OFAC 命中直接 manual_review + 退款 |
| 退款政策 | ToS 明寫「points 已 credited 不退；deposit 未 credit 前若被 reject，退到原 sender_address 扣 gas」 | 避免 chargeback 風險 |
| 稅務 | 每月匯出 onramp 對帳表給會計師 | 站台收入應報營業稅 / 所得稅 |

### 4.3 受 sanction 篩查的最小集

每筆 `pending_risk_check` deposit 都要對 `sender_address` 查：

1. **Chainalysis Sanctions free endpoint** (`https://public.chainalysis.com/api/v1/address/{address}`)
   - 免費、只查 OFAC 制裁地址
   - 命中 → status='manual_review'，**不可自動退款**（退款回 sanctioned 地址等於再次違反制裁）
2. 平台自建 blocklist（人工累積已知詐騙地址）
3. （未來升級）TRM Labs / Chainalysis KYT 付費 API，含 mixer / darknet / hack 資金追蹤

### 4.4 與 PointsChain v2 既有合規承諾的對齊

| 既有承諾（[WHITEPAPER §1](BLOCKCHAIN/POINTSCHAIN_WHITEPAPER.md)）| 本提案如何遵守 |
|---|---|
| 不偷偷增發 | 自動 credit 路徑不 mint；ONRAMP_VAULT 從 genesis 5% 撥出，refill 走 multisig |
| 每筆變動有 ledger event + chain hash | 每筆 credit 寫一筆 `onramp_purchase` ledger_v2 event |
| 客服不能濫權 | manual_review approve 走 2-of-3 multisig |
| UI 警告大額轉帳 | 「only BEP-20 USDT」紅色警告 + Travel Rule 提示 |
| 不洩漏個資 | explorer 顯示時隱藏 user_id / IP；只露 receive_address（已是 user-specific） |

---

## 5. 對 BLOCKCHAIN/ 既有文件的影響

> 依 [IMPLEMENTATION_GUIDE.md §0.3](BLOCKCHAIN/IMPLEMENTATION_GUIDE.md)，root 拍板**後**才能修改下列文件：

| 文件 | 需要的修改 |
|---|---|
| `README.md` | Phase 順序圖加 Phase 3B；文件清單加 `POINTS_ONRAMP_API.md`（拍板後從本提案升級而來） |
| `POINTSCHAIN_WHITEPAPER.md` | §3.2 官方地址列表 10→11（加 `PNT1ONRAMP`）；§3.5 genesis allocation 撥出 5% 中部分給 ONRAMP_VAULT |
| `POINTSCHAIN_ENGINEERING.md` | 新增 §5B Phase 3B；ledger_v2 event_type CHECK 加 3 個 onramp event |
| `POINTS_WALLET_ADDRESSING.md` | §5 表加第 11 列；§4 schema 的 wallet_type CHECK 加 `'onramp_vault'` |
| `POINTSCHAIN_QA.md` | 新增 §5B Phase 3B QA gate（refer §7 below） |
| `IMPLEMENTATION_GUIDE.md` | §4.1 鏈核心紅線加 onramp 專屬紅線（§8 below） |
| 新增 `POINTS_ONRAMP_API.md` | 本提案的正式升級版 |

---

## 6. 動工順序

依 [IMPLEMENTATION_GUIDE.md §2](BLOCKCHAIN/IMPLEMENTATION_GUIDE.md)：

```
Phase 0 ✅
   │
Phase 1   ← 必須完成
   │
Phase 1A  ← 必須完成（依賴 source/sink + pool runway 監測）
   │
Phase 2   ← 必須完成（依賴 ledger_v2）
   │
   ├─ Phase 3 (站內 transfer)  ─┐
   │                              │ 可並行（兩者 schema 獨立）
   └─ Phase 3B (本提案 on-ramp) ─┘
   │
Phase 4   ← multisig（vault refill / sweep 都需要）
```

**動工前必須先有的東西**：
1. Phase 1 / 1A / 2 出口 gate 全綠 + root 拍板「准進 Phase 3B」
2. ONRAMP_VAULT 地址由 root 透過 multisig signer 流程**公開生成**並寫 immutable 文件
3. genesis allocation 已透過 multisig 撥款給 ONRAMP_VAULT 初始 pool
4. 冷錢包 BSC USDT 收款地址已建立（建議 hardware wallet 或 multisig safe）
5. RPC 提供者選定（建議至少兩家：QuickNode + Ankr + 官方 BSC RPC fallback）
6. Chainalysis Sanctions free API endpoint 已驗證可用
7. 律師確認台灣 VASP 義務範圍（再次強調：**不是工程能繞過的**）

---

## 7. QA Gate（Phase 3B 出口）

對應 [POINTSCHAIN_QA.md](BLOCKCHAIN/) 既有風格，逐項必過：

### 7.1 功能正確性
- [ ] 1 萬筆模擬入金，confirmed 後 100% 寫入 ledger_v2，0 漏 0 重
- [ ] 重複送同 tx_hash 必拒絕（`UNIQUE(chain, tx_hash, log_index)` 觸發）
- [ ] sender 為 OFAC 制裁地址 → status='manual_review'，不自動 credit
- [ ] daily_limit / monthly_limit 觸頂 → 後續 deposit status='manual_review'
- [ ] confirmations < required 時不寫 ledger
- [ ] reserve_health < 1.0 時自動暫停 credit + 通知 root
- [ ] 模擬 5-block reorg：detected 但未 credited 的 deposit 自動回退；已 credited 的進 incident_lockdown
- [ ] HD 衍生 1 萬筆地址 0 衝突，可重現 (deterministic from seed)

### 7.2 安全
- [ ] master seed 在 log / API response / stack trace / secure_audit 均不出現（grep test）
- [ ] RPC URL 在 DB 內以 AES-GCM 加密，明文不落 log
- [ ] 私鑰熱錢包不存在於正式 server（所有 user receive_address 的私鑰只在 HD wallet 衍生時暫存 in-memory）
- [ ] sweep service 簽章走 multisig 2-of-3（測試 1-of-3 / 0-of-3 必失敗）

### 7.3 對帳
- [ ] daily reconcile job 跑 30 天，每天 `reserve_health ≥ 1.0`
- [ ] ONRAMP_VAULT 餘額 + Σ user-credited from onramp 在每個區塊都等於 Σ confirmed deposits × rate
- [ ] supply invariant boot-time 過（包含新 vault 餘額）

### 7.4 UI / RWD
- [ ] mobile 8 breakpoint：購買頁、deposit 紀錄頁、admin dashboard 全過
- [ ] 倒數計時器在 background tab 不漂移
- [ ] QR code 在 imToken 實機掃描成功（測試名單：imToken / TokenPocket / Trust Wallet）

### 7.5 法遵
- [ ] 對外不主動 advertise（前端頁面在未登入時不可見）
- [ ] ToS 加入 onramp 章節
- [ ] 5 年紀錄保存有 backup test
- [ ] 隔離 QA 重現「sender 為 sanctioned 地址」的完整人工處置流程

---

## 8. 紅線（任一違反 = release blocker）

加進 [IMPLEMENTATION_GUIDE.md §4.1](BLOCKCHAIN/IMPLEMENTATION_GUIDE.md)：

- ❌ 自動 credit 路徑 mint 新 points（必須來自 ONRAMP_VAULT 餘額）
- ❌ ONRAMP_VAULT 餘額為負仍允許 credit
- ❌ `reserve_health < 1.0` 仍允許 credit
- ❌ 同 `(chain, tx_hash, log_index)` 寫兩筆 ledger
- ❌ confirmations < `confirmations_required` 仍 credit
- ❌ OFAC sanctioned 地址自動 credit 或自動 refund 回該地址
- ❌ master seed 出現在任何 log / API response / stack trace / secure_audit
- ❌ RPC URL / cold wallet private key 以明文存 DB 或檔案
- ❌ sweep 不走 multisig
- ❌ 對「未登入訪客」公開 onramp 入口 / 匯率 / 接收地址（合規界線）
- ❌ `incident_lockdown` 期間仍接受新 deposit credit
- ❌ 退款發到非原 sender_address

---

## 9. 風險 / 替代方案

### 9.1 主要風險

| 風險 | 影響 | 緩解 |
|---|---|---|
| **法遵風險 - 被認定為未登記 VASP** | 高 | 嚴格限額 + 不對外廣告 + 律師意見 + 隨時可停 |
| **熱錢包資安 - HD seed 外洩** | 全平台用戶充值資產 = 0 | master seed 用 KMS / HSM；正式部署前做 pentest |
| **Reorg / 鏈分叉** | 已 credit 的 points 對應的 USDT 不見了 | confirmations ≥ 15；watchdog 監控；reorg > 15 → incident_lockdown |
| **RPC 提供者故障** | watcher 漏掃 = user 充值無感 | 多 RPC fallback；backlog_blocks > N 自動降級 + 通知 |
| **匯率風險 - USDT 脫鉤** | ONRAMP_VAULT 用 points 計但 USDT < $1 | 暫不接受（fee_basis_points = 0 但保留正抽成空間） |
| **詐騙資金洗入** | 平台被當洗錢通道 | Chainalysis 篩查 + KYC + 上限 |
| **「我自己玩玩」漂移成「對外營運」** | 從規模上失控 → 真的觸 VASP 義務 | 全站日總量上限 + monthly DAU 監測 |

### 9.2 替代方案（可考慮但不推薦）

**A. 不開 on-ramp，改走法幣金流**
- 用 Stripe / 綠界 / LinePay 收新台幣，發放 points
- Pros: 完全避開 VASP；信用卡 chargeback 有處理流程
- Cons: 違背使用者明確需求；金流商抽 2–3%；無法服務海外用戶
- 結論: 若 root 對 VASP 風險不可接受，這是 fallback

**B. 不自己做 on-ramp，整合 MoonPay / Transak**
- 第三方收 USDT/法幣，把對應 points 配額透過 API 通知本站
- Pros: 法遵由 partner 扛
- Cons: 配套合約 + 整合工 + 抽成 4–6%；小型社群可能談不到 partner

**C. EXCHFUND 直接當 vault，不新增官方地址**
- Pros: 不動 [POINTS_WALLET_ADDRESSING.md §5](BLOCKCHAIN/POINTS_WALLET_ADDRESSING.md) 10 地址規則
- Cons: 混淆 trading risk 與 user deposit liability；`exchange_fund_health` 公式失去意義；未來 trading 規模擴大時兩者打架
- 結論: 不推薦；但若 root 堅持 10 地址不變，可改成 EXCHFUND 內部 sub-account 並擴充 health denominator

**D. 完全用智能合約而非 per-user 地址**
- 用戶呼叫 `DepositRouter.deposit(uint256 userId, uint256 amount)`
- Pros: 不用做 HD wallet / sweep service
- Cons: imToken 體驗變差（要 approve + deposit 兩 tx + DApp 交互）；合約需審計
- 結論: 不適合「imToken 用戶友善」這個目標

---

## 10. 需要 root 拍板的點（依優先序）

1. **是否同意在台灣現行法源不確定下推進此提案**（最高層級；其他都次要）
2. **是否同意新增第 11 個官方地址 `OFFICIAL_ONRAMP_VAULT`**（修改 [POINTS_WALLET_ADDRESSING.md §5](BLOCKCHAIN/POINTS_WALLET_ADDRESSING.md) 的「10 地址固定」規則）
3. **是否同意從 genesis allocation 的 5% 未分配中撥 X% 給 ONRAMP_VAULT**（具體 X 多少 = root 決定）
4. **匯率政策**：固定 100 points / USDT？是否抽手續費（fee_basis_points）？是否允許 root 透過 multisig 隨時改？
5. **限額政策**：採用 §4.2 建議值，或 root 另定？
6. **KYC 等級**：採用 §4.2 兩級（L0 / L1）或更嚴？
7. **是否同意 Phase 3B 與 Phase 3 並行**（vs 嚴格依 phase 順序等到 Phase 3 完成）
8. **是否要求律師意見書才能進入動工**（強烈建議「是」）
9. **是否同意預算 BSC RPC（QuickNode 月費 ~$50–200 USD）+ 冷錢包硬體（hardware wallet ~$200）**

---

## 11. 工程量估算

| 階段 | 估時（單一資深 dev） |
|---|---|
| Schema + bootstrap migration | 1 週 |
| OnRampService + ledger 整合 + invariant guard | 2 週 |
| onramp_watcher (BSC RPC poll + reorg handling) | 2 週 |
| onramp_hd_wallet + sweep service (multisig) | 1.5 週 |
| onramp_risk (Chainalysis + manual review) | 1 週 |
| Routes + admin dashboard | 1.5 週 |
| 前端購買頁 + admin UI + mobile RWD | 2 週 |
| Pytest + smoke + pentest | 2 週 |
| 文件升級進 BLOCKCHAIN/ canonical | 0.5 週 |
| 隔離 QA + production hardening | 1.5 週 |
| **合計** | **約 15 週 ≈ 3.5–4 個月** |

如果 Phase 4 multisig 還沒完成 → 等 Phase 4，否則 sweep / vault refill 沒有合規路徑。

---

## 12. 與本提案相關的既有文件

- [BLOCKCHAIN/README.md](BLOCKCHAIN/README.md)
- [BLOCKCHAIN/IMPLEMENTATION_GUIDE.md](BLOCKCHAIN/IMPLEMENTATION_GUIDE.md)
- [BLOCKCHAIN/POINTSCHAIN_WHITEPAPER.md](BLOCKCHAIN/POINTSCHAIN_WHITEPAPER.md)
- [BLOCKCHAIN/POINTSCHAIN_ENGINEERING.md](BLOCKCHAIN/POINTSCHAIN_ENGINEERING.md)
- [BLOCKCHAIN/POINTS_WALLET_ADDRESSING.md](BLOCKCHAIN/POINTS_WALLET_ADDRESSING.md)
- [BLOCKCHAIN/POINTSCHAIN_QA.md](BLOCKCHAIN/POINTSCHAIN_QA.md)

---

*Proposal v1 drafted by Claude (2026-05-14)。狀態：DRAFT — pending root approval。任何後續修改必須先 ping root，不可直接寫進 BLOCKCHAIN/ canonical。*
