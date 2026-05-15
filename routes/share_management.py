from datetime import datetime

from flask import request

from services.media.videos import ensure_video_schema
from services.share_access_events import ensure_share_access_event_schema, list_share_access_events
from services.storage.catalog import ensure_storage_album_schema


def register_share_management_routes(app, deps):
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_db = deps["get_db"]
    json_resp = deps["json_resp"]
    require_csrf = deps["require_csrf"]
    require_csrf_safe = deps["require_csrf_safe"]
    parse_positive_int = deps["parse_positive_int"]
    audit = deps.get("audit", lambda *args, **kwargs: None)
    get_client_ip = deps.get("get_client_ip", lambda: "")
    get_ua = deps.get("get_ua", lambda: "")

    def actor_value(actor, key, default=None):
        if not actor:
            return default
        try:
            return actor[key]
        except Exception:
            return actor.get(key, default) if hasattr(actor, "get") else default

    def actor_or_401():
        actor = get_current_user_ctx()
        if not actor:
            return None, json_resp({"ok": False, "msg": "未登入"}), 401
        return actor, None, None

    def now_text():
        return datetime.utcnow().replace(microsecond=0).isoformat()

    def share_status(row):
        if row.get("revoked_at"):
            return "revoked"
        expires_at = str(row.get("expires_at") or "").strip()
        if expires_at and expires_at <= now_text():
            return "expired"
        max_views = int(row.get("max_views") or 0)
        access_count = int(row.get("access_count") or 0)
        if max_views > 0 and access_count >= max_views:
            return "view_limit_reached"
        return "active"

    def row_int(row, key, default=0):
        try:
            return int(row[key])
        except Exception:
            try:
                return int(row.get(key, default))
            except Exception:
                return default

    def table_exists(conn, table):
        try:
            return bool(conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (str(table),),
            ).fetchone())
        except Exception:
            return False

    def storage_share_payload(row):
        data = dict(row)
        token = data.get("token") or ""
        item = {
            "id": data.get("id"),
            "share_type": "file",
            "resource_id": data.get("storage_file_id") or data.get("file_id"),
            "resource_title": data.get("display_name") or data.get("original_filename_plain_for_public") or data.get("file_id") or "檔案分享",
            "owner_user_id": row_int(data, "owner_user_id"),
            "password_required": False,
            "can_preview": bool(row_int(data, "can_preview")),
            "can_download": bool(row_int(data, "can_download", 1)),
            "access_scope": data.get("access_scope") or "link",
            "required_user_id": row_int(data, "required_user_id"),
            "required_username": data.get("required_username") or "",
            "expires_at": data.get("expires_at"),
            "max_views": row_int(data, "max_views"),
            "access_count": row_int(data, "access_count"),
            "last_accessed_at": data.get("last_accessed_at"),
            "created_at": data.get("created_at"),
            "revoked_at": data.get("revoked_at"),
            "status": share_status(data),
            "share_url": f"/shared/files/{token}" if token else "",
            "requires_fragment_key": bool(str(data.get("wrapped_file_key_envelope") or "").strip()),
        }
        return item

    def album_share_payload(row):
        data = dict(row)
        item = {
            "id": data.get("id"),
            "share_type": "album",
            "resource_id": data.get("album_id"),
            "resource_title": data.get("title") or "相簿分享",
            "owner_user_id": row_int(data, "owner_user_id"),
            "password_required": bool(row_int(data, "password_required")),
            "can_preview": True,
            "can_download": False,
            "expires_at": None,
            "max_views": 0,
            "access_count": row_int(data, "access_count"),
            "last_accessed_at": data.get("last_accessed_at"),
            "created_at": data.get("created_at"),
            "revoked_at": data.get("revoked_at"),
            "status": share_status(data),
            "share_url": f"/shared/albums/{data.get('token')}" if data.get("token") else "",
        }
        return item

    def video_share_payload(row):
        data = dict(row)
        item = {
            "id": data.get("id"),
            "share_type": "video",
            "resource_id": data.get("video_id"),
            "resource_title": data.get("title") or "影音分享",
            "owner_user_id": row_int(data, "owner_user_id"),
            "password_required": bool(row_int(data, "password_required")),
            "can_preview": True,
            "can_download": False,
            "expires_at": data.get("expires_at"),
            "max_views": row_int(data, "max_views"),
            "access_count": row_int(data, "access_count"),
            "last_accessed_at": data.get("last_accessed_at"),
            "created_at": data.get("created_at"),
            "revoked_at": data.get("revoked_at"),
            "status": share_status(data),
            "share_url": f"/shared/videos/{data.get('token')}" if data.get("token") else "",
        }
        return item

    def share_table_map():
        return {
            "file": ("storage_share_links", "id"),
            "album": ("album_share_links", "id"),
            "video": ("video_share_links", "id"),
        }

    def ensure_share_tables(conn):
        ensure_storage_album_schema(conn)
        ensure_video_schema(conn)
        ensure_share_access_event_schema(conn)

    def get_share_row(conn, share_type, share_id):
        table_map = share_table_map()
        if share_type not in table_map:
            return None, None, None
        table, id_col = table_map[share_type]
        row = conn.execute(f"SELECT * FROM {table} WHERE {id_col}=?", (str(share_id),)).fetchone()
        return row, table, id_col

    def require_share_access(actor, row):
        if not row:
            return json_resp({"ok": False, "msg": "找不到分享連結"}), 404
        if int(row["owner_user_id"]) != int(actor["id"]):
            return json_resp({"ok": False, "msg": "不可管理他人的分享連結"}), 403
        return None, None

    def share_access_events(conn, share_type, row, status):
        data = dict(row)
        events = []
        for event in list_share_access_events(conn, share_type=share_type, share_id=data.get("id"), limit=80):
            ip = event.get("ip") or ""
            events.append({
                "event_type": event.get("event_type") or "opened",
                "label": "分享已開啟",
                "created_at": event.get("created_at"),
                "opened_at": event.get("created_at"),
                "ip": ip,
                "source_ip": ip,
                "user_agent": event.get("user_agent") or "",
                "detail": "分享連結被開啟。",
            })
        if data.get("created_at"):
            events.append({
                "event_type": "created",
                "label": "分享已建立",
                "created_at": data.get("created_at"),
                "detail": "分享連結建立成功。",
            })
        if data.get("last_accessed_at"):
            events.append({
                "event_type": "accessed",
                "label": "最近一次存取",
                "created_at": data.get("last_accessed_at"),
                "opened_at": data.get("last_accessed_at"),
                "detail": f"累計存取 {row_int(data, 'access_count')} 次。",
            })
        if status == "view_limit_reached":
            events.append({
                "event_type": "ended",
                "label": "分享次數已用完",
                "created_at": data.get("last_accessed_at") or data.get("created_at"),
                "detail": f"最大可觀看次數 {row_int(data, 'max_views')} 次。",
            })
        elif status == "expired":
            events.append({
                "event_type": "ended",
                "label": "分享已到期",
                "created_at": data.get("expires_at") or data.get("created_at"),
                "detail": "分享到期後不再允許存取。",
            })
        if data.get("revoked_at"):
            events.append({
                "event_type": "revoked",
                "label": "分享已撤銷",
                "created_at": data.get("revoked_at"),
                "detail": "分享連結已由擁有者撤銷。",
            })
        return sorted(events, key=lambda item: str(item.get("created_at") or ""), reverse=True)

    @app.route("/api/shares", methods=["GET"])
    @require_csrf_safe
    def shares_list():
        actor, err, status_code = actor_or_401()
        if err:
            return err, status_code
        include_all = False
        limit = parse_positive_int(request.args.get("limit"), default=100, min_value=1, max_value=200)
        conn = get_db()
        try:
            ensure_storage_album_schema(conn)
            ensure_video_schema(conn)
            owner_clause = "" if include_all else "WHERE sl.owner_user_id=?"
            owner_params = [] if include_all else [int(actor["id"])]
            if table_exists(conn, "uploaded_files"):
                upload_name_select = "uf.original_filename_plain_for_public"
                upload_join = "LEFT JOIN uploaded_files uf ON uf.id=sl.file_id"
            else:
                upload_name_select = "NULL AS original_filename_plain_for_public"
                upload_join = ""
            if table_exists(conn, "users"):
                required_user_select = "u.username AS required_username"
                required_user_join = "LEFT JOIN users u ON u.id=sl.required_user_id"
            else:
                required_user_select = "NULL AS required_username"
                required_user_join = ""
            shares = []
            for row in conn.execute(
                f"""
                SELECT sl.*, sf.display_name, {upload_name_select}, {required_user_select}
                FROM storage_share_links sl
                LEFT JOIN storage_files sf ON sf.id=sl.storage_file_id
                {required_user_join}
                {upload_join}
                {owner_clause}
                ORDER BY sl.created_at DESC
                LIMIT ?
                """,
                tuple(owner_params + [limit]),
            ).fetchall():
                shares.append(storage_share_payload(row))
            album_where = "" if include_all else "WHERE asl.owner_user_id=?"
            for row in conn.execute(
                f"""
                SELECT asl.*, a.title
                FROM album_share_links asl
                LEFT JOIN albums a ON a.id=asl.album_id
                {album_where}
                ORDER BY asl.created_at DESC
                LIMIT ?
                """,
                tuple(owner_params + [limit]),
            ).fetchall():
                shares.append(album_share_payload(row))
            video_where = "" if include_all else "WHERE vsl.owner_user_id=?"
            for row in conn.execute(
                f"""
                SELECT vsl.*, v.title
                FROM video_share_links vsl
                LEFT JOIN videos v ON v.id=vsl.video_id
                {video_where}
                ORDER BY vsl.created_at DESC
                LIMIT ?
                """,
                tuple(owner_params + [limit]),
            ).fetchall():
                shares.append(video_share_payload(row))
            shares.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
            return json_resp({"ok": True, "shares": shares[:limit]})
        finally:
            conn.close()

    @app.route("/api/shares/<share_type>/<share_id>/revoke", methods=["POST"])
    @require_csrf
    def share_revoke(share_type, share_id):
        actor, err, status_code = actor_or_401()
        if err:
            return err, status_code
        share_type = str(share_type or "").strip().lower()
        if share_type not in share_table_map():
            return json_resp({"ok": False, "msg": "分享類型錯誤"}), 400
        conn = get_db()
        try:
            ensure_share_tables(conn)
            row, table, id_col = get_share_row(conn, share_type, share_id)
            err, status_code = require_share_access(actor, row)
            if err:
                return err, status_code
            conn.execute(f"UPDATE {table} SET revoked_at=? WHERE {id_col}=? AND revoked_at IS NULL", (now_text(), str(share_id)))
            conn.commit()
            audit("SHARE_LINK_REVOKED", get_client_ip(), user=actor_value(actor, "username"), success=True, ua=get_ua(), detail=f"type={share_type},id={share_id}")
            return json_resp({"ok": True, "msg": "分享連結已撤銷"})
        finally:
            conn.close()

    @app.route("/api/shares/<share_type>/<share_id>/access-events", methods=["GET"])
    @require_csrf_safe
    def share_access_event_list(share_type, share_id):
        actor, err, status_code = actor_or_401()
        if err:
            return err, status_code
        share_type = str(share_type or "").strip().lower()
        if share_type not in share_table_map():
            return json_resp({"ok": False, "msg": "分享類型錯誤"}), 400
        conn = get_db()
        try:
            ensure_share_tables(conn)
            row, _table, _id_col = get_share_row(conn, share_type, share_id)
            err, status_code = require_share_access(actor, row)
            if err:
                return err, status_code
            status = share_status(dict(row))
            return json_resp({"ok": True, "status": status, "events": share_access_events(conn, share_type, row, status)})
        finally:
            conn.close()
