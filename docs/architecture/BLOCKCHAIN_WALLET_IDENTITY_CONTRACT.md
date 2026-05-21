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
| `burn` | `system` | System identity for simulated burn bookkeeping. |

## Cold Wallet Binding

Cold wallets use `ECDSA_P256_SHA256`.

1. Browser creates or imports a private key.
2. Browser exports the public JWK and derives the `pc1...` address.
3. Browser signs the canonical wallet-binding payload.
4. Server verifies the signature and rejects any request containing private-key material such as `d`, `private_key`, `seed`, or `secret`.
5. User must confirm the private key has been saved before binding.

The server-side contract is implemented in `services/points_chain/wallet_identity.py`.

## Signup Bonus

New registrations no longer receive the signup bonus during `/api/register`.
For non-root users, the bonus is issued after wallet onboarding completes. The
award remains idempotent through the existing `new_user_signup_bonus` ledger
action; retrying onboarding does not create duplicate bonus entries.

## Frontend Checks

For this phase, frontend QA should verify:

- A newly approved / logged-in user sees the PointsChain wallet onboarding card.
- `使用官方熱錢包` creates a wallet and awards the signup bonus once.
- `建立冷錢包` shows a private JWK in the browser, requires the backup checkbox, and only sends public key / address / signature to the API.
- `匯入冷錢包` binds an existing browser-side private JWK without sending private-key material.
- `建立多簽錢包` accepts signer addresses and threshold, then stores only the policy wallet.
- Root does not see the user wallet onboarding card and can inspect mint / burn system wallet identities.

## Non-Goals

- No real public-chain deployment.
- No server-side custody of user-created private keys.
- No reservation table as an independent financial source of truth.
- No migration of existing product debit / credit behavior in this slice.
