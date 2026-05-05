import hashlib
import json
import re
import secrets
import uuid
from datetime import datetime, timedelta

from services.cloud_drive import is_e2ee_file
from services.points_chain import DISPLAY_CURRENCY

try:
    from argon2.low_level import Type as Argon2Type
    from argon2.low_level import hash_secret_raw as argon2_hash_secret_raw
except Exception:  # pragma: no cover - optional dependency
    Argon2Type = None
    argon2_hash_secret_raw = None


VIDEO_VISIBILITIES = {"public", "unlisted", "private"}
VIDEO_STATUSES = {"processing", "ready", "blocked"}
VIDEO_TITLE_MAX = 120
VIDEO_DESCRIPTION_MAX = 2000
VIDEO_COMMENT_MAX = 1000
VIDEO_VIEW_DEDUP_HOURS = 6
VIDEO_VIEW_MIN_SECONDS = 5
VIDEO_TIP_MIN_POINTS = 1
VIDEO_TIP_MAX_POINTS = 1_000_000
VIDEO_SHARE_PASSWORD_ITERATIONS = 120_000
MAX_VIDEO_SHARE_PASSWORD_LENGTH = 128
VIDEO_SHARE_PASSWORD_MAX_FAILURES = 5
VIDEO_SHARE_PASSWORD_LOCK_MINUTES = 15
VIDEO_SHARE_MAX_VIEWS_LIMIT = 1_000_000
VIDEO_SHARE_WRAP_ALGORITHM = "AES-GCM"
VIDEO_SHARE_WRAP_VERSION = 1
_VIDEO_SHARE_UNSET = object()
UNSAFE_COMMENT_RE = re.compile(r"(<\s*script\b|on[a-z]+\s*=|javascript\s*:)", re.IGNORECASE)
VIDEO_FILENAME_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm", ".ogv", ".avi", ".mkv"}
AUDIO_FILENAME_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".weba", ".opus", ".oga", ".ogg"}
MEDIA_FILENAME_EXTENSIONS = VIDEO_FILENAME_EXTENSIONS | AUDIO_FILENAME_EXTENSIONS


def utc_now():
    return datetime.utcnow().replace(microsecond=0).isoformat()


def _actor_value(actor, key, default=None):
    if not actor:
        return default
    try:
        return actor[key]
    except Exception:
        return actor.get(key, default) if hasattr(actor, "get") else default


def _role(actor):
    if not actor:
        return "anonymous"
    if _actor_value(actor, "username") == "root":
        return "super_admin"
    return _actor_value(actor, "role", "user") or "user"


def _role_rank(role):
    return {"anonymous": -1, "user": 0, "manager": 1, "admin": 1, "super_admin": 2}.get(role or "user", 0)


def is_manager_or_root(actor):
    return _role_rank(_role(actor)) >= _role_rank("manager")


def _as_dict(row):
    return dict(row) if row is not None else None


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _json(data):
    return json.dumps(data or {}, ensure_ascii=False, sort_keys=True)


