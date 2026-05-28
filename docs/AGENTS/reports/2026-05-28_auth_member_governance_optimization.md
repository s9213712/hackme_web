# Auth / Member Governance Optimization

Date: 2026-05-28

## Scope

- Optimized account and member-management read paths for large member/session
  sets.
- Hardened registration gift recovery so only accounts explicitly marked as
  deferred can receive login-time signup-gift reissue.
- Rechecked auth, session, member-level, governance, CSRF, and related frontend
  wiring.

## Changes

- Added users indexes for status, role/status, effective level/status, sanction
  status, last login, lowercase username, and lowercase email lookups through
  both runtime migration and bootstrap schema.
- Added auth DB composite indexes for CSRF username/expiry, login attempts by
  user/success/time, and active sessions by user/expiry.
- Changed admin user-list online-session decoration to query only users on the
  current page instead of aggregating every active session.
- Added `users.signup_bonus_deferred`. Registration sets it when points/wallet
  initialization fails, and login retries the signup gift only for flagged
  approved accounts.
- Added legacy migration coverage for `blocked_until` in the public account
  column repair helper.
- Updated frontend avatar static coverage to match the current cropper zoom
  range and save guard condition.

## Verification

- `python3 -m py_compile routes/public.py routes/users.py services/security/identity.py services/server/database.py services/security/permissions.py services/users/member_levels.py tests/account/auth/test_account_register.py tests/account/auth/test_account_lockout.py tests/account/sessions/test_account_sessions.py tests/users/test_identity_schema.py tests/platform/test_auth_db_split.py`
- `pytest -q tests/users/test_identity_schema.py tests/platform/test_auth_db_split.py tests/account/auth/test_account_register.py`
- `pytest -q tests/account/auth/test_account_lockout.py tests/account/sessions/test_account_sessions.py`
- `pytest -q tests/users/test_member_level_rules.py tests/users/test_member_governance_dispositions.py tests/users/test_sanction_notices.py tests/users/test_profile_friends.py`
- `pytest -q tests/security/auth/test_access_controls.py tests/security/auth/test_auth_csrf_safe.py tests/security/auth/test_session_idle_timeout.py`
- `pytest -q tests/frontend/auth/test_frontend_auth_timeout.py tests/frontend/auth/test_frontend_captcha.py tests/frontend/auth/test_frontend_avatar.py tests/frontend/auth/test_frontend_birthday.py tests/frontend/auth/test_frontend_register.py tests/frontend/admin/test_frontend_account_admin.py tests/frontend/community/test_frontend_governance.py`
- `pytest -q tests/platform/test_release_policy.py tests/scripts/prepush/test_prepush_v2.py`
- `git diff --check`

All listed checks passed after the avatar static-test contract was updated.

## Remaining Optimization Queue

- Add request-level microbenchmarks around `/api/admin/users` for query time,
  session-decoration time, JSON serialization time, response bytes, and RSS
  delta.
- Add an admin-user pagination stress probe with large user and session counts.
- Consider a lightweight member-governance snapshot for dashboard counters if
  root pages start combining account, sanction, appeal, and report aggregates in
  one request.
