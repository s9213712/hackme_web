# Violation Fine And Feature Restriction Policy

Status: implemented baseline, 2026-05-23.

## Intent

The violation system uses a reward-and-penalty model:

- Users are not directly debited by root/admin.
- A fine is created after repeat violations or manager review.
- The user must authorize payment from a wallet.
- If the fine is unpaid after the due time, only selected features are restricted.
- Paying the fine or winning a fine appeal releases restrictions.
- Fine payments are burned by default, so moderation does not become an official revenue source.

This mirrors common platform patterns: YouTube uses warning/strike escalation and feature loss for repeated violations, and Discord exposes account standing with progressively stronger penalties. The project adapts the pattern to PointsChain by replacing direct account punishment with wallet-authorized payment plus feature restrictions.

References:

- YouTube Community Guidelines strike escalation: https://support.google.com/youtube/answer/12950271
- YouTube strike appeal flow: https://support.google.com/youtube/answer/185111
- Discord account standing / warning system: https://support.discord.com/hc/en-us/articles/18210965981847-Discord-Warning-System

## Current RC Rule

Three-strike unlock policy:

- Trigger: normal user reaches `violation_count >= 3`.
- Fine amount: `300 + (violation_count - 3) * 100` points.
- Due time: 72 hours after fine creation.
- Payment destination: BURN.
- Default overdue restrictions:
  - discussion posting
  - comments/replies
  - direct messages
  - cloud upload
  - video publishing
  - trading orders
  - paid service spend

Manual manager fine:

- Manager+ may create a fine against a user.
- The target cannot be root.
- Managers cannot target same-or-higher roles.
- The fine must include amount, reason, and restriction features.

## Appeals

Violation appeals and fine appeals are separate.

Fine appeals:

- User can appeal a pending or overdue fine.
- Manager+ can approve or reject.
- Approval waives the fine and releases restrictions.
- Rejection keeps the fine payable and restrictions active if overdue.

## Enforcement

Back-end restrictions are enforced on feature entry points:

- discussion/thread creation
- replies/comments
- chat/DM actions where routed through member permission checks
- cloud upload
- video upload/publish
- trading order and margin open
- wallet transfer
- generic service spend

The UI only mirrors state. The server is the enforcement boundary.

## Rewards And Positive Incentives

The following are policy targets. They should be funded through official treasury governance, not direct mint:

- P0 bug bounty: high official treasury reward, manager+ governance approval.
- P1 bug bounty: medium official treasury reward, manager+ governance approval.
- Valid disputed-transaction recovery: optional recovery operations fee may be charged only if the governance/recovery policy selects it. The fee must be disclosed in the recovery proposal.
- False or abusive dispute reports: may create a violation fine and restrict dispute creation.

## Non-Goals

- No admin direct wallet debit.
- No root-only confiscation.
- No secret balance modification.
- No unpaid fine that silently blocks actions without a human-readable error.

