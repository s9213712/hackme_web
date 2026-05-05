#!/usr/bin/env bash
# 01_internal_test_login_token.sh
# ---------------------------------------------------------------------------
# 教學：internal_test login token 完整生命週期
#
#   internal_test login token 是 "門票"：
#   - 由 root 產生 / 輪換
#   - 全站只有一個（singleton；存在 system_settings.internal_test_login_token_hash）
#   - 只在 server 處於 `internal_test` mode 時，會在 /api/login 額外驗證
#   - 在其他 mode 下 server 不會檢查它（也不會用它授權任何事）
#
# 流程（root + tester 兩個視角）：
#   ROOT
#     1. 確認 server 健康
#     2. 用 root 帳號登入 + 完成 forced password change
#     3. 把 server 切到 `internal_test` mode（confirm phrase: SWITCH_TO_INTERNAL_TEST）
#     4. POST /api/admin/access-controls/internal-test-token
#        → 回 issued plaintext token；server 只存 hash
#     5. 安全把 token 交給被邀請的 tester（out-of-band；本腳本印 fingerprint，不印 raw）
#   TESTER
#     6. 用 tester 帳號 + 平常密碼 + internal_test_token 登入
#     7. 確認 /api/me 看得到自己 session
#     8. 想登出再做事就走平常 /api/logout
#
# Usage:
#   BASE_URL=https://127.0.0.1:5000 \
#   ROOT_USER=root \
#   ROOT_NEW_PW='RootStrongP@ssw0rd' \
#   TESTER_USER=test \
#   TESTER_PW=testpw \
#     bash 01_internal_test_login_token.sh
#
# Notes:
#   - Designed for ISOLATED dev / canary runtime only.
#   - Never paste a real production token into this script.
#   - Token raw value is never echoed; only first 8 chars + "..." + last 4 chars
#     of the sha256 fingerprint are shown so you can match it across logs.

set -euo pipefail

BASE_URL="${BASE_URL:-https://127.0.0.1:5000}"
ROOT_USER="${ROOT_USER:-root}"
ROOT_NEW_PW="${ROOT_NEW_PW:?need ROOT_NEW_PW (post-forced-change root password)}"
ROOT_INITIAL_PW="${ROOT_INITIAL_PW:-$ROOT_NEW_PW}"  # 第一次跑時可能還是 initial pw
TESTER_USER="${TESTER_USER:-test}"
TESTER_PW="${TESTER_PW:?need TESTER_PW (tester normal password)}"

# NOTE: internal_test mode has browser_only_mode_enabled=true, which blocks
# /api/* requests without a browser-like User-Agent. The tutorial therefore
# sends a Mozilla-marker UA on every curl. (See SERVER_MODE_V2_PROFILE_MATRIX.md
# §Mode Behavior Matrix browser_only row.)
CURL_OPTS=(-sk --max-time 30 -H "User-Agent: Mozilla/5.0 (X11; Linux) HackmeWebTutorialClient/1.0")

# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

say() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# Print only a fingerprint of the token, not the raw value.
print_fingerprint() {
  local token="$1"
  local fp
  fp=$(printf '%s' "$token" | sha256sum | awk '{print $1}')
  printf '  fingerprint sha256: %s...%s (length=%d)\n' \
    "${fp:0:8}" "${fp: -4}" "${#token}" >&2
}

# Get a CSRF token + cookie jar in a single function.
get_csrf() {
  local cookie_jar="$1"
  curl "${CURL_OPTS[@]}" -c "$cookie_jar" -b "$cookie_jar" \
    "$BASE_URL/api/csrf-token" \
    | jq -re '.csrf_token'
}

# ────────────────────────────────────────────────────────────────────────────
# ROOT side
# ────────────────────────────────────────────────────────────────────────────

ROOT_JAR=$(mktemp); trap 'rm -f "$ROOT_JAR" "$TESTER_JAR"' EXIT
TESTER_JAR=$(mktemp)

say "1) probe server"
curl "${CURL_OPTS[@]}" -o /dev/null -w "  HTTP %{http_code}  bytes=%{size_download}\n" \
  "$BASE_URL/api/version" || fail "server not reachable at $BASE_URL"

