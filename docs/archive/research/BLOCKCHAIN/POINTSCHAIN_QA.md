# PointsChain v2 QA / Release Gate

> **狀態：設計已拍板（root, 2026-05-04），尚未實作完成。**
> 對應 [POINTSCHAIN_ENGINEERING.md](POINTSCHAIN_ENGINEERING.md) Phase 0–6 的測試需求；
> 也是 §J 拍板的 14 項 QA 必測清單的正式落地點。

---

## 1. 14 項 QA Gate 必測（拍板 §J）

每個 phase 完成都必須跑一遍對應子集；任一未過 → BLOCK NEXT PHASE。

| # | 必測項 | 主要 phase | 驗證方法 |
|---|---|---|---|
| 1 | wallet address 不重複 | 1 | DB UNIQUE + migration 100k user 0 衝突 |
| 2 | private key 不進 log | 1 / 5 | `grep -r "private key" runtime/logs/` = 0；pentest 故意觸發 ValueError 確認 |
| 3 | nonce replay 必拒 | 3 / 5 | 自動 100 筆同 nonce |
| 4 | signature bypass 必拒 | 5 | 1000 mutated payload 驗 |
| 5 | burn address 不可轉出 | 1+ | 嘗試 from_address=BURN 寫入必 ValueError |
| 6 | mint 不可單人執行 | 4 | threshold-1 簽章 execute 必拒 |
| 7 | multisig 未達門檻不可 execute | 4 | 同 #6 |
| 8 | wallet = ledger replay | 1 / 2 | nightly diff job + 任意 user 可 download ledger 自驗 |
| 9 | supply invariant 正確 | 1+ | boot-time gate + 每次 seal 區塊前 gate |
| 10 | transfer 金額 / fee / balance_after 正確 | 3 | 手算 + 1000 並發無 invariant 破壞 |
| 11 | incident_lockdown 擋 trading / transfer / mint / multisig execute | 1+ | 8 種 action_type 全測 |
| 12 | explorer 資料與 DB / chain 一致 | 6 | 隨機抽 100 筆 event，UI 顯示 vs DB 必完全一致 |
| 13 | mobile UI 可用 | all | 8 個 breakpoint RWD + headless screenshot（環境支援時）|
| 14 | docs / README / test scripts 同步 | all | 每 phase 完成必檢查；缺則該 phase fail |

---

## 2. Phase 0 出口 Gate（鏈化前清債）

> **2026-05-04 final review update**: 原先 Phase 0 blockers / recommend / low issues 已完成收斂；
> isolated live API 驗證、runtime cleanup、today feature regression 與 full pytest 皆通過。
> `docs/AGENTS/reports/*` 只保留歷史 baseline / evidence，不作 current gate 的 canonical 規格來源。

- [x] **#129 close** ✅ — `test_backtest_does_not_silently_replace_isolated_single_candle` PASS
- [x] **#130 close** ✅ — `test_backtest_skips_outlier_jump_candles_instead_of_booking_fake_profit` PASS
- [x] **#131 close** ✅ — `test_workflow_backtest_does_not_false_trigger_bollinger_on_flat_sequence` PASS
- [x] **#122 close** ✅ — scan window high/low 觸發、`last_scan_at` 成功後才更新、回歸與 full pytest 通過
- [x] **PB-1 close** ✅ — `test_trading_order_invalid_decimal_is_sanitized_for_user` PASS
- [x] `pytest -q tests/test_trading_engine.py tests/test_points_chain.py` 100% 綠
- [x] `tests/test_release_policy.py` 含 needle test 100% 綠
- [x] isolated QA replay 與 final isolated live API review 100% 綠
- [x] Bot audit dashboard 落地（[`docs/trading/TRADING_BOT_AUDIT.md`](../trading/TRADING_BOT_AUDIT.md) 已升級反映現況）

---

## 3. Phase 1 出口 Gate（地址化）

### 3.1 Schema / Migration

- [ ] `points_wallet_addresses` 表存在
- [ ] `points_supply_state` 表存在且 `id=1` row 存在
- [ ] 10 個官方地址全部 `status='active'`（含 `PNT1EXCHFUND`；見 WHITEPAPER §3.2 / §3.6）
- [ ] `OFFICIAL_BURN` 與 `OFFICIAL_MINT` 的 `encrypted wallet secret IS NULL`
- [ ] migration 後每個既有 user 都有 1 筆 `is_primary=1` custodial address
- [ ] migration 報告寫入 `secure_audit`

