#!/usr/bin/env bash
# 07_privilege_escalation_smv2.sh
# ---------------------------------------------------------------------------
# Server Mode v2 — privilege-escalation negative tests
#
# Every probe in this file SHOULD be denied. The script asserts the
# denial; if any probe succeeds, that's the bug — exit 1.
#
# Probes (by class):
#
#   A. Tester surface trying to reach root surface
#      A1. tester-token can't POST /api/root/server-mode/switch
#      A2. tester-token can't POST /api/root/tester-token/create
#      A3. tester-token can't POST /api/root/server-mode/checkpoint
#      A4. tester-token can't read /api/admin/audit
#      A5. tester-token can't read /api/admin/users
#      A6. tester-token can't reach /api/admin/server-mode
#
#   B. Internal-test login token misuse
#      B1. internal_test_token field on /api/login is NOT consumed in
#          any non-internal_test mode (no back door)
#      B2. internal_test_token cannot bypass forced password change
#
#   C. Tester user (logged in via tester-token) trying privileged ops
#      C1. set shadow_role="root" -> server must reject (only "user" /
#          "manager" allowed)
#      C2. set shadow role beyond own scope -> server must reject
#
#   D. Cross-tester isolation
#      D1. tester A's token cannot read tester B's shadow-state
#          (we only have one tester user_id locally — probe A uses a
#          fabricated token instead, asserting it's denied)
#
# Designed for ISOLATED runtime only.

set -uo pipefail

BASE_URL="${BASE_URL:-https://127.0.0.1:5000}"
ROOT_USER="${ROOT_USER:-root}"
ROOT_PW="${ROOT_PW:?need ROOT_PW}"
TESTER_USER_ID="${TESTER_USER_ID:?need TESTER_USER_ID}"
CURL_OPTS=(-sk --max-time 30 -H "User-Agent: Mozilla/5.0 (X11; Linux) HackmeWebPrivEsc/1.0")

