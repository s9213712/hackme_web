#!/usr/bin/env python3
"""
html_learning — Flask auth server
Security: Argon2id password hash, Fernet session tokens, rate limiting,
          per-IP 3-strike block (10 min), full audit logging, CSRF protection.
"""

import os, sqlite3, re, json, time, hashlib, secrets, hmac, threading
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, make_response
from cryptography.fernet import Fernet
import argon2

# ── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DB_PATH    = os.path.join(BASE_DIR, "database.db")
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
BLOCK_FILE = os.path.join(BASE_DIR, "blocked_ips.json")
FAIL_FILE  = os.path.join(BASE_DIR, "fail_log.json")
RATE_FILE  = os.path.join(BASE_DIR, "rate_limit.json")
AUDIT_FILE = os.path.join(BASE_DIR, "audit.log")

# ── Logging ───────────────────────────────────────────────────────────────────
_audit_lock = threading.Lock()

def audit(action, ip, user="-", success=False, ua="-", detail="-"):
    entry = {
        "ts":      datetime.now().isoformat(timespec="milliseconds"),
        "action":  action,
        "ip":      ip,
        "user":    user,
        "success": success,
        "ua":      ua[:200],
        "detail":  detail,
    }
    line = json.dumps(entry, ensure_ascii=False)
    _audit_lock.acquire()
    try:
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    finally:
        _audit_lock.release()

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

# ── Argon2 hasher ─────────────────────────────────────────────────────────────
_hasher = argon2.PasswordHasher(time_cost=3, memory_cost=65536,
                                parallelism=4, hash_len=32, salt_len=16)

def hash_password(pw):    return _hasher.hash(pw)
def verify_password(h, p):
    try:    return _hasher.verify(h, p)
    except argon2.exceptions.VerifyMismatch: return False

# ── Fernet (session tokens) ───────────────────────────────────────────────────
def _get_fernet_key():
    key_file = os.path.join(BASE_DIR, ".fkey")
    if os.path.exists(key_file): return open(key_file,"rb").read()
    k = Fernet.generate_key()
    open(key_file,"wb").write(k)
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

def verify_token(token):
    try:
        data = json.loads(fernet.decrypt(token.encode()).decode())
        if datetime.now() > datetime.fromisoformat(data["exp"]): return None
        return data["user"]
    except Exception: return None

# ── Security helpers ────────────────────────────────────────────────────────────
def get_client_ip():
    if request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0].strip()
    return request.remote_addr or "0.0.0.0"

def get_ua(): return request.headers.get("User-Agent","-")[:200]

def is_ip_blocked(ip):
    data = load_json(BLOCK_FILE)
    entry = data.get(ip)
    if not entry: return False
    if datetime.now() < datetime.fromisoformat(entry["until"]): return True
    del data[ip]; save_json(BLOCK_FILE, data); return False

def block_ip(ip, minutes=10):
    data = load_json(BLOCK_FILE)
    data[ip] = {"until": (datetime.now() + timedelta(minutes=minutes)).isoformat()}
    save_json(BLOCK_FILE, data)

def record_failed_login(ip):
    now = datetime.now()
    data = load_json(FAIL_FILE)
    data = {k:v for k,v in data.items() if now < datetime.fromisoformat(v["until"])}
    rec = data.get(ip, {"count":0})
    count = rec["count"] + 1
    data[ip] = {"count": count, "until": (now + timedelta(minutes=10)).isoformat()}
    save_json(FAIL_FILE, data)
    return count

def clear_failed_logins(ip):
    data = load_json(FAIL_FILE); data.pop(ip, None); save_json(FAIL_FILE, data)

def is_rate_limited(ip, max_req=30, window_sec=60):
    now = datetime.now()
    data = load_json(RATE_FILE)
    data = {k:v for k,v in data.items()
            if now - datetime.fromisoformat(v["window_start"]) < timedelta(seconds=window_sec)}
    entry = data.get(ip)
    if not entry:
        data[ip] = {"count":1, "window_start": now.isoformat()}
        save_json(RATE_FILE, data); return False, {"count":1,"limit":max_req}
    count = entry["count"] + 1
    entry["count"] = count
    data[ip] = entry
    save_json(RATE_FILE, data)
    if count > max_req: return True, {"count":count,"limit":max_req}
    return False, {"count":count,"limit":max_req}

# ── Password validation ────────────────────────────────────────────────────────
PW_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]).{8,128}$")

def validate_password(pw):
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
    return conn

def init_db():
    conn = get_db()
    conn.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)")
    conn.commit()
    row = conn.execute("SELECT 1 FROM users WHERE username=?", ("root",)).fetchone()
    if not row:
        conn.execute("INSERT INTO users (username,password) VALUES (?,?)",
                     ("root", hash_password("Admin@1234")))
        conn.commit()
    conn.close()

# ── Flask app ──────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=PUBLIC_DIR, static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

