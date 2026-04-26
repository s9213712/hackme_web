#!/usr/bin/env python3
"""
hackme_web — Flask auth server
Hardened edition: timing-noise, account-enumeration protection,
CSRF tokens, strict CSP, full security headers, rate-limit amplification.
"""

import os, sqlite3, re, json, time, hashlib, secrets, hmac, threading, random, base64, fcntl, subprocess, signal, sys
from ipaddress import ip_address
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, make_response
from cryptography.fernet import Fernet
import argon2
from flask_talisman import Talisman

# ── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "database")
DB_PATH = os.path.join(DB_DIR, "database.db")
LOG_DIR = os.path.join(BASE_DIR, "logs")
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
AUDIT_LOG_PATH = os.path.join(LOG_DIR, "audit.log")
SERVER_LOG_PATH = os.path.join(LOG_DIR, "server.log")

os.makedirs(DB_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
# ── Hash-chain integrity key (server-side only, not exposed to client) ───────
# Seed derived from SECRET_KEY so it survives restarts (prevents chain-break on reboot)
def _get_chain_seed():
    # Try to read persisted seed
    seed_file = os.path.join(BASE_DIR, ".chain_seed")
    if os.path.exists(seed_file):
        try:
            with open(seed_file) as f:
                return f.read().strip()
        except Exception:
            pass
    # First run — generate and persist
    import secrets as _s
    seed = _s.token_hex(24)
    with open(seed_file, "w") as f:
        f.write(seed)
    os.chmod(seed_file, 0o600)  # readable only by owner
    return seed

CHAIN_SEED = _get_chain_seed()

# ── Secrets ─────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("SESSION_SECRET",
    open(os.path.join(BASE_DIR, ".fkey")).read() if os.path.exists(os.path.join(BASE_DIR, ".fkey")) else secrets.token_hex(32)
)

_INTEGRITY_KEY = SECRET_KEY.encode()  # HMAC 金鑰（在 SECRET_KEY 之後定義）

# ── Logging ───────────────────────────────────────────────────────────────────
_audit_lock = threading.Lock()

def _chain_hash(prev_hash, entry_json):
    """HMAC-SHA256(prev_hash || entry_json)，確保即使內容相同也不同"""
    return hmac.new(_INTEGRITY_KEY, (prev_hash + entry_json).encode(), "sha256").hexdigest()

def audit(action, ip, user="-", success=False, ua="-", detail="-"):
    """寫入 secure_audit 表（hash chain）+ 可選 legacy JSON 檔（僅轉移期保留）"""
    ts = datetime.now().isoformat(timespec="milliseconds")
    entry = {
        "ts":      ts,
        "action":  action,
        "ip":      ip,
        "user":    user,
        "success": success,
        "ua":      ua[:200],
        "detail":  detail,
    }
    entry_json = json.dumps(entry, ensure_ascii=False)

    conn = get_db()
    try:
        # 取得上一筆記錄的 hash
        prev_row = conn.execute(
            "SELECT chain_hash FROM secure_audit ORDER BY id DESC LIMIT 1"
        ).fetchone()
        prev_hash = prev_row["chain_hash"] if prev_row else CHAIN_SEED

        chain_hash = _chain_hash(prev_hash, entry_json)

        conn.execute(
            "INSERT INTO secure_audit (ts, action, ip, user, success, ua, detail, chain_hash) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (ts, action, ip, user, 1 if success else 0, ua, detail, chain_hash)
        )
        conn.commit()
    finally:
        conn.close()

    # 同步寫入 logs/audit.log（專用日誌目錄）
    _audit_lock.acquire()
    try:
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(entry_json + "\n")
    finally:
        _audit_lock.release()

def verify_audit_integrity(start_id=None, end_id=None):
    """驗證 secure_audit 的 hash chain 完整性。回傳 (ok, broken_at_or_None, details)"""
    conn = get_db()
    try:
        if start_id is None:
            rows = conn.execute(
                "SELECT id, ts, action, ip, user, success, ua, detail, chain_hash "
                "FROM secure_audit ORDER BY id ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, ts, action, ip, user, success, ua, detail, chain_hash "
                "FROM secure_audit WHERE id>=? AND id<=? ORDER BY id ASC",
                (start_id, end_id or start_id)
            ).fetchall()

        if not rows:
            return True, None, "no entries"

        prev_hash = CHAIN_SEED
        for r in rows:
            recomputed = _chain_hash(prev_hash,
                json.dumps({
                    "ts": r["ts"], "action": r["action"], "ip": r["ip"],
                    "user": r["user"], "success": bool(r["success"]),
                    "ua": r["ua"], "detail": r["detail"]
                }, ensure_ascii=False))
            if recomputed != r["chain_hash"]:
                return False, r["id"], f"hash mismatch at id={r['id']} (篡改偵測)"
            prev_hash = r["chain_hash"]
        return True, None, f"integrity OK ({len(rows)} entries verified)"
    finally:
        conn.close()

# ── JSON helpers ──────────────────────────────────────────────────────────────
def load_json(path):
    if not os.path.exists(path): return {}
    try:
        with open(path) as f: return json.load(f)
    except Exception:
        return {}

def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

# ── Atomic JSON ops (thread/process safe via fcntl) ─────────────────────────────
_json_locks = {}   # path → threading.Lock (held within a single process)
def _get_json_lock(path):
    if path not in _json_locks:
        _json_locks[path] = threading.Lock()
    return _json_locks[path]

def load_json_with_lock(path):
    with _get_json_lock(path):
        if not os.path.exists(path): return {}
        try:
            with open(path) as f: return json.load(f)
        except Exception:
            return {}

def save_json_with_lock(path, data):
    with _get_json_lock(path):
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)

# ── CSRF double-submit helpers ─────────────────────────────────────────────────
def generate_csrf_dummy():
    """Dummy value for double-submit verification (matches cookie token)."""
    tok = request.cookies.get("csrf_token", "")
    return tok

def verify_csrf_double_submit(body_token):
    """
    Double-submit: body token must match cookie csrf_token.
    No session required — safe for /register.
    """
    if not isinstance(body_token, str):
        return False
    cookie_tok = request.cookies.get("csrf_token", "")
    if not isinstance(cookie_tok, str) or not cookie_tok or not body_token:
        return False
    if cookie_tok != body_token:
        return False
    # Also verify it exists in DB and is not expired
    tok_hash = hashlib.sha256(cookie_tok.encode()).hexdigest()
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM csrf_tokens WHERE token_hash=? AND expires_at>?",
        (tok_hash, datetime.now().isoformat())
    ).fetchone()
    conn.close()
    if not row:
        return False
    # Consume token (delete immediately — prevents replay)
    conn = get_db()
    conn.execute("DELETE FROM csrf_tokens WHERE token_hash=?", (tok_hash,))
    conn.commit()
    conn.close()
    return True

# ── Argon2 hasher ─────────────────────────────────────────────────────────────
_hasher = argon2.PasswordHasher(time_cost=3, memory_cost=65536,
                                parallelism=4, hash_len=32, salt_len=16)

def hash_password(pw):    return _hasher.hash(pw)
def verify_password(h, p):
    try:    return _hasher.verify(h, p)
    except argon2.exceptions.VerifyMismatchError: return False
    except argon2.exceptions.VerificationError: return False
    except argon2.exceptions.InvalidHash: return False
    except (argon2.exceptions.DecodeError, ValueError, TypeError): return False
    except Exception: return False

# ── Fernet (session tokens) ───────────────────────────────────────────────────
def _get_fernet_key():
    key_file = os.path.join(BASE_DIR, ".fkey")
    if os.path.exists(key_file):
        key = open(key_file, "rb").read()
        if len(key) >= 32:
            return key
    k = Fernet.generate_key()
    open(key_file, "wb").write(k)
    return k

fernet = Fernet(_get_fernet_key())
SESSION_TTL = 3600 * 4

def make_token(username):
    payload = json.dumps({
        "user":  username,
        "exp":   (datetime.now() + timedelta(seconds=SESSION_TTL)).isoformat(),
        "nonce": secrets.token_hex(8)
    }, ensure_ascii=False)
    return fernet.encrypt(payload.encode()).decode()

# ── Sensitive field encryption helpers (PII) ─────────────────────────────
def encrypt_field(value):
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    if value == "":
        return ""
    return fernet.encrypt(value.encode("utf-8")).decode("utf-8")

def decrypt_field(value):
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        return str(value)
    try:
        return fernet.decrypt(value.encode("utf-8")).decode("utf-8")
    except Exception:
        # Backward compatibility with pre-encryption rows
        return value

def verify_token(token):
    try:
        data = json.loads(fernet.decrypt(token.encode()).decode())
        if datetime.now() > datetime.fromisoformat(data["exp"]): return None
        return data["user"]
    except Exception: return None

# ── Token hash (stored in DB for session lookup) ──────────────────────────────
def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()

# ── Security helpers ────────────────────────────────────────────────────────────
# ── Trusted proxies (prevent X-Forwarded-For spoofing) ───────────────────────
def parse_ip_set(raw_value):
    if not raw_value:
        return set()
    values = set()
    for token in str(raw_value).split(","):
        token = token.strip()
        if not token:
            continue
        try:
            values.add(str(ip_address(token)))
        except Exception:
            continue
    return values

TRUSTED_PROXY_IPS = parse_ip_set(os.environ.get("TRUSTED_PROXY_IPS", ""))
USE_XFF = os.environ.get("USE_XFF", "false").strip().lower() in {"1", "true", "on", "yes"}
UNTRUSTED_XFF_MSG = "X-Forwarded-For from untrusted proxy rejected"
IP_BLOCKING_ENABLED = os.environ.get("IP_BLOCKING_ENABLED", "false").strip().lower() in {"1", "true", "on", "yes"}

# ── CSRF double-submit secret ─────────────────────────────────────────────────
CSRF_SECRET_KEY = os.environ.get("CSRF_SECRET_KEY",
    open(os.path.join(BASE_DIR, ".csrfkey")).read().strip()
    if os.path.exists(os.path.join(BASE_DIR, ".csrfkey")) else None
) or (lambda: (open(os.path.join(BASE_DIR, ".csrfkey"), "w").write(secrets.token_hex(32)),
               secrets.token_hex(32)))()


def get_client_ip():
    remote = request.remote_addr or ""
    try:
        remote = str(ip_address(remote))
    except Exception:
        remote = "0.0.0.0"

    # By default, do not trust X-Forwarded-For unless explicitly enabled.
    # This avoids spoofing when app is accessed directly (local tests / direct TLS).
    if not USE_XFF or not TRUSTED_PROXY_IPS:
        return remote

    # Only trust XFF when request source is a trusted proxy in allow-list.
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        if remote in TRUSTED_PROXY_IPS:
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            if parts:
                try:
                    return str(ip_address(parts[0]))
                except Exception:
                    return remote
    return remote

def get_ua(): return request.headers.get("User-Agent","-")[:200]

# ══════════════════════════════════════════════════════════════════════
#  安全事件追蹤（全部寫入 security_events 表，廢除 JSON 檔）
# ══════════════════════════════════════════════════════════════════════

def is_ip_blocked(ip):
    """查 security_events 表，回傳是否在封鎖中（root 永遠不通過）"""
    if ip == "127.0.0.1" or ip == "::1":
        return False          # localhost 不封鎖
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT detail FROM security_events "
            "WHERE event_type='ip_block' AND ip_address=? "
            "ORDER BY created_at DESC LIMIT 1",
            (ip,)
        ).fetchone()
        if not row:
            return False
        # detail 格式：blocked_until=ISO時間
        try:
            until = datetime.fromisoformat(row["detail"].replace("blocked_until=",""))
            return datetime.now() < until
        except Exception:
            return False
    finally:
        conn.close()

