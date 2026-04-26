#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:5000}"

TMP_DIR="$(mktemp -d)"
RESP="$TMP_DIR/resp.json"
JAR_PUBLIC="$TMP_DIR/public.jar"
JAR_A="$TMP_DIR/user_a.jar"
JAR_B="$TMP_DIR/user_b.jar"
trap 'rm -rf "$TMP_DIR"' EXIT

now_ms() {
  date +%s%3N
}

status_code() {
  sed -n '1s/HTTP\/1\.[01] \([0-9][0-9][0-9]\).*/\1/p' "$RESP" | head -n1
}

extract_json_field() {
  local key="$1"
  python3 - "$RESP" "$key" <<'PY'
import json
import pathlib
import sys

path = sys.argv[1]
key = sys.argv[2]
text = pathlib.Path(path).read_text(errors="ignore")
start = text.find("\n{")
if start == -1:
    start = text.find("{")
body = text[start:] if start != -1 else text

try:
    payload = json.loads(body)
except Exception:
    print("")
    raise SystemExit

cur = payload
for part in key.split("."):
    if not isinstance(cur, dict) or part not in cur:
        print("")
        raise SystemExit
    cur = cur.get(part, "")

if cur is None:
    print("")
else:
    print(cur)
PY
}

fetch_home_csrf() {
  local jar="$1"
  local code
  code=$(curl -sS -i -o "$RESP" -c "$jar" -w "%{http_code}" "$BASE_URL/")
  if [ "$code" -ne 200 ]; then
    echo "[home] HTTP $code"
    return 1
  fi
  CSRF_TOKEN="$(awk '/^(127\.0\.0\.1|localhost|::1)/ {print $7; exit}' "$jar")"
  if [ -z "$CSRF_TOKEN" ]; then
    echo "[home] 無法取得 CSRF token"
    return 1
  fi
}

fetch_auth_csrf() {
  local jar="$1"
  local code
  code=$(curl -sS -i -o "$RESP" -w "%{http_code}" -b "$jar" -c "$jar" "$BASE_URL/api/csrf-token")
  if [ "$code" -ne 200 ]; then
    echo "[csrf] HTTP $code"
    return 1
  fi
  CSRF_TOKEN="$(extract_json_field csrf_token)"
  if [ -z "$CSRF_TOKEN" ]; then
    echo "[csrf] 無法解析 csrf token"
    return 1
  fi
}

call_api() {
  local method="$1" path="$2" body="$3" token="$4" jar="$5"
  local code
  if [ -z "$token" ]; then
    if [ "$body" != "-" ]; then
      code=$(curl -sS -i -o "$RESP" -b "$jar" -c "$jar" -H 'Content-Type: application/json' -d "$body" -w "%{http_code}" -X "$method" "$BASE_URL$path")
    else
      code=$(curl -sS -i -o "$RESP" -b "$jar" -c "$jar" -w "%{http_code}" -X "$method" "$BASE_URL$path")
    fi
  elif [ "$body" != "-" ]; then
    code=$(curl -sS -i -o "$RESP" -b "$jar" -c "$jar" -H "X-CSRF-Token: $token" -H 'Content-Type: application/json' -d "$body" -w "%{http_code}" -X "$method" "$BASE_URL$path")
  else
    code=$(curl -sS -i -o "$RESP" -b "$jar" -c "$jar" -H "X-CSRF-Token: $token" -w "%{http_code}" -X "$method" "$BASE_URL$path")
  fi
  echo "$code"
}

print_case() {
  local title="$1" expect="$2" got="$3" detail="$4"
  local status="FAIL"
  if [ "$expect" = "$got" ]; then
    status="PASS"
  fi
  printf '%-80s %-6s (status=%s) %s\n' "$title" "$status" "$got" "$detail"
}

run_case() {
  local title="$1" expect="$2" method="$3" path="$4" body="$5" token="$6" jar="$7"
  local code
  code=$(call_api "$method" "$path" "$body" "$token" "$jar")
  print_case "$title" "$expect" "$code" "$path"
}

