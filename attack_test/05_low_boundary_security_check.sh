#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:5000}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JAR_FILE="$(mktemp)"
RESP_FILE="$(mktemp)"
BACKUP_DIR=""

cleanup() {
  rm -f "$JAR_FILE" "$RESP_FILE"
  if [ -n "${BACKUP_DIR}" ] && [ -d "$BACKUP_DIR" ]; then
    for f in blocked_ips.json fail_log.json rate_limit.json; do
      if [ -f "$BACKUP_DIR/$f" ]; then
        cp "$BACKUP_DIR/$f" "$PROJECT_ROOT/$f"
      elif [ -f "$BACKUP_DIR/$f.missing" ]; then
        rm -f "$PROJECT_ROOT/$f"
      fi
    done
    rm -rf "$BACKUP_DIR"
  fi
}
trap cleanup EXIT

short_status() {
  sed -n '1s/HTTP\/1\.1 \([0-9][0-9][0-9]\).*/\1/p' "$RESP_FILE" | head -n1
}

short_body() {
  tr -d '\r' < "$RESP_FILE" | sed -n '/^{/,$p' | tr '\n' ' '
}

backup_locks() {
  BACKUP_DIR="$(mktemp -d)"
  for f in blocked_ips.json fail_log.json rate_limit.json; do
    if [ -f "$PROJECT_ROOT/$f" ]; then
      cp "$PROJECT_ROOT/$f" "$BACKUP_DIR/$f"
    else
      touch "$BACKUP_DIR/$f.missing"
    fi
  done
}

reset_rate_files() {
  for f in blocked_ips.json fail_log.json rate_limit.json; do
    printf '{}\n' > "$PROJECT_ROOT/$f"
  done
}

fetch_home_csrf() {
  local code
  code=$(curl -sS -i -o "$RESP_FILE" -w "%{http_code}" -c "$JAR_FILE" "$BASE_URL/")
  CSRF_TOKEN="$(awk '/^(127\.0\.0\.1|localhost|::1)/ {print $7; exit}' "$JAR_FILE")"
  echo "CODE=$code TOKEN=${CSRF_TOKEN:-<missing>}"
}

call_api() {
  local method="$1" path="$2" body="$3" token="$4" xff="$5"
  local extra=( -sS -i -o "$RESP_FILE" -w "%{http_code}" -b "$JAR_FILE" -c "$JAR_FILE" -X "$method" )

  if [ -n "$token" ]; then
    extra+=( -H "X-CSRF-Token: $token" )
  fi

  if [ -n "$xff" ]; then
    extra+=( -H "X-Forwarded-For: $xff" )
  fi

  if [ "$body" != "-" ]; then
    extra+=( -H 'Content-Type: application/json' -d "$body" )
  fi

  extra+=( "$BASE_URL$path" )
  curl "${extra[@]}"
}

run_case() {
  local name="$1" method="$2" path="$3" body="$4" token="$5" xff="$6"
  call_api "$method" "$path" "$body" "$token" "$xff" >/dev/null
  printf '%-70s %3s | %s\n' "$name" "$(short_status)" "$(short_body)"
}

print_title() {
  printf '\n=== %s ===\n' "$1"
}

echo "target: $BASE_URL"

print_title "可到達性"
for host in "$BASE_URL" "http://localhost:5000"; do
  st="$(curl -sS -o /tmp/target_home.out -w '%{http_code}' "$host/")"
  echo "GET $host/ => $st"
done

print_title "CSRF 邊界"
fetch_home_csrf >/dev/null
run_case "login without CSRF header" POST /api/login '{"username":"root","password":"bad"}' '' ''
run_case "login with garbage CSRF header" POST /api/login '{"username":"root","password":"bad"}' 'deadbeef' ''
run_case "logout no auth no token" POST /api/logout - '' ''

print_title "註冊邊界"
backup_locks
reset_rate_files

fetch_home_csrf >/dev/null
NEW_USER="reg$(date +%s)"
run_case "register (valid)" POST /api/register "{\"username\":\"$NEW_USER\",\"password\":\"Passw0rd!A\",\"csrf_token\":\"$CSRF_TOKEN\"}" '' ''