def block_ip(ip, minutes=10, reason="multiple failures"):
    """寫入 security_events（ip_block），超時後自動不算"""
    if ip == "127.0.0.1" or ip == "::1":
        return
    blocked_until = (datetime.now() + timedelta(minutes=minutes)).isoformat()
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO security_events (event_type, ip_address, detail, created_at) "
            "VALUES ('ip_block', ?, ?, ?)",
            (ip, f"blocked_until={blocked_until}", datetime.now().isoformat())
        )
        conn.commit()
    finally:
        conn.close()

def record_login_failure(ip, username="", ua="-", detail="-", lock_on=3):
    """寫入 security_events（login_fail），累計超限自動封鎖"""
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO security_events (event_type, ip_address, target_user, detail, created_at) "
            "VALUES ('login_fail', ?, ?, ?, ?)",
            (ip, username, detail, datetime.now().isoformat())
        )
        # 計算最近 N 分鐘內失敗次數
        since = (datetime.now() - timedelta(minutes=10)).isoformat()
        count = conn.execute(
            "SELECT COUNT(*) as c FROM security_events "
            "WHERE event_type='login_fail' AND ip_address=? AND created_at>=?",
            (ip, since)
        ).fetchone()["c"]
        conn.commit()
    finally:
        conn.close()

    audit("LOGIN_FAIL", ip, username, ua=ua, detail=detail)

    if count >= lock_on and IP_BLOCKING_ENABLED:
        block_ip(ip, 10, f"{count} failures → 10 min block")
        audit("LOGIN_IP_BLOCKED", ip, username, ua=ua,
              detail=f"{count} failures → 10 min block")
    return count

def clear_failed_logins(ip):
    """清除該 IP 的失敗記錄（登入成功後呼叫）"""
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM security_events WHERE event_type='login_fail' AND ip_address=?",
            (ip,)
        )
        conn.commit()
    finally:
        conn.close()

def is_rate_limited(ip, max_req=30, window_sec=60):
    """寫入 security_events（rate_limit），計算視窗內次數"""
    conn = get_db()
    try:
        since = (datetime.now() - timedelta(seconds=window_sec)).isoformat()
        conn.execute(
            "INSERT INTO security_events (event_type, ip_address, detail, created_at) "
            "VALUES ('rate_limit', ?, ?, ?)",
            (ip, f"window={window_sec}s", datetime.now().isoformat())
        )
        count = conn.execute(
            "SELECT COUNT(*) as c FROM security_events "
            "WHERE event_type='rate_limit' AND ip_address=? AND created_at>=?",
            (ip, since)
        ).fetchone()["c"]
        conn.commit()
        if count > max_req:
            return True, {"count": count, "limit": max_req}
        return False, {"count": count, "limit": max_req}
    finally:
        conn.close()

def record_403_access(ip, path, username="-"):
    """403 未授權存取寫入 security_events（可觸發違規計次）"""
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO security_events (event_type, ip_address, target_user, detail, created_at) "
            "VALUES ('403_access', ?, ?, ?, ?)",
            (ip, username, f"path={path}", datetime.now().isoformat())
        )
        conn.commit()
    finally:
        conn.close()

# ══════════════════════════════════════════════════════════════════════
#  防竄改違規計次（hash chain）
# ══════════════════════════════════════════════════════════════════════

def _violation_chain_hash(prev_hash, entry_json):
    return hmac.new(_INTEGRITY_KEY, (prev_hash + entry_json).encode(), "sha256").hexdigest()

def secure_add_violation(user_id, username, role, points, reason, triggered_by, actor_username):
    """
    寫入 secure_violations（hash chain）。
    回傳 (action, msg, new_count)。
    不在這裡自動刪除/降級——由呼叫端處理。
    """
    ts = datetime.now().isoformat(timespec="milliseconds")
    entry = {
        "user_id": user_id, "username": username, "points": points,
        "reason": reason, "triggered_by": triggered_by,
        "actor_username": actor_username, "ts": ts,
    }
    entry_json = json.dumps(entry, ensure_ascii=False)

    conn = get_db()
    try:
        prev_row = conn.execute(
            "SELECT entry_hash FROM secure_violations WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (user_id,)
        ).fetchone()
        prev_hash = prev_row["entry_hash"] if prev_row else CHAIN_SEED

        entry_hash  = _violation_chain_hash(prev_hash, entry_json)

        conn.execute(
            "INSERT INTO secure_violations "
            "(user_id, username, points, reason, triggered_by, actor_username, created_at, prev_hash, entry_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (user_id, username, points, reason, triggered_by, actor_username, ts, prev_hash, entry_hash)
        )
        conn.commit()
    finally:
        conn.close()

    # 更新 users.violation_count
    conn2 = get_db()
    try:
        new_count = conn2.execute(
            "UPDATE users SET violation_count = violation_count + ? WHERE id = ? RETURNING violation_count",
            (points, user_id)
        ).fetchone()["violation_count"]
        conn2.commit()
    finally:
        conn2.close()

    return entry_hash, new_count

def verify_violation_integrity(user_id):
    """驗證某用戶的 violation chain。回傳 (ok, broken_at_or_None, details)"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, user_id, username, points, reason, triggered_by, actor_username, created_at, prev_hash, entry_hash "
            "FROM secure_violations WHERE user_id=? ORDER BY id ASC",
            (user_id,)
        ).fetchall()
        if not rows:
            return True, None, "no entries"

        prev_hash = CHAIN_SEED
        for r in rows:
            recomputed = _violation_chain_hash(prev_hash,
                json.dumps({
                    "user_id": r["user_id"], "username": r["username"],
                    "points": r["points"], "reason": r["reason"],
                    "triggered_by": r["triggered_by"],
                    "actor_username": r["actor_username"], "ts": r["created_at"]
                }, ensure_ascii=False))
            if recomputed != r["entry_hash"]:
                return False, r["id"], f"篡改偵測 at id={r['id']}"
            prev_hash = r["entry_hash"]
        return True, None, f"integrity OK ({len(rows)} records verified)"
    finally:
        conn.close()

# ── 申覆判斷輔助函式 ─────────────────────────────────────────────────────
def get_latest_violation(conn, user_id):
    return conn.execute(
        "SELECT id, user_id, username, points, reason, triggered_by, actor_username, created_at "
        "FROM secure_violations WHERE user_id=? ORDER BY id DESC LIMIT 1",
        (user_id,)
    ).fetchone()

def parse_iso_to_datetime(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(v)
    except Exception:
        return None

# ══════════════════════════════════════════════════════════════════════
#  自動違規觸發整合
# ══════════════════════════════════════════════════════════════════════

def check_and_apply_auto_violations(user_id, username, role, actor_username="system"):
    """
    檢查是否觸發自動違規。
    傳入：user_id, username, role, actor（通常是 'system'）
    回傳：(triggered, reason, new_total) 或 (False, None, current_count)
    """
    settings = SYSTEM_SETTINGS   # 全域
    triggered = False
    reason = None

    # 1. 登入失敗超限觸發（由 record_login_failure 已在 security_events 寫log，
    #    這裡只檢查累計次數）
    if settings.get("login_violation_enabled", True):
        threshold = settings.get("max_login_fails_for_violation", 5)
        conn = get_db()
        try:
            since = (datetime.now() - timedelta(hours=1)).isoformat()
            fail_count = conn.execute(
                "SELECT COUNT(*) as c FROM security_events "
                "WHERE event_type='login_fail' AND target_user=? AND created_at>=?",
                (username, since)
            ).fetchone()["c"]
            # 每 threshold 次失敗計 1 點
            if fail_count >= threshold:
                points = fail_count // threshold
                entry_hash, new_total = secure_add_violation(
                    user_id, username, role, points,
                    f"auto: 登入失敗 {fail_count} 次（閾值 {threshold}）",
                    "system", actor_username
                )
                triggered = True
                reason = f"登入失敗 {fail_count} 次 → +{points} 點"
        finally:
            conn.close()

    return triggered, reason, None

# ══════════════════════════════════════════════════════════════════════
#  Constant-time delay (anti-timing-attack)
# ══════════════════════════════════════════════════════════════════════
MIN_DELAY = 0.25   # seconds — minimum to obscure real verify time
MAX_DELAY = 0.90   # seconds — random extra delay

def timing_delay():
    """Add random jitter to obscure Argon2 timing."""
    time.sleep(MIN_DELAY + random.uniform(0, MAX_DELAY - MIN_DELAY))

# ── Account enumeration protection ─────────────────────────────────────────
# Real error messages — used in AUDIT only, never returned to client
REAL_MSGS = {
    "blank":    "請填寫帳號與密碼",
    "blocked":  "IP 已被鎖定，請稍後再試",
    "ratelimit":"請求太頻繁，請稍後再試",
    "no_user":  "登入失敗（帳號或密碼錯誤）",
    "bad_pw":   "登入失敗（帳號或密碼錯誤）",
    "inactive": "帳號已被停用",
    "locked":   "帳號已被鎖定",
}
# Generic message returned to client — identical for all failures
GENERIC_MSG = "登入失敗（帳號或密碼錯誤）"
GENERIC_MSG_REG = "註冊失敗，請稍後再試"

# ── CSRF token ────────────────────────────────────────────────────────────────
CSRF_TOKEN_TTL = 3600  # 1 hour

def make_csrf_token():
    return secrets.token_hex(16)

def store_csrf_token(token, username):
    conn = get_db()
    expires = (datetime.now() + timedelta(seconds=CSRF_TOKEN_TTL)).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO csrf_tokens (token_hash, username, expires_at) VALUES (?, ?, ?)",
        (hashlib.sha256(token.encode()).hexdigest(), username, expires)
    )
    conn.commit()
    conn.close()

def verify_csrf_token(token, username):
    if not isinstance(token, str) or not token:
        return False
    if not isinstance(username, str) or not username:
        return False
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT 1 FROM csrf_tokens WHERE token_hash=? AND username=? AND expires_at>?",
            (hashlib.sha256(token.encode()).hexdigest(), username, datetime.now().isoformat())
        ).fetchone()
        return row is not None
    finally:
        conn.close()

def delete_csrf_token(token):
    """Remove a used CSRF token from DB to prevent replay."""
    if not token: return
    h = hashlib.sha256(token.encode()).hexdigest()
    conn = get_db()
    conn.execute("DELETE FROM csrf_tokens WHERE token_hash=?", (h,))
    conn.commit()
    conn.close()

# ── CSRF require decorator ─────────────────────────────────────────────────────
def require_csrf(f):
    """Decorator: verify CSRF token, then DELETE it to prevent replay.
    Checks __public__ for unauthenticated routes (login), username for authenticated ones.
    Login: token MUST come from header or body (NOT cookie) to prevent browser-auto-submit bypass.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # Extract CSRF token — try header first, then JSON body (never from cookie)
        csrf_tok = request.headers.get("X-CSRF-Token", "") or ""
        if not isinstance(csrf_tok, str):
            csrf_tok = ""
        body_username = None
        if request.is_json:
            body = request.get_json(silent=True) or {}
            if isinstance(body, dict):
                body_username = body.get("username", "")
                if isinstance(body_username, str):
                    body_username = body_username.strip()
                else:
                    body_username = ""
            if not csrf_tok:
                if isinstance(body, dict):
                    csrf_body = body.get("csrf_token", "")
                    if isinstance(csrf_body, str):
                        csrf_tok = csrf_body

        # Determine if user is authenticated
        tok = request.cookies.get("session_token")
        user = db_get_user_from_token(tok) if tok else None

        if user:
            # Authenticated routes — verify against real username only
            if not verify_csrf_token(csrf_tok, user):
                return json_resp({"ok": False, "msg": "CSRF token 無效或已過期"}), 403
        else:
            # Unauthenticated login — token must be in body or header (NOT cookie)
            if not csrf_tok:
                return json_resp({"ok": False, "msg": "CSRF token 缺失"}), 403
            # Valid if token matches __public__ OR target username
            if not verify_csrf_token(csrf_tok, "__public__") and \
               not (body_username and verify_csrf_token(csrf_tok, body_username)):
                return json_resp({"ok": False, "msg": "CSRF token 無效或已過期"}), 403

        # Delete immediately — token can only be used once (replay prevention)
        delete_csrf_token(csrf_tok)

        return f(*args, **kwargs)
    return decorated

