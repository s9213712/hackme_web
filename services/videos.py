import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta

from services.cloud_drive import is_e2ee_file
from services.points_chain import DISPLAY_CURRENCY


VIDEO_VISIBILITIES = {"public", "unlisted", "private"}
VIDEO_STATUSES = {"processing", "ready", "blocked"}
VIDEO_TITLE_MAX = 120
VIDEO_DESCRIPTION_MAX = 2000
VIDEO_COMMENT_MAX = 1000
VIDEO_VIEW_DEDUP_HOURS = 6
VIDEO_VIEW_MIN_SECONDS = 5
VIDEO_TIP_MIN_POINTS = 1
VIDEO_TIP_MAX_POINTS = 1_000_000
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
    _ensure_columns(conn, "video_views", {"counted": "INTEGER NOT NULL DEFAULT 0"})
    _ensure_columns(conn, "videos", {"cover_file_id": "TEXT"})
    _ensure_columns(conn, "video_tips", {
        "net_points": "INTEGER NOT NULL DEFAULT 0",
        "fee_user_id": "INTEGER",
        "ledger_fee_uuid": "TEXT",
        "idempotency_key": "TEXT",
    })
    conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_owner ON videos(owner_user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_visibility ON videos(visibility, status, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_video_views_video_created ON video_views(video_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_video_comments_video_created ON video_comments(video_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_video_tips_video_created ON video_tips(video_id, created_at)")
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


def _video_base_select():
    return """
        SELECT v.*,
               u.username AS owner_username,
               u.nickname AS owner_nickname,
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
    if is_e2ee_file(row):
        raise ValueError("E2EE media files cannot be server-streamed")
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


def publish_video(conn, *, actor, cloud_file_id, title, description="", visibility="public", cover_file_id=None):
    ensure_video_schema(conn)
    if not actor:
        raise PermissionError("login required")
    file_row = validate_publishable_cloud_file(conn, actor=actor, cloud_file_id=cloud_file_id)
    cover_row = validate_video_cover_file(conn, actor=actor, cover_file_id=cover_file_id)
    now = utc_now()
    existing = conn.execute("SELECT * FROM videos WHERE cloud_file_id=?", (file_row["id"],)).fetchone()
    if existing:
        cover_sql = ", cover_file_id=?" if cover_row or cover_file_id == "" else ""
        params = [
            normalize_title(title),
            normalize_description(description),
            normalize_visibility(visibility),
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
                normalize_visibility(visibility),
                now,
                now,
            ),
        )
        video_id = cur.lastrowid
    return get_video(conn, video_id, actor=actor)


def can_view_video(actor, video_row, *, for_stream=False):
    if not video_row:
        return False
    status = video_row["status"]
    if status == "blocked":
        return bool(actor and (_safe_int(_actor_value(actor, "id")) == _safe_int(video_row["owner_user_id"]) or is_manager_or_root(actor)) and not for_stream)
    visibility = video_row["visibility"]
    if visibility in {"public", "unlisted"}:
        return True
    return bool(actor and (_safe_int(_actor_value(actor, "id")) == _safe_int(video_row["owner_user_id"]) or is_manager_or_root(actor)))


def get_video(conn, video_id, *, actor=None, for_stream=False):
    ensure_video_schema(conn)
    row = conn.execute(_video_base_select() + " WHERE v.id=?", (int(video_id),)).fetchone()
    if not row:
        return None
    if not can_view_video(actor, row, for_stream=for_stream):
        raise PermissionError("video is private or blocked")
    return serialize_video(row, actor=actor, liked=_liked_by_actor(conn, video_id, actor))


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
