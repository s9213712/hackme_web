# 2026-05-26 09:02 Live :5000 Profile / Friends QA

Scope: continued multi-account social QA on live `https://127.0.0.1:5000`, using `test` and `qa_upload_0402`.

## Findings

### P1 Fixed: friend APIs leaked raw `users` rows in response payloads

`POST /api/friends/request` returned `request.target` as the raw active user row. In live testing, a normal user saw fields such as encrypted `nickname`, account timestamps, level metadata, and login/security-related columns for the target account.

Fix:

- `services/users/friends.py` now sanitizes returned `target` payloads through a public user payload helper.
- The fix covers friend request, friend-code add, block, and follow response payloads.
- Regression tests assert private keys such as `status`, `created_at`, `updated_at`, `nickname`, `id_number`, `phone`, and login/security columns are not returned.

Live verification after reload:

```json
"target": {
  "avatar_file_id": "",
  "display_name": "qa_upload_0402",
  "id": 4,
  "is_official": false,
  "member_level": "normal",
  "role": "user",
  "role_label": "使用者",
  "username": "qa_upload_0402"
}
```

### Operational Note: reload initially failed due to partial dependency sync

During live sync, only `services/users/friends.py` was copied first. The live run root still had an older `services/users/profiles.py`, so gunicorn workers failed to import `profile_style_for_payload`.

Recovery:

- Synced `services/users/profiles.py` to the live run root.
- Restarted gunicorn on `127.0.0.1:5000`.
- New live master PID: `752480`.
- `/api/version` and social APIs are responding again.

## Verified

- Friend request from `test` to `qa_upload_0402` creates an unread `friend_request` notification.
- Accepting the request from `qa_upload_0402` creates an unread `friend_request_accepted` notification for `test`.
- After acceptance, `test` viewing `qa_upload_0402` shows `friend_status: accepted`, `can_pm: true`, and `can_invite_game: true`.
- Blocking `qa_upload_0402` from `test` returns only public target fields, removes interactive capability from the blocked side, and prevents a reverse friend request.
- Unblocking and re-requesting restores the normal pending/accept flow.
- Public profile payload does not expose `friend_code` or display timezone for another user.
- Frontend source hides Edit/Friends tabs when viewing another user profile and forces the profile tab back to Home.
- Financial invariants stayed green after the restart: `status: pass`, `flow_gap_points: 0`, and `pc0_operational_ledgers_not_sealed_into_pc1_blocks: pass`.

## Commands

- `pytest tests/users/test_profile_friends.py -q`
  - Passed.
- `python3 -m py_compile services/users/friends.py routes/users.py`
  - Passed.
- `pytest tests/users/test_profile_friends.py tests/frontend/users/test_profile_friends_frontend.py -q`
  - Passed.
- Manual live API checks with `test` and `qa_upload_0402`.

## Follow-up

The live restart was recovered, but the replacement gunicorn was started manually after the original master exited. Future syncs should copy dependency groups together or run an import check inside the live run root before HUP/restart.
