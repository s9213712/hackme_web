import hashlib
import secrets
from datetime import datetime, timedelta


TOKEN_PURPOSES = {"password_reset", "email_verify"}


def ensure_account_recovery_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS account_recovery_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            purpose TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            requested_ip TEXT,
            user_agent TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mail_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            kind TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_account_recovery_tokens_hash ON account_recovery_tokens(token_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_account_recovery_tokens_user ON account_recovery_tokens(user_id, purpose, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mail_outbox_kind ON mail_outbox(kind, created_at)")


def normalize_email(value):
    email = str(value or "").strip().lower()
    if not email or len(email) > 254 or "@" not in email:
        return ""
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain:
        return ""
    return email


def hash_recovery_token(token):
    return hashlib.sha256(f"account-recovery-v1:{token}".encode("utf-8")).hexdigest()


def create_recovery_token(conn, *, user_id, purpose, ip=None, user_agent=None, ttl_minutes=60):
    if purpose not in TOKEN_PURPOSES:
        raise ValueError("unsupported recovery token purpose")
    ensure_account_recovery_schema(conn)
    now = datetime.now()
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO account_recovery_tokens "
        "(user_id, purpose, token_hash, requested_ip, user_agent, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            int(user_id),
            purpose,
            hash_recovery_token(token),
            ip,
            (user_agent or "")[:300],
            now.isoformat(),
            (now + timedelta(minutes=max(1, int(ttl_minutes)))).isoformat(),
        ),
    )
    return token


def queue_mail(conn, *, recipient, subject, body, kind):
    ensure_account_recovery_schema(conn)
    conn.execute(
        "INSERT INTO mail_outbox (recipient, subject, body, kind, status, created_at) VALUES (?, ?, ?, ?, 'queued', ?)",
        (recipient, subject[:200], body, kind, datetime.now().isoformat()),
    )


def lookup_valid_token(conn, *, token, purpose):
    ensure_account_recovery_schema(conn)
    if purpose not in TOKEN_PURPOSES:
        return None
    token_hash = hash_recovery_token(token)
    row = conn.execute(
        """
        SELECT t.*, u.username, u.email
        FROM account_recovery_tokens t
        JOIN users u ON u.id=t.user_id
        WHERE t.token_hash=? AND t.purpose=? AND t.used_at IS NULL
        LIMIT 1
        """,
        (token_hash, purpose),
    ).fetchone()
    if not row:
        return None
    try:
        if datetime.now() > datetime.fromisoformat(row["expires_at"]):
            return None
    except Exception:
        return None
    return row


def mark_token_used(conn, token_id):
    conn.execute("UPDATE account_recovery_tokens SET used_at=? WHERE id=?", (datetime.now().isoformat(), int(token_id)))

