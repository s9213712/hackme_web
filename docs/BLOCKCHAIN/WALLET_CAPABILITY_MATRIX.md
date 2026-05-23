# Wallet Capability Matrix

Status: RC1 wallet spend boundary.

RC1 only supports official treasury multisig spend. User-created multisig
wallets are receive-only and must not be able to transfer out through any API
path.

| wallet_scope | custody_mode | receive | view | transfer_out | multisig_spend | governance_treasury_execute | status |
|---|---|---:|---:|---|---|---|---|
| user | custodial/server_hot | yes | yes | yes, subject to normal rules | no | no | enabled |
| user | self_custody | yes | yes | yes, requires valid local signature | no | no | enabled |
| user | multisig | yes | yes | no in RC1 | no in RC1 | no | receive_only / preview |
| official_treasury | multisig | yes | yes | only via treasury proposal + governance + timelock + multisig threshold | yes | yes | RC1 official feature |
| system_reserve | service/system | yes | admin/system only | only through approved system flow | no | no | system controlled |
| exchange_fund | service/system | yes | admin/system only | only through approved exchange/fund flow | no unless explicitly official_treasury | no | system controlled |

## Address-Proven Disputes

Self-custody and imported cold wallets must prove address control with a local
signature. Private keys never leave the client.

`official_hot` wallets use `custodial/server_hot` custody and are bound to the
current account by `points_wallet_identities.user_id`. They do not have a
client private key. For transaction disputes, the holder account may open or
reply with `account_bound_official_hot_v1` proof. Root/admin APIs must still
serialize the case as address-only and must not expose reporter account
identity fields.

## Hard Rule

If `custody_mode == "multisig"` and `wallet_scope != "official_treasury"`, any
outbound/spend/reserve/exchange-collateral operation must reject with:

```text
user_multisig_receive_only_rc1
```

Allowed:

- user multisig receive
- user multisig view
- user multisig explorer lookup

Rejected:

- user multisig transfer out
- user multisig product payment
- user multisig service fee reserve
- user multisig exchange collateral/order funding
- user multisig withdraw/outbound movement
- user multisig admin-triggered spend

Official treasury multisig is separate. It can execute only after proposal,
governance pass, timelock, payload-hash verification, root-veto rules where
applicable, and signer threshold.
