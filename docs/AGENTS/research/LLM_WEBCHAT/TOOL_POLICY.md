# Tool Policy

## Tool Registration

Every tool must be registered with:

```text
name
version
description
input_schema
required_role
required_permissions
risk_level
read_only
require_confirmation
allowed_modes
executor
```

## Risk Levels

```text
low
medium
high
critical
```

## Global Rules

1. Unregistered tools cannot execute.
2. LLM cannot add tools.
3. LLM cannot modify tool policy.
4. Tool arguments must pass schema validation.
5. Tools cannot accept raw SQL, raw shell, or raw Python code.
6. Write tools default to dry-run / preview.
7. Policy engine runs before every tool call.
8. Tool execution failure must not crash the server.
9. Every tool call gets an `action_id`.
10. Every tool call writes audit.

## First Read-only Tools

```text
user.get_self_profile
points.get_balance
points.list_transactions
forum.search_posts
forum.get_post
drive.list_files
drive.search_files
marketplace.search_items
admin.search_users
admin.view_audit_logs
```

Rules:

- `admin.search_users` requires admin / root.
- `admin.view_audit_logs` requires admin / root, `risk_level=medium`, output redaction, and audit.
- Normal users can query only their own data.
- AI cannot inspect private files owned by other users.

## Low-risk Write Tools

```text
forum.create_draft_post
forum.create_reply_draft
drive.create_folder
marketplace.create_draft_listing
```

These should default to dry-run until write tools are explicitly enabled.

## Medium-risk Write Tools

```text
forum.publish_post
forum.publish_reply
drive.rename_file
drive.move_file
marketplace.publish_listing
```

These require explicit user confirmation.

## High-risk Tools

```text
admin.freeze_user
points.adjust_balance
snapshot.create
```

These require pending action + manual second confirmation. V1 should prefer
`snapshot.status` and `snapshot.list`; direct `snapshot.create` execution should
remain disabled until confirmation and audit are stable.

## Critical Tools

```text
snapshot.restore
server.reset
integrity.approve_manifest
security.run_pentest
shell.exec
```

V1 response:

```text
此操作屬於 critical risk，第一版 AI Agent 不允許執行。
```

## Policy Engine Checks

Before every tool:

1. User is logged in.
2. User role is sufficient.
3. User has required permissions.
4. Current server mode allows this tool.
5. Risk level allows direct execution.
6. Mutation requires preview / confirmation.
7. Rate limit is not exceeded.
8. No other user's private data is accessed.
9. Dangerous root-only operation is not attempted.
10. Cross-user / cross-tenant access is blocked.

Policy output:

```json
{
  "allowed": true,
  "reason": "ok",
  "requires_confirmation": false,
  "confirmation_type": null,
  "safe_preview": {}
}
```
