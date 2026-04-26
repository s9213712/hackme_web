#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:5000}"

TMP_DIR="$(mktemp -d)"
RESP="$TMP_DIR/resp.json"
JAR_A="$TMP_DIR/user_a.jar"
JAR_B="$TMP_DIR/user_b.jar"
JAR_C="$TMP_DIR/user_c.jar"
JAR_PUBLIC="$TMP_DIR/public.jar"
trap 'rm -rf "$TMP_DIR"' EXIT

now_ms() { date +%s%3N; }

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
    echo "[home] cannot get csrf"
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
  CSRF_TOKEN="$(python3 - "$RESP" <<'PY'
import json, pathlib, sys
path = sys.argv[1]
txt = pathlib.Path(path).read_text(errors="ignore")
idx = txt.find("\n{")
if idx == -1:
    idx = txt.find("{")
if idx == -1:
    print("")
    raise SystemExit
try:
    data = json.loads(txt[idx:])
    print(data.get("csrf_token", ""))
except Exception:
    print("")
PY
)"
  if [ -z "$CSRF_TOKEN" ]; then
    echo "[csrf] cannot parse token"
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
  printf '%-85s %-6s (status=%s) %s\n' "$title" "$status" "$got" "$detail"
}

run_case() {
  local title="$1" expect="$2" method="$3" path="$4" body="$5" token="$6" jar="$7"
  local code
  code=$(call_api "$method" "$path" "$body" "$token" "$jar")
  print_case "$title" "$expect" "$code" "$path"
}

extract_json_field() {
  local key="$1"
  python3 - "$RESP" "$key" <<'PY'
import json, pathlib, sys
path = sys.argv[1]
key = sys.argv[2]
text = pathlib.Path(path).read_text(errors="ignore")
idx = text.find("\n{")
if idx == -1:
    idx = text.find("{")
if idx == -1:
    print("")
    raise SystemExit
try:
    payload = json.loads(text[idx:])
except Exception:
    print("")
    raise SystemExit
cur = payload
for part in key.split("."):
    if not isinstance(cur, dict) or part not in cur:
        print("")
        raise SystemExit
    cur = cur.get(part)
if cur is None:
    print("")
else:
    print(cur)
PY
}

register_user() {
  local user="$1" pw="$2" jar="$3"
  local phone body code

  fetch_home_csrf "$jar"
  phone="$(printf '09%08d' "$((RANDOM%100000000))")"
  body="{\"username\":\"$user\",\"password\":\"$pw\",\"password_confirm\":\"$pw\",\"nickname\":\"$user\",\"real_name\":\"$user\",\"id_number\":\"A12345$user\",\"birthdate\":\"1990-01-01\",\"phone\":\"$phone\",\"csrf_token\":\"$CSRF_TOKEN\"}"
  code=$(call_api POST /api/register "$body" "$CSRF_TOKEN" "$jar")
  echo "$code"
}

login_user() {
  local user="$1" pw="$2" jar="$3"
  local body
  local code

  fetch_home_csrf "$jar"
  body="{\"username\":\"$user\",\"password\":\"$pw\",\"csrf_token\":\"$CSRF_TOKEN\"}"
  code=$(call_api POST /api/login "$body" "$CSRF_TOKEN" "$jar")
  echo "$code"
}

user_a="chat_abnd_a_$(now_ms)"
user_b="chat_abnd_b_$(now_ms)"
user_c="chat_abnd_c_$(now_ms)"
pass="Passw0rd!A"

echo "=== chat 邊界測試（高風險） ==="

code="$(register_user "$user_a" "$pass" "$JAR_PUBLIC")"
print_case "註冊 A" 200 "$code" "$user_a"
code="$(register_user "$user_b" "$pass" "$JAR_PUBLIC")"
print_case "註冊 B" 200 "$code" "$user_b"
code="$(register_user "$user_c" "$pass" "$JAR_PUBLIC")"
print_case "註冊 C" 200 "$code" "$user_c"

code=$(login_user "$user_a" "$pass" "$JAR_A")
print_case "A 登入" 200 "$code" "$user_a"
fetch_auth_csrf "$JAR_A"
USER_A_CSRF="$CSRF_TOKEN"

code=$(login_user "$user_b" "$pass" "$JAR_B")
print_case "B 登入" 200 "$code" "$user_b"
fetch_auth_csrf "$JAR_B"
USER_B_CSRF="$CSRF_TOKEN"

code=$(login_user "$user_c" "$pass" "$JAR_C")
print_case "C 登入" 200 "$code" "$user_c"
fetch_auth_csrf "$JAR_C"
USER_C_CSRF="$CSRF_TOKEN"

run_case "未登入讀取聊天室" 401 GET /api/chat/rooms - "" "$JAR_PUBLIC"
run_case "未登入建立聊天室" 401 POST /api/chat/rooms "{\"name\":\"x\"}" "" "$JAR_PUBLIC"

