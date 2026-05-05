#!/usr/bin/env bash
# 02_tester_token_shadow_api.sh
# ---------------------------------------------------------------------------
# 教學：Server Mode v2 tester token 完整生命週期
#
#   tester token 是 "scoped API key"：
#   - 由 root 透過 POST /api/root/tester-token/create 建立（per-tester）
#   - 存進 tester_tokens table（HMAC-signed, expiring, revocable）
#   - 用於呼叫 /api/tester/* 系列 shadow API（GET shadow-state /
#     POST shadow-role / POST shadow-wallet）
#   - 只在 server 處於 `test` 或 `internal_test` mode 時有效
#   - 永遠不能呼叫 root / admin / server-mode / snapshot / integrity / audit API
#
# 流程（root + tester 兩個視角）：
#   ROOT
#     1. 確認 server 已切到 test 或 internal_test mode
#     2. POST /api/root/tester-token/create
#        → 回 issued plaintext token + token_id；server 只存 hash
#     3. 把 token 安全交給 tester（out-of-band）
#   TESTER
#     4. 呼叫 GET /api/tester/shadow-state（讀自己 shadow 資料）
#     5. 呼叫 POST /api/tester/shadow-role（改 shadow role）
#     6. 呼叫 POST /api/tester/shadow-wallet（加減 shadow points）
#     7. 嘗試呼叫 admin / root API 應該被擋（負面測試）
#   ROOT
#     8. POST /api/root/tester-token/revoke 回收 token
#     9. 嘗試再次使用 revoked token 應該失敗
#
# Usage:
#   BASE_URL=https://127.0.0.1:5000 \
#   ROOT_USER=root \
#   ROOT_PW='RootStrongP@ssw0rd' \
#   TESTER_USER_ID=3 \
#     bash 02_tester_token_shadow_api.sh
#
# Notes:
#   - Designed for ISOLATED dev / canary runtime only.
#   - Server must already be in `test` or `internal_test` mode before running.
#   - Token raw value is never echoed; only fingerprint is shown.

set -euo pipefail

BASE_URL="${BASE_URL:-https://127.0.0.1:5000}"
ROOT_USER="${ROOT_USER:-root}"
ROOT_PW="${ROOT_PW:?need ROOT_PW}"
TESTER_USER_ID="${TESTER_USER_ID:?need TESTER_USER_ID (numeric user id of the tester)}"

# NOTE: internal_test mode has browser_only_mode_enabled=true, which blocks
# /api/* requests without a browser-like User-Agent. (test mode does not.)
# Sending a Mozilla-marker UA keeps the script working in both modes.
CURL_OPTS=(-sk --max-time 30 -H "User-Agent: Mozilla/5.0 (X11; Linux) HackmeWebTutorialClient/1.0")

# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

say() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

print_fingerprint() {
  local token="$1"
  local fp
  fp=$(printf '%s' "$token" | sha256sum | awk '{print $1}')
  printf '  fingerprint sha256: %s...%s (length=%d)\n' \
    "${fp:0:8}" "${fp: -4}" "${#token}" >&2
}

get_csrf() {
  local cookie_jar="$1"
  curl "${CURL_OPTS[@]}" -c "$cookie_jar" -b "$cookie_jar" \
    "$BASE_URL/api/csrf-token" \
    | jq -re '.csrf_token'
}

ROOT_JAR=$(mktemp); trap 'rm -f "$ROOT_JAR"' EXIT

# ────────────────────────────────────────────────────────────────────────────
# ROOT side: setup
# ────────────────────────────────────────────────────────────────────────────

say "1) probe + verify server mode is test or internal_test"
ver=$(curl "${CURL_OPTS[@]}" "$BASE_URL/api/version")
mode_no_auth=$(printf '%s' "$ver" | jq -r '.mode // .server_mode // "unknown"')
say "  unauthenticated /api/version reports mode=$mode_no_auth (informational)"

