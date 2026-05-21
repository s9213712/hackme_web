# 10 Blockchain Walletization Prework Plan

一句話說明：本文件是 `04.BLOCKCHAIN` 分支的開工前計畫，用來把既有 PointsChain 擴展成全站唯一錢包帳務層；在完成本計畫列出的盤點與 gate 前，不直接開始大規模改功能碼。

## 狀態與分支

- Current branch: `04.BLOCKCHAIN`
- Base branch: `03.Points`
- Base commit: `3cd8666` (`Use Node 24 GitHub actions`)
- Scope: 全站錢包化、PointsChain 交易語意統一、前端錢包狀態一致化、QA / audit gate
- Non-goal: 不在本計畫階段實作公開去中心化鏈、不跳過既有 PointsChain v2 phase gate、不直接改 `docs/AGENTS/research/BLOCKCHAIN/` 的既定設計取捨

既有研究文件曾使用 `04.blockchain` 命名；本次依 root / user 指定，以 `04.BLOCKCHAIN` 作為實際工作分支。後續 commit / push / CI 都以此分支為準。

## 開工原則

1. `points_ledger` 是 source of truth；`points_wallets` 是可重建快取，不是最終可信來源。
2. 全站任何加點、扣點、凍結、解凍、退款、轉帳、手續費、回滾都必須走統一錢包服務。
3. 各業務模組不得自行更新 wallet balance。
4. 所有扣款路徑必須有 idempotency key，重送不能重複扣點。
5. 長任務先 reserve / freeze，成功 capture，失敗或取消 release；已扣款後才失敗則 refund。
6. `wallet_reservations` 與 `wallet_transaction_groups` 可保存業務狀態，但不得成為獨立帳務真相來源。
7. Safe mode、非 production mode、wallet frozen / closed 時必須阻擋寫入。
8. 每個實作切片都要有對應 pytest；牽涉前端交易體驗時要加 Playwright 或靜態 frontend test。
9. 每個可驗證切片完成後 commit + push 到 `04.BLOCKCHAIN`，再看 GitHub Actions。
10. 本階段不得把 `points_ledger` 變成可直接 `UPDATE balance` 的快取真相；所有 fund / wallet balance 必須能由 append-only ledger replay 重建。
11. 若需要 balance cache，只能標記為 `derived_cache`，且必須有 rebuild / verify 指令或 helper。

## 現有基礎

目前 repo 已有可用基礎，這次不從零重寫：

- `services/points_chain/schema.py`: wallet、ledger、block、backup、recovery schema 與 hash helper
- `services/points_chain/service.py`: `PointsLedgerService`、交易、wallet replay、verify、backup / restore
- `routes/economy.py`: points wallet、ledger、catalog、admin adjust、root chain verify / recovery API
- `services/trading/`: trading 下單、凍結、成交、保證金、手續費、風控與驗證
- `routes/comfyui.py`: ComfyUI job / billing 入口
- `services/media/videos.py`: 影片打賞、曝光 boost、平台手續費
- `tests/points/`, `tests/trading/`, `tests/comfyui/`, `tests/video/`: 既有回歸測試基礎

## Phase 0：開工前盤點

目標：先知道所有價值流在哪裡，不先猜。

盤點輸出：

- 每個入口是否已經走 PointsChain
- 是否有 idempotency
- 是否有 reserve / capture / release / refund 語意
- 是否會直接改 wallet 或模組內部餘額
- 是否有前端餘額提示
- 是否有失敗退款或補償流程
- 是否有 root / admin 稽核入口

盤點範圍：

