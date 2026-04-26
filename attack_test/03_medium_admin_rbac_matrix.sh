#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:5000}"
MANAGER_USERNAME="${MANAGER_USERNAME:-s92137}"
MANAGER_PASSWORD="${MANAGER_PASSWORD:-Manager@1234}"
SUPER_USERNAME="${SUPER_USERNAME:-root}"
SUPER_PASSWORD="${SUPER_PASSWORD:-root}"

STAMP="$(date +%s)"
USER_COOKIE="$(mktemp)"
MGR_COOKIE="$(mktemp)"
SUP_COOKIE="$(mktemp)"
RESP_FILE="$(mktemp)"
cleanup() {
  rm -f "$USER_COOKIE" "$MGR_COOKIE" "$SUP_COOKIE" "$RESP_FILE"
}
trap cleanup EXIT

fetch_public_csrf() {
  local tmp
  tmp="$(mktemp)"
  local jar="$1"
  curl -sS -i -o "$tmp" -c "$jar" -b "$jar" "$BASE_URL/" >/dev/null
  local tok
  tok="$(sed -n 's/^Set-Cookie: csrf_token=\([^;]*\).*/\1/pI' "$tmp" | tr -d '\r' | head -n 1)"
  rm -f "$tmp"
  if [ -z "$tok" ]; then
    echo "fetch csrf failed" >&2
    return 1
  fi
  printf '%s\n' "$tok"
}

fetch_session_csrf() {
  local jar="$1" tmp
  tmp="$(mktemp)"
  curl -sS -i -o "$tmp" -b "$jar" -c "$jar" "$BASE_URL/api/csrf-token" >/dev/null
  local body
  body="$(tr -d '\r' < "$tmp" | sed -n '/^{/,$p' | tr -d '\n')"
  rm -f "$tmp"
  token="$(printf '%s' "$body" | sed -n 's/.*\"csrf_token\":\"\([^\"]*\)\".*/\1/p')"
  if [ -z "$token" ]; then
    echo "fetch session csrf failed" >&2
    return 1
  fi
  printf '%s\n' "$token"
}

call_api() {
  local jar="$1" method="$2" path="$3" body="$4" token="$5"
  local cmd=(curl -sS -i -o "$RESP_FILE" -b "$jar" -c "$jar" -X "$method")
  if [ -n "$token" ]; then
    cmd+=( -H "X-CSRF-Token: $token" )
  fi
  if [ "$body" != "-" ]; then
    cmd+=( -H 'Content-Type: application/json' -d "$body" )
  fi
  cmd+=( "$BASE_URL$path" )
  "${cmd[@]}" >/dev/null
}

status_code() {
  sed -n 's/^HTTP\/[0-9.]* \([0-9][0-9][0-9]\).*/\1/p' "$RESP_FILE" | head -n 1
}

print_response() {
  local title="$1"
  local code
  local body
  code="$(status_code)"
  body="$(tr -d '\r' < "$RESP_FILE" | sed -n '/^{/,$p' | tr '\n' ' ')"
  printf '%-62s %-3s %s\n' "$title" "$code" "$body"
}

login_user() {
  local username="$1" password="$2" jar="$3"
  local token body
  token="$(fetch_public_csrf "$jar")"
  body="{\"username\":\"$username\",\"password\":\"$password\",\"csrf_token\":\"$token\"}"
  call_api "$jar" "POST" "/api/login" "$body" "$token" >/dev/null
  local code
  code="$(status_code)"
  if [ "$code" != "200" ]; then
    return 1
  fi
  return 0
}

register_user() {
  local username="$1" password="$2" jar="$3"
  local token body
  token="$(fetch_public_csrf "$jar")"
  body="{\"username\":\"$username\",\"password\":\"$password\",\"password_confirm\":\"$password\",\"nickname\":\"rbtest\",\"real_name\":\"Rbac User\",\"id_number\":\"ABCD${STAMP}X\",\"birthdate\":\"1990-01-01\",\"phone\":\"0912345678\",\"csrf_token\":\"$token\"}"
  call_api "$jar" "POST" "/api/register" "$body" "$token" >/dev/null
  local code
  code="$(status_code)"
  if [ "$code" != "200" ]; then
    echo "register_user failed: $username"
    return 1
  fi
  return 0
}

