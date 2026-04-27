import base64
import hashlib
import html
import os
import random
import secrets
from datetime import datetime, timedelta

CAPTCHA_MODES = {"none", "math", "image", "turnstile"}
DEFAULT_CAPTCHA_TTL_SECONDS = 300


def normalize_captcha_mode(mode):
    mode = str(mode or "none").strip().lower()
    return mode if mode in CAPTCHA_MODES else "none"


def captcha_is_required(mode):
    return normalize_captcha_mode(mode) != "none"


def ensure_captcha_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS captcha_challenges (
            id           TEXT PRIMARY KEY,
            mode         TEXT NOT NULL,
            answer_hash  TEXT NOT NULL,
            ip_hash      TEXT,
            expires_at   TEXT NOT NULL,
            used_at      TEXT,
            created_at   TEXT NOT NULL
        )
        """
    )


def _hash_ip(ip):
    if not ip:
        return ""
    return hashlib.sha256(str(ip).encode("utf-8")).hexdigest()


def _hash_answer(challenge_id, answer):
    normalized = str(answer or "").strip().lower()
    return hashlib.sha256(f"{challenge_id}:{normalized}".encode("utf-8")).hexdigest()


def _ttl_seconds(value):
    try:
        ttl = int(value)
    except Exception:
        ttl = DEFAULT_CAPTCHA_TTL_SECONDS
    return max(60, min(ttl, 3600))


def _new_math_problem():
    left = random.randint(2, 18)
    right = random.randint(2, 12)
    op = random.choice(("+", "-"))
    if op == "-" and left < right:
        left, right = right, left
    answer = left + right if op == "+" else left - right
    return f"{left} {op} {right} = ?", str(answer)


def _svg_data_uri(question):
    safe_question = html.escape(question)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="220" height="72" viewBox="0 0 220 72">
<rect width="220" height="72" rx="10" fill="#111827"/>
<path d="M18 52 C48 8, 84 66, 116 22 S177 58, 204 18" stroke="#38bdf8" stroke-width="3" fill="none" opacity=".7"/>
<circle cx="42" cy="18" r="4" fill="#fbbf24" opacity=".8"/>
<circle cx="174" cy="50" r="5" fill="#34d399" opacity=".8"/>
<text x="50%" y="48%" text-anchor="middle" dominant-baseline="middle" fill="#f8fafc" font-family="monospace" font-size="28" font-weight="700">{safe_question}</text>
</svg>"""
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def create_captcha_challenge(conn, *, mode="none", ttl_seconds=DEFAULT_CAPTCHA_TTL_SECONDS, ip=""):
    mode = normalize_captcha_mode(mode)
    if mode == "none":
        return {"required": False, "mode": "none"}
    if mode == "turnstile":
        return {"required": True, "mode": "turnstile"}

    ensure_captcha_schema(conn)
    question, answer = _new_math_problem()
    challenge_id = secrets.token_urlsafe(18)
    now = datetime.now()
    expires_at = (now + timedelta(seconds=_ttl_seconds(ttl_seconds))).isoformat()
    conn.execute(
        "INSERT INTO captcha_challenges (id, mode, answer_hash, ip_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (challenge_id, mode, _hash_answer(challenge_id, answer), _hash_ip(ip), expires_at, now.isoformat()),
    )
    payload = {
        "required": True,
        "mode": mode,
        "captcha_id": challenge_id,
        "question": question,
        "expires_at": expires_at,
    }
    if mode == "image":
        payload["image_data_uri"] = _svg_data_uri(question)
    return payload


def verify_captcha_response(conn, settings, data, *, ip=""):
    mode = normalize_captcha_mode((settings or {}).get("captcha_mode"))
    if mode == "none":
        return True, ""
    if not isinstance(data, dict):
        return False, "驗證資料格式錯誤"
    if mode == "turnstile":
        token = str(data.get("captcha_turnstile_token") or "").strip()
        if not token:
            return False, "請完成 Turnstile 驗證"
        if not os.environ.get("TURNSTILE_SECRET_KEY"):
            return False, "Turnstile 尚未設定服務端金鑰，請改用 math/image 或設定 TURNSTILE_SECRET_KEY"
        return False, "Turnstile 服務端驗證尚未啟用，請先改用 math/image"

    challenge_id = str(data.get("captcha_id") or "").strip()
    answer = str(data.get("captcha_answer") or "").strip()
    if not challenge_id or not answer:
        return False, "請完成驗證碼"
    ensure_captcha_schema(conn)
    row = conn.execute(
        "SELECT id, mode, answer_hash, expires_at, used_at FROM captcha_challenges WHERE id=?",
        (challenge_id,),
    ).fetchone()
    if not row or row["mode"] != mode:
        return False, "驗證碼已失效，請重新取得"
    if row["used_at"]:
        return False, "驗證碼已使用，請重新取得"
    try:
        expires_at = datetime.fromisoformat(row["expires_at"])
    except Exception:
        return False, "驗證碼狀態異常，請重新取得"
    if expires_at < datetime.now():
        return False, "驗證碼已過期，請重新取得"
    if _hash_answer(challenge_id, answer) != row["answer_hash"]:
        return False, "驗證碼錯誤"
    conn.execute("UPDATE captcha_challenges SET used_at=? WHERE id=?", (datetime.now().isoformat(), challenge_id))
    return True, ""
