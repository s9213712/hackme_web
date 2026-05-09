#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_GIT_REPO_DIR="$SOURCE_ROOT"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
RUN_ROOT=""
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-5000}"
SKIP_INSTALL=0
FOREGROUND=0
ROOT_PASSWORD="${ROOT_PASSWORD:-root}"
MANAGER_PASSWORD="${MANAGER_PASSWORD:-admin}"
TEST_PASSWORD="${TEST_PASSWORD:-test}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

usage() {
  cat <<'USAGE'
Usage:
  ./test_for_develop.sh [options]

Purpose:
  Copy the repo to /tmp, initialize a development-friendly runtime, and launch
  server.py from the copied workspace so the repo never accumulates runtime or
  cache pollution.

Important:
  For server-mode / production-gate validation, HTML_LEARNING_GIT_REPO_DIR must
  point at a real git repo with a readable .git directory. Do not point it at
  the /tmp copied workspace unless that copy still preserves git metadata.

Options:
  --host HOST              Default: 127.0.0.1
  --port PORT              Default: 5000
  --run-root PATH          Use a fixed /tmp run root instead of auto-generating one
  --skip-install           Reuse runtime/venv inside the tmp copy
  --foreground             Run in the foreground instead of nohup background mode
  --root-password VALUE    Default: root
  --manager-password VALUE Default: admin
  --test-password VALUE    Default: test
  -h, --help               Show this help
USAGE
}

say() {
  printf '%s\n' "$*"
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

copy_repo() {
  mkdir -p "$COPY_ROOT"
  tar -C "$SOURCE_ROOT" \
    --exclude='./.git' \
    --exclude='./.pytest_cache' \
    --exclude='./.venv' \
    --exclude='./__pycache__' \
    --exclude='./cache' \
    --exclude='./runtime' \
    --exclude='*/.pytest_cache' \
    --exclude='*/__pycache__' \
    --exclude='*/cache' \
    --exclude='*.pyc' \
    -cf - . | tar -C "$COPY_ROOT" -xf -
}

python_has_runtime_dependencies() {
  python3 - <<'PY' >/dev/null 2>&1
import argon2
import cryptography
import flask
import flask_talisman
PY
}

resolve_python() {
  local venv_dir="$RUNTIME_ROOT/venv"
  if [[ -x "$venv_dir/bin/python3" ]]; then
    PYTHON_BIN="$venv_dir/bin/python3"
    return 0
  fi
  if [[ "$SKIP_INSTALL" == "1" ]]; then
    if python_has_runtime_dependencies; then
      PYTHON_BIN="python3"
      return 0
    fi
    die "--skip-install requires either an existing tmp venv at $venv_dir or a ready system python3 environment"
  fi
  if python_has_runtime_dependencies; then
    PYTHON_BIN="python3"
    return 0
  fi
  python3 -m venv "$venv_dir"
  PYTHON_BIN="$venv_dir/bin/python3"
  if [[ ! -x "$PYTHON_BIN" ]]; then
    die "failed to create tmp venv at $venv_dir"
  fi
  PIP_DISABLE_PIP_VERSION_CHECK=1 "$PYTHON_BIN" -m pip install --upgrade pip
  PIP_DISABLE_PIP_VERSION_CHECK=1 "$PYTHON_BIN" -m pip install -r "$COPY_ROOT/requirements.txt"
}

wait_for_server_url() {
  command -v curl >/dev/null 2>&1 || return 1
  local url
  local scheme
  for _ in $(seq 1 80); do
    for scheme in https http; do
      url="${scheme}://${HOST}:${PORT}/api/version"
      if curl -k -sS "$url" >/dev/null 2>&1; then
        printf '%s\n' "${scheme}://${HOST}:${PORT}"
        return 0
      fi
    done
    sleep 0.5
  done
  return 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="${2:?missing host}"
      shift 2
      ;;
    --port)
      PORT="${2:?missing port}"
      shift 2
      ;;
    --run-root)
      RUN_ROOT="${2:?missing run root}"
      shift 2
      ;;
    --skip-install)
      SKIP_INSTALL=1
      shift
      ;;
    --foreground)
      FOREGROUND=1
      shift
      ;;
    --root-password)
      ROOT_PASSWORD="${2:?missing root password}"
      shift 2
      ;;
    --manager-password)
      MANAGER_PASSWORD="${2:?missing manager password}"
      shift 2
      ;;
    --test-password)
      TEST_PASSWORD="${2:?missing test password}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

