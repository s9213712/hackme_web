# Hard Cap + Constitutional Expansion Clause

PointsChain defaults to a hard `max_supply`. Normal minting cannot exceed
`max_supply - reserved_locked`; when the releasable supply is exhausted, normal
`MINT_REQUEST` creation and execution must fail with `mint_supply_exhausted`.

Supply expansion is not an emergency mint button. It is represented as:

- `action_type=PARAMETER_CHANGE`
- `payload.proposal_type=SUPPLY_EXPANSION_REQUEST`
- `payload.execution_class=MONETARY_POLICY_AMENDMENT`
- `governance_domain=PROTOCOL_PARAMETER`
- `proposal_severity=CRITICAL`

The proposal only authorizes a `max_supply` increase. It does not mint, spend,
grant, compensate, or transfer points. Follow-up minting still requires the
normal `MINT_REQUEST` path.

## Eligibility

All conditions must be true before a supply expansion proposal can be created
or executed:

- `mint_remaining <= 0` or `releasable_remaining <= 0`.
- Official Treasury is below the minimum operating reserve.
- PROMO and EXCHANGE funds are below their critical operating watermarks.
- The proposal includes a reason, reference, financial report, risk disclosure,
  destination official fund, and immutable trigger-condition snapshot.
- Lower-risk alternatives are documented as considered.

## Voting Policy

Supply expansion uses a constitutional policy:

- Active-user voting scope.
- Root has no veto.
- Quorum: at least 50% of active eligible voters, minimum 5 when available.
- Yes threshold: 80% of decisive votes.
- Vote differential: yes minus no must be at least 50% of eligible voters.
- Timelock: 7 days.
- Expiration: 14 days.

## Caps

- Single expansion cap: 1% of the original constitutional max supply.
- Annual expansion cap: 3% of the original constitutional max supply.
- Duplicate references are rejected.
- Executed proposals cannot be replayed.

## Mint Restriction After Expansion

Expanded supply may only be minted into the destination fund approved by the
monetary policy amendment. Direct minting to users remains forbidden. Minting
expanded capacity to a different fund is rejected by both the governance precheck
and the append-only economy event layer.

## Explorer / Audit Requirements

Every supply expansion execution must leave governance audit evidence showing:

- old and new `max_supply`
- requested delta
- dilution basis points
- trigger-condition snapshot
- fund-balance snapshot
- destination fund and spending restrictions
- proposal hash / payload hash / execution result

