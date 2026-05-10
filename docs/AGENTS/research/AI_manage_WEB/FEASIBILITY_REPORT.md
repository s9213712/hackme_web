# Feasibility Report

## Verdict

Feasibility: **7.5 / 10**

Recommended start: **Phase 0 docs + Phase 1 read-only management console**.

Do not start with autonomous write operations. The safe first target is a
read-only operations layer where AI explains status and produces
evidence-backed recommendations. Drafts, previews, pending actions, and
execution are later phases gated by LLM_WEBCHAT.

## Why It Fits `hackme_web`

The project already has modules that can become AI-observable surfaces:

- forum and community content
- direct messages / chat
- cloud drive and attachments
- points / economy / future PointsChain
- marketplace
- trading records and bot audit
- admin center
- audit logs
- snapshot / restore state
- Server Mode v2
- security smoke / pentest gates

The proposed [LLM_WEBCHAT](../LLM_WEBCHAT/) layer already defines the correct
foundation:

- local LLM adapters
- tool registry
- policy engine
- planner / executor
- confirmation system
- audit logs
- prompt-injection defense
- mobile Agent Console

AI-managed web should reuse those components and add an operations layer on top.

## Main Benefits

1. Faster admin triage.
2. Better visibility across logs, reports, snapshots, and queues.
3. Safer operator workflow through previews and confirmation.
4. Consistent release / security checklist execution.
5. Mobile-friendly administration.
6. Reduced root/admin cognitive load.

## Main Risks

| Risk | Severity | Mitigation |
|---|---|---|
| AI performs unauthorized admin action | Critical | Tool registry + policy engine + confirmation |
| Prompt injection from forum/file content | High | untrusted content wrapper + no policy override |
| AI leaks private data | High | scoped tools + output redaction + audit |
| AI causes production damage | Critical | production-safe mode + disabled critical tools |
| Audit log misses action context | High | action_id on every tool call |
| Operator over-trusts AI recommendation | Medium | confidence, evidence links, dry-run previews |
| Mobile UI hides risk details | Medium | mandatory risk cards and confirmation screens |

## Current Blockers

1. `LLM_WEBCHAT` is still a research proposal.
2. Tool schemas and policy engine do not exist yet.
3. Confirmation system is not implemented.
4. Agent audit storage is not implemented.
5. There is no AI operations dashboard.
6. Existing admin actions are not yet wrapped as allowlisted tools.

## Feasibility By Capability

| Capability | Feasibility | Notes |
|---|---:|---|
| Read-only dashboard summary | High | Uses existing pages/logs through safe tools |
| QA/checklist guidance | High | Mostly summarization + tool execution |
| Draft creation | High | Forum/listing drafts are low-risk |
| Admin triage suggestions | Medium-high | Needs audit and evidence links |
| User moderation queue assistance | Medium | Requires careful privacy and appeal rules |
| Points/economy recommendations | Medium | Must not adjust balances directly |
| Trading risk suggestions | Medium | Read-only first; no autonomous trades |
| Snapshot recommendations | Medium | Create snapshot can be high-risk; restore forbidden |
| Security checks | Medium-low | AI can suggest/run safe checks, not pentest in v1 |
| Autonomous root operations | Low | Not recommended |

## Recommendation

Proceed only as:

```text
observe -> evidence -> suggest -> preview -> pending action -> human confirm -> execute -> audit
```

The first implementation should stop at:

```text
observe -> evidence -> suggest -> audit
```

Never as:

```text
prompt -> AI decides -> AI executes root/admin operation
```