RUN_ROOT="${RUN_ROOT:-/tmp/hackme_web_dev_${RUN_ID}_$$}"
COPY_ROOT="$RUN_ROOT/hackme_web"
RUNTIME_ROOT="$COPY_ROOT/runtime"
LOG_CAPTURE="$RUNTIME_ROOT/logs/server_direct.out"
PID_FILE="$RUNTIME_ROOT/server.pid"

[[ ! -e "$COPY_ROOT" ]] || die "tmp copy already exists: $COPY_ROOT"

copy_repo
mkdir -p \
  "$RUNTIME_ROOT/database" \
  "$RUNTIME_ROOT/logs" \
  "$RUNTIME_ROOT/chats" \
  "$RUNTIME_ROOT/anchors" \
  "$RUNTIME_ROOT/storage" \
  "$RUNTIME_ROOT/reports"

resolve_python
if [[ "$PYTHON_BIN" != "python3" ]]; then
  say "[dev-tmp] python:    $PYTHON_BIN"
else
  say "[dev-tmp] python:    python3 (reuse current environment)"
fi

export HACKME_RUNTIME_DIR="$RUNTIME_ROOT"
export HTML_LEARNING_DB_DIR="$RUNTIME_ROOT/database"
export HTML_LEARNING_LOG_DIR="$RUNTIME_ROOT/logs"
export HTML_LEARNING_CHAT_DIR="$RUNTIME_ROOT/chats"
export HTML_LEARNING_ANCHOR_DIR="$RUNTIME_ROOT/anchors"
export HTML_LEARNING_STORAGE_DIR="$RUNTIME_ROOT/storage"
export HTML_LEARNING_REPORTS_DIR="$RUNTIME_ROOT/reports"
export HTML_LEARNING_HOST="$HOST"
export HTML_LEARNING_PORT="$PORT"
export HTML_LEARNING_ROOT_PASSWORD="$ROOT_PASSWORD"
export HTML_LEARNING_MANAGER_PASSWORD="$MANAGER_PASSWORD"
export HTML_LEARNING_TEST_PASSWORD="$TEST_PASSWORD"
export HTML_LEARNING_DISABLE_DEFAULT_PASSWORD_POLICY=1
if [[ -z "${HTML_LEARNING_GIT_REPO_DIR:-}" ]]; then
  if git -C "$DEFAULT_GIT_REPO_DIR" rev-parse HEAD >/dev/null 2>&1; then
    export HTML_LEARNING_GIT_REPO_DIR="$DEFAULT_GIT_REPO_DIR"
  else
    export HTML_LEARNING_GIT_REPO_DIR="$COPY_ROOT"
  fi
fi
export PYTHONPATH="$COPY_ROOT"
export PYTHONPYCACHEPREFIX="$RUNTIME_ROOT/pycache"

cd "$COPY_ROOT"

HACKME_RUNTIME_OUTPUT_CAPTURE=0 "$PYTHON_BIN" - <<'PY'
from datetime import datetime
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

feature_updates = {
    key: True
    for key in server.DEFAULT_SETTINGS
    if key.startswith("feature_")
}
feature_updates["feature_account_security_enabled"] = False
feature_updates.update({
    "allow_register": True,
    "audit_chain_enabled": False,
    "audit_chain_reseal_required": False,
    "browser_only_mode_enabled": False,
    "captcha_mode": "none",
    "force_https": False,
    "integrity_guard_enabled": False,
    "integrity_guard_strict_mode": False,
    "ip_blocking_enabled": False,
    "login_violation_enabled": False,
    "max_login_failures": 999999,
    "production_single_account_ip_lock_enabled": False,
    "production_single_ip_account_lock_enabled": False,
    "rate_limit_violation_enabled": False,
    "require_email_verification": False,
    "root_ip_whitelist_enabled": False,
    "server_ssl_enabled": True,
    "session_idle_timeout_minutes": 1440,
    "session_ttl_hours": 168,
    # Dev default: assume root has the Windows-portable ComfyUI bundle
    # mounted under WSL at /mnt/d/share/ComfyUI_windows_portable and uses
    # run_in_linux.sh as the entrypoint. Switch to local mode so the dev
    # runtime calls the locally-launched ComfyUI on 127.0.0.1 by default.
    "comfyui_connection_mode": "local",
    "comfyui_base_dir": "/mnt/d/share/ComfyUI_windows_portable",
    "comfyui_local_start_script": "run_in_linux.sh",
})
server.save_settings(feature_updates)

