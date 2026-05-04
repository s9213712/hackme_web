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

### 3.2 系統有 9 個官方地址

```
PNT1TREASURY...      平台總庫           (multisig 3-of-5)
PNT1REWARD...        獎勵池             (multisig 3-of-5 出帳)
PNT1FEEPOOL...       手續費池           (自動入帳)
PNT1RESERVE...       市場儲備池         (multisig 2-of-3)
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
              + fee_pool_balance + burned_supply
```

server 啟動時、每次 seal 區塊前都會驗一次。不過**直接拒啟動 + 進 incident_lockdown**。

---

## 4. 你看得到什麼

### 4.1 區塊瀏覽器（不用登入）

- 總供給 / 流通 / 燒毀 / 增發
- 最新區塊高度、近期區塊
- 9 個官方地址歷史（公開）
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

> Status: **Design approved (2026-05-04)，implementation blocked until Phase 0/1/2/4/6 complete.**
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
