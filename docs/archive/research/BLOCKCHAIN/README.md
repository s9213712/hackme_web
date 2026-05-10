# BLOCKCHAIN/ — PointsChain v2 設計文件總集

> Status: **Design approved (root, 2026-05-04). ✅ Phase 0 cleanup closed the blocker issues and full verification passed.**
> Current release verdict: **ALLOW PHASE 1 CANDIDATE**, pending root approval to start implementation work.

本資料夾收斂 `hackme_web` 全站區塊鏈化（PointsChain v2）所有正式設計文件，包含 wallet 地址化、ledger v2、轉帳、多簽、self-custody、explorer、QA Mining。

---

## 進入順序建議

| 你是誰 | 先讀哪份 |
|---|---|
| 一般用戶 / admin / 外部審計 | [POINTSCHAIN_WHITEPAPER.md](POINTSCHAIN_WHITEPAPER.md) — 概念與承諾 |
| dev / 架構師 | [POINTSCHAIN_ENGINEERING.md](POINTSCHAIN_ENGINEERING.md) — 8-phase 工程地圖 |
| 動工 agent（任何要寫源碼的人）| [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md) — **動工前必讀**：分支規則、紅線、提案流程 |
| QA / Release | [POINTSCHAIN_QA.md](POINTSCHAIN_QA.md) — 各 phase 出口 gate + invariants + Release Blocker |

## 文件清單

| 文件 | 對象 | 內容 | Phase |
|---|---|---|---|
| [POINTSCHAIN_WHITEPAPER.md](POINTSCHAIN_WHITEPAPER.md) | user / admin / root / 外部審計 | 概念、承諾、Phase 對應 | all |
| [POINTSCHAIN_ENGINEERING.md](POINTSCHAIN_ENGINEERING.md) | dev / qa | 8-phase 工程地圖 / schema / API / 風險 / 時程 | all |
| **[IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md)** | **動工 agent** | **動工前必讀**：分支規則 (`04.blockchain`) + 紅線 + 提案流程 + phase 動工模板 | all |
| [POINTS_WALLET_ADDRESSING.md](POINTS_WALLET_ADDRESSING.md) | dev | PNT1 + base58check + ed25519 + 10 官方地址 + supply_state | Phase 1 |
| [POINTS_TRANSFER_API.md](POINTS_TRANSFER_API.md) | dev | preview / transfer / nonce / fee 路徑 | Phase 3 |
| [MULTISIG_WALLETS.md](MULTISIG_WALLETS.md) | dev | 5-role signer / 3-of-5 / proposal / approve / execute | Phase 4 |
| [POINTS_MINING_REWARDS.md](POINTS_MINING_REWARDS.md) | dev / admin / user | QA Mining 公式 + 雙人審核 + signer 排除 + trust_score + retroactive | **Phase 7** |
| [POINTSCHAIN_QA.md](POINTSCHAIN_QA.md) | qa | 14 項必測 + 各 Phase 出口 gate + invariants + Release Blocker | all |
| [POINTS_MONETARY_POLICY.md](POINTS_MONETARY_POLICY.md) | dev / treasurer | mint / burn / fee / reserve rebalancing 制度 | Governance G-2 |
| [TREASURY_BUDGET_POLICY.md](TREASURY_BUDGET_POLICY.md) | dev / committee | 預算 buckets + committee 結構 + reconciliation | Governance G-2 |

> 遠期 governance / voting / dispute 文件已移出本資料夾；目前只保留 PointsChain MVP 動工、上線 gate、貨幣政策與 treasury 必要規格。

## Phase 順序與依賴

```
Phase 0  鏈化前清債               已完成 final cleanup / runtime cleanup / live API validation / full pytest
   │                              ── 摘要保留於 IMPLEMENTATION_GUIDE.md；歷史 evidence 必要時查 Git history
Phase 1  地址化基礎建設            wallet_addresses + 10 official (含 EXCHFUND) + supply_state
   │
Phase 1A Economy Observability    source/sink + pool runway + exchange fund solvency dashboard
   │
Phase 2  Ledger v2                 address-centric + dual-write + state/supply root
   │
Phase 3  Transfer (custodial)      用戶互轉 + UUID nonce + fee 路徑
   │
Phase 4  Multisig                  5-role signer + 3-of-5 / 2-of-3 + signer 自動排除
   │
Phase 5  Self-Custody              opt-in + 前端 ed25519 + 私鑰絕不上 server
   │
Phase 6  Explorer                  公開區塊瀏覽器 + merkle proof + RWD
   │
Phase 7  QA Mining                 ★ Phase 0 cleanup closed.
   ↓                               Phase 7 implementation blocked until
                                   Phase 1 / 1A / 2 / 4 / 6 complete and
                                   root separately authorizes Phase 7.
                                   公式 reward + multisig 升級 + signer 排除 + trust 守護
        Phase 8 Content Mining (未來)
        Phase 9 Validator Reward (未來)
```

預估 Phase 0–7 全做完約 **4.5–5 個月**（單一資深 dev）。

## 設計核心承諾（root 拍板 2026-05-04）

1. **不要把錯誤上鏈** → Phase 0 強制清債 + boot-time invariant
2. **不要把錯誤永久化** → 所有 phase 出口 gate 必過才動下一個
3. **不要讓區塊鏈變成 bug 永久保存器** → snapshot/restore 寫 marker + 強制 reconcile
4. **官方絕不單人濫權** → multisig 永遠 ≥ 2；signer 對自己相關的決議自動排除投票
5. **使用者自主但不被迫管私鑰** → Hybrid Custody，預設 custodial
6. **獎勵不是印鈔** → reward_pool 補充走 multisig；不允許自動 mint / 自動 burn 用戶資產

## 歷史 Evidence / 設計討論

舊 AGENTS 報告與一次性 evidence 已從 tracked docs 移除。需要追溯 Phase 0 或跨 agent 討論時，請查 Git history / issue history；目前是否可動工、是否准進 Phase 1，以本資料夾的正式文件與最新 test / live validation 結果為準。

## 動工門檻

> **動工前 root 必須給「特定 phase 啟動」的明確授權**，不能因為「設計拍板了」自動開工。

每進入下一 phase 都必須：

1. 上一 phase 出口 gate 100% 過
2. 對應 docs / pytest / smoke / pentest / regression 都同步
3. 在 commit message 或外部工作紀錄保存 phase gate 摘要
4. root 簽核

## 維護規則

- 本資料夾下核心設計文件 + IMPLEMENTATION_GUIDE.md + 本 README 視為 canonical
- 任何修訂必須由 root 同意；個別 dev 不可改設計取捨
- 章節之間相互引用採相對路徑（`./POINTSCHAIN_QA.md`）；引用本資料夾外用 `../`
- 命名固定，不可改檔名（外部 README / docs/03_ADMIN_GUIDE.md / docs/08_TRADING_ENGINE.md 等都已連結）
- **動工前必先讀 [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md)**，不可跳過