### 3.2 Address Checksum

- [ ] 1 萬筆隨機產生地址全 checksum 正確
- [ ] 1 萬筆隨機 mutate 1 byte 後 verify 必失敗
- [ ] 前端 preview 對 checksum 錯的地址即時拒絕

### 3.3 Schema 雙保險

- [ ] 嘗試 INSERT `wallet_type IN ('burn','mint')` 帶 `encrypted wallet secret NOT NULL` → IntegrityError
- [ ] 嘗試 ledger 寫 `from_address=OFFICIAL_BURN` → ValueError
- [ ] 嘗試 ledger 寫 `to_address=OFFICIAL_MINT`（一般 transfer 路徑）→ ValueError

### 3.4 Supply Invariant

- [ ] boot 時驗 `total = init + mint − burn`；不過拒啟動 + 進 incident_lockdown
- [ ] 故意把某 wallet balance 加 1，重 boot → 必拒啟動 + audit event
- [ ] supply_state 與 wallet 總和差 = 0（10k user 樣本）

### 3.5 既有 trading / video / shop regression

- [ ] `pytest -q tests/test_trading_engine.py` 100% 綠
- [ ] `pytest -q tests/test_video_*` 100% 綠
- [ ] smoke_suite + functional_permission_pentest 0 fail
- [ ] dual-key 過渡（user_id ↔ address）查詢結果一致

### 3.6 UI

- [ ] 個人頁顯示 primary_address + 複製按鈕
- [ ] 官方地址 badge 顯示
- [ ] supply 狀態燈在 admin dashboard
- [ ] mobile RWD 8 breakpoint 全綠

---

## 4. Phase 2 出口 Gate（Ledger v2）

### 4.1 Dual-write 一致性

- [ ] 寫入 100 萬筆事件，v1 ↔ v2 0 不一致
- [ ] dual-write 任一失敗 → 整 transaction rollback
- [ ] nightly diff job 連續 7 天 0 diff
- [ ] diff > 0 自動進 incident_lockdown 並通知 root

### 4.2 Replay 與一致性

- [ ] `replay_v2(address)` 結果 == `points_wallets` 對應 balance（10k user）
- [ ] Replay 10k 筆事件耗時 p95 < 5s
- [ ] state_root 不依賴 row insert order（相同 events 不同順序產生相同 root）

### 4.3 Merkle Proof

- [ ] `GET /api/points/tx/<event_id>/proof` 對任意 event 都回 valid proof
- [ ] proof 拼回 events_root 必相符
- [ ] mutated 1 byte 的 proof verify 必失敗

### 4.4 Block Seal

- [ ] 每 block ≤ 1000 events 或 60s seal
- [ ] seal 前 supply invariant 不過 → 直接 ValueError + 進 incident_lockdown
- [ ] 連續 100 個 block 0 hash chain break

### 4.5 對既有路徑影響

- [ ] trading fee dual-write 進 fee_pool（手算 vs DB 對帳）
- [ ] video tip 寫成 transfer event
- [ ] bot trade 寫成 bot_trade event
- [ ] snapshot manifest 含 supply_state hash + ledger_v2 schema check
- [ ] restore 寫 `restore_marker` event；reconcile 不過進 incident_lockdown

---

## 5. Phase 3 出口 Gate（Transfer）

### 5.1 規則拒絕

- [ ] 自動 100 筆 nonce replay 全拒（含 race condition）
- [ ] 轉到 burn / mint / 自己 / 不存在地址 / disabled / revoked 全拒
- [ ] timestamp 偏離 > 5 分鐘必拒
- [ ] amount ≤ 0 必拒
- [ ] currency_type 不等於 `points` 必拒
- [ ] memo > 256 字元必拒

### 5.2 Invariant

- [ ] 1000 並發 transfer 0 invariant 破壞
- [ ] 每筆 `Δ(from)+Δ(to)+Δ(fee_pool)==0`（10k 樣本驗證）
- [ ] 每筆 supply_state 不變
- [ ] preview vs final 結果一致（amount / fee / balance_after）

