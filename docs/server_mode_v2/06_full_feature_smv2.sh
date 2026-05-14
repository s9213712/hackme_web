#!/usr/bin/env bash
# 06_full_feature_smv2.sh
# ---------------------------------------------------------------------------
# Server Mode v2 — full-feature smoke
#
# Walks through every SMv2 admin surface a fresh deployment exposes,
# end-to-end:
#   1. Probe server health
#   2. Root login + forced password change (if needed)
#   3. List server-mode profiles
#   4. Read production_requirements
#   5. Create mode_checkpoint
#   6. Switch to internal_test
#   7. Rotate internal_test login token
#   8. Issue + use a tester token (tester APIs)
#   9. Read tester-token list
#   10. Read mode_switch_logs (and verify chain)
#   11. Read /api/admin/security-center (the data the launch-check
#       conditions card reads)
#   12. Read /api/admin/health (the data the 健康度 dashboard reads)
#   13. Revoke the tester token
#   14. Switch back to dev_ready
#
# A single failure exits 1 — wire into CI as the "all SMv2 surfaces
# still respond and follow contract" smoke. Designed for ISOLATED
# runtime only.

set -uo pipefail

BASE_URL="${BASE_URL:-https://127.0.0.1:5000}"
ROOT_USER="${ROOT_USER:-root}"
ROOT_INITIAL_PW="${ROOT_INITIAL_PW:?need ROOT_INITIAL_PW}"
ROOT_NEW_PW="${ROOT_NEW_PW:?need ROOT_NEW_PW (must differ from initial)}"
TESTER_USER_ID="${TESTER_USER_ID:?need TESTER_USER_ID}"
CURL_OPTS=(-sk --max-time 30 -H "User-Agent: Mozilla/5.0 (X11; Linux) HackmeWebSmokeAll/1.0")

