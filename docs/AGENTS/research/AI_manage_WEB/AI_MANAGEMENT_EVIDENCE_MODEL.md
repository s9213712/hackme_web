# AI Management Evidence Model

Every recommendation or risk card must show why it exists. Evidence must be
operator-visible, permission-scoped, and redacted.

## Required Evidence Fields

```text
evidence_id
source_tool_name
source_tool_version
source_result_hash
source_timestamp
actor_user_id
server_mode
permission_context
summary
link_target
sensitivity_level
redaction_status
confidence
```

## Rules

- Evidence comes from registered read-only tools or approved preview results.
- Evidence is scoped to the viewer's permissions.
- Evidence summary is redacted before storage and display.
- Evidence hash allows later integrity comparison.
- Evidence does not expose raw private file content, raw secret values, raw DB
  rows, or unredacted audit lines.
- Stale evidence must be marked expired after TTL.

## Sensitivity Levels

```text
public
user_private
admin_sensitive
root_sensitive
secret_redacted
```

Admin/root evidence can be summarized for lower roles only if the source tool
explicitly supports redaction for that role.
