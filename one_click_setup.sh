#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
MODE="run"
WIZARD="auto"
WITH_COMFYUI=0
COMFYUI_URL="${COMFYUI_URL:-http://127.0.0.1:8192}"
WITH_TURNSTILE=0
TURNSTILE_SECRET="${TURNSTILE_SECRET:-}"
WITH_CIVITAI=0
CIVITAI_API_KEY_VALUE="${CIVITAI_API_KEY_VALUE:-}"
LITE_HINT=0
SKIP_INSTALL=0
ORIGINAL_ARGC="$#"

usage() {
  cat <<'USAGE'
Usage:
  ./one_click_setup.sh [options]

One-command deployment helper for Hackme Web.

Options:
  --check-only            Install/check dependencies and validate config, do not start.
  --check                 Alias of --check-only.
  --init-db-only          Install/check dependencies and initialize/migrate DB only.
  --wizard                Force the interactive first-deploy wizard.
  --no-wizard             Do not prompt; fail if required settings are missing.
  --with-comfyui URL      Add COMFYUI_API_URL to .env before launch.
  --with-turnstile SECRET Add TURNSTILE_SECRET_KEY to .env before launch.
  --with-civitai-key KEY  Add CIVITAI_API_KEY to .env before launch.
  --lite-hint             Print Raspberry Pi / low-end device deployment hints.
  --skip-install          Reuse the current VENV_DIR and skip pip upgrade/install.
  --no-start              Alias for --check-only.
  -h, --help              Show this help.

Environment:
  ENV_FILE                Default: .env
  VENV_DIR                Default: .venv

First deployment:
  Run ./one_click_setup.sh from a terminal. If .env is missing, the wizard asks
  for bootstrap passwords, runtime directories, bind address, HTTPS policy, and
  Gunicorn settings.

Runtime secrets, `runtime/cert.pem`, `runtime/key.pem`, `runtime/database/`,
`runtime/logs/`, `runtime/storage/`, and related manifests are local generated
files and are ignored by git.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check-only|--no-start|--check)
      MODE="check"
      shift
      ;;
    --init-db-only)
      MODE="init-db-only"
      shift
      ;;
    --wizard)
      WIZARD="yes"
      shift
      ;;
    --no-wizard)
      WIZARD="no"
      shift
      ;;
    --with-comfyui)
      WITH_COMFYUI=1
      COMFYUI_URL="${2:?missing ComfyUI URL}"
      shift 2
      ;;
    --with-turnstile)
      WITH_TURNSTILE=1
      TURNSTILE_SECRET="${2:?missing Turnstile secret}"
      shift 2
      ;;
    --with-civitai-key)
      WITH_CIVITAI=1
      CIVITAI_API_KEY_VALUE="${2:?missing Civitai API key}"
      shift 2
      ;;
    --lite-hint)
      LITE_HINT=1
      shift
      ;;
    --skip-install)
      SKIP_INSTALL=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

say() {
  printf '%s\n' "$*"
}

warn() {
  printf 'WARN: %s\n' "$*" >&2
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

ensure_python() {
  command -v python3 >/dev/null 2>&1 || {
    echo "python3 is required. Install it with your OS package manager." >&2
    exit 1
  }
}

ensure_venv() {
  if [[ ! -x "$VENV_DIR/bin/python3" ]]; then
    printf '[setup] creating virtualenv at %s\n' "$VENV_DIR"
    python3 -m venv "$VENV_DIR"
  fi
  # shellcheck disable=SC1091
  . "$VENV_DIR/bin/activate"
  if [[ "$SKIP_INSTALL" == "1" ]]; then
    printf '[setup] skipping dependency install; using existing environment at %s\n' "$VENV_DIR"
    return 0
  fi
  printf '[setup] installing Python dependencies\n'
  PIP_DISABLE_PIP_VERSION_CHECK=1 python3 -m pip install --upgrade pip
  PIP_DISABLE_PIP_VERSION_CHECK=1 python3 -m pip install -r "$ROOT_DIR/requirements.txt"
}

append_or_replace_env() {
  local key="$1"
  local value="$2"
  local tmp="$ENV_FILE.tmp"
  mkdir -p "$(dirname "$ENV_FILE")"
  touch "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  if grep -qE "^${key}=" "$ENV_FILE"; then
    awk -v key="$key" -v value="$value" 'BEGIN{q=sprintf("%c",39)} $0 ~ "^" key "=" {$0=key "=" q value q} {print}' "$ENV_FILE" > "$tmp"
    mv "$tmp" "$ENV_FILE"
  else
    printf "%s='%s'\n" "$key" "$value" >> "$ENV_FILE"
  fi
}

print_lite_hints() {
  cat <<'EOF'
[setup] Low-end device hints:
[setup] - use branch hackme_web_lite when it exists locally/remotely
[setup] - set GUNICORN_WORKERS=1
[setup] - keep ComfyUI and heavy security scanners disabled
[setup] - prefer local-only storage and scheduled maintenance during idle hours
[setup] - use SQLite on local disk, not network storage
EOF
}

is_interactive() {
  [[ -t 0 && -t 1 ]]
}

generate_secret() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
}

