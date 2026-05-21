# Economy Layer Guardrails

一句話說明：這是 `04.BLOCKCHAIN` Phase 1A / 1B 的經濟層硬限制；它先建立可 replay 的私有鏈經濟地基，不把 ComfyUI、Trading、Video、Storage、Games 等產品流接進來。

## Source Of Truth

Status: Phase 1A foundation is implemented and Phase 1A.5 acceptance passed.
The accepted scope is still replay/dashboard/API-read-model only; product
traffic must not be routed into this layer before Phase 1C / 1D approval.

- `points_ledger` 不得變成可直接 `UPDATE balance` 的快取真相。
- Phase 1A 新增的 `points_economy_events` 是模擬鏈 fund wallet 的 append-only event ledger。
- 所有 fund / wallet balance 必須能由 append-only ledger replay 重建。
- `points_wallets` 與 `points_economy_derived_balances` 只能是 `derived_cache`。
- 任何 derived cache 必須提供 rebuild / verify path；verify mismatch 是 audit finding，不得由前端靜默修正。

## Forbidden Operations

- 禁止刪除或修改既有 economy event。
- 禁止刪除或修改既有 economy incident；Phase 1A incident 只 append。
- 禁止手填 dashboard 數字後當作供給真相。
- 禁止讓 reward / trading / exchange fund 憑空創造資產。
- 禁止 bootstrap 重跑時重複 mint。
- 禁止讓 MINT 超過 `max_supply - reserved_locked` 的可釋出上限，除非之後有明確 policy override 與 audit event。
- 禁止讓 BURN 造成 `active_supply < 0`。
- 禁止在 Phase 1A / 1B 開放 user-to-user transfer。

## Phase 1A Acceptance

- Bootstrap rerun is idempotent and does not duplicate MINT events.
- MINT is capped by `max_supply - reserved_locked`.
- BURN only increases `burned_total`; active supply cannot become negative.
- Dashboard supply / fund balances are derived from replay and verified cache, not manual fields.
- Economic incidents are append-only and do not mutate balances.
- Snapshots record replay height, last event hash, wallet root hash, minted total, burned total, active supply, and circulating supply.

## Phase 1B API Boundary

Phase 1B may add admin APIs for controlled transfers, but those APIs must still use dry-run / commit semantics and replay verification:

- `POST /api/admin/economy/transfers/dry-run`
- `POST /api/admin/economy/transfers/commit`
- `GET /api/admin/economy/ledger`
- `GET /api/admin/economy/replay-status`
- `POST /api/admin/economy/rebuild-derived-balances`

Phase 1C / 1D may connect product traffic after the foundation passes review. Product flows must not be connected before replay, idempotency, derived-cache verification, and dashboard health checks are stable.