say "2) root login (initial or post-change)"
csrf=$(get_csrf "$ROOT_JAR")
login_resp=$(curl "${CURL_OPTS[@]}" -c "$ROOT_JAR" -b "$ROOT_JAR" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/login" \
  -d "{\"username\":\"$ROOT_USER\",\"password\":\"$ROOT_INITIAL_PW\",\"csrf_token\":\"$csrf\"}")
login_ok=$(printf '%s' "$login_resp" | jq -r '.ok // false')
must_change=$(printf '%s' "$login_resp" | jq -r '.must_change_password // false')
[ "$login_ok" = "true" ] || fail "root login failed: $login_resp"

if [ "$must_change" = "true" ]; then
  say "  forced password change required (first login). PUTting new pw via /api/admin/users/<root_id>"
  me=$(curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" "$BASE_URL/api/me")
  rid=$(printf '%s' "$me" | jq -r '.id')
  csrf=$(get_csrf "$ROOT_JAR")
  curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" \
    -H "Content-Type: application/json" \
    -H "X-CSRF-Token: $csrf" \
    -X PUT "$BASE_URL/api/admin/users/$rid" \
    -d "{\"current_password\":\"$ROOT_INITIAL_PW\",\"password\":\"$ROOT_NEW_PW\",\"password_confirm\":\"$ROOT_NEW_PW\",\"csrf_token\":\"$csrf\"}" \
    | jq -e '.ok' >/dev/null || fail "password change failed"
  # re-login with new pw
  rm -f "$ROOT_JAR"; ROOT_JAR=$(mktemp)
  csrf=$(get_csrf "$ROOT_JAR")
  curl "${CURL_OPTS[@]}" -c "$ROOT_JAR" -b "$ROOT_JAR" \
    -H "Content-Type: application/json" \
    -H "X-CSRF-Token: $csrf" \
    -X POST "$BASE_URL/api/login" \
    -d "{\"username\":\"$ROOT_USER\",\"password\":\"$ROOT_NEW_PW\",\"csrf_token\":\"$csrf\"}" \
    | jq -e '.ok' >/dev/null || fail "re-login with new pw failed"
fi

say "3) check current server mode and switch to internal_test if needed"
mode_resp=$(curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" "$BASE_URL/api/root/server-mode")
# /api/root/server-mode returns: {"ok": true, "mode": {"current_mode": "...", ...}, ...}
# so we read mode.current_mode (nested), with fallbacks for older shapes.
current_mode=$(printf '%s' "$mode_resp" | jq -r '.mode.current_mode // .current_mode // "unknown"')
say "  current_mode=$current_mode"

if [ "$current_mode" != "internal_test" ]; then
  # safety: NEVER auto-switch to internal_test from production. Only from
  # dev_ready / test / superweak / maintenance is it considered safe in this demo.
  case "$current_mode" in
    production|incident_lockdown)
      fail "refusing to auto-switch from '$current_mode' to internal_test. Switch manually."
      ;;
  esac

  say "  creating mode_checkpoint then switching to internal_test"
  csrf=$(get_csrf "$ROOT_JAR")
  curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" \
    -H "Content-Type: application/json" \
    -H "X-CSRF-Token: $csrf" \
    -X POST "$BASE_URL/api/root/server-mode/checkpoint" \
    -d "{\"target_mode\":\"internal_test\",\"reason\":\"prepare internal_test demo\",\"csrf_token\":\"$csrf\"}" \
    | jq -e '.ok' >/dev/null || fail "checkpoint failed"
  csrf=$(get_csrf "$ROOT_JAR")
  curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" \
    -H "Content-Type: application/json" \
    -H "X-CSRF-Token: $csrf" \
    -X POST "$BASE_URL/api/root/server-mode/switch" \
    -d "{\"target_mode\":\"internal_test\",\"confirm\":\"SWITCH_TO_INTERNAL_TEST\",\"reason\":\"internal_test login-token demo\",\"csrf_token\":\"$csrf\"}" \
    | jq -e '.ok' >/dev/null || fail "mode switch failed (need root + correct phrase)"
fi

say "4) rotate internal_test login token"
csrf=$(get_csrf "$ROOT_JAR")
rotate_resp=$(curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/admin/access-controls/internal-test-token" \
  -d "{\"confirm\":\"ROTATE_INTERNAL_TEST_TOKEN\",\"ttl_minutes\":60,\"csrf_token\":\"$csrf\"}")
issued=$(printf '%s' "$rotate_resp" | jq -r '.token // .issued_token // empty')
[ -n "$issued" ] || fail "rotate did not return a token: $rotate_resp"
say "  rotation OK"
print_fingerprint "$issued"

say "5) hand the issued token to the tester out-of-band (e.g. encrypted IM)."
say "   For the demo we keep it in a shell variable. In real ops, transmit"
say "   securely and zero it in shell history when done."

# ────────────────────────────────────────────────────────────────────────────
# TESTER side
# ────────────────────────────────────────────────────────────────────────────

say "6) tester login attempt WITHOUT internal_test_token (should fail in internal_test mode)"
csrf=$(get_csrf "$TESTER_JAR")
no_token_resp=$(curl "${CURL_OPTS[@]}" -c "$TESTER_JAR" -b "$TESTER_JAR" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/login" \
  -d "{\"username\":\"$TESTER_USER\",\"password\":\"$TESTER_PW\",\"csrf_token\":\"$csrf\"}" \
  -w "  HTTP %{http_code}\n")
say "  expected: rejected because internal_test mode requires the login token"
printf '%s\n' "$no_token_resp" | head -3 >&2

# fresh jar (the failed login may have set a 4xx cookie)
rm -f "$TESTER_JAR"; TESTER_JAR=$(mktemp)

say "7) tester login WITH internal_test_token (should succeed)"
csrf=$(get_csrf "$TESTER_JAR")
ok_resp=$(curl "${CURL_OPTS[@]}" -c "$TESTER_JAR" -b "$TESTER_JAR" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/login" \
  -d "$(jq -n --arg u "$TESTER_USER" --arg p "$TESTER_PW" \
                 --arg t "$issued"     --arg c "$csrf" \
            '{username:$u, password:$p, internal_test_token:$t, csrf_token:$c}')")
ok=$(printf '%s' "$ok_resp" | jq -r '.ok // false')
[ "$ok" = "true" ] || fail "tester login (with token) failed: $ok_resp"
say "  login OK"

say "8) /api/me sanity check"
curl "${CURL_OPTS[@]}" -b "$TESTER_JAR" "$BASE_URL/api/me" \
  | jq '{username, role, status, role_label}'

say "9) tester logout"
csrf=$(get_csrf "$TESTER_JAR")
curl "${CURL_OPTS[@]}" -b "$TESTER_JAR" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/logout" \
  -d "{\"csrf_token\":\"$csrf\"}" \
  | jq -e '.ok' >/dev/null || say "  logout returned non-ok (possibly already expired)"

say "DONE. Remember: the issued token is still active until its TTL or a"
say "      subsequent rotation invalidates it. To invalidate now, root can"
say "      POST /api/admin/access-controls and clear_internal_test_token=true."