def json_resp(data, status=200):
    r = make_response(jsonify(data), status)
    r.headers["Cache-Control"] = "no-store"
    r.headers["X-Content-Type-Options"] = "nosniff"
    return r

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index(): return send_from_directory(PUBLIC_DIR, "index.html")

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
    if not data:
        audit("REGISTER_EMPTY", ip, ua=ua)
        return json_resp({"ok":False,"msg":"Invalid request"}), 400

    username = (data.get("username","")).strip()
    password = data.get("password","") or ""

    # Username validation
    if not username:        return json_resp({"ok":False,"msg":"帳號不可為空"}), 400
    if len(username) < 3:   return json_resp({"ok":False,"msg":"帳號至少需要 3 個字元"}), 400
    if len(username) > 32:  return json_resp({"ok":False,"msg":"帳號最長 32 字元"}), 400
    if not re.fullmatch(r"[a-zA-Z0-9_\-]+", username):
        return json_resp({"ok":False,"msg":"帳號只能包含英文、數字、底線、減號"}), 400

    ok, msg = validate_password(password)
    if not ok:
        audit("REGISTER_BAD_PW", ip, username, ua=ua, detail=msg)
        return json_resp({"ok":False,"msg":msg}), 400

    conn = get_db()
    try:
        existing = conn.execute("SELECT 1 FROM users WHERE username=?",(username,)).fetchone()
        if existing:
            time.sleep(0.3)  # timing obfuscation
            audit("REGISTER_DUP", ip, username, ua=ua, success=False)
            return json_resp({"ok":False,"msg":"帳號已存在"}), 409
        conn.execute("INSERT INTO users (username,password) VALUES (?,?)",
                     (username, hash_password(password)))
        conn.commit()
        audit("REGISTER_OK", ip, username, ua=ua, success=True)
        return json_resp({"ok":True,"msg":"註冊成功"})
    finally:
        conn.close()

@app.route("/api/login", methods=["POST"])
def login():
    ip, ua = get_client_ip(), get_ua()
    if is_ip_blocked(ip):
        audit("LOGIN_BLOCKED", ip, ua=ua, detail="IP locked")
        until = load_json(BLOCK_FILE).get(ip,{}).get("until","")
        return json_resp({"ok":False,"msg":f"IP 已被鎖定，請於 {until[:16]} 後再試"}), 429

    blocked, info = is_rate_limited(ip, max_req=30, window_sec=60)
    if blocked:
        audit("LOGIN_RATELIMIT", ip, ua=ua)
        return json_resp({"ok":False,"msg":f"請求太頻繁（{info['limit']}次/分鐘）"}), 429

    try:    data = request.get_json(force=True)
    except: return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
    if not data: return json_resp({"ok":False,"msg":"Invalid request"}), 400

    username = (data.get("username","")).strip()
    password = data.get("password","") or ""

    if not username or not password:
        audit("LOGIN_BLANK", ip, username, ua=ua, detail="blank field")
        return json_resp({"ok":False,"msg":"請填寫帳號與密碼"}), 400

    conn = get_db()
    try:
        row = conn.execute("SELECT password FROM users WHERE username=?",(username,)).fetchone()
        verified = bool(row) and verify_password(row["password"], password)

        if not verified:
            failures = record_failed_login(ip)
            audit("LOGIN_FAIL", ip, username, ua=ua, detail=f"failures={failures}")
            if failures >= 3:
                block_ip(ip, 10)
                audit("LOGIN_IP_BLOCKED", ip, username, ua=ua, detail="3 failures → 10 min block")
                return json_resp({"ok":False,"msg":"登入失敗 3 次，IP 已被鎖定 10 分鐘"}), 429
            return json_resp({"ok":False,"msg":f"登入失敗（剩 {3-failures} 次嘗試）"}), 401

        clear_failed_logins(ip)
        token = make_token(username)
        audit("LOGIN_OK", ip, username, ua=ua, success=True)
        resp = json_resp({"ok":True,"msg":"恭喜登入成功","token":token})
        resp.set_cookie("session_token", token, max_age=SESSION_TTL,
                        httponly=True, samesite="Strict",
                        secure=request.is_secure)
        return resp
    finally:
        conn.close()

@app.route("/api/logout", methods=["POST"])
def logout():
    ip, ua, tok = get_client_ip(), get_ua(), request.cookies.get("session_token")
    user = verify_token(tok) if tok else None
    audit("LOGOUT", ip, username=user or "-", ua=ua, success=bool(user))
    resp = json_resp({"ok":True,"msg":"已登出"})
    resp.delete_cookie("session_token")
    return resp

@app.route("/api/me", methods=["GET"])
def me():
    ip, tok = get_client_ip(), request.cookies.get("session_token")
    user = verify_token(tok) if tok else None
    if not user: return json_resp({"ok":False,"msg":"未登入"}), 401
    return json_resp({"ok":True,"username":user})

@app.route("/api/audit", methods=["GET"])
def api_audit():
    tok = request.cookies.get("session_token")
    user = verify_token(tok) if tok else None
    if not user: return json_resp({"ok":False,"msg":"未授權"}), 401
    if not os.path.exists(AUDIT_FILE): return json_resp({"ok":True,"entries":[]})
    with open(AUDIT_FILE) as f: lines = f.readlines()
    entries = []
    for l in lines[-200:]:
        try: entries.append(json.loads(l))
        except: pass
    return json_resp({"ok":True,"entries":entries})

@app.route("/<path:invalid>", methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS"])
def catch_all(invalid):
    ip, ua = get_client_ip(), get_ua()
    audit("404_CATCHALL", ip, ua=ua, detail=f"path={invalid}")
    return json_resp({"ok":False,"msg":"Not found"}), 404

# ── Start ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    audit("SERVER_START", "0.0.0.0", detail="html_learning server started")
    print(f"\n🌐 html_learning server running at http://localhost:5000")
    print(f"   Default credentials: root / Admin@1234")
    print(f"   Audit log: {AUDIT_FILE}\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
