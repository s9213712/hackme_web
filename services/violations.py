import hmac
import json
import re
from datetime import datetime, timedelta

MAX_VIOLATIONS = {"manager": 3, "user": 5}
NO_AUTO_PENALTY_USERS = {"admin"}
CHAT_WARNING_CATEGORY_WORDS = {
    "色情": [
        "色情", "性行為", "亂倫", "裸體", "裸照", "porn", "pornhub", "xvideos", "sex", "sexy",
        "erotic", "sexual", "adult", "pornography", "露骨", "pussy", "摳穴", "口交", "肛交", "做愛"
    ],
    "血腥": [
        "血腥", "暴力", "殺人", "刀", "槍", "肢解", "gore", "weapon", "knife", "gun", "shoot", "殘忍", "毆打"
    ],
    "自殺": [
        "自殺", "suicide", "想死", "死亡", "自殘", "我不想活", "結束生命", "hang", "自盡", "活著太累", "不想活", "結束自己"
    ],
    "辱罵": [
        "白癡", "智障", "fuck", "fuckyou", "fuck you", "shit", "幹你", "幹妳", "低能", "腦殘"
    ],
    "敏感資訊": [
        "密碼是", "password is", "passwd", "pwd="
    ],
}

_STATE = {
    "get_db": None,
    "get_system_settings": None,
    "audit": None,
    "get_client_ip": None,
    "chain_seed": None,
    "integrity_key": None,
}


def configure_violations_service(*, get_db, get_system_settings, audit, get_client_ip, chain_seed, integrity_key):
    _STATE.update({
        "get_db": get_db,
        "get_system_settings": get_system_settings,
        "audit": audit,
        "get_client_ip": get_client_ip,
        "chain_seed": chain_seed,
        "integrity_key": integrity_key,
    })


def _violation_chain_hash(prev_hash, entry_json):
    return hmac.new(_STATE["integrity_key"], (prev_hash + entry_json).encode(), "sha256").hexdigest()


def _get_chat_warning_words():
    settings = _STATE["get_system_settings"]() or {}
    raw_rules = settings.get("chat_filter_rules_json", "")
    if isinstance(raw_rules, str) and raw_rules.strip():
        try:
            payload = json.loads(raw_rules)
            if isinstance(payload, dict):
                parsed = {}
                for label, keywords in payload.items():
                    if not isinstance(label, str) or not isinstance(keywords, list):
                        continue
                    clean = [str(keyword).strip() for keyword in keywords if str(keyword).strip()]
                    if clean:
                        parsed[label.strip()] = clean
                if parsed:
                    return parsed
        except Exception:
            pass
    return {label: list(keywords) for label, keywords in CHAT_WARNING_CATEGORY_WORDS.items()}


