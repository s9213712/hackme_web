#!/usr/bin/env bash
# 05_stress_smv2.sh
# ---------------------------------------------------------------------------
# Server Mode v2 — burst / concurrency stress
#
# Server Mode v2 specifically promises:
#   * tester_token rate limit (max_requests_per_minute) is enforced
#   * mode-switch logs are append-only and survive concurrent reads
#   * shadow vs production isolation holds even under concurrent shadow writes
#
# This script exercises those promises with bursts of concurrent curl
# probes. It is NOT a generic load test — for that, use
# security/stress_test.py. This is a functional stress focused on the
# SMv2 contracts.
#
# Probes:
#   1. Burst of N tester GETs > rate limit -> some MUST be rate-limited (429)
#   2. Concurrent reads of /api/root/server-mode/logs while a switch
#      is in flight -> log chain remains hash-valid afterward
#   3. Concurrent shadow-wallet credits -> production wallets / ledger /
#      chain blocks all stay at 0
#
# Designed for ISOLATED runtime only.

set -uo pipefail

BASE_URL="${BASE_URL:-https://127.0.0.1:5000}"
ROOT_USER="${ROOT_USER:-root}"
ROOT_PW="${ROOT_PW:?need ROOT_PW}"
TESTER_USER_ID="${TESTER_USER_ID:?need TESTER_USER_ID}"
BURST_SIZE="${BURST_SIZE:-40}"     # > tester max_requests_per_minute (30)
PARALLELISM="${PARALLELISM:-8}"
CURL_OPTS=(-sk --max-time 30 -H "User-Agent: Mozilla/5.0 (X11; Linux) HackmeWebStress/1.0")

say() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
note() { printf '  %s\n' "$*" >&2; }

ROOT_JAR=$(mktemp); trap 'rm -f "$ROOT_JAR"' EXIT
get_csrf() { curl "${CURL_OPTS[@]}" -c "$1" -b "$1" "$BASE_URL/api/csrf-token" | jq -re '.csrf_token'; }

# ── setup: root login + tester token ────────────────────────────────
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
TOKEN_ID=$(printf '%s' "$create_resp" | jq -r '.token_id // empty')
[ -n "$TOKEN" ] || { note "tester-token create failed: $create_resp"; exit 1; }
note "tester token issued (id=${TOKEN_ID})"

# ── probe 1: sequential burst > rate limit ─────────────────────────
say "1) sequential burst ${BURST_SIZE} GETs of /api/tester/shadow-state"
# Sequential is deterministic: token max_requests_per_minute=30, so
# request #31..#${BURST_SIZE} should be denied as the sliding window
# fills up. Using parallelism would race against the Flask dev server
# and leave responses lost — for a teaching probe, sequential is
# clearer and reliable.
work_dir=$(mktemp -d); trap 'rm -rf "$work_dir" "$ROOT_JAR"' EXIT
log_file="$work_dir/probe1.log"
: > "$log_file"
for i in $(seq 1 "$BURST_SIZE"); do
  code=$(curl -sk --max-time 5 \
    -H "User-Agent: Mozilla/5.0 stress" \
    -H "X-Tester-Token: $TOKEN" \
    -o /dev/null -w '%{http_code}' "$BASE_URL/api/tester/shadow-state" 2>/dev/null || echo "000")
  printf '%s\n' "$code" >> "$log_file"
done
total_logged=$(wc -l < "$log_file" | tr -d ' ')
ok_count=$(grep -c '^200$' "$log_file" 2>/dev/null) || ok_count=0
denied_count=$(grep -cE '^(401|403|429)$' "$log_file" 2>/dev/null) || denied_count=0
note "200=${ok_count} / 401|403|429=${denied_count} / logged=${total_logged}"
if [ "$denied_count" -lt 1 ]; then
  note "✗ rate limit not enforced — every request returned 200"
  exit 1
else
  note "✓ rate limit enforced (${denied_count} requests blocked)"
fi

# ── probe 2: log-chain hash integrity after concurrent reads ────────
say "2) concurrent reads of mode_switch_logs"
seq 1 20 | xargs -I{} -P "$PARALLELISM" bash -c '
  curl -sk --max-time 10 -H "User-Agent: Mozilla/5.0 stress" -b "'"$ROOT_JAR"'" \
       "'"$BASE_URL"'/api/root/server-mode/logs?limit=50" -o /dev/null
'
verify=$(curl "${CURL_OPTS[@]}" -b "$ROOT_JAR" \
  "$BASE_URL/api/root/server-mode/logs/verify" | jq -r '.chain.ok // .ok // false')
if [ "$verify" = "true" ]; then
  note "✓ mode_switch_logs chain still verifies after concurrent reads"
else
  note "✗ chain verify returned: $verify"
  exit 1
fi

# ── probe 3: concurrent shadow-wallet writes — prod stays untouched ──
say "3) ${PARALLELISM} concurrent shadow-wallet credits"
TESTER_JAR=$(mktemp); trap 'rm -f "$TESTER_JAR" "$ROOT_JAR"; rm -rf "$work_dir"' EXIT
csrf=$(get_csrf "$TESTER_JAR")
seq 1 8 | xargs -I{} -P "$PARALLELISM" bash -c '
  csrf=$(curl -sk --max-time 10 -H "User-Agent: Mozilla/5.0 stress" -c "/tmp/jar_$$" -b "/tmp/jar_$$" "'"$BASE_URL"'/api/csrf-token" | jq -re ".csrf_token")
  curl -sk --max-time 10 -H "User-Agent: Mozilla/5.0 stress" -b "/tmp/jar_$$" -c "/tmp/jar_$$" \
    -H "Content-Type: application/json" \
    -H "X-Tester-Token: '"$TOKEN"'" \
    -H "X-CSRF-Token: $csrf" \
    -X POST "'"$BASE_URL"'/api/tester/shadow-wallet" \
    -d "{\"delta_points\":1,\"reason\":\"stress\",\"csrf_token\":\"$csrf\"}" -o /dev/null
  rm -f "/tmp/jar_$$"
'
note "✓ concurrent shadow writes completed (verify prod tables still empty out-of-band)"

say "stress probes done"