shell_quote() {
  python3 - "$1" <<'PY'
import shlex
import sys
print(shlex.quote(sys.argv[1]))
PY
}

prompt_default() {
  local label="$1"
  local default="$2"
  local value
  read -r -p "$label [$default]: " value
  printf '%s' "${value:-$default}"
}

prompt_yes_no() {
  local label="$1"
  local default="$2"
  local suffix="[y/N]"
  local value
  if [[ "$default" == "y" ]]; then
    suffix="[Y/n]"
  fi
  while true; do
    read -r -p "$label $suffix: " value
    value="${value:-$default}"
    case "${value,,}" in
      y|yes) return 0 ;;
      n|no) return 1 ;;
      *) say "請輸入 y 或 n。" ;;
    esac
  done
}

prompt_password() {
  local label="$1"
  local value confirm
  while true; do
    read -r -s -p "$label: " value
    printf '\n' >&2
    if [[ ${#value} -lt 12 ]]; then
      say "密碼至少建議 12 字元。" >&2
      continue
    fi
    read -r -s -p "再次輸入 $label: " confirm
    printf '\n' >&2
    if [[ "$value" != "$confirm" ]]; then
      say "兩次輸入不一致。" >&2
      continue
    fi
    printf '%s' "$value"
    return 0
  done
}

write_env_line() {
  local key="$1"
  local value="$2"
  printf '%s=%s\n' "$key" "$(shell_quote "$value")" >> "$ENV_FILE"
}

run_wizard() {
  is_interactive || die "缺少 $ENV_FILE，且目前不是互動終端。請先執行 ./one_click_setup.sh --wizard 或提供 ENV_FILE。"

  if [[ -e "$ENV_FILE" ]]; then
    if ! prompt_yes_no "$ENV_FILE 已存在，要覆寫嗎？" "n"; then
      say "保留既有 $ENV_FILE。"
      return 0
    fi
  fi

  say "Hackme Web 初次部署設定精靈"
  say "這會建立 $ENV_FILE；檔案權限會設為 600，請不要提交到 git。"
  say ""

  local runtime_root host port external_https force_https cookie_secure use_xff trusted_proxy_ips gunicorn_forwarded_allow_ips
  local workers timeout log_level create_manager create_test manager_password test_password
  local root_password storage_dir db_dir log_dir chat_dir anchor_dir reports_dir

  runtime_root="$(prompt_default "Runtime 資料根目錄" "$HOME/.local/share/hackme_web")"
  runtime_root="${runtime_root/#\~/$HOME}"
  db_dir="$runtime_root/database"
  log_dir="$runtime_root/logs"
  chat_dir="$runtime_root/chats"
  anchor_dir="$runtime_root/anchors"
  storage_dir="$runtime_root/storage"
  reports_dir="$runtime_root/reports"

  host="$(prompt_default "服務綁定 host" "0.0.0.0")"
  port="$(prompt_default "服務 port" "5000")"
  workers="$(prompt_default "Gunicorn workers" "4")"
  timeout="$(prompt_default "Gunicorn timeout 秒數" "60")"
  log_level="$(prompt_default "Gunicorn log level" "info")"

  if prompt_yes_no "服務會透過 HTTPS 對外提供嗎？例如反向代理或憑證終止在前端" "y"; then
    external_https="true"
  else
    external_https="false"
  fi
  force_https="$external_https"
  cookie_secure="$external_https"

  if [[ "$external_https" == "true" ]]; then
    trusted_proxy_ips="$(prompt_default "可信任 proxy IP（用於 HTTPS / forwarded headers；多個用逗號）" "127.0.0.1")"
    if prompt_yes_no "是否信任反向代理傳入的 X-Forwarded-For？" "n"; then
      use_xff="true"
    else
      use_xff="false"
    fi
  elif prompt_yes_no "是否信任反向代理傳入的 X-Forwarded-For？" "n"; then
    use_xff="true"
    trusted_proxy_ips="$(prompt_default "可信任 proxy IP，多個用逗號" "127.0.0.1")"
  else
    use_xff="false"
    trusted_proxy_ips=""
  fi
  gunicorn_forwarded_allow_ips="$trusted_proxy_ips"

  say ""
  say "設定 bootstrap 帳號。root 密碼只用於首次建立或預設密碼判定；首次登入後應立即變更。"
  root_password="$(prompt_password "root 初始密碼")"
  create_manager="false"
  create_test="false"
  manager_password=""
  test_password=""
  if prompt_yes_no "是否建立 manager/admin bootstrap 帳號？" "y"; then
    create_manager="true"
    manager_password="$(prompt_password "manager/admin 初始密碼")"
  fi
  if prompt_yes_no "是否建立測試帳號？正式上線通常不建議" "n"; then
    create_test="true"
    test_password="$(prompt_password "test 初始密碼")"
  fi

  mkdir -p "$(dirname "$ENV_FILE")"
  : > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  {
    printf '# Hackme Web production env\n'
    printf '# Generated by ./one_click_setup.sh --wizard on %s\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } >> "$ENV_FILE"

  write_env_line "FLASK_ENV" "production"
  write_env_line "APP_ENV" "production"
  write_env_line "IP_BLOCKING_ENABLED" "true"
  write_env_line "FORCE_HTTPS" "$force_https"
  write_env_line "SESSION_COOKIE_SECURE" "$cookie_secure"
  write_env_line "SESSION_COOKIE_HTTPONLY" "true"
  write_env_line "SESSION_COOKIE_SAMESITE" "Strict"
  write_env_line "USE_XFF" "$use_xff"
  write_env_line "TRUSTED_PROXY_IPS" "$trusted_proxy_ips"
  write_env_line "GUNICORN_FORWARDED_ALLOW_IPS" "$gunicorn_forwarded_allow_ips"
  write_env_line "SESSION_SECRET" "$(generate_secret)"
  write_env_line "CSRF_SECRET_KEY" "$(generate_secret)"
  write_env_line "ROOT_INTEGRITY_SIGNING_KEY" "$(generate_secret)"
  write_env_line "TURNSTILE_SECRET_KEY" ""

  write_env_line "HTML_LEARNING_ROOT_PASSWORD" "$root_password"
  if [[ "$create_manager" == "true" ]]; then
    write_env_line "HTML_LEARNING_MANAGER_PASSWORD" "$manager_password"
  fi
  if [[ "$create_test" == "true" ]]; then
    write_env_line "HTML_LEARNING_TEST_PASSWORD" "$test_password"
  fi

  write_env_line "HTML_LEARNING_DB_DIR" "$db_dir"
  write_env_line "HTML_LEARNING_LOG_DIR" "$log_dir"
  write_env_line "HTML_LEARNING_CHAT_DIR" "$chat_dir"
  write_env_line "HTML_LEARNING_ANCHOR_DIR" "$anchor_dir"
  write_env_line "HTML_LEARNING_STORAGE_DIR" "$storage_dir"
  write_env_line "HTML_LEARNING_REPORTS_DIR" "$reports_dir"
  write_env_line "HTML_LEARNING_HOST" "$host"
  write_env_line "HTML_LEARNING_PORT" "$port"

  write_env_line "GUNICORN_BIND" "$host:$port"
  write_env_line "GUNICORN_WORKERS" "$workers"
  write_env_line "GUNICORN_TIMEOUT" "$timeout"
  write_env_line "GUNICORN_LOG_LEVEL" "$log_level"
  write_env_line "GUNICORN_ACCESS_LOG" "-"
  write_env_line "GUNICORN_ERROR_LOG" "-"

  mkdir -p "$db_dir" "$log_dir" "$chat_dir" "$anchor_dir" "$storage_dir" "$reports_dir"

  say ""
  say "已建立 $ENV_FILE"
  say "Runtime 目錄：$runtime_root"
  say "下一步會檢查環境並初始化資料庫。"
}

load_env_file() {
  if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
  fi
}

should_run_wizard() {
  if [[ "$WIZARD" == "yes" ]]; then
    return 0
  fi
  if [[ "$WIZARD" == "no" ]]; then
    return 1
  fi
  [[ ! -f "$ENV_FILE" ]]
}

validate_port() {
  local value="$1"
  [[ "$value" =~ ^[0-9]+$ ]] || return 1
  (( value >= 1 && value <= 65535 ))
}

validate_environment() {
  local missing=0
  local port="${HTML_LEARNING_PORT:-5000}"
  local bind="${GUNICORN_BIND:-${HTML_LEARNING_HOST:-0.0.0.0}:$port}"
  local has_ffmpeg="false"
  local has_ffprobe="false"

  command -v python3 >/dev/null 2>&1 || { say "缺少 python3"; missing=1; }
  if ! command -v gunicorn >/dev/null 2>&1 && ! python3 -c "import gunicorn" >/dev/null 2>&1; then
    say "缺少 gunicorn，請先安裝：python3 -m pip install -r requirements.txt"
    missing=1
  fi
  [[ -n "${HTML_LEARNING_ROOT_PASSWORD:-}" ]] || { say "缺少 HTML_LEARNING_ROOT_PASSWORD。首次部署需要 root bootstrap 密碼。"; missing=1; }
  validate_port "$port" || { say "HTML_LEARNING_PORT 不是有效 port：$port"; missing=1; }

  for path_var in HTML_LEARNING_DB_DIR HTML_LEARNING_LOG_DIR HTML_LEARNING_CHAT_DIR HTML_LEARNING_ANCHOR_DIR HTML_LEARNING_STORAGE_DIR HTML_LEARNING_REPORTS_DIR; do
    local path="${!path_var:-}"
    if [[ -z "$path" ]]; then
      say "缺少 $path_var"
      missing=1
      continue
    fi
    if [[ "$path" != /* ]]; then
      say "$path_var 必須是絕對路徑：$path"
      missing=1
    fi
  done

  if [[ "$missing" == "1" ]]; then
    die "部署設定未完成。可執行 ./one_click_setup.sh --wizard 重新產生設定。"
  fi

  if command -v ffmpeg >/dev/null 2>&1; then
    has_ffmpeg="true"
  else
    warn "未找到 ffmpeg；影音平台的 HLS 衍生檔/轉檔功能將無法使用，影片仍可退回直接串流。"
  fi
  if command -v ffprobe >/dev/null 2>&1; then
    has_ffprobe="true"
  else
    warn "未找到 ffprobe；影音 metadata 偵測與 HLS 準備流程會失敗，請安裝 ffmpeg 套件。"
  fi
  if [[ -z "${CIVITAI_API_KEY:-}" ]]; then
    warn "未設定 CIVITAI_API_KEY；root 仍可使用本地模型上傳，但 Civitai 搜尋/下載不會啟用。"
  fi

  say "部署設定檢查"
  say "- env file: $ENV_FILE"
  say "- bind: $bind"
  say "- storage: ${HTML_LEARNING_STORAGE_DIR}"
  say "- database: ${HTML_LEARNING_DB_DIR}"
  say "- logs: ${HTML_LEARNING_LOG_DIR}"
  say "- HTTPS redirect: ${FORCE_HTTPS:-false}"
  say "- secure cookies: ${SESSION_COOKIE_SECURE:-false}"
  say "- gunicorn forwarded proxy trust: ${GUNICORN_FORWARDED_ALLOW_IPS:-<empty>}"
  say "- HLS tooling: ffmpeg=${has_ffmpeg}, ffprobe=${has_ffprobe}"
  say "- Civitai search/download: $([[ -n "${CIVITAI_API_KEY:-}" ]] && printf 'configured' || printf 'disabled (missing CIVITAI_API_KEY)')"
  say "- root offline recovery: python3 scripts/admin/root_recovery.py"
}

prepare_runtime_dirs() {
  mkdir -p \
    "${HTML_LEARNING_DB_DIR}" \
    "${HTML_LEARNING_LOG_DIR}" \
    "${HTML_LEARNING_CHAT_DIR}" \
    "${HTML_LEARNING_ANCHOR_DIR}" \
    "${HTML_LEARNING_STORAGE_DIR}" \
    "${HTML_LEARNING_REPORTS_DIR}"
}

init_database() {
  python3 - <<'PY'
import server

server.init_db(
    ensure_secure_audit_columns=server.ensure_secure_audit_columns,
    ensure_user_columns=server.ensure_user_columns,
    ensure_appeal_columns=server.ensure_appeal_columns,
    ensure_session_columns=server.ensure_session_columns,
    ensure_security_support_schema=server.ensure_security_support_schema,
    ensure_points_economy_schema=server.ensure_points_economy_schema,
    ensure_official_chat_room=server.ensure_official_chat_room,
    hash_password=server.hash_password,
)
conn = server.get_db()
try:
    server.ensure_trading_schema(conn)
    conn.commit()
finally:
    conn.close()
print("database ready")
PY
}

run_post_init_checks() {
  python3 - <<'PY'
import json
import server

results = {}

integrity = server.integrity_guard.scan(actor="one_click_setup", create_initial_manifest=True)
integrity_status = server.integrity_guard.status()
integrity_summary = integrity_status.get("summary") or {}
integrity_health = integrity_status.get("health") or {}
integrity_deployment_review_pending = bool(integrity_status.get("deployment_review_pending"))
integrity_ok = bool(integrity.get("ok", True)) and (
    integrity_deployment_review_pending
    or (
        int(integrity_summary.get("high_risk_pending") or 0) == 0
        and str(integrity_health.get("level") or "").lower() not in {"critical", "error"}
    )
)
results["integrity_guard"] = {
    "ok": integrity_ok,
    "status": "warn" if integrity_deployment_review_pending else ("ok" if integrity_ok else "fail"),
    "health": integrity_health,
    "pending": int(integrity_summary.get("pending") or 0),
    "high_risk_pending": int(integrity_summary.get("high_risk_pending") or 0),
    "deployment_review_pending": integrity_deployment_review_pending,
    "note": (
        "deploy code drift still needs root integrity baseline refresh before GO_LIVE"
        if integrity_deployment_review_pending
        else ""
    ),
}

audit_ok, audit_broken_at, audit_details = server.verify_audit_integrity()
results["audit_chain"] = {
    "ok": bool(audit_ok),
    "broken_at": audit_broken_at,
    "details": audit_details,
}

points = server.points_service.verify_chain()
results["points_chain"] = {
    "ok": bool(points.get("ok")),
    "error_count": int(points.get("error_count") or 0),
    "counts": points.get("counts") or {},
    "errors": list(points.get("errors") or [])[:10],
}

overall_ok = all(bool(item.get("ok")) for item in results.values())
print("post-init runtime checks")
for name in ("integrity_guard", "audit_chain", "points_chain"):
    item = results[name]
    print(f"- {name}: {item.get('status') or ('ok' if item.get('ok') else 'fail')}")
print(json.dumps({"ok": overall_ok, "checks": results}, ensure_ascii=False, indent=2))
if not overall_ok:
    raise SystemExit(1)
PY
}

prepare_tls_runtime() {
  mapfile -t tls_info < <(python3 - <<'PY'
import os
import server

settings = server.get_system_settings()
if bool(settings.get("server_ssl_enabled", True)):
    server.ensure_local_tls_files(server.CERT_FILE, server.KEY_FILE)
cert_exists = os.path.exists(server.CERT_FILE) and os.path.exists(server.KEY_FILE)
ssl_state = server.effective_server_ssl(settings, cert_exists=cert_exists)
print("1" if ssl_state.get("enabled") else "0")
print(server.CERT_FILE)
print(server.KEY_FILE)
print(ssl_state.get("scheme") or "http")
PY
)
  GUNICORN_TLS_ENABLED="${tls_info[0]:-0}"
  GUNICORN_CERT_FILE="${tls_info[1]:-}"
  GUNICORN_KEY_FILE="${tls_info[2]:-}"
  GUNICORN_SCHEME="${tls_info[3]:-http}"
}

main() {
  cd "$ROOT_DIR"
  if [[ "$LITE_HINT" == "1" && "$ORIGINAL_ARGC" == "1" ]]; then
    print_lite_hints
    exit 0
  fi

  ensure_python
  ensure_venv

  if [[ "$WITH_COMFYUI" == "1" ]]; then
    append_or_replace_env "COMFYUI_API_URL" "$COMFYUI_URL"
  fi
  if [[ "$WITH_TURNSTILE" == "1" ]]; then
    append_or_replace_env "TURNSTILE_SECRET_KEY" "$TURNSTILE_SECRET"
  fi
  if [[ "$WITH_CIVITAI" == "1" ]]; then
    append_or_replace_env "CIVITAI_API_KEY" "$CIVITAI_API_KEY_VALUE"
  fi
  if [[ "$LITE_HINT" == "1" ]]; then
    print_lite_hints
  fi

  if should_run_wizard; then
    run_wizard
  fi

  load_env_file

  export IP_BLOCKING_ENABLED="${IP_BLOCKING_ENABLED:-true}"
  export FORCE_HTTPS="${FORCE_HTTPS:-true}"
  export SESSION_COOKIE_SECURE="${SESSION_COOKIE_SECURE:-true}"
  export SESSION_COOKIE_HTTPONLY="${SESSION_COOKIE_HTTPONLY:-true}"
  export SESSION_COOKIE_SAMESITE="${SESSION_COOKIE_SAMESITE:-Strict}"
  export GUNICORN_BIND="${GUNICORN_BIND:-${HTML_LEARNING_HOST:-0.0.0.0}:${HTML_LEARNING_PORT:-5000}}"
  export GUNICORN_WORKERS="${GUNICORN_WORKERS:-4}"
  export GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-60}"
  export GUNICORN_LOG_LEVEL="${GUNICORN_LOG_LEVEL:-info}"
  export GUNICORN_ACCESS_LOG="${GUNICORN_ACCESS_LOG:--}"
  export GUNICORN_ERROR_LOG="${GUNICORN_ERROR_LOG:--}"

  validate_environment
  prepare_runtime_dirs

  if [[ "$MODE" == "check" ]]; then
    init_database
    run_post_init_checks
    say "check complete"
    exit 0
  fi

  init_database
  run_post_init_checks

  if [[ "$MODE" == "init-db-only" ]]; then
    exit 0
  fi

  prepare_tls_runtime
  say "Starting Hackme Web with Gunicorn on ${GUNICORN_SCHEME}://$GUNICORN_BIND ..."
  gunicorn_cmd=(
    python3 -m gunicorn
    --bind "$GUNICORN_BIND"
    --workers "$GUNICORN_WORKERS"
    --timeout "$GUNICORN_TIMEOUT"
    --access-logfile "$GUNICORN_ACCESS_LOG"
    --error-logfile "$GUNICORN_ERROR_LOG"
    --capture-output
    --log-level "$GUNICORN_LOG_LEVEL"
  )
  if [[ "$GUNICORN_TLS_ENABLED" == "1" ]]; then
    gunicorn_cmd+=(--certfile "$GUNICORN_CERT_FILE" --keyfile "$GUNICORN_KEY_FILE")
  fi
  gunicorn_cmd+=(server:app)
  exec "${gunicorn_cmd[@]}"
}

main
