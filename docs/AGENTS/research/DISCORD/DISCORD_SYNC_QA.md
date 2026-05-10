# Discord Sync QA

## Unit Tests

```text
test_discord_binding_create
test_discord_account_link
test_discord_oauth_state_hash_only
test_discord_oauth_state_single_use
test_discord_oauth_state_user_mismatch_rejected
test_root_config_secret_refs_only
test_outbound_job_idempotency
test_loop_guard
test_allowed_mentions_disabled
test_rate_limit_retry_after
test_rate_limit_dead_letter_after_max_attempts
test_unlinked_discord_user_rejected
test_dm_sync_requires_both_opt_in
test_dm_sync_revoke_pauses_binding
test_dm_sync_expired_consent_rejected
test_binding_policy_version_mismatch_blocks_resume
test_payload_redacted_before_audit
test_discord_role_does_not_grant_web_role
test_attachment_v1_link_only
```

## Integration Tests

Use fakes, not live Discord:

- fake Discord adapter
- fake Gateway event
- fake REST send
- fake 429 response
- fake global rate-limit response
- fake edit/delete events
- fake Message Content unavailable event
- fake Discord permission drift
- fake OAuth callback
- fake root config secret store

## Security Tests

```text
bot token 不出現在 response/log
webhook token 不出現在 audit detail
external inbound endpoint HMAC fail rejects
Discord @everyone 被 neutralize
unlinked Discord user 不能寫 private DM
blocked user 不能透過 Discord 繞過 block
incident_lockdown pauses sync
maintenance pauses queue without dropping jobs
OAuth state is single-use and TTL-bound
DM consent token is hash-only and single-use
Message Content unavailable blocks canonical inbound write
policy_version mismatch blocks old queued job
dead-letter jobs are not replayed automatically
allowed_mentions disabled on retry payloads
raw payload is not stored in high-sensitivity audit
```

## Manual Smoke

1. Root configures Discord bot.
2. Admin binds forum board.
3. Web thread appears in Discord.
4. Discord reply appears on web.
5. Web edit updates Discord.
6. Discord delete becomes web tombstone.
7. Both users opt in to DM bridge.
8. DM bridge works.
9. Either user revokes; bridge pauses.

## MVP Acceptance

MVP passes only when:

1. Account linking works.
2. Root/admin config works.
3. Forum board binding works.
4. Web outbound creates Discord message/thread.
5. Message mapping is written after outbound success.
6. Queue honors fake 429 retry.
7. Dead-letter queue is visible and not auto-replayed.
8. Audit logs are written.
9. `maintenance` and `incident_lockdown` pause sync.
10. OAuth state is hash-only, TTL-bound, and single-use.
11. `allowed_mentions.parse=[]` is enforced.
12. Inbound canonical writes are disabled in MVP.
13. Chat room sync, DM bridge, attachment import, reaction sync, role sync, and
    history backfill are disabled in MVP.

## Risk Matrix

| Risk | Level | Mitigation |
|---|---|---|
| Private message leak | High | opt-in, default off, revoke, audit |
| Self-bot policy violation | High | bot/OAuth/webhook only |
| Message Content intent unavailable | Medium-high | outbound-only first, inbound checklist |
| Sync loop | High | mapping + bot ignore + idempotency |
| Discord rate limit | Medium | queue + header-based retry |
| Permission bypass | High | inbound permission guard |
| Attachment safety | High | V1 link-only; V2 quarantine + scan |
| Discord permission drift | Medium | reconcile + admin alert |
| Test data pollutes production | Medium-high | Server Mode scope + test guild + shadow binding |
| OAuth CSRF/state replay | High | hash-only state, TTL, same-user callback, single-use |
| Raw payload leakage | High | payload hash + redacted payload summary only |
