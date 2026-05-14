# Discord OAuth Security

V1 account linking uses Discord OAuth2 only for identity binding.

## V1 Scope

```text
identify
```

Do not request in V1:

- `email`
- `guilds`
- `connections`
- long-lived user access outside the callback

Do not store long-term Discord user access tokens unless a future phase has a
separate approved design.

## Start Flow

1. Logged-in user requests link start.
2. Server creates cryptographically random `state`.
3. Store only `state_hash`.
4. Bind state to `user_id`, `redirect_after`, and TTL.
5. Redirect only to configured Discord OAuth URL and configured callback URI.

## Callback Flow

1. Require logged-in user.
2. Hash submitted `state` and find pending row.
3. Reject missing, expired, used, revoked, or different-user state.
4. Exchange code with short timeout.
5. Fetch Discord identity.
6. Enforce unique `discord_user_id`.
7. Mark state `used`.
8. Write or update `discord_accounts`.

## Collision Handling

- If Discord account is already linked to another active `hackme_web` user,
  reject and write audit.
- If current user re-links the same Discord account, update profile metadata and
  scopes.
- If account was revoked, allow re-link only after a fresh OAuth flow.
- If account is blocked, root/admin action is required before re-link.

## Redirect Rules

- Callback URL must be allowlisted.
- `redirect_after` must be local-site relative path only.
- External redirect URLs are rejected.
- OAuth errors are redacted before UI/audit output.

## Revoke Rules

- User may revoke their own Discord link.
- Revoke pauses bindings that require that account.
- Revoke pauses any DM bridge consent for that user.
- Revoke does not delete historical audit or message mappings.