def require_csrf_safe(f):
    """Like @require_csrf but does NOT delete the token — safe for GET read-only endpoints.
    Verifies the token is valid for the authenticated user, then leaves it intact so
    the browser can reuse it for subsequent requests in the same session.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        csrf_tok = request.headers.get("X-CSRF-Token", "") or ""
        if not isinstance(csrf_tok, str):
            csrf_tok = ""
        tok = request.cookies.get("session_token")
        user = db_get_user_from_token(tok) if tok else None
        if not user:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        if not verify_csrf_token(csrf_tok, user):
            return json_resp({"ok": False, "msg": "CSRF token 無效或已過期"}), 403
        # NOTE: token is intentionally NOT deleted — safe for read-only GET
        return f(*args, **kwargs)
    return decorated

# ── Password validation ────────────────────────────────────────────────────────
PW_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]).{8,128}$")

def validate_password(pw):
    if not isinstance(pw, str): return False, "密碼格式錯誤"
    if len(pw) < 8:   return False, "密碼至少需要 8 個字元"
    if len(pw) > 128: return False, "密碼太長（最多 128 字元）"
    if not re.search(r"[A-Z]", pw):  return False, "密碼必須包含大寫字母"
    if not re.search(r"[a-z]", pw):  return False, "密碼必須包含小寫字母"
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", pw):
        return False, "密碼必須包含符號"
    return True, "OK"

# ── Database ───────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
    except Exception:
        pass
    return conn

# RBAC / account status helpers
ROLE_RANK       = {"user": 0, "manager": 1, "super_admin": 2}
ROLE_LABEL      = {
    "super_admin": "最高管理者",
    "manager": "管理者",
    "user": "一般用戶",
}
MAX_MANAGERS    = 5
MAX_VIOLATIONS  = {"manager": 3, "user": 5}
MAX_LOGIN_FAILS_FOR_VIOLATION = 5  # 登入失敗幾次後計點
VIOLATION_APPEAL_WINDOW_HOURS = 24

# ── System settings (可被超級管理者修改) ───────────────────────────────────
SETTINGS_FILE = os.path.join(BASE_DIR, "system_settings.json")

DEFAULT_SETTINGS = {
    "max_login_fails_for_violation": 5,
    "login_violation_enabled": True,
    "rate_limit_violation_enabled": True,
    "maintenance_mode": False,
}

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()
    try:
        with open(SETTINGS_FILE) as f:
            return {**DEFAULT_SETTINGS, **json.load(f)}
    except Exception:
        return DEFAULT_SETTINGS.copy()

def save_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

SYSTEM_SETTINGS = load_settings()

# ── Server restart helper ────────────────────────────────────────────────────
def restart_server():
    """Send SIGTERM to this process — let the start-script handle restart."""
    audit("SERVER_RESTART_REQUESTED", get_client_ip(), detail="graceful restart initiated")
    os.kill(os.getpid(), signal.SIGTERM)


def role_rank(role):
    return ROLE_RANK.get(role or "user", 0)

def count_role(role):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM users WHERE role=? AND username<>'root'",
            (role,)
        ).fetchone()
        return row["c"] if row else 0
    finally:
        conn.close()

def add_violation(user_id, username, role, points=1, reason="手動計點", triggered_by="super_admin", actor_username="admin"):
    """
    增加違規計點（寫入 secure_violations hash-chain），
    超過閾值自動降級 / 刪除。回傳 (action_taken, msg, new_count)。
    """
    # 先寫入 secure_violations（會更新 users.violation_count）
    entry_hash, new_count = secure_add_violation(
        user_id, username, role, points, reason, triggered_by, actor_username
    )

    conn = get_db()
    try:
        threshold = MAX_VIOLATIONS.get(role, 5)
        if new_count >= threshold:
            conn.execute(
                "UPDATE users SET status='inactive', violation_count=?, updated_at=? WHERE id=?",
                (new_count, datetime.now().isoformat(), user_id)
            )
            conn.commit()
            audit("USER_SUSPENDED_BY_VIOLATION", get_client_ip(), user="system",
                  detail=f"user_id={user_id} violated={new_count} (secure_violations hash={entry_hash[:16]}...)")
            return "suspended", f"違規次數 {new_count}/{threshold}，帳號已暫停，請申覆", new_count
        return "counted", f"違規計點 +{points}（{new_count}/{threshold}）", new_count
    finally:
        conn.close()

def normalize_text(v):
    return (v or "").strip() if isinstance(v, str) else ""

def parse_birthdate(v):
    if not v:
        return None
    v = str(v).strip()
    try:
        datetime.strptime(v, "%Y-%m-%d")
        return v
    except Exception:
        return None

def parse_positive_int(v, default=None, min_value=1, max_value=None):
    if v is None:
        return default
    if isinstance(v, bool):
        return None
    if isinstance(v, float) and not v.is_integer():
        return None
    if isinstance(v, str):
        v = v.strip()
    try:
        value = int(v)
    except (TypeError, ValueError):
        return None
    if value < min_value:
        return None
    if max_value is not None and value > max_value:
        return None
    return value

def validate_id_number(v):
    if not isinstance(v, str):
        return False
    v = v.strip()
    if not v:
        return False
    return bool(re.fullmatch(r"^[A-Za-z0-9]{5,24}$", v))

def validate_phone(v):
    if not isinstance(v, str):
        return False
    v = v.strip()
    if not v:
        return False
    return bool(re.fullmatch(r"^\+?[0-9][0-9\-]{5,30}$", v))

def get_user_by_username(username):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT id, username, email, nickname, real_name, birthdate, id_number, phone, status, role, blocked_until "
            "FROM users WHERE username=?",
            (username,)
        ).fetchone()
    finally:
        conn.close()

def get_current_user_ctx():
    tok = request.cookies.get("session_token")
    if not tok:
        return None
    username = db_get_user_from_token(tok)
    if not username:
        return None
    return get_user_by_username(username)

def user_public_payload(row):
    if not row:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "nickname": decrypt_field(row["nickname"]),
        "real_name": decrypt_field(row["real_name"]),
        "birthdate": decrypt_field(row["birthdate"]),
        "id_number": decrypt_field(row["id_number"]),
        "phone": decrypt_field(row["phone"]),
        "status": row["status"],
        "role": row["role"],
        "role_label": ROLE_LABEL.get(row["role"], row["role"]),
        "blocked_until": row["blocked_until"],
        "violation_count": dict(row).get("violation_count") or 0,
    }

def ensure_user_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    for col, ddl in (
        ("nickname", "ALTER TABLE users ADD COLUMN nickname TEXT"),
        ("blocked_until", "ALTER TABLE users ADD COLUMN blocked_until TEXT"),
        ("violation_count", "ALTER TABLE users ADD COLUMN violation_count INTEGER NOT NULL DEFAULT 0"),
    ):
        if col not in cols:
            conn.execute(ddl)

def ensure_appeal_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(violation_appeals)").fetchall()}
    for col, ddl in (
        ("pre_status", "ALTER TABLE violation_appeals ADD COLUMN pre_status TEXT NOT NULL DEFAULT 'active'"),
        ("pre_role", "ALTER TABLE violation_appeals ADD COLUMN pre_role TEXT NOT NULL DEFAULT 'user'"),
    ):
        if col not in cols:
            conn.execute(ddl)

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT    NOT NULL UNIQUE,
            email      TEXT,
            nickname   TEXT,
            real_name  TEXT,
            birthdate  TEXT,
            id_number  TEXT,
            phone      TEXT,
            blocked_until TEXT,
            status     TEXT    NOT NULL DEFAULT 'active',
            role       TEXT    NOT NULL DEFAULT 'user',
            created_at TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS user_passwords (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            password_hash   TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS login_attempts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
            ip_address   TEXT,
            user_agent   TEXT,
            success      INTEGER NOT NULL DEFAULT 0,
            attempted_at TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash   TEXT    NOT NULL UNIQUE,
            ip_address   TEXT,
            user_agent   TEXT,
            expires_at   TEXT    NOT NULL,
            created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS csrf_tokens (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            token_hash   TEXT    NOT NULL UNIQUE,
            username     TEXT    NOT NULL,
            expires_at   TEXT    NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions(token_hash);
        CREATE INDEX IF NOT EXISTS idx_sessions_user_id     ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_login_attempts_user  ON login_attempts(user_id);
        CREATE INDEX IF NOT EXISTS idx_login_attempts_ip    ON login_attempts(ip_address);
        CREATE INDEX IF NOT EXISTS idx_login_attempts_time  ON login_attempts(attempted_at);
        CREATE INDEX IF NOT EXISTS idx_csrf_token_hash      ON csrf_tokens(token_hash);

        /* ── 防竄改審計日誌（hash chain）─── */
        CREATE TABLE IF NOT EXISTS secure_audit (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT    NOT NULL,
            action      TEXT    NOT NULL,
            ip          TEXT,
            user        TEXT,
            success     INTEGER NOT NULL DEFAULT 0,
            ua          TEXT,
            detail      TEXT,
            chain_hash  TEXT    NOT NULL   /* SHA256HMAC(prev_hash || entry_json) */
        );
        CREATE INDEX IF NOT EXISTS idx_secure_audit_ts    ON secure_audit(ts);
        CREATE INDEX IF NOT EXISTS idx_secure_audit_action ON secure_audit(action);
        CREATE INDEX IF NOT EXISTS idx_secure_audit_user   ON secure_audit(user);

        /* ── 防竄改違規計次（hash chain）─── */
        CREATE TABLE IF NOT EXISTS secure_violations (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL,
            username       TEXT    NOT NULL,
            points         INTEGER NOT NULL DEFAULT 1,
            reason         TEXT    NOT NULL,
            triggered_by   TEXT    NOT NULL,   /* 'system' | 'manager' | 'super_admin' */
            actor_username TEXT    NOT NULL,   /* 操作者 */
            created_at     TEXT    NOT NULL,
            prev_hash      TEXT    NOT NULL,   /* 上一筆記錄的 chain_hash */
            entry_hash     TEXT    NOT NULL    /* 本筆記錄的 hash */
        );
        CREATE INDEX IF NOT EXISTS idx_sec_viol_user   ON secure_violations(user_id);
        CREATE INDEX IF NOT EXISTS idx_sec_viol_reason  ON secure_violations(reason);
        CREATE INDEX IF NOT EXISTS idx_sec_viol_actor  ON secure_violations(actor_username);

        /* ── 申覆流程（可溯源）─── */
        CREATE TABLE IF NOT EXISTS violation_appeals (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id                 INTEGER NOT NULL,
            username                TEXT    NOT NULL,
            latest_violation_id     INTEGER,
            violation_count_snapshot INTEGER NOT NULL DEFAULT 0,
            penalty_points          INTEGER NOT NULL DEFAULT 0,
            pre_status              TEXT    NOT NULL DEFAULT 'active',
            pre_role                TEXT    NOT NULL DEFAULT 'user',
            reason                  TEXT    NOT NULL,
            status                  TEXT    NOT NULL DEFAULT 'pending',  /* pending / approved / rejected */
            reviewed_by             TEXT,
            reviewed_at             TEXT,
            review_note             TEXT,
            created_at              TEXT    NOT NULL,
            CONSTRAINT fk_appeal_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_appeal_user      ON violation_appeals(user_id);
        CREATE INDEX IF NOT EXISTS idx_appeal_status     ON violation_appeals(status);
        CREATE INDEX IF NOT EXISTS idx_appeal_created_at ON violation_appeals(created_at);

        /* ── 安全事件追蹤（廢除 blocked_ips.json / fail_log.json / rate_limit.json）─── */
        CREATE TABLE IF NOT EXISTS security_events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type   TEXT    NOT NULL,   /* 'login_fail' | 'ip_block' | 'rate_limit' | '403_access' */
            ip_address   TEXT    NOT NULL,
            target_user  TEXT,
            detail       TEXT,
            created_at   TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sec_event_ip    ON security_events(ip_address);
        CREATE INDEX IF NOT EXISTS idx_sec_event_type  ON security_events(event_type);
        CREATE INDEX IF NOT EXISTS idx_sec_event_time  ON security_events(created_at);
    """)

    ensure_user_columns(conn)
    ensure_appeal_columns(conn)

    # Keep role value consistent when coming from older schema
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "role" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
    except Exception:
        pass
    conn.execute("UPDATE users SET role='user' WHERE role IS NULL OR role=''")

    # Ensure root account exists, keep existing root data/password across restarts.
    # First start will create with root/root; later upgrades preserve edits.
    now = datetime.now().isoformat()
    root_row = conn.execute("SELECT id FROM users WHERE username='root'").fetchone()
    if root_row:
        root_id = root_row["id"]
        conn.execute(
            "UPDATE users SET role='super_admin', status='active', updated_at=? WHERE id=?",
            (now, root_id)
        )
    else:
        root_cur = conn.execute(
            "INSERT INTO users (username, status, role, created_at, updated_at) VALUES (?, 'active', 'super_admin', ?, ?)",
            ("root", now, now)
        )
        root_id = root_cur.lastrowid
        conn.execute(
            "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)",
            (root_id, hash_password("root"), now)
        )
    # Only seed default root password if missing.
    has_root_pw = conn.execute(
        "SELECT 1 FROM user_passwords WHERE user_id=? LIMIT 1", (root_id,)
    ).fetchone()
    if not has_root_pw:
        conn.execute(
            "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)",
            (root_id, hash_password("root"), now)
        )

    # Manager account: s92137 (keep password if already existed)
    row = conn.execute("SELECT id FROM users WHERE username='s92137'").fetchone()
    if row:
        conn.execute(
            "UPDATE users SET role='manager', status='active', updated_at=? WHERE username='s92137'",
            (now,)
        )
    else:
        mgr_cur = conn.execute(
            "INSERT INTO users (username, status, role, created_at, updated_at) VALUES (?, 'active', 'manager', ?, ?)",
            ("s92137", now, now)
        )
        conn.execute(
            "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)",
            (mgr_cur.lastrowid, hash_password("Manager@1234"), now)
        )

    conn.commit()
    conn.close()