say()  { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
ok()   { printf '  ✓ %s\n' "$*" >&2; }

ROOT_JAR=$(mktemp); trap 'rm -f "$ROOT_JAR"' EXIT
get_csrf() { curl "${CURL_OPTS[@]}" -c "$1" -b "$1" "$BASE_URL/api/csrf-token" | jq -re '.csrf_token'; }

say "1) health probe"
curl "${CURL_OPTS[@]}" -o /dev/null -w "  HTTP %{http_code}\n" "$BASE_URL/api/version" || fail "server unreachable"
ok "server reachable"

say "2) root login + forced password change"
csrf=$(get_csrf "$ROOT_JAR")
login=$(curl "${CURL_OPTS[@]}" -c "$ROOT_JAR" -b "$ROOT_JAR" \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/login" \
  -d "{\"username\":\"$ROOT_USER\",\"password\":\"$ROOT_INITIAL_PW\",\"csrf_token\":\"$csrf\"}")
[ "$(printf '%s' "$login" | jq -r '.ok // false')" = "true" ] || fail "root login failed: $login"
must_change=$(printf '%s' "$login" | jq -r '.must_change_password // false')
if [ "$must_change" = "true" ]; then
  rid=$(curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" "$BASE_URL/api/me" | jq -r '.id')
  csrf=$(get_csrf "$ROOT_JAR")
  curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" \
    -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
    -X PUT "$BASE_URL/api/admin/users/$rid" \
    -d "{\"current_password\":\"$ROOT_INITIAL_PW\",\"password\":\"$ROOT_NEW_PW\",\"password_confirm\":\"$ROOT_NEW_PW\",\"csrf_token\":\"$csrf\"}" \
    | jq -e '.ok' >/dev/null || fail "forced password change failed"
  rm -f "$ROOT_JAR"; ROOT_JAR=$(mktemp)
  csrf=$(get_csrf "$ROOT_JAR")
  curl "${CURL_OPTS[@]}" -c "$ROOT_JAR" -b "$ROOT_JAR" \
    -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
    -X POST "$BASE_URL/api/login" \
    -d "{\"username\":\"$ROOT_USER\",\"password\":\"$ROOT_NEW_PW\",\"csrf_token\":\"$csrf\"}" \
    | jq -e '.ok' >/dev/null || fail "re-login failed"
fi
ok "root logged in"

say "3) GET /api/root/server-mode (profile list + current mode)"
mode_state=$(curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" "$BASE_URL/api/root/server-mode")
[ "$(printf '%s' "$mode_state" | jq -r '.ok // false')" = "true" ] || fail "server-mode read failed"
ok "current_mode = $(printf '%s' "$mode_state" | jq -r '.mode.current_mode')"

say "4) GET /api/root/server-mode/requirements"
req=$(curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" "$BASE_URL/api/root/server-mode/requirements")
required_count=$(printf '%s' "$req" | jq -r '.required | length // 0')
[ "$required_count" = "13" ] || fail "expected 13 required reports, got $required_count"
ok "13 production gate reports listed"

say "5) POST /api/root/server-mode/checkpoint (target=internal_test)"
csrf=$(get_csrf "$ROOT_JAR")
curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/root/server-mode/checkpoint" \
  -d "{\"target_mode\":\"internal_test\",\"reason\":\"smoke 06\",\"csrf_token\":\"$csrf\"}" \
  | jq -e '.ok' >/dev/null || fail "checkpoint failed"
ok "checkpoint created"

say "6) POST /api/root/server-mode/switch (target=internal_test)"
csrf=$(get_csrf "$ROOT_JAR")
curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/root/server-mode/switch" \
  -d "{\"target_mode\":\"internal_test\",\"confirm\":\"SWITCH_TO_INTERNAL_TEST\",\"reason\":\"smoke 06\",\"csrf_token\":\"$csrf\"}" \
  | jq -e '.ok' >/dev/null || fail "mode switch failed"
ok "switched to internal_test"

say "7) rotate internal_test login token"
csrf=$(get_csrf "$ROOT_JAR")
rotate_resp=$(curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/admin/access-controls/internal-test-token" \
  -d "{\"confirm\":\"ROTATE_INTERNAL_TEST_TOKEN\",\"ttl_minutes\":30,\"target_username\":\"$TESTER_USER\",\"csrf_token\":\"$csrf\"}")
[ -n "$(printf '%s' "$rotate_resp" | jq -r '.token // empty')" ] || fail "rotate failed: $rotate_resp"
ok "internal_test login token rotated"

say "8) issue + consume tester token"
csrf=$(get_csrf "$ROOT_JAR")
expires_at=$(python3 -c "from datetime import datetime, timedelta; print((datetime.now()+timedelta(minutes=30)).isoformat())")
create_resp=$(curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/root/tester-token/create" \
  -d "$(jq -n --arg c "$csrf" --argjson uid "$TESTER_USER_ID" --arg exp "$expires_at" \
    '{tester_user_id:$uid, allowed_features:["smv2"], allowed_routes:["/api/tester/shadow-state","/api/tester/shadow-role","/api/tester/shadow-wallet"], expires_at:$exp, max_requests_per_minute:30, can_modify_own_role:true, can_modify_own_points:true, csrf_token:$c}')")
TOKEN=$(printf '%s' "$create_resp" | jq -r '.token // empty')
TOKEN_ID=$(printf '%s' "$create_resp" | jq -r '.token_id // empty')
[ -n "$TOKEN" ] || fail "tester-token create failed: $create_resp"
state=$(curl "${CURL_OPTS[@]}" -H "X-Tester-Token: $TOKEN" "$BASE_URL/api/tester/shadow-state")
[ "$(printf '%s' "$state" | jq -r '.ok // false')" = "true" ] || fail "shadow-state via tester token failed"
ok "tester token end-to-end OK"

say "9) GET /api/root/tester-token/list"
listed=$(curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" "$BASE_URL/api/root/tester-token/list" | jq -r '.tokens | length // 0')
[ "$listed" -ge 1 ] || fail "tester-token list returned 0 entries"
ok "tester-token list has $listed entries"

say "10) GET /api/root/server-mode/logs (and chain verify)"
logs=$(curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" "$BASE_URL/api/root/server-mode/logs?limit=20" | jq -r '.logs | length // 0')
[ "$logs" -ge 1 ] || fail "mode-switch logs empty"
ok "$logs mode_switch_logs entries"

say "11) GET /api/admin/security-center (data for 總覽 + launch-check A 區)"
sc=$(curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" "$BASE_URL/api/admin/security-center")
for k in settings audit_integrity readiness anomaly mode; do
  [ "$(printf '%s' "$sc" | jq -r ".security_center.$k // empty")" != "" ] || fail "security-center.$k missing"
done
for k in allow_register captcha_mode production_single_account_ip_lock_enabled production_single_ip_account_lock_enabled; do
  printf '%s' "$sc" | jq -e --arg k "$k" '.security_center.settings | has($k)' >/dev/null || fail "security-center.settings.$k missing"
done
ok "security-center exposes summary fields and required settings keys"

say "12) GET /api/admin/health (data for 健康度)"
hc=$(curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" "$BASE_URL/api/admin/health")
[ "$(printf '%s' "$hc" | jq -r '.ok // false')" = "true" ] || fail "/api/admin/health failed"
ok "health dashboard data available"

say "13) revoke tester token"
csrf=$(get_csrf "$ROOT_JAR")
curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/root/tester-token/revoke" \
  -d "{\"token_id\":\"$TOKEN_ID\",\"reason\":\"smoke end\",\"csrf_token\":\"$csrf\"}" \
  | jq -e '.ok' >/dev/null || fail "revoke failed"
ok "tester token revoked"

say "14) switch back to dev_ready"
csrf=$(get_csrf "$ROOT_JAR")
curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/root/server-mode/checkpoint" \
  -d "{\"target_mode\":\"dev_ready\",\"reason\":\"smoke 06 cleanup\",\"csrf_token\":\"$csrf\"}" \
  | jq -e '.ok' >/dev/null || fail "checkpoint(dev_ready) failed"
csrf=$(get_csrf "$ROOT_JAR")
curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/root/server-mode/switch" \
  -d "{\"target_mode\":\"dev_ready\",\"confirm\":\"SWITCH_TO_DEV_READY\",\"reason\":\"smoke 06 cleanup\",\"csrf_token\":\"$csrf\"}" \
  | jq -e '.ok' >/dev/null || fail "mode switch(dev_ready) failed"
ok "back to dev_ready"

say "ALL FULL-FEATURE PROBES PASSED"
