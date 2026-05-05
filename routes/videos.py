from pathlib import Path
import mimetypes
import json
from datetime import datetime, timedelta

from flask import Response, request, send_file, session

from services.cloud_drive import (
    decrypt_server_encrypted_bytes,
    ensure_cloud_drive_attachment_schema,
    is_e2ee_file,
    is_server_encrypted_file,
    resolve_file_storage_path,
    store_cloud_upload,
)
from services.http_headers import build_content_disposition
from services.media_streaming import (
    ensure_media_stream_schema,
    get_stream_status,
    prepare_stream_asset,
    should_auto_prepare_stream,
    stream_playback_payload,
)
from services.e2ee_streaming import (
    ensure_e2ee_stream_v2_schema,
    get_e2ee_stream_v2_status,
    resolve_e2ee_chunk_response,
    serialize_manifest_for_client,
    upsert_e2ee_stream_v2_asset,
)
from services.storage_albums import create_storage_file_entry, ensure_storage_album_schema
from services.upload_security import safe_public_filename
from services.videos import (
    add_video_comment,
    ensure_video_schema,
    ensure_video_share_link,
    get_video,
    list_video_comments,
    list_videos,
    mark_video_share_link_accessed,
    publish_video,
    revoke_video_share_link,
    record_video_view,
    resolve_video_share_token,
    set_video_like,
    shared_video_payload,
    tip_video,
)


