# AI Management Tool Catalog

AI Management uses LLM_WEBCHAT tool schema contract. It does not define a
separate tool format.

## V1 Read-only Tools

```text
ai_management.get_overview
server_mode.get_status
production_gate.get_status
snapshot.get_status
snapshot.list_recent
audit.get_summary
points_chain.get_status
trading.get_risk_summary
cloud_drive.get_storage_summary
forum.get_moderation_summary
```

Optional after Discord Sync outbound MVP:

```text
discord_sync.get_queue_summary
discord_sync.get_dead_letter_summary
```

## Tool Contract

Each tool must define:

```text
name
version
input_schema
output_schema
required_role
risk_level
read_only
allowed_modes
redaction
audit_required
max_rows
max_chars
```

## V1 Restrictions

- All overview tools are read-only.
- `audit.get_summary` is sensitive read-only:
  - `risk_level = medium`
  - `required_role = admin/root`
  - `redaction = required`
  - `audit_required = true`
  - `max_rows = small`
  - raw audit lines are forbidden
- `admin.view_audit_logs` remains sensitive read-only and requires redaction.
- Cloud Drive tools return metadata/summary only unless the user explicitly owns
  and authorizes content access.
- Trading tools return risk summaries only; no trade execution.
- PointsChain tools return status and verification summaries only; no transfer,
  mint, burn, or adjustment.
- Snapshot tools return status/list/recommendation only; no create/restore
  execution in V1.