say "2) root login"
csrf=$(get_csrf "$ROOT_JAR")
curl "${CURL_OPTS[@]}" -c "$ROOT_JAR" -b "$ROOT_JAR" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/login" \
  -d "{\"username\":\"$ROOT_USER\",\"password\":\"$ROOT_PW\",\"csrf_token\":\"$csrf\"}" \
  | jq -e '.ok' >/dev/null || fail "root login failed"

say "3) get authoritative server-mode"
mode_resp=$(curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" "$BASE_URL/api/root/server-mode")
# /api/root/server-mode returns: {"ok": true, "mode": {"current_mode": "...", ...}, ...}
current_mode=$(printf '%s' "$mode_resp" | jq -r '.mode.current_mode // .current_mode // "unknown"')
say "  current_mode=$current_mode"
case "$current_mode" in
  test|internal_test) : ;;
  *)
    fail "tester tokens are only valid in 'test' or 'internal_test' mode (current=$current_mode). Switch first."
    ;;
esac

say "4) create a scoped tester token for user_id=$TESTER_USER_ID"
csrf=$(get_csrf "$ROOT_JAR")
# /api/root/tester-token/create expects:
#   tester_user_id, allowed_features, allowed_routes,
#   expires_at (ISO 8601 — NOT ttl_minutes),
#   max_requests_per_minute (NOT rate_per_minute),
#   can_modify_own_role / can_modify_own_points / can_run_security_tests
#
# IMPORTANT: server stores expires_at as naive local time (datetime.now().isoformat())
# and compares it as a STRING. Don't pass a UTC "Z" timestamp — that compares
# 5h before "now" (TW = UTC+8) and the token is treated as already-expired.
# Use local naive ISO instead.
expires_at=$(python3 -c "from datetime import datetime, timedelta; print((datetime.now()+timedelta(minutes=60)).isoformat())")
create_resp=$(curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/root/tester-token/create" \
  -d "$(jq -n --arg c "$csrf" --argjson uid "$TESTER_USER_ID" --arg exp "$expires_at" \
    '{tester_user_id:$uid,
      allowed_features:["server_mode_v2"],
      allowed_routes:["/api/tester/shadow-state","/api/tester/shadow-role","/api/tester/shadow-wallet"],
      expires_at:$exp,
      max_requests_per_minute:30,
      can_modify_own_role:true,
      can_modify_own_points:true,
      can_run_security_tests:false,
      csrf_token:$c}')")
TOKEN=$(printf '%s' "$create_resp" | jq -r '.token // .issued_token // empty')
TOKEN_ID=$(printf '%s' "$create_resp" | jq -r '.token_id // .id // empty')
[ -n "$TOKEN" ] || fail "create did not return token: $create_resp"
[ -n "$TOKEN_ID" ] || fail "create did not return token_id: $create_resp"
say "  token_id=$TOKEN_ID"
print_fingerprint "$TOKEN"

# 5) hand it to the tester out-of-band. For demo, we keep it in shell var.

# ────────────────────────────────────────────────────────────────────────────
# TESTER side: consume
# ────────────────────────────────────────────────────────────────────────────

say "6) tester GET /api/tester/shadow-state (read-only)"
curl "${CURL_OPTS[@]}" \
  -H "X-Tester-Token: $TOKEN" \
  "$BASE_URL/api/tester/shadow-state" \
  | jq '{tester_user_id, shadow_role, shadow_wallet_balance: .shadow_wallet.balance_points, txn_count: (.shadow_transactions | length)}' \
  || fail "shadow-state read failed"

say "7) tester POST /api/tester/shadow-role (set role to manager inside shadow only)"
csrf=$(get_csrf /tmp/_tester_jar.$$)
curl "${CURL_OPTS[@]}" -c /tmp/_tester_jar.$$ -b /tmp/_tester_jar.$$ \
  -H "Content-Type: application/json" \
  -H "X-Tester-Token: $TOKEN" \
  -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/tester/shadow-role" \
  -d "{\"shadow_role\":\"manager\",\"csrf_token\":\"$csrf\"}" \
  | jq '.'
rm -f /tmp/_tester_jar.$$

say "8) tester POST /api/tester/shadow-wallet (credit 100 shadow points)"
# Server expects {"delta_points": <int>, "reason": "..."}.
# Positive = credit, negative = debit. (No "direction"/"amount" fields.)
csrf=$(get_csrf /tmp/_tester_jar.$$)
curl "${CURL_OPTS[@]}" -c /tmp/_tester_jar.$$ -b /tmp/_tester_jar.$$ \
  -H "Content-Type: application/json" \
  -H "X-Tester-Token: $TOKEN" \
  -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/tester/shadow-wallet" \
  -d "{\"delta_points\":100,\"reason\":\"demo top-up\",\"csrf_token\":\"$csrf\"}" \
  | jq '.'
rm -f /tmp/_tester_jar.$$

say "9) re-read shadow-state — should reflect new role + balance"
curl "${CURL_OPTS[@]}" \
  -H "X-Tester-Token: $TOKEN" \
  "$BASE_URL/api/tester/shadow-state" \
  | jq '{shadow_role, balance: .shadow_wallet.balance_points, txn_count: (.shadow_transactions | length)}'

# ────────────────────────────────────────────────────────────────────────────
# Negative tests
# ────────────────────────────────────────────────────────────────────────────

say "10) negative test: tester token must NOT reach admin/root surfaces"
for ep in /api/admin/users /api/root/server-mode /api/admin/audit; do
  http=$(curl "${CURL_OPTS[@]}" -o /dev/null -w '%{http_code}' \
    -H "X-Tester-Token: $TOKEN" \
    "$BASE_URL$ep")
  printf '  %s -> HTTP %s ' "$ep" "$http"
  case "$http" in
    401|403) printf '✓ correctly denied\n' ;;
    *) printf '⚠ unexpected (should be 401/403)\n' ;;
  esac
done

say "11) negative test: tester token must NOT include production wallet writes"
http=$(curl "${CURL_OPTS[@]}" -o /dev/null -w '%{http_code}' \
  -H "X-Tester-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -X POST "$BASE_URL/api/admin/points/adjust" \
  -d "{\"user_id\":1,\"amount\":1000,\"direction\":\"credit\",\"reason\":\"abuse_attempt\"}")
printf '  /api/admin/points/adjust via tester token -> HTTP %s ' "$http"
case "$http" in
  401|403) printf '✓ correctly denied\n' ;;
  *) printf '⚠ unexpected\n' ;;
