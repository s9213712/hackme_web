# PointsChain Monetary Policy v1

> **Status：Design draft (Claude, 2026-05-05). Approval pending. Implementation blocked until PointsChain v2 Phase 1 / 1A / 2 / 4 / 6 complete + Governance Phase G-2 authorization.**
>
> 配合 [POINTSCHAIN_WHITEPAPER.md §3.4–3.8](POINTSCHAIN_WHITEPAPER.md#34-supply-hard-cap) 的供給結構。

---

## 1. 為什麼需要正式 monetary policy

技術上有 mint / burn / cap 的 SQL；制度上要寫死「**什麼情況可以 mint、上限多少、誰能簽、要等多久**」，否則 mint 就只是技術功能、不是經濟制度。

本 policy 是 **proposal-driven**：所有 mint / burn / fee / emission 改動都必須經 proposal、simulation、multisig/timelock、explorer 公開後才能 execute。

經濟原則：

- Points 是站內 utility / reputation / settlement unit，不承諾投資報酬，不以法幣掛鉤，不以外部交易流通作為第一版目標。
- Mint 是最後手段；日常 reward / airdrop / market support 先用既有 official pool、fee recycling、reserve transfer。
- Earn 必須對平台有可驗證貢獻；spend 必須對平台有真實成本、稀缺性、風控價值或 user utility。
- 所有 policy change 都必須先產 dry-run simulation，再進 proposal。

---

## 2. 不可增發資產（Non-mintable）

下列**永遠不可 mint**（即使 root + 全員 multisig 都不行）：

```
1. 已 burn 的 supply（PNT1BURN 累計）— 可以新 mint，但不能「reverse 一筆 burn」
2. 已 expired 的 voucher / redemption — 商品兌換完的 points
3. self-custody user 遺失的 supply — 私鑰遺失 = 永久損失（whitepaper 已聲明）
4. 已上鏈但 user 主動 burn 的 supply
```

機制保證：

- `from_address = PNT1BURN` 的 ledger insert 拒絕
- 任何「補回 burn」的提案 schema validation 直接 reject
- 翻案 / 申訴最多 mint 進**新**地址，不能改既有 burn ledger

---

## 3. 可增發資產（Mintable, 走 proposal）

只能 mint 進 5 個池（**永不**直接進 user wallet）：

```
PNT1TREASURY     L4 / 3-of-5（scheduled / targeted）
PNT1RESERVE      L3 / 3-of-5
PNT1REWARD       L3 / 3-of-5（scheduled mostly）
PNT1EXCHFUND     L3 / 3-of-5（emergency 4-of-5）
PNT1AIRDROP      L3 / 3-of-5（time-bound campaigns）
```

各池的 governance constraints：

| 池 | 進帳上限 | 最常 mint 場景 |
|---|---|---|
| Treasury | 年化 ≤ 5% (合計 + scheduled) | 戰略儲備、長期準備 |
| Reserve | 季度 ≤ 2% | 危機補位 |
| Reward | 季度 ≤ 3% | reward pool 補充（mining cap 增加時） |
| ExchFund | scheduled 季度 ≤ 1.5%；**emergency 單次 ≤ 3%** | CFD / PVP 流動性、health critical |
| Airdrop | 單次 ≤ 1%；年化 ≤ 1.5% | 活動空投 |

---

## 3.1 Mint 前置決策樹

任何 mint proposal 建立前，系統必須先產生 `mint_precheck_report`，確認以下問題：

| 問題 | 若答案為否 |
|---|---|
| 對應 official pool runway 是否低於 policy 下限？ | 不准 mint；改用既有 pool |
| 是否已評估 treasury / reserve transfer 替代方案？ | 不准 mint |
| 是否有最近 30 / 90 天 source-sink report？ | 不准 mint |
| 是否有 dry-run simulation，且 hard cap / 30-day cap / pool invariant 全通過？ | 不准 mint |
| 是否明確定義 mint 後的支出窗口與失效提醒？ | 不准 mint |
| 是否公開於 explorer 且可被 governance review？ | 不准 mint |

建議決策順序：

```
pool shortage
  -> reduce spending / pause payout?
  -> fee split / fee rate adjustment?
  -> treasury or reserve transfer?
  -> scheduled / targeted mint?
  -> emergency mint only if exchange/reserve health is critical
```

Mint 執行目的地仍只能是 official pool。任何「mint 後立即對 user 發放」必須拆成兩筆：`mint_to_pool` proposal + pool payout proposal / budget authorization。

---

## 4. 三條 Mint 路徑（formal）

對應 [WHITEPAPER §3.7](POINTSCHAIN_WHITEPAPER.md#37-emission-schedule發行--增發)：

### 4.1 Scheduled Mint

```yaml
trigger:
  - 排程觸發（每季 / 半年 / 年）
  - 提前 14 天公告
governance:
  tier: L3
  proposal_path: standard
  multisig: 3-of-5
  timelock: 7 days
  voting_period: 7 days
limits:
  annual_total: ≤ 5% of current circulating
  per_event: ≤ 2% of current circulating
destination:
  - 5 池中任一
forbid:
  - 直接進 user wallet
  - 同一 quarter 內 2 次以上 scheduled
```

### 4.2 Targeted Mint

```yaml
trigger:
  - 治理提案（特定活動 / 補贖 / 流動性激勵）
  - public discussion ≥ 14 days
governance:
  tier: L3
  proposal_path: standard with extended notice
  multisig: 3-of-5
  timelock: 7 days
  voting_period: 7 days + 7 day notice before voting
limits:
  per_event: ≤ 2% of current circulating
  rolling_30d: ≤ 3% (含其他 mint 路徑合計)
destination:
  - 5 池中任一
forbid:
  - 跳過 14-day notice
  - 套用到 user wallet
```

### 4.3 Emergency Mint

```yaml
trigger:
  - exchange_fund.health ≤ 0.3 持續 24 小時 → 自動產 draft
  - 或 reserve_pool depletion < 10%
governance:
  tier: L4
  proposal_path: emergency-fast-track
  multisig: 4-of-5
  timelock: 0 (但 execute 後 7 天內必須 publish postmortem)
  voting_period: N/A (emergency committee approve)
limits:
  per_event: ≤ 3% of current circulating
  cool_down: 14 days（一次後 14 天內不可再 emergency mint）
destination:
  - 限定 PNT1EXCHFUND 或 PNT1RESERVE
forbid:
  - 同一 trigger reason 14 天內重發
  - 進 user wallet 或 Reward / Airdrop
required_after:
  - public incident report ≤ 7 days
  - postmortem with root + emergency committee sign-off
```

---

## 5. Hard Cap 與守恆

```
total_supply        = initial_supply + minted_supply − burned_supply
total_supply        ≤ supply_cap_core_points (governance L4 to change)

invariant per chain block seal:
total_supply == circulating + treasury + reserve + exchange_fund + reward
              + fee_pool + airdrop + escrow + settle + burned
```

任一不等成立 → 拒 seal block + 進 incident_lockdown + 觸發 emergency governance audit event。

**Hard cap 上修**走 L4：

```
governance.parameters.mint.core_points.hard_cap   L4
  - voting period: 14 days
  - quorum: 40%
  - pass: 66%
  - veto: 33%
  - timelock: 14 days
  - 必須附 5-year emission projection
```

---

## 6. Burn Policy

對應 [WHITEPAPER §3.8](POINTSCHAIN_WHITEPAPER.md#38-burn-triggers燒毀觸發)：

### 6.1 自動 burn（governance.parameter 控制）

| 來源 | 參數 | 預設 | 走 proposal 改 |
|---|---|---|---|
| trading fee | `burn.fee_burn_rate` | 0% | L3 |
| 違規罰金（嚴重） | `burn.penalty.severe_percent` | 100% | L3 |
| 違規罰金（中等） | `burn.penalty.medium_percent` | 50% | L3 |
| 違規罰金（輕微） | `burn.penalty.light_percent` | 0% | L3 |
| 商品兌換 | `burn.redemption.percent` | 100% | L3 |
| 過期 voucher | `burn.expired_voucher.percent` | 100% | L3 |
| 失效 escrow | `burn.expired_escrow.percent` | 0% | L3 |

### 6.2 手動 burn（走 L3 proposal）

從 PNT1TREASURY / PNT1REWARD / PNT1FEEPOOL 主動銷毀：

```
proposal_type: burn
payload:
  source: PNT1TREASURY|PNT1REWARD|PNT1FEEPOOL
  amount: int
  reason: string
governance:
  tier: L3
  multisig: 3-of-5
  timelock: 7 days
  voting: standard
```

### 6.3 Burn 鐵律

- `from_address = PNT1BURN` 寫入直接拒
- burn 不影響 hard cap（cap 是「歷史總 mint 上限」）
- 每筆 burn 必填 `burn_reason`（fee_burn / penalty_<severity> / redemption / proposal_<id> / voucher_expired / escrow_expired）
- explorer 公開、可按 reason 篩選
- 月度自動產 burn statistics report

---

## 7. Fee Recycling Policy

當前狀態：transfer fee_rate=0；本節為未來啟用後的政策。Trading fee 可先啟用，但必須受 exchange fund health gate 約束。

```
governance.parameters:
  transfer.fee_rate                  # 例如 0.001（千分之一）
  transfer.fee_min_absolute          # 例如 1 point（防 amount × rate < 1）
  transfer.fee_recycle_split:
    fee_pool_percent:    50          # 進 PNT1FEEPOOL（後續 governance 處置）
    burn_percent:        25          # 直接進 PNT1BURN
    exchange_fund_percent: 20        # 進 PNT1EXCHFUND（CFD / PVP 流動性）
    reward_percent:      5           # 進 PNT1REWARD
    # sum = 100%

  trading.fee_recycle_split:
    exchange_fund_percent: 40        # 承擔 trading payout / market making risk
    fee_pool_percent:      30
    reserve_percent:       20
    burn_percent:          10
    # sum = 100%
```

每筆 fee 4 個 ledger event（已在 [POINTS_TRANSFER_API §3](POINTS_TRANSFER_API.md) 設計，service 層必須完整支援）。

**改 fee_rate 走 L3**；改 split 走 L3；新增 split 對象走 L4（需動 governance schema）。

交易 fee split 的 `burn_percent` 第一版可設為 0，但必須明確寫入 governance parameter；不可在程式碼中硬編隱藏比例。

---

## 8. Reserve Rebalancing Policy

```
governance.parameters:
  reserve.target_percent_of_circulating: 15%
  reserve.lower_alert_percent: 10%
  reserve.upper_alert_percent: 20%
```

季度自動 audit：

```
if reserve_balance / circulating < 10%:
  自動產 draft proposal（L3 mint to reserve OR L3 treasury → reserve）

if reserve_balance / circulating > 20%:
  自動產 draft proposal（L3 reserve → treasury OR L3 reserve burn）
```

draft 仍要走 7 天 voting + 7 天 timelock。**自動產 draft ≠ 自動執行。**

---

## 9. Mint / Burn 暫停條件（Pause Triggers）

下列情況**自動暫停所有 mint 提案**，直到解除：

| 情況 | 暫停範圍 | 解除條件 |
|---|---|---|
| supply invariant 不成立 | 所有 mint + 所有 burn | root + multisig 3-of-5 確認 invariant 復原 |
| total_supply ≥ 95% × hard_cap | scheduled + targeted mint（emergency 仍可） | hard cap raise proposal 通過 |
| audit chain 雜湊鏈異常 | 所有 mint + 所有 burn | audit chain 重建驗證通過 |
| `incident_lockdown` 啟動 | 所有非緊急 governance | incident 結束 |
| 30 天內已 emergency mint 過 | emergency mint 路徑（cool-down） | 14 天滿（per §4.3） |

---

## 10. 公開透明度

每月 explorer 自動產出 monetary policy report：

```
Total supply               (start, end, delta)
Minted breakdown           (scheduled / targeted / emergency × destination)
Burned breakdown           (auto / manual × reason)
Fee pool inflow / outflow  (fee_rate × volume × split)
Reserve health             (% of circulating, target band)
Exchange fund health       (per WHITEPAPER §3.6)
Treasury runway            (預估按目前支出能撐多久)
Pending mint proposals     (in voting / queued)
Pending burn proposals
Source / sink ratio         earned vs spent vs burned vs locked
Pool runway                 treasury / reserve / reward / exchange fund
Top emission reasons        login / bug bounty / mining / airdrop / manual adjustment
Top sink reasons            storage / ComfyUI / server rental / fee / redemption / burn
```

每年 Q1 自動產 5-year emission projection（非綁定，但要公開）。

上線後前 90 天改為每週產出 source/sink report；任一週 `earned_total > spent_total + burned_total + locked_total` 且差距超過 25%，自動產 inflation-risk alert。

---

## 11. Governance Phase 對應

```
Governance Phase G-2  Treasury budget + monetary policy enforcement
  - 完成 governance_parameters 表 + parameter registry
  - mint / burn proposal flow (本檔 §4 / §6)
  - hard cap raise L4 flow
  - automatic suspend triggers（§9）
  - monthly report job
```

依賴：

```
PointsChain v2 Phase 4（multisig）完成
PointsChain v2 Phase 6（explorer）完成（公開報表需要 explorer）
proposal / timelock / simulation / execution flow 完整實作
```

---

## 12. 跨參考

- 預算：[TREASURY_BUDGET_POLICY.md](TREASURY_BUDGET_POLICY.md)
- 供給結構：[POINTSCHAIN_WHITEPAPER.md §3.4-3.8](POINTSCHAIN_WHITEPAPER.md)
- multisig：[MULTISIG_WALLETS.md](MULTISIG_WALLETS.md)
- transfer fee：[POINTS_TRANSFER_API.md](POINTS_TRANSFER_API.md)