# ── Session helpers ─────────────────────────────────────────────────────────────
def db_save_session(user_id, token, ip, ua):
    conn = get_db()
    expires = (datetime.now() + timedelta(seconds=SESSION_TTL)).isoformat()
    conn.execute(
        "INSERT INTO sessions (user_id, token_hash, ip_address, user_agent, expires_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, hash_token(token), ip, ua, expires)
    )
    conn.commit()
    conn.close()

def db_delete_session(token):
    conn = get_db()
    conn.execute("DELETE FROM sessions WHERE token_hash=?", (hash_token(token),))
    conn.commit()
    conn.close()

def db_clean_expired_sessions():
    conn = get_db()
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (datetime.now().isoformat(),))
    conn.commit()
    conn.close()

def db_get_user_from_token(token):
    conn = get_db()
    row = conn.execute(
        "SELECT u.username FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?",
        (hash_token(token), datetime.now().isoformat())
    ).fetchone()
    conn.close()
    return row["username"] if row else None

def db_get_user_role(username):
    conn = get_db()
    row = conn.execute(
        "SELECT role FROM users WHERE username=?", (username,)
    ).fetchone()
    conn.close()
    return row["role"] if row else None

# ── Flask app ──────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=PUBLIC_DIR, static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

# ── Security Headers (via Flask-Talisman) ─────────────────────────────────────
# CSP: strict mode (no inline scripts/styles)
talisman = Talisman(app,
    content_security_policy={
        "default-src": "'self'",
        "script-src":  "'self'",
        "style-src":   "'self'",
        "img-src":     "'self' data:",
        "font-src":    "'self'",
        "connect-src": "'self'",
        "frame-ancestors": "'none'",
        "form-action":  "'self'",
        "base-uri":    "'self'",
        "object-src":  "'none'",
    },
    referrer_policy="no-referrer",
    feature_policy={},
    force_https=False,        # SSL termination at proxy level
)

# ── Legacy security headers (supplement Talisman) ─────────────────────────────
@app.after_request
def extra_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    # Talisman sets Server header; override to avoid fingerprinting
    response.headers["Server"] = "WebServer"
    response.headers.pop("X-Powered-By", None)
    if request.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# ── CORS (tightly scoped — no wildcard) ────────────────────────────────────────
@app.before_request
def restrict_cors():
    if request.method == "OPTIONS":
        origin = request.headers.get("Origin", "")
        # Only allow same-origin
        if origin and origin != request.host_url.rstrip("/"):
            return ("", 204)

# ── JSON response helper ───────────────────────────────────────────────────────
def json_resp(data, status=200):
    r = make_response(jsonify(data), status)
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Cache-Control"] = "no-store"
    return r

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    resp = make_response(send_from_directory(PUBLIC_DIR, "index.html"))
    tok = request.cookies.get("session_token")
    user = db_get_user_from_token(tok) if tok else None
    if not user:
        # Ship a CSRF token for login form — no session needed
        tok = make_csrf_token()
        store_csrf_token(tok, "__public__")
        resp.set_cookie("csrf_token", tok, max_age=3600, httponly=False,
                        samesite="Strict", secure=request.is_secure)
    # Logged-in users keep their per-user csrf_token cookie (set at login)
    return resp

# ── GET CSRF token ─────────────────────────────────────────────────────────────
@app.route("/api/csrf-token", methods=["GET"])
def get_csrf_token():
    tok = request.cookies.get("session_token")
    username = db_get_user_from_token(tok) if tok else None
    if not username:
        return json_resp({"ok":False,"msg":"未登入"}), 401
    token = make_csrf_token()
    store_csrf_token(token, username)
    return json_resp({"ok":True,"csrf_token":token})

@app.route("/api/register", methods=["POST"])
def register():
    ip, ua = get_client_ip(), get_ua()
    audit("REGISTER_ATTEMPT", ip, ua=ua)
    if is_ip_blocked(ip):
        audit("REGISTER_BLOCKED", ip, ua=ua, detail="IP locked")
        return json_resp({"ok":False,"msg":"IP 已被鎖定，請稍後再試"}), 429

    blocked, info = is_rate_limited(ip, max_req=10, window_sec=60)
    if blocked:
        audit("REGISTER_RATELIMIT", ip, ua=ua)
        return json_resp({"ok":False,"msg":f"請求太頻繁（{info['limit']}次/分鐘）"}), 429

    try:    data = request.get_json(force=True)
    except: return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
    if not isinstance(data, dict):
        audit("REGISTER_EMPTY", ip, ua=ua)
        return json_resp({"ok":False,"msg":"Invalid request"}), 400

    # CSRF double-submit check (no session required — safe for register)
    if not verify_csrf_double_submit(data.get("csrf_token", "")):
        audit("REGISTER_CSRF", ip, ua=ua)
        return json_resp({"ok":False,"msg":"Invalid request"}), 403

    username = normalize_text(data.get("username"))
    password = data.get("password","") if isinstance(data.get("password"), str) else ""
    password_confirm = data.get("password_confirm","") if isinstance(data.get("password_confirm"), str) else ""
    nickname = normalize_text(data.get("nickname"))
    real_name = normalize_text(data.get("real_name"))
    id_number = normalize_text(data.get("id_number"))
    birthdate = parse_birthdate(data.get("birthdate"))
    phone = normalize_text(data.get("phone"))

    # Username validation
    if not username:        return json_resp({"ok":False,"msg":"帳號不可為空"}), 400
    if len(username) < 3:  return json_resp({"ok":False,"msg":"帳號至少需要 3 個字元"}), 400
    if len(username) > 32: return json_resp({"ok":False,"msg":"帳號最長 32 字元"}), 400
    if not re.fullmatch(r"[a-zA-Z0-9_\-]+", username):
        return json_resp({"ok":False,"msg":"帳號只能包含英文、數字、底線、減號"}), 400
    if not nickname:
        return json_resp({"ok":False,"msg":"暱稱不可為空"}), 400
    if not real_name:
        return json_resp({"ok":False,"msg":"真實姓名不可為空"}), 400
    if not validate_id_number(id_number):
        return json_resp({"ok":False,"msg":"身分證格式錯誤"}), 400
    if not birthdate:
        return json_resp({"ok":False,"msg":"生日需為 YYYY-MM-DD"}), 400
    if not validate_phone(phone):
        return json_resp({"ok":False,"msg":"電話格式錯誤"}), 400
    if password != password_confirm:
        return json_resp({"ok":False,"msg":"兩次輸入的密碼不一致"}), 400

    ok, msg = validate_password(password)
    if not ok:
        audit("REGISTER_BAD_PW", ip, username, ua=ua, detail=msg)
        return json_resp({"ok":False,"msg":msg}), 400

    conn = get_db()
    try:
        existing = conn.execute("SELECT 1 FROM users WHERE username=?",(username,)).fetchone()
        if existing:
            time.sleep(0.3)
            audit("REGISTER_DUP", ip, username, ua=ua, success=False)
            # Return generic — don't reveal account exists
            return json_resp({"ok":False,"msg":"註冊失敗，請稍後再試"}), 409

        now = datetime.now().isoformat()
        cur = conn.execute(
            "INSERT INTO users (username, nickname, real_name, birthdate, id_number, phone, status, role, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'active', 'user', ?, ?)",
            (username, encrypt_field(nickname), encrypt_field(real_name), encrypt_field(birthdate), encrypt_field(id_number), encrypt_field(phone), now, now)
        )
        user_id = cur.lastrowid
        conn.execute(
            "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)",
            (user_id, hash_password(password), now)
        )
        conn.commit()
        audit("REGISTER_OK", ip, username, ua=ua, success=True)
        return json_resp({"ok":True,"msg":"註冊成功"})
    finally:
        conn.close()