conn = server.get_db()
try:
    server.ensure_trading_schema(conn)
    now = datetime.now().isoformat()
    conn.execute("DELETE FROM ip_blocks")
    conn.execute("DELETE FROM security_events")
    conn.execute("DELETE FROM notifications WHERE type='root_security_alert'")
    conn.execute("UPDATE sessions SET is_revoked=1, revoked_at=?", (now,))
    conn.execute(
        """
        UPDATE users
        SET must_change_password=0,
            is_default_password=0,
            failed_login_count=0,
            locked_until=NULL,
            blocked_until=NULL,
            updated_at=?
        WHERE username IN ('root', 'admin', 'test')
        """,
        (now,),
    )
    conn.execute(
        """
        UPDATE trading_markets_registry
        SET enabled=1,
            allow_spot=1,
            allow_margin=1,
            allow_bots=1,
            allow_risk_grade_usage=1,
            live_price_enabled=1,
            reference_price_enabled=1,
            updated_at=?
        """,
        (now,),
    )
    conn.execute(
        """
        UPDATE trading_markets
        SET enabled=1,
            allow_margin=1,
            allow_bots=1,
            allow_risk_grade_usage=1,
            live_price_enabled=1,
            reference_price_enabled=1,
            updated_at=?
        """,
        (now,),
    )
    for key, value in (
        ("trading.enabled", "true"),
        ("trading.borrowing_enabled", "true"),
        ("trading.margin_liquidation_enabled", "false"),
        ("trading.bot_auto_scan_enabled", "false"),
        ("trading.bot_audit_enabled", "false"),
        ("trading.price_degrade_pause_market_orders", "false"),
        ("trading.price_degrade_pause_bots", "false"),
        ("trading.price_degrade_pause_borrowing", "false"),
        ("trading.warning_language", "zh-TW"),
        ("trading.simulated_slippage_enabled", "false"),
        ("trading.simulated_slippage_base_basis_points", "0"),
        ("trading.simulated_slippage_size_basis_points_per_10k_notional", "0"),
        ("trading.simulated_slippage_max_basis_points", "0"),
        # Dev default: pin price fusion to Binance public API only so the
        # /tmp dev runtime does not require OKX/Coinbase/Kraken/Gemini/Bitstamp
        # reachability for spot trading, live-price, or risk-grade gating.
        ("trading.price_fusion_mode", "manual_weights"),
        (
            "trading.price_fusion_manual_weights_json",
            '{"binance_public_api": 100.0, "okx_public_api": 0.0, '
            '"coinbase_exchange": 0.0, "kraken_public_api": 0.0, '
            '"gemini_public_api": 0.0, "bitstamp_public_api": 0.0}',
        ),
        ("trading.price_fusion_min_provider_count", "1"),
        ("trading.price_fusion_trade_min_provider_count", "1"),
        # Lift the single-provider cap to 100% so dev runtime can run on
        # Binance alone without the provider_weight_cap_unenforceable warning.
        ("trading.price_fusion_max_single_provider_weight_percent", "100"),
    ):
        conn.execute(
            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            (key, value, now, "test_for_develop"),
        )
    conn.commit()
finally:
    conn.close()
PY

if [[ "$FOREGROUND" == "1" ]]; then
  say "[dev-tmp] repo copy: $COPY_ROOT"
  say "[dev-tmp] runtime:   $RUNTIME_ROOT"
  say "[dev-tmp] mode:      foreground server.py"
  exec "$PYTHON_BIN" server.py
fi

setsid "$PYTHON_BIN" server.py >"$LOG_CAPTURE" 2>&1 < /dev/null &
SERVER_PID="$!"
printf '%s\n' "$SERVER_PID" > "$PID_FILE"

SERVER_URL="$(wait_for_server_url || true)"

say "[dev-tmp] repo copy: $COPY_ROOT"
say "[dev-tmp] runtime:   $RUNTIME_ROOT"
say "[dev-tmp] pid:       $SERVER_PID"
if [[ -n "$SERVER_URL" ]]; then
  say "[dev-tmp] url:       $SERVER_URL"
else
  say "[dev-tmp] url:       startup pending; inspect logs"
fi
say "[dev-tmp] accounts:   root/${ROOT_PASSWORD} admin/${MANAGER_PASSWORD} test/${TEST_PASSWORD}"
say "[dev-tmp] log:       $LOG_CAPTURE"