### 5.3 Event / Hash chain

- [ ] event_id 全 unique（10k 樣本）
- [ ] payload_hash 全 unique（10k 樣本）
- [ ] previous_event_hash 連續無破洞

### 5.4 UI / UX

- [ ] preview 顯示對方類型 badge 正確
- [ ] burn 地址 → reject 並指引 burn API
- [ ] 大額 / 官方 / 陌生地址警告觸發
- [ ] 失敗訊息使用者可懂（不用一般使用者看不懂的費率縮寫）
- [ ] mobile 8 breakpoint 全綠

---

## 6. Phase 4 出口 Gate（Multisig）

### 6.1 Threshold

- [ ] threshold-1 execute 必拒
- [ ] threshold=1 schema CHECK 拒絕
- [ ] 過期 approval 無法 execute
- [ ] 同 signer 重複 approve 必拒（DB UNIQUE 強制）

### 6.2 Signature

- [ ] 1000 mutated payload signature verify 必拒
- [ ] 假 signer（非 wallet active signer）approve 必拒
- [ ] approval_payload_hash != proposal.payload_hash 必拒

### 6.3 incident_lockdown

- [ ] 8 種 action_type 在 incident_lockdown 期間 execute 全拒（除 `incident_lockdown_release`）
- [ ] 解除 lockdown 必須走 multisig（不能 root 一鍵）

### 6.4 Action 限制

- [ ] `supply_cap_change` 在 dev_ready / internal_test 必拒
- [ ] `signer_rotation` 在 dev_ready / internal_test 必拒
- [ ] mint 達 hard cap 後 propose mint 必拒

### 6.5 並發

- [ ] 1000 並發 approve 0 race condition
- [ ] 同一 proposal 達 threshold 後再 approve 必拒（status='approved'）

### 6.6 UI

- [ ] proposal 進度 / signer 狀態 / expires_at 顯示正確
- [ ] 簽章 UI 顯示完整 payload + 倒數 10s
- [ ] 執行 UI 二次確認 + 失敗訊息明確
- [ ] mobile 全綠

---

## 7. Phase 5 出口 Gate（Self-Custody）

### 7.1 簽章驗證

- [ ] 正確 signature 通過
- [ ] 1000 mutated payload signature 必拒
- [ ] 用錯的 public key verify 必拒
- [ ] nonce replay 必拒

### 7.2 私鑰紅線

- [ ] `grep -r "private key" runtime/logs/ runtime/ /tmp/` = 0
- [ ] 故意觸發 ValueError stack trace 不含 private key
- [ ] API response 永遠不含 private key
- [ ] secure_audit / bug-reports / mode_switch_logs 不含 private key

### 7.3 切換流程

- [ ] custodial → self_custody 後餘額不變
- [ ] 切換需 2 警告 + 倒數 30s + 勾選確認
- [ ] keystore 匯出 UI 強制 2 確認 + 倒數
- [ ] keystore 在另一裝置匯入後可成功簽章轉帳

### 7.4 Capability

- [ ] 啟用 self-custody 前 capability check（瀏覽器支援 ed25519）
- [ ] 不支援的瀏覽器禁啟用並顯示原因

---

## 8. Phase 6 出口 Gate（Explorer）

### 8.1 一致性

- [ ] explorer 顯示的 supply_state 與 DB 一致
- [ ] 隨機抽 100 筆 event，UI 顯示與 DB 完全一致
- [ ] block_id / events_root / state_root / supply_root 與 DB 完全一致

### 8.2 Performance

- [ ] 10k events 場景 query p95 < 1s
- [ ] explorer summary p95 < 500ms
- [ ] block detail p95 < 1s

### 8.3 隱私

- [ ] 匿名查別人地址歷史 → 拒
- [ ] 登入查別人地址歷史 → 拒（除非是官方 / 自己）
- [ ] 匿名查官方地址歷史 → 通過
- [ ] private key 永不顯示於 explorer

### 8.4 Mobile / UX

- [ ] 8 breakpoint RWD 全綠
- [ ] 官方地址 badge 顯示
- [ ] 失敗訊息使用者可懂

---

## 8a. Phase 7 出口 Gate（QA Mining / Contribution Rewards）