extract_id_by_username() {
  local json_file="$1" username="$2"
  python3 - "$json_file" "$username" <<'PY'
import json
import sys
path = sys.argv[1]
target = sys.argv[2]
text = open(path, "r", encoding="utf-8").read()
idx = text.find("{")
if idx < 0:
    print("")
    raise SystemExit
try:
    data = json.loads(text[idx:])
except Exception:
    print("")
    raise SystemExit
users = data.get("users") or []
for row in users:
    if row.get("username") == target:
        print(row.get("id", ""))
        raise SystemExit
print("")
PY
}

echo "=== 03_medium_admin_rbac_matrix ==="
echo "Target: $BASE_URL"
echo

TEST_USER="rbac_test_${STAMP}"
TEST_PASS="Rbac@1234!A"

echo "[1] 建立一般用戶帳號"
register_user "$TEST_USER" "$TEST_PASS" "$USER_COOKIE" >/dev/null
echo "  create user => $TEST_USER"

echo "[2] 一般用戶不可訪問管理 API"
login_user "$TEST_USER" "$TEST_PASS" "$USER_COOKIE"
user_csrf="$(fetch_session_csrf "$USER_COOKIE")"
call_api "$USER_COOKIE" "GET" "/api/admin/users" "-" "$user_csrf" >/dev/null
print_response "GET /api/admin/users as normal user"
call_api "$USER_COOKIE" "GET" "/api/admin/audit" "-" "$user_csrf" >/dev/null
print_response "GET /api/admin/audit as normal user"
call_api "$USER_COOKIE" "GET" "/api/admin/settings" "-" "$user_csrf" >/dev/null
print_response "GET /api/admin/settings as normal user"
echo

echo "[3] 管理者(view only) 行為驗證"
login_user "$MANAGER_USERNAME" "$MANAGER_PASSWORD" "$MGR_COOKIE"
mgr_csrf="$(fetch_session_csrf "$MGR_COOKIE")"
call_api "$MGR_COOKIE" "GET" "/api/admin/users" "-" "$mgr_csrf" >/dev/null
print_response "GET /api/admin/users as manager"
call_api "$MGR_COOKIE" "POST" "/api/admin/users" "{\"username\":\"x\",\"password\":\"Test@1234!A\",\"password_confirm\":\"Test@1234!A\",\"nickname\":\"x\",\"real_name\":\"x\",\"id_number\":\"ABCDX1\",\"birthdate\":\"1990-01-01\",\"phone\":\"0912345678\",\"role\":\"user\",\"status\":\"active\"}" "$mgr_csrf" >/dev/null
print_response "POST /api/admin/users as manager (應被拒)"

tmp_users="$(mktemp)"
call_api "$MGR_COOKIE" "GET" "/api/admin/users" "-" "$mgr_csrf" >/dev/null
cp "$RESP_FILE" "$tmp_users"
USER_ID="$(extract_id_by_username "$tmp_users" "$TEST_USER")"
rm -f "$tmp_users"
if [ -z "$USER_ID" ]; then
  echo "failed to parse test user id"
else
  call_api "$MGR_COOKIE" "POST" "/api/admin/users/${USER_ID}/promote" "-" "$mgr_csrf" >/dev/null
  print_response "POST /api/admin/users/${USER_ID}/promote as manager (應被拒)"
fi
echo

if [ -n "${USER_ID:-}" ]; then
  echo "[4] super admin 權限驗證"
  login_user "$SUPER_USERNAME" "$SUPER_PASSWORD" "$SUP_COOKIE"
  super_csrf="$(fetch_session_csrf "$SUP_COOKIE")"
  call_api "$SUP_COOKIE" "POST" "/api/admin/users/${USER_ID}/promote" "-" "$super_csrf" >/dev/null
  print_response "POST /api/admin/users/${USER_ID}/promote as root"
  call_api "$SUP_COOKIE" "GET" "/api/admin/settings" "-" "$super_csrf" >/dev/null
  print_response "GET /api/admin/settings as root"
  call_api "$SUP_COOKIE" "POST" "/api/admin/users/${USER_ID}/demote" "-" "$super_csrf" >/dev/null
  print_response "POST /api/admin/users/${USER_ID}/demote as root"
fi

echo
echo "Done."