| Domain | Value Flow | First Check |
|---|---|---|
| Account | 註冊禮、生日禮、管理員初始補助、週薪 | `routes/public.py`, `routes/users.py`, `services/points_chain` |
| Community | 發文、留言、按讚、檢舉、申訴回滾 | `routes/community*`, `routes/appeals.py` |
| Storage | 容量購買、失敗退款、掃描失敗回補 | `routes/files.py`, storage tests |
| ComfyUI | 生圖、生影片、生音訊、批次、取消、失敗退款 | `routes/comfyui.py`, `services/comfyui` |
| Video | 打賞、曝光 boost、平台手續費 | `services/media/videos.py`, `routes/videos.py` |
| Games | 每日任務、排行榜獎勵、道具消耗 | `routes/games.py`, `public/js/games` |
| Trading | 下單凍結、成交、撤單解凍、保證金、利息、爆倉 | `services/trading` |
| Admin / Root | 人工加扣點、凍結錢包、chain verify、backup / recovery | `routes/economy.py`, `routes/system_admin.py` |

Exit gate:

- 產出 repo 內盤點文件或表格
- 至少列出所有會寫入 `record_transaction`, `_record_transaction`, `spend_points`, `rollback_ledger` 的呼叫點
- 標出第一批必修 blocker，不把 blocker 混進功能開發 commit
- Snapshot 現有 wallet cache，replay 既有 ledger，先分類 mismatch 再開始 facade migration

Migration / backfill gate:

- 任何 schema 或 facade rollout 前，先 snapshot current wallet balances。
- Replay 既有 `points_ledger` 並和 `points_wallets` cache 對帳。
- 先分類 mismatch：正常 legacy 差異、資料缺失、疑似 corruption、需要人工判斷。
- 只有在原始 reference id 可恢復時，才 backfill transaction groups。
- 不可為了讓歷史看起來完整而 fabricated ledger history；不可恢復的 legacy event 必須用明確的 migration adjustment entry 補正，並保留 reason / operator / source report。

## Phase 1：Wallet Service Facade

目標：新增統一語意層，讓業務模組不用知道 ledger 底層細節。

### Phase 1A：Private economy layer foundation

目標：先建立可 replay 的模擬鏈經濟地基，不開始 Phase 1C / 1D 的產品流接入。

Status: implemented and accepted in Phase 1A.5. The accepted surface is still
foundation/read-model only; ComfyUI, Trading, Video, Storage, Games, and other
product flows remain outside this layer until Phase 1C / 1D.

已批准的 Phase 1A / 1B guardrails 見
[architecture/ECONOMY_LAYER_GUARDRAILS.md](architecture/ECONOMY_LAYER_GUARDRAILS.md)。

Phase 1A 只能做：

- MINT / BURN / official treasury / PROMO fund / EXCHANGE fund 的 deterministic fund wallet。
- Versioned economy policy，包含 `max_supply`、`reserved_locked`、bootstrap allocation 與 fund watermarks。
- Append-only economy event ledger。
- Replay-derived balances、derived cache rebuild / verify、snapshot。
- Root dashboard read model，所有數字來自 replay / derived view。
- Economic incident append-only event，不自動改 balance。

Phase 1A 不做：

- 不遷移 ComfyUI、Trading、Video、Storage、Games 的既有交易行為。
- 不開 user-to-user transfer。
- 不讓 fund balance cache 成為財務真相。
- 不新增會取代 replay 的 reservation truth。

Phase 1A exit gate:

- Bootstrap 重跑 idempotent，不重複 mint。
- MINT 不得超過 `max_supply - reserved_locked` 的可釋出上限，除非明確 policy override。
- BURN 只增加 `burned_total`，不得讓 `active_supply` 為負。
- Dashboard 數字必須全部來自 replay / derived view，不得手填。
- Economic incident 先只 append，不得自動改 balance。
- `tests/economy/` 覆蓋 bootstrap、mint cap、burn、derived cache verify、incident append-only、idempotency conflict。

### Phase 1B：Admin economy transfer API

Phase 1B 才能新增下列 API，且仍不得接產品流：

- `POST /api/admin/economy/transfers/dry-run`
- `POST /api/admin/economy/transfers/commit`
- `GET /api/admin/economy/ledger`
- `GET /api/admin/economy/replay-status`
- `POST /api/admin/economy/rebuild-derived-balances`

