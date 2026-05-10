# Operating Model

## Autonomy Levels

| Level | Name | AI Capability | Human Requirement |
|---|---|---|---|
| L0 | Explain-only | Summaries, explanations, docs links | None |
| L1 | Read-only operator | Run allowlisted read-only tools | Login + policy |
| L2 | Draft assistant | Create drafts / previews | User reviews before publish |
| L3 | Pending-action operator | Queue medium/high-risk actions | Human confirmation |
| L4 | Guarded execution | Execute confirmed low/medium user-owned actions | Explicit token / phrase |
| L5 | Autonomous admin | Direct admin/root execution | **Forbidden in v1** |

MVP maximum is **L1/L2**. V1 maximum should be **L3** only after LLM_WEBCHAT
read-only executor, audit, and action state machine are implemented. L4 is a
later narrow phase for confirmed low/medium user-owned actions only.

## User Roles

| Actor | AI Management Scope |
|---|---|
| normal user | own profile, own files, own points, own forum drafts |
| manager/admin | moderation, reports, non-root admin views |
| root | system status, high-risk pending actions, configuration review |
| guest | no AI management access |

## Management Domains

### Forum

Allowed early:

- summarize board health
- search posts
- draft post / reply
- suggest moderation actions

Blocked until later:

- autonomous delete
- autonomous ban
- mass moderation

### Cloud Drive

Allowed early:

- list own files
- search own files
- create folder preview/draft
- summarize storage usage

Blocked:

- reading another user's private files
- exporting encrypted private content
- deleting files without confirmation

### Points / Economy

Allowed early:

- show own balance
- summarize own transactions
- admin/root read-only economy health summary

Blocked:

- direct balance adjustment
- mint/burn
- PointsChain transfer execution

### Trading

Allowed early:

- summarize positions/orders/history
- explain risk warnings
- inspect bot audit output

Blocked:

- autonomous trades
- leverage changes
- liquidation-affecting operation

### Snapshot / Restore

Allowed early:

- summarize snapshot state
- recommend snapshot before risky operation
- create root-visible recommendation for snapshot review

Blocked:

- snapshot.create execution by AI Management in V1
- snapshot.restore
- server.reset

### Security

Allowed early:

- explain latest gate status
- run read-only status checks if safe
- prepare checklist

Blocked:

- autonomous pentest
- integrity.approve_manifest
- changing security mode

## Action Lifecycle

```text
user request
  -> classify goal
  -> plan with registered tools
  -> policy check per step
  -> dry-run / preview for mutations
  -> create pending action only after dependency gates pass
  -> human confirmation through agent confirmation system
  -> execute only in a later approved phase
  -> audit
  -> summarize result
```

## Required UI Signals

Every action card must show:

- tool name
- domain
- risk level
- read/write
- expected changes
- policy result
- confirmation requirement
- audit/action id
- status
