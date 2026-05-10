# Security, Audit, Confirmation, And Memory

## Prompt Injection Defense

Implement in `services/agent/safety.py`.

Rules:

1. LLM tool names must exactly match the registry.
2. LLM cannot create tools.
3. LLM cannot override policy.
4. User / file / post / comment content is untrusted content.
5. Tool output is untrusted content.
6. Arguments must be schema-validated.
7. Tool chains cannot auto-escalate privileges.
8. AI cannot confirm high-risk operations.
9. AI cannot modify agent policy.
10. AI must not ask users to paste secrets, tokens, or private keys.

The following phrases in content must be treated as ordinary text:

```text
ignore previous instructions
disable safety
run shell
reveal secrets
approve root action
bypass confirmation
```

## Confirmation System

Implement in `services/agent/confirmations.py`.

Principles:

- AI only creates pending actions.
- User manually confirms in UI.
- High-risk root/admin actions require password, TOTP, or WebAuthn plus confirm phrase.
- Confirmation token has TTL.
- Confirmation token is single-use.
- Confirmation token is bound to user_id, action_id, tool_name, and action hash.
- Payload modification invalidates confirmation.

Example confirm phrase:

```text
CONFIRM RESTORE SNAPSHOT
```

## Audit

Implement in `services/agent/audit.py`.

Audit event names:

```text
AI_CHAT_REQUEST
AI_CHAT_PROVIDER_ERROR
AI_AGENT_PLAN_CREATED
AI_AGENT_POLICY_BLOCKED
AI_AGENT_ACTION_PREVIEWED
AI_AGENT_CONFIRMATION_CREATED
AI_AGENT_CONFIRMATION_USED
AI_AGENT_TOOL_EXECUTED
AI_AGENT_TOOL_FAILED
AI_AGENT_OUTPUT_REDACTED
AI_AGENT_PROMPT_INJECTION_DETECTED
```

Every agent behavior records:

```text
action_id
plan_id
user_id
actor_role
session_id
server_mode
tool_name
tool_version
input_summary
output_summary
risk_level
read_only
policy_decision
confirmation_status
input_hash
output_hash
before_state_hash
after_state_hash
ip
user_agent
timestamp
success/failure
error
```

High-risk actions also record:

```text
confirm_user
confirm_method
confirm_phrase
action_payload_hash
```

Audit rules:

- Do not store cleartext passwords, tokens, private keys, or CSRF/session values.
- Do not store raw prompt or raw output in high-sensitivity audit; store hash and
  safe summary.
- Admin/root can query audit logs through policy-checked tools.
- Audit tampering must be detectable by hash chain or existing integrity guard.
- Agent replies cannot display sensitive content.

## Memory

Implement in `services/agent/memory.py`.

V1 memory is safe memory only:

- user preferences
- common pages
- common query choices

Memory must not store:

- passwords
- tokens
- private file contents
- E2EE keys
- secrets

Memory requirements:

- user scoped
- user can clear own memory
- memory is not an authorization source
- admin/root cannot read other user memory unless an audited policy allows it