def register_video_routes(app, deps):
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_db = deps["get_db"]
    get_client_ip = deps.get("get_client_ip", lambda: "")
    get_ua = deps.get("get_ua", lambda: "")
    json_resp = deps["json_resp"]
    require_csrf = deps["require_csrf"]
    require_csrf_safe = deps["require_csrf_safe"]
    audit = deps.get("audit", lambda *args, **kwargs: None)
    points_service = deps.get("points_service")
    storage_root = deps["STORAGE_DIR"]
    server_file_fernet = deps.get("server_file_fernet")
    get_system_settings = deps.get("get_system_settings", lambda: {})
    get_member_level_rule = deps["get_member_level_rule"]
    ffmpeg_bin = deps.get("FFMPEG_BIN", "ffmpeg")
    ffprobe_bin = deps.get("FFPROBE_BIN", "ffprobe")
    forbidden_share_fields = {"raw_file_key", "e2ee_password", "vk", "share_key", "share_key_bytes"}

    def _parse_json_body():
        try:
            data = request.get_json(force=True)
        except Exception:
            return None, json_resp({"ok": False, "msg": "Invalid JSON", "error": "invalid_json"}), 400
        if not isinstance(data, dict):
            return None, json_resp({"ok": False, "msg": "Invalid request", "error": "invalid_request"}), 400
        return data, None, None

    def _actor_or_401():
        actor = get_current_user_ctx()
        if not actor:
            return None, json_resp({"ok": False, "msg": "請先登入", "error": "login_required"}), 401
        return actor, None

    def _error_response(exc):
        message = str(exc) or exc.__class__.__name__
        if isinstance(exc, PermissionError):
            return json_resp({"ok": False, "msg": message, "error": "forbidden"}), 403
        if "無法以目前伺服器金鑰解密" in message:
            return json_resp({"ok": False, "msg": message, "error": "decrypt_unavailable"}), 409
        if "insufficient balance" in message:
            return json_resp({"ok": False, "msg": "積分不足，無法投幣", "error": "insufficient_balance"}), 409
        return json_resp({"ok": False, "msg": message, "error": exc.__class__.__name__}), 400

    def _svg_placeholder_response(message, *, label="封面不可顯示"):
        safe_label = (label or "封面不可顯示").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        safe_message = (message or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
<rect width="960" height="540" fill="#151823"/>
<rect x="32" y="32" width="896" height="476" rx="20" fill="#202533" stroke="#39405a"/>
<text x="480" y="220" text-anchor="middle" fill="#f4f6ff" font-size="34" font-family="Arial, sans-serif">{safe_label}</text>
<text x="480" y="280" text-anchor="middle" fill="#b8bfd8" font-size="20" font-family="Arial, sans-serif">{safe_message}</text>
</svg>"""
        return Response(svg, status=200, mimetype="image/svg+xml")

    def _settings_float(key, default):
        try:
            return float((get_system_settings() or {}).get(key, default))
        except Exception:
            return float(default)

    def _settings_bool(key, default):
        raw = (get_system_settings() or {}).get(key, default)
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in {"1", "true", "yes", "on", "y", "t"}

    def _is_manager_or_root(actor):
        if not actor:
            return False
        role = str(actor.get("role") or "").strip().lower()
        return actor.get("username") == "root" or role in {"manager", "admin", "super_admin"}

    def _load_stream_file(conn, *, file_id):
        row = conn.execute(
            "SELECT * FROM uploaded_files WHERE id=? AND deleted_at IS NULL",
            (str(file_id or ""),),
        ).fetchone()
        if not row:
            raise ValueError("找不到影音檔案")
        return row

    def _assert_stream_prepare_allowed(actor, row):
        if not actor:
            raise PermissionError("login required")
        if int(row["owner_user_id"]) == int(actor["id"]) or _is_manager_or_root(actor):
            return
        raise PermissionError("只有檔案擁有者或管理者可以準備串流衍生檔")

    def _maybe_prepare_stream_asset(conn, *, file_row, visibility):
        if not _settings_bool("video_stream_auto_prepare_enabled", True):
            return None, None
        decision = should_auto_prepare_stream(file_row, visibility=visibility)
        if not decision.get("enabled"):
            return None, None
        try:
            asset = prepare_stream_asset(
                conn,
                file_row=file_row,
                storage_root=storage_root,
                server_file_fernet=server_file_fernet,
                ffprobe_bin=ffprobe_bin,
                ffmpeg_bin=ffmpeg_bin,
            )
            return asset, None
        except Exception as exc:
            return None, f"HLS 串流準備失敗：{exc}"

    def _uploaded_file_is_media(file_storage):
        filename = getattr(file_storage, "filename", "") or ""
        declared = str(getattr(file_storage, "mimetype", "") or "").split(";", 1)[0].strip().lower()
        guessed = str(mimetypes.guess_type(filename)[0] or "").lower()
        return (
            declared.startswith("video/")
            or declared.startswith("audio/")
            or guessed.startswith("video/")
            or guessed.startswith("audio/")
        )

    def _uploaded_file_is_image(file_storage):
        filename = getattr(file_storage, "filename", "") or ""
        declared = str(getattr(file_storage, "mimetype", "") or "").split(";", 1)[0].strip().lower()
        guessed = str(mimetypes.guess_type(filename)[0] or "").lower()
        return declared.startswith("image/") or guessed.startswith("image/")

    def _default_media_title(file_storage):
        filename = safe_public_filename(getattr(file_storage, "filename", "") or "media")
        stem = Path(filename).stem.strip()
        return stem or "未命名影音"

    def _parse_publish_request():
        if request.files or request.form:
            data = {
                "cloud_file_id": (request.form.get("cloud_file_id") or "").strip(),
                "title": (request.form.get("title") or "").strip(),
                "description": request.form.get("description") or "",
                "visibility": (request.form.get("visibility") or "public").strip() or "public",
                "cover_file_id": (request.form.get("cover_file_id") or "").strip() or None,
                "share_password": request.form.get("share_password") or "",
                "share_wrapped_file_key_envelope": request.form.get("share_wrapped_file_key_envelope") or "",
                "share_expires_at": request.form.get("share_expires_at") or "",
                "share_max_views": request.form.get("share_max_views") or "",
            }
            return data, request.files.get("cover"), None, None
        data, err, status = _parse_json_body()
        if isinstance(data, dict):
            data["share_password"] = data.get("share_password") or ""
            data["share_wrapped_file_key_envelope"] = data.get("share_wrapped_file_key_envelope") or ""
            data["share_expires_at"] = data.get("share_expires_at") or ""
            data["share_max_views"] = data.get("share_max_views") or ""
        return data, None, err, status

    def _reject_sensitive_share_fields(payload):
        payload = payload or {}
        for field in forbidden_share_fields:
            value = payload.get(field)
            if value not in (None, "", [], {}):
                return json_resp({"ok": False, "msg": f"禁止提交敏感分享欄位：{field}", "error": "forbidden_share_secret_field"}), 400
        return None

    def _store_video_cover_upload(conn, *, actor, member_rule, cover_upload, privacy_mode):
        if not cover_upload or not cover_upload.filename:
            return None, None, None, None
        if not _uploaded_file_is_image(cover_upload):
            return None, None, "封面圖只接受圖片檔", "cover_not_image"
        cover_result, cover_msg = store_cloud_upload(
            conn,
            actor=actor,
            member_rule=member_rule,
            storage_root=storage_root,
            file_storage=cover_upload,
            privacy_mode=privacy_mode,
            scan_now=True,
            server_file_fernet=server_file_fernet,
        )
        if cover_msg:
            return None, None, cover_msg, "cover_upload_rejected"
        cover_row = conn.execute("SELECT * FROM uploaded_files WHERE id=?", (cover_result["file_id"],)).fetchone()
        cover_storage_file, cover_storage_msg = create_storage_file_entry(
            conn,
            actor=actor,
            file_row=cover_row,
            virtual_path=f"/Media/Covers/{cover_result['file_id']}-{safe_public_filename(cover_upload.filename)}",
            display_name=safe_public_filename(cover_upload.filename),
            source="video_cover_upload",
        )
        if cover_storage_msg:
            return None, None, cover_storage_msg, "cover_storage_entry_failed"
        return cover_result, cover_storage_file, None, None

    def _parse_http_byte_range(range_header, total_size):
        if not range_header:
            return None, None
        value = str(range_header or "").strip()
        if not value.startswith("bytes="):
            return None, "invalid"
        spec = value[6:].split(",", 1)[0].strip()
        if "-" not in spec:
            return None, "invalid"
        start_raw, end_raw = spec.split("-", 1)
        try:
            if start_raw == "":
                suffix_len = int(end_raw)
                if suffix_len <= 0:
                    return None, "invalid"
                start = max(0, total_size - suffix_len)
                end = total_size - 1
            else:
                start = int(start_raw)
                end = int(end_raw) if end_raw else total_size - 1
        except Exception:
            return None, "invalid"
        if total_size <= 0 or start < 0 or end < start or start >= total_size:
            return None, "invalid"
        return (start, min(end, total_size - 1)), None

    def _send_bytes_with_range(raw, *, download_name, mimetype, range_header=None):
        total_size = len(raw)
        byte_range, error = _parse_http_byte_range(range_header, total_size)
        if error:
            response = Response(status=416)
            response.headers["Content-Range"] = f"bytes */{total_size}"
            response.headers["Accept-Ranges"] = "bytes"
            return response
        if byte_range:
            start, end = byte_range
            response = Response(raw[start:end + 1], status=206, mimetype=mimetype or "application/octet-stream")
            response.headers["Content-Range"] = f"bytes {start}-{end}/{total_size}"
            response.headers["Content-Length"] = str(end - start + 1)
        else:
            response = Response(raw, status=200, mimetype=mimetype or "application/octet-stream")
            response.headers["Content-Length"] = str(total_size)
        response.headers["Accept-Ranges"] = "bytes"
        response.headers["Content-Disposition"] = build_content_disposition("inline", download_name)
        return response

    def _shared_video_password_from_request():
        return request.headers.get("X-Video-Share-Password") or request.args.get("password") or ""

    def _shared_video_access_state():
        raw = session.get("video_share_access")
        return raw if isinstance(raw, dict) else {}

    def _shared_video_has_session_access(token):
        state = _shared_video_access_state()
        key = str(token or "")
        expires_at = str(state.get(key) or "").strip()
        if not expires_at:
            return False
        return expires_at > datetime.utcnow().replace(microsecond=0).isoformat()

    def _grant_shared_video_session_access(token, *, hours=8):
        state = _shared_video_access_state()
        state[str(token or "")] = (datetime.utcnow() + timedelta(hours=max(1, int(hours)))).replace(microsecond=0).isoformat()
        session["video_share_access"] = state
        session.modified = True

    def _revoke_shared_video_session_access(token):
        state = _shared_video_access_state()
        if str(token or "") in state:
            state.pop(str(token or ""), None)
            session["video_share_access"] = state
            session.modified = True

    def _shared_video_seen_state():
        raw = session.get("video_share_seen")
        return raw if isinstance(raw, dict) else {}

    def _shared_video_seen(token):
        return bool(_shared_video_seen_state().get(str(token or "")))

    def _mark_shared_video_seen(token):
        state = _shared_video_seen_state()
        state[str(token or "")] = True
        session["video_share_seen"] = state
        session.modified = True

    def _count_shared_video_access(conn, row, token, counted_in_session):
        if counted_in_session:
            return True
        mark_video_share_link_accessed(conn, row["share_id"] if "share_id" in row.keys() else row["id"])
        _mark_shared_video_seen(token)
        return True

    def _shared_video_error_response(reason):
        if reason == "password_required":
            return json_resp({
                "ok": False,
                "msg": "這部影音需要分享密碼",
                "reason": reason,
                "password_required": True,
            }), 401
        if reason == "password_invalid":
            return json_resp({
                "ok": False,
                "msg": "分享密碼不正確",
                "reason": reason,
                "password_required": True,
            }), 403
        if reason == "password_locked":
            return json_resp({"ok": False, "msg": "分享密碼嘗試次數過多，請稍後再試", "reason": reason, "password_required": True}), 429
        if reason == "expired":
            return json_resp({"ok": False, "msg": "此分享連結已到期", "reason": reason}), 410
        if reason == "view_limit_reached":
            return json_resp({"ok": False, "msg": "此分享連結已達最大觀看次數", "reason": reason}), 410
        if reason == "forbidden_fragment_transport":
            return json_resp({"ok": False, "msg": "分享金鑰必須保留在 URL fragment，不可送到伺服器", "reason": reason}), 400
        return json_resp({"ok": False, "msg": "分享影音不存在或已失效", "reason": reason}), 404

    def _resolve_shared_video(conn, token):
        if request.args.get("vk"):
            return None, "forbidden_fragment_transport", False, _shared_video_seen(token)
        password_verified = _shared_video_has_session_access(token)
        counted_in_session = _shared_video_seen(token)
        row, reason = resolve_video_share_token(
            conn,
            token,
            password=_shared_video_password_from_request(),
            password_verified=password_verified,
            counted_in_session=counted_in_session,
        )
        return row, reason, password_verified, counted_in_session

    def _e2ee_direct_status(row):
        return {
            "uploaded_file_id": row["id"],
            "source_mode": "e2ee",
            "media_type": "audio" if str(row["original_filename_plain_for_public"] or "").lower().endswith((".mp3", ".m4a", ".aac", ".flac", ".wav", ".weba", ".opus", ".oga", ".ogg")) else "video",
            "status": "direct_only",
            "storage_mode": "browser_e2ee",
            "master_manifest_path": "",
            "duration_seconds": 0.0,
            "source_mime_type": str(row["mime_type_plain_for_public"] or mimetypes.guess_type(str(row["original_filename_plain_for_public"] or ""))[0] or ""),
            "source_size_bytes": int(row["size_bytes"] or 0),
            "error_message": "端到端加密影音只支援瀏覽器端解密播放，會較慢且不支援 HLS 加速。",
            "variants": [],
        }

    def _playback_payload_for_file(conn, *, row, video_id, shared_token=None):
        media_type = "audio" if str(row["original_filename_plain_for_public"] or "").lower().endswith((".mp3", ".m4a", ".aac", ".flac", ".wav", ".weba", ".opus", ".oga", ".ogg")) else "video"
        if is_e2ee_file(row):
            ensure_e2ee_stream_v2_schema(conn)
            if shared_token:
                ciphertext_url = f"/api/videos/shared/{shared_token}/ciphertext"
                e2ee_key_url = f"/api/videos/shared/{shared_token}/e2ee-key"
                manifest_url = f"/api/videos/shared/{shared_token}/e2ee-stream-v2/manifest"
                chunk_url_template = f"/api/videos/shared/{shared_token}/e2ee-stream-v2/chunks/__INDEX__"
            else:
                ciphertext_url = f"/api/cloud-drive/files/{row['id']}/preview/content"
                e2ee_key_url = f"/api/cloud-drive/files/{row['id']}/e2ee-key"
                manifest_url = f"/api/videos/{video_id}/e2ee-stream-v2/manifest"
                chunk_url_template = f"/api/videos/{video_id}/e2ee-stream-v2/chunks/__INDEX__"
            stream_v2 = get_e2ee_stream_v2_status(conn, file_row=row, storage_root=storage_root)
            available = bool(stream_v2 and stream_v2.get("available"))
            payload = {
                "mode": "e2ee_stream_v2" if available else "e2ee_direct",
                "media_type": media_type,
                "source_mode": "e2ee",
                "fallback_url": ciphertext_url,
                "stream_url": ciphertext_url,
                "ciphertext_url": ciphertext_url,
                "e2ee_key_url": e2ee_key_url,
                "requires_fragment_key": bool(shared_token),
                "master_url": "",
                "hls_js_url": "",
                "player_strategy": "browser_e2ee_stream_v2" if available else "browser_e2ee_full_fallback",
                "stream_warning": (
                    "正在使用 E2EE Streaming v2：密文分段下載、瀏覽器端解密；伺服器無法看到明文。"
                    if available
                    else "此 strict E2EE 影音尚未建立 Streaming v2 manifest，將退回舊版完整解密播放。"
                ),
                "streaming_ready": available,
                "high_performance_streaming": False,
                "status": stream_v2 if stream_v2 else _e2ee_direct_status(row),
                "manifest_url": manifest_url,
                "chunk_url_template": chunk_url_template,
                "stream_v2_available": available,
            }
            return payload
        payload = stream_playback_payload(conn, file_row=row, video_id=video_id)
        payload["high_performance_streaming"] = payload.get("mode") == "hls"
        return payload

    def _shared_video_html(token):
        token = str(token or "")
        return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>分享影音</title>
  <style>
    body {{ margin:0; background:#111521; color:#eef2ff; font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    .wrap {{ max-width:960px; margin:0 auto; padding:1rem; }}
    .card {{ background:#171c2b; border:1px solid #2a3150; border-radius:18px; padding:1rem; box-shadow:0 14px 40px rgba(0,0,0,.22); }}
    .msg {{ min-height:1.4rem; color:#b9c2f0; margin:.75rem 0; white-space:pre-wrap; }}
    .field {{ display:grid; gap:.35rem; margin:.75rem 0; }}
    input, button, textarea {{ font:inherit; }}
    input[type=password] {{ width:100%; box-sizing:border-box; padding:.7rem .9rem; border-radius:12px; border:1px solid #39405c; background:#0f1422; color:#eef2ff; }}
    button {{ padding:.7rem 1rem; border-radius:12px; border:0; background:#3d78ff; color:#fff; cursor:pointer; }}
    button.secondary {{ background:#2b3148; }}
    video, audio {{ width:100%; margin-top:.8rem; border-radius:14px; background:#070b15; }}
    .meta {{ color:#b8bfd8; font-size:.95rem; }}
    .hidden {{ display:none !important; }}
    @media (max-width: 640px) {{
      .wrap {{ padding:.75rem; }}
      .card {{ padding:.85rem; border-radius:14px; }}
      video, audio {{ border-radius:10px; }}
      button {{ width:100%; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1 id="title">分享影音</h1>
      <div class="meta" id="meta">讀取中...</div>
      <div class="msg" id="msg"></div>
      <form id="share-password-form" class="hidden">
        <div class="field">
          <label for="share-password">分享密碼</label>
          <input id="share-password" type="password" autocomplete="current-password" />
        </div>
        <button type="submit">解鎖影音</button>
      </form>
      <div id="player-host" class="hidden"></div>
      <div id="e2ee-note" class="meta hidden">此影音採端到端加密，只支援瀏覽器端解密播放，首次載入與快轉會較慢。</div>
    </div>
  </div>
  <script>
  const TOKEN = {token!r};

  function $(id) {{ return document.getElementById(id); }}
  function setMsg(text, bad=false) {{
    const el = $("msg");
    if (!el) return;
    el.textContent = text || "";
    el.style.color = bad ? "#ff9da1" : "#b9c2f0";
  }}
  function isSharePasswordResponse(res, json) {{
    const reason = String(json?.reason || "").trim();
    return [401, 403, 429].includes(Number(res?.status || 0))
      || !!json?.password_required
      || ["password_required", "password_invalid", "password_locked"].includes(reason);
  }}
  function showSharePasswordPrompt(message) {{
    const form = $("share-password-form");
    if (form) form.classList.remove("hidden");
    const input = $("share-password");
    if (input) {{
      try {{ input.focus(); }} catch (_err) {{}}
    }}
    const meta = $("meta");
    if (meta && (!meta.textContent || meta.textContent === "讀取中...")) {{
      meta.textContent = "此分享影音需要先解鎖";
    }}
    setMsg(message || "這部影音需要分享密碼");
  }}
  function formatProgressBytes(value) {{
    const num = Number(value || 0);
    if (!Number.isFinite(num) || num <= 0) return "0 B";
    if (num < 1024) return `${{num}} B`;
    if (num < 1024 * 1024) return `${{(num / 1024).toFixed(1)}} KB`;
    if (num < 1024 * 1024 * 1024) return `${{(num / 1024 / 1024).toFixed(1)}} MB`;
    return `${{(num / 1024 / 1024 / 1024).toFixed(2)}} GB`;
  }}
  async function readBlobWithProgress(response, onProgress) {{
    if (!response.body || typeof response.body.getReader !== "function") {{
      return response.blob();
    }}
    const total = Number(response.headers.get("Content-Length") || 0);
    const reader = response.body.getReader();
    const chunks = [];
    let loaded = 0;
    while (true) {{
      const {{ done, value }} = await reader.read();
      if (done) break;
      if (value) {{
        chunks.push(value);
        loaded += value.byteLength || 0;
        if (typeof onProgress === "function") onProgress(loaded, total);
      }}
    }}
    return new Blob(chunks, {{ type: response.headers.get("Content-Type") || "application/octet-stream" }});
  }}
  function browserSupportsNativeHls(mediaType="video") {{
    const probe = document.createElement(mediaType === "audio" ? "audio" : "video");
    return !!(probe && typeof probe.canPlayType === "function" && probe.canPlayType("application/vnd.apple.mpegurl"));
  }}
  let sharedHls = null;
  let sharedHlsLoadPromise = null;
  function destroySharedPlaybackArtifacts() {{
    if (sharedHls && typeof sharedHls.destroy === "function") {{
      try {{ sharedHls.destroy(); }} catch (_) {{}}
    }}
    sharedHls = null;
  }}
  function loadSharedHlsLibrary(url) {{
    if (window.Hls) return Promise.resolve(window.Hls);
    if (sharedHlsLoadPromise) return sharedHlsLoadPromise;
    sharedHlsLoadPromise = new Promise((resolve, reject) => {{
      const existing = document.querySelector('script[data-shared-hls-js="1"]');
      if (existing) {{
        existing.addEventListener("load", () => resolve(window.Hls || null), {{ once: true }});
        existing.addEventListener("error", () => reject(new Error("HLS.js 載入失敗")), {{ once: true }});
        return;
      }}
      const script = document.createElement("script");
      script.src = url;
      script.async = true;
      script.defer = true;
      script.dataset.sharedHlsJs = "1";
      script.onload = () => resolve(window.Hls || null);
      script.onerror = () => reject(new Error("HLS.js 載入失敗"));
      document.head.appendChild(script);
    }}).catch((err) => {{
      sharedHlsLoadPromise = null;
      throw err;
    }});
    return sharedHlsLoadPromise;
  }}
  function b64ToBytes(value) {{
    const binary = atob(String(value || "").replace(/\\s+/g, ""));
    const out = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
    return out;
  }}
  function b64UrlToBytes(value) {{
    const normalized = String(value || "").replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized + "=".repeat((4 - normalized.length % 4) % 4);
    return b64ToBytes(padded);
  }}
  function playerTimeBuffered(player, timeSeconds) {{
    if (!player?.buffered) return false;
    const target = Number(timeSeconds || 0);
    for (let i = 0; i < player.buffered.length; i += 1) {{
      if (target >= player.buffered.start(i) && target <= player.buffered.end(i)) return true;
    }}
    return false;
  }}
  function browserSupportsE2eeStreamV2() {{
    return Boolean(window.MediaSource && window.Worker && window.crypto?.subtle);
  }}
  function createSharedE2eeWorker() {{
    return new Worker("/js/workers/e2ee-stream-v2-worker.js?v=20260505-e2eev2");
  }}
  function decryptSharedChunkWithWorker(worker, keyBytes, nonce, ciphertext) {{
    return new Promise((resolve, reject) => {{
      const id = `${{Date.now()}}:${{Math.random().toString(16).slice(2)}}`;
      const keyBuffer = keyBytes.buffer.slice(0);
      const onMessage = (event) => {{
        const payload = event?.data || {{}};
        if (payload.id !== id) return;
        worker.removeEventListener("message", onMessage);
        if (payload.type === "decrypt-chunk-ok") resolve(payload.plaintext);
        else reject(new Error(payload.message || "E2EE chunk 解密失敗"));
      }};
      worker.addEventListener("message", onMessage);
      worker.postMessage({{
        type: "decrypt-chunk",
        id,
        keyBytes: keyBuffer,
        nonce,
        ciphertext,
      }}, [keyBuffer, ciphertext]);
    }});
  }}
  function appendSharedSourceBufferAsync(sourceBuffer, payload) {{
    return new Promise((resolve, reject) => {{
      const cleanup = () => {{
        sourceBuffer.removeEventListener("updateend", onEnd);
        sourceBuffer.removeEventListener("error", onErr);
      }};
      const onEnd = () => {{
        cleanup();
        resolve();
      }};
      const onErr = () => {{
        cleanup();
        reject(new Error("MediaSource append 失敗"));
      }};
      sourceBuffer.addEventListener("updateend", onEnd, {{ once: true }});
      sourceBuffer.addEventListener("error", onErr, {{ once: true }});
      sourceBuffer.appendBuffer(payload);
    }});
  }}
  function shareKeyFromFragment() {{
    const hash = String(window.location.hash || "");
    const params = new URLSearchParams(hash.startsWith("#") ? hash.slice(1) : hash);
    return String(params.get("vk") || "").trim();
  }}
    async function importShareKey(rawFragment) {{
      const bytes = b64UrlToBytes(rawFragment);
      if (bytes.byteLength < 32) {{
      throw new Error("分享連結缺少有效的片段金鑰，請向分享者重新取得完整連結。");
      }}
      return crypto.subtle.importKey("raw", bytes, {{ name: "AES-GCM", length: 256 }}, false, ["decrypt"]);
    }}
  async function unwrapSharedFileKeyBytes(envelopeText, fragmentKey) {{
    const envelope = JSON.parse(envelopeText || "{{}}");
    if (String(envelope.alg || "") !== "AES-GCM" || Number(envelope.v || 0) !== 1) {{
      throw new Error("分享金鑰封裝格式不支援，請分享者重新產生分享連結。");
    }}
    try {{
      const wrappingKey = await importShareKey(fragmentKey);
      return await crypto.subtle.decrypt(
        {{ name: "AES-GCM", iv: b64ToBytes(envelope.nonce) }},
        wrappingKey,
        b64ToBytes(envelope.ciphertext)
      );
    }} catch (_) {{
      throw new Error("分享授權無效或已被竄改。請確認你持有完整分享連結；若分享者遺失 fragment，只能重新產生分享。");
    }}
  }}
  async function unwrapSharedFileKey(envelopeText, fragmentKey) {{
    const rawKey = await unwrapSharedFileKeyBytes(envelopeText, fragmentKey);
    return crypto.subtle.importKey("raw", rawKey, {{ name: "AES-GCM" }}, true, ["decrypt"]);
  }}
  async function decryptJsonMetadata(fileKey, encryptedMetadata) {{
    const envelope = JSON.parse(encryptedMetadata || "{{}}");
    const plaintext = await crypto.subtle.decrypt({{ name: "AES-GCM", iv: b64ToBytes(envelope.nonce) }}, fileKey, b64ToBytes(envelope.ciphertext));
    return JSON.parse(new TextDecoder().decode(plaintext));
  }}
  async function decryptSharedE2eeBlob(blob, e2eeShare, fragmentKey) {{
    const fileKey = await unwrapSharedFileKey(e2eeShare.wrapped_file_key_envelope, fragmentKey);
    const plaintext = await crypto.subtle.decrypt({{ name: "AES-GCM", iv: b64ToBytes(e2eeShare.nonce) }}, fileKey, await blob.arrayBuffer());
    const metadata = await decryptJsonMetadata(fileKey, e2eeShare.encrypted_metadata);
    return {{
      blob: new Blob([plaintext], {{ type: metadata.mime_type || "application/octet-stream" }}),
      filename: metadata.filename || "media",
    }};
  }}
  async function fallbackSharedE2eeToFullDecrypt(player, playback, fragmentKey, message, seekTarget = null) {{
    setMsg(message || "已退回舊版完整解密播放。", false);
    setMsg("正在讀取 E2EE 分享授權：伺服器只會提供密文與分享封裝，不會接收原始密碼、raw file key 或 #vk。");
    const keyRes = await fetch(playback.e2ee_key_url, {{ credentials: "same-origin" }});
    const keyJson = await keyRes.json().catch(() => ({{}}));
    if (!keyRes.ok || !keyJson.ok || !keyJson.e2ee_share) throw new Error(keyJson.msg || "E2EE 分享解密資訊讀取失敗");
    const cipherRes = await fetch(playback.ciphertext_url, {{ credentials: "same-origin" }});
    if (!cipherRes.ok) throw new Error("E2EE 密文讀取失敗");
    const cipherBlob = await readBlobWithProgress(cipherRes, (loaded, total) => {{
      const summary = total > 0
        ? `${{formatProgressBytes(loaded)}} / ${{formatProgressBytes(total)}}`
        : formatProgressBytes(loaded);
      setMsg(`正在下載加密影音檔：${{summary}}。完成後會在瀏覽器端解密，不會把密碼或金鑰送到伺服器。`);
    }});
    setMsg("正在瀏覽器端解密影音。這一步不會把原始 E2EE 密碼、raw file key 或 #vk 傳到伺服器。");
    const decrypted = await decryptSharedE2eeBlob(cipherBlob, keyJson.e2ee_share, fragmentKey);
    player.src = URL.createObjectURL(decrypted.blob);
    if (seekTarget !== null) {{
      player.addEventListener("loadedmetadata", () => {{
        try {{ player.currentTime = seekTarget; }} catch (_) {{}}
      }}, {{ once: true }});
    }}
  }}
  async function attachSharedE2eeStreamV2(player, playback, fragmentKey) {{
    if (!browserSupportsE2eeStreamV2()) {{
      await fallbackSharedE2eeToFullDecrypt(player, playback, fragmentKey, "目前裝置不支援 E2EE Streaming v2，已退回舊版完整解密播放。");
      return;
    }}
    setMsg("正在讀取 E2EE 分享授權：strict E2EE 仍由瀏覽器端持有 fragment 與解密能力。");
    const manifestRes = await fetch(playback.manifest_url, {{ credentials: "same-origin" }});
    const manifestJson = await manifestRes.json().catch(() => ({{}}));
    if (!manifestRes.ok || manifestJson.available === false) {{
      await fallbackSharedE2eeToFullDecrypt(player, playback, fragmentKey, manifestJson.msg || "此 strict E2EE 影音尚未建立 Streaming v2 manifest，已退回舊版完整解密播放。");
      return;
    }}
    const rawKey = new Uint8Array(await unwrapSharedFileKeyBytes((await (await fetch(playback.e2ee_key_url, {{ credentials: "same-origin" }})).json()).e2ee_share.wrapped_file_key_envelope, fragmentKey));
    const mediaSource = new MediaSource();
    const objectUrl = URL.createObjectURL(mediaSource);
    player.src = objectUrl;
    setMsg("正在使用 E2EE Streaming v2：密文分段下載、瀏覽器端 Web Worker 解密，伺服器無法看到明文。");
    const worker = createSharedE2eeWorker();
    let nextChunk = 0;
    let sourceBuffer = null;
    let closed = false;
    const cleanup = () => {{
      if (closed) return;
      closed = true;
      try {{ worker.terminate(); }} catch (_) {{}}
    }};
    const fallback = async (message, seekTarget = null) => {{
      cleanup();
      await fallbackSharedE2eeToFullDecrypt(player, playback, fragmentKey, message, seekTarget);
    }};
    player.addEventListener("seeking", () => {{
      const target = Number(player.currentTime || 0);
      if (!playerTimeBuffered(player, target) && nextChunk < Number(manifestJson.chunk_count || 0)) {{
        fallback("偵測到尚未緩衝區段的快轉，已退回舊版完整解密播放以確保可用性。", target).catch((err) => setMsg(err.message || "E2EE fallback 失敗", true));
      }}
    }});
    mediaSource.addEventListener("sourceopen", () => {{
      try {{
        sourceBuffer = mediaSource.addSourceBuffer(manifestJson.content_type || "video/mp4");
      }} catch (err) {{
        fallback("目前裝置無法以 MediaSource 播放此 strict E2EE 影音，已退回舊版完整解密播放。").catch((fallbackErr) => setMsg(fallbackErr.message || "E2EE fallback 失敗", true));
        return;
      }}
      const pump = async () => {{
        if (closed || !sourceBuffer) return;
        if (nextChunk >= Number(manifestJson.chunk_count || 0)) {{
          if (mediaSource.readyState === "open" && !sourceBuffer.updating) {{
            try {{ mediaSource.endOfStream(); }} catch (_) {{}}
          }}
          cleanup();
          setMsg("正在使用 E2EE Streaming v2；若裝置或格式不支援快轉，系統會退回舊版完整解密播放。");
          return;
        }}
        const meta = manifestJson.chunks?.[nextChunk];
        const chunkRes = await fetch(playback.chunk_url_template.replace("__INDEX__", String(meta.chunk_index)), {{ credentials: "same-origin" }});
        if (!chunkRes.ok) {{
          const payload = await chunkRes.json().catch(() => ({{}}));
          throw new Error(payload.msg || `HTTP ${{chunkRes.status}}`);
        }}
        const cipher = await chunkRes.arrayBuffer();
        const plain = await decryptSharedChunkWithWorker(worker, new Uint8Array(rawKey), meta.nonce, cipher);
        await appendSharedSourceBufferAsync(sourceBuffer, new Uint8Array(plain));
        nextChunk += 1;
        setMsg(`正在使用 E2EE Streaming v2：已解密分段 ${{nextChunk}} / ${{manifestJson.chunk_count}}。`);
        queueMicrotask(() => {{
          pump().catch((err) => fallback(`E2EE Streaming v2 分段播放失敗，已退回舊版完整解密播放。 (${{err.message || "unknown"}})`));
        }});
      }};
      pump().catch((err) => fallback(err.message || "E2EE Streaming v2 初始化失敗"));
    }}, {{ once: true }});
  }}
  async function unlockShare(password) {{
    const res = await fetch(`/api/videos/shared/${{encodeURIComponent(TOKEN)}}/unlock`, {{
      method: "POST",
      credentials: "same-origin",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ password }}),
    }});
    const json = await res.json().catch(() => ({{}}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `HTTP ${{res.status}}`);
    return json;
  }}
  async function fetchJson(url) {{
    const res = await fetch(url, {{ credentials: "same-origin" }});
    const json = await res.json().catch(() => ({{}}));
    return {{ res, json }};
  }}
  async function loadSharedVideo() {{
    const metaEl = $("meta");
    if (metaEl) metaEl.textContent = "正在讀取分享資訊...";
    const meta = await fetchJson(`/api/videos/shared/${{encodeURIComponent(TOKEN)}}`);
    if (isSharePasswordResponse(meta.res, meta.json)) {{
      showSharePasswordPrompt(meta.json.msg || "這部影音需要分享密碼");
      return;
    }}
    if (!meta.res.ok || !meta.json.ok) throw new Error(meta.json.msg || `HTTP ${{meta.res.status}}`);
    const video = meta.json.video || {{}};
    $("title").textContent = video.title || "分享影音";
    $("meta").textContent = `${{video.owner_nickname || video.owner_username || "使用者"}} · ${{video.visibility || "unlisted"}}`;
    if (video.share_requires_fragment_key) {{
      const requirements = [];
      requirements.push("此 E2EE 影音必須使用完整分享連結");
      if (video.share_password_required) requirements.push("並輸入分享密碼");
      requirements.push("若遺失連結片段金鑰，分享者只能重新產生分享。");
      setMsg(requirements.join(" · "));
    }}
    if (metaEl) metaEl.textContent = `${{video.owner_nickname || video.owner_username || "使用者"}} · 準備讀取播放資訊`;
    const playback = await fetchJson(`/api/videos/shared/${{encodeURIComponent(TOKEN)}}/playback`);
    if (isSharePasswordResponse(playback.res, playback.json)) {{
      showSharePasswordPrompt(playback.json.msg || "這部影音需要分享密碼");
      return;
    }}
    if (!playback.res.ok || !playback.json.ok) throw new Error(playback.json.msg || `HTTP ${{playback.res.status}}`);
    await renderPlayback(video, playback.json);
  }}
  async function renderPlayback(video, playback) {{
    const host = $("player-host");
    host.classList.remove("hidden");
    const mediaTag = video.media_type === "audio" ? "audio" : "video";
    host.innerHTML = mediaTag === "audio"
      ? `<audio id="shared-player" controls preload="metadata"></audio>`
      : `<video id="shared-player" controls playsinline preload="metadata"></video>`;
    const player = $("shared-player");
    if (!player) return;
    destroySharedPlaybackArtifacts();
    if (playback.mode === "e2ee_stream_v2") {{
      $("e2ee-note").classList.remove("hidden");
      const fragmentKey = shareKeyFromFragment();
      if (!fragmentKey) {{
        throw new Error("此 E2EE 分享影音缺少連結片段金鑰，無法復原。請向分享者重新取得完整連結；若分享者也遺失，只能重新產生分享。");
      }}
      await attachSharedE2eeStreamV2(player, playback, fragmentKey);
      return;
    }}
    if (playback.mode === "e2ee_direct") {{
      $("e2ee-note").classList.remove("hidden");
      const fragmentKey = shareKeyFromFragment();
      if (!fragmentKey) {{
        throw new Error("此 E2EE 分享影音缺少連結片段金鑰，無法復原。請向分享者重新取得完整連結；若分享者也遺失，只能重新產生分享。");
      }}
      await fallbackSharedE2eeToFullDecrypt(player, playback, fragmentKey, "正在使用舊版完整解密播放。strict E2EE 不支援伺服器端轉檔、縮圖與內容掃描，速度會較慢。");
      return;
    }}
    if (playback.mode === "hls" && browserSupportsNativeHls(video.media_type)) {{
      player.src = playback.master_url || playback.fallback_url || "";
      setMsg("Safari / 原生 HLS 已啟用。");
      return;
    }}
    if (playback.mode === "hls" && playback.master_url) {{
      try {{
        const Hls = await loadSharedHlsLibrary(playback.hls_js_url || "/js/vendor/hls.light.min.js?v=20260505-hlsjs");
        if (!Hls || typeof Hls.isSupported !== "function" || !Hls.isSupported()) {{
          throw new Error("目前瀏覽器不支援 HLS.js 所需的 MediaSource");
        }}
        sharedHls = new Hls({{ enableWorker: true, backBufferLength: 30 }});
        sharedHls.on(Hls.Events.ERROR, (_event, data) => {{
          if (!data?.fatal) return;
          destroySharedPlaybackArtifacts();
          player.src = playback.fallback_url || playback.stream_url || "";
          setMsg(`HLS.js 播放失敗，已改用直接串流。${{data?.details ? ` (${{data.details}})` : ""}}`, true);
        }});
        sharedHls.loadSource(playback.master_url);
        sharedHls.attachMedia(player);
        setMsg("已使用 HLS.js 播放；桌機 Chrome / Firefox / Edge 可穩定播放 HLS。");
        return;
      }} catch (err) {{
        player.src = playback.fallback_url || playback.stream_url || "";
        setMsg(`HLS.js 初始化失敗，已改用直接串流。${{err?.message ? ` (${{err.message}})` : ""}}`, true);
        return;
      }}
    }}
    player.src = playback.fallback_url || playback.stream_url || "";
    setMsg(playback.stream_warning || (playback.high_performance_streaming ? "目前使用高效串流。" : "目前使用直接串流。"));
  }}
  $("share-password-form").addEventListener("submit", async (event) => {{
    event.preventDefault();
    try {{
      await unlockShare(($("share-password").value || "").trim());
      $("share-password-form").classList.add("hidden");
      setMsg("分享密碼驗證成功。");
      await loadSharedVideo();
    }} catch (err) {{
      setMsg(err.message || "分享密碼驗證失敗", true);
    }}
  }});
  loadSharedVideo().catch((err) => setMsg(err.message || "分享影音載入失敗", true));
  </script>
</body>
</html>"""

    @app.route("/api/videos/publish", methods=["POST"])
    @require_csrf
    def video_publish():
        actor, err = _actor_or_401()
        if err:
            return err
        data, cover_upload, err, status = _parse_publish_request()
        if err:
            return err, status
        sensitive = _reject_sensitive_share_fields(data)
        if sensitive:
            return sensitive
        conn = get_db()
        try:
            cover_result = None
            cover_storage_file = None
            if cover_upload and cover_upload.filename:
                rule = get_member_level_rule(conn, actor["effective_level"] or actor["member_level"])
                cover_result, cover_storage_file, cover_msg, cover_error = _store_video_cover_upload(
                    conn,
                    actor=actor,
                    member_rule=rule,
                    cover_upload=cover_upload,
                    privacy_mode="standard_plain",
                )
                if cover_msg:
                    conn.rollback()
                    return json_resp({"ok": False, "msg": cover_msg, "error": cover_error}), 400
            video = publish_video(
                conn,
                actor=actor,
                cloud_file_id=data.get("cloud_file_id"),
                title=data.get("title"),
                description=data.get("description") or "",
                visibility=data.get("visibility") or "public",
                cover_file_id=cover_result["file_id"] if cover_result else (data.get("cover_file_id") or None),
                share_password=data.get("share_password") or "",
                share_wrapped_file_key_envelope=data.get("share_wrapped_file_key_envelope") or "",
                share_expires_at=data.get("share_expires_at") or "",
                share_max_views=data.get("share_max_views") or 0,
            )
            file_row = conn.execute("SELECT * FROM uploaded_files WHERE id=?", (video["cloud_file_id"],)).fetchone()
            stream_asset, stream_warning = _maybe_prepare_stream_asset(
                conn,
                file_row=file_row,
                visibility=video["visibility"],
            )
            conn.commit()
            audit(
                "VIDEO_PUBLISH",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"video_id={video['id']},cloud_file_id={video['cloud_file_id']},visibility={video['visibility']}",
            )
            return json_resp({
                "ok": True,
                "video": video,
                "stream_asset": stream_asset,
                "stream_warning": stream_warning or "",
                "cover_file": ({**cover_result, "filename": safe_public_filename(cover_upload.filename)} if cover_result else None),
                "cover_storage_file": cover_storage_file,
            })
        except Exception as exc:
            conn.rollback()
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/upload", methods=["POST"])
    @require_csrf
    def video_upload_and_publish():
        actor, err = _actor_or_401()
        if err:
            return err
        uploaded = request.files.get("video") or request.files.get("file")
        if not uploaded or not uploaded.filename:
            return json_resp({"ok": False, "msg": "請選擇要上傳的影音檔", "error": "missing_file"}), 400
        if not _uploaded_file_is_media(uploaded):
            return json_resp({"ok": False, "msg": "只接受影片或音樂檔", "error": "not_media"}), 400
        sensitive = _reject_sensitive_share_fields(request.form)
        if sensitive:
            return sensitive
        privacy_mode = str(request.form.get("privacy_mode") or "standard_plain").strip() or "standard_plain"
        if privacy_mode not in {"standard_plain", "server_encrypted"}:
            return json_resp({"ok": False, "msg": "影音隱私模式不支援", "error": "unsupported_privacy_mode"}), 400
        cover_upload = request.files.get("cover")
        conn = get_db()
        try:
            ensure_cloud_drive_attachment_schema(conn)
            ensure_storage_album_schema(conn)
            rule = get_member_level_rule(conn, actor["effective_level"] or actor["member_level"])
            upload_result, msg = store_cloud_upload(
                conn,
                actor=actor,
                member_rule=rule,
                storage_root=storage_root,
                file_storage=uploaded,
                privacy_mode=privacy_mode,
                scan_now=True,
                server_file_fernet=server_file_fernet,
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg, "error": "upload_rejected"}), 400
            file_row = conn.execute("SELECT * FROM uploaded_files WHERE id=?", (upload_result["file_id"],)).fetchone()
            storage_file, storage_msg = create_storage_file_entry(
                conn,
                actor=actor,
                file_row=file_row,
                virtual_path=f"/Media/{upload_result['file_id']}-{safe_public_filename(uploaded.filename)}",
                display_name=safe_public_filename(uploaded.filename),
                source="video_upload",
            )
            if storage_msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": storage_msg, "error": "storage_entry_failed"}), 400
            cover_result = None
            cover_storage_file = None
            if cover_upload and cover_upload.filename:
                cover_result, cover_storage_file, cover_msg, cover_error = _store_video_cover_upload(
                    conn,
                    actor=actor,
                    member_rule=rule,
                    privacy_mode="server_encrypted" if privacy_mode == "server_encrypted" else "standard_plain",
                    cover_upload=cover_upload,
                )
                if cover_msg:
                    conn.rollback()
                    return json_resp({"ok": False, "msg": cover_msg, "error": cover_error}), 400
            video = publish_video(
                conn,
                actor=actor,
                cloud_file_id=upload_result["file_id"],
                title=request.form.get("title") or _default_media_title(uploaded),
                description=request.form.get("description") or "",
                visibility=request.form.get("visibility") or "public",
                cover_file_id=cover_result["file_id"] if cover_result else None,
                share_password=request.form.get("share_password") or "",
                share_wrapped_file_key_envelope=request.form.get("share_wrapped_file_key_envelope") or "",
                share_expires_at=request.form.get("share_expires_at") or "",
                share_max_views=request.form.get("share_max_views") or 0,
            )
            stream_asset, stream_warning = _maybe_prepare_stream_asset(
                conn,
                file_row=file_row,
                visibility=video["visibility"],
            )
            conn.commit()
            audit(
                "VIDEO_UPLOAD_PUBLISH",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"video_id={video['id']},cloud_file_id={video['cloud_file_id']},privacy_mode={privacy_mode},visibility={video['visibility']}",
            )
            return json_resp({
                "ok": True,
                "video": video,
                "file": {**upload_result, "filename": safe_public_filename(uploaded.filename)},
                "storage_file": storage_file,
                "stream_asset": stream_asset,
                "stream_warning": stream_warning or "",
                "cover_file": ({**cover_result, "filename": safe_public_filename(cover_upload.filename)} if cover_result else None),
                "cover_storage_file": cover_storage_file,
            })
        except Exception as exc:
            conn.rollback()
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/shared/videos/<token>", methods=["GET"])
    def shared_video_page(token):
        return Response(_shared_video_html(token), status=200, mimetype="text/html; charset=utf-8")

    @app.route("/api/videos/shared/<token>/unlock", methods=["POST"])
    def shared_video_unlock(token):
        conn = get_db()
        try:
            data = request.get_json(silent=True) or {}
            sensitive = _reject_sensitive_share_fields(data)
            if sensitive:
                return sensitive
            password = str(data.get("password") or "")
            row, reason = resolve_video_share_token(conn, token, password=password, password_verified=False)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            _grant_shared_video_session_access(token)
            conn.commit()
            return json_resp({"ok": True, "share_url": f"/shared/videos/{token}", "password_required": bool((row["share_password_required"] if "share_password_required" in row.keys() else row["password_required"]) or 0)})
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>", methods=["GET"])
    def shared_video_detail(token):
        conn = get_db()
        try:
            row, reason, password_verified, counted_in_session = _resolve_shared_video(conn, token)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            video, _ = shared_video_payload(conn, token, password_verified=password_verified, counted_in_session=counted_in_session)
            _count_shared_video_access(conn, row, token, counted_in_session)
            conn.commit()
            return json_resp({"ok": True, "video": video})
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>/playback", methods=["GET"])
    def shared_video_playback(token):
        conn = get_db()
        try:
            row, reason, _password_verified, _counted_in_session = _resolve_shared_video(conn, token)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            _count_shared_video_access(conn, row, token, _counted_in_session)
            file_row = _load_stream_file(conn, file_id=row["cloud_file_id"])
            payload = _playback_payload_for_file(conn, row=file_row, video_id=row["id"], shared_token=token)
            payload["video_id"] = int(row["id"])
            payload["can_prepare_stream"] = False
            payload["prepare_stream_url"] = ""
            conn.commit()
            return json_resp({"ok": True, **payload})
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>/stream", methods=["GET"])
    def shared_video_stream(token):
        conn = get_db()
        try:
            row, reason, _password_verified, _counted_in_session = _resolve_shared_video(conn, token)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            _count_shared_video_access(conn, row, token, _counted_in_session)
            file_row = _load_stream_file(conn, file_id=row["cloud_file_id"])
            path = resolve_file_storage_path(storage_root, file_row)
            if not path.exists():
                return json_resp({"ok": False, "msg": "實體檔案不存在", "error": "file_missing"}), 404
            filename = file_row["original_filename_plain_for_public"] or row["title"] or "video"
            mimetype = file_row["mime_type_plain_for_public"] or "video/mp4"
            if is_e2ee_file(file_row):
                conn.commit()
                return send_file(path, as_attachment=False, download_name=filename, mimetype="application/octet-stream", conditional=True)
            if is_server_encrypted_file(file_row):
                raw = decrypt_server_encrypted_bytes(path, server_file_fernet)
                conn.commit()
                return _send_bytes_with_range(raw, download_name=filename, mimetype=mimetype, range_header=request.headers.get("Range"))
            conn.commit()
            return send_file(path, as_attachment=False, download_name=filename, mimetype=mimetype, conditional=True)
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>/cover", methods=["GET"])
    def shared_video_cover(token):
        conn = get_db()
        try:
            row, reason, _password_verified, _counted_in_session = _resolve_shared_video(conn, token)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            _count_shared_video_access(conn, row, token, _counted_in_session)
            cover_file_id = row["cover_file_id"]
            if not cover_file_id:
                return json_resp({"ok": False, "msg": "此影音沒有封面", "error": "cover_not_found"}), 404
            cover_row = conn.execute(
                "SELECT * FROM uploaded_files WHERE id=? AND deleted_at IS NULL",
                (cover_file_id,),
            ).fetchone()
            if not cover_row:
                return json_resp({"ok": False, "msg": "封面檔案不存在", "error": "cover_file_not_found"}), 404
            path = resolve_file_storage_path(storage_root, cover_row)
            if not path.exists():
                return json_resp({"ok": False, "msg": "封面實體檔案不存在", "error": "cover_file_missing"}), 404
            filename = cover_row["original_filename_plain_for_public"] or "cover"
            mimetype = cover_row["mime_type_plain_for_public"] or mimetypes.guess_type(filename)[0] or "image/jpeg"
            if is_server_encrypted_file(cover_row):
                raw = decrypt_server_encrypted_bytes(path, server_file_fernet)
                conn.commit()
                return _send_bytes_with_range(raw, download_name=filename, mimetype=mimetype, range_header=request.headers.get("Range"))
            conn.commit()
            return send_file(path, as_attachment=False, download_name=filename, mimetype=mimetype, conditional=True)
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>/e2ee-key", methods=["GET"])
    def shared_video_e2ee_key(token):
        conn = get_db()
        try:
            row, reason, _password_verified, _counted_in_session = _resolve_shared_video(conn, token)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            _count_shared_video_access(conn, row, token, _counted_in_session)
            file_row = _load_stream_file(conn, file_id=row["cloud_file_id"])
            if not is_e2ee_file(file_row):
                return json_resp({"ok": False, "msg": "此影音不是端到端加密檔案"}), 400
            if not str((row["share_wrapped_file_key_envelope"] if "share_wrapped_file_key_envelope" in row.keys() else row["wrapped_file_key_envelope"]) or "").strip():
                return json_resp({"ok": False, "msg": "此 E2EE 影音尚未建立可分享的瀏覽器端解密授權", "error": "missing_share_key_wrap"}), 409
            conn.commit()
            return json_resp({
                "ok": True,
                "e2ee_share": {
                    "file_id": file_row["id"],
                    "privacy_mode": file_row["privacy_mode"],
                    "encrypted_metadata": file_row["original_filename_encrypted"],
                    "wrapped_file_key_envelope": row["share_wrapped_file_key_envelope"] if "share_wrapped_file_key_envelope" in row.keys() else row["wrapped_file_key_envelope"],
                    "encryption_algorithm": file_row["encryption_algorithm"],
                    "encryption_version": file_row["encryption_version"],
                    "nonce": file_row["nonce"],
                    "ciphertext_sha256": file_row["ciphertext_sha256"],
                },
            })
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>/e2ee-stream-v2/manifest", methods=["GET"])
    def shared_video_e2ee_stream_v2_manifest(token):
        conn = get_db()
        try:
            row, reason, _password_verified, _counted_in_session = _resolve_shared_video(conn, token)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            _count_shared_video_access(conn, row, token, _counted_in_session)
            file_row = _load_stream_file(conn, file_id=row["cloud_file_id"])
            if not is_e2ee_file(file_row):
                return json_resp({"ok": False, "msg": "此影音不是端到端加密檔案", "error": "not_e2ee"}), 400
            payload = serialize_manifest_for_client(conn, file_row=file_row, storage_root=storage_root)
            conn.commit()
            return json_resp(payload)
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>/e2ee-stream-v2/chunks/<int:chunk_index>", methods=["GET"])
    def shared_video_e2ee_stream_v2_chunk(token, chunk_index):
        conn = get_db()
        try:
            row, reason, _password_verified, _counted_in_session = _resolve_shared_video(conn, token)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            _count_shared_video_access(conn, row, token, _counted_in_session)
            file_row = _load_stream_file(conn, file_id=row["cloud_file_id"])
            if not is_e2ee_file(file_row):
                return json_resp({"ok": False, "msg": "此影音不是端到端加密檔案", "error": "not_e2ee"}), 400
            resolved, error = resolve_e2ee_chunk_response(conn, file_row=file_row, storage_root=storage_root, chunk_index=chunk_index)
            if error:
                status = 404 if error.get("error") == "chunk_not_found" else 409
                return json_resp(error), status
            conn.commit()
            response = Response(resolved["payload"], status=200, mimetype=resolved.get("content_type") or "application/octet-stream")
            response.headers["Content-Length"] = str(len(resolved["payload"]))
            response.headers["Cache-Control"] = "private, max-age=0, no-store"
            return response
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>/ciphertext", methods=["GET"])
    def shared_video_ciphertext(token):
        conn = get_db()
        try:
            row, reason, _password_verified, _counted_in_session = _resolve_shared_video(conn, token)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            _count_shared_video_access(conn, row, token, _counted_in_session)
            file_row = _load_stream_file(conn, file_id=row["cloud_file_id"])
            if not is_e2ee_file(file_row):
                return json_resp({"ok": False, "msg": "此影音不是端到端加密檔案"}), 400
            path = resolve_file_storage_path(storage_root, file_row)
            if not path.exists():
                return json_resp({"ok": False, "msg": "實體檔案不存在"}), 404
            conn.commit()
            return send_file(
                path,
                as_attachment=False,
                download_name=file_row["original_filename_plain_for_public"] or "e2ee.bin",
                mimetype="application/octet-stream",
                conditional=True,
            )
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>/hls/master.m3u8", methods=["GET"])
    def shared_video_hls_master(token):
        conn = get_db()
        try:
            row, reason, _password_verified, _counted_in_session = _resolve_shared_video(conn, token)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            _count_shared_video_access(conn, row, token, _counted_in_session)
            file_row = _load_stream_file(conn, file_id=row["cloud_file_id"])
            asset = get_stream_status(conn, file_row=file_row)
            if not asset or asset.get("status") != "ready" or not asset.get("master_manifest_path"):
                return json_resp({"ok": False, "msg": "影音串流尚未準備完成", "error": "stream_not_ready"}), 409
            path = resolve_file_storage_path(storage_root, {"storage_path": asset["master_manifest_path"]})
            conn.commit()
            return send_file(path, as_attachment=False, download_name="master.m3u8", mimetype="application/vnd.apple.mpegurl", conditional=True)
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>/hls/<variant>/playlist.m3u8", methods=["GET"])
    def shared_video_hls_variant_playlist(token, variant):
        conn = get_db()
        try:
            row, reason, _password_verified, _counted_in_session = _resolve_shared_video(conn, token)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            _count_shared_video_access(conn, row, token, _counted_in_session)
            file_row = _load_stream_file(conn, file_id=row["cloud_file_id"])
            asset = get_stream_status(conn, file_row=file_row)
            if not asset or asset.get("status") != "ready":
                return json_resp({"ok": False, "msg": "影音串流尚未準備完成", "error": "stream_not_ready"}), 409
            match = next((item for item in (asset.get("variants") or []) if item.get("name") == variant), None)
            if not match:
                return json_resp({"ok": False, "msg": "找不到串流變體", "error": "variant_not_found"}), 404
            path = resolve_file_storage_path(storage_root, {"storage_path": match["playlist_path"]})
            conn.commit()
            return send_file(path, as_attachment=False, download_name="playlist.m3u8", mimetype="application/vnd.apple.mpegurl", conditional=True)
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>/hls/<variant>/<segment>", methods=["GET"])
    def shared_video_hls_segment(token, variant, segment):
        conn = get_db()
        try:
            row, reason, _password_verified, _counted_in_session = _resolve_shared_video(conn, token)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            _count_shared_video_access(conn, row, token, _counted_in_session)
            file_row = _load_stream_file(conn, file_id=row["cloud_file_id"])
            asset = get_stream_status(conn, file_row=file_row)
            if not asset or asset.get("status") != "ready":
                return json_resp({"ok": False, "msg": "影音串流尚未準備完成", "error": "stream_not_ready"}), 409
            match = next((item for item in (asset.get("variants") or []) if item.get("name") == variant), None)
            if not match:
                return json_resp({"ok": False, "msg": "找不到串流變體", "error": "variant_not_found"}), 404
            if "/" in segment or ".." in segment:
                return json_resp({"ok": False, "msg": "無效的串流片段", "error": "invalid_segment"}), 400
            rel = next((item["path"] for item in (match.get("segments") or []) if item.get("filename") == segment), "")
            if not rel:
                if segment == "init.mp4" and match.get("init_segment_path"):
                    rel = match["init_segment_path"]
                else:
                    return json_resp({"ok": False, "msg": "找不到串流片段", "error": "segment_not_found"}), 404
            path = resolve_file_storage_path(storage_root, {"storage_path": rel})
            mimetype = "video/mp4" if segment.endswith(".mp4") or segment.endswith(".m4s") else "application/octet-stream"
            conn.commit()
            return send_file(path, as_attachment=False, download_name=segment, mimetype=mimetype, conditional=True)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/share-link", methods=["PUT", "DELETE"])
    @require_csrf
    def video_share_link_manage(video_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            video = get_video(conn, video_id, actor=actor)
            if not video or not video.get("can_edit"):
                return json_resp({"ok": False, "msg": "找不到影音", "error": "not_found"}), 404
            if request.method == "DELETE":
                revoke_video_share_link(conn, actor=actor, video_id=video_id)
                audit(
                    "VIDEO_SHARE_LINK_REVOKE",
                    get_client_ip(),
                    user=actor["username"],
                    success=True,
                    ua=get_ua(),
                    detail=f"video_id={int(video_id)}",
                )
                conn.commit()
                return json_resp({"ok": True, "share_link": None, "video_id": int(video_id)})
            data = request.get_json(silent=True) or {}
            sensitive = _reject_sensitive_share_fields(data)
            if sensitive:
                return sensitive
            share_link, msg = ensure_video_share_link(
                conn,
                actor=actor,
                video_id=video_id,
                password=data["share_password"] if "share_password" in data else None,
                wrapped_file_key_envelope=data["share_wrapped_file_key_envelope"] if "share_wrapped_file_key_envelope" in data else None,
                expires_at=data["share_expires_at"] if "share_expires_at" in data else None,
                max_views=data["share_max_views"] if "share_max_views" in data else None,
                regenerate=bool(data.get("regenerate")),
            )
            if msg:
                return json_resp({"ok": False, "msg": msg, "error": "share_link_update_failed"}), 400
            updated = get_video(conn, video_id, actor=actor)
            audit(
                "VIDEO_SHARE_LINK_UPDATE",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=(
                    f"video_id={int(video_id)},"
                    f"regenerate={1 if data.get('regenerate') else 0},"
                    f"password_required={1 if share_link and share_link.get('password_required') else 0},"
                    f"state={share_link.get('state') if share_link else 'unknown'}"
                ),
            )
            conn.commit()
            return json_resp({"ok": True, "share_link": share_link, "video": updated})
        except PermissionError as exc:
            conn.rollback()
            return _error_response(exc)
        except ValueError as exc:
            conn.rollback()
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos", methods=["GET"])
    @require_csrf
    def video_list():
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            videos = list_videos(
                conn,
                actor=actor,
                sort=request.args.get("sort") or "new",
                page=request.args.get("page") or 1,
            )
            return json_resp({"ok": True, "videos": videos})
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>", methods=["GET"])
    @require_csrf
    def video_detail(video_id):
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            video = get_video(conn, video_id, actor=actor)
            if not video:
                return json_resp({"ok": False, "msg": "找不到影片", "error": "not_found"}), 404
            comments = list_video_comments(conn, actor=actor, video_id=video_id, limit=100)
            return json_resp({"ok": True, "video": video, "comments": comments})
        except PermissionError as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/media/<file_id>/prepare-stream", methods=["POST"])
    @require_csrf
    def media_prepare_stream(file_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            ensure_media_stream_schema(conn)
            row = _load_stream_file(conn, file_id=file_id)
            _assert_stream_prepare_allowed(actor, row)
            if is_e2ee_file(row):
                return json_resp({"ok": False, "msg": "E2EE 影音只支援瀏覽器端解密播放，不建立伺服器端串流衍生檔", "error": "e2ee_direct_only"}), 409
            asset = prepare_stream_asset(
                conn,
                file_row=row,
                storage_root=storage_root,
                server_file_fernet=server_file_fernet,
                ffprobe_bin=ffprobe_bin,
                ffmpeg_bin=ffmpeg_bin,
            )
            conn.commit()
            audit(
                "MEDIA_STREAM_PREPARE",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"file_id={file_id},status={asset.get('status')}",
            )
            return json_resp({"ok": True, "asset": asset})
        except Exception as exc:
            conn.rollback()
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/media/<file_id>/e2ee-stream-v2", methods=["POST"])
    @require_csrf
    def media_prepare_e2ee_stream_v2(file_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            ensure_e2ee_stream_v2_schema(conn)
            row = _load_stream_file(conn, file_id=file_id)
            _assert_stream_prepare_allowed(actor, row)
            if not is_e2ee_file(row):
                return json_resp({"ok": False, "msg": "只有 strict E2EE 影音可建立 Streaming v2", "error": "not_e2ee"}), 400
            if request.is_json:
                return json_resp({"ok": False, "msg": "E2EE Streaming v2 準備需要 multipart bundle 上傳", "error": "multipart_required"}), 400
            bundle = request.files.get("bundle")
            manifest_json = request.form.get("manifest_json") or ""
            if not bundle or not getattr(bundle, "filename", ""):
                return json_resp({"ok": False, "msg": "缺少 E2EE Streaming v2 bundle", "error": "missing_bundle"}), 400
            if not manifest_json.strip():
                return json_resp({"ok": False, "msg": "缺少 E2EE Streaming v2 manifest", "error": "missing_manifest"}), 400
            try:
                manifest_payload = json.loads(manifest_json)
            except Exception:
                return json_resp({"ok": False, "msg": "E2EE Streaming v2 manifest JSON 不正確", "error": "invalid_manifest_json"}), 400
            sensitive = _reject_sensitive_share_fields(manifest_payload)
            if sensitive:
                return sensitive
            asset = upsert_e2ee_stream_v2_asset(
                conn,
                file_row=row,
                storage_root=storage_root,
                manifest_payload=manifest_payload,
                bundle_bytes=bundle.read(),
            )
            conn.commit()
            audit(
                "MEDIA_E2EE_STREAM_V2_PREPARE",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"file_id={file_id},chunks={asset.get('chunk_count', 0)}",
            )
            return json_resp({"ok": True, "asset": asset})
        except Exception as exc:
            conn.rollback()
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/e2ee-stream-v2/manifest", methods=["GET"])
    @require_csrf
    def video_e2ee_stream_v2_manifest(video_id):
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            ensure_e2ee_stream_v2_schema(conn)
            video = get_video(conn, video_id, actor=actor, for_stream=True)
            if not video:
                return json_resp({"ok": False, "msg": "找不到影片", "error": "not_found"}), 404
            row = _load_stream_file(conn, file_id=video["cloud_file_id"])
            if not is_e2ee_file(row):
                return json_resp({"ok": False, "msg": "此影音不是端到端加密檔案", "error": "not_e2ee"}), 400
            return json_resp(serialize_manifest_for_client(conn, file_row=row, storage_root=storage_root))
        except PermissionError as exc:
            return _error_response(exc)
        except ValueError as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/e2ee-stream-v2/chunks/<int:chunk_index>", methods=["GET"])
    @require_csrf
    def video_e2ee_stream_v2_chunk(video_id, chunk_index):
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            ensure_e2ee_stream_v2_schema(conn)
            video = get_video(conn, video_id, actor=actor, for_stream=True)
            if not video:
                return json_resp({"ok": False, "msg": "找不到影片", "error": "not_found"}), 404
            row = _load_stream_file(conn, file_id=video["cloud_file_id"])
            if not is_e2ee_file(row):
                return json_resp({"ok": False, "msg": "此影音不是端到端加密檔案", "error": "not_e2ee"}), 400
            resolved, error = resolve_e2ee_chunk_response(conn, file_row=row, storage_root=storage_root, chunk_index=chunk_index)
            if error:
                status = 404 if error.get("error") == "chunk_not_found" else 409
                return json_resp(error), status
            response = Response(resolved["payload"], status=200, mimetype=resolved.get("content_type") or "application/octet-stream")
            response.headers["Content-Length"] = str(len(resolved["payload"]))
            response.headers["Cache-Control"] = "private, max-age=0, no-store"
            return response
        except PermissionError as exc:
            return _error_response(exc)
        except ValueError as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/media/<file_id>/stream-status", methods=["GET"])
    @require_csrf
    def media_stream_status(file_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            ensure_media_stream_schema(conn)
            row = _load_stream_file(conn, file_id=file_id)
            _assert_stream_prepare_allowed(actor, row)
            return json_resp({"ok": True, "asset": get_stream_status(conn, file_row=row)})
        except Exception as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/playback", methods=["GET"])
    @require_csrf
    def video_playback(video_id):
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            ensure_media_stream_schema(conn)
            video = get_video(conn, video_id, actor=actor, for_stream=True)
            if not video:
                return json_resp({"ok": False, "msg": "找不到影片", "error": "not_found"}), 404
            row = _load_stream_file(conn, file_id=video["cloud_file_id"])
            payload = _playback_payload_for_file(conn, row=row, video_id=video_id)
            payload["video_id"] = int(video_id)
            payload["can_prepare_stream"] = bool(video.get("can_edit")) and not is_e2ee_file(row)
            payload["prepare_stream_url"] = video.get("prepare_stream_url") or ""
            return json_resp({"ok": True, **payload})
        except PermissionError as exc:
            return _error_response(exc)
        except ValueError as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/stream", methods=["GET"])
    @require_csrf
    def video_stream(video_id):
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            video = get_video(conn, video_id, actor=actor, for_stream=True)
            if not video:
                return json_resp({"ok": False, "msg": "找不到影片", "error": "not_found"}), 404
            row = conn.execute(
                "SELECT * FROM uploaded_files WHERE id=? AND deleted_at IS NULL",
                (video["cloud_file_id"],),
            ).fetchone()
            if not row:
                return json_resp({"ok": False, "msg": "找不到影片檔案", "error": "file_not_found"}), 404
            path = resolve_file_storage_path(storage_root, row)
            if not path.exists():
                return json_resp({"ok": False, "msg": "實體檔案不存在", "error": "file_missing"}), 404
            filename = row["original_filename_plain_for_public"] or video["title"] or "video"
            mimetype = row["mime_type_plain_for_public"] or "video/mp4"
            if is_e2ee_file(row):
                return send_file(
                    path,
                    as_attachment=False,
                    download_name=filename,
                    mimetype="application/octet-stream",
                    conditional=True,
                )
            if is_server_encrypted_file(row):
                raw = decrypt_server_encrypted_bytes(path, server_file_fernet)
                return _send_bytes_with_range(raw, download_name=filename, mimetype=mimetype, range_header=request.headers.get("Range"))
            return send_file(path, as_attachment=False, download_name=filename, mimetype=mimetype, conditional=True)
        except PermissionError as exc:
            return _error_response(exc)
        except ValueError as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/hls/master.m3u8", methods=["GET"])
    @require_csrf
    def video_hls_master(video_id):
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            ensure_media_stream_schema(conn)
            video = get_video(conn, video_id, actor=actor, for_stream=True)
            if not video:
                return json_resp({"ok": False, "msg": "找不到影片", "error": "not_found"}), 404
            row = _load_stream_file(conn, file_id=video["cloud_file_id"])
            asset = get_stream_status(conn, file_row=row)
            if not asset or asset.get("status") != "ready" or not asset.get("master_manifest_path"):
                return json_resp({"ok": False, "msg": "影音串流尚未準備完成", "error": "stream_not_ready"}), 409
            path = resolve_file_storage_path(storage_root, {"storage_path": asset["master_manifest_path"]})
            return send_file(path, as_attachment=False, download_name="master.m3u8", mimetype="application/vnd.apple.mpegurl", conditional=True)
        except PermissionError as exc:
            return _error_response(exc)
        except ValueError as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/hls/<variant>/playlist.m3u8", methods=["GET"])
    @require_csrf
    def video_hls_variant_playlist(video_id, variant):
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            ensure_media_stream_schema(conn)
            video = get_video(conn, video_id, actor=actor, for_stream=True)
            if not video:
                return json_resp({"ok": False, "msg": "找不到影片", "error": "not_found"}), 404
            row = _load_stream_file(conn, file_id=video["cloud_file_id"])
            asset = get_stream_status(conn, file_row=row)
            if not asset or asset.get("status") != "ready":
                return json_resp({"ok": False, "msg": "影音串流尚未準備完成", "error": "stream_not_ready"}), 409
            match = next((item for item in (asset.get("variants") or []) if item.get("name") == variant), None)
            if not match:
                return json_resp({"ok": False, "msg": "找不到串流變體", "error": "variant_not_found"}), 404
            path = resolve_file_storage_path(storage_root, {"storage_path": match["playlist_path"]})
            return send_file(path, as_attachment=False, download_name="playlist.m3u8", mimetype="application/vnd.apple.mpegurl", conditional=True)
        except PermissionError as exc:
            return _error_response(exc)
        except ValueError as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/hls/<variant>/<segment>", methods=["GET"])
    @require_csrf
    def video_hls_segment(video_id, variant, segment):
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            ensure_media_stream_schema(conn)
            video = get_video(conn, video_id, actor=actor, for_stream=True)
            if not video:
                return json_resp({"ok": False, "msg": "找不到影片", "error": "not_found"}), 404
            row = _load_stream_file(conn, file_id=video["cloud_file_id"])
            asset = get_stream_status(conn, file_row=row)
            if not asset or asset.get("status") != "ready":
                return json_resp({"ok": False, "msg": "影音串流尚未準備完成", "error": "stream_not_ready"}), 409
            match = next((item for item in (asset.get("variants") or []) if item.get("name") == variant), None)
            if not match:
                return json_resp({"ok": False, "msg": "找不到串流變體", "error": "variant_not_found"}), 404
            if "/" in segment or ".." in segment:
                return json_resp({"ok": False, "msg": "無效的串流片段", "error": "invalid_segment"}), 400
            rel = next((item["path"] for item in (match.get("segments") or []) if item.get("filename") == segment), "")
            if not rel:
                if segment == "init.mp4" and match.get("init_segment_path"):
                    rel = match["init_segment_path"]
                else:
                    return json_resp({"ok": False, "msg": "找不到串流片段", "error": "segment_not_found"}), 404
            path = resolve_file_storage_path(storage_root, {"storage_path": rel})
            mimetype = "video/mp4" if segment.endswith(".mp4") or segment.endswith(".m4s") else "application/octet-stream"
            return send_file(path, as_attachment=False, download_name=segment, mimetype=mimetype, conditional=True)
        except PermissionError as exc:
            return _error_response(exc)
        except ValueError as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/cover", methods=["GET"])
    @require_csrf
    def video_cover(video_id):
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            video = get_video(conn, video_id, actor=actor)
            if not video:
                return json_resp({"ok": False, "msg": "找不到影音", "error": "not_found"}), 404
            cover_file_id = video.get("cover_file_id")
            if not cover_file_id:
                return json_resp({"ok": False, "msg": "此影音沒有封面", "error": "cover_not_found"}), 404
            row = conn.execute(
                "SELECT * FROM uploaded_files WHERE id=? AND deleted_at IS NULL",
                (cover_file_id,),
            ).fetchone()
            if not row:
                return json_resp({"ok": False, "msg": "封面檔案不存在", "error": "cover_file_not_found"}), 404
            path = resolve_file_storage_path(storage_root, row)
            if not path.exists():
                return json_resp({"ok": False, "msg": "封面實體檔案不存在", "error": "cover_file_missing"}), 404
            filename = row["original_filename_plain_for_public"] or "cover"
            mimetype = row["mime_type_plain_for_public"] or mimetypes.guess_type(filename)[0] or "image/jpeg"
            if is_server_encrypted_file(row):
                try:
                    raw = decrypt_server_encrypted_bytes(path, server_file_fernet)
                except ValueError as exc:
                    return _svg_placeholder_response(str(exc))
                return _send_bytes_with_range(raw, download_name=filename, mimetype=mimetype, range_header=request.headers.get("Range"))
            return send_file(path, as_attachment=False, download_name=filename, mimetype=mimetype, conditional=True)
        except PermissionError as exc:
            return _error_response(exc)
        except ValueError as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/view", methods=["POST"])
    @require_csrf
    def video_view(video_id):
        actor, err = _actor_or_401()
        if err:
            return err
        data, err, status = _parse_json_body()
        if err:
            return err, status
        conn = get_db()
        try:
            result = record_video_view(
                conn,
                actor=actor,
                video_id=video_id,
                ip=get_client_ip(),
                watch_seconds=data.get("watch_seconds") or 0,
                completed=bool(data.get("completed")),
            )
            conn.commit()
            return json_resp({"ok": True, **result})
        except Exception as exc:
            conn.rollback()
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/like", methods=["POST", "DELETE"])
    @require_csrf
    def video_like(video_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            video = set_video_like(conn, actor=actor, video_id=video_id, liked=request.method == "POST")
            conn.commit()
            return json_resp({"ok": True, "video": video})
        except Exception as exc:
            conn.rollback()
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/comments", methods=["GET", "POST"])
    @require_csrf
    def video_comments(video_id):
        actor = get_current_user_ctx()
        if request.method == "POST":
            actor, err = _actor_or_401()
            if err:
                return err
            data, err, status = _parse_json_body()
            if err:
                return err, status
        conn = get_db()
        try:
            if request.method == "GET":
                comments = list_video_comments(conn, actor=actor, video_id=video_id, limit=100)
                return json_resp({"ok": True, "comments": comments})
            comment = add_video_comment(
                conn,
                actor=actor,
                video_id=video_id,
                content=data.get("content"),
                parent_id=data.get("parent_id"),
            )
            conn.commit()
            audit(
                "VIDEO_COMMENT",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"video_id={video_id},comment_id={comment['id']}",
            )
            return json_resp({"ok": True, "comment": comment})
        except Exception as exc:
            conn.rollback()
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/comment", methods=["POST"])
    @require_csrf
    def video_comment_alias(video_id):
        return video_comments(video_id)

    @app.route("/api/videos/<int:video_id>/tip", methods=["POST"])
    @require_csrf
    def video_tip(video_id):
        actor, err = _actor_or_401()
        if err:
            return err
        data, err, status = _parse_json_body()
        if err:
            return err, status
        conn = get_db()
        try:
            amount = int(data.get("amount") or 0)
            min_points = max(1, int(_settings_float("video_tip_min_points", 1)))
            if amount < min_points:
                return json_resp({"ok": False, "msg": f"投幣至少需要 {min_points} 點", "error": "tip_amount_too_small"}), 400
            ensure_video_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            result = tip_video(
                conn,
                points_service=points_service,
                actor=actor,
                video_id=video_id,
                amount=amount,
                fee_percent=_settings_float("video_tip_fee_percent", 5),
                idempotency_key=request.headers.get("Idempotency-Key") or data.get("idempotency_key"),
            )
            conn.commit()
            audit(
                "VIDEO_TIP",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"video_id={video_id},amount={result['tip']['amount_points']},fee={result['tip']['fee_points']}",
            )
            return json_resp(result)
        except Exception as exc:
            conn.rollback()
            return _error_response(exc)
        finally:
            conn.close()