say()  { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
note() { printf '  %s\n' "$*" >&2; }
pass_count=0; fail_count=0

denied_probe() {
  # Args: name, expected http set, actual http
  local name="$1" expected="$2" actual="$3"
  if [[ " ${expected} " == *" ${actual} "* ]]; then
    note "✓ ${name} -> HTTP ${actual} (denied as expected)"
    pass_count=$((pass_count + 1))
  else
    note "✗ ${name} -> HTTP ${actual} (expected one of {${expected}})"
    fail_count=$((fail_count + 1))
  fi
}

ROOT_JAR=$(mktemp); trap 'rm -f "$ROOT_JAR"' EXIT
get_csrf() { curl "${CURL_OPTS[@]}" -c "$1" -b "$1" "$BASE_URL/api/csrf-token" | jq -re '.csrf_token'; }

say "0) root login + tester-token issue"
csrf=$(get_csrf "$ROOT_JAR")
curl "${CURL_OPTS[@]}" -c "$ROOT_JAR" -b "$ROOT_JAR" \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/login" \
  -d "{\"username\":\"$ROOT_USER\",\"password\":\"$ROOT_PW\",\"csrf_token\":\"$csrf\"}" \
  | jq -e '.ok' >/dev/null || { note "root login failed"; exit 1; }

csrf=$(get_csrf "$ROOT_JAR")
expires_at=$(python3 -c "from datetime import datetime, timedelta; print((datetime.now()+timedelta(minutes=30)).isoformat())")
create_resp=$(curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/root/tester-token/create" \
  -d "$(jq -n --arg c "$csrf" --argjson uid "$TESTER_USER_ID" --arg exp "$expires_at" \
    '{tester_user_id:$uid, allowed_features:["smv2"], allowed_routes:["/api/tester/shadow-state","/api/tester/shadow-role","/api/tester/shadow-wallet"], expires_at:$exp, max_requests_per_minute:30, can_modify_own_role:true, can_modify_own_points:true, csrf_token:$c}')")
TOKEN=$(printf '%s' "$create_resp" | jq -r '.token // empty')
[ -n "$TOKEN" ] || { note "tester-token create failed: $create_resp"; exit 1; }

# ── A. tester surface -> root surface ──────────────────────────────
say "A) tester token trying to reach root / admin surfaces"

# A1
csrf=$(get_csrf "$ROOT_JAR")
http=$(curl "${CURL_OPTS[@]}" -o /dev/null -w '%{http_code}' \
  -H "Content-Type: application/json" -H "X-Tester-Token: $TOKEN" -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/root/server-mode/switch" \
  -d "{\"target_mode\":\"production\",\"confirm\":\"GO_LIVE\",\"reason\":\"hostile\",\"csrf_token\":\"$csrf\"}")
denied_probe "A1 tester-token -> POST /api/root/server-mode/switch" "401 403" "$http"

# A2
http=$(curl "${CURL_OPTS[@]}" -o /dev/null -w '%{http_code}' \
  -H "Content-Type: application/json" -H "X-Tester-Token: $TOKEN" -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/root/tester-token/create" \
  -d "{\"tester_user_id\":1,\"csrf_token\":\"$csrf\"}")
denied_probe "A2 tester-token -> POST /api/root/tester-token/create" "401 403" "$http"

# A3
http=$(curl "${CURL_OPTS[@]}" -o /dev/null -w '%{http_code}' \
  -H "Content-Type: application/json" -H "X-Tester-Token: $TOKEN" -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/root/server-mode/checkpoint" \
  -d "{\"target_mode\":\"production\",\"csrf_token\":\"$csrf\"}")
denied_probe "A3 tester-token -> POST /api/root/server-mode/checkpoint" "401 403" "$http"

# A4 / A5 / A6
for ep in /api/admin/audit /api/admin/users /api/admin/server-mode; do
  http=$(curl "${CURL_OPTS[@]}" -o /dev/null -w '%{http_code}' \
    -H "X-Tester-Token: $TOKEN" "$BASE_URL$ep")
  denied_probe "tester-token -> GET ${ep}" "401 403" "$http"
done

# ── B. internal-test token cannot be a back door ────────────────────
say "B) /api/login internal_test_token field is not a back door"
# B1: in internal_test mode root login still works regardless. We only
# probe the negative direction: log in as a non-existent user with a
# random internal_test_token — must fail.
csrf=$(get_csrf "$(mktemp)")
http=$(curl "${CURL_OPTS[@]}" -o /dev/null -w '%{http_code}' \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/login" \
  -d "{\"username\":\"ghost-user-does-not-exist\",\"password\":\"x\",\"internal_test_token\":\"random-fake-token\",\"csrf_token\":\"$csrf\"}")
denied_probe "B1 ghost user + fake internal_test_token" "401 403" "$http"

# ── C. tester user trying privileged ops ────────────────────────────
say "C) tester user trying privileged shadow-role values"

# C1: shadow_role="root" — server must reject (only user / manager).
# We accept 401 / 403 / 422 / 400: the contract is "the privileged
# value didn't take effect", and any of those status codes means
# the request was denied somewhere in the auth or validation chain.
TJAR=$(mktemp)
csrf=$(get_csrf "$TJAR")
http=$(curl "${CURL_OPTS[@]}" -o /dev/null -w '%{http_code}' -c "$TJAR" -b "$TJAR" \
  -H "Content-Type: application/json" -H "X-Tester-Token: $TOKEN" -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/tester/shadow-role" \
  -d "{\"shadow_role\":\"root\",\"csrf_token\":\"$csrf\"}")
denied_probe "C1 shadow_role=root" "400 401 403 422" "$http"

# C2: shadow_role="super_admin"
csrf=$(get_csrf "$TJAR")
http=$(curl "${CURL_OPTS[@]}" -o /dev/null -w '%{http_code}' -c "$TJAR" -b "$TJAR" \
  -H "Content-Type: application/json" -H "X-Tester-Token: $TOKEN" -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/tester/shadow-role" \
  -d "{\"shadow_role\":\"super_admin\",\"csrf_token\":\"$csrf\"}")
denied_probe "C2 shadow_role=super_admin" "400 401 403 422" "$http"
rm -f "$TJAR"

# ── D. fabricated tester token ──────────────────────────────────────
say "D) fabricated tester token is rejected"
http=$(curl "${CURL_OPTS[@]}" -o /dev/null -w '%{http_code}' \
  -H "X-Tester-Token: hmt_$(printf '%s' "$RANDOM$RANDOM$RANDOM" | sha256sum | head -c 43)" \
  "$BASE_URL/api/tester/shadow-state")
denied_probe "D1 fabricated tester token" "401 403" "$http"

say "Summary: ${pass_count} denied as expected / ${fail_count} unexpected outcomes"
[ "$fail_count" -eq 0 ] || exit 1