def secure_add_violation(user_id, username, role, points, reason, triggered_by, actor_username, update_user_counter=True):
    ts = datetime.now().isoformat(timespec="milliseconds")
    entry = {
        "user_id": user_id, "username": username, "points": points,
        "reason": reason, "triggered_by": triggered_by,
        "actor_username": actor_username, "ts": ts,
    }
    entry_json = json.dumps(entry, ensure_ascii=False)

    conn = _STATE["get_db"]()
    try:
        conn.execute("BEGIN IMMEDIATE")
        prev_row = conn.execute(
            "SELECT entry_hash FROM secure_violations WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (user_id,)
        ).fetchone()
        prev_hash = prev_row["entry_hash"] if prev_row else _STATE["chain_seed"]
        entry_hash = _violation_chain_hash(prev_hash, entry_json)
        conn.execute(
            "INSERT INTO secure_violations (user_id, username, points, reason, triggered_by, actor_username, created_at, prev_hash, entry_hash) VALUES (?,?,?,?,?,?,?,?,?)",
            (user_id, username, points, reason, triggered_by, actor_username, ts, prev_hash, entry_hash)
        )
        if update_user_counter:
            row = conn.execute(
                "UPDATE users SET violation_count = violation_count + ? WHERE id = ? RETURNING violation_count",
                (points, user_id)
            ).fetchone()
            if not row:
                raise ValueError(f"user_id={user_id} not found")
            new_count = row["violation_count"]
        else:
            row = conn.execute(
                "SELECT violation_count FROM users WHERE id=?",
                (user_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"user_id={user_id} not found")
            new_count = row["violation_count"]
        conn.commit()
        return entry_hash, new_count
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def verify_violation_integrity(user_id):
    conn = _STATE["get_db"]()
    try:
        rows = conn.execute(
            "SELECT id, user_id, username, points, reason, triggered_by, actor_username, created_at, prev_hash, entry_hash FROM secure_violations WHERE user_id=? ORDER BY id ASC",
            (user_id,)
        ).fetchall()
        if not rows:
            return True, None, "no entries"

        prev_hash = _STATE["chain_seed"]
        for r in rows:
            recomputed = _violation_chain_hash(prev_hash, json.dumps({
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


def get_latest_violation(conn, user_id):
    return conn.execute(
        "SELECT id, user_id, username, points, reason, triggered_by, actor_username, created_at FROM secure_violations WHERE user_id=? ORDER BY id DESC LIMIT 1",
        (user_id,)
    ).fetchone()


def parse_iso_to_datetime(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(v)
    except Exception:
        return None


def check_and_apply_auto_violations(user_id, username, role, actor_username="system"):
    settings = _STATE["get_system_settings"]()
    triggered = False
    reason = None

    if settings.get("login_violation_enabled", True):
        threshold = settings.get("max_login_fails_for_violation", 5)
        conn = _STATE["get_db"]()
        try:
            since = (datetime.now() - timedelta(hours=1)).isoformat()
            fail_count = conn.execute(
                "SELECT COUNT(*) as c FROM security_events WHERE event_type='login_fail' AND target_user=? AND created_at>=?",
                (username, since)
            ).fetchone()["c"]
            if fail_count >= threshold:
                points = fail_count // threshold
                secure_add_violation(
                    user_id, username, role, points,
                    f"auto: 登入失敗 {fail_count} 次（閾值 {threshold}）",
                    "system", actor_username
                )
                triggered = True
                reason = f"登入失敗 {fail_count} 次 → +{points} 點"
        finally:
            conn.close()

    return triggered, reason, None


def add_violation(user_id, username, role, points=1, reason="手動計點", triggered_by="super_admin", actor_username="admin"):
    entry_hash, new_count = secure_add_violation(
        user_id, username, role, points, reason, triggered_by, actor_username
    )

    conn = _STATE["get_db"]()
    try:
        threshold = MAX_VIOLATIONS.get(role, 5)
        if username in NO_AUTO_PENALTY_USERS:
            _STATE["audit"]("VIOLATION_TEST_ACCOUNT_NO_PENALTY", _STATE["get_client_ip"](), user="system",
                            detail=f"user_id={user_id} username={username} count={new_count}/{threshold}")
            return "test_counted", f"測試帳號違規計點 +{points}（{new_count}/{threshold}），不自動封鎖或降級", new_count
        if new_count >= threshold:
            conn.execute(
                "UPDATE users SET status='inactive', violation_count=?, updated_at=? WHERE id=?",
                (new_count, datetime.now().isoformat(), user_id)
            )
            conn.commit()
            _STATE["audit"]("USER_SUSPENDED_BY_VIOLATION", _STATE["get_client_ip"](), user="system",
                            detail=f"user_id={user_id} violated={new_count} (secure_violations hash={entry_hash[:16]}...)")
            return "suspended", f"違規次數 {new_count}/{threshold}，帳號已暫停，請申覆", new_count
        return "counted", f"違規計點 +{points}（{new_count}/{threshold}）", new_count
    finally:
        conn.close()


def detect_chat_violation(text):
    if not isinstance(text, str):
        return False, None
    normalized = text.lower().strip()
    compact = re.sub(r"\s+", "", normalized)
    for label, keys in _get_chat_warning_words().items():
        for keyword in keys:
            if not keyword:
                continue
            kw = keyword.lower().strip()
            if kw in normalized or kw in compact:
                return True, label
    return False, None