預計 facade 操作：

- `credit`: 入帳，例如獎勵、退款補償
- `debit`: 直接扣款，例如一次性消費
- `reserve`: 預扣 / 凍結，例如 ComfyUI job、Trading order
- `capture`: 成功後從 reserve 轉正式扣款
- `release`: 取消或失敗時釋放 reserve
- `refund`: 已扣款後退款
- `transfer`: 使用者間或使用者到官方帳戶轉移
- `fee`: 平台手續費
- `rollback`: 管理員或申訴回滾

必要行為：

- 統一 idempotency 檢查
- 統一 reference type / reference id
- 統一 public / private metadata size limit
- 統一 insufficient balance / wallet status error
- 統一 safe mode / production guard
- 統一通知 job / security / audit hooks

### Idempotency contract

- Same actor + operation + idempotency key + same request hash must return the original result.
- Same actor + operation + idempotency key + different request hash must return conflict.
- Idempotency must be enforced by database-level uniqueness, not only by application memory or best-effort service checks.
- Idempotency records must store request hash, result ledger ids, status, created_at, and expires_at.
- Retried reserve / capture / release / refund requests must never create duplicate financial effects.
- Conflict responses must include enough non-sensitive context for the caller to distinguish retry success from payload mismatch.

### Refund / rollback boundary

- `refund` 是正常業務退款，例如已扣款任務失敗、商品/服務未履約、平台補償。
- `rollback` 是管理員、申訴或稽核修正，必須 reference 原始 ledger / transaction group。
- `refund` 與 `rollback` 都不得刪除或修改既有 ledger，只能追加補償交易。
- `rollback` 必須保留 actor、reason、original ledger uuid、original transaction group id、appeal / audit reference。
- 對同一原始 ledger 的 rollback 必須 idempotent，且不得讓 wallet replay 產生負餘額或負凍結餘額。

Exit gate:

- facade 有單元測試
- 既有 PointsChain 測試不退化
- 至少一個低風險路徑切到 facade 並通過整合測試
- idempotency conflict、retry same payload、retry different payload 都有 DB-backed 測試
- refund / rollback 邊界有測試，確認兩者都只 append compensating ledger entries

## Phase 2：Reservation / Transaction Group

目標：處理長任務與一個業務事件多筆 ledger 的一致性。

候選資料模型：

- `wallet_reservations`: 記錄凍結來源、狀態、到期、對應 job id
- `wallet_transaction_groups`: 記錄同一業務事件下的 debit / credit / fee / refund ledger
- `wallet_policy_rules`: 模組扣款、退款、手續費策略

只有在現有 ledger 欄位不足時才新增表；能以現有欄位可靠完成時，不新增 schema。

### Source-of-truth rule for reservations

`wallet_reservations` and `wallet_transaction_groups` may store operational state, but they must not become independent financial truth. Available balance, reserved balance, frozen balance, captured balance, and refund results must be replayable from `points_ledger` or verified by a required reconciliation job. Any mismatch is a critical audit finding.

具體要求：

- `wallet_reservations.status` 不能單獨決定可用餘額。
- `points_ledger` 必須能重播出凍結、解凍、扣款、退款的財務效果。
- reservation / transaction group 只能作為業務流程索引、UI 狀態、job 關聯、對帳輔助。
- reconciliation 必須檢查 ledger replay 結果和 reservation / transaction group 狀態是否一致。
- mismatch 不得由前端或一般業務 API 靜默修正；必須進 root / health / security audit surface。

### Policy rule rollout constraint

初期 policy 先以程式碼常數或 versioned config 表達。只有在至少兩個 domain 需要可配置策略，且 audit / versioning / rollback 規則已定義後，才引入資料庫型 `wallet_policy_rules`。

在引入資料庫型 policy 前必須先定義：