register_user() {
  local user="$1" pw="$2" jar="$3"
  local body code phone

  fetch_home_csrf "$jar"
  phone="$(printf '09%08d' "$((RANDOM % 100000000))")"
  body="{\"username\":\"$user\",\"password\":\"$pw\",\"password_confirm\":\"$pw\",\"nickname\":\"$user\",\"real_name\":\"$user\",\"id_number\":\"A12345$user\",\"birthdate\":\"1990-01-01\",\"phone\":\"$phone\",\"csrf_token\":\"$CSRF_TOKEN\"}"
  code=$(call_api POST /api/register "$body" "$CSRF_TOKEN" "$jar")
  echo "$code"
}

login_user() {
  local user="$1" pw="$2" jar="$3" code body
  fetch_home_csrf "$jar"
  body="{\"username\":\"$user\",\"password\":\"$pw\",\"csrf_token\":\"$CSRF_TOKEN\"}"
  code=$(call_api POST /api/login "$body" "$CSRF_TOKEN" "$jar")
  echo "$code"
}

echo "=== 對話服務安全回歸 ==="

USER_A="chat_a_$(now_ms)"
USER_B="chat_b_$(now_ms)"
PASS="Passw0rd!A"

code="$(register_user "$USER_A" "$PASS" "$JAR_PUBLIC")"
print_case "註冊使用者 A" 200 "$code" "$USER_A"

code="$(register_user "$USER_B" "$PASS" "$JAR_PUBLIC")"
print_case "註冊使用者 B" 200 "$code" "$USER_B"

code=$(login_user "$USER_A" "$PASS" "$JAR_A")
print_case "A 登入" 200 "$code" "$USER_A"
fetch_auth_csrf "$JAR_A"
USER_A_CSRF="$CSRF_TOKEN"

ROOM_NAME="room_$(now_ms)"
code=$(call_api POST /api/chat/rooms "{\"name\":\"$ROOM_NAME\"}" "$USER_A_CSRF" "$JAR_A")
print_case "A 建立聊天室" 200 "$code" "$ROOM_NAME"
ROOM_ID="$(extract_json_field 'room.id')"

if [ -z "$ROOM_ID" ]; then
  echo "聊天室建立失敗，終止"
  exit 1
fi

run_case "A 取聊天室清單（含新聊天室）" 200 GET /api/chat/rooms - "$USER_A_CSRF" "$JAR_A"

code=$(login_user "$USER_B" "$PASS" "$JAR_B")
print_case "B 登入" 200 "$code" "$USER_B"
fetch_auth_csrf "$JAR_B"
USER_B_CSRF="$CSRF_TOKEN"

run_case "B 非成員讀取聊天室訊息" 403 GET "/api/chat/rooms/$ROOM_ID/messages" - "$USER_B_CSRF" "$JAR_B"
run_case "B 加入聊天室" 200 POST "/api/chat/rooms/$ROOM_ID/join" "{}" "$USER_B_CSRF" "$JAR_B"

fetch_auth_csrf "$JAR_A"
USER_A_CSRF="$CSRF_TOKEN"
call_api POST "/api/chat/rooms/$ROOM_ID/messages" "{\"content\":\"Hello\"}" "$USER_A_CSRF" "$JAR_A" >/dev/null
call_api POST "/api/chat/rooms/$ROOM_ID/messages" "{\"content\":\"hello again\"}" "$USER_B_CSRF" "$JAR_B" >/dev/null

fetch_auth_csrf "$JAR_A"
USER_A_CSRF="$CSRF_TOKEN"
code=$(call_api POST "/api/chat/rooms/$ROOM_ID/messages" "{\"content\":\"這裡有 色情 內容\"}" "$USER_A_CSRF" "$JAR_A")
print_case "A 發送首次違規訊息（應警告）" 403 "$code" "$ROOM_ID"

fetch_auth_csrf "$JAR_A"
USER_A_CSRF="$CSRF_TOKEN"
code=$(call_api POST "/api/chat/rooms/$ROOM_ID/messages" "{\"content\":\"再次含 血腥 用語\"}" "$USER_A_CSRF" "$JAR_A")
print_case "A 違規次次發言（應進入計點）" 403 "$code" "$ROOM_ID"

run_case "A 讀取聊天室訊息" 200 GET "/api/chat/rooms/$ROOM_ID/messages" - "$USER_A_CSRF" "$JAR_A"

echo "Done."
