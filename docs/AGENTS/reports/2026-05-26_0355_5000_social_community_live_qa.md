# 2026-05-26 03:55 5000 Social/Community Live QA

Scope: live `https://127.0.0.1:5000` social feature audit with `test`, `admin`, and `root` cookies.

## Passed

- Friend request flow: `test -> admin` created a request, admin notification appeared, admin accepted, and test received an accepted notification.
- User profile privacy: viewing admin from test did not expose `friend_code`; PM target options only exposed valid friend/admin targets.
- Community board flow: normal user board creation is still blocked by current policy; manager-created board request entered review and was approved by manager.
- Community thread flow: test created an approved normal thread on the approved board, replied successfully, and the thread detail returned the expected post.
- Sensitive word enforcement: a blocked reply returned 403, did not insert a post, recorded a violation for `test`, and wrote `COMMUNITY_SENSITIVE_BLOCKED`.
- Financial invariants stayed green after reload: `/api/root/points/financial-invariants` returned `ok:true`, `status:"pass"`.

## Fixed

- `GET /api/community/boards/<board_id>/threads` previously returned `can_post_directly:false` for a normal member even though the same member's thread was immediately approved.
- The response now distinguishes posting/moderation semantics:
  - `can_post_directly`
  - `can_post_without_review`
  - `requires_thread_review`
  - `can_moderate`
- New coverage in `tests/community/test_community_permissions.py` verifies newbie users require review and normal users can post without review.

## Validation

- `python3 -m py_compile routes/community.py tests/community/test_community_permissions.py`
- `python3 -m pytest tests/community/test_community_permissions.py -q` -> 32 passed
- `git diff --check -- routes/community.py tests/community/test_community_permissions.py`
- Live reload: `kill -HUP 211291`
- Live API confirmed test user sees `can_post_directly:true`, `can_post_without_review:true`, `requires_thread_review:false`, `can_moderate:false`.

## Notes

- A 400 during board review was caused by a manual QA payload using `decision` instead of the expected `action`; the correct payload succeeded.
- One old worker timeout was observed during a previous reload cycle; after this reload, live social requests and financial invariant checks returned 200 without new traceback.
