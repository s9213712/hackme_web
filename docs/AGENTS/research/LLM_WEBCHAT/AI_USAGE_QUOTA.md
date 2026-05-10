# AI Usage Quota

## Why Quotas Exist

Local LLMs still need limits. Without quotas, AI chat and agent plans can be
used for denial-of-service, privacy scraping, or unbounded log growth.

## Suggested Settings

```text
AI_CHAT_DAILY_LIMIT
AI_AGENT_PLAN_DAILY_LIMIT
AI_AGENT_TOOL_CALL_LIMIT_PER_PLAN
AI_AGENT_MAX_CONTEXT_CHARS
AI_AGENT_MAX_FILE_SNIPPET_CHARS
AI_AGENT_MAX_TOOL_OUTPUT_CHARS
AI_AGENT_TIMEOUT_SECONDS
AI_AGENT_PROVIDER_TIMEOUT_SECONDS
```

## Conservative Defaults

```text
AI_CHAT_DAILY_LIMIT=100
AI_AGENT_PLAN_DAILY_LIMIT=20
AI_AGENT_TOOL_CALL_LIMIT_PER_PLAN=8
AI_AGENT_MAX_CONTEXT_CHARS=24000
AI_AGENT_MAX_FILE_SNIPPET_CHARS=6000
AI_AGENT_MAX_TOOL_OUTPUT_CHARS=12000
AI_AGENT_TIMEOUT_SECONDS=45
AI_AGENT_PROVIDER_TIMEOUT_SECONDS=30
```

Root may tune these values. Normal users cannot tune them.

Production should default to stricter or equal limits than dev/test. Test and
internal_test can use lower limits to catch quota handling early.

## V1 Policy

V1 does not charge points. It uses:

- rate limit
- daily quota
- max context size
- max tool calls per plan
- timeout

## Future PointsChain Billing

V2 may add PointsChain usage ledger, but only after PointsChain v2 ledger,
supply, and transfer semantics are stable.

Do not mix PointsChain billing into v1 WebChat / Agent implementation.