@app.route("/api/login", methods=["POST"])
@require_csrf
def login():
    ip, ua = get_client_ip(), get_ua()

    # Check blocked BEFORE anything else
    if is_ip_blocked(ip):
        audit("LOGIN_BLOCKED", ip, ua=ua, detail="IP locked")
        timing_delay()  # still do delay so blocked vs not-blocked timing looks same
        return json_resp({"ok":False,"msg":"登入失敗（帳號或密碼錯誤）"}), 429

    blocked, info = is_rate_limited(ip, max_req=30, window_sec=60)
    if blocked:
        audit("LOGIN_RATELIMIT", ip, ua=ua)
        timing_delay()
        return json_resp({"ok":False,"msg":"請求太頻繁，請稍後再試"}), 429

    try:
        data = request.get_json(force=True)
    except Exception:
        record_login_failure(ip, ua=ua, detail="invalid_json")
        timing_delay()
        return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
    if not isinstance(data, dict):
        record_login_failure(ip, ua=ua, detail="json_not_object")
        timing_delay()
        return json_resp({"ok":False,"msg":"Invalid request"}), 400

    username = (data.get("username","") if isinstance(data.get("username"), str) else "").strip()
    password = data.get("password","") if isinstance(data.get("password"), str) else ""

    # Generic blank check — same message regardless of which field
    if not username or not password:
        record_login_failure(ip, username, ua=ua, detail="blank_field")
        timing_delay()
        return json_resp({"ok":False,"msg":"請填寫帳號與密碼"}), 400

    conn = get_db()
    try:
        user_row = conn.execute(
            "SELECT id, username, status, blocked_until, role FROM users WHERE username=?", (username,)
        ).fetchone()

        # Always do timing-consuming verify to prevent timing oracles
        pw_hash = None
        if user_row:
            pw_row = conn.execute(
                "SELECT password_hash FROM user_passwords WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
                (user_row["id"],)
            ).fetchone()
            if pw_row:
                pw_hash = pw_row["password_hash"]

        # Perform verify with constant-ish delay regardless of user existence
        if pw_hash:
            verified = verify_password(pw_hash, password)
        else:
            # Fake hash work — user doesn't exist, still burn same CPU time
            # Properly formatted: 16-byte salt → 22 b64 chars, 32-byte hash → 43 b64 chars
            fake_salt = base64.urlsafe_b64encode(b"fakesaltPASSSalt0").decode()[:22]
            fake_hsh  = base64.urlsafe_b64encode(b"f" * 32).decode()[:43]
            try:
                verify_password(f"$argon2id$v=19$m=65536,t=3,p=4${fake_salt}${fake_hsh}", password)
            except argon2.exceptions.VerifyMismatchError:
                pass  # expected — always fails
            verified = False

        # ALWAYS add jitter delay to obscure timing differences
        timing_delay()

        now = datetime.now().isoformat()
        if verified:
            if user_row["blocked_until"]:
                try:
                    blocked_until = datetime.fromisoformat(user_row["blocked_until"])
                    if datetime.now() < blocked_until:
                        audit("LOGIN_BLOCKED_TEMP", ip, username, ua=ua, detail=f"blocked_until={user_row['blocked_until']}")
                        return json_resp({"ok":False,"msg":"登入失敗（帳號或密碼錯誤）"}), 401
                except Exception:
                    pass
            if user_row["status"] != "active":
                audit("LOGIN_INACTIVE", ip, username, ua=ua, success=False)
                return json_resp({"ok":False,"msg":"登入失敗（帳號或密碼錯誤）"}), 401

            # Log successful attempt
            conn.execute(
                "INSERT INTO login_attempts (user_id, ip_address, user_agent, success, attempted_at) VALUES (?, ?, ?, 1, ?)",
                (user_row["id"], ip, ua, now)
            )
            conn.commit()

            # Create token + save session to DB
            token = make_token(username)
            db_save_session(user_row["id"], token, ip, ua)

            audit("LOGIN_OK", ip, username, ua=ua, success=True)
            resp = json_resp({"ok":True,"msg":"恭喜登入成功","token":token})
            resp.set_cookie("session_token", token, max_age=SESSION_TTL,
                            httponly=True, samesite="Strict",
                            secure=request.is_secure)
            # Invalidate the public CSRF token and issue a fresh per-user token
            new_csrf = make_csrf_token()
            store_csrf_token(new_csrf, username)
            resp.set_cookie("csrf_token", new_csrf, max_age=CSRF_TOKEN_TTL,
                            httponly=False, samesite="Strict",
                            secure=request.is_secure)
            return resp
        else:
            # Log failed attempt
            user_id_for_log = user_row["id"] if user_row else None
            conn.execute(
                "INSERT INTO login_attempts (user_id, ip_address, user_agent, success, attempted_at) VALUES (?, ?, ?, 0, ?)",
                (user_id_for_log, ip, ua, now)
            )
            conn.commit()
            record_login_failure(ip, username=username, ua=ua, detail="bad_credentials")

            # Generic message — never distinguish "no user" from "bad pw"
            return json_resp({"ok":False,"msg":"登入失敗（帳號或密碼錯誤）"}), 401
    finally:
        conn.close()

@app.route("/api/logout", methods=["POST"])
@require_csrf
def logout():
    ip, ua, tok = get_client_ip(), get_ua(), request.cookies.get("session_token")
    user = db_get_user_from_token(tok) if tok else None
    if tok:
        db_delete_session(tok)
    audit("LOGOUT", ip, user=user or "-", ua=ua, success=bool(user))
    resp = json_resp({"ok":True,"msg":"已登出"})
    resp.delete_cookie("session_token")
    resp.delete_cookie("csrf_token")
    return resp

@app.route("/api/me", methods=["GET"])
def me():
    ctx = get_current_user_ctx()
    if not ctx:
        return json_resp({"ok":False,"msg":"未登入"}), 401
    role = "super_admin" if ctx["username"] == "root" else ctx["role"]
    return json_resp({
        "ok": True,
        "username": ctx["username"],
        "role": role,
        "role_label": ROLE_LABEL.get(role, role),
        "status": ctx["status"],
        "nickname": decrypt_field(ctx["nickname"]),
        "birthdate": decrypt_field(ctx["birthdate"]),
    })

@app.route("/api/audit", methods=["GET"])
def api_audit():
    tok = request.cookies.get("session_token")
    user = db_get_user_from_token(tok) if tok else None
    if not user: return json_resp({"ok":False,"msg":"未授權"}), 401
    if role_rank(db_get_user_role(user) or "user") < role_rank("manager"):
        audit("AUDIT_FORBIDDEN", get_client_ip(), user, detail="non-manager attempted audit access")
        return json_resp({"ok":False,"msg":"需要管理者或最高管理者權限"}), 403

    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT u.username, la.ip_address, la.user_agent, la.success, la.attempted_at "
            "FROM login_attempts la LEFT JOIN users u ON u.id=la.user_id "
            "ORDER BY la.attempted_at DESC LIMIT 200"
        ).fetchall()
    finally:
        conn.close()

    entries = []
    for r in rows:
        entries.append({
            "user":      r["username"] or "(未知)",
            "ip":        r["ip_address"],
            "ua":        r["user_agent"],
            "success":   bool(r["success"]),
            "time":      r["attempted_at"],
        })
    return json_resp({"ok":True,"entries":entries})

@app.route("/api/admin/users", methods=["GET","POST"])
@require_csrf_safe
def admin_users():
    actor = get_current_user_ctx()
    if not actor:
        return json_resp({"ok":False,"msg":"未登入"}), 401

    if actor["username"] == "root":
        actor_role = "super_admin"
    else:
        actor_role = actor["role"]

    # Manager can only view; super_admin can add / modify / delete
    if request.method == "GET":
        if role_rank(actor_role) < role_rank("manager"):
            return json_resp({"ok":False,"msg":"權限不足"}), 403
        conn = get_db()
        try:
            now = datetime.now()
            if actor_role == "super_admin":
                rows = conn.execute(
                    "SELECT id, username, email, nickname, real_name, birthdate, id_number, phone, status, role, blocked_until, violation_count "
                    "FROM users ORDER BY id ASC"
                ).fetchall()
                data = [user_public_payload(r) for r in rows]
            else:
                rows = conn.execute(
                    "SELECT id, username, status, role, blocked_until, violation_count FROM users ORDER BY id ASC"
                ).fetchall()
                data = []
                for r in rows:
                    blocked_until = r["blocked_until"]
                    blocked = False
                    if blocked_until:
                        try:
                            blocked = datetime.fromisoformat(blocked_until) > now
                        except Exception:
                            blocked = False
                    data.append({
                        "id": r["id"],
                        "username": r["username"],
                        "nickname": "",
                        "real_name": "",
                        "status": r["status"],
                        "role": r["role"],
                        "blocked_until": r["blocked_until"],
                        "blocked": blocked,
                        "violation_count": (r["violation_count"] if "violation_count" in r.keys() else 0),
                    })
        finally:
            conn.close()
        return json_resp({
            "ok": True,
            "users": data,
            "can_manage": role_rank(actor_role) >= role_rank("super_admin")
        })

    # POST — super_admin only
    if role_rank(actor_role) < role_rank("super_admin"):
        return json_resp({"ok":False,"msg":"只有最高權限可新增帳號"}), 403

    try:
        data = request.get_json(force=True)
    except Exception:
        return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
    if not isinstance(data, dict):
        return json_resp({"ok":False,"msg":"Invalid request"}), 400

    username = normalize_text(data.get("username"))
    password = data.get("password", "") if isinstance(data.get("password"), str) else ""
    password_confirm = data.get("password_confirm","") if isinstance(data.get("password_confirm"), str) else ""
    nickname = normalize_text(data.get("nickname"))
    real_name = normalize_text(data.get("real_name"))
    id_number = normalize_text(data.get("id_number"))
    birthdate = parse_birthdate(data.get("birthdate"))
    phone = normalize_text(data.get("phone"))
    role = normalize_text(data.get("role")) or "user"
    status = normalize_text(data.get("status")) or "active"

    if role not in ROLE_RANK:
        return json_resp({"ok":False,"msg":"不支援的角色"}), 400
    if status not in ("active","inactive"):
        return json_resp({"ok":False,"msg":"帳號狀態錯誤"}), 400
    if not username or len(username) < 3:
        return json_resp({"ok":False,"msg":"帳號至少 3 字元"}), 400
    if len(username) > 32:
        return json_resp({"ok":False,"msg":"帳號最長 32 字元"}), 400
    if not re.fullmatch(r"[a-zA-Z0-9_\-]+", username):
        return json_resp({"ok":False,"msg":"帳號只能包含英文、數字、底線、減號"}), 400
    if not nickname:
        return json_resp({"ok":False,"msg":"暱稱不可為空"}), 400
    if not real_name:
        return json_resp({"ok":False,"msg":"真實姓名不可為空"}), 400
    if not validate_id_number(id_number):
        return json_resp({"ok":False,"msg":"身分證格式錯誤"}), 400
    if not birthdate:
        return json_resp({"ok":False,"msg":"生日需為 YYYY-MM-DD"}), 400
    if not validate_phone(phone):
        return json_resp({"ok":False,"msg":"電話格式錯誤"}), 400
    if password != password_confirm:
        return json_resp({"ok":False,"msg":"兩次輸入的密碼不一致"}), 400

    # 超級管理者可指定任意密碼（繞過複雜度規則，但仍截斷長度）
    is_super = actor_role == "super_admin"
    if password:
        password = password[:128]  # 截斷防止超長密碼
        if not is_super:
            ok, msg = validate_password(password)
            if not ok:
                return json_resp({"ok":False,"msg":msg}), 400
    else:
        return json_resp({"ok":False,"msg":"新建帳號必須指定密碼"}), 400

    conn = get_db()
    try:
        existing = conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone()
        if existing:
            return json_resp({"ok":False,"msg":"帳號已存在"}), 409
        now = datetime.now().isoformat()
        cur = conn.execute(
            "INSERT INTO users (username, nickname, real_name, birthdate, id_number, phone, role, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (username, encrypt_field(nickname), encrypt_field(real_name), encrypt_field(birthdate), encrypt_field(id_number), encrypt_field(phone), role, status, now, now)
        )
        conn.execute(
            "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)",
            (cur.lastrowid, hash_password(password), now)
        )
        conn.commit()
        audit("ADMIN_CREATE_USER", get_client_ip(), user=actor["username"], success=True, ua=get_ua(),
              detail=f"target={username}, role={role}")
        return json_resp({"ok":True,"msg":"帳號已建立"})
    finally:
        conn.close()

