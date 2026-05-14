# Provider Security

## Provider URL Rules

1. Provider base URL is root-configured only.
2. Normal requests cannot set arbitrary provider URLs.
3. Default allowed hosts are `localhost`, `127.0.0.1`, and `::1`.
4. LAN providers require a separate root-only enable flag.
5. URLs with username/password are rejected.
6. Redirects to non-allowlisted hosts are rejected.
7. Only `http` and `https` schemes are allowed.
8. `file://`, `ftp://`, `gopher://`, and similar schemes are forbidden.
9. Timeout must be bounded.
10. Provider offline must return friendly error.
11. Every request re-resolves hostname and verifies the resolved IP is still
    allowlisted.

## SSRF Protection

The adapter layer must not become an internal network scanner. Provider
configuration should be validated at save time and again before every request.

Before each provider request:

1. Parse and normalize the URL.
2. Reject encoded or unusual IP forms that cannot be safely normalized.
3. Resolve the hostname.
4. Check every resolved IP against the allowlist.
5. Reject redirects unless the redirect target passes the same checks.

Test cases:

```text
http://2130706433:11434
http://0177.0.0.1:11434
http://[::ffff:127.0.0.1]:11434
DNS first resolves public, then private
redirect to 127.0.0.1 from non-allowlisted host
```

## Model Selection

Model name should be selected from:

- configured allowlist, or
- provider-discovered model list that root/admin approved.

Do not pass arbitrary user-provided model strings directly to provider.

## Health Check

Expose provider health through AI namespace only:

```text
GET /api/ai/providers
```

The response may include provider availability, configured model allowlist, and
friendly error codes. It must not include raw provider URLs if those URLs contain
private LAN hostnames or secret-bearing config.

## Provider Tool Calls

Provider-native tool-call formats are disabled by default:

```yaml
llm:
  enable_provider_tool_format: false
agent:
  enable_tools: true
```

If a provider returns tool calls during WebChat, treat them as plain suggestions.
Only Agent Executor can execute tools after registry, schema, mode, role, and
policy checks.
