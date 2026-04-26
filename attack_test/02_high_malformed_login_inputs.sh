#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:5000}"
PROJECT_ROOT="${PROJECT_ROOT:-/home/s92137/html_learning}"
COOKIE_JAR="$(mktemp)"
RESP_FILE="$(mktemp)"
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

call_login() {
  local payload="$1" xff="$2"
  local token
  token="$(fetch_public_csrf)"
  local cmd=(curl -sS -i -o "$RESP_FILE" -b "$COOKIE_JAR" -c "$COOKIE_JAR" -X POST -H "X-CSRF-Token: $token" -H 'Content-Type: application/json')
  if [ -n "$xff" ]; then
    cmd+=( -H "X-Forwarded-For: $xff" )
  fi
  cmd+=( -d "$payload" "$BASE_URL/api/login" )
  "${cmd[@]}" >/dev/null
}

status_code() {
  sed -n 's/^HTTP\/[0-9.]* \([0-9][0-9][0-9]\).*/\1/p' "$RESP_FILE" | head -n 1
}

response_body() {
  tr -d '\r' < "$RESP_FILE" | sed -n '/^{/,$p' | tr '\n' ' '
}

snapshot_fail_log() {
  local file="$PROJECT_ROOT/fail_log.json"
  if [ ! -f "$file" ]; then
    echo "fail_log.json: <not found>"
    return
  fi
  python3 - "$file" <<'PY'
import json,sys
path=sys.argv[1]
try:
    data=json.load(open(path))
except Exception:
    print("fail_log.json: <invalid-json>")
    raise SystemExit
print(f"fail_log entries: {len(data)}")
for k,v in sorted(data.items(), key=lambda x: str(x[0])):
    if isinstance(v, dict):
        c=v.get("count",0)
        print(f"  {k}: {c}")
PY
}

declare -a PAYLOADS=(
  '[1,2,3]'
  '{"username":123,"password":"x"}'
  '{"username":null,"password":"x"}'
  '{"username":["root"],"password":"x"}'
  '"just-a-string"'
  '123'
)

echo "=== 02_high_malformed_login_inputs ==="
echo "Target: $BASE_URL"
echo "Goal: 驗證 malformed login 是否不再造成 unhandled 500，並觀察失敗計數一致性"
echo

echo "[A] snapshot before malformed 測試"
snapshot_fail_log
echo

for payload in "${PAYLOADS[@]}"; do
  call_login "$payload" ""
  code="$(status_code)"
  body="$(response_body)"
  printf '%-55s %-3s %s\n' "payload=${payload:0:40}..." "$code" "$body"
done
echo

echo "[B] 混合 malformed + 合法錯誤密碼測試（可比對 fail_log 變化）"
call_login '{"username":"root","password":"wrong-pass"}' ""
echo "root/wrong status: $(status_code) | $(response_body)"
snapshot_fail_log
echo

echo "Done."
