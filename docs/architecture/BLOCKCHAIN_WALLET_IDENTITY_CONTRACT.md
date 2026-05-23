# Blockchain Wallet Identity Contract

一句話說明：這是 `04.BLOCKCHAIN` 的模擬鏈錢包身份層；它處理用戶錢包建立、匯入、多簽 policy、mint / burn 系統錢包、註冊禮 onboarding，並提供站內服務費 reserve 簽名契約。

## Scope

- Branch: `04.BLOCKCHAIN`
- Phase: Phase 1 wallet identity / onboarding foundation
- Product billing migration: high-frequency site service fees now enter the shared `spend_points()` reserve / batch settlement layer
- Financial source of truth: `points_ledger`
- Wallet cache: `points_wallets`, still rebuildable from ledger replay

Remaining direct legacy findings for ComfyUI, Trading, Video, Storage, Games,
bug bounty, or admin economy APIs must converge on the shared wallet / service
fee facade instead of adding new direct balance writes.

## Wallet Types

| Type | Custody | Private-key rule |
|---|---|---|
| `official_hot` | `server_hot` | Simulated official account; no exportable user private key is stored. |
| `self_custody_cold` | `self_custody` | Browser generates the P-256 private key; server receives public JWK, address, and signature only. |
| `imported_cold` | `self_custody` | Browser imports an existing private JWK; server receives public JWK, address, and signature only. |
| `user_multisig_preview` | `multisig` | RC1 hidden/preview user multisig. It can receive and be observed, but cannot transfer out or pay service fees. Existing legacy `multisig` identities are exposed this way and downgraded to `spend_capability=receive_only`. |
| `official_treasury_multisig` | `multisig` | Official treasury control model. Governance approval grants execution eligibility only; manager+/root signer threshold is still required before treasury execution. |
| `mint` | `system` | System identity for simulated issuance bookkeeping. |
| `burn` | `system` | Fixed null-style address `pc1000...0000`. It is receive-only and unspendable: any transfer to this address is normalized as supply burn and no flow may use it as a source. |

## RC1 Multisig Rule

RC1 only supports official treasury multisig as a spend-capable multisig path.
General user multisig remains a hidden preview capability:

- `wallet_scope=user`, `custody_mode=multisig`, `spend_capability=receive_only`
- It may be created by legacy/API paths, receive funds, appear in Explorer, and show in wallet lists.
- It must not appear as a normal frontend creation action.
- It cannot transfer out, pay wallet creation fees, or pay service fees even if the frontend is bypassed.

Official treasury multisig is represented as:

- `wallet_type=official_treasury_multisig`
- `wallet_scope=official_treasury`
- `custody_mode=multisig`
- `spend_capability=enabled`

The official treasury spend path is:

`manager+ proposal -> signer set / threshold / payload_hash snapshot -> governance pass -> timelock pass -> signer signatures -> threshold/weight ready -> execute -> audit log`

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
Lost wallets are hidden from the normal account wallet list and do not count
toward the account total. The public address remains queryable in the explorer.
Restoring the same address requires importing the private key again and passing
the same signature verification flow. If another account restores that lost
address first, the address and its points balance follow the private key holder.
An active address cannot be bound to two accounts at the same time.
`official_hot` wallets cannot be deleted from the user UI because they are
simulated server-managed identities.

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

## Service Fee Reserve Signatures

Wallet-to-wallet transfers sign `points_wallet_transfer`. High-frequency site
service fees sign `points_service_fee_reserve` when the source wallet is
`self_custody`. The payload includes user id, source wallet address, item key,
quantity, amount, request UUID, and reference fields. The server writes only a
freeze ledger at service time; batch settlement later appends unfreeze + debit
ledgers and sends the final debit to BURN.

## Frontend Checks

For this phase, frontend QA should verify:

- A newly approved / logged-in user sees the PointsChain wallet onboarding card.
- `使用官方熱錢包` creates a wallet and awards the signup bonus once.
- `建立冷錢包` shows a private JWK in the browser, requires the backup checkbox, and only sends public key / address / signature to the API.
- `匯入冷錢包` binds an existing browser-side private JWK without sending private-key material.
- `刪除冷錢包` lets the user select a specific self-custody wallet; after removal it disappears from the account list, and importing the same private key restores the same address.
- Official hot wallets show a non-deletable hint and do not expose the delete button.
- General users do not see a `建立多簽錢包` action in RC1. Legacy/API-created user multisig wallets are displayed as `觀察/收款模式，轉出暫不支援`.
- Manager+ users see the official treasury signer center in governance, including signer roles, weights, threshold, pending proposals, timelock, and execute readiness.
- Root does not see the user wallet onboarding card and can inspect mint / burn system wallet identities.

## Non-Goals

- No real public-chain deployment.
- No server-side custody of user-created private keys.
- No general-user spendable multisig wallet protocol in RC1.
- No reservation table as an independent financial source of truth; service fee
  rows are pointers to append-only freeze / settlement ledgers.
- No new product debit / credit behavior may bypass the shared wallet / service
  fee facade.

The Phase 1A private economy layer extends this identity slice with MINT,
BURN, treasury, PROMO, and EXCHANGE fund wallets. Its hard replay/cache rules
are documented in [ECONOMY_LAYER_GUARDRAILS.md](ECONOMY_LAYER_GUARDRAILS.md).