> Status: design approved. Phase 0 cleanup closed. Phase 7 implementation blocked until Phase 1 / 2 / 4 / 6 complete and root separately authorizes Phase 7.
> 完整規格 [POINTS_MINING_REWARDS.md](POINTS_MINING_REWARDS.md) §21。

### 8a.1 Schema / 結構

- [ ] 6 張 mining 表 + bug_reports 升級欄全建立
- [ ] CHECK constraint 啟用（reporter≠verifier / second≠reporter,verifier / share_bp 1-10000 / status enum）
- [ ] OFFICIAL_REWARD_POOL address 存在（依 Phase 1）

### 8a.2 公式

- [ ] base × repro × novelty × security × trust 計算與 hard cap 一致（10 case 手算）
- [ ] formula_json 內每項都記錄
- [ ] admin 試圖向上超過 hard cap → reject
- [ ] formula breakdown 在前後台都顯示

### 8a.3 Reporter ≠ Verifier 紅線

- [ ] DB INSERT verified_by = user_id → IntegrityError
- [ ] API root 試 verify 自己 claim → 403
- [ ] UI verifier 下拉禁選自己
- [ ] Split 表 verifier 同 reporter user_id → reject

### 8a.4 雙人審核 / Multisig

- [ ] low/medium 雙 admin 同意才 approve；同人不算
- [ ] high 須 root 或 security_admin + verifier 兩人
- [ ] blocker 走 multisig 或 2-of-3 emergency
- [ ] reward ≥ 1000 自動 escalate multisig
- [ ] root 自己領獎強制 3-of-5 multisig
- [ ] **multisig signer 自動排除自己相關 reward 的投票**（threshold = nominal；剩餘 signer 不夠 → awaiting_independent_signer 狀態）

### 8a.5 Cap / Budget / Solvency

- [ ] daily_cap × trust 加權 = effective cap 正確
- [ ] reach cap → 進 pending_next_period
- [ ] reward_pool 不足 4 週 → 黃燈
- [ ] reward_pool 不足 1 週 → 紅燈
- [ ] reward_pool < pending payouts → 暫停 execute
- [ ] reward_pool 永不變負
- [ ] 不可自動 mint 補 reward_pool

### 8a.6 Trust score

- [ ] verified low/medium +5；high/blocker +10
- [ ] FP -10；連續 5 次 FP → trust=30 + suspended 7 days
- [ ] suspended 期間不可送 claim
- [ ] 30 天無活動慢慢回升至 50

### 8a.7 FP / Reject 流程

- [ ] FP 給 5 points 但只在格式完整 + 善意提交 + trust ≥ 30 + 還有 cap
- [ ] FP 仍計入 daily/weekly cap
- [ ] duplicate 給 10% reward
- [ ] reject 不消耗 budget

### 8a.8 Retroactive

- [ ] retroactive batch 必走 multisig 3-of-5
- [ ] 一筆 batch 內所有 reference 都記錄
- [ ] explorer 顯示但不洩 user_id/IP/device

### 8a.9 Anti-Sybil

- [ ] client_ip_hash / device_fingerprint / account_age 全記
- [ ] 同 IP/device 24h 多 user 自動 risk_flag
- [ ] same_payment_account 自動偵測
- [ ] 後台只顯示 hash 不顯示明文

### 8a.10 Burn / 罰金

- [ ] **第一版自動 burn 必拒**（任何路徑）
- [ ] suspend 路徑可運作
- [ ] 罰金提案必走 multisig

### 8a.11 Explorer

- [ ] 顯示 payout / category / severity / amount / from REWARD_POOL / to anonymized address
- [ ] 不顯示 user_id / IP / device
- [ ] 排行榜匿名（opt-in 才顯示暱稱）

### 8a.12 Mobile / UX / docs

- [ ] 所有頁面 8 breakpoint RWD
- [ ] 失敗訊息使用者可懂
- [ ] formula breakdown 清楚
- [ ] docs / README / test scripts 同步更新

---

## 9. 跨 Phase Invariant（隨時必過）

任何時間點以下永遠成立：

