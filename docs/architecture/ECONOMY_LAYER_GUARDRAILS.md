# Economy Layer Guardrails

一句話說明：這是 PointsChain MVP RC1 的經濟層硬限制；它把已存在的 ComfyUI、Trading、Video、Storage、Games 等產品流收斂到可 replay、可治理、可 release-gate 驗收的財務邊界。

## Source Of Truth

Status: PointsChain MVP RC1 cleanup is in progress. The shared PointsChain
transaction entry appends economy events and fund wallet balances are derived
from replay. RC1 acceptance requires all runtime product writes to enter through
approved Economy / PointsChain facades instead of direct ledger APIs.
The intended economy is closed-loop: points may only enter circulation from
MINT-backed fund wallets, and rewards / grants must eventually be represented
as append-only transfers from PROMO, official treasury, exchange, or another
approved fund.

- `points_ledger` 不得變成可直接 `UPDATE balance` 的快取真相。
- `points_economy_events` 是模擬鏈 fund wallet 的 append-only event ledger。
- 所有 fund / wallet balance 必須能由 append-only ledger replay 重建。
- `points_wallets` 與 `points_economy_derived_balances` 只能是 `derived_cache`。
- 任何 derived cache 必須提供 rebuild / verify path；verify mismatch 是 audit finding，不得由前端靜默修正。
- `legacy_bridge` 只能揭露既有 legacy `points_ledger` 在外用戶積分與 PROMO Fund 應橋接差額；它不得自動補寫 PROMO debit、不得改 legacy wallet balance，也不得取代 replay 真相。
- RC1 requires all new `points_ledger` writes through approved internal primitives to also append a closed-loop `points_economy_events` row. The old ledger row is compatibility/audit output, not the fund balance source of truth.

## Forbidden Operations

- 禁止刪除或修改既有 economy event。
- 禁止刪除或修改既有 economy incident；RC1 incident 只 append。
- 禁止手填 dashboard 數字後當作供給真相。
- 禁止讓 reward / trading / exchange fund 憑空創造資產。
- 禁止 bootstrap 重跑時重複 mint。
- 禁止讓 MINT 超過 `max_supply - reserved_locked` 的可釋出上限，除非之後有明確 policy override 與 audit event。
- 禁止讓 BURN 造成 `active_supply < 0`。
- 禁止產品層直接呼叫 `record_transaction(...)`、`_record_transaction(...)` 或直接 ledger append。
- 禁止產品層直接 mutate `points_wallets` balance / frozen 欄位。
- 禁止產品層把 derived wallet cache 當財務真相。
- 禁止新增繞過 service-fee reserve / batch burn / approved transfer facade 的扣款路徑。

## RC1 Economy Acceptance

- Bootstrap rerun is idempotent and does not duplicate MINT events.
- MINT is capped by `max_supply - reserved_locked`.
- BURN only increases `burned_total`; active supply cannot become negative.
- Dashboard supply / fund balances are derived from replay and verified cache, not manual fields.
- Dashboard must disclose legacy member outstanding points separately until product reward flows are formally bridged into PROMO append-only events.
- Economic incidents are append-only and do not mutate balances.
- Snapshots record replay height, last event hash, wallet root hash, minted total, burned total, active supply, and circulating supply.

## RC1 API Boundary

RC1 may add admin APIs for controlled transfers, but those APIs must still use dry-run / commit semantics and replay verification:

- `POST /api/admin/economy/transfers/dry-run`
- `POST /api/admin/economy/transfers/commit`
- `GET /api/admin/economy/ledger`
- `GET /api/admin/economy/replay-status`
- `POST /api/admin/economy/rebuild-derived-balances`

Product flows must not be connected or retained unless replay, idempotency,
derived-cache verification, reserve/release semantics, and dashboard health
checks are stable.
