import base64
import mimetypes
import os
import re
import secrets
from datetime import datetime
from io import BytesIO
from urllib.parse import urlparse

from flask import request

from services.cloud_drive import attach_existing_file, ensure_cloud_drive_attachment_schema, store_cloud_upload
from services.comfyui_client import ComfyUIClient, ComfyUIError
from services.storage_albums import add_album_file, create_storage_file_entry, ensure_storage_album_schema


DEFAULT_COMFYUI_URL = os.environ.get("COMFYUI_API_URL", "http://localhost:8192")
DEFAULT_COMFYUI_PORT = 8192
SAFE_SAMPLER_FALLBACK = "euler"
SAFE_SCHEDULER_FALLBACK = "normal"
DEFAULT_GENERATION_TIMEOUT_SECONDS = 600
MAX_GENERATION_TIMEOUT_SECONDS = 1800
COMFYUI_BASIC_PRICE_ITEM_KEY = "comfyui_txt2img_basic"
COMFYUI_HOST_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")


class _MemoryFile:
    def __init__(self, data, filename, mimetype):
        self.stream = BytesIO(data)
        self.filename = filename
        self.mimetype = mimetype


def register_comfyui_routes(app, deps):
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_db = deps["get_db"]
    get_member_level_rule = deps["get_member_level_rule"]
    get_client_ip = deps.get("get_client_ip", lambda: "")
    get_ua = deps.get("get_ua", lambda: "")
    audit = deps.get("audit", lambda *args, **kwargs: None)
    json_resp = deps["json_resp"]
    require_csrf = deps.get("require_csrf", deps["require_csrf_safe"])
    require_csrf_safe = deps["require_csrf_safe"]
    storage_root = deps.get("STORAGE_DIR", ".")
    get_system_settings = deps.get("get_system_settings", lambda: {})
    injected_client = deps.get("comfyui_client")
    points_service = deps.get("points_service")

    def _actor_or_401():
        actor = get_current_user_ctx()
        if not actor:
            return None, json_resp({"ok": False, "msg": "請先登入"}, 401)
        settings = get_system_settings() or {}
        if settings.get("feature_comfyui_enabled") is False:
            return None, json_resp({"ok": False, "msg": "ComfyUI 產圖功能目前未啟用"}, 403)
        return actor, None

    def _actor_value(actor, key, default=None):
        if not actor:
            return default
        try:
            return actor[key]
        except Exception:
            return actor.get(key, default) if hasattr(actor, "get") else default

    def _root_or_403():
        actor, err = _actor_or_401()
        if err:
            return None, err
        if _actor_value(actor, "username") != "root":
            return None, json_resp({"ok": False, "msg": "只有 root 可執行此操作"}, 403)
        return actor, None

    def _validate_comfyui_host(value):
        host = str(value or "").strip().strip("[]")
        if not host:
            return None
        if len(host) > 253:
            return None
        forbidden = ("://", "/", "\\", "@", "?", "#", "%", " ")
        if any(part in host for part in forbidden):
            return None
        if not COMFYUI_HOST_RE.match(host):
            return None
        return host

    def _parse_comfyui_endpoint(data):
        default_url = urlparse(DEFAULT_COMFYUI_URL)
        host = _validate_comfyui_host(data.get("host") or data.get("comfyui_api_host") or default_url.hostname or "localhost")
        if host is None:
            return None, None, "ComfyUI Host / IP 必須是主機名稱或 IP，不可包含 http://、路徑、帳密或特殊字元"
        try:
            port = int(data.get("port") or data.get("comfyui_api_port") or default_url.port or DEFAULT_COMFYUI_PORT)
        except Exception:
            return None, None, "ComfyUI Port 必須是 1-65535"
        if port < 1 or port > 65535:
            return None, None, "ComfyUI Port 必須是 1-65535"
        display_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        return f"http://{display_host}:{port}", {"host": host, "port": port}, None

    def _configured_comfyui_url():
        settings = get_system_settings() or {}
        default_url = urlparse(DEFAULT_COMFYUI_URL)
        host = str(settings.get("comfyui_api_host") or default_url.hostname or os.environ.get("COMFYUI_API_HOST") or "localhost").strip()
        host = host.strip("[]")
        if not host:
            host = "localhost"
        try:
            port = int(settings.get("comfyui_api_port") or default_url.port or DEFAULT_COMFYUI_PORT)
        except Exception:
            port = DEFAULT_COMFYUI_PORT
        port = min(65535, max(1, port))
        display_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        return f"http://{display_host}:{port}"

    def _configured_max_batch_size():
        settings = get_system_settings() or {}
        return _int_range(settings.get("comfyui_max_batch_size"), 1, 1, 8)

    def _client():
        return injected_client or ComfyUIClient(_configured_comfyui_url())

    def _client_for_url(url):
        if injected_client is not None:
            return injected_client
        factory = deps.get("comfyui_client_factory")
        if factory:
            return factory(url)
        return ComfyUIClient(url)

    def _is_root(actor):
        return _actor_value(actor, "username") == "root"

    def _comfyui_charge_required(actor):
        return not _is_root(actor)

    def _comfyui_price_quote(quantity):
        if not points_service:
            return None, "積分服務未啟用，無法使用 ComfyUI 產圖"
        catalog = points_service.list_catalog()
        item = next((row for row in catalog if row.get("item_key") == COMFYUI_BASIC_PRICE_ITEM_KEY), None)
        if not item:
            return None, "ComfyUI 產圖收費項目未啟用"
        quantity = max(1, int(quantity or 1))
        unit_price = int(item.get("base_price") or 0)
        return {
            "item_key": COMFYUI_BASIC_PRICE_ITEM_KEY,
            "item_name": item.get("item_name") or "ComfyUI 基礎生圖一次",
            "unit_price": unit_price,
            "quantity": quantity,
            "total_price": unit_price * quantity,
            "currency_type": "points",
        }, None

    def _ensure_comfyui_balance(actor, quote):
        if not quote or not points_service:
            return None
        wallet = points_service.get_wallet(_actor_value(actor, "id"))
        balance = int((wallet or {}).get("points_balance") or 0)
        if balance < int(quote.get("total_price") or 0):
            return f"積分不足：本次產圖需要 {quote['total_price']} 點，目前餘額 {balance} 點"
        return None

    def _charge_comfyui_generation(actor, quote, *, prompt_id):
        if not quote or not points_service:
            return None
        result = points_service.spend_points(
            user_id=_actor_value(actor, "id"),
            item_key=quote["item_key"],
            quantity=quote["quantity"],
            reference_type="comfyui_generation",
            reference_id=str(prompt_id or ""),
            idempotency_key=f"comfyui_generation:{_actor_value(actor, 'id')}:{prompt_id or secrets.token_hex(8)}",
            metadata={
                "charged_after_success": True,
                "unit_price": quote["unit_price"],
                "quantity": quote["quantity"],
                "total_price": quote["total_price"],
            },
            actor=actor,
        )
        return {
            "charged": True,
            "item_key": quote["item_key"],
            "unit_price": quote["unit_price"],
            "quantity": quote["quantity"],
            "total_price": quote["total_price"],
            "ledger_uuid": (result.get("ledger") or {}).get("ledger_uuid"),
            "wallet": result.get("wallet"),
        }

    def _json_error_from_comfy(exc, active_client=None):
        active_client = active_client or _client()
        return json_resp({"ok": False, "msg": str(exc), "comfyui_url": getattr(active_client, "base_url", _configured_comfyui_url())}), 503

    def _comfyui_unavailable_payload(exc, active_client=None):
        active_client = active_client or _client()
        return {
            "ok": True,
            "available": False,
            "msg": str(exc),
            "comfyui_url": getattr(active_client, "base_url", _configured_comfyui_url()),
        }

    def _int_range(value, default, minimum, maximum, *, multiple_of=None):
        try:
            number = int(value)
        except Exception:
            number = default
        number = max(minimum, min(maximum, number))
        if multiple_of:
            number = max(minimum, (number // multiple_of) * multiple_of)
        return number

    def _float_range(value, default, minimum, maximum):
        try:
            number = float(value)
        except Exception:
            number = default
        return max(minimum, min(maximum, number))

    def _clean_filename(name, fallback="comfyui.png"):
        text = str(name or "").strip()
        text = text.split("/")[-1].split("\\")[-1]
        text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
        if not text:
            text = fallback
        if "." not in text:
            text += ".png"
        return text[:120]

    def _normalize_generation_payload(data):
        prompt = str(data.get("prompt") or "").strip()
        if not prompt:
            return None, "請輸入提示詞"
        if len(prompt) > 3000:
            return None, "提示詞最多 3000 字"
        negative = str(data.get("negative_prompt") or "").strip()
        if len(negative) > 3000:
            return None, "負面提示詞最多 3000 字"
        model = str(data.get("model") or "").strip()
        if not model:
            return None, "請選擇模型"
        seed = _int_range(data.get("seed"), secrets.randbits(32), 0, 2**63 - 1)
        params = {
            "model": model,
            "prompt": prompt,
            "negative_prompt": negative,
            "width": _int_range(data.get("width"), 512, 64, 2048, multiple_of=8),
            "height": _int_range(data.get("height"), 512, 64, 2048, multiple_of=8),
            "steps": _int_range(data.get("steps"), 20, 1, 80),
            "cfg": _float_range(data.get("cfg"), 7.0, 1.0, 30.0),
            "sampler_name": str(data.get("sampler_name") or SAFE_SAMPLER_FALLBACK).strip() or SAFE_SAMPLER_FALLBACK,
            "scheduler": str(data.get("scheduler") or SAFE_SCHEDULER_FALLBACK).strip() or SAFE_SCHEDULER_FALLBACK,
            "seed": seed,
            "batch_size": _int_range(data.get("batch_size"), 1, 1, _configured_max_batch_size()),
            "filename_prefix": _clean_filename(data.get("filename_prefix") or "hackme_web", fallback="hackme_web").rsplit(".", 1)[0],
        }
        return params, None

    def _safe_text(value, limit):
        text = str(value or "").strip()
        text = re.sub(r"\r\n?", "\n", text)
        return text[:limit]

    def _ensure_comfyui_share_schema(conn):
        now = None
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS forum_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                sort_order INTEGER NOT NULL DEFAULT 100,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS forum_boards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER REFERENCES forum_categories(id) ON DELETE SET NULL,
                slug TEXT UNIQUE,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                rules TEXT,
                visibility TEXT NOT NULL DEFAULT 'public',
                sort_order INTEGER NOT NULL DEFAULT 100,
                is_active INTEGER NOT NULL DEFAULT 1,
                last_activity_at TEXT,
                owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                owner_username TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'approved',
                review_note TEXT,
                reviewed_by TEXT,
                reviewed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS forum_threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL REFERENCES forum_boards(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'approved',
                review_note TEXT,
                reviewed_by TEXT,
                reviewed_at TEXT,
                post_type TEXT NOT NULL DEFAULT 'normal',
                is_sticky INTEGER NOT NULL DEFAULT 0,
                is_locked INTEGER NOT NULL DEFAULT 0,
                is_curated INTEGER NOT NULL DEFAULT 0,
                view_count INTEGER NOT NULL DEFAULT 0,
                edited_at TEXT,
                edited_by TEXT,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                deleted_at TEXT,
                deleted_by TEXT,
                delete_reason TEXT,
                author_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                author_username TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        return now

    def _find_or_create_comfyui_board(conn, actor):
        _ensure_comfyui_share_schema(conn)
        row = conn.execute(
            """
            SELECT id, title FROM forum_boards
            WHERE is_active=1 AND status='approved' AND (title='ComfyUI專區' OR title LIKE '%ComfyUI%')
            ORDER BY CASE WHEN title='ComfyUI專區' THEN 0 ELSE 1 END, sort_order ASC, id ASC
            LIMIT 1
            """
        ).fetchone()
        if row:
            return dict(row)
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO forum_categories (name, description, sort_order, is_active, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)",
            ("交流討論", "預設討論分類", 10, now, now),
        )
        category = conn.execute("SELECT id FROM forum_categories WHERE name=?", ("交流討論",)).fetchone()
        cur = conn.execute(
            """
            INSERT INTO forum_boards (
                category_id, slug, title, description, rules, visibility, sort_order, is_active,
                last_activity_at, owner_user_id, owner_username, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'public', 30, 1, ?, ?, ?, 'approved', ?, ?)
            """,
            (
                category["id"] if category else None,
                "comfyui",
                "ComfyUI專區",
                "ComfyUI 工作流、模型、節點與生成參數交流。",
                "分享工作流時請標註來源與使用限制。",
                now,
                int(_actor_value(actor, "id")),
                _actor_value(actor, "username", "system"),
                now,
                now,
            ),
        )
        return {"id": cur.lastrowid, "title": "ComfyUI專區"}

    def _maybe_add_to_album(conn, *, actor, album_id, storage_file_id, file_id, caption=""):
        normalized_album_id = str(album_id or "").strip()
        if not normalized_album_id:
            return None, None
        album, msg = add_album_file(
            conn,
            actor=actor,
            album_id=normalized_album_id,
            storage_file_id=storage_file_id,
            file_id=file_id,
            caption=caption,
        )
        if msg and msg != "檔案已在相簿內":
            return None, msg
        if album is None:
            album = {"id": normalized_album_id, "already_exists": True}
        return album, None

    def _save_fetched_image(conn, *, actor, data, image):
        filename = _clean_filename(data.get("display_name") or image.filename)
        guessed_mime = mimetypes.guess_type(filename)[0] or image.mime_type or "image/png"
        memory_file = _MemoryFile(image.data, filename, guessed_mime)
        ensure_cloud_drive_attachment_schema(conn)
        ensure_storage_album_schema(conn)
        rule = get_member_level_rule(conn, _actor_value(actor, "effective_level") or _actor_value(actor, "member_level"))
        upload_result, msg = store_cloud_upload(
            conn,
            actor=actor,
            member_rule=rule,
            storage_root=storage_root,
            file_storage=memory_file,
            privacy_mode="private_scannable",
            scan_now=True,
        )
        if msg:
            return None, None, None, msg
        file_row = conn.execute("SELECT * FROM uploaded_files WHERE id=?", (upload_result["file_id"],)).fetchone()
        virtual_path = str(data.get("virtual_path") or "").strip()
        if not virtual_path:
            virtual_path = f"/ComfyUI/{filename}"
        storage_file, msg = create_storage_file_entry(
            conn,
            actor=actor,
            file_row=file_row,
            virtual_path=virtual_path,
            display_name=filename,
            source="comfyui",
        )
        if msg:
            return None, None, None, msg
        album, msg = _maybe_add_to_album(
            conn,
            actor=actor,
            album_id=data.get("album_id"),
            storage_file_id=storage_file["id"],
            file_id=upload_result["file_id"],
            caption="ComfyUI 產圖",
        )
        if msg:
            return None, None, None, msg
        return upload_result, storage_file, album, None

    def _existing_saved_image(conn, *, actor, data):
        file_id = str(data.get("file_id") or data.get("saved_file_id") or "").strip()
        if not file_id:
            return None
        ensure_cloud_drive_attachment_schema(conn)
        ensure_storage_album_schema(conn)
        file_row = conn.execute("SELECT * FROM uploaded_files WHERE id=? AND deleted_at IS NULL", (file_id,)).fetchone()
        if not file_row or int(file_row["owner_user_id"]) != int(_actor_value(actor, "id")):
            return None
        storage_file_id = str(data.get("storage_file_id") or "").strip()
        params = [file_id, int(_actor_value(actor, "id"))]
        where = "file_id=? AND owner_user_id=? AND deleted_at IS NULL AND COALESCE(is_trashed, 0)=0"
        if storage_file_id:
            where += " AND id=?"
            params.append(storage_file_id)
        storage_row = conn.execute(
            f"SELECT * FROM storage_files WHERE {where} ORDER BY updated_at DESC, created_at DESC LIMIT 1",
            tuple(params),
        ).fetchone()
        upload_result = {"file_id": file_id}
        storage_file = dict(storage_row) if storage_row else None
        album, msg = _maybe_add_to_album(
            conn,
            actor=actor,
            album_id=data.get("album_id"),
            storage_file_id=storage_file["id"] if storage_file else None,
            file_id=file_id,
            caption="ComfyUI 產圖",
        )
        if msg:
            return upload_result, storage_file, album, msg
        return upload_result, storage_file, album, None

    def _compose_comfyui_share_content(data, *, file_id, storage_file):
        params = data.get("generation") if isinstance(data.get("generation"), dict) else {}
        note = _safe_text(data.get("note"), 900)
        prompt = _safe_text(params.get("prompt") or data.get("prompt"), 1400)
        negative = _safe_text(params.get("negative_prompt") or data.get("negative_prompt"), 700)
        model = _safe_text(params.get("model"), 180)
        sampler = _safe_text(params.get("sampler_name"), 80)
        scheduler = _safe_text(params.get("scheduler"), 80)
        size = f"{params.get('width') or '-'} x {params.get('height') or '-'}"
        lines = []
        if note:
            lines.extend(["心得", note, ""])
        lines.extend([
            f"[[comfyui-image:{file_id}]]",
            f"圖片檔案：{_safe_text((storage_file or {}).get('display_name') or (storage_file or {}).get('virtual_path') or file_id, 160)}",
            "",
            "提示詞",
            prompt or "-",
            "",
            "負面提示詞",
            negative or "-",
            "",
            "產圖參數",
            f"模型：{model or '-'}",
            f"尺寸：{size}",
            f"步數：{params.get('steps') or '-'}",
            f"CFG：{params.get('cfg') or '-'}",
            f"張數：{params.get('batch_size') or 1}",
            f"Seed：{params.get('seed') if params.get('seed') is not None else '-'}",
            f"Sampler：{sampler or '-'}",
            f"Scheduler：{scheduler or '-'}",
        ])
        return "\n".join(lines)[:3900]

    @app.route("/api/comfyui/status", methods=["GET"])
    @require_csrf_safe
    def comfyui_status():
        actor, err = _actor_or_401()
        if err:
            return err
        active_client = _client()
        try:
            if hasattr(active_client, "health_check"):
                status = active_client.health_check(timeout=3)
            else:
                active_client.get_models()
                status = {"ok": True}
        except ComfyUIError as exc:
            return json_resp(_comfyui_unavailable_payload(exc, active_client))
        return json_resp({
            "ok": True,
            "available": True,
            "comfyui_url": getattr(active_client, "base_url", _configured_comfyui_url()),
            "max_batch_size": _configured_max_batch_size(),
            "billing": None if not _comfyui_charge_required(actor) else (_comfyui_price_quote(1)[0] or {}),
            "system": status.get("system") if isinstance(status, dict) else {},
        })

    @app.route("/api/root/comfyui/test-connection", methods=["POST"])
    @require_csrf
    def root_comfyui_test_connection():
        actor, err = _root_or_403()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "Invalid request"}), 400
        url, endpoint, msg = _parse_comfyui_endpoint(data)
        if msg:
            return json_resp({"ok": False, "msg": msg}), 400
        active_client = _client_for_url(url)
        try:
            status = active_client.health_check(timeout=3) if hasattr(active_client, "health_check") else {"ok": True}
            audit(
                "COMFYUI_CONNECTION_TEST",
                get_client_ip(),
                user=_actor_value(actor, "username"),
                success=True,
                ua=get_ua(),
                detail=f"url={url}",
            )
            return json_resp({
                "ok": True,
                "available": True,
                "comfyui_url": getattr(active_client, "base_url", url),
                "endpoint": endpoint,
                "system": status.get("system") if isinstance(status, dict) else {},
            })
        except ComfyUIError as exc:
            audit(
                "COMFYUI_CONNECTION_TEST",
                get_client_ip(),
                user=_actor_value(actor, "username"),
                success=False,
                ua=get_ua(),
                detail=f"url={url}, error={exc}",
            )
            return json_resp({
                "ok": True,
                "available": False,
                "msg": str(exc),
                "comfyui_url": getattr(active_client, "base_url", url),
                "endpoint": endpoint,
            })

    @app.route("/api/comfyui/models", methods=["GET"])
    @require_csrf_safe
    def comfyui_models():
        actor, err = _actor_or_401()
        if err:
            return err
        active_client = _client()
        try:
            models = active_client.get_models()
            options = active_client.get_sampler_options()
        except ComfyUIError as exc:
            return _json_error_from_comfy(exc, active_client)
        return json_resp({
            "ok": True,
            "models": models,
            "samplers": options.get("samplers") or [SAFE_SAMPLER_FALLBACK],
            "schedulers": options.get("schedulers") or [SAFE_SCHEDULER_FALLBACK],
            "comfyui_url": getattr(active_client, "base_url", _configured_comfyui_url()),
            "max_batch_size": _configured_max_batch_size(),
            "billing": None if not _comfyui_charge_required(actor) else (_comfyui_price_quote(1)[0] or {}),
        })

    @app.route("/api/comfyui/generate", methods=["POST"])
    @require_csrf
    def comfyui_generate():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        params, msg = _normalize_generation_payload(data if isinstance(data, dict) else {})
        if msg:
            return json_resp({"ok": False, "msg": msg}), 400
        quote = None
        if _comfyui_charge_required(actor):
            quote, msg = _comfyui_price_quote(params["batch_size"])
            if msg:
                return json_resp({"ok": False, "msg": msg}), 503
            msg = _ensure_comfyui_balance(actor, quote)
            if msg:
                return json_resp({"ok": False, "msg": msg}), 409
            if data.get("confirm_billing") is not True:
                return json_resp({
                    "ok": False,
                    "msg": (
                        f"請先確認扣點：本次成功產圖將扣 {quote['total_price']} 點；"
                        "產圖失敗不扣點，丟棄預覽不退款。"
                    ),
                    "billing": {**quote, "confirmation_required": True},
                }), 409
        active_client = _client()
        try:
            result = active_client.generate_image(
                params,
                timeout_seconds=_int_range(
                    data.get("timeout_seconds"),
                    DEFAULT_GENERATION_TIMEOUT_SECONDS,
                    30,
                    MAX_GENERATION_TIMEOUT_SECONDS,
                ),
            )
        except ComfyUIError as exc:
            audit("COMFYUI_GENERATE_ERROR", get_client_ip(), user=actor["username"], success=False, ua=get_ua(), detail=str(exc)[:180])
            return _json_error_from_comfy(exc, active_client)
        billing = {"charged": False, "exempt": "root"} if not quote else None
        if quote:
            try:
                billing = _charge_comfyui_generation(actor, quote, prompt_id=result.get("prompt_id"))
            except Exception as exc:
                audit("COMFYUI_BILLING_ERROR", get_client_ip(), user=actor["username"], success=False, ua=get_ua(), detail=str(exc)[:180])
                return json_resp({"ok": False, "msg": f"產圖成功，但扣款失敗：{exc}"}), 409
        result_images = result.get("images") if isinstance(result.get("images"), list) else []
        if not result_images:
            result_images = [{
                "image_ref": result["image_ref"],
                "mime_type": result["mime_type"],
                "data": result["data"],
            }]
        images = []
        for index, item in enumerate(result_images):
            raw_data = item.get("data") or b""
            mime_type = item.get("mime_type") or result.get("mime_type") or "image/png"
            image_ref_item = item.get("image_ref") if isinstance(item.get("image_ref"), dict) else result["image_ref"]
            images.append({
                "prompt_id": result["prompt_id"],
                "image_ref": image_ref_item,
                "mime_type": mime_type,
                "size_bytes": len(raw_data),
                "data_url": f"data:{mime_type};base64,{base64.b64encode(raw_data).decode('ascii')}",
                "seed": params["seed"],
                "model": params["model"],
                "batch_size": params["batch_size"],
                "batch_index": index,
            })
        image = images[0]
        image_ref = result["image_ref"]
        audit("COMFYUI_GENERATE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"prompt_id={result['prompt_id']}, file={image_ref.get('filename')}, batch={len(images)}")
        return json_resp({
            "ok": True,
            "image": image,
            "images": images,
            "billing": billing,
        })

    @app.route("/api/comfyui/interrupt", methods=["POST"])
    @require_csrf
    def comfyui_interrupt():
        actor, err = _actor_or_401()
        if err:
            return err
        active_client = _client()
        try:
            if not hasattr(active_client, "interrupt"):
                return json_resp({"ok": False, "msg": "ComfyUI 中斷產圖不支援"}), 501
            result = active_client.interrupt()
        except ComfyUIError as exc:
            audit("COMFYUI_INTERRUPT_ERROR", get_client_ip(), user=actor["username"], success=False, ua=get_ua(), detail=str(exc)[:180])
            return _json_error_from_comfy(exc, active_client)
        audit("COMFYUI_INTERRUPT", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail="interrupt requested")
        return json_resp({"ok": True, "msg": "已送出中斷產圖請求", "interrupt": result if isinstance(result, dict) else {}})

    @app.route("/api/comfyui/save", methods=["POST"])
    @require_csrf
    def comfyui_save():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        data = data if isinstance(data, dict) else {}
        image_ref = data.get("image_ref")
        if not isinstance(image_ref, dict):
            return json_resp({"ok": False, "msg": "缺少 image_ref"}), 400
        active_client = _client()
        try:
            image = active_client.fetch_image(image_ref)
        except ComfyUIError as exc:
            return _json_error_from_comfy(exc, active_client)
        conn = get_db()
        try:
            upload_result, storage_file, album, msg = _save_fetched_image(conn, actor=actor, data=data, image=image)
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("COMFYUI_SAVE_TO_DRIVE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"file_id={upload_result['file_id']}, storage_file_id={storage_file['id']}")
            return json_resp({"ok": True, "file": upload_result, "storage_file": storage_file, "album": album})
        finally:
            conn.close()

    @app.route("/api/comfyui/discard", methods=["POST"])
    @require_csrf
    def comfyui_discard():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        data = data if isinstance(data, dict) else {}
        image_ref = data.get("image_ref")
        if not isinstance(image_ref, dict):
            return json_resp({"ok": False, "msg": "缺少 image_ref"}), 400
        active_client = _client()
        try:
            if not hasattr(active_client, "discard_image"):
                return json_resp({"ok": False, "msg": "ComfyUI 原始檔刪除不支援"}), 501
            result = active_client.discard_image(image_ref, prompt_id=data.get("prompt_id"))
        except ComfyUIError as exc:
            audit("COMFYUI_DISCARD_ERROR", get_client_ip(), user=actor["username"], success=False, ua=get_ua(), detail=str(exc)[:180])
            return _json_error_from_comfy(exc, active_client)
        if not (result.get("file_deleted") or result.get("file_missing")):
            msg = "已丟棄前端預覽；ComfyUI 未提供刪除 output 檔案端點，原始檔可能仍留在 ComfyUI output。若要同步刪原檔，請設定 COMFYUI_OUTPUT_DIR 或 COMFYUI_BASE_DIR。"
            audit("COMFYUI_DISCARD_UNSUPPORTED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=str(result)[:180])
            return json_resp({"ok": True, "msg": msg, "discard": result, "warning": "source_file_not_deleted"})
        audit("COMFYUI_DISCARD", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"file={image_ref.get('filename')}, result={result}")
        return json_resp({"ok": True, "msg": "已丟棄預覽並刪除 ComfyUI 原始檔", "discard": result})

    @app.route("/api/comfyui/share", methods=["POST"])
    @require_csrf
    def comfyui_share():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        data = data if isinstance(data, dict) else {}
        image_ref = data.get("image_ref")
        conn = get_db()
        try:
            existing = _existing_saved_image(conn, actor=actor, data=data)
            if existing:
                upload_result, storage_file, album, msg = existing
                if msg:
                    conn.rollback()
                    return json_resp({"ok": False, "msg": msg}), 400
            else:
                if not isinstance(image_ref, dict):
                    return json_resp({"ok": False, "msg": "缺少 image_ref"}), 400
                active_client = _client()
                try:
                    image = active_client.fetch_image(image_ref)
                except ComfyUIError as exc:
                    return _json_error_from_comfy(exc, active_client)
                upload_result, storage_file, album, msg = _save_fetched_image(conn, actor=actor, data=data, image=image)
                if msg:
                    conn.rollback()
                    return json_resp({"ok": False, "msg": msg}), 400
            board = _find_or_create_comfyui_board(conn, actor)
            title = _safe_text(data.get("title"), 120) or "ComfyUI 產圖分享"
            content = _compose_comfyui_share_content(
                data,
                file_id=upload_result["file_id"],
                storage_file=storage_file or {},
            )
            if not content.strip():
                conn.rollback()
                return json_resp({"ok": False, "msg": "分享內容不可為空"}), 400
            level = _actor_value(actor, "effective_level") or _actor_value(actor, "base_level") or _actor_value(actor, "member_level") or "normal"
            role = _actor_value(actor, "role", "user")
            status = "pending" if role == "user" and level == "newbie" else "approved"
            now = datetime.now().isoformat()
            cur = conn.execute(
                """
                INSERT INTO forum_threads (
                    board_id, title, content, status, post_type, author_user_id,
                    author_username, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'normal', ?, ?, ?, ?)
                """,
                (board["id"], title, content, status, int(_actor_value(actor, "id")), _actor_value(actor, "username"), now, now),
            )
            thread_id = cur.lastrowid
            conn.execute("UPDATE forum_boards SET last_activity_at=?, updated_at=? WHERE id=?", (now, now, board["id"]))
            attached, msg = attach_existing_file(
                conn,
                actor=actor,
                file_id=upload_result["file_id"],
                context_type="forum_thread",
                context_id=thread_id,
                grant_role="user",
                can_preview=True,
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit(
                "COMFYUI_SHARE_TO_COMMUNITY",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"thread_id={thread_id}, file_id={upload_result['file_id']}, board_id={board['id']}",
            )
            return json_resp({
                "ok": True,
                "msg": "已分享到 ComfyUI 專區" if status == "approved" else "已送出分享，待審核後公開",
                "thread": {"id": thread_id, "board_id": board["id"], "title": title, "status": status},
                "file": upload_result,
                "storage_file": storage_file,
                "album": album,
                "attachment": attached,
            })
        finally:
            conn.close()