@app.route("/api/admin/users/<int:user_id>", methods=["GET"])
@require_csrf_safe
def admin_user_item(user_id):
    actor = get_current_user_ctx()
    if not actor:
        return json_resp({"ok":False,"msg":"未登入"}), 401
    actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
    if role_rank(actor_role) < role_rank("super_admin"):
        return json_resp({"ok":False,"msg":"只有最高權限可管理帳號"}), 403

    conn = get_db()
    try:
        target = conn.execute(
            "SELECT id, username, nickname, real_name, birthdate, id_number, phone, role, status, blocked_until, violation_count FROM users WHERE id=?",
            (user_id,)
        ).fetchone()
        if not target:
            return json_resp({"ok":False,"msg":"找不到帳號"}), 404
        return json_resp({
            "ok": True,
            "user": {
                "id": target["id"],
                "username": target["username"],
                "nickname": decrypt_field(target["nickname"]),
                "real_name": decrypt_field(target["real_name"]),
                "birthdate": decrypt_field(target["birthdate"]),
                "id_number": decrypt_field(target["id_number"]),
                "phone": decrypt_field(target["phone"]),
                "role": target["role"],
                "status": target["status"],
                "blocked_until": target["blocked_until"],
                "violation_count": target["violation_count"] or 0,
            }
        })
    finally:
        conn.close()

@app.route("/api/admin/users/<int:user_id>", methods=["PUT", "DELETE"])
@require_csrf
def admin_user_item_mutate(user_id):
    actor = get_current_user_ctx()
    if not actor:
        return json_resp({"ok":False,"msg":"未登入"}), 401
    actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
    if role_rank(actor_role) < role_rank("super_admin"):
        return json_resp({"ok":False,"msg":"只有最高權限可管理帳號"}), 403

    conn = get_db()
    try:
        target = conn.execute(
            "SELECT id, username, nickname, real_name, birthdate, id_number, phone, role, status, blocked_until, violation_count FROM users WHERE id=?",
            (user_id,)
        ).fetchone()
        if not target:
            return json_resp({"ok":False,"msg":"找不到帳號"}), 404

        if request.method == "DELETE":
            if target["username"] == "root":
                return json_resp({"ok":False,"msg":"不可刪除最高管理者帳號"}), 403
            conn.execute("DELETE FROM users WHERE id=?", (user_id,))
            conn.commit()
            audit("ADMIN_DELETE_USER", get_client_ip(), user=actor["username"], success=True, ua=get_ua(),
                  detail=f"target_id={user_id}")
            return json_resp({"ok":True,"msg":"帳號已刪除"})

        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400

        updates = []
        params = []
        if "nickname" in data:
            updates.append("nickname=?")
            params.append(encrypt_field(normalize_text(data["nickname"])))
        if "real_name" in data:
            updates.append("real_name=?")
            params.append(encrypt_field(normalize_text(data["real_name"])))
        if "id_number" in data:
            val = normalize_text(data["id_number"])
            if not validate_id_number(val):
                return json_resp({"ok":False,"msg":"身分證格式錯誤"}), 400
            updates.append("id_number=?")
            params.append(encrypt_field(val))
        if "birthdate" in data:
            val = parse_birthdate(data["birthdate"])
            if not val:
                return json_resp({"ok":False,"msg":"生日需為 YYYY-MM-DD"}), 400
            updates.append("birthdate=?")
            params.append(encrypt_field(val))
        if "phone" in data:
            val = normalize_text(data["phone"])
            if not validate_phone(val):
                return json_resp({"ok":False,"msg":"電話格式錯誤"}), 400
            updates.append("phone=?")
            params.append(encrypt_field(val))
        if "status" in data:
            val = normalize_text(data["status"])
            if val not in ("active","inactive"):
                return json_resp({"ok":False,"msg":"帳號狀態錯誤"}), 400
            updates.append("status=?")
            params.append(val)
        if "role" in data:
            val = normalize_text(data["role"])
            if val not in ROLE_RANK:
                return json_resp({"ok":False,"msg":"不支援的角色"}), 400
            if target["username"] == "root" and val != "super_admin":
                return json_resp({"ok":False,"msg":"最高管理者角色不可變更"}), 403
            updates.append("role=?")
            params.append(val)
        if "password" in data and isinstance(data["password"], str) and data["password"]:
            pw = data["password"][:128]  # 截斷防止超長密碼
            pw_confirm = data.get("password_confirm","") if isinstance(data.get("password_confirm"), str) else ""
            if pw_confirm and pw != pw_confirm:
                return json_resp({"ok":False,"msg":"兩次密碼輸入不一致"}), 400
            if actor_role != "super_admin":
                ok, msg = validate_password(pw)
                if not ok:
                    return json_resp({"ok":False,"msg":msg}), 400
            conn.execute(
                "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)",
                (user_id, hash_password(pw), datetime.now().isoformat())
            )
        if "username" in data:
            return json_resp({"ok":False,"msg":"不允許變更帳號名稱"}), 400

        pw_payload = "password" in data and isinstance(data["password"], str) and data["password"]
        if not updates and not pw_payload:
            return json_resp({"ok":False,"msg":"未提供可更新欄位"}), 400

        if pw_payload and not updates:
            conn.commit()
        elif updates:
            updates.append("updated_at=?")
            params.append(datetime.now().isoformat())
            params.append(user_id)
            sql = "UPDATE users SET " + ", ".join(updates) + " WHERE id=?"
            conn.execute(sql, params)
            conn.commit()
        audit("ADMIN_UPDATE_USER", get_client_ip(), user=actor["username"], success=True, ua=get_ua(),
              detail=f"target_id={user_id}")
        return json_resp({"ok":True,"msg":"帳號已更新"})
    finally:
        conn.close()

@app.route("/api/admin/users/<int:user_id>/block", methods=["POST"])
@require_csrf
def admin_user_block(user_id):
    actor = get_current_user_ctx()
    if not actor:
        return json_resp({"ok":False,"msg":"未登入"}), 401
    actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
    if role_rank(actor_role) < role_rank("manager"):
        return json_resp({"ok":False,"msg":"權限不足"}), 403

    try:
        data = request.get_json(force=True)
    except Exception:
        return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
    if not isinstance(data, dict):
        return json_resp({"ok":False,"msg":"Invalid request"}), 400

    action = normalize_text(data.get("action")).lower() or "block"
    minutes = data.get("minutes", 30)
    if not isinstance(minutes, int):
        try:
            minutes = int(minutes)
        except Exception:
            minutes = 30
    if minutes < 1: minutes = 1
    if minutes > 1440: minutes = 1440

    conn = get_db()
    try:
        target = conn.execute("SELECT id, username, role FROM users WHERE id=?", (user_id,)).fetchone()
        if not target:
            return json_resp({"ok":False,"msg":"找不到帳號"}), 404
        if target["username"] == "root" and actor_role != "super_admin":
            return json_resp({"ok":False,"msg":"無權限封鎖最高管理者"}), 403

        if action == "unblock":
            conn.execute("UPDATE users SET status='active', blocked_until=NULL WHERE id=?", (user_id,))
            conn.commit()
            audit("ADMIN_UNBLOCK_USER", get_client_ip(), user=actor["username"], success=True, ua=get_ua(),
                  detail=f"target_id={user_id}")
            return json_resp({"ok":True,"msg":"帳號已解除封鎖"})

        blocked_until = (datetime.now() + timedelta(minutes=minutes)).isoformat()
        conn.execute("UPDATE users SET status='inactive', blocked_until=? WHERE id=?", (blocked_until, user_id))
        conn.commit()
        audit("ADMIN_BLOCK_USER", get_client_ip(), user=actor["username"], success=True, ua=get_ua(),
              detail=f"target_id={user_id}, minutes={minutes}")
        return json_resp({"ok":True,"msg":f"帳號已封鎖 {minutes} 分鐘"})
    finally:
        conn.close()

