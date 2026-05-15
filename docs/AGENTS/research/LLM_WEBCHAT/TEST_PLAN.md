# Test Plan

## LLM Adapters

Target file:

```text
tests/test_llm_adapters.py
```

Cases:

1. Ollama connection failure returns friendly error.
2. LM Studio connection failure returns friendly error.
3. Timeout does not crash server.
4. Secrets are not injected into prompts.
5. Provider base URL cannot be supplied by normal user request.
6. Non-localhost provider is rejected unless root enables LAN providers.
7. URL schemes such as `file://`, `ftp://`, and `gopher://` are rejected.
8. Provider redirect to non-allowlisted host is rejected.
9. Unknown model name is rejected unless root/provider allowlist contains it.
10. Encoded localhost forms such as `2130706433`, octal IPv4, and IPv6-mapped
    IPv4 are normalized or rejected.
11. DNS rebinding is blocked by resolving and checking IP before each request.

## Agent Policy

Target file:

```text
tests/test_agent_policy.py
```

Cases:

1. Anonymous user cannot use agent.
2. Normal user cannot use admin tool.
3. Admin cannot use root critical tool.
4. Production forbids dangerous tools.
5. High-risk tool requires confirmation.

## Agent Tools

Target file:

```text
tests/test_agent_tools.py
```

Cases:

1. Read-only tool does not mutate DB.
2. Write tool dry-run does not mutate DB.
3. Schema validation blocks malicious parameters.
4. Missing tool cannot execute.
5. Unknown argument fields are rejected.
6. LLM-returned nonexistent tool name is rejected.
7. Read-only tool cannot be wrapped as write action.
8. Sensitive read-only tool such as `admin.view_audit_logs` is medium risk and redacted.

## Confirmations

Target file:

```text
tests/test_agent_confirmations.py
```

Cases:

1. Token single-use.
2. Expired token rejected.
3. Payload mutation invalidates token.
4. AI cannot self-confirm.

## Prompt Injection

Target file:

```text
tests/test_agent_injection.py
```

Cases:

1. Forum post containing `ignore previous instructions` cannot change policy.
2. File content requesting `reveal secrets` cannot execute.
3. User request to bypass confirmation is rejected.
4. Tool output with malicious text is not treated as system instruction.
5. Cloud Drive content requesting access to another user's file is rejected.
6. Chat message requesting `shell.exec` is treated as ordinary text.
7. Audit log line with fake `key=value` or newline injection cannot alter agent audit.
8. E2EE file plaintext is never read by the agent.
9. User asking AI to paste token/password/private key is refused.
10. LLM extra arguments fail schema validation.

## Agent Audit

Target file:

```text
tests/test_agent_audit.py
```

Cases:

1. Every tool call has audit log.
2. High-risk action has confirmation audit.
3. Audit does not store cleartext password, token, or private key.
4. Audit event names match the AI audit event spec.
5. Tool version, policy version, plan ID, action ID, input hash, and output hash
   are recorded for tool actions.

## Mobile Responsive E2E

Viewports:

```text
360x800
390x844
430x932
768x1024
1366x768
```

Checks:

1. No horizontal scroll.
2. Sidebar opens and closes.
3. Modal fully usable.
4. Admin table readable.
5. Cloud drive can upload / open menu.
6. Forum can create post / reply.
7. WebChat can input and read.
8. Agent Console can view plan and confirm action.
9. Root high-risk confirmation modal does not overflow.

## Acceptance Criteria

1. User can chat with local LLM.
2. Ollama / LM Studio can be switched.
3. Agent can create step plan.
4. Agent can execute read-only tools.
5. Agent can create draft / preview.
6. High-risk actions are not directly executed.
7. Critical tools are blocked.
8. Every tool call has audit.
9. Prompt injection tests pass.
10. Mobile WebChat / Agent Console works.
11. No horizontal scroll.
12. All related tests pass.