esac

# ────────────────────────────────────────────────────────────────────────────
# ROOT side: revoke
# ────────────────────────────────────────────────────────────────────────────

say "12) root revokes the tester token"
csrf=$(get_csrf "$ROOT_JAR")
curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $csrf" \
  -X POST "$BASE_URL/api/root/tester-token/revoke" \
  -d "{\"token_id\":\"$TOKEN_ID\",\"reason\":\"demo end\",\"csrf_token\":\"$csrf\"}" \
  | jq '.'

say "13) negative test: revoked token can no longer access /api/tester/*"
http=$(curl "${CURL_OPTS[@]}" -o /dev/null -w '%{http_code}' \
  -H "X-Tester-Token: $TOKEN" \
  "$BASE_URL/api/tester/shadow-state")
printf '  GET /api/tester/shadow-state with revoked token -> HTTP %s ' "$http"
case "$http" in
  401|403) printf '✓ correctly denied\n' ;;
  *) printf '⚠ unexpected (token should be invalid after revoke)\n' ;;
esac

say "14) root lists tokens (token raw value is NEVER returned again, only metadata)"
# NOTE: 'label' is a reserved word in jq (used by `label $foo | ...`). The
# object shorthand `{label}` therefore fails to parse — quote it explicitly.
curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" \
  "$BASE_URL/api/root/tester-token/list" \
  | jq '[.tokens[] | {token_id, tester_user_id, "label": .label, status, expires_at, last_used_at}]' \
  | head -40

say "DONE. Key takeaways:"
say "  • tester token 是 scoped API key，不是 'login 替代品'。"
say "  • 只能呼叫 /api/tester/* 上的 shadow APIs。"
say "  • 改變的 role / wallet / transaction 都進 test_shadow_* 表，"
say "    不會動到 production users / points_wallets / points_ledger。"
say "  • token 的 raw value 由 root create 時取一次；之後只存 hash + metadata。"
say "  • 任何不正確 scope / 過期 / revoked token 行為都應該以 401/403 結束，"
say "    不應該讓 server 嘗試 'fall back' 到任何替代授權路徑。"
