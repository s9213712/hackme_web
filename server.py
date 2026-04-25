#!/usr/bin/env python3
"""
Flask server for html_learning auth demo.
- SQLite encrypted database (Fernet symmetric encryption on password field)
- Default account: root / Admin@1234
- 3 failed attempts → IP blocked for 10 minutes
"""

import os
import sqlite3
import hashlib
import hmac
import secrets
import re
import time
import json
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory
from cryptography.fernet import Fernet

# ── Config ──────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DB_PATH     = os.path.join(BASE_DIR, "database.db")
PUBLIC_DIR  = os.path.join(BASE_DIR, "public")
BLOCK_FILE  = os.path.join(BASE_DIR, "blocked_ips.json")
FAIL_FILE   = os.path.join(BASE_DIR, "fail_log.json")
PORT        = 5000

# ── Encryption (Fernet = AES-128-CBC + HMAC) ─────────────────────────────────
def _get_key() -> bytes:
    key_file = os.path.join(BASE_DIR, ".key")
    if os.path.exists(key_file):
        return open(key_file, "rb").read()
    key = Fernet.generate_key()
    open(key_file, "wb").write(key)
    return key

fernet = Fernet(_get_key())

# ── Database helpers ──────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL   -- Fernet-encrypted
        )
    """)
    conn.commit()
    # Create default root/admin account if not exists
    cur = conn.execute("SELECT 1 FROM users WHERE username = ?", ("root",))
    if not cur.fetchone():
        pw_hash = _encrypt_pw("Admin@1234")
        conn.execute("INSERT INTO users (username, password) VALUES (?, ?)", ("root", pw_hash))
        conn.commit()
    conn.close()

def _encrypt_pw(pw: str) -> str:
    return fernet.encrypt(pw.encode()).decode()

def _decrypt_pw(encrypted: str) -> str:
    return fernet.decrypt(encrypted.encode()).decode()

# ── IP blocking helpers ───────────────────────────────────────────────────────
def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def is_ip_blocked(ip: str) -> bool:
    block_data = load_json(BLOCK_FILE)
    entry = block_data.get(ip)
    if not entry:
        return False
    if datetime.now() < datetime.fromisoformat(entry["until"]):
        return True
    # Expired — clean up
    del block_data[ip]
    save_json(BLOCK_FILE, block_data)
    return False

def block_ip(ip: str, minutes: int = 10):
    block_data = load_json(BLOCK_FILE)
    block_data[ip] = {"until": (datetime.now() + timedelta(minutes=minutes)).isoformat()}
    save_json(BLOCK_FILE, block_data)

def record_failed_login(ip: str) -> int:
    """Returns number of consecutive failures for this IP."""
    fail_data = load_json(FAIL_FILE)
    now = datetime.now()
    # Prune entries older than 10 minutes
    for k, v in list(fail_data.items()):
        if now > datetime.fromisoformat(v["until"]):
            del fail_data[k]
    record = fail_data.get(ip)
    if not record:
        count = 1
    else:
        count = record["count"] + 1
    fail_data[ip] = {
        "count": count,
        "until": (now + timedelta(minutes=10)).isoformat()
    }
    save_json(FAIL_FILE, fail_data)
    return count

def clear_failed_logins(ip: str):
    fail_data = load_json(FAIL_FILE)
    fail_data.pop(ip, None)
    save_json(FAIL_FILE, fail_data)

# ── Validation ────────────────────────────────────────────────────────────────
PASSWORD_RE = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]).{8,}$"
)

def validate_password(pw: str) -> tuple[bool, str]:
    if len(pw) < 8:
        return False, "密碼至少需要 8 個字元"
    if not re.search(r"[A-Z]", pw):
        return False, "密碼必須包含至少一個大寫字母"
    if not re.search(r"[a-z]", pw):
        return False, "密碼必須包含至少一個小寫字母"
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", pw):
        return False, "密碼必須包含至少一個符號"
    return True, "OK"

# ── Flask app ──────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=PUBLIC_DIR, static_url_path="")

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(PUBLIC_DIR, "index.html")

@app.route("/api/register", methods=["POST"])
def register():
    ip = request.remote_addr
    if is_ip_blocked(ip):
        return jsonify({"ok": False, "msg": "IP 已被鎖定，請稍後再試"}), 429

    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "msg": "Invalid request"}), 400

    username = (data.get("username") or "").strip()
    password = (data.get("password") or "")

    if not username:
        return jsonify({"ok": False, "msg": "帳號不可為空"}), 400
    if len(username) < 3:
        return jsonify({"ok": False, "msg": "帳號至少需要 3 個字元"}), 400

    ok, msg = validate_password(password)
    if not ok:
        return jsonify({"ok": False, "msg": msg}), 400

    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            return jsonify({"ok": False, "msg": "帳號已存在"}), 409

        encrypted_pw = _encrypt_pw(password)
        conn.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (username, encrypted_pw)
        )
        conn.commit()
        return jsonify({"ok": True, "msg": "註冊成功"})
    finally:
        conn.close()

@app.route("/api/login", methods=["POST"])
def login():
    ip = request.remote_addr
    if is_ip_blocked(ip):
        remaining = load_json(BLOCK_FILE).get(ip, {}).get("until", "")
        return jsonify({"ok": False, "msg": f"IP 已被鎖定，請於 {remaining[:16]} 後再試"}), 429

    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "msg": "Invalid request"}), 400

    username = (data.get("username") or "").strip()
    password = (data.get("password") or "")

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT password FROM users WHERE username = ?", (username,)
        ).fetchone()

        if not row or _decrypt_pw(row["password"]) != password:
            failures = record_failed_login(ip)
            if failures >= 3:
                block_ip(ip, minutes=10)
                return jsonify({"ok": False, "msg": "登入失敗 3 次，IP 已被鎖定 10 分鐘"}), 429
            return jsonify({"ok": False, "msg": f"登入失敗（剩 {3 - failures} 次嘗試）"}), 401

        clear_failed_logins(ip)
        return jsonify({"ok": True, "msg": "恭喜登入成功"})
    finally:
        conn.close()

@app.route("/api/logout", methods=["POST"])
def logout():
    # Stateless JWT-free server — logout is handled client-side.
    return jsonify({"ok": True, "msg": "已登出"})

# ── Init & run ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    print(f"\n🌐 html_learning server running at http://localhost:{PORT}")
    print(f"   Default credentials: root / Admin@1234")
    print(f"   (Password must be ≥8 chars with upper, lower & symbol)\n")
    app.run(host="0.0.0.0", port=PORT, debug=True)
