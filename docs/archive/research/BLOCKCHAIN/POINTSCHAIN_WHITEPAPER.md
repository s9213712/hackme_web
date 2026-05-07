# PointsChain Whitepaper v1

> **狀態：設計已拍板（root, 2026-05-04），尚未實作完成。**
> 本文件是 user / admin / root / 外部審計可讀的版本。
> 詳細工程設計請見 [POINTSCHAIN_ENGINEERING.md](POINTSCHAIN_ENGINEERING.md)。
> 本文件未來實作完成後會升版為 v1.0；目前是 v1-draft，內容可被官方修訂但不能被個別工程師改動。

---

## 1. 是什麼

PointsChain 是 hackme_web 的私有積分鏈。

- 每個用戶有獨立的 **錢包地址**（PNT1 開頭）
- 每筆積分變動寫入 **不可竄改的帳本**
- 高風險動作（增發、總庫支出、解封系統）走 **多簽提案**
- 所有人可從 **區塊瀏覽器** 自行查證數字

設計目標：

> **能查證、能證明、能監督；但不要被迫成為自己的銀行。**

---

## 2. 為什麼這樣設計

### 2.1 信任問題

- 平台不能偷偷增發 → 增發必須 3-of-5 multisig + 公開上鏈
- 平台不能偷偷扣款 → 每筆變動有 ledger event + chain hash
- 客服不能濫權 → admin 看得到、動不了官方總庫
- 用戶可被詐騙轉帳 → UI 警告 + 大額二次確認 + 不可逆說明

### 2.2 自主性與救援的妥協

採用 **Hybrid Custody**：

| 模式 | 預設 | 私鑰位置 | 救援 |
|---|---|---|---|
| Custodial（平台託管） | ✅ 預設 | 平台用 AES-GCM 加密保管 | 帳號可救回 |
| Self-Custody（自主管理） | opt-in | 用戶自己保管，平台只存 public key | 遺失即損失 |

一般用戶**預設用 custodial**，不會被迫管理私鑰。
進階用戶可 opt-in self-custody，但啟用前 UI 強制 2 次確認 + 警告「私鑰遺失不可恢復」。

---

## 3. 核心事實（user 必讀）

### 3.1 你會有錢包地址

格式：

```
PNT1 + base58check(public_key_hash + checksum)
```

例：`PNT1ab8K9XBp...`（32–34 字元）

特性：
- 不會直接暴露 user_id
- 帶 4-byte checksum，前端可在 preview 偵測手誤
- 官方地址有明確 badge（避免被冒充）

### 3.2 系統有 10 個官方地址

```
PNT1TREASURY...      平台總庫           (multisig 3-of-5)
PNT1REWARD...        獎勵池             (multisig 3-of-5 出帳)
PNT1FEEPOOL...       手續費池           (自動入帳)
PNT1RESERVE...       市場儲備池         (multisig 2-of-3)
PNT1EXCHFUND...      交易所基金         (multisig 2-of-3；CFD 對坐 / PVP 做市現貨)
PNT1MINT...          增發發行端         (multisig 3-of-5；無私鑰)
PNT1BURN...          燒毀終點           (無私鑰；不可轉出)
PNT1AIRDROP...       活動空投           (multisig 2-of-3)
PNT1ESCROW...        糾紛暫管           (multisig 2-of-3 釋放)
PNT1SETTLE...        交易結算暫存       (撮合引擎內部)
```

規則：
- 所有官方地址不能登入（沒有對應 user）
- mint / burn 地址 **沒有私鑰**（DB `encrypted wallet secret IS NULL`）
- 任何 from_address=BURN 的 ledger 寫入直接拒絕（雙保險）
- 所有官方地址進出全部上鏈、explorer 可公開查

### 3.3 高風險動作走多簽

5 位 signer 角色：

| Role | 職責 |
|---|---|
| `root_owner` | 平台所有人 |
| `security_admin` | 安全管理 |
| `finance_admin` | 財務管理 |
| `qa_release_admin` | QA / Release 管理 |
| `emergency_recovery_admin` | 緊急復原管理 |

mainnet 門檻：

