import json
import secrets
from datetime import datetime


APPEARANCE_COLOR_KEYS = (
    "site_bg",
    "site_surface",
    "site_accent",
    "site_accent2",
    "site_text",
    "site_muted",
)
APPEARANCE_LAYOUT_MODES = {"centered", "wide"}
APPEARANCE_DENSITIES = {"comfortable", "compact"}
APPEARANCE_RADIUS_VALUES = {8, 12, 18, 24}
APPEARANCE_FONT_SCALES = {0.95, 1.0, 1.08, 1.15}
APPEARANCE_CONTENT_WIDTHS = {1180, 1380, 1600}
APPEARANCE_FONT_FAMILIES = {"system", "rounded", "serif", "mono"}
APPEARANCE_BACKGROUND_STYLES = {"flat", "aurora", "grid"}
APPEARANCE_PANEL_STYLES = {"glass", "matte", "solid"}
APPEARANCE_SIDEBAR_WIDTHS = {"compact", "standard", "wide"}


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
            friend_code TEXT,
            friend_code_rotated_at TEXT,
            custom_title TEXT,
            custom_title_status TEXT NOT NULL DEFAULT 'none',
            profile_visibility TEXT NOT NULL DEFAULT 'public',
            appearance_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(user_profiles)").fetchall()}
    if "appearance_json" not in columns:
        conn.execute("ALTER TABLE user_profiles ADD COLUMN appearance_json TEXT NOT NULL DEFAULT '{}'")
    if "friend_code" not in columns:
        conn.execute("ALTER TABLE user_profiles ADD COLUMN friend_code TEXT")
    if "friend_code_rotated_at" not in columns:
        conn.execute("ALTER TABLE user_profiles ADD COLUMN friend_code_rotated_at TEXT")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_user_profiles_friend_code ON user_profiles(friend_code) WHERE friend_code IS NOT NULL AND friend_code<>''")


def _now():
    return datetime.now().isoformat()


def _clean(value, max_len):
    return str(value or "").strip()[:max_len]


def _visibility(value):
    value = str(value or "public").strip().lower()
    return value if value in {"public", "members", "private"} else "public"


def _clean_color(value):
    value = str(value or "").strip()
    return value if len(value) == 7 and value.startswith("#") and all(ch in "0123456789abcdefABCDEF" for ch in value[1:]) else ""


def _table_columns(conn, table):
    columns = set()
    for row in conn.execute(f"PRAGMA table_info({table})").fetchall():
        try:
            columns.add(row["name"])
        except Exception:
            columns.add(row[1])
    return columns


def _generate_friend_code(conn):
    for _ in range(20):
        cleaned = "".join(ch for ch in secrets.token_urlsafe(12) if ch.isalnum())
        if len(cleaned) < 12:
            continue
        code = "F" + cleaned[:12]
        if not conn.execute("SELECT 1 FROM user_profiles WHERE friend_code=?", (code,)).fetchone():
            return code
    raise RuntimeError("friend code generation exhausted")


def ensure_profile_friend_code(conn, user_id):
    ensure_user_profile_schema(conn)
    row = conn.execute("SELECT friend_code FROM user_profiles WHERE user_id=?", (int(user_id),)).fetchone()
    if row and row["friend_code"]:
        return row["friend_code"]
    code = _generate_friend_code(conn)
    now = _now()
    conn.execute(
        "UPDATE user_profiles SET friend_code=?, friend_code_rotated_at=?, updated_at=? WHERE user_id=?",
        (code, now, now, int(user_id)),
    )
    return code


def rotate_friend_code(conn, user_id):
    ensure_user_profile_schema(conn)
    get_or_create_profile(conn, user_id)
    code = _generate_friend_code(conn)
    now = _now()
    conn.execute(
        "UPDATE user_profiles SET friend_code=?, friend_code_rotated_at=?, updated_at=? WHERE user_id=?",
        (code, now, now, int(user_id)),
    )
    return code


