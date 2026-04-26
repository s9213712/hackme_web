#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:5000}"
ROOT_USERNAME="${ROOT_USERNAME:-root}"
ROOT_PASSWORD="${ROOT_PASSWORD:-root}"

COOKIE_JAR="$(mktemp)"
RESP_FILE="$(mktemp)"
STAMP="$(date +%s)"
cleanup() {
  rm -f "$COOKIE_JAR" "$RESP_FILE"
}
trap cleanup EXIT

fetch_public_csrf() {
  local tmp
  tmp="$(mktemp)"
  curl -sS -i -o "$tmp" -c "$COOKIE_JAR" -b "$COOKIE_JAR" "$BASE_URL/" >/dev/null
  local tok
  tok="$(sed -n 's/^Set-Cookie: csrf_token=\([^;]*\).*/\1/pI' "$tmp" | tr -d '\r' | head -n 1)"
  rm -f "$tmp"
  if [ -z "$tok" ]; then
    echo "fetch csrf failed" >&2
    return 1
  fi
  printf '%s\n' "$tok"
}

call_api() {
  local method="$1" path="$2" body="$3" xff="$4" token="$5"
  local cmd=(curl -sS -i -o "$RESP_FILE" -b "$COOKIE_JAR" -c "$COOKIE_JAR" -X "$method")
  if [ -n "$token" ]; then
    cmd+=( -H "X-CSRF-Token: $token" )
  fi
  if [ -n "$xff" ]; then
    cmd+=( -H "X-Forwarded-For: $xff" )
  fi
  if [ "$body" != "-" ]; then
    cmd+=( -H 'Content-Type: application/json' -d "$body" )
  fi
  cmd+=( "$BASE_URL$path" )
  "${cmd[@]}"
}

status_code() {
  sed -n 's/^HTTP\/[0-9.]* \([0-9][0-9][0-9]\).*/\1/p' "$RESP_FILE" | head -n 1
}

response_body() {
  tr -d '\r' < "$RESP_FILE" | sed -n '/^{/,$p' | tr '\n' ' '
}

login_attempt() {
  local xff="$1" password="$2" title="$3"
  local token body
  token="$(fetch_public_csrf)"
  body="{\"username\":\"${ROOT_USERNAME}\",\"password\":\"${password}\",\"csrf_token\":\"${token}\"}"
  call_api "POST" "/api/login" "$body" "$xff" "$token" >/dev/null
  local code
  code="$(status_code)"
  local body_text
  body_text="$(response_body)"
  printf '%-70s %-3s %s\n' "$title" "$code" "$body_text"
}

register_attempt() {
  local seq="$1" xff="$2"
  local token uname body
  token="$(fetch_public_csrf)"
  uname="xffreg_${STAMP}_${seq}"
  body="{\"username\":\"${uname}\",\"password\":\"Test@1234!A\",\"password_confirm\":\"Test@1234!A\",\"nickname\":\"atk\",\"real_name\":\"attack\",\"id_number\":\"ABCD${seq}\",\"birthdate\":\"1990-01-01\",\"phone\":\"0912345678\",\"csrf_token\":\"${token}\"}"
  call_api "POST" "/api/register" "$body" "$xff" "$token" >/dev/null
  local code
  code="$(status_code)"
  local body_text
  body_text="$(response_body)"
  printf '%-70s %-3s %s\n' "register[$seq] xff=$xff" "$code" "$body_text"
}

echo "=== 01_critical_xff_auth_lock_bypass_check ==="
echo "Target: $BASE_URL"
echo "Goal: 驗證 X-Forwarded-For 不應能稀釋登入/註冊封鎖"
echo

echo "[1] 嘗試對同一 XFF 觸發登入錯誤封鎖"
login_attempt "203.0.113.10" "wrong-pass-1" "login wrong-1 (XFF=203.0.113.10)"
login_attempt "203.0.113.10" "wrong-pass-2" "login wrong-2 (XFF=203.0.113.10)"
login_attempt "203.0.113.10" "wrong-pass-3" "login wrong-3 (XFF=203.0.113.10)"
echo

echo "[2] 驗證是否可換另一個 XFF 直接以正確密碼繞過封鎖"
login_attempt "198.51.100.10" "${ROOT_PASSWORD}" "login with correct pw on different XFF"
echo

echo "[3] 註冊率限制邊界測試（應該不受 XFF 分片繞過）"
for i in $(seq 1 11); do
  register_attempt "$i" "192.0.2.10"
done
for i in $(seq 12 14); do
  register_attempt "$i" "192.0.2.$(expr 10 + $i)"
done

echo
echo "Done."