| 動作 | 簽章門檻 |
|---|---|
| Mint 增發 | 3-of-5 |
| Treasury 轉出 | 3-of-5 |
| Reserve 調度 | 2-of-3 |
| Dispute 賠付釋放 | 2-of-3 |
| Airdrop 活動發放 | 2-of-3 |
| 解除 incident_lockdown | 3-of-5 |
| 修改 supply hard cap | 3-of-5 |

internal_test 模式門檻可降至 2-of-3，但**永遠不能降到 1-of-1**。

### 3.4 Supply Hard Cap

- **Core Points** 設 hard cap（具體數字由 root 在啟用前公告）
- **Reward Pool** 不在 hard cap 內，但增發進 reward pool 仍走 multisig
- **單一 root 不可修改 hard cap**；要改必走 3-of-5 multisig 提案，explorer 公開
- Mint 達 cap 後再提案會被自動 reject

公開的 4 個關鍵供給數字：

```
total_supply        = initial_supply + minted_supply − burned_supply
circulating_supply  = Σ user balances + 官方非保留地址 active balance + locked balance
locked_supply       = frozen + escrow_locked + multisig_pending
burned_supply       = 進入 PNT1BURN 累計
```

invariant：

```
total_supply == circulating_supply + reserve_balance + reward_pool_balance
              + fee_pool_balance + exchange_fund_balance + treasury_balance
              + airdrop_balance + escrow_balance + settle_balance
              + burned_supply
```

server 啟動時、每次 seal 區塊前都會驗一次。不過**直接拒啟動 + 進 incident_lockdown**。

### 3.5 Genesis Allocation（初始分配）

mainnet 起跑時固定一次的分配，hash 上鏈成 genesis block。**任何後續變更都必須走 multisig 提案 + explorer 公開**，不能私下移轉。

下列為**建議初稿**（initial supply 視 root 決定的具體上限按比例展開；表中%是相對 initial supply）：

| 地址 | 建議比例 | 用途 | 流動性 |
|---|---|---|---|
| `PNT1TREASURY` | **30%** | 平台長期儲備 / 戰略資金 | 鎖定，多簽提案才出 |
| `PNT1RESERVE` | **15%** | 市場儲備池（穩定機制 / 危機注流） | 多簽 2-of-3 |
| `PNT1EXCHFUND` | **20%** | 交易所基金（見 §3.6） | 多簽 2-of-3 |
| `PNT1REWARD` | **15%** | QA mining / 貢獻獎勵預先注入 | 自動發 + 公式驅動 |
| `PNT1AIRDROP` | **5%** | 活動空投 / 早期用戶激勵 | 多簽 2-of-3 |
| 早期用戶分配 | **10%** | 公開申請、KYC 通過後直接撥款 | 直接到 user wallet |
| `PNT1FEEPOOL` | **0%**（運行時累積） | 手續費自動入帳 | 自動 |
| `PNT1MINT` / `PNT1BURN` / `PNT1ESCROW` / `PNT1SETTLE` | 0% | mint / burn / 暫管位 | 機制專用 |
| 未分配（保留至後續 mint 提案） | **5%** | 上線後動態調整空間 | 鎖定 |

合計 100%。實際數字由 root 在 mainnet 啟用前透過 3-of-5 multisig 公告 + 寫入 genesis block，**寫入後不能修改**（只能透過 multisig mint / burn 改變總量）。

genesis block hash 與 10 個官方地址的初始餘額快照永久公開。任何人都能 reproduce：`sha256(genesis_payload) == published_hash`。

### 3.6 PNT1EXCHFUND — 交易所基金

**為什麼需要這個池**

本平台 trading 系統有兩個演進階段，兩個都需要平台手上有實質資產儲備：

1. **目前：House-counterparty CFD（主莊對坐）**
   平台對坐使用者開倉 / 平倉，使用者贏錢時 platform 必須付得出來、輸錢時 platform 收到的是真金白銀的 points。沒有單獨儲備池的話，平台贏的錢和輸的錢混在 Treasury 裡，做風險控管 + 帳務隔離很困難。

2. **未來：PVP 撮合（user 對 user），平台當 market maker**
   PVP 流動性不夠時，平台必須「先放單」吃掉買賣價差，這需要平台手上隨時有現貨 / points 兩邊都備好。沒有專屬資金做市，PVP 開盤就會空轉。