room_name="room_$(now_ms)"
code=$(call_api POST /api/chat/rooms "{\"name\":\"$room_name\"}" "$USER_A_CSRF" "$JAR_A")
print_case "A 建立聊天室" 200 "$code" "$room_name"
ROOM_ID="$(extract_json_field 'room.id')"
if [ -z "$ROOM_ID" ]; then
  echo "cannot extract ROOM_ID, stop"
  exit 1
fi

run_case "B 加入不存在聊天室" 404 POST "/api/chat/rooms/2147483647/join" "{}" "$USER_B_CSRF" "$JAR_B"
run_case "A 取得聊天室清單" 200 GET /api/chat/rooms - "$USER_A_CSRF" "$JAR_A"
run_case "C 讀取 A 的聊天室(未加入)" 403 GET "/api/chat/rooms/$ROOM_ID/messages" - "$USER_C_CSRF" "$JAR_C"

fetch_auth_csrf "$JAR_B"
USER_B_CSRF="$CSRF_TOKEN"
code=$(call_api POST "/api/chat/rooms/$ROOM_ID/join" "{}" "$USER_B_CSRF" "$JAR_B")
print_case "B 加入存在聊天室" 200 "$code" "/api/chat/rooms/$ROOM_ID/join"

fetch_auth_csrf "$JAR_B"
USER_B_CSRF="$CSRF_TOKEN"
code=$(call_api POST "/api/chat/rooms/$ROOM_ID/messages" "{\"content\":\"hello boundary\"}" "$USER_B_CSRF" "$JAR_B")
print_case "B 傳送正常訊息" 200 "$code" "/api/chat/rooms/$ROOM_ID/messages"

fetch_auth_csrf "$JAR_B"
USER_B_CSRF="$CSRF_TOKEN"
code=$(call_api POST "/api/chat/rooms/$ROOM_ID/messages" "{\"content\":\"spoof attempt\"}" "$USER_B_CSRF" "$JAR_C")
print_case "C 使用 B 的 CSRF token 發送訊息" 403 "$code" "/api/chat/rooms/$ROOM_ID/messages"

fetch_auth_csrf "$JAR_B"
USER_B_CSRF="$CSRF_TOKEN"

run_case "聊天室訊息參數 limit=0" 400 GET "/api/chat/rooms/$ROOM_ID/messages?limit=0" - "$USER_B_CSRF" "$JAR_B"
run_case "聊天室訊息參數 limit=1000000" 400 GET "/api/chat/rooms/$ROOM_ID/messages?limit=1000000" - "$USER_B_CSRF" "$JAR_B"
run_case "聊天室訊息參數 limit=abc" 400 GET "/api/chat/rooms/$ROOM_ID/messages?limit=abc" - "$USER_B_CSRF" "$JAR_B"

fetch_auth_csrf "$JAR_B"
USER_B_CSRF="$CSRF_TOKEN"
run_case "送訊息內容空字串" 400 POST "/api/chat/rooms/$ROOM_ID/messages" "{\"content\":\"\"}" "$USER_B_CSRF" "$JAR_B"

fetch_auth_csrf "$JAR_B"
USER_B_CSRF="$CSRF_TOKEN"
run_case "送訊息缺少 content 欄位" 400 POST "/api/chat/rooms/$ROOM_ID/messages" "{\"body\":\"x\"}" "$USER_B_CSRF" "$JAR_B"

fetch_auth_csrf "$JAR_B"
USER_B_CSRF="$CSRF_TOKEN"
run_case "送訊息非 JSON Body" 400 POST "/api/chat/rooms/$ROOM_ID/messages" "-" "$USER_B_CSRF" "$JAR_B"

fetch_auth_csrf "$JAR_B"
USER_B_CSRF="$CSRF_TOKEN"
run_case "訊息超過上限（一次）" 400 POST "/api/chat/rooms/$ROOM_ID/messages" "{\"content\":\"$(printf 'x%.0s' {1..600})\"}" "$USER_B_CSRF" "$JAR_B"

fetch_auth_csrf "$JAR_B"
USER_B_CSRF="$CSRF_TOKEN"
code=$(call_api POST "/api/chat/rooms/$ROOM_ID/messages" "{\"content\":\"first post\"}" "$USER_B_CSRF" "$JAR_B")
print_case "同一 token 首次送出" 200 "$code" "baseline"
code=$(call_api POST "/api/chat/rooms/$ROOM_ID/messages" "{\"content\":\"second post\"}" "$USER_B_CSRF" "$JAR_B")
print_case "同一 token 重放（POST）" 403 "$code" "token replay 防護"

code="$(call_api GET "/api/chat/rooms/$ROOM_ID/messages" "-" "" "$JAR_PUBLIC")"
print_case "C 使用公共 cookie 跨帳號讀取" 401 "$code" "/api/chat/rooms/$ROOM_ID/messages"

fetch_auth_csrf "$JAR_B"
USER_B_CSRF="$CSRF_TOKEN"
code=$(call_api GET "/api/chat/rooms/$ROOM_ID/messages" "-" "$USER_B_CSRF" "$JAR_B")
print_case "會員 B 讀訊息正常" 200 "$code" "/api/chat/rooms/$ROOM_ID/messages"

echo "Done."