- policy version 如何綁到 ledger / transaction group
- 舊交易如何用原 policy replay
- root 修改 policy 的 audit event
- policy rollback 或停用後既有 reservation 如何處理

Exit gate:

- 重複 submit 不重複 reserve
- job 成功只 capture 一次
- job 失敗 / 取消 release 一次
- capture 後失敗走 refund，而不是 release
- wallet replay 後餘額與 reservation 狀態一致
- DB-backed reservation / transaction group 不會取代 ledger replay 作為財務真相

## Phase 3：ComfyUI 錢包化

目標：先處理最容易出現長任務與靜默失敗的模組。

要求：

- 模板執行前顯示預估費用
- 提交任務時 reserve
- 任務成功後 capture
- 任務失敗、取消、後端拒絕、超時等待中斷時 release
- 若媒體已生成但前端預覽失敗，不可誤判成扣款失敗；需以 job result / output store 為準
- `capture` 的判斷來源必須是後端 job finalization / output store 狀態，不得依賴前端 preview 成功與否
- 批次任務要能拆出每張 / 每段 output 對應費用
- 任務中心顯示 wallet state：reserved、captured、released、refunded

ComfyUI capture authority:

- Backend job finalization 是 capture authority。
- Output store 已登記成功產物時，即使前端 preview card 載入失敗，也不得自動 release。
- 前端 preview failure 應進 media preview / output delivery 修復流程，不應改寫 wallet state。
- 若 backend job finalization 與 output store 狀態不一致，必須進 reconciliation，不得由前端猜測扣款結果。

Exit gate:

- ComfyUI generation tests 覆蓋成功、失敗、取消、重送
- 前端測試確認餘額、預估費用、失敗回補提示
- 不出現靜默扣款
- 測試覆蓋「後端成功但前端 preview 失敗」時仍以 output store 決定 capture / delivery 狀態

## Phase 4：Trading 錢包語意統一

目標：Trading 已大量接 PointsChain，但要把語意整理成和全站一致。

要求：

- 下單 reserve / freeze
- 撤單 release
- 成交 capture
- 平倉、利息、手續費用 transaction group 表達
- 爆倉與強制處置保留風控 metadata
- Root 模擬餘額與正式 PointsChain 餘額清楚分離

Exit gate:

- 既有 trading core tests 全綠
- 增補 reservation / transaction group 對帳測試
- 前端下單面板顯示可用餘額、凍結餘額、預估手續費

## Phase 5：Storage / Video / Games / Community 接入

目標：把其他模組的加扣點路徑統一。

Storage:

- 容量購買扣款
- 失敗或安全掃描拒絕時退款策略
- 到期扣除或服務停用不直接改錢包

Video:

- 打賞拆成 payer debit、creator credit、platform fee
- 曝光 boost 扣款與可追蹤效果
- 交易結果能從影片管理頁連到 ledger proof

Games:

- 每日任務、排行榜、道具消耗統一走 wallet facade
- 避免遊戲前端自行相信分數直接發點

Community:

- 發文、留言、按讚獎勵有 rate limit / idempotency
- 檢舉、申訴、處分回滾能找到原 ledger

Exit gate:

- 每個 domain 至少有一個成功與失敗測試
- 前端不再出現只顯示點數但查不到 ledger 的狀態

## Phase 6：Root / Admin / User UI

目標：使用者與管理者都能看懂錢包狀態。

User wallet:

- 可用餘額
- 凍結餘額
- 最近交易
- 每筆 proof
- CSV export

Admin:

- 查詢任意 user wallet
- 查詢 transaction group
- 查詢 reservation
- 查詢異常：負餘額、長時間未 release、重複 idempotency conflict

Root:

- 供給報表
- chain verify / seal / backup / recovery
- reservation reconciliation
- wallet replay / mismatch detector
- safe mode 狀態

Exit gate:

- Desktop / mobile 都無文字重疊
- 權限分層測試通過
- 管理操作都有 audit event

## Phase 7：Reconciliation / Audit / Safety Gates