兩個階段都需要 `PNT1EXCHFUND`。

**入帳規則**（自動，不需提案）

```
PNT1EXCHFUND 入帳來源（流入）：
  + 交易手續費的 X%（建議初值 50%；其餘進 PNT1FEEPOOL 或 burn）
  + 融資 / 借券利息收入（margin interest payments）
  + CFD 對坐 user 虧損方的 settle（platform 是贏家時）
  + 強平回收（liquidation fee 的一部分）
```

**出帳規則**（嚴格）

```
PNT1EXCHFUND 出帳路徑（流出）：
  - CFD 對坐 user 賺錢時的 payout（platform 是輸家時）
  - PVP 做市單的下單保證金（撮合時暫扣，撮合完歸還或結算）
  - 多簽 2-of-3 提案（風控 / 危機調度 / 跨池調度）
  - 達到「池子下限」alert 時，由 PNT1RESERVE 調用 2-of-3 multisig 補注
```

**池子健康度監控**

```
exchange_fund_health =
  exchange_fund_balance / max(open_cfd_exposure + pvp_market_making_lockup, 1)
```

警戒線（公開、可調，但要 multisig）：

| 健康度 | 動作 |
|---|---|
| ≥ 2.0 | 健康；可能會把多餘的轉一部分回 Treasury（每月一次，多簽） |
| 1.0–2.0 | 正常營運區間 |
| 0.5–1.0 | warn；自動暫停接收高槓桿開倉、降低新單 max-leverage |
| ≤ 0.5 | critical；自動切 trading 至 read-only + 觸發 PNT1RESERVE 補注提案 |
| 持續 ≤ 0.3 超過 24h | 觸發**緊急增發**機制（見 §3.7） |

`exchange_fund_balance` / `exchange_fund_health` 公開於 explorer + 上線前檢查分頁。

### 3.7 Emission Schedule（發行 / 增發）

**第一原則**：每筆 mint 都上鏈、explorer 可查；single root 永遠不能單人 mint。

**三條發行路徑**

| 路徑 | 觸發 | 門檻 | 速率上限 | 用途 |
|---|---|---|---|---|
| **Scheduled Mint** | 排程（季 / 半年 / 年） | 3-of-5 | 年化 ≤ **5%** of current circulating | reward pool 補充、流動性擴張 |
| **Targeted Mint** | 特定治理提案 | 3-of-5 + 提案要過 7 天公示期 | 單次 ≤ **2%** of current circulating | 獎勵活動、空投、PVP 流動性激勵 |
| **Emergency Mint**（§3.6 觸發） | 自動 trigger 後 | **4-of-5** + 須有公開 incident report | 單次 ≤ **3%** of current circulating | 交易所基金 / Reserve 危機補注 |

**通用約束**

- 任何單次 mint 不可超過剩餘的 hard-cap headroom（hard cap − total_supply）
- 連續 30 天累計 mint 不可超過 current circulating 的 **3%**（防 bypass schedule 用碎單堆疊）
- mint 的目的地受限：**只能進**`PNT1TREASURY` / `PNT1RESERVE` / `PNT1REWARD` / `PNT1EXCHFUND` / `PNT1AIRDROP`，**不能直接進** user wallet（必須先進池再撥）
- mint 提案在 explorer 公開 + 寫進 mode_switch_logs / governance ledger
- mint 進池後 30 天內未動用，會自動產生審計提醒，但不會自動退回（人為決策）

**緊急增發專屬規範**

`PNT1EXCHFUND` 健康度連續 24h ≤ 0.3 → 自動產出 emergency mint 提案 draft：

```yaml
emergency_mint_proposal:
  amount: ≤ 3% of current circulating
  destination: PNT1EXCHFUND  # 不可改
  trigger_metric: exchange_fund_health
  trigger_value: <實測>
  observation_window_hours: 24
  signoff_threshold: 4-of-5
  cool_down_days: 14   # 觸發後 14 天內不可再起 emergency
  public_disclosure: true   # 提案立即上 explorer，不能私下處理
```

approve 後 24 小時內必須執行，不執行則提案自動失效；執行後立即發 incident report 公告原因 + 後續 reserve 補位計畫。