# ── 推廣 / 降級（promote / demote）───────────────────────────────────────────────
@app.route("/api/admin/users/<int:user_id>/promote", methods=["POST"])
@require_csrf
def admin_user_promote(user_id):
    """僅超級管理者可推廣帳號"""
    actor = get_current_user_ctx()
    if not actor:
        return json_resp({"ok":False,"msg":"未登入"}), 401
    actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
    if role_rank(actor_role) < role_rank("super_admin"):
        return json_resp({"ok":False,"msg":"權限不足"}), 403

    conn = get_db()
    try:
        target = conn.execute(
            "SELECT id, username, role FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if not target:
            return json_resp({"ok":False,"msg":"找不到帳號"}), 404

        from_role = target["role"]
        if from_role == "super_admin":
            return json_resp({"ok":False,"msg":"最高管理者無需推廣"}), 400
        if from_role == "manager" and role_rank(actor_role) < role_rank("super_admin"):
            return json_resp({"ok":False,"msg":"只有最高管理者可推廣管理者"}), 403

        to_role = "manager" if from_role == "user" else "super_admin"
        if to_role == "manager":
            limit = MAX_MANAGERS
            if count_role("manager") >= limit:
                return json_resp({"ok":False,"msg":f"管理者已達上限（{limit} 人）"}), 400
        # super_admin 限額 1 不需要檢查（root 不可變）

        conn.execute("UPDATE users SET role=?, violation_count=0, updated_at=? WHERE id=?",
                     (to_role, datetime.now().isoformat(), user_id))
        conn.commit()
        audit("USER_PROMOTED", get_client_ip(), user=actor["username"],
              success=True, detail=f"user_id={user_id} {from_role}→{to_role}")
        return json_resp({"ok":True,"msg":f"已升為 {ROLE_LABEL[to_role]}"})
    finally:
        conn.close()

@app.route("/api/admin/users/<int:user_id>/demote", methods=["POST"])
@require_csrf
def admin_user_demote(user_id):
    """超級管理者可將管理者降為一般用戶（再次降級＝刪除，由系統自動判斷）"""
    actor = get_current_user_ctx()
    if not actor:
        return json_resp({"ok":False,"msg":"未登入"}), 401
    actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
    if role_rank(actor_role) < role_rank("super_admin"):
        return json_resp({"ok":False,"msg":"只有最高管理者可降級帳號"}), 403

    conn = get_db()
    try:
        target = conn.execute(
            "SELECT id, username, role FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if not target:
            return json_resp({"ok":False,"msg":"找不到帳號"}), 404
        if target["username"] == "root":
            return json_resp({"ok":False,"msg":"最高管理者帳號不可降級"}), 403
        from_role = target["role"]
        if from_role == "user":
            # 一般用戶 → 刪除
            audit("USER_DELETED_BY_ADMIN", get_client_ip(), user=actor["username"],
                  detail=f"user_id={user_id} demoted from user (delete)")
            conn.execute("DELETE FROM users WHERE id=?", (user_id,))
            conn.commit()
            return json_resp({"ok":True,"msg":"一般用戶已刪除"})
        # 管理者 → 一般用戶
        conn.execute("UPDATE users SET role='user', violation_count=0, updated_at=? WHERE id=?",
                     (datetime.now().isoformat(), user_id))
        conn.commit()
        audit("MANAGER_DEMOTED_BY_ADMIN", get_client_ip(), user=actor["username"],
              detail=f"user_id={user_id} manager→user")
        return json_resp({"ok":True,"msg":"已降級為一般用戶"})
    finally:
        conn.close()

# ── 違規計點（系統自動 or 超級管理者手動）─────────────────────────────────────
@app.route("/api/admin/users/<int:user_id>/violation", methods=["POST"])
@require_csrf
def admin_user_violation(user_id):
    """管理者可對一般用戶計點；超級管理者可對任何帳號計點（root 除外）"""
    actor = get_current_user_ctx()
    if not actor:
        return json_resp({"ok":False,"msg":"未登入"}), 401
    actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
    if role_rank(actor_role) < role_rank("manager"):
        return json_resp({"ok":False,"msg":"權限不足"}), 403

    try:
        data = request.get_json(force=True) or {}
    except:
        return json_resp({"ok":False,"msg":"Invalid JSON"}), 400

    if not isinstance(data, dict):
        return json_resp({"ok":False,"msg":"Invalid request"}), 400
    points = parse_positive_int(data.get("points", 1))
    if points is None:
        return json_resp({"ok":False,"msg":"違規點數格式錯誤"}), 400
    reason = str(data.get("reason", "手動計點"))[:200]
    triggered_by = "super_admin" if actor_role == "super_admin" else "manager"

    conn = get_db()
    try:
        target = conn.execute(
            "SELECT id, username, role FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if not target:
            return json_resp({"ok":False,"msg":"找不到帳號"}), 404
        if target["username"] == "root":
            return json_resp({"ok":False,"msg":"無法對最高管理者計點"}), 403
        if actor_role == "manager" and target["role"] != "user":
            return json_resp({"ok":False,"msg":"無權對此角色計點"}), 403

        action, msg, new_count = add_violation(
            user_id, target["username"], target["role"],
            points=points, reason=reason,
            triggered_by=triggered_by, actor_username=actor["username"]
        )
        audit("VIOLATION_ADDED", get_client_ip(), user=actor["username"],
              detail=f"target_id={user_id} action={action} points={points} reason={reason}")
        return json_resp({"ok":True,"msg":msg,"new_count":new_count})
    finally:
        conn.close()

def _serialize_appeal_row(r):
    if not r:
        return None
    return {
        "id": r["id"],
        "user_id": r["user_id"] if "user_id" in r.keys() else None,
        "username": r["username"],
        "latest_violation_id": r["latest_violation_id"],
        "violation_count_snapshot": r["violation_count_snapshot"],
        "penalty_points": r["penalty_points"],
        "pre_status": r["pre_status"] if ("pre_status" in r.keys()) else None,
        "pre_role": r["pre_role"] if ("pre_role" in r.keys()) else None,
        "reason": r["reason"],
        "status": r["status"],
        "reviewed_by": r["reviewed_by"],
        "reviewed_at": r["reviewed_at"],
        "review_note": r["review_note"],
        "created_at": r["created_at"],
    }

def _serialize_violation_row(r):
    if not r:
        return None
    return {
        "id": r["id"],
        "user_id": r["user_id"],
        "username": r["username"],
        "points": r["points"],
        "reason": r["reason"],
        "triggered_by": r["triggered_by"],
        "actor_username": r["actor_username"],
        "created_at": r["created_at"],
    }

@app.route("/api/appeals", methods=["GET"])
@require_csrf_safe
def violation_appeals_list():
    actor = get_current_user_ctx()
    if not actor:
        return json_resp({"ok":False,"msg":"未登入"}), 401

    conn = get_db()
    try:
        user_id = actor["id"]
        actor_username = actor["username"]
        latest_violation = get_latest_violation(conn, user_id)
        rows = conn.execute(
            "SELECT id, latest_violation_id, violation_count_snapshot, penalty_points, reason, status, reviewed_by, reviewed_at, review_note, created_at "
            "FROM violation_appeals WHERE user_id=? ORDER BY id DESC LIMIT 20",
            (user_id,)
        ).fetchall()

        now = datetime.now()
        latest_dt = parse_iso_to_datetime(latest_violation["created_at"]) if latest_violation else None
        remaining_seconds = 0
        latest_ok = False
        if latest_dt:
            elapsed = now - latest_dt
            if elapsed <= timedelta(hours=VIOLATION_APPEAL_WINDOW_HOURS):
                remaining_seconds = int((timedelta(hours=VIOLATION_APPEAL_WINDOW_HOURS) - elapsed).total_seconds())
                latest_ok = True

        pending_row = conn.execute(
            "SELECT 1 FROM violation_appeals WHERE user_id=? AND status='pending' LIMIT 1",
            (user_id,)
        ).fetchone()

        return json_resp({
            "ok": True,
            "latest_violation": _serialize_violation_row(latest_violation),
            "can_appeal": bool(latest_violation and latest_ok and not pending_row and actor_username != "root"),
            "remaining_seconds": remaining_seconds,
            "appeals": [_serialize_appeal_row(r) for r in rows],
        })
    finally:
        conn.close()

@app.route("/api/appeals", methods=["POST"])
@require_csrf
def submit_violation_appeal():
    actor = get_current_user_ctx()
    if not actor:
        return json_resp({"ok":False,"msg":"未登入"}), 401
    actor_username = actor["username"]
    if actor_username == "root":
        return json_resp({"ok":False,"msg":"最高管理者無需申覆"}), 403

    conn = get_db()
    try:
        user_id = actor["id"]
        latest_violation = get_latest_violation(conn, user_id)
        if not latest_violation:
            return json_resp({"ok":False,"msg":"沒有可申覆的違規紀錄"}), 400

        latest_dt = parse_iso_to_datetime(latest_violation["created_at"])
        if not latest_dt or datetime.now() - latest_dt > timedelta(hours=VIOLATION_APPEAL_WINDOW_HOURS):
            return json_resp({"ok":False,"msg":"超過申覆時限（24 小時）"}), 409

        existing = conn.execute(
            "SELECT 1 FROM violation_appeals WHERE user_id=? AND status='pending' LIMIT 1",
            (user_id,)
        ).fetchone()
        if existing:
            return json_resp({"ok":False,"msg":"已有待審中的申覆"}), 409

        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        reason = normalize_text(data.get("reason"))
        if not reason:
            return json_resp({"ok":False,"msg":"請填寫申覆原因"}), 400
        if len(reason) > 200:
            return json_resp({"ok":False,"msg":"申覆原因請控制在 200 字以內"}), 400

        user_row = conn.execute(
            "SELECT id, username, violation_count, status, role FROM users WHERE id=?",
            (user_id,)
        ).fetchone()
        if not user_row:
            return json_resp({"ok":False,"msg":"帳號不存在"}), 404

        conn.execute(
            "INSERT INTO violation_appeals "
            "(user_id, username, latest_violation_id, violation_count_snapshot, penalty_points, pre_status, pre_role, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                user_row["username"],
                latest_violation["id"],
                user_row["violation_count"],
                latest_violation["points"],
                user_row["status"],
                user_row["role"],
                reason,
                datetime.now().isoformat()
            )
        )
        conn.commit()
        audit("VIOLATION_APPEAL_SUBMITTED", get_client_ip(), user=actor_username,
              detail=f"user_id={user_id} latest_violation_id={latest_violation['id']}")
        return json_resp({"ok":True,"msg":"申覆已提交，等待超級管理員審核"})
    finally:
        conn.close()

@app.route("/api/admin/appeals", methods=["GET"])
@require_csrf_safe
def admin_violation_appeals():
    actor = get_current_user_ctx()
    if not actor:
        return json_resp({"ok":False,"msg":"未登入"}), 401
    actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
    if actor_role != "super_admin":
        return json_resp({"ok":False,"msg":"只有最高管理者可審核申覆"}), 403

    status = normalize_text(request.args.get("status","")) or "pending"
    page = parse_positive_int(request.args.get("page", 1))
    if page is None:
        return json_resp({"ok":False,"msg":"page 參數格式錯誤"}), 400
    limit = parse_positive_int(request.args.get("limit", 20), max_value=100)
    if limit is None:
        return json_resp({"ok":False,"msg":"limit 參數格式錯誤"}), 400
    offset = (page - 1) * limit

    conn = get_db()
    try:
        where = "WHERE 1=1"
        params = []
        if status in ("pending","approved","rejected"):
            where = "WHERE status=?"
            params.append(status)
        count_query = "SELECT COUNT(*) as c FROM violation_appeals " + where
        total = conn.execute(count_query, params).fetchone()["c"]
        rows = conn.execute(
            "SELECT id, user_id, username, latest_violation_id, violation_count_snapshot, penalty_points, pre_status, pre_role, reason, status, reviewed_by, reviewed_at, review_note, created_at "
            f"FROM violation_appeals {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()

        items = []
        for r in rows:
            items.append({
                "id": r["id"],
                "user_id": r["user_id"],
                "username": r["username"],
                "latest_violation_id": r["latest_violation_id"],
                "violation_count_snapshot": r["violation_count_snapshot"],
                "penalty_points": r["penalty_points"],
                "pre_status": r["pre_status"],
                "pre_role": r["pre_role"],
                "reason": r["reason"],
                "status": r["status"],
                "reviewed_by": r["reviewed_by"],
                "reviewed_at": r["reviewed_at"],
                "review_note": r["review_note"],
                "created_at": r["created_at"]
            })
        return json_resp({
            "ok": True,
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "status": status
        })
    finally:
        conn.close()

@app.route("/api/admin/appeals/<int:appeal_id>/review", methods=["POST"])
@require_csrf
def admin_violation_appeal_review(appeal_id):
    actor = get_current_user_ctx()
    if not actor:
        return json_resp({"ok":False,"msg":"未登入"}), 401
    actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
    if actor_role != "super_admin":
        return json_resp({"ok":False,"msg":"只有最高管理者可審核申覆"}), 403

    try:
        data = request.get_json(force=True)
    except Exception:
        return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
    if not isinstance(data, dict):
        return json_resp({"ok":False,"msg":"Invalid request"}), 400

    action = normalize_text(data.get("action")).lower()
    if action not in ("approve", "reject"):
        return json_resp({"ok":False,"msg":"action 必須是 approve 或 reject"}), 400
    note = normalize_text(data.get("note"))[:200]

    conn = get_db()
    try:
        appeal = conn.execute(
            "SELECT * FROM violation_appeals WHERE id=?", (appeal_id,)
        ).fetchone()
        if not appeal:
            return json_resp({"ok":False,"msg":"找不到申覆申請"}), 404
        if appeal["status"] != "pending":
            return json_resp({"ok":False,"msg":"申覆申請已處理"}), 409

        user_row = conn.execute(
            "SELECT id, username, status, role, violation_count FROM users WHERE id=?",
            (appeal["user_id"],)
        ).fetchone()
        if not user_row:
            return json_resp({"ok":False,"msg":"申覆帳號已不存在"}), 404

        final_status = "approved" if action == "approve" else "rejected"
        reviewed_at = datetime.now().isoformat()

        if action == "approve":
            penalty_points = appeal["penalty_points"] or 0
            restored_count = max(0, (appeal["violation_count_snapshot"] or 0) - (penalty_points or 0))
            # 申覆成立→恢復申覆前狀態
            conn.execute(
                "UPDATE users SET status=?, role=?, violation_count=?, blocked_until=CASE WHEN ?='active' THEN NULL ELSE blocked_until END WHERE id=?",
                (appeal["pre_status"], appeal["pre_role"], restored_count, appeal["pre_status"], appeal["user_id"])
            )
        else:
            # 若維持原處分，保留目前狀態，但可記錄檢閱備註
            pass

        conn.execute(
            "UPDATE violation_appeals SET status=?, reviewed_by=?, reviewed_at=?, review_note=? WHERE id=?",
            (final_status, actor["username"], reviewed_at, note, appeal_id)
        )
        conn.commit()
        audit("VIOLATION_APPEAL_REVIEWED", get_client_ip(), user=actor["username"],
              detail=f"appeal_id={appeal_id} action={action}")
        return json_resp({"ok":True,"msg": "已核准撤銷" if action == "approve" else "已維持原處分"})
    finally:
        conn.close()

# ── 查詢所有違規記錄（可驗證 integrity）──────────────────────────────────────
@app.route("/api/admin/violations", methods=["GET"])
@require_csrf_safe
def admin_violations():
    """列出所有用戶的最新違規狀態 + integrity 驗證結果"""
    actor = get_current_user_ctx()
    if not actor:
        return json_resp({"ok":False,"msg":"未登入"}), 401
    actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
    if role_rank(actor_role) < role_rank("manager"):
        return json_resp({"ok":False,"msg":"權限不足"}), 403

    page = parse_positive_int(request.args.get("page", 1))
    if page is None:
        return json_resp({"ok":False,"msg":"page 參數格式錯誤"}), 400
    limit = parse_positive_int(request.args.get("limit", 50), max_value=200)
    if limit is None:
        return json_resp({"ok":False,"msg":"limit 參數格式錯誤"}), 400
    offset = (page - 1) * limit
    username_filter = request.args.get("username", "").strip() or None

    conn = get_db()
    try:
        # 用戶清單（含 violation_count）
        base_query = "SELECT id, username, role, violation_count FROM users WHERE username<>'root' "
        if username_filter:
            base_query += "AND username=? "
            count_query = "SELECT COUNT(*) as c FROM users WHERE username<>'root' AND username=? "
            users_rows = conn.execute(base_query + "ORDER BY id ASC LIMIT ? OFFSET ?",
                                      (username_filter, limit, offset)).fetchall()
            total = conn.execute(count_query, (username_filter,)).fetchone()["c"]
        else:
            base_query += "ORDER BY id ASC LIMIT ? OFFSET ?"
            count_query = "SELECT COUNT(*) as c FROM users WHERE username<>'root' "
            users_rows = conn.execute(base_query, (limit, offset)).fetchall()
            total = conn.execute(count_query).fetchone()["c"]

        result = []
        for u in users_rows:
            uid = u["id"]
            uname = u["username"]
            ok, broken_at, details = verify_violation_integrity(uid)
            last = conn.execute(
                "SELECT entry_hash, created_at FROM secure_violations "
                "WHERE user_id=? ORDER BY id DESC LIMIT 1",
                (uid,)
            ).fetchone()
            result.append({
                "user_id":         uid,
                "username":        uname,
                "role":            u["role"],
                "violation_count": u["violation_count"],
                "integrity": {
                    "ok":         ok,
                    "broken_at":  broken_at,
                    "details":    details,
                    "latest_hash": last["entry_hash"][:24] + "..." if last else None,
                    "latest_ts":  last["created_at"] if last else None,
                }
            })

        # 整體 audit chain integrity（用於顯示）
        audit_ok, audit_broken, audit_details = verify_audit_integrity()

        return json_resp({
            "ok":      True,
            "entries": result,
            "total":   total,
            "page":    page,
            "limit":   limit,
            "users":   [{"username": u["username"], "violation_count": u["violation_count"]} for u in
                        conn.execute("SELECT username, violation_count FROM users WHERE username<>'root' ORDER BY id ASC").fetchall()],
            "integrity": {
                "ok":        audit_ok,
                "broken_at": audit_broken,
                "details":   audit_details,
            }
        })
    finally:
        conn.close()

# ── 重置單一用戶違規計次（super_admin only）────────────────────────────────────
@app.route("/api/admin/users/<int:user_id>/reset-violations", methods=["POST"])
@require_csrf
def admin_reset_violations(user_id):
    """超級管理者將用戶違規歸零"""
    actor = get_current_user_ctx()
    if not actor or actor["username"] != "root":
        return json_resp({"ok":False,"msg":"只有最高管理者可執行此操作"}), 403

    conn = get_db()
    try:
        target = conn.execute(
            "SELECT id, username, role, violation_count FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if not target:
            return json_resp({"ok":False,"msg":"找不到帳號"}), 404

        conn.execute("UPDATE users SET violation_count=0 WHERE id=?", (user_id,))
        conn.commit()
        audit("VIOLATIONS_RESET", get_client_ip(), user=actor["username"],
              detail=f"target_id={user_id} previous_count={target['violation_count']}")
        return json_resp({"ok":True,"msg":f"已重置 {target['username']} 的違規計次"})
    finally:
        conn.close()

# ── 審計日誌（manager + super_admin 皆可檢視）────────────────────────────────
@app.route("/api/admin/audit", methods=["GET"])
@require_csrf_safe
def admin_audit():
    actor = get_current_user_ctx()
    if not actor:
        return json_resp({"ok":False,"msg":"未登入"}), 401
    actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
    if role_rank(actor_role) < role_rank("manager"):
        return json_resp({"ok":False,"msg":"權限不足"}), 403

    page = parse_positive_int(request.args.get("page", 1))
    if page is None:
        return json_resp({"ok":False,"msg":"page 參數格式錯誤"}), 400
    limit = parse_positive_int(request.args.get("limit", 50), max_value=200)
    if limit is None:
        return json_resp({"ok":False,"msg":"limit 參數格式錯誤"}), 400
    offset = (page - 1) * limit

    # 讀取 secure_audit 表（hash chain）
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) as c FROM secure_audit").fetchone()["c"]
        rows  = conn.execute(
            "SELECT id, ts, action, ip, user, success, ua, detail, chain_hash "
            "FROM secure_audit ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()
        entries = []
        for r in rows:
            entries.append({
                "id":        r["id"],
                "ts":        r["ts"],
                "timestamp": r["ts"],
                "action":    r["action"],
                "actor":     r["user"],
                "ip":        r["ip"],
                "user":      r["user"],
                "success":   bool(r["success"]),
                "ua":        r["ua"],
                "detail":    r["detail"],
                "details":   r["detail"],
                "chain_hash": r["chain_hash"][:32] + "...",  # 只顯示前 32 字符
                "_chain_hash": r["chain_hash"],
            })

        # Legacy fallback：audit.log JSONL（避免 table 還沒同步時前端顯示空白）
        if total == 0 and not entries:
            if os.path.exists(AUDIT_LOG_PATH):
                with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
                    raw_lines = [ln.strip() for ln in f if ln.strip()]
                normalized_lines = list(reversed(raw_lines))
                page_lines = normalized_lines[offset:offset + limit]
                for idx, line in enumerate(page_lines):
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    entries.append({
                        "id":            total + idx + 1,
                        "ts":            obj.get("ts", ""),
                        "timestamp":     obj.get("ts", ""),
                        "action":        obj.get("action", ""),
                        "actor":         obj.get("user", ""),
                        "ip":            obj.get("ip", ""),
                        "user":          obj.get("user", ""),
                        "success":       bool(obj.get("success", False)),
                        "ua":            obj.get("ua", ""),
                        "detail":        obj.get("detail", ""),
                        "details":       obj.get("detail", ""),
                        "chain_hash":    "",
                        "_chain_hash":    "",
                        "source":        "legacy_log",
                    })
                total = len(raw_lines)

        # Integrity 驗證
        ok, broken_at, details = verify_audit_integrity()

        return json_resp({
            "ok": True,
            "entries": entries,
            "total": total,
            "page": page,
            "limit": limit,
            "integrity": {"ok": ok, "broken_at": broken_at, "details": details}
        })
    finally:
        conn.close()

# ── 系統參數（超級管理者 only）───────────────────────────────────────────────
@app.route("/api/admin/settings", methods=["GET","PUT"])
@require_csrf_safe
def admin_settings():
    actor = get_current_user_ctx()
    if not actor:
        return json_resp({"ok":False,"msg":"未登入"}), 401
    if actor["username"] != "root":
        return json_resp({"ok":False,"msg":"只有最高管理者可修改系統參數"}), 403

    SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")

    if request.method == "GET":
        defaults = {
            "allow_register": True,
            "require_email_verification": False,
            "max_login_failures": 3,
            "block_duration_minutes": 10,
            "session_ttl_hours": 4,
        }
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE) as f:
                current = json.load(f)
            defaults.update(current)
        return json_resp({"ok":True,"settings":defaults})

    # PUT
    try:
        data = request.get_json(force=True)
    except:
        return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
    if not isinstance(data, dict):
        return json_resp({"ok":False,"msg":"Invalid request"}), 400

    allowed_keys = {
        "allow_register": bool,
        "require_email_verification": bool,
        "max_login_failures": int,
        "block_duration_minutes": int,
        "session_ttl_hours": int,
    }
    settings = {}
    for key, val_type in allowed_keys.items():
        if key in data:
            try:
                settings[key] = val_type(data[key])
            except (ValueError, TypeError):
                return json_resp({"ok":False,"msg":f"{key} 格式錯誤"}), 400

    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)
    audit("SETTINGS_CHANGED", get_client_ip(), user=actor["username"],
          detail=str(settings))
    return json_resp({"ok":True,"msg":"系統參數已更新","settings":settings})

# ── 重啟服務器（超級管理者 only）─────────────────────────────────────────────
@app.route("/api/admin/restart", methods=["POST"])
@require_csrf
def admin_restart():
    actor = get_current_user_ctx()
    if not actor:
        return json_resp({"ok":False,"msg":"未登入"}), 401
    if actor["username"] != "root":
        return json_resp({"ok":False,"msg":"只有最高管理者可重啟服務器"}), 403

    audit("SERVER_RESTART", get_client_ip(), user=actor["username"], detail="initiated by admin")
    # 非同步重啟，避免來不及回應
    import threading, subprocess
    def restart_delayed():
        time.sleep(1.5)
        # Kill old server on port 5000
        subprocess.run(["fuser", "-k", "5000/tcp"],
                       cwd=BASE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)
        # Start new server
        subprocess.Popen(
            ["python3", os.path.join(BASE_DIR, "server.py")],
            cwd=BASE_DIR,
            stdout=open(SERVER_LOG_PATH, "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True
        )
    threading.Thread(target=restart_delayed, daemon=True).start()
    return json_resp({"ok":True,"msg":"服務器正在重啟，請稍後重新整理頁面"})

@app.route("/<path:invalid>", methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS"])
def catch_all(invalid):
    ip, ua = get_client_ip(), get_ua()
    audit("404_CATCHALL", ip, ua=ua, detail=f"path={invalid}")
    return json_resp({"ok":False,"msg":"Not found"}), 404

# ── Start ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    CERT_FILE = os.path.join(BASE_DIR, "cert.pem")
    KEY_FILE  = os.path.join(BASE_DIR, "key.pem")
    has_ssl = os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE)

    audit("SERVER_START", "0.0.0.0", detail="hackme_web server started — hardened edition")
    scheme = "https" if has_ssl else "http"
    print(f"\n🌐  hackme_web server running at {scheme}://localhost:5000")
    print(f"    Default credentials: root / root")
    print(f"    SSL: {'enabled' if has_ssl else 'disabled (add cert.pem + key.pem to enable)'}")
    print(f"    Audit log: database (secure_audit table + hash-chain)")
    print(f"    Security: Argon2id + timing-noise + account-enum-protection + CSRF + strict-headers\n")

    kwargs = {"host": "0.0.0.0", "port": 5000, "debug": False}
    if has_ssl:
        kwargs["ssl_context"] = (CERT_FILE, KEY_FILE)
    app.run(**kwargs)
