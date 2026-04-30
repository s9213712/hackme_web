from datetime import datetime


def ensure_user_profile_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            display_name TEXT,
            bio TEXT,
            signature TEXT,
            location TEXT,
            website TEXT,
            custom_title TEXT,
            custom_title_status TEXT NOT NULL DEFAULT 'none',
            profile_visibility TEXT NOT NULL DEFAULT 'public',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def _now():
    return datetime.now().isoformat()


def _clean(value, max_len):
    return str(value or "").strip()[:max_len]


def _visibility(value):
    value = str(value or "public").strip().lower()
    return value if value in {"public", "members", "private"} else "public"


def get_or_create_profile(conn, user_id):
    ensure_user_profile_schema(conn)
    row = conn.execute("SELECT * FROM user_profiles WHERE user_id=?", (int(user_id),)).fetchone()
    if row:
        return dict(row)
    now = _now()
    conn.execute(
        """
        INSERT INTO user_profiles (user_id, display_name, bio, signature, location, website, profile_visibility, created_at, updated_at)
        VALUES (?, '', '', '', '', '', 'public', ?, ?)
        """,
        (int(user_id), now, now),
    )
    return dict(conn.execute("SELECT * FROM user_profiles WHERE user_id=?", (int(user_id),)).fetchone())


def update_profile(conn, *, actor, data):
    ensure_user_profile_schema(conn)
    profile = get_or_create_profile(conn, actor["id"])
    updates = {
        "display_name": _clean(data.get("display_name", profile.get("display_name")), 80),
        "bio": _clean(data.get("bio", profile.get("bio")), 1000),
        "signature": _clean(data.get("signature", profile.get("signature")), 300),
        "location": _clean(data.get("location", profile.get("location")), 80),
        "website": _clean(data.get("website", profile.get("website")), 200),
        "profile_visibility": _visibility(data.get("profile_visibility", profile.get("profile_visibility"))),
    }
    if updates["website"] and not (updates["website"].startswith("https://") or updates["website"].startswith("http://")):
        return None, "website 必須以 http:// 或 https:// 開頭"
    updates["updated_at"] = _now()
    conn.execute(
        """
        UPDATE user_profiles
        SET display_name=?, bio=?, signature=?, location=?, website=?, profile_visibility=?, updated_at=?
        WHERE user_id=?
        """,
        (
            updates["display_name"],
            updates["bio"],
            updates["signature"],
            updates["location"],
            updates["website"],
            updates["profile_visibility"],
            updates["updated_at"],
            int(actor["id"]),
        ),
    )
    return get_public_profile(conn, username=actor["username"], viewer=actor), None


def get_public_profile(conn, *, username, viewer=None):
    ensure_user_profile_schema(conn)
    row = conn.execute(
        """
        SELECT u.id, u.username, u.role, u.member_level, u.effective_level, u.created_at,
               p.display_name, p.bio, p.signature, p.location, p.website,
               p.custom_title, p.custom_title_status, p.profile_visibility, p.updated_at AS profile_updated_at
        FROM users u
        LEFT JOIN user_profiles p ON p.user_id=u.id
        WHERE u.username=? AND (u.deleted_at IS NULL OR u.deleted_at='')
        """,
        (str(username or "").strip(),),
    ).fetchone()
    if not row:
        return None
    data = dict(row)
    visibility = data.get("profile_visibility") or "public"
    is_owner = viewer and int(viewer.get("id") or -1) == int(data["id"])
    is_member = bool(viewer)
    if visibility == "private" and not is_owner:
        data["bio"] = ""
        data["signature"] = ""
        data["location"] = ""
        data["website"] = ""
    if visibility == "members" and not is_member:
        data["bio"] = ""
        data["signature"] = ""
        data["location"] = ""
        data["website"] = ""
    return data