`Cool-down`：14 天內最多一次 emergency mint，避免被當常態工具濫用。

### 3.8 Burn Triggers（燒毀觸發）

`PNT1BURN` 是**唯一可永久退出 supply 的路徑**。任何 burn 都對應一筆已上鏈 ledger。

**自動 burn（不需提案）**

| 來源 | 比例 | 說明 |
|---|---|---|
| 交易手續費 | **手續費的 X%** 進 burn（建議初值 0% / 後續可 multisig 調整到 10–30%） | 模擬 BNB-style fee burn 的可選機制 |
| 違規罰金 | **嚴重違規 100%**（root 提案）；中等違規 50%；輕微 0% | 罰金扣 user wallet → 進 burn |
| 過期 voucher / 商品贖回 | 100% | 用戶兌換實體 / 服務後對應 points 永久銷毀 |
| 失效 escrow | 條件性 | 由 escrow 釋放規則決定，預設不 burn |

**手動 burn（需提案）**

| 動作 | 門檻 | 常見情境 |
|---|---|---|
| 銷毀官方持有 supply | 3-of-5 | 縮表、抗通膨、主動降通膨壓力 |
| 銷毀 reward pool 餘量 | 3-of-5 + 公示 | reward pool 剩太多、確認用不到 |
| 銷毀 fee pool | 3-of-5 | 平台聲明的「定期 burn」承諾 |

**burn 的硬規則**

- `from_address = PNT1BURN` 的 ledger 寫入直接拒絕（不能從 burn 把錢搬出來；雙保險）
- burn 不影響 hard cap：cap 是「歷史以來總 mint 上限」，不會因為 burn 變高
- 每筆 burn 都有 `burn_reason` 欄位（`fee_burn` / `penalty` / `redemption` / `manual_proposal_<id>`），explorer 可篩選
- 每月 explorer 自動產出 burn statistics（按 reason 分組）

**user 視角**：自己錢包被 burn 走的 points 永遠不可逆。罰金 / 兌換完成的 burn 上鏈後 30 天內可以申訴翻案，root 翻案需要 3-of-5 mint 補回（不是反向 burn）。

---

## 4. 你看得到什麼

### 4.1 區塊瀏覽器（不用登入）

- 總供給 / 流通 / 燒毀 / 增發
- 最新區塊高度、近期區塊
- 10 個官方地址歷史（公開）
- 任意 event_id 的 merkle proof 與區塊歸屬證明
- multisig 提案佇列（status 公開，不含 signer 私鑰）

### 4.2 區塊瀏覽器（要登入）

- 自己地址的完整歷史
- 自己參與的 multisig（如為 signer）

### 4.3 永不公開

- 別人地址的歷史（避免 doxxing）
- 任何用戶的 private key（永不出現在 API、log、錯誤訊息、stack trace）

---

## 5. 你能做什麼

### 5.1 一般用戶

- 查餘額、查歷史、查 merkle proof（同現在但更完整）
- 互轉積分（Phase 3 上線後）
- opt-in 到 self-custody（Phase 5 上線後）
- 透過 bug-reports 送異常回報

### 5.2 admin / manager

- 查所有用戶餘額、ledger
- 處理 bug-reports
- **不能**單人增發、動官方總庫、修改 supply cap
- 可發起 multisig proposal 但執行需門檻

### 5.3 root

- 啟動 incident_lockdown（即時生效）
- 解除 incident_lockdown（需多簽）
- 提案 mint / burn / 大額轉出（執行需門檻）
- 設定 multisig signer 名單（有 audit log）
- **不能**繞過任何多簽門檻

---

## 6. 系統如何保證資料正確

| 保證 | 機制 |
|---|---|
| 餘額 = 帳本 replay | nightly diff job + 任何人可下載 ledger 自己跑 replay；不一致系統自動進 incident_lockdown |
| 總供給恆等式 | server boot-time gate + 每次 seal 區塊前驗證 |
| 帳本不可竄改 | 每筆 ledger 帶 previous_event_hash；每個區塊帶 prev_hash；每個區塊有 merkle root + state root + supply root |
| 重放攻擊不會成功 | client_nonce = UUID + per-address unique 約束 + timestamp window |
| 多簽不會被繞過 | execute 路徑硬檢查 threshold；未達門檻直接拒絕 |
| Burn 不會被誤轉走 | burn address 沒私鑰；任何 from_address=BURN 的寫入硬拒；雙保險 |
| 系統異常不會靜默 | audit chain 記錄；用戶可送 bug-report；admin 收到通知；invariant 失敗自動 incident_lockdown |
| Restore 不靜默成功 | restore 完成後寫 `restore_marker` event 並重 reconcile；wallet/ledger/chain 任一對不上自動進 incident_lockdown |

