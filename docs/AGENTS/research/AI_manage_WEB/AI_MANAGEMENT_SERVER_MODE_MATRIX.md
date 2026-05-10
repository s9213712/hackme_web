# AI Management Server Mode Matrix

AI Management obeys Server Mode v2 and cannot expand permissions granted by the
underlying tool policy.

| Mode | Overview | Recommend | Read tools | Draft | Pending action | Execute |
|---|---:|---:|---:|---:|---:|---:|
| `production` | on | on | on | preview only | medium/high queue only | off in V1 |
| `internal_test` | shadow only | shadow only | shadow only | shadow only | shadow only | shadow only |
| `test` | fake/isolated | fake | fake | fake | fake | fake |
| `dev_ready` | on | on | limited | dry-run | off by default | off |
| `maintenance` | root only | root only | status only | off | off | off |
| `incident_lockdown` | root only | rescue only | status only | off | off | off |
| `superweak` | off | off | off | off | off | off |

## V1 Rules

- Production execution is disabled in V1.
- Production recommendations must include evidence.
- Internal-test output must not reference production-only private data.
- Maintenance and incident-lockdown allow only root status and queue inspection.
- Superweak disables AI Management.

## Resume Rules

After a mode transition, cached recommendations and evidence must be revalidated
against the current server mode before display or action creation.
