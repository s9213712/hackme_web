# ExchangeFundPolicy V1

The exchange fund is not a root-controlled loose balance. It is a branch-scoped
official fund with policy buckets.

Buckets:

| Bucket | Use |
|---|---|
| `spot_liquidity` | spot/trial liquidity and immediate user trading settlement. |
| `futures_insurance` | future contract/insurance exposure. |
| `liquidation_buffer` | bad debt and liquidation shortfall buffer. |
| `market_maker_pool` | future official market maker allocation. |

Rules:

- exchange fund replenishment destination is fixed to the exchange fund address.
- bucket is required.
- reason, reference, idempotency key, and payload hash are required.
- daily movement cap applies.
- low-water and critical-water warnings are reported to the root dashboard.
- fallback from treasury writes `economic_model_stress`.
- trading reserve pool and chain exchange fund balance must reconcile.
- branch recovery cannot reuse old-branch exchange balances as new-branch spendable truth.

RC1 exposes current buckets and reconciliation; P2P/contract/official market
making risk can be added only after RC1.
