# LLM Adapter Layer

## Supported Providers

### Ollama

Default endpoint:

```text
http://localhost:11434/api/chat
```

### LM Studio

Default endpoint:

```text
http://localhost:1234/v1/chat/completions
```

LM Studio uses an OpenAI-compatible API.

## Config

```yaml
llm:
  provider: lmstudio
  model: local-model
  ollama_base_url: http://localhost:11434
  lmstudio_base_url: http://localhost:1234/v1
  timeout_seconds: 60
  enable_provider_tool_format: false
  enable_streaming: false
agent:
  enable_tools: true
```

## Module Responsibilities

| File | Responsibility |
|---|---|
| `services/llm/base.py` | Common request / response dataclasses and provider interface |
| `services/llm/ollama.py` | Ollama adapter |
| `services/llm/lmstudio.py` | LM Studio OpenAI-compatible adapter |
| `services/llm/router.py` | Select provider from config and request override |

## Adapter Contract

Every provider should return a normalized response:

```json
{
  "ok": true,
  "assistant_message": "...",
  "tool_calls": [],
  "usage": {},
  "provider": "lmstudio",
  "model": "local-model",
  "error": null
}
```

Provider errors must be user-safe:

```json
{
  "ok": false,
  "assistant_message": "",
  "tool_calls": [],
  "usage": {},
  "provider": "ollama",
  "model": "llama3",
  "error": {
    "code": "provider_unavailable",
    "message": "Local LLM provider is not reachable. Check Ollama or LM Studio."
  }
}
```

## Failure Handling

The adapter layer must not crash the Flask server on:

- timeout
- refused connection
- provider process not started
- missing model
- malformed provider response
- unsupported provider

## Secret Handling

Adapters must not read or send:

- session cookies
- CSRF tokens
- secret keys
- environment variables
- database URLs
- password / token fields

Provider URL and model selection rules are defined in
[PROVIDER_SECURITY.md](PROVIDER_SECURITY.md).