```
1.  USDT balance >= 0  ─→ 已對應到 points balance ≥ 0
2.  asset balance >= 0  ─→ 同上
3.  Σ user_balances + Σ official_balances + burned_supply ≤ total_supply
4.  total_supply == initial_supply + minted_supply − burned_supply
5.  ∀ ledger_event_v2: amount > 0 AND payload_hash unique
6.  ∀ ledger_event_v2 with from_address: NOT (from_address = OFFICIAL_BURN)
7.  ∀ ledger_event_v2 with to_address (transfer path): NOT (to_address = OFFICIAL_MINT)
8.  ∀ multisig_wallet: threshold ≥ 2
9.  ∀ wallet_address with wallet_type IN ('burn','mint'): encrypted wallet secret IS NULL
10. ∀ chain_block_v2: events_root == merkle(events sorted by id)
11. closed order 不得再次成交
12. canceled order 不得成交
13. fee_pool_balance == Σ fee_amount across all fee events
14. circulating + reserve + reward_pool + fee_pool + burned == total_supply
```

每項都有對應的 pytest 與 nightly job；任何破壞自動進 incident_lockdown。

---

## 10. Release Blocker（鏈化版）

任一條成立直接 **BLOCK** 進 mainnet：

```
私鑰外洩
增發繞過多簽
burn address 可轉出
mint address 可被一般 transfer 寫入
wallet != ledger replay
supply invariant fail
nonce replay 成功
signature bypass
admin / root 單人動官方總庫
official address 被一般 API 操作
multisig threshold = 1
incident_lockdown 期間可 execute multisig（除 release）
chain block hash 鏈中斷
state_root / supply_root 對不上實際 wallet 與 supply

# Phase 7 Mining Release Blocker（補充）
mining reward 公式繞過 hard cap
admin 單人 approve ≥ 1000 reward
root 自己領獎未走 multisig
signer 對自己相關 reward 仍可投票
reporter == verifier 仍可 approve
雙人審核兩人同人
reward_pool 變負
incident_lockdown 期間 mining payout execute
自動 burn 用戶資產
explorer 洩漏 user_id / IP / device
retroactive batch 未走 multisig
mining payout 不寫 ledger_v2 + chain_block
```

---

## 11. 測試腳本與重現

每個 phase 完成都歸檔對應腳本到：

```
docs/AGENTS/reports/claude/pointschain_v2_phaseN_<date>/
├── README.md
├── PHASE_GATE_REPORT.md
├── scripts/
└── evidence/
```

模板沿用 [`docs/AGENTS/reports/claude/prechain_qa_2026-05-04/`](../AGENTS/reports/claude/prechain_qa_2026-05-04/) 的結構。

---

## 12. 持續監控（Production runtime）

| 指標 | 閾值 | 動作 |
|---|---|---|
| Wallet vs ledger replay diff | > 0 | incident_lockdown + 通知 root |
| Supply invariant diff | > 0 | incident_lockdown + 通知 root |
| Block seal 失敗率 | > 1%/hour | warning + audit |
| Multisig signature failure | > 5%/hour | warning + audit |
| Nonce replay 嘗試率 | > 1%/min | warning |
| Private key 字串出現於 log（grep） | > 0 | **CRITICAL**：incident_lockdown + 立即輪換 master key |
| Explorer query p95 | > 1s | warning |

---

## 13. 相關文件

- [POINTSCHAIN_WHITEPAPER.md](POINTSCHAIN_WHITEPAPER.md)
- [POINTSCHAIN_ENGINEERING.md](POINTSCHAIN_ENGINEERING.md)
- [POINTS_WALLET_ADDRESSING.md](POINTS_WALLET_ADDRESSING.md)
- [POINTS_TRANSFER_API.md](POINTS_TRANSFER_API.md)
- [MULTISIG_WALLETS.md](MULTISIG_WALLETS.md)
- [AGENTS/reports/claude/prechain_qa_2026-05-04/PRE_BLOCKCHAIN_READINESS_REPORT.md](../AGENTS/reports/claude/prechain_qa_2026-05-04/PRE_BLOCKCHAIN_READINESS_REPORT.md) — Phase 0 base line
- [AGENTS/QA_MISSION_FOR_AGENTS.md](../AGENTS/QA_MISSION_FOR_AGENTS.md) — 整站 QA runbook
- [AGENTS/TRADING_SYSTEM_QA_FOR_AGENTS.md](../AGENTS/TRADING_SYSTEM_QA_FOR_AGENTS.md) — 交易 QA
