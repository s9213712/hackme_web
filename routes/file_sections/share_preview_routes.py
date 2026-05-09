import json

from flask import request, send_file

from services.media.previews import build_preview_metadata, preview_category
from services.storage.cloud_drive import (
    can_download_file,
    get_cloud_drive_security_policy,
    is_e2ee_file,
    resolve_file_storage_path,
)
from services.storage.storage_albums import (
    create_share_link,
    ensure_storage_album_schema,
    list_share_links,
    mark_album_share_link_accessed,
    mark_share_link_accessed,
    public_album_payload,
    resolve_album_share_file,
    resolve_album_share_token,
    resolve_share_token,
    revoke_share_link,
)
from services.security.upload_security import log_file_access


def register_file_share_preview_routes(app, ctx):
    get_db = ctx["get_db"]
    get_client_ip = ctx["get_client_ip"]
    get_ua = ctx["get_ua"]
    audit = ctx["audit"]
    json_resp = ctx["json_resp"]
    require_csrf = ctx["require_csrf"]
    require_csrf_safe = ctx["require_csrf_safe"]
    storage_root = ctx["storage_root"]

    actor_or_401 = ctx["actor_or_401"]
    read_readable_file_path = ctx["readable_file_path"]
    decryption_unavailable_preview = ctx["decryption_unavailable_preview"]
    requires_download_warning = ctx["requires_download_warning"]
    preview_allowed_by_policy = ctx["preview_allowed_by_policy"]
    preview_row_with_storage_fallback = ctx["preview_row_with_storage_fallback"]
    send_readable_file = ctx["send_readable_file"]
    svg_placeholder_response = ctx["svg_placeholder_response"]

    # 保留原 route block 的 helper 名稱，避免搬動時混入行為改寫。
    _actor_or_401 = actor_or_401
    _readable_file_path = read_readable_file_path
    _decryption_unavailable_preview = decryption_unavailable_preview
    _requires_download_warning = requires_download_warning
    _preview_allowed_by_policy = preview_allowed_by_policy
    _preview_row_with_storage_fallback = preview_row_with_storage_fallback
    _send_readable_file = send_readable_file
    _svg_placeholder_response = svg_placeholder_response

    @app.route("/api/storage/share-links", methods=["GET", "POST"])
    @require_csrf_safe
    def storage_share_links():
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            ensure_storage_album_schema(conn)
            if request.method == "GET":
                links = list_share_links(conn, actor=actor, storage_file_id=request.args.get("storage_file_id"))
                return json_resp({"ok": True, "share_links": links})
            try:
                data = request.get_json(force=True)
            except Exception:
                return json_resp({"ok": False, "msg": "請求 JSON 格式錯誤"}), 400
            link, msg = create_share_link(
                conn,
                actor=actor,
                storage_file_id=data.get("storage_file_id"),
                expires_at=data.get("expires_at") or None,
                can_preview=bool(data.get("can_preview", False)),
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("STORAGE_SHARE_LINK_CREATE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"share_link_id={link['id']}")
            return json_resp({"ok": True, "share_link": link})
        finally:
            conn.close()

    @app.route("/api/storage/share-links/<link_id>/revoke", methods=["POST"])
    @require_csrf
    def storage_share_link_revoke(link_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            link, msg = revoke_share_link(conn, actor=actor, link_id=link_id)
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 404
            conn.commit()
            audit("STORAGE_SHARE_LINK_REVOKE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"share_link_id={link_id}")
            return json_resp({"ok": True, "share_link": link})
        finally:
            conn.close()

    @app.route("/api/storage/shared/<token>/download", methods=["GET"])
    def storage_share_link_download(token):
        conn = get_db()
        try:
            row, reason = resolve_share_token(conn, token)
            if not row:
                return json_resp({"ok": False, "msg": "分享連結不存在或已失效", "reason": reason}), 404
            policy = get_cloud_drive_security_policy(conn)
            if policy.get("block_unclean_downloads") and not is_e2ee_file(row) and row["scan_status"] not in {"clean", "not_required"}:
                return json_resp({"ok": False, "msg": "檔案尚未通過安全檢查"}), 403
            if _requires_download_warning(policy, row):
                confirmed = (
                    request.args.get("confirm_high_risk") == "1"
                    or request.headers.get("X-Confirm-High-Risk-Download", "").lower() in {"1", "true", "yes"}
                )
                if not confirmed:
                    return json_resp({
                        "ok": False,
                        "requires_confirmation": True,
                        "msg": "此分享檔案為高風險或無法完整掃描，請確認信任來源後再下載。",
                        "risk_level": row["risk_level"],
                        "scan_status": row["scan_status"],
                    }), 409
            path = resolve_file_storage_path(storage_root, row)
            if not path.exists():
                return json_resp({"ok": False, "msg": "實體檔案不存在"}), 404
            mark_share_link_accessed(conn, row["id"])
            log_file_access(conn, file_id=row["file_id"], actor_user_id=None, action="storage_share_download", result="allowed", reason="share_link", ip=get_client_ip(), user_agent=get_ua())
            conn.commit()
            response = _send_readable_file(row, as_attachment=True, download_name=row["display_name"] or row["original_filename_plain_for_public"] or "download.bin")
            if response is None:
                return json_resp({"ok": False, "msg": "實體檔案不存在"}), 404
            return response
        finally:
            conn.close()

    def _html_safe_json(value):
        return (
            json.dumps(str(value or ""))
            .replace("&", "\\u0026")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029")
        )

    @app.route("/shared/albums/<token>", methods=["GET"])
    def storage_album_share_page(token):
        safe_token = _html_safe_json(token)
        return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>分享相簿</title>
  <style>
    body {{ margin: 0; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f7f9; color: #172033; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 32px 20px; }}
    .meta {{ color: #667085; margin: 8px 0 24px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 16px; }}
    .tile {{ background: #fff; border: 1px solid #dde3ea; border-radius: 8px; overflow: hidden; }}
    .thumb {{ aspect-ratio: 1 / 1; display: grid; place-items: center; background: #edf1f5; color: #667085; }}
    .thumb img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
    .name {{ padding: 10px 12px; overflow-wrap: anywhere; font-size: 14px; }}
    .empty {{ padding: 24px; background: #fff; border: 1px solid #dde3ea; border-radius: 8px; }}
    .password-panel {{ display: none; margin: 16px 0 24px; padding: 16px; background: #fff; border: 1px solid #dde3ea; border-radius: 8px; }}
    .password-panel.show {{ display: block; }}
    .password-row {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
    .password-row input {{ min-width: 220px; flex: 1; padding: 10px 12px; border: 1px solid #c7d0dc; border-radius: 6px; }}
    .password-row button {{ padding: 10px 14px; border: 0; border-radius: 6px; background: #2357d9; color: #fff; cursor: pointer; }}
  </style>
</head>
<body>
  <main>
    <h1 id="album-title">分享相簿</h1>
    <div class="meta" id="album-meta">讀取中...</div>
    <form class="password-panel" id="album-password-panel">
      <label for="album-password-input">這本相簿需要分享密碼</label>
      <div class="password-row">
        <input type="password" id="album-password-input" autocomplete="current-password" placeholder="輸入分享密碼">
        <button type="submit">開啟相簿</button>
      </div>
    </form>
    <div class="grid" id="album-files"></div>
  </main>
  <script>
  const SHARE_KEY = {safe_token};
  const titleEl = document.getElementById("album-title");
  const metaEl = document.getElementById("album-meta");
  const filesEl = document.getElementById("album-files");
  const passwordPanel = document.getElementById("album-password-panel");
  const passwordInput = document.getElementById("album-password-input");
  let sharePassword = "";
  function fileKind(file) {{
    const mime = String(file.mime_type || "").toLowerCase();
    if (mime.startsWith("image/")) return "image";
    if (mime.startsWith("video/")) return "video";
    return "file";
  }}
  function esc(value) {{
    return String(value || "").replace(/[&<>"']/g, (ch) => ({{ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }}[ch]));
  }}
  function fileUrl(file, inline) {{
    const raw = file.download_url || "#";
    try {{
      const url = new URL(raw, window.location.origin);
      if (sharePassword) url.searchParams.set("password", sharePassword);
      if (inline) url.searchParams.set("inline", "1");
      return url.pathname + url.search;
    }} catch (err) {{
      return raw;
    }}
  }}
  function loadAlbum() {{
    const headers = sharePassword ? {{ "X-Album-Share-Password": sharePassword }} : {{}};
    fetch(`/api/storage/shared/albums/${{encodeURIComponent(SHARE_KEY)}}`, {{ headers }})
    .then((res) => res.json().then((body) => ({{ status: res.status, body }})))
    .then((result) => {{
      if (!result.body.ok) {{
        if (result.body.reason === "password_required" || result.body.reason === "password_invalid") {{
          passwordPanel.classList.add("show");
          metaEl.textContent = result.body.reason === "password_invalid" ? "密碼不正確，請重新輸入。" : "請輸入分享密碼。";
          filesEl.innerHTML = "";
          passwordInput.focus();
          return;
        }}
        throw new Error(result.body.msg || "分享相簿不存在或已失效");
      }}
      passwordPanel.classList.remove("show");
      const album = result.body.album || {{}};
      titleEl.textContent = album.title || "分享相簿";
      metaEl.textContent = `${{(album.files || []).length}} 個檔案${{album.description ? " · " + album.description : ""}}`;
      if (!album.files || !album.files.length) {{
        filesEl.innerHTML = '<div class="empty">這本相簿目前沒有可顯示的檔案</div>';
        return;
      }}
      filesEl.innerHTML = album.files.map((file) => {{
        const kind = fileKind(file);
        const href = fileUrl(file, false);
        const inlineHref = fileUrl(file, true);
        const safeHref = esc(href);
        const thumb = kind === "image"
          ? `<a class="thumb" href="${{safeHref}}" target="_blank" rel="noreferrer"><img src="${{esc(inlineHref)}}" alt=""></a>`
          : `<a class="thumb" href="${{safeHref}}" target="_blank" rel="noreferrer">${{esc(kind)}}</a>`;
        return `<article class="tile">${{thumb}}<div class="name">${{esc(file.display_name || file.file_id || "file")}}</div></article>`;
      }}).join("");
    }})
    .catch((err) => {{
      titleEl.textContent = "分享相簿無法開啟";
      metaEl.textContent = err.message || "分享相簿不存在或已失效";
      filesEl.innerHTML = "";
    }});
  }}
  passwordPanel.addEventListener("submit", (event) => {{
    event.preventDefault();
    sharePassword = passwordInput.value || "";
    loadAlbum();
  }});
  loadAlbum();
  </script>
</body>
</html>"""

    def _album_share_password_from_request():
        return request.headers.get("X-Album-Share-Password") or request.args.get("password") or ""

    def _album_share_error_response(reason):
        if reason == "password_required":
            return json_resp({
                "ok": False,
                "msg": "這本相簿需要分享密碼",
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
        return json_resp({"ok": False, "msg": "分享相簿不存在或已失效", "reason": reason}), 404

    @app.route("/api/storage/shared/albums/<token>", methods=["GET"])
    def storage_album_share_api(token):
        conn = get_db()
        try:
            row, reason = resolve_album_share_token(conn, token, _album_share_password_from_request())
            if not row:
                return _album_share_error_response(reason)
            album = public_album_payload(conn, row)
            mark_album_share_link_accessed(conn, row["id"])
            conn.commit()
            return json_resp({"ok": True, "album": album})
        finally:
            conn.close()

    @app.route("/api/storage/shared/albums/<token>/files/<file_id>/download", methods=["GET"])
    def storage_album_share_file_download(token, file_id):
        conn = get_db()
        try:
            resolved, reason = resolve_album_share_file(conn, token, file_id, _album_share_password_from_request())
            if not resolved:
                if reason in {"password_required", "password_invalid"}:
                    return _album_share_error_response(reason)
                return json_resp({"ok": False, "msg": "分享檔案不存在或已失效", "reason": reason}), 404
            share = resolved["share"]
            row = resolved["file"]
            policy = get_cloud_drive_security_policy(conn)
            if policy.get("block_unclean_downloads") and not is_e2ee_file(row) and row["scan_status"] not in {"clean", "not_required"}:
                return json_resp({"ok": False, "msg": "檔案尚未通過安全檢查"}), 403
            if _requires_download_warning(policy, row):
                confirmed = (
                    request.args.get("confirm_high_risk") == "1"
                    or request.headers.get("X-Confirm-High-Risk-Download", "").lower() in {"1", "true", "yes"}
                )
                if not confirmed:
                    return json_resp({
                        "ok": False,
                        "requires_confirmation": True,
                        "msg": "此分享檔案為高風險或無法完整掃描，請確認信任來源後再下載。",
                        "risk_level": row["risk_level"],
                        "scan_status": row["scan_status"],
                    }), 409
            path = resolve_file_storage_path(storage_root, row)
            if not path.exists():
                return json_resp({"ok": False, "msg": "實體檔案不存在"}), 404
            mark_album_share_link_accessed(conn, share["id"])
            log_file_access(conn, file_id=row["id"], actor_user_id=None, action="album_share_download", result="allowed", reason="album_share_link", ip=get_client_ip(), user_agent=get_ua())
            conn.commit()
            inline = request.args.get("inline") == "1"
            response = _send_readable_file(row, as_attachment=not inline, download_name=row["display_name"] or row["original_filename_plain_for_public"] or "download.bin")
            if response is None:
                return json_resp({"ok": False, "msg": "實體檔案不存在"}), 404
            return response
        finally:
            conn.close()