fetch_home_csrf >/dev/null
run_case "register duplicate" POST /api/register "{\"username\":\"$NEW_USER\",\"password\":\"Passw0rd!A\",\"csrf_token\":\"$CSRF_TOKEN\"}" '' ''

fetch_home_csrf >/dev/null
run_case "register empty username" POST /api/register "{\"username\":\"\",\"password\":\"Passw0rd!A\",\"csrf_token\":\"$CSRF_TOKEN\"}" '' ''

fetch_home_csrf >/dev/null
run_case "register short username" POST /api/register "{\"username\":\"ab\",\"password\":\"Passw0rd!A\",\"csrf_token\":\"$CSRF_TOKEN\"}" '' ''

fetch_home_csrf >/dev/null
run_case "register long username" POST /api/register "{\"username\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"password\":\"Passw0rd!A\",\"csrf_token\":\"$CSRF_TOKEN\"}" '' ''

fetch_home_csrf >/dev/null
run_case "register spaces" POST /api/register "{\"username\":\"a b\",\"password\":\"Passw0rd!A\",\"csrf_token\":\"$CSRF_TOKEN\"}" '' ''

fetch_home_csrf >/dev/null
run_case "register no csrf_token field" POST /api/register "{\"username\":\"badcsrf$NEW_USER\",\"password\":\"Passw0rd!A\"}" '' ''

print_title "登入邊界"
fetch_home_csrf >/dev/null
run_case "login wrong credential" POST /api/login "{\"username\":\"$NEW_USER\",\"password\":\"wrong\"}" "$CSRF_TOKEN" ''

fetch_home_csrf >/dev/null
run_case "login SQLi payload" POST /api/login "{\"username\":\"' OR 1=1 --\",\"password\":\"x\"}" "$CSRF_TOKEN" ''

fetch_home_csrf >/dev/null
run_case "login empty username" POST /api/login "{\"username\":\"\",\"password\":\"x\"}" "$CSRF_TOKEN" ''

fetch_home_csrf >/dev/null
run_case "login blank password" POST /api/login "{\"username\":\"$NEW_USER\",\"password\":\"\"}" "$CSRF_TOKEN" ''

print_title "登入成功與授權"
fetch_home_csrf >/dev/null
call_api POST /api/login "{\"username\":\"$NEW_USER\",\"password\":\"Passw0rd!A\"}" "$CSRF_TOKEN" "" >/dev/null
echo "login valid status $(short_status) | $(short_body)"
run_case "me with valid session" GET /api/me - '' ''
run_case "audit as normal user" GET /api/audit - '' ''

print_title "登出與會話邊界"
run_case "logout without CSRF header" POST /api/logout - '' ''
fetch_home_csrf >/dev/null
run_case "logout with CSRF header" POST /api/logout - "$CSRF_TOKEN" ''
run_case "me after logout" GET /api/me - '' ''

# Tamper session cookie value only if exists
SESSION_COOKIE="$(awk '/session_token/ {print $7; exit}' "$JAR_FILE")"
if [ -n "$SESSION_COOKIE" ]; then
  TAMPERED="${SESSION_COOKIE}X"
  awk -v old="$SESSION_COOKIE" -v new="$TAMPERED" '{gsub(old, new)}1' "$JAR_FILE" > "$JAR_FILE.t"
  mv "$JAR_FILE.t" "$JAR_FILE"
  run_case "me with tampered session" GET /api/me - '' ''
fi

print_title "額外邊界"
fetch_home_csrf >/dev/null
run_case "wrong csrf via XFF 127.0.0.1" POST /api/login "{\"username\":\"$NEW_USER\",\"password\":\"bad\"}" 'deadbeef' '127.0.0.1'
fetch_home_csrf >/dev/null
run_case "wrong csrf via XFF invalid chain" POST /api/login "{\"username\":\"$NEW_USER\",\"password\":\"bad\"}" 'deadbeef' 'bad, 127.0.0.1'

echo -e "\nDone.\n"
