# Requirement Gap Audit - 2026-05-16 18:41

Scope: scan recent conversation-driven requirements for features that were treated as requirements but did not fully land in code. This pass is a static/source audit, not a full browser stress QA run.

## Confirmed Gaps

### 1. Direct E2EE file key sharing bypasses the friend-target rule

Requirement: targeted actions such as cloud-drive sharing should let normal users select only accepted friends; privileged roles only get all-user targeting for explicit management contexts.

Evidence:
- `routes/share_management.py` enforces `assert_can_target_user(..., context="cloud_drive_share")` for managed share links.
- `routes/files.py` `/api/files/<file_id>/share` calls `share_e2ee_file(...)` directly.
- `services/storage/cloud_drive.py::share_e2ee_file` checks file ownership, E2EE mode, self-share, key presence, and recipient existence, but does not check `assert_can_target_user`.

Impact: a normal user who knows a user id may grant E2EE key access to a non-friend through the direct E2EE share endpoint.

Recommended fix: enforce `assert_can_target_user(conn, actor, recipient_user_id, context="cloud_drive_share")` inside `share_e2ee_file` or immediately before calling it, and add a regression test for non-friend denial plus friend success.

### 2. Game invites are not wired to the friend-target rule

Requirement: only friends can invite each other to games; root/manager exceptions are for management/private-message contexts, not general game invitations.

Evidence:
- `services/users/friends.py` already defines `game_invite` and `game_multiplayer_invite` as personal target contexts.
- `routes/games.py::create_game_multiplayer_invite` resolves `opponent_username` and inserts an invite without `assert_can_target_user`.
- `routes/games.py::create_chess_invite` does the same for chess invites.

Impact: normal users can invite non-friends by username.

Recommended fix: add `assert_can_target_user(..., context="game_multiplayer_invite")` and `assert_can_target_user(..., context="game_invite")` before invite creation, with route-level tests.

### 3. Public profile entry points are only partially implemented

Requirement: clicking a comment/post/video owner name or avatar should open that user's profile.

Evidence:
- Backend profile APIs exist: `/api/users/me/profile`, `/api/users/<id>/profile`, friends APIs, friend code, target options.
- The personal profile panel exists in the sidebar and user card/edit flow.
- `public/js/00-core.js::userIdentityMarkup` renders avatar/name as static spans.
- Community threads/posts call `userIdentityMarkup(...)`, and video detail renders owner name as plain text.
- No frontend handler/function was found for `openUserProfile`, `data-profile-user`, or equivalent public profile navigation.

Impact: users can manage their own profile/friends, but the requested cross-feature discovery path to other users' pages is not complete.

Recommended fix: add a public profile viewer modal/panel, make `userIdentityMarkup` optionally clickable when `user_id` exists, and wire community/video owner names to `/api/users/<id>/profile`.

## Partial / Known Deferred Items

### Server-side encrypted pipeline

Current state:
- New `server_encrypted` uploads use chunked server-side encryption instead of splitting behavior by file size.
- Download and inline media content decrypt in chunks, so the main server no longer reads the whole encrypted file into memory.
- The old single-token Fernet format remains read-compatible only for files that were already stored that way.

This removes the user-facing large-file rejection path. A fully resumable/background server-side encryption pipeline with per-file encryption progress is still a separate future hardening step.

### Diffusers / in-process ComfyUI backend

Current state:
- `services/comfyui/diffusers_client.py` blocks in-process Diffusers generation unless `HTML_LEARNING_ALLOW_IN_PROCESS_DIFFUSERS=1`.
- Default ComfyUI mode is `remote`.

This is acceptable hardening. The UI still exposes Diffusers mode text, but the dangerous runtime path is fail-closed by default.

## Confirmed Landed In This Audit

- Trading background engine exists, starts server-side, and has tests for running without a login session.
- Root trading `run-once` is enqueue-and-return, not synchronous execution.
- Root trading sitewide/report endpoints read stored snapshots.
- Trading default price source is Binance public API, with fused price retained as fallback/configurable root mode.
- Root points wallet tabs for funding pool, all-user positions, and PointsChain circulation are present.
- BT/direct-link downloads are task-center backed, show speed, support pause/resume/cancel, and prioritize queued jobs by availability score.
- HLS preparation uses an external worker path and Job Center rows.
- E2EE stream v2 preparation has Job Center representation and inline bundle size guards.
- System resource board exists with CPU/GPU/VRAM/RAM gauges and cached resource sampling.
- Cloud-drive capacity UI is a water-level visual, not a battery metaphor.
- Stockfish depth only appears for Stockfish/stockfisher difficulty and is persisted/capped server-side.
- Share management has edit buttons, copy feedback, video share handoff, and events visibility.
- Official chat anonymity and regular group optional anonymity are implemented as separate mechanisms.

## Suggested Next Patch Order

1. Enforce friend-target checks on direct E2EE file sharing and game invites.
2. Add public profile viewer/entry points for community and video owner identities.
3. Decide whether `server_encrypted` should remain capped-only or get a true background encryption worker.