目標：讓錯誤被自動看見，不等使用者回報。

檢查項目：

- wallet balance vs ledger replay
- reservation timeout
- transaction group incomplete
- ledger hash chain
- block seal coverage
- supply gap
- root / platform fee account 對帳
- Trading open order frozen vs wallet frozen
- ComfyUI job state vs reservation state

Migration / backfill checks:

- Snapshot current wallet balances before migration.
- Replay existing ledger and compare with wallet cache.
- Classify mismatches before wallet facade rollout.
- Backfill transaction groups only when original references are recoverable.
- For unrecoverable legacy events, append explicit migration adjustment entries instead of fabricating historical ledger rows.
- Migration adjustment entries must include source report hash, operator, reason, and affected user / reference scope.

Exit gate:

- 增加 root report 或 health report
- CI / prepush 至少跑快速一致性檢查
- 發現 critical mismatch 時回報 security / health center
- migration / backfill report 能被 root 匯出與重新驗證

## Phase 8：文件與發佈

目標：功能完成後同步 operator / user / developer 文件。

要更新：

- `docs/07_POINTSCHAIN.md`
- `docs/03_ADMIN_GUIDE.md`
- `docs/04_USER_GUIDE.md`
- `docs/05_FEATURES_OVERVIEW.md`
- `docs/08_TRADING_ENGINE.md`
- `docs/comfyui/README.md`
- `docs/video/VIDEO_PLATFORM.md`
- `docs/API_REFERENCE.md`
- `docs/11_QA_TESTING.md`

Exit gate:

- docs 與實際 API / UI 一致
- 沒有把研究文件當成已上線功能宣傳
- 版本號與 update summary 同步

## 第一個實作切片

正式動功能碼前，第一個切片只做盤點與測試護欄：

1. 新增全站 value-flow inventory。
2. 寫一個靜態檢查，列出直接呼叫 `_record_transaction` / `record_transaction` / `spend_points` / `rollback_ledger` 的位置。
3. 標示哪些呼叫點可直接保留、哪些應遷移到 wallet facade。
4. 不改交易行為。
5. 跑 points / trading / video / comfyui 相關快速測試。
6. Commit + push 到 `04.BLOCKCHAIN`。

Initial test targets:

- `tests/points/test_wallet_facade_idempotency.py`
- `tests/points/test_wallet_facade_reservation.py`
- `tests/points/test_wallet_replay_reserved_balance.py`
- `tests/comfyui/test_comfyui_wallet_reservation.py`
- `tests/trading/test_trading_wallet_semantics.py`
- `tests/static/test_wallet_direct_call_inventory.py`

Phase 0 first-slice artifacts:

- Value-flow inventory: [architecture/BLOCKCHAIN_WALLET_VALUE_FLOW_INVENTORY.md](architecture/BLOCKCHAIN_WALLET_VALUE_FLOW_INVENTORY.md)
- Static scanner: `scripts/security/gate/wallet_direct_call_inventory.py`
- Scanner test: `tests/static/test_wallet_direct_call_inventory.py`

Phase 1 wallet identity / onboarding artifact:

- Contract: [architecture/BLOCKCHAIN_WALLET_IDENTITY_CONTRACT.md](architecture/BLOCKCHAIN_WALLET_IDENTITY_CONTRACT.md)
- Server code: `services/points_chain/wallet_identity.py`
- Contract test: `tests/points/test_wallet_identity.py`
- Boundary: no ComfyUI / Trading / Video / Storage / Games product billing flow is migrated in this slice.

## 開工前 Done Definition

本計畫階段完成時，必須滿足：

- `04.BLOCKCHAIN` 分支已存在且追蹤 origin
- working tree 乾淨
- 有全站 value-flow inventory
- 有第一批 blocker / risk list
- 有 wallet facade API 草案
- 有測試清單
- GitHub Actions 沒有紅燈

滿足後才進入功能碼實作。
