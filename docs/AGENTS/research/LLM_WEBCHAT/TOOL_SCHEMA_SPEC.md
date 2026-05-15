# Tool Schema Interface Spec

## Required Shape

Every registered tool must define:

```json
{
  "name": "points.get_balance",
  "version": "1.0",
  "description": "Return current user's points balance.",
  "input_schema": {},
  "output_schema": {
    "points_balance": "integer",
    "points_frozen": "integer",
    "wallet_status": "string"
  },
  "required_role": "user",
  "required_permissions": [],
  "risk_level": "low",
  "read_only": true,
  "allowed_modes": ["production", "internal_test", "test", "dev_ready"],
  "redaction": "none",
  "audit_required": true
}
```

## Validation Rules

1. Tool name must exactly match registry.
2. Tool version must be known.
3. Unknown input fields are rejected.
4. Missing required fields are rejected.
5. Raw SQL / shell / Python code fields are forbidden.
6. Output schema is validated before sending to LLM.
7. Tool output is untrusted content.
8. Tool output cannot become system instruction.

## Sensitive Read-only Tools

Read-only does not always mean low risk.

Example:

```json
{
  "name": "admin.view_audit_logs",
  "version": "1.0",
  "required_role": "admin",
  "risk_level": "medium",
  "read_only": true,
  "redaction": "required",
  "audit_required": true
}
```

## Initial Tool Risk Corrections

- `points.get_balance`: low
- `points.list_transactions`: low for self, medium for admin cross-user summary
- `admin.search_users`: medium
- `admin.view_audit_logs`: medium, redaction required
- `snapshot.status`: low/root or admin depending endpoint
- `snapshot.list`: medium/root or admin
- `snapshot.create`: high, pending action only