---

## 7. Snapshot / Restore 與鏈的關係

PointsChain v2 對既有 snapshot/restore 的明確策略：

1. **Chain 永不 rollback**：snapshot 包含 chain block 內容供 audit 重建，但 restore 不會把 chain 倒退。
2. **Restore 寫 marker event**：restore 完成後在 ledger v2 寫一筆 `restore_marker` event（不影響餘額，僅記錄事件）。
3. **Restore 後強制 reconcile**：state_root + supply_root 必須與 restore 的 snapshot 對得上；對不上自動進 incident_lockdown。
4. **Restore 不能靜默成功**：UI / audit log / mode_switch_log 都會看到 restore 事件，root 必須二次確認 `confirm:RESTORE`。
5. **Snapshot diff** 在 restore 前後都必須記錄到 audit。

---

## 8. 你不該期待什麼

- ❌ 這不是真正的去中心化區塊鏈。它是 permissioned chain，平台運作。
- ❌ 平台無法救你的 self-custody 私鑰。遺失就是遺失。
- ❌ 不跨平台流通，不掛鉤法幣，不保證購買力。
- ❌ 不阻止你被詐騙轉帳。重要操作有警告，但決定在你。
- ❌ 不對 incident_lockdown 期間延遲負責；那是設計上的安全停機。

---

## 9. 你會看到的鏈上事件

| 情境 | 鏈上事件 |
|---|---|
| 註冊送點 | `mint`：from=Mint, to=你；reward_pool 同步 +N |
| 任務獎勵 | `reward`：from=Reward Pool, to=你 |
| 現貨買賣 | `trade_buy` / `trade_sell` 在 Trading Settlement；fee 進 Fee Pool |
| 影片投幣 | `transfer` from=投幣者, to=你；可能 `transfer_fee` 進 Fee Pool |
| 朋友互轉 | `transfer_out` + `transfer_in`；fee 進 Fee Pool |
| 商城購買 | `transfer_out` to=賣家；糾紛期 to=Dispute Escrow |
| 系統異常 | `incident_marker` event；後續修復進 `restore_marker` |
| 多簽執行 | `multisig_execute` event 帶 proposal_id |

---

## 10. 上線順序（user 看得到的版本）

| 階段 | 你會看到的變化 |
|---|---|
| Phase 0 | 沒事；底層 4 件 high-severity bug 修完才繼續 |
| Phase 1 | 個人頁多了「我的錢包地址」欄位；可在 explorer 看官方總供給 |
| Phase 2 | 帳本格式升級（不影響你）；可查任意交易的 merkle proof |
| Phase 3 | **可以互轉積分** |
| Phase 4 | mint / 大額官方支出能在後台看到 multisig proposal 與 signer 進度 |
| Phase 5 | **可 opt-in 自主錢包** |
| Phase 6 | 完整公開區塊瀏覽器 |
| **Phase 7** | **QA Mining 上線：找 bug、提供 repro、驗證、領獎都可走鏈上路徑**（細節見 §10a） |

預估 Phase 0–6 ~4 個月；Phase 7 約 +3–4 週。

### 10a. Phase 7：QA Mining / 貢獻獎勵

> Status: **Design approved (2026-05-04). Phase 0 cleanup closed. Phase 7 implementation blocked until Phase 1 / 2 / 4 / 6 complete and root separately authorizes Phase 7.**
> 完整規格見 [POINTS_MINING_REWARDS.md](POINTS_MINING_REWARDS.md)。

#### 你能做什麼

- 在挖礦中心查看可申領任務
- 從交易機器人稽核黃燈訂單一鍵提 bug（自動帶 bot/order/diff）
- 自己寫 bug report 提交（要含 9 欄完整資訊）
- 驗證別人的 bug（不能驗自己提的）
- 領 reward（自動從 OFFICIAL_REWARD_POOL 出帳）

