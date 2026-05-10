# Discord Sync Server Mode Matrix

Discord Sync must obey Server Mode v2. External Discord events are never allowed
to cross mode boundaries or write production data from test/shadow contexts.

| Mode | Account link | Outbound | Inbound | Queue worker | DM bridge | Attachments |
|---|---:|---:|---:|---:|---:|---:|
| `production` | on | on | phase-gated | on | off until Phase 6 | link-only |
| `internal_test` | test guild only | shadow/test binding | shadow/test binding | test queue | off | off |
| `test` | fake adapter | fake only | fake only | fake queue | off | off |
| `dev_ready` | root only | fake/manual | off | optional fake | off | off |
| `maintenance` | read-only | paused | paused | paused | off | off |
| `incident_lockdown` | root inspect only | paused | paused | paused | off | off |
| `superweak` | off | off | off | off | off | off |

## Rules

- `production` binding may write production Discord mirror state only after root
  enables Discord Sync.
- `internal_test` must use `server_mode_scope=shadow` or `test_guild`; it must
  not write production Forum/Chat/DM rows.
- `test` must use fake Discord adapters by default.
- `maintenance` and `incident_lockdown` preserve queued jobs but do not process
  them.
- Resume from paused modes must re-check binding policy version, config hash,
  linked account status, Discord permission drift, and rate-limit state.
- `superweak` disables Discord Sync.

## Binding Scope

```text
production   -> production data only after root enables sync
test_guild   -> isolated Discord test guild only
shadow       -> no production Forum/Chat/DM writes
```
