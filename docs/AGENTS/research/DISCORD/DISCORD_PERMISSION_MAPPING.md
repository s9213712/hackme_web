# Discord Permission Mapping

Discord identity is only an external identity signal. `hackme_web` permissions
remain authoritative.

## Identity Mapping

```text
discord_user_id -> discord_accounts -> hackme_web user_id
```

Inbound canonical write requires:

1. Discord account linked.
2. Linked `hackme_web` account active.
3. User not suspended, blocked, or revoked.
4. Binding active.
5. Binding direction allows inbound.
6. Server mode allows inbound for binding scope.
7. Source-specific permission allows write.
8. Content policy allows processing.
9. Rate limit and queue policy allow processing.

## Source-specific Checks

Forum:

- board permission
- thread lock status
- moderation status
- member level

Chat room:

- room membership
- room write permission
- block list
- room moderation status

DM bridge:

- both users approved DM bridge consent
- both Discord accounts linked
- neither user blocked the other
- neither user revoked consent
- bridge channel/thread permission has not drifted

## Role Rules

Do not map:

```text
Discord admin    -> hackme_web root/admin/manager
Discord mod role -> hackme_web moderator
Discord role     -> member_level
```

Discord roles may be shown as external metadata for root/admin review, but they
do not grant site permissions.