#### 我們承諾的事

| 承諾 | 機制 |
|---|---|
| 獎勵公式可解釋 | 前後台都顯示 `base × repro × novelty × security × trust` 的 breakdown |
| 大額（≥ 1000）走多簽 | 自動升級 multisig；root 自己領一律 3-of-5；signer 自動排除自己 |
| 不能自己驗自己 | DB CHECK + API + UI + 測試四層守護；連 root 也不行 |
| 不會憑空印鈔 | reward_pool 補充必走 multisig；不允許自動 mint |
| reward_pool 永不變負 | boot-time + payout-time gate；solvency 4 級燈號 |
| 不打擊新人 | trust_score 50 起步；FP 仍給 5 points 象徵獎 |
| 公開但不洩個資 | explorer 顯示金額/類別/匿名地址，永不洩 user_id/IP/device |
| 第一版不會自動扣資產 | 罰金/burn 只設計路徑，要實際啟用需後續 multisig 決策 |

#### 嚴重程度與審核

| Severity | base | hard cap | 審核 |
|---|---:|---:|---|
| Low | 30 | 50 | 雙人 admin |
| Medium | 150 | 250 | 雙人 admin |
| High | 600 | 1200 | root 或 security_admin + verifier |
| Blocker | 2500 | 5000 | multisig 或 2-of-3 emergency |

reward ≥ 1000 一律 multisig（無論 severity）。

#### 你不該期待

- ❌ 第一週免 cap 衝刺：不會有，刷分基線一致
- ❌ 主觀大額獎金：公式驅動 + hard cap，admin 可向下調但不可超過 cap
- ❌ AI 灌水文洗分：Content Mining 是 Phase 8 才開放，且有更嚴 anti-spam 風控
- ❌ 自己驗自己賺雙倍：reporter ≠ verifier 是紅線

---

## 11. 文件對應

| 你想知道 | 看哪份 |
|---|---|
| 工程設計細節 / schema / API 規格 | [POINTSCHAIN_ENGINEERING.md](POINTSCHAIN_ENGINEERING.md) |
| 地址格式與生成規則 | [POINTS_WALLET_ADDRESSING.md](POINTS_WALLET_ADDRESSING.md) |
| 轉帳 API | [POINTS_TRANSFER_API.md](POINTS_TRANSFER_API.md) |
| 多簽錢包 | [MULTISIG_WALLETS.md](MULTISIG_WALLETS.md) |
| QA Mining / 貢獻獎勵（Phase 7） | [POINTS_MINING_REWARDS.md](POINTS_MINING_REWARDS.md) |
| QA / Release Gate | [POINTSCHAIN_QA.md](POINTSCHAIN_QA.md) |
| 既有 PointsChain 概念（v1） | [07_POINTSCHAIN.md](../07_POINTSCHAIN.md) |
| 鏈化前的清債（Phase 0） | 參考 [PHASE_0_CLEANUP_GATE.md](PHASE_0_CLEANUP_GATE.md) 的 final review 結論與歷史 evidence |

---

## 12. 最終原則

> 不要把錯誤上鏈。
> 不要把錯誤永久化。
> 不要讓區塊鏈變成 bug 的永久保存器。

對應到本設計：

| 精神 | 措施 |
|---|---|
| 不要把錯誤上鏈 | Phase 0 強制清債；boot-time supply invariant；nightly v1↔v2 diff |
| 可驗證地址 | base58check + checksum；前端 preview |
| 可追蹤流向 | from_address / to_address ledger v2 + merkle proof |
| 可重建餘額 | replay_v2() + 任意 user 可下載 ledger 自驗 |
| 可稽核供給 | `points_supply_state` + multisig mint/burn + explorer 公開 |
| 可防止官方濫權 | multisig 不可降為 1-of-1；incident_lockdown 阻 execute |
| 可讓使用者理解 | 官方地址有人類可讀 badge；轉帳前 preview；rate 用百分比不用縮寫 |

---

*Whitepaper v1 by Claude，root 拍板 2026-05-04。後續修訂須經 root 同意，並同步更新 ENGINEERING + QA 文件。*