def _sha256_text(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _table_columns(conn, table):
    try:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


def _ensure_columns(conn, table, definitions):
    columns = _table_columns(conn, table)
    for column, ddl in definitions.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _share_row_value(row, key, default=None):
    if not row:
        return default
    candidates = [f"share_{key}", key]
    for candidate in candidates:
        try:
            return row[candidate]
        except Exception:
            continue
    return default


def ensure_video_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_uuid TEXT NOT NULL UNIQUE,
            owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            cloud_file_id TEXT NOT NULL UNIQUE REFERENCES uploaded_files(id) ON DELETE CASCADE,
            cover_file_id TEXT REFERENCES uploaded_files(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            visibility TEXT NOT NULL DEFAULT 'public',
            status TEXT NOT NULL DEFAULT 'ready',
            duration_seconds INTEGER NOT NULL DEFAULT 0,
            view_count INTEGER NOT NULL DEFAULT 0,
            like_count INTEGER NOT NULL DEFAULT 0,
            coin_total INTEGER NOT NULL DEFAULT 0,
            comment_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (visibility IN ('public', 'unlisted', 'private')),
            CHECK (status IN ('processing', 'ready', 'blocked'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS video_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
            viewer_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            ip_hash TEXT,
            watch_seconds INTEGER NOT NULL DEFAULT 0,
            completed INTEGER NOT NULL DEFAULT 0,
            counted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS video_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            UNIQUE(video_id, user_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS video_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            parent_id INTEGER REFERENCES video_comments(id) ON DELETE CASCADE,
            like_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS video_tips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
            from_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            to_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            amount_points INTEGER NOT NULL,
            fee_points INTEGER NOT NULL DEFAULT 0,
            net_points INTEGER NOT NULL DEFAULT 0,
            fee_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            ledger_debit_uuid TEXT,
            ledger_credit_uuid TEXT,
            ledger_fee_uuid TEXT,
            idempotency_key TEXT UNIQUE,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS video_share_links (
            id TEXT PRIMARY KEY,
            video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
            owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            password_required INTEGER NOT NULL DEFAULT 0,
            password_hash TEXT,
            wrapped_file_key_envelope TEXT,
            expires_at TEXT,
            max_views INTEGER NOT NULL DEFAULT 0,
            failed_password_attempts INTEGER NOT NULL DEFAULT 0,
            password_locked_until TEXT,
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            access_count INTEGER NOT NULL DEFAULT 0,
            last_accessed_at TEXT,
            revoked_at TEXT
        )
        """
    )
    _ensure_columns(conn, "video_views", {"counted": "INTEGER NOT NULL DEFAULT 0"})
    _ensure_columns(conn, "videos", {"cover_file_id": "TEXT"})
    _ensure_columns(conn, "video_tips", {
        "net_points": "INTEGER NOT NULL DEFAULT 0",
        "fee_user_id": "INTEGER",
        "ledger_fee_uuid": "TEXT",
        "idempotency_key": "TEXT",
    })
    _ensure_columns(conn, "video_share_links", {
        "password_required": "INTEGER NOT NULL DEFAULT 0",
        "password_hash": "TEXT",
        "wrapped_file_key_envelope": "TEXT",
        "expires_at": "TEXT",
        "max_views": "INTEGER NOT NULL DEFAULT 0",
        "failed_password_attempts": "INTEGER NOT NULL DEFAULT 0",
        "password_locked_until": "TEXT",
        "access_count": "INTEGER NOT NULL DEFAULT 0",
        "last_accessed_at": "TEXT",
        "revoked_at": "TEXT",
    })
    conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_owner ON videos(owner_user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_visibility ON videos(visibility, status, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_video_views_video_created ON video_views(video_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_video_comments_video_created ON video_comments(video_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_video_tips_video_created ON video_tips(video_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_video_share_links_video_created ON video_share_links(video_id, created_at)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_video_tips_idempotency ON video_tips(idempotency_key) WHERE idempotency_key IS NOT NULL")


def serialize_video(row, *, actor=None, liked=False):
    data = _as_dict(row)
    if not data:
        return None
    for key in ("id", "owner_user_id", "duration_seconds", "view_count", "like_count", "coin_total", "comment_count"):
        data[key] = _safe_int(data.get(key), 0)
    data["liked_by_me"] = bool(liked)
    data["can_edit"] = bool(actor and (_safe_int(_actor_value(actor, "id")) == data["owner_user_id"] or is_manager_or_root(actor)))
    data["stream_url"] = f"/api/videos/{data['id']}/stream"
    data["playback_url"] = f"/api/videos/{data['id']}/playback"
    data["stream_status_url"] = f"/api/media/{data['cloud_file_id']}/stream-status"
    data["prepare_stream_url"] = f"/api/media/{data['cloud_file_id']}/prepare-stream" if data["can_edit"] else ""
    data["cover_url"] = f"/api/videos/{data['id']}/cover" if data.get("cover_file_id") else ""
    data["media_type"] = _cloud_file_media_type(data)
    return data


def _video_share_url(token):
    return f"/shared/videos/{token}" if token else ""


def _hash_share_token(token):
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _hash_video_share_password(password):
    password = str(password or "")
    if len(password) > MAX_VIDEO_SHARE_PASSWORD_LENGTH:
        raise ValueError("影音分享密碼太長")
    salt = secrets.token_urlsafe(16)
    if argon2_hash_secret_raw and Argon2Type is not None:
        time_cost = 3
        memory_cost = 65536
        parallelism = 4
        digest = argon2_hash_secret_raw(
            password.encode("utf-8"),
            salt.encode("utf-8"),
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=32,
            type=Argon2Type.ID,
        ).hex()
        return f"argon2id${time_cost}${memory_cost}${parallelism}${salt}${digest}"
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        VIDEO_SHARE_PASSWORD_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${VIDEO_SHARE_PASSWORD_ITERATIONS}${salt}${digest}"


def _verify_video_share_password(password, stored_hash):
    parts = str(stored_hash or "").split("$")
    if len(parts) == 4 and parts[0] == "pbkdf2_sha256":
        try:
            iterations = int(parts[1])
        except Exception:
            return False
        salt = parts[2]
        expected = parts[3]
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            str(password or "").encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        ).hex()
        return secrets.compare_digest(actual, expected)
    if len(parts) == 6 and parts[0] == "argon2id" and argon2_hash_secret_raw and Argon2Type is not None:
        try:
            time_cost = int(parts[1])
            memory_cost = int(parts[2])
            parallelism = int(parts[3])
        except Exception:
            return False
        salt = parts[4]
        expected = parts[5]
        actual = argon2_hash_secret_raw(
            str(password or "").encode("utf-8"),
            salt.encode("utf-8"),
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=32,
            type=Argon2Type.ID,
        ).hex()
        return secrets.compare_digest(actual, expected)
    return False


def _normalized_share_wrap_envelope(value):
    if value in (None, "", {}):
        return ""
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except Exception as exc:
            raise ValueError("分享金鑰封裝格式不正確") from exc
    elif isinstance(value, dict):
        payload = dict(value)
    else:
        raise ValueError("分享金鑰封裝格式不正確")
    if str(payload.get("alg") or "") != VIDEO_SHARE_WRAP_ALGORITHM:
        raise ValueError("分享金鑰封裝演算法不支援")
    if int(payload.get("v") or 0) != VIDEO_SHARE_WRAP_VERSION:
        raise ValueError("分享金鑰封裝版本不支援")
    nonce = str(payload.get("nonce") or "").strip()
    ciphertext = str(payload.get("ciphertext") or "").strip()
    if not nonce or not ciphertext:
        raise ValueError("分享金鑰封裝缺少必要欄位")
    normalized = {
        "alg": VIDEO_SHARE_WRAP_ALGORITHM,
        "v": VIDEO_SHARE_WRAP_VERSION,
        "nonce": nonce,
        "ciphertext": ciphertext,
    }
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)


def _normalize_video_share_expiry(value):
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        expires_at = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if expires_at.tzinfo is not None:
            expires_at = expires_at.astimezone().replace(tzinfo=None)
    except Exception as exc:
        raise ValueError("分享到期時間格式不正確") from exc
    if expires_at <= datetime.utcnow():
        raise ValueError("分享到期時間必須晚於現在")
    return expires_at.replace(microsecond=0).isoformat()


def _normalize_video_share_max_views(value):
    if value in (None, "", 0, "0"):
        return 0
    try:
        count = int(value)
    except Exception as exc:
        raise ValueError("最大觀看次數必須是整數") from exc
    if count < 0 or count > VIDEO_SHARE_MAX_VIEWS_LIMIT:
        raise ValueError(f"最大觀看次數必須是 0-{VIDEO_SHARE_MAX_VIEWS_LIMIT}")
    return count


def _video_share_is_expired(row):
    expires_at = str(_share_row_value(row, "expires_at", "") or "").strip()
    return bool(expires_at and expires_at <= utc_now())


def _video_share_password_is_locked(row):
    locked_until = str(_share_row_value(row, "password_locked_until", "") or "").strip()
    return bool(locked_until and locked_until > utc_now())


def _record_video_share_password_failure(conn, row):
    attempts = int(_share_row_value(row, "failed_password_attempts", 0) or 0) + 1
    locked_until = _share_row_value(row, "password_locked_until")
    if attempts >= VIDEO_SHARE_PASSWORD_MAX_FAILURES:
        locked_until = (datetime.utcnow() + timedelta(minutes=VIDEO_SHARE_PASSWORD_LOCK_MINUTES)).replace(microsecond=0).isoformat()
        attempts = 0
    conn.execute(
        """
        UPDATE video_share_links
        SET failed_password_attempts=?, password_locked_until=?
        WHERE id=?
        """,
        (attempts, locked_until, _share_row_value(row, "id")),
    )


def _clear_video_share_password_failures(conn, link_id):
    conn.execute(
        """
        UPDATE video_share_links
        SET failed_password_attempts=0, password_locked_until=NULL
        WHERE id=?
        """,
        (str(link_id),),
    )


def revoke_video_share_link(conn, *, actor, video_id):
    ensure_video_schema(conn)
    video = conn.execute("SELECT * FROM videos WHERE id=?", (int(video_id),)).fetchone()
    if not video or not actor:
        raise ValueError("找不到影音")
    actor_id = int(_actor_value(actor, "id") or 0)
    if int(video["owner_user_id"]) != actor_id and not is_manager_or_root(actor):
        raise ValueError("找不到影音")
    now = utc_now()
    conn.execute(
        """
        UPDATE video_share_links
        SET revoked_at=?
        WHERE video_id=? AND revoked_at IS NULL
        """,
        (now, int(video_id)),
    )


def _video_share_password_required(row):
    if not row:
        return False
    value = _share_row_value(row, "password_required")
    if value is not None:
        return bool(int(value or 0))
    return bool(str(_share_row_value(row, "password_hash") or ""))


def _video_share_link_payload(row):
    if not row:
        return None
    token = _share_row_value(row, "token")
    return {
        "id": _share_row_value(row, "id"),
        "video_id": int(_share_row_value(row, "video_id", 0) or 0),
        "created_at": _share_row_value(row, "created_at"),
        "access_count": int(_share_row_value(row, "access_count", 0) or 0),
        "last_accessed_at": _share_row_value(row, "last_accessed_at"),
        "expires_at": _share_row_value(row, "expires_at", "") or "",
        "max_views": int(_share_row_value(row, "max_views", 0) or 0),
        "url": _video_share_url(token),
        "password_required": _video_share_password_required(row),
        "requires_fragment_key": bool(str(_share_row_value(row, "wrapped_file_key_envelope", "") or "").strip()),
    }


def _active_video_share_link(conn, video_id):
    ensure_video_schema(conn)
    return conn.execute(
        """
        SELECT * FROM video_share_links
        WHERE video_id=? AND revoked_at IS NULL
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (int(video_id),),
    ).fetchone()


def _apply_video_share_password(conn, link_id, *, password=_VIDEO_SHARE_UNSET):
    if password is _VIDEO_SHARE_UNSET or password is None:
        return None
    password = str(password or "")
    if not password:
        conn.execute(
            """
            UPDATE video_share_links
            SET password_required=0, password_hash=NULL, failed_password_attempts=0, password_locked_until=NULL
            WHERE id=?
            """,
            (link_id,),
        )
        return None
    try:
        password_hash = _hash_video_share_password(password)
    except ValueError as exc:
        return str(exc)
    conn.execute(
        """
        UPDATE video_share_links
        SET password_required=1, password_hash=?, failed_password_attempts=0, password_locked_until=NULL
        WHERE id=?
        """,
        (password_hash, link_id),
    )
    return None


def ensure_video_share_link(
    conn,
    *,
    actor,
    video_id,
    password=_VIDEO_SHARE_UNSET,
    wrapped_file_key_envelope=_VIDEO_SHARE_UNSET,
    expires_at=_VIDEO_SHARE_UNSET,
    max_views=_VIDEO_SHARE_UNSET,
    regenerate=False,
):
    ensure_video_schema(conn)
    video = conn.execute("SELECT * FROM videos WHERE id=?", (int(video_id),)).fetchone()
    if not video or int(video["owner_user_id"]) != int(_actor_value(actor, "id")):
        return None, "找不到影音"
    normalized_envelope = None if wrapped_file_key_envelope in (_VIDEO_SHARE_UNSET, None) else _normalized_share_wrap_envelope(wrapped_file_key_envelope)
    normalized_expires_at = None if expires_at in (_VIDEO_SHARE_UNSET, None) else _normalize_video_share_expiry(expires_at)
    normalized_max_views = None if max_views in (_VIDEO_SHARE_UNSET, None) else _normalize_video_share_max_views(max_views)
    is_e2ee_share = is_e2ee_file(_cloud_file_row(conn, video["cloud_file_id"])) and video["visibility"] == "unlisted"
    if is_e2ee_share and normalized_envelope == "":
        return None, "E2EE 持連結可看影音必須建立瀏覽器端分享授權"
    existing = _active_video_share_link(conn, video_id)
    if existing and not regenerate and normalized_envelope is None:
        msg = _apply_video_share_password(conn, existing["id"], password=password)
        if msg:
            return None, msg
        updates = []
        params = []
        if normalized_expires_at is not None:
            updates.append("expires_at=?")
            params.append(normalized_expires_at or None)
        if normalized_max_views is not None:
            updates.append("max_views=?")
            params.append(normalized_max_views)
        if updates:
            conn.execute(
                f"""
                UPDATE video_share_links
                SET {", ".join(updates)}
                WHERE id=?
                """,
                (*params, existing["id"]),
            )
        existing = conn.execute("SELECT * FROM video_share_links WHERE id=?", (existing["id"],)).fetchone()
        return _video_share_link_payload(existing), None
    if existing and regenerate and is_e2ee_share and normalized_envelope is None:
        return None, "E2EE 分享重新產生連結時，必須重新建立瀏覽器端分享授權"
    effective_envelope = normalized_envelope
    effective_expires_at = normalized_expires_at
    effective_max_views = normalized_max_views
    password_hash = None
    password_required = 0
    if existing:
        if effective_envelope is None:
            effective_envelope = str(existing["wrapped_file_key_envelope"] or "")
        if effective_expires_at is None:
            effective_expires_at = str(existing["expires_at"] or "")
        if effective_max_views is None:
            effective_max_views = int(existing["max_views"] or 0)
        if password in (_VIDEO_SHARE_UNSET, None):
            password_hash = existing["password_hash"]
            password_required = int(existing["password_required"] or 0)
    if password_hash is None:
        if password in (_VIDEO_SHARE_UNSET, None):
            password = ""
        if str(password or ""):
            try:
                password_hash = _hash_video_share_password(password)
                password_required = 1
            except ValueError as exc:
                return None, str(exc)
        else:
            password_hash = None
            password_required = 0
    effective_envelope = "" if effective_envelope is None else str(effective_envelope or "")
    effective_expires_at = "" if effective_expires_at is None else str(effective_expires_at or "")
    effective_max_views = 0 if effective_max_views is None else int(effective_max_views or 0)
    if is_e2ee_share and not effective_envelope:
        return None, "E2EE 持連結可看影音必須建立瀏覽器端分享授權"
    if existing:
        conn.execute(
            """
            UPDATE video_share_links
            SET revoked_at=?
            WHERE id=?
            """,
            (utc_now(), existing["id"]),
        )
    token = secrets.token_urlsafe(32)
    now = utc_now()
    link_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO video_share_links (
            id, video_id, owner_user_id, token, token_hash, password_required,
            password_hash, wrapped_file_key_envelope, expires_at, max_views,
            created_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            link_id,
            int(video_id),
            int(video["owner_user_id"]),
            token,
            _hash_share_token(token),
            password_required,
            password_hash,
            effective_envelope or None,
            effective_expires_at or None,
            effective_max_views,
            int(_actor_value(actor, "id")),
            now,
        ),
    )
    row = conn.execute("SELECT * FROM video_share_links WHERE id=?", (link_id,)).fetchone()
    return _video_share_link_payload(row), None


def _serialize_shared_video(row):
    if not row:
        return None
    data = serialize_video(row, actor=None, liked=False)
    if not data:
        return None
    token = _share_row_value(row, "token")
    data["stream_url"] = f"/api/videos/shared/{token}/stream"
    data["playback_url"] = f"/api/videos/shared/{token}/playback"
    data["cover_url"] = f"/api/videos/shared/{token}/cover" if data.get("cover_file_id") else ""
    data["share_url"] = _video_share_url(token)
    data["share_password_required"] = _video_share_password_required(row)
    data["share_requires_fragment_key"] = bool(str(_share_row_value(row, "wrapped_file_key_envelope", "") or "").strip())
    data["share_expires_at"] = _share_row_value(row, "expires_at", "") or ""
    data["share_max_views"] = int(_share_row_value(row, "max_views", 0) or 0)
    return data


def _video_base_select():
    return """
        SELECT v.*,
               u.username AS owner_username,
               u.nickname AS owner_nickname,
               f.privacy_mode AS cloud_privacy_mode,
               f.original_filename_plain_for_public AS cloud_filename,
               f.mime_type_plain_for_public AS cloud_mime_type,
               f.size_bytes AS cloud_size_bytes,
               cf.original_filename_plain_for_public AS cover_filename,
               cf.mime_type_plain_for_public AS cover_mime_type,
               cf.size_bytes AS cover_size_bytes
        FROM videos v
        LEFT JOIN users u ON u.id=v.owner_user_id
        LEFT JOIN uploaded_files f ON f.id=v.cloud_file_id
        LEFT JOIN uploaded_files cf ON cf.id=v.cover_file_id AND cf.deleted_at IS NULL
    """


def _liked_by_actor(conn, video_id, actor):
    if not actor:
        return False
    row = conn.execute(
        "SELECT 1 FROM video_likes WHERE video_id=? AND user_id=? LIMIT 1",
        (int(video_id), int(_actor_value(actor, "id"))),
    ).fetchone()
    return bool(row)


def normalize_visibility(value):
    visibility = str(value or "public").strip().lower()
    if visibility not in VIDEO_VISIBILITIES:
        raise ValueError("visibility must be public, unlisted, or private")
    return visibility


def normalize_title(value):
    title = str(value or "").replace("\x00", "").strip()
    if not title:
        raise ValueError("title is required")
    if len(title) > VIDEO_TITLE_MAX:
        raise ValueError(f"title must be {VIDEO_TITLE_MAX} characters or fewer")
    return title


def normalize_description(value):
    description = str(value or "").replace("\x00", "").strip()
    if len(description) > VIDEO_DESCRIPTION_MAX:
        raise ValueError(f"description must be {VIDEO_DESCRIPTION_MAX} characters or fewer")
    return description


def normalize_comment(value):
    content = str(value or "").replace("\x00", "").strip()
    if not content:
        raise ValueError("comment is required")
    if len(content) > VIDEO_COMMENT_MAX:
        raise ValueError(f"comment must be {VIDEO_COMMENT_MAX} characters or fewer")
    if UNSAFE_COMMENT_RE.search(content):
        raise ValueError("comment contains unsafe markup")
    return content


def _cloud_file_row(conn, cloud_file_id):
    return conn.execute("SELECT * FROM uploaded_files WHERE id=?", (str(cloud_file_id or ""),)).fetchone()


def _cloud_file_is_media(row):
    mime = str((row["mime_type_plain_for_public"] if "mime_type_plain_for_public" in row.keys() else row["cloud_mime_type"]) or "").lower() if row else ""
    if mime.startswith("video/") or mime.startswith("audio/"):
        return True
    filename = str((row["original_filename_plain_for_public"] if "original_filename_plain_for_public" in row.keys() else row["cloud_filename"]) or "").lower() if row else ""
    return any(filename.endswith(ext) for ext in MEDIA_FILENAME_EXTENSIONS)


def _cloud_file_media_type(row):
    mime = str((row["mime_type_plain_for_public"] if "mime_type_plain_for_public" in row.keys() else row["cloud_mime_type"]) or "").lower() if row else ""
    filename = str((row["original_filename_plain_for_public"] if "original_filename_plain_for_public" in row.keys() else row["cloud_filename"]) or "").lower() if row else ""
    if mime.startswith("audio/") or any(filename.endswith(ext) for ext in AUDIO_FILENAME_EXTENSIONS):
        return "audio"
    return "video"


def validate_publishable_cloud_file(conn, *, actor, cloud_file_id):
    row = _cloud_file_row(conn, cloud_file_id)
    if not row or row["deleted_at"]:
        raise ValueError("cloud file not found")
    if _safe_int(row["owner_user_id"]) != _safe_int(_actor_value(actor, "id")):
        raise PermissionError("cannot publish another user's file")
    if not _cloud_file_is_media(row):
        raise ValueError("cloud file must be a video or audio file")
    if str(row["scan_status"] or "") in {"infected", "quarantined"} or str(row["risk_level"] or "") == "blocked":
        raise ValueError("media file is blocked by upload security policy")
    return row


def validate_video_cover_file(conn, *, actor, cover_file_id):
    if not cover_file_id:
        return None
    row = _cloud_file_row(conn, cover_file_id)
    if not row or row["deleted_at"]:
        raise ValueError("cover file not found")
    if _safe_int(row["owner_user_id"]) != _safe_int(_actor_value(actor, "id")):
        raise PermissionError("cannot use another user's cover")
    if is_e2ee_file(row):
        raise ValueError("E2EE cover files cannot be displayed by the server")
    mime = str(row["mime_type_plain_for_public"] or "").lower()
    filename = str(row["original_filename_plain_for_public"] or "").lower()
    if not (mime.startswith("image/") or filename.endswith((".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"))):
        raise ValueError("cover file must be an image")
    if str(row["scan_status"] or "") in {"infected", "quarantined"} or str(row["risk_level"] or "") == "blocked":
        raise ValueError("cover file is blocked by upload security policy")
    return row


def publish_video(
    conn,
    *,
    actor,
    cloud_file_id,
    title,
    description="",
    visibility="public",
    cover_file_id=None,
    share_password=None,
    share_wrapped_file_key_envelope=None,
    share_expires_at=None,
    share_max_views=0,
):
    ensure_video_schema(conn)
    if not actor:
        raise PermissionError("login required")
    file_row = validate_publishable_cloud_file(conn, actor=actor, cloud_file_id=cloud_file_id)
    cover_row = validate_video_cover_file(conn, actor=actor, cover_file_id=cover_file_id)
    normalized_visibility = normalize_visibility(visibility)
    if is_e2ee_file(file_row) and normalized_visibility == "public":
        raise ValueError("E2EE 影音不可設為公開，請改用持連結可看或私人")
    now = utc_now()
    existing = conn.execute("SELECT * FROM videos WHERE cloud_file_id=?", (file_row["id"],)).fetchone()
    if existing:
        cover_sql = ", cover_file_id=?" if cover_row or cover_file_id == "" else ""
        params = [
            normalize_title(title),
            normalize_description(description),
            normalized_visibility,
            now,
        ]
        if cover_sql:
            params.append(cover_row["id"] if cover_row else None)
        params.append(existing["id"])
        conn.execute(
            f"""
            UPDATE videos
            SET title=?, description=?, visibility=?, status='ready', updated_at=?{cover_sql}
            WHERE id=?
            """,
            tuple(params),
        )
        video_id = existing["id"]
    else:
        cur = conn.execute(
            """
            INSERT INTO videos (
                video_uuid, owner_user_id, cloud_file_id, cover_file_id, title, description,
                visibility, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?)
            """,
            (
                uuid.uuid4().hex,
                int(_actor_value(actor, "id")),
                file_row["id"],
                cover_row["id"] if cover_row else None,
                normalize_title(title),
                normalize_description(description),
                normalized_visibility,
                now,
                now,
            ),
        )
        video_id = cur.lastrowid
    if normalized_visibility == "unlisted":
        share_link, msg = ensure_video_share_link(
            conn,
            actor=actor,
            video_id=video_id,
            password=share_password,
            wrapped_file_key_envelope=share_wrapped_file_key_envelope,
            expires_at=share_expires_at,
            max_views=share_max_views,
            regenerate=bool(share_wrapped_file_key_envelope),
        )
        if msg:
            raise ValueError(msg)
    video = get_video(conn, video_id, actor=actor)
    if normalized_visibility == "unlisted":
        video["share_link"] = share_link
        video["share_url"] = share_link["url"]
        video["share_password_required"] = bool(share_link["password_required"])
    return video


def can_view_video(actor, video_row, *, for_stream=False):
    if not video_row:
        return False
    status = video_row["status"]
    if status == "blocked":
        return bool(actor and (_safe_int(_actor_value(actor, "id")) == _safe_int(video_row["owner_user_id"]) or is_manager_or_root(actor)) and not for_stream)
    visibility = video_row["visibility"]
    if visibility == "public":
        return True
    if visibility == "unlisted":
        return bool(actor and (_safe_int(_actor_value(actor, "id")) == _safe_int(video_row["owner_user_id"]) or is_manager_or_root(actor)))
    return bool(actor and (_safe_int(_actor_value(actor, "id")) == _safe_int(video_row["owner_user_id"]) or is_manager_or_root(actor)))


def get_video(conn, video_id, *, actor=None, for_stream=False):
    ensure_video_schema(conn)
    row = conn.execute(_video_base_select() + " WHERE v.id=?", (int(video_id),)).fetchone()
    if not row:
        return None
    if not can_view_video(actor, row, for_stream=for_stream):
        raise PermissionError("video is private or blocked")
    data = serialize_video(row, actor=actor, liked=_liked_by_actor(conn, video_id, actor))
    if data and data.get("can_edit") and row["visibility"] == "unlisted":
        share = _active_video_share_link(conn, video_id)
        if share:
            payload = _video_share_link_payload(share)
            data["share_link"] = payload
            data["share_url"] = payload["url"]
            data["share_password_required"] = bool(payload["password_required"])
            data["share_requires_fragment_key"] = bool(payload["requires_fragment_key"])
            data["share_expires_at"] = payload["expires_at"]
            data["share_max_views"] = int(payload["max_views"] or 0)
    return data


def list_videos(conn, *, actor=None, sort="new", page=1, page_size=24):
    ensure_video_schema(conn)
    page = max(1, _safe_int(page, 1))
    page_size = min(50, max(1, _safe_int(page_size, 24)))
    sort = str(sort or "new").lower()
    order = "v.created_at DESC, v.id DESC"
    if sort == "hot":
        order = "(v.view_count + v.like_count * 4 + v.coin_total * 2 + v.comment_count * 3) DESC, v.created_at DESC"
    elif sort == "trending":
        order = "(v.like_count * 3 + v.comment_count * 2 + v.coin_total * 4) DESC, v.updated_at DESC"
    params = []
    where = ["v.status='ready'", "f.deleted_at IS NULL"]
    if actor:
        where.append("(v.visibility='public' OR v.owner_user_id=? OR ?=1)")
        params.extend([int(_actor_value(actor, "id")), 1 if is_manager_or_root(actor) else 0])
    else:
        where.append("v.visibility='public'")
    rows = conn.execute(
        _video_base_select() + f" WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ? OFFSET ?",
        (*params, page_size, (page - 1) * page_size),
    ).fetchall()
    return [serialize_video(row, actor=actor, liked=_liked_by_actor(conn, row["id"], actor)) for row in rows]


def resolve_video_share_token(conn, token, *, password=None, password_verified=False, counted_in_session=False):
    ensure_video_schema(conn)
    base_select = _video_base_select().replace("SELECT", "", 1).lstrip()
    row = conn.execute(
        """
        SELECT
            vsl.id AS share_id,
            vsl.video_id AS share_video_id,
            vsl.token AS share_token,
            vsl.password_required AS share_password_required,
            vsl.password_hash AS share_password_hash,
            vsl.wrapped_file_key_envelope AS share_wrapped_file_key_envelope,
            vsl.expires_at AS share_expires_at,
            vsl.max_views AS share_max_views,
            vsl.failed_password_attempts AS share_failed_password_attempts,
            vsl.password_locked_until AS share_password_locked_until,
            vsl.created_at AS share_created_at,
            vsl.access_count AS share_access_count,
            vsl.last_accessed_at AS share_last_accessed_at,
        """ + base_select +
        """
         JOIN video_share_links vsl ON vsl.video_id=v.id
         WHERE vsl.token_hash=? AND vsl.revoked_at IS NULL AND f.deleted_at IS NULL
        """,
        (_hash_share_token(token),),
    ).fetchone()
    if not row:
        return None, "not_found"
    if row["visibility"] != "unlisted":
        return None, "not_unlisted"
    if row["status"] != "ready":
        return None, "not_ready"
    if _video_share_is_expired(row):
        return None, "expired"
    if int(_share_row_value(row, "max_views", 0) or 0) > 0 and not counted_in_session and int(_share_row_value(row, "access_count", 0) or 0) >= int(_share_row_value(row, "max_views", 0) or 0):
        return None, "view_limit_reached"
    if _video_share_password_is_locked(row):
        return None, "password_locked"
    if _video_share_password_required(row):
        if not password_verified:
            if not str(password or ""):
                return None, "password_required"
            if not _verify_video_share_password(password, _share_row_value(row, "password_hash", "")):
                _record_video_share_password_failure(conn, row)
                return None, "password_invalid"
            _clear_video_share_password_failures(conn, _share_row_value(row, "id"))
    return row, None


def mark_video_share_link_accessed(conn, link_id):
    conn.execute(
        """
        UPDATE video_share_links
        SET access_count=access_count + 1, last_accessed_at=?
        WHERE id=?
        """,
        (utc_now(), str(link_id)),
    )


def shared_video_payload(conn, token, *, password=None, password_verified=False, counted_in_session=False):
    row, reason = resolve_video_share_token(
        conn,
        token,
        password=password,
        password_verified=password_verified,
        counted_in_session=counted_in_session,
    )
    if not row:
        return None, reason
    return _serialize_shared_video(row), None


def record_video_view(conn, *, actor=None, video_id, ip="", watch_seconds=0, completed=False):
    ensure_video_schema(conn)
    video = get_video(conn, video_id, actor=actor)
    if not video:
        raise ValueError("video not found")
    watch_seconds = max(0, min(24 * 3600, _safe_int(watch_seconds, 0)))
    viewer_user_id = _actor_value(actor, "id") if actor else None
    ip_hash = _sha256_text(ip or "anonymous") if ip else ""
    cutoff = (datetime.utcnow() - timedelta(hours=VIDEO_VIEW_DEDUP_HOURS)).replace(microsecond=0).isoformat()
    params = [int(video_id), cutoff]
    identity_where = []
    if viewer_user_id:
        identity_where.append("viewer_user_id=?")
        params.append(int(viewer_user_id))
    if ip_hash:
        identity_where.append("ip_hash=?")
        params.append(ip_hash)
    existing_counted = None
    if identity_where:
        existing_counted = conn.execute(
            f"""
            SELECT id FROM video_views
            WHERE video_id=? AND created_at>=? AND counted=1 AND ({' OR '.join(identity_where)})
            LIMIT 1
            """,
            tuple(params),
        ).fetchone()
    counted = int(watch_seconds >= VIDEO_VIEW_MIN_SECONDS and not existing_counted)
    now = utc_now()
    conn.execute(
        """
        INSERT INTO video_views (video_id, viewer_user_id, ip_hash, watch_seconds, completed, counted, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (int(video_id), int(viewer_user_id) if viewer_user_id else None, ip_hash, watch_seconds, 1 if completed else 0, counted, now),
    )
    if counted:
        conn.execute("UPDATE videos SET view_count=view_count+1, updated_at=? WHERE id=?", (now, int(video_id)))
    return {"ok": True, "counted": bool(counted), "video_id": int(video_id)}


def set_video_like(conn, *, actor, video_id, liked=True):
    ensure_video_schema(conn)
    if not actor:
        raise PermissionError("login required")
    get_video(conn, video_id, actor=actor)
    now = utc_now()
    if liked:
        cur = conn.execute(
            "INSERT OR IGNORE INTO video_likes (video_id, user_id, created_at) VALUES (?, ?, ?)",
            (int(video_id), int(_actor_value(actor, "id")), now),
        )
        if cur.rowcount:
            conn.execute("UPDATE videos SET like_count=like_count+1, updated_at=? WHERE id=?", (now, int(video_id)))
    else:
        cur = conn.execute(
            "DELETE FROM video_likes WHERE video_id=? AND user_id=?",
            (int(video_id), int(_actor_value(actor, "id"))),
        )
        if cur.rowcount:
            conn.execute("UPDATE videos SET like_count=MAX(0, like_count-1), updated_at=? WHERE id=?", (now, int(video_id)))
    return get_video(conn, video_id, actor=actor)


def add_video_comment(conn, *, actor, video_id, content, parent_id=None):
    ensure_video_schema(conn)
    if not actor:
        raise PermissionError("login required")
    get_video(conn, video_id, actor=actor)
    parent = None
    if parent_id not in (None, ""):
        parent = conn.execute("SELECT id FROM video_comments WHERE id=? AND video_id=?", (int(parent_id), int(video_id))).fetchone()
        if not parent:
            raise ValueError("parent comment not found")
    now = utc_now()
    cur = conn.execute(
        """
        INSERT INTO video_comments (video_id, user_id, content, parent_id, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (int(video_id), int(_actor_value(actor, "id")), normalize_comment(content), int(parent_id) if parent else None, now),
    )
    conn.execute("UPDATE videos SET comment_count=comment_count+1, updated_at=? WHERE id=?", (now, int(video_id)))
    return get_comment(conn, cur.lastrowid)


def get_comment(conn, comment_id):
    row = conn.execute(
        """
        SELECT c.*, u.username, u.nickname
        FROM video_comments c
        LEFT JOIN users u ON u.id=c.user_id
        WHERE c.id=?
        """,
        (int(comment_id),),
    ).fetchone()
    return serialize_comment(row)


def serialize_comment(row):
    data = _as_dict(row)
    if not data:
        return None
    for key in ("id", "video_id", "user_id", "parent_id", "like_count"):
        if key in data and data[key] is not None:
            data[key] = int(data[key])
    return data


def list_video_comments(conn, *, actor=None, video_id, limit=100):
    ensure_video_schema(conn)
    get_video(conn, video_id, actor=actor)
    rows = conn.execute(
        """
        SELECT c.*, u.username, u.nickname
        FROM video_comments c
        LEFT JOIN users u ON u.id=c.user_id
        WHERE c.video_id=?
        ORDER BY COALESCE(c.parent_id, c.id) ASC, c.parent_id IS NOT NULL ASC, c.created_at ASC, c.id ASC
        LIMIT ?
        """,
        (int(video_id), min(200, max(1, _safe_int(limit, 100)))),
    ).fetchall()
    return [serialize_comment(row) for row in rows]


def calculate_tip_fee(amount, fee_percent):
    amount = int(amount)
    fee_percent = max(0.0, float(fee_percent or 0))
    fee = int(amount * fee_percent / 100)
    if fee >= amount and amount > 1:
        fee = amount - 1
    return max(0, fee)


def tip_video(conn, *, points_service, actor, video_id, amount, fee_percent=5, idempotency_key=None):
    ensure_video_schema(conn)
    if not actor:
        raise PermissionError("login required")
    amount = int(amount)
    if amount < VIDEO_TIP_MIN_POINTS or amount > VIDEO_TIP_MAX_POINTS:
        raise ValueError(f"amount must be between {VIDEO_TIP_MIN_POINTS} and {VIDEO_TIP_MAX_POINTS}")
    video_row = conn.execute("SELECT * FROM videos WHERE id=?", (int(video_id),)).fetchone()
    if not video_row:
        raise ValueError("video not found")
    if not can_view_video(actor, video_row):
        raise PermissionError("video is private or blocked")
    from_user_id = int(_actor_value(actor, "id"))
    to_user_id = int(video_row["owner_user_id"])
    if from_user_id == to_user_id:
        raise ValueError("cannot tip your own video")
    if not points_service or not hasattr(points_service, "_record_transaction"):
        raise RuntimeError("PointsChain service is unavailable")
    if hasattr(points_service, "ensure_schema"):
        points_service.ensure_schema(conn)
    fee = calculate_tip_fee(amount, fee_percent)
    net = amount - fee
    fee_user_id = None
    idem = str(idempotency_key or "").strip()[:160] or f"video_tip:{uuid.uuid4().hex}"
    existing = conn.execute("SELECT * FROM video_tips WHERE idempotency_key=?", (idem,)).fetchone()
    if existing:
        if (
            _safe_int(existing["video_id"]) != int(video_id)
            or _safe_int(existing["from_user_id"]) != from_user_id
            or _safe_int(existing["to_user_id"]) != to_user_id
            or _safe_int(existing["amount_points"]) != amount
        ):
            raise ValueError("idempotency key conflicts with another video tip")
        return {"ok": True, "created": False, "tip": serialize_tip(existing)}
    if fee > 0:
        fee_user = conn.execute("SELECT id FROM users WHERE username='root' LIMIT 1").fetchone()
        if not fee_user:
            raise RuntimeError("official fee account is unavailable")
        fee_user_id = int(fee_user["id"])
    now = utc_now()
    debit_row, debit_created = points_service._record_transaction(
        conn,
        user_id=from_user_id,
        currency_type=DISPLAY_CURRENCY,
        direction="debit",
        amount=amount,
        action_type="video_tip_debit",
        reference_type="video",
        reference_id=str(video_id),
        idempotency_key=f"{idem}:debit",
        reason="video tip",
        public_metadata={"video_id": int(video_id), "to_user_id": to_user_id, "gross_points": amount, "fee_points": fee, "net_points": net},
        actor=actor,
    )
    credit_row, credit_created = points_service._record_transaction(
        conn,
        user_id=to_user_id,
        currency_type=DISPLAY_CURRENCY,
        direction="credit",
        amount=net,
        action_type="video_tip_credit",
        reference_type="video",
        reference_id=str(video_id),
        idempotency_key=f"{idem}:credit",
        reason="video tip revenue",
        public_metadata={"video_id": int(video_id), "from_user_id": from_user_id, "gross_points": amount, "fee_points": fee, "net_points": net},
        actor=actor,
    )
    fee_row = None
    fee_created = False
    if fee > 0:
        fee_row, fee_created = points_service._record_transaction(
            conn,
            user_id=fee_user_id,
            currency_type=DISPLAY_CURRENCY,
            direction="credit",
            amount=fee,
            action_type="video_tip_platform_fee",
            reference_type="video",
            reference_id=str(video_id),
            idempotency_key=f"{idem}:fee",
            reason="video tip platform fee",
            public_metadata={
                "video_id": int(video_id),
                "from_user_id": from_user_id,
                "to_user_id": to_user_id,
                "gross_points": amount,
                "fee_points": fee,
                "net_points": net,
            },
            actor=actor,
        )
    cur = conn.execute(
        """
        INSERT INTO video_tips (
            video_id, from_user_id, to_user_id, amount_points, fee_points, net_points,
            fee_user_id, ledger_debit_uuid, ledger_credit_uuid, ledger_fee_uuid,
            idempotency_key, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(video_id),
            from_user_id,
            to_user_id,
            amount,
            fee,
            net,
            fee_user_id,
            debit_row["ledger_uuid"],
            credit_row["ledger_uuid"],
            fee_row["ledger_uuid"] if fee_row else None,
            idem,
            now,
        ),
    )
    conn.execute("UPDATE videos SET coin_total=coin_total+?, updated_at=? WHERE id=?", (amount, now, int(video_id)))
    row = conn.execute("SELECT * FROM video_tips WHERE id=?", (cur.lastrowid,)).fetchone()
    return {
        "ok": True,
        "created": bool(debit_created or credit_created or fee_created),
        "tip": serialize_tip(row),
        "ledger": {
            "debit_uuid": debit_row["ledger_uuid"],
            "credit_uuid": credit_row["ledger_uuid"],
            "fee_uuid": fee_row["ledger_uuid"] if fee_row else None,
        },
    }


def serialize_tip(row):
    data = _as_dict(row)
    if not data:
        return None
    for key in ("id", "video_id", "from_user_id", "to_user_id", "fee_user_id", "amount_points", "fee_points", "net_points"):
        data[key] = _safe_int(data.get(key), 0)
    return data
