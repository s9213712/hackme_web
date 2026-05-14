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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_review_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            requested_identifier_hash TEXT NOT NULL,
            requested_ip TEXT,
            user_agent TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            reviewed_at TEXT,
            reviewed_by_user_id INTEGER,
            review_note TEXT,
            completed_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_account_recovery_tokens_hash ON account_recovery_tokens(token_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_account_recovery_tokens_user ON account_recovery_tokens(user_id, purpose, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mail_outbox_kind ON mail_outbox(kind, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_password_reset_reviews_status ON password_reset_review_requests(status, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_password_reset_reviews_user ON password_reset_review_requests(user_id, status)")


def normalize_email(value):
    email = str(value or "").strip().lower()
    if not email or len(email) > 254 or "@" not in email:
        return ""
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain:
        return ""
    return email


def hash_recovery_identifier(value):
    normalized = str(value or "").strip().lower()
    return hashlib.sha256(f"account-recovery-identifier-v1:{normalized}".encode("utf-8")).hexdigest()


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


def create_password_reset_review_request(conn, *, user_id, identifier, ip=None, user_agent=None):
    ensure_account_recovery_schema(conn)
    existing = conn.execute(
        """
        SELECT id FROM password_reset_review_requests
        WHERE user_id=? AND status='pending'
        ORDER BY id DESC LIMIT 1
        """,
        (int(user_id),),
    ).fetchone()
    if existing:
        return int(existing["id"]), False
    cur = conn.execute(
        """
        INSERT INTO password_reset_review_requests
        (user_id, requested_identifier_hash, requested_ip, user_agent, status, created_at)
        VALUES (?, ?, ?, ?, 'pending', ?)
        """,
        (
            int(user_id),
            hash_recovery_identifier(identifier),
            ip,
            (user_agent or "")[:300],
            datetime.now().isoformat(),
        ),
    )
    return int(cur.lastrowid), True


def list_password_reset_review_requests(conn, *, status="pending", limit=100):
    ensure_account_recovery_schema(conn)
    where = ""
    params = []
    if status and status != "all":
        where = "WHERE r.status=?"
        params.append(status)
    params.append(max(1, min(int(limit or 100), 200)))
    return conn.execute(
        f"""
        SELECT
            r.*,
            u.username AS target_username,
            u.role AS target_role,
            u.status AS target_status,
            reviewer.username AS reviewed_by_username
        FROM password_reset_review_requests r
        JOIN users u ON u.id=r.user_id
        LEFT JOIN users reviewer ON reviewer.id=r.reviewed_by_user_id
        {where}
        ORDER BY
            CASE r.status WHEN 'pending' THEN 0 ELSE 1 END,
            r.created_at DESC,
            r.id DESC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()


def get_password_reset_review_request(conn, request_id):
    ensure_account_recovery_schema(conn)
    return conn.execute(
        """
        SELECT
            r.*,
            u.username AS username,
            u.username AS target_username,
            u.role AS target_role,
            u.status AS target_status
        FROM password_reset_review_requests r
        JOIN users u ON u.id=r.user_id
        WHERE r.id=?
        LIMIT 1
        """,
        (int(request_id),),
    ).fetchone()


def mark_password_reset_review_request(conn, *, request_id, status, reviewer_user_id, note=""):
    if status not in {"approved", "rejected"}:
        raise ValueError("unsupported password reset review status")
    now = datetime.now().isoformat()
    conn.execute(
        """
        UPDATE password_reset_review_requests
        SET status=?, reviewed_at=?, reviewed_by_user_id=?, review_note=?, completed_at=?
        WHERE id=? AND status='pending'
        """,
        (status, now, int(reviewer_user_id), str(note or "")[:500], now, int(request_id)),
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
