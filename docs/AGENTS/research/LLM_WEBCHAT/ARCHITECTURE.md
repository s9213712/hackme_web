# Architecture

## System Shape

```text
Frontend WebChat / Agent Console / Mobile Responsive UI
        ↓
routes/ai_chat.py / routes/ai_agent.py
        ↓
LLM Adapter Layer
  ├── Ollama Adapter
  ├── LM Studio Adapter
  └── Future Provider Adapter
        ↓
Agent Core
  ├── Planner
  ├── Executor
  ├── Policy Engine
  ├── Tool Registry
  ├── Confirmation System
  ├── Safety Filter
  └── Audit Logger
        ↓
Platform Tools
  ├── Forum Tools
  ├── Cloud Drive Tools
  ├── Points Tools
  ├── Marketplace Tools
  ├── Admin Tools
  └── Snapshot Tools
```

## Proposed Backend Modules

```text
services/llm/
  __init__.py
  base.py
  ollama.py
  lmstudio.py
  router.py

services/llm/tools/
  __init__.py
  forum.py
  files.py
  points.py
  marketplace.py
  admin.py

services/agent/
  __init__.py
  agent_core.py
  planner.py
  executor.py
  tool_registry.py
  tool_schemas.py
  policy.py
  memory.py
  audit.py
  safety.py
  confirmations.py
```

## Proposed Routes

```text
routes/ai_chat.py
routes/ai_agent.py
```

## Proposed Frontend Files

```text
public/js/ai_chat.js
public/js/ai_agent.js
public/js/mobile-nav.js

public/css/ai_chat.css
public/css/ai_agent.css
public/css/responsive.css
```

## Proposed Operator Docs

Final implementation docs should be promoted from this research folder into
normal `docs/` only after root approves implementation:

```text
docs/AI_AGENT_PLATFORM_CONTROL.md
docs/AI_AGENT_TOOL_POLICY.md
docs/WEBCHAT_LLM_INTEGRATION.md
docs/MOBILE_RESPONSIVE_DESIGN.md
```

## Proposed Tests

```text
tests/test_llm_adapters.py
tests/test_agent_policy.py
tests/test_agent_tools.py
tests/test_agent_confirmations.py
tests/test_agent_injection.py
tests/test_agent_audit.py
```

## Boundary

The LLM layer must not receive:

- session cookies
- CSRF tokens
- password hashes
- secret keys
- environment variables
- raw database connection details
- private file contents unless explicitly requested and authorized

See [CURRENT_REPO_RECONCILIATION.md](CURRENT_REPO_RECONCILIATION.md) for route
and frontend naming constraints.