def sanitize_appearance_settings(data):
    data = data if isinstance(data, dict) else {}
    out = {}
    for key in APPEARANCE_COLOR_KEYS:
        color = _clean_color(data.get(key))
        if color:
            out[key] = color
    layout = str(data.get("site_layout_mode") or "").strip().lower()
    if layout in APPEARANCE_LAYOUT_MODES:
        out["site_layout_mode"] = layout
    density = str(data.get("site_density") or "").strip().lower()
    if density in APPEARANCE_DENSITIES:
        out["site_density"] = density
    try:
        radius = int(data.get("site_radius_px"))
    except Exception:
        radius = None
    if radius in APPEARANCE_RADIUS_VALUES:
        out["site_radius_px"] = radius
    try:
        font_scale = round(float(data.get("site_font_scale")), 2)
    except Exception:
        font_scale = None
    if font_scale in APPEARANCE_FONT_SCALES:
        out["site_font_scale"] = font_scale
    try:
        content_width = int(data.get("site_content_width"))
    except Exception:
        content_width = None
    if content_width in APPEARANCE_CONTENT_WIDTHS:
        out["site_content_width"] = content_width
    font_family = str(data.get("site_font_family") or "").strip().lower()
    if font_family in APPEARANCE_FONT_FAMILIES:
        out["site_font_family"] = font_family
    background_style = str(data.get("site_background_style") or "").strip().lower()
    if background_style in APPEARANCE_BACKGROUND_STYLES:
        out["site_background_style"] = background_style
    panel_style = str(data.get("site_panel_style") or "").strip().lower()
    if panel_style in APPEARANCE_PANEL_STYLES:
        out["site_panel_style"] = panel_style
    sidebar_width = str(data.get("site_sidebar_width") or "").strip().lower()
    if sidebar_width in APPEARANCE_SIDEBAR_WIDTHS:
        out["site_sidebar_width"] = sidebar_width
    return out


def get_profile_appearance(conn, user_id):
    ensure_user_profile_schema(conn)
    row = conn.execute(
        "SELECT appearance_json FROM user_profiles WHERE user_id=?",
        (int(user_id),),
    ).fetchone()
    if not row:
        return {}
    profile = dict(row)
    raw = profile.get("appearance_json") or "{}"
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        parsed = {}
    return sanitize_appearance_settings(parsed)


def update_profile_appearance(conn, *, actor, data):
    ensure_user_profile_schema(conn)
    get_or_create_profile(conn, actor["id"])
    appearance = sanitize_appearance_settings(data)
    updated_at = _now()
    conn.execute(
        "UPDATE user_profiles SET appearance_json=?, updated_at=? WHERE user_id=?",
        (json.dumps(appearance, ensure_ascii=False, sort_keys=True), updated_at, int(actor["id"])),
    )
    return appearance


def clear_profile_appearance(conn, *, actor):
    ensure_user_profile_schema(conn)
    get_or_create_profile(conn, actor["id"])
    updated_at = _now()
    conn.execute(
        "UPDATE user_profiles SET appearance_json='{}', updated_at=? WHERE user_id=?",
        (updated_at, int(actor["id"])),
    )
    return {}


def get_or_create_profile(conn, user_id):
    ensure_user_profile_schema(conn)
    row = conn.execute("SELECT * FROM user_profiles WHERE user_id=?", (int(user_id),)).fetchone()
    if row:
        profile = dict(row)
        if not profile.get("friend_code"):
            profile["friend_code"] = ensure_profile_friend_code(conn, user_id)
        return profile
    now = _now()
    code = _generate_friend_code(conn)
    conn.execute(
        """
        INSERT INTO user_profiles (user_id, display_name, bio, signature, location, website, friend_code, friend_code_rotated_at, profile_visibility, appearance_json, created_at, updated_at)
        VALUES (?, '', '', '', '', '', ?, ?, 'public', '{}', ?, ?)
        """,
        (int(user_id), code, now, now, now),
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
    user_cols = _table_columns(conn, "users")
    member_level_expr = "u.member_level" if "member_level" in user_cols else "'' AS member_level"
    effective_level_expr = "u.effective_level" if "effective_level" in user_cols else "'' AS effective_level"
    created_at_expr = "u.created_at" if "created_at" in user_cols else "'' AS created_at"
    deleted_filter = "AND (u.deleted_at IS NULL OR u.deleted_at='')" if "deleted_at" in user_cols else ""
    row = conn.execute(
        f"""
        SELECT u.id, u.username, u.role, {member_level_expr}, {effective_level_expr}, {created_at_expr},
               p.display_name, p.bio, p.signature, p.location, p.website,
               p.friend_code, p.friend_code_rotated_at,
               p.custom_title, p.custom_title_status, p.profile_visibility, p.updated_at AS profile_updated_at
        FROM users u
        LEFT JOIN user_profiles p ON p.user_id=u.id
        WHERE u.username=? {deleted_filter}
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
    if not is_owner:
        data.pop("friend_code", None)
        data.pop("friend_code_rotated_at", None)
    return data
