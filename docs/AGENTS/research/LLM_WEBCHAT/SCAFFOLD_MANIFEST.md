# Scaffold Manifest

This manifest lists files that can be pre-created when root authorizes
implementation. Do not create these implementation files as empty placeholders
until the owning phase starts; stale empty modules make imports and reviews
harder to reason about.

## Phase 1: LLM Adapter Layer

```text
services/llm/__init__.py
services/llm/base.py
services/llm/ollama.py
services/llm/lmstudio.py
services/llm/router.py
tests/test_llm_adapters.py
```

Pre-create when Phase 1 starts.

## Phase 2: WebChat API

```text
routes/ai_chat.py
public/js/ai_chat.js
public/css/ai_chat.css
docs/WEBCHAT_LLM_INTEGRATION.md
```

Pre-create only after adapter interface is stable.

## Phase 3-4: Tool System

```text
services/llm/tools/__init__.py
services/llm/tools/forum.py
services/llm/tools/files.py
services/llm/tools/points.py
services/llm/tools/marketplace.py
services/llm/tools/admin.py
services/agent/tool_registry.py
services/agent/tool_schemas.py
services/agent/policy.py
services/agent/executor.py
tests/test_agent_policy.py
tests/test_agent_tools.py
```

Start with read-only tools only.

## Phase 5-9: Agent Core

```text
services/agent/__init__.py
services/agent/agent_core.py
services/agent/planner.py
services/agent/executor.py
services/agent/memory.py
services/agent/audit.py
services/agent/safety.py
services/agent/confirmations.py
routes/ai_agent.py
tests/test_agent_confirmations.py
tests/test_agent_injection.py
tests/test_agent_audit.py
```

Pre-create with failing tests or minimal implementations only when the phase
owner is ready to wire them into Flask and the service layer.

## Phase 13-16: Frontend And Mobile

```text
public/js/ai_agent.js
public/js/mobile-nav.js
public/css/ai_agent.css
public/css/responsive.css
docs/AI_AGENT_PLATFORM_CONTROL.md
docs/AI_AGENT_TOOL_POLICY.md
docs/MOBILE_RESPONSIVE_DESIGN.md
```

Pre-create alongside UI tests and viewport checks.

## Files Not Allowed In V1

Do not add an executable implementation for:

```text
shell.exec
snapshot.restore
server.reset
security.run_pentest
integrity.approve_manifest
```

V1 may register these names as blocked critical tools only if the executor
always returns:

```text
此操作屬於 critical risk，第一版 AI Agent 不允許執行。
```
