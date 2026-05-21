# Blockchain Wallet Identity Contract

一句話說明：這是 `04.BLOCKCHAIN` 的模擬鏈錢包身份層；它先處理用戶錢包建立、匯入、多簽 policy、mint / burn 系統錢包與註冊禮 onboarding，不改既有產品扣款流程。

## Scope

- Branch: `04.BLOCKCHAIN`
- Phase: Phase 1 wallet identity / onboarding foundation
- Product billing migration: not included in this slice
- Financial source of truth: `points_ledger`
- Wallet cache: `points_wallets`, still rebuildable from ledger replay

This slice intentionally does not migrate the Phase 0 `migrate` findings for
ComfyUI, Trading, Video, Storage, Games, bug bounty, or admin economy APIs.

## Wallet Types

| Type | Custody | Private-key rule |
|---|---|---|
| `official_hot` | `server_hot` | Simulated official account; no exportable user private key is stored. |
| `self_custody_cold` | `self_custody` | Browser generates the P-256 private key; server receives public JWK, address, and signature only. |
| `imported_cold` | `self_custody` | Browser imports an existing private JWK; server receives public JWK, address, and signature only. |
| `multisig` | `multisig` | Server stores the signer-address policy and threshold, not signer private keys. |
| `mint` | `system` | System identity for simulated issuance bookkeeping. |
| `burn` | `system` | Fixed null-style address `pc1000...0000` for simulated burn bookkeeping. |

## Cold Wallet Binding

Cold wallets use `ECDSA_P256_SHA256`.

1. Browser creates or imports a private key.
2. Browser exports the public JWK and derives the `pc1...` address.
3. Browser signs the canonical wallet-binding payload.
4. Server verifies the signature and rejects any request containing private-key material such as `d`, `private_key`, `seed`, or `secret`.
5. User must confirm the private key has been saved before binding.

The server-side contract is implemented in `services/points_chain/wallet_identity.py`.

## Cold Wallet Deletion / Recovery

Users may remove an active `self_custody_cold` or `imported_cold` wallet from
the points balance page. Removal is not a database delete: the identity row is
marked `lost`, `is_primary` is cleared, and ledger history remains append-only.
Restoring the same address requires importing the private key again and passing
the same signature verification flow. `official_hot` wallets cannot be deleted
from the user UI because they are simulated server-managed identities.

## Signup Bonus

New registrations no longer receive the signup bonus during `/api/register`.
For non-root users, the bonus is issued after wallet onboarding completes. The
award remains idempotent through the existing `new_user_signup_bonus` ledger
action; retrying onboarding does not create duplicate bonus entries.

## Ledger Display IDs

The legacy `public_account_id` remains an HMAC-based PointsChain ledger identity
for proof and compatibility. It is not a simulated blockchain address. New
wallet identities use `pc1...` addresses, and ledger reads include a read-only
`wallet_flow` projection so UI can display issuance and spend direction as
wallet-address flow without changing the underlying append-only ledger rows.

`ledger_uuid` is the transaction id of a ledger row. It is used for proof,
rollback, refund references, and audit lookup; it is not a source or destination
wallet address.

## Frontend Checks

For this phase, frontend QA should verify:

- A newly approved / logged-in user sees the PointsChain wallet onboarding card.
- `使用官方熱錢包` creates a wallet and awards the signup bonus once.
- `建立冷錢包` shows a private JWK in the browser, requires the backup checkbox, and only sends public key / address / signature to the API.
- `匯入冷錢包` binds an existing browser-side private JWK without sending private-key material.
- `刪除冷錢包` appears only for self-custody wallets; after removal, importing the same private key restores the same address.
- Official hot wallets show a non-deletable hint and do not expose the delete button.
- `建立多簽錢包` accepts signer addresses and threshold, then stores only the policy wallet.
- Root does not see the user wallet onboarding card and can inspect mint / burn system wallet identities.

## Non-Goals

- No real public-chain deployment.
- No server-side custody of user-created private keys.
- No reservation table as an independent financial source of truth.
- No migration of existing product debit / credit behavior in this slice.

The Phase 1A private economy layer extends this identity slice with MINT,
BURN, treasury, PROMO, and EXCHANGE fund wallets. Its hard replay/cache rules
are documented in [ECONOMY_LAYER_GUARDRAILS.md](ECONOMY_LAYER_GUARDRAILS.md).
